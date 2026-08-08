"""Derived-asset cache tests (spec §4.7): cold==warm identity, hit/miss, and LRU eviction.

The cache is an accelerator, never authoritative: a cold cache must produce byte-identical output
to a warm one, and it must evict least-recently-used variants under its byte budget. It also must
decline small images so it never changes an ordinary render's pixels.
"""

from __future__ import annotations

from pathlib import Path

import skia

from arcavex.bootstrap import build_facade
from arcavex.services.cache import DerivedImageCache

_IMAGE_TEMPLATE = """\
version: 0.1.0
formats:
  square:
    canvas: {width: 200px, height: 200px, dpi: 72}
root:
  type: group
  id: root
  children:
    - id: photo
      type: image
      asset: big.png
      fit: cover
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: fill, h: fill}
"""


def _write_image(path: Path, w: int, h: int) -> Path:
    surface = skia.Surface(w, h)
    canvas = surface.getCanvas()
    canvas.clear(skia.Color4f(0.1, 0.4, 0.9, 1.0))
    paint = skia.Paint()
    paint.setColor(skia.ColorRED)
    canvas.drawRect(skia.Rect.MakeXYWH(w * 0.1, h * 0.1, w * 0.5, h * 0.4), paint)
    data = surface.makeImageSnapshot().encodeToData(skia.EncodedImageFormat.kPNG, 100)
    path.write_bytes(bytes(data))
    return path


def _encode(image: object) -> bytes:
    return bytes(image.encodeToData(skia.EncodedImageFormat.kPNG, 100))  # type: ignore[attr-defined]


def _pixels(image: object) -> object:
    """Return the variant's raw pixel array — what a render actually draws (cold==warm anchor)."""
    # Explicit colorType: the default is the platform's native surface order.
    return image.toarray(colorType=skia.kRGBA_8888_ColorType)  # type: ignore[attr-defined]


def test_variant_miss_then_hit(tmp_path: Path) -> None:
    source = _write_image(tmp_path / "big.png", 2500, 2000)  # 5 MP, triggers the cache
    cache = DerivedImageCache(root=tmp_path / "cache", byte_budget=64_000_000)

    first = cache.variant(source, 400, 320)
    assert first is not None
    assert (first.width(), first.height()) == (400, 320)
    assert cache.stats()["misses"] == 1

    second = cache.variant(source, 400, 320)
    assert second is not None
    assert cache.stats()["hits"] == 1  # served from memory, no re-decode


def test_small_image_is_declined(tmp_path: Path) -> None:
    """A small source keeps its direct-decode path so existing renders are unchanged."""
    source = _write_image(tmp_path / "small.png", 512, 512)
    cache = DerivedImageCache(root=tmp_path / "cache")
    assert cache.variant(source, 128, 128) is None


def test_upscale_is_declined(tmp_path: Path) -> None:
    source = _write_image(tmp_path / "big.png", 2500, 2000)
    cache = DerivedImageCache(root=tmp_path / "cache")
    assert cache.variant(source, 3000, 2400) is None


def test_cold_cache_produces_identical_bytes(tmp_path: Path) -> None:
    """Two independent cold caches downscale a source to byte-identical variants (determinism)."""
    source = _write_image(tmp_path / "big.png", 2500, 2000)
    warm = DerivedImageCache(root=tmp_path / "a", byte_budget=64_000_000)
    cold = DerivedImageCache(root=tmp_path / "b", byte_budget=64_000_000)
    warm_px = _pixels(warm.variant(source, 400, 320))
    cold_px = _pixels(cold.variant(source, 400, 320))
    assert (warm_px == cold_px).all()


def test_disk_tier_is_reused_by_a_fresh_instance(tmp_path: Path) -> None:
    """A new cache over the same directory serves the variant from disk (a hit, no rebuild)."""
    source = _write_image(tmp_path / "big.png", 2500, 2000)
    root = tmp_path / "cache"
    first = DerivedImageCache(root=root, byte_budget=64_000_000)
    built = _pixels(first.variant(source, 400, 320))

    reopened = DerivedImageCache(root=root, byte_budget=64_000_000)
    served = reopened.variant(source, 400, 320)
    assert reopened.stats()["hits"] == 1
    assert reopened.stats()["misses"] == 0
    assert (_pixels(served) == built).all()


def test_lru_eviction_under_byte_budget(tmp_path: Path) -> None:
    """Distinct variants past the byte budget evict the least-recently-used entry."""
    source = _write_image(tmp_path / "big.png", 2500, 2000)
    # A single 400×320 RGBA variant is 512 000 bytes; a budget below two of them forces eviction.
    cache = DerivedImageCache(root=tmp_path / "cache", byte_budget=600_000)
    cache.variant(source, 400, 320)
    cache.variant(source, 401, 320)  # distinct key, pushes total over budget
    assert cache.stats()["evictions"] >= 1
    assert cache.stats()["entries"] == 1


def test_disk_tier_evicts_under_byte_budget(tmp_path: Path) -> None:
    """The persistent tier is byte-bounded too: distinct variants past the budget prune the
    oldest on-disk PNG by mtime, so ``$ARCAVEX_HOME/cache/derived/`` cannot grow unbounded (§4.7).
    """
    source = _write_image(tmp_path / "big.png", 2500, 2000)
    root = tmp_path / "cache"

    # Discover one variant's on-disk (PNG) size so the budget is set relative to it.
    probe = DerivedImageCache(root=root, byte_budget=64_000_000)
    probe.variant(source, 400, 320)
    one = next(root.rglob("*.png")).stat().st_size
    import shutil

    shutil.rmtree(root)

    # A budget holding ~2 variants; writing several distinct ones must evict the oldest on disk.
    budget = one * 2 + one // 2
    cache = DerivedImageCache(root=root, byte_budget=budget)
    for width in (400, 401, 402, 403, 404, 405):
        cache.variant(source, width, 320)

    assert cache.stats()["disk_evictions"] >= 1
    total = sum(path.stat().st_size for path in root.rglob("*.png"))
    assert total <= budget  # the disk tree is held under the byte budget


def test_render_is_identical_cold_vs_warm(tmp_path: Path, monkeypatch) -> None:
    """A large image renders byte-identically whether the derived cache is cold or warm (§4.7)."""
    def _render(home: Path) -> str:
        tpl_dir = home / "proj"
        tpl_dir.mkdir(parents=True, exist_ok=True)
        _write_image(tpl_dir / "big.png", 2500, 2500)
        (tpl_dir / "template.yaml").write_text(_IMAGE_TEMPLATE, encoding="utf-8")
        monkeypatch.setenv("ARCAVEX_HOME", str(home / "arcavex_home"))
        facade = build_facade()
        first = facade.render_file(
            tpl_dir / "template.yaml", format_name="square", output=home / "a.png"
        )
        assert first.ok, first.diagnostics
        # Second render reuses the now-warm cache; the output must be byte-identical.
        second = facade.render_file(
            tpl_dir / "template.yaml", format_name="square", output=home / "b.png"
        )
        assert first.content_sha256 == second.content_sha256
        return first.content_sha256

    cold_home_a = tmp_path / "run_a"
    cold_home_b = tmp_path / "run_b"
    # Two independent cold caches (different homes) must agree with each other and with warm.
    assert _render(cold_home_a) == _render(cold_home_b)
