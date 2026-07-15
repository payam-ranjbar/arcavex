"""LRU cache of downscaled image variants (spec §4.7).

A 40-megapixel photograph dropped into a 400-pixel slot should be decoded and downscaled once,
not on every render. This cache holds derived *variants* — an image resized to the pixel box it
will actually occupy — keyed by ``(content-hash, target-width, target-height)``. The content hash
in the key is what makes the cache safe: a variant is a pure, deterministic function of the source
bytes and the target size, so a **cold cache produces byte-identical output to a warm one** — the
cache is an accelerator, never authoritative (spec §4.7). Variants are held in an in-process LRU
bounded by a byte budget (approximate decoded size) and persisted as lossless PNGs under
``$ARCAVEX_HOME/cache/derived/`` so a later process reuses them; both tiers are disposable and
evicted least-recently-used when over budget.

The cache only engages for a genuine downscale (a large source into a much smaller slot); a small
image is decoded directly and left untouched, so it never changes the pixels of an existing
render. Downscaling uses a fixed Mitchell cubic resampler on the CPU, which is deterministic.
"""

from __future__ import annotations

import os
from collections import OrderedDict
from pathlib import Path

import skia  # type: ignore[import-untyped]

from arcavex.services.fsutil import atomic_write_bytes, home_dir, sha256_file

# Only cache a real downscale: the source must be large in absolute terms and clearly bigger than
# the slot, so ordinary logos/icons keep their existing direct-decode path untouched.
_MIN_SOURCE_PIXELS = 4_000_000
_MIN_DOWNSCALE_RATIO = 4.0
_DEFAULT_BUDGET_BYTES = 256_000_000
_MITCHELL = skia.SamplingOptions(skia.CubicResampler.Mitchell())


def cache_root() -> Path:
    """Return the derived-variant cache directory under the Arcavex home."""
    return home_dir() / "cache" / "derived"


class DerivedImageCache:
    """An LRU cache of downscaled image variants, memory-backed with a disk tier."""

    def __init__(self, root: Path | None = None, byte_budget: int = _DEFAULT_BUDGET_BYTES) -> None:
        """Bind the cache to its on-disk ``root`` and in-memory ``byte_budget``."""
        self._root = Path(root) if root is not None else cache_root()
        self._budget = max(1, byte_budget)
        self._mem: OrderedDict[str, object] = OrderedDict()
        self._mem_bytes = 0
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    def stats(self) -> dict[str, int]:
        """Return hit/miss/eviction counters and current memory footprint (for tests/doctor)."""
        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "mem_bytes": self._mem_bytes,
            "entries": len(self._mem),
        }

    def variant(self, path: Path, target_w: int, target_h: int) -> object | None:
        """Return a downscaled variant image for ``path`` at ``target_w×target_h``.

        Returns ``None`` when caching does not apply (a small source, or a slot not meaningfully
        smaller than the source), so the caller keeps its direct decode path and existing output.
        """
        path = Path(path)
        target_w, target_h = max(1, target_w), max(1, target_h)
        source = _decode(path)
        if source is None:
            return None
        sw, sh = source.width(), source.height()  # type: ignore[attr-defined]
        if not _should_downscale(sw, sh, target_w, target_h):
            return None

        key = f"{sha256_file(path)}_{target_w}x{target_h}"
        cached = self._mem.get(key)
        if cached is not None:
            self._mem.move_to_end(key)
            self.hits += 1
            return cached
        disk = self._read_disk(key)
        if disk is not None:
            self.hits += 1
            self._admit(key, disk)
            return disk

        self.misses += 1
        built = _downscale(source, target_w, target_h)
        self._write_disk(key, built)
        # Normalize the in-memory entry to the disk representation (decode the PNG we just wrote),
        # so a same-process memory hit and a fresh-process disk hit hold the identical image and
        # draw to identical pixels — cold and warm caches are byte-identical, not merely close.
        variant = self._read_disk(key) or built
        self._admit(key, variant)
        return variant

    # ------------------------------------------------------------------ internals
    def _admit(self, key: str, image: object) -> None:
        cost = _image_bytes(image)
        self._mem[key] = image
        self._mem.move_to_end(key)
        self._mem_bytes += cost
        while self._mem_bytes > self._budget and len(self._mem) > 1:
            _, evicted = self._mem.popitem(last=False)
            self._mem_bytes -= _image_bytes(evicted)
            self.evictions += 1

    def _disk_path(self, key: str) -> Path:
        return self._root / key[:2] / f"{key}.png"

    def _read_disk(self, key: str) -> object | None:
        target = self._disk_path(key)
        if not target.is_file():
            return None
        try:
            data = target.read_bytes()
            os.utime(target, None)  # touch for disk-LRU recency
            return skia.Image.MakeFromEncoded(skia.Data.MakeWithoutCopy(data))
        except (OSError, ValueError, RuntimeError):
            return None

    def _write_disk(self, key: str, image: object) -> None:
        encoded = image.encodeToData(skia.EncodedImageFormat.kPNG, 100)  # type: ignore[attr-defined]
        if encoded is None:
            return
        try:
            atomic_write_bytes(self._disk_path(key), bytes(encoded))
        except OSError:
            # The cache is disposable; a write failure must never fail a render.
            pass


def _decode(path: Path) -> object | None:
    try:
        return skia.Image.open(str(path))
    except (ValueError, RuntimeError):
        return None


def _should_downscale(sw: int, sh: int, tw: int, th: int) -> bool:
    if sw * sh < _MIN_SOURCE_PIXELS:
        return False
    if tw >= sw or th >= sh:
        return False
    return (sw * sh) / (tw * th) >= _MIN_DOWNSCALE_RATIO


def _downscale(source: object, target_w: int, target_h: int) -> object:
    surface = skia.Surface(target_w, target_h)
    canvas = surface.getCanvas()
    canvas.clear(skia.Color4f(0, 0, 0, 0))
    dst = skia.Rect.MakeWH(target_w, target_h)
    canvas.drawImageRect(source, dst, _MITCHELL)
    return surface.makeImageSnapshot()


def _image_bytes(image: object) -> int:
    return int(image.width()) * int(image.height()) * 4  # type: ignore[attr-defined]
