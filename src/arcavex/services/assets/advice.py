"""ARC-AST-020: an image node whose asset is mostly transparent padding for its fit mode.

Raised at compile time, alongside the asset-existence check, so `validate` reports it and every
render surface inherits it without a per-caller check.
"""

from __future__ import annotations

from pathlib import Path

from arcavex.kernel.diagnostics import Diagnostic, diagnostic
from arcavex.services.assets.alpha import COVERAGE_WARN_BELOW, OpaqueBox, opaque_box

# Measuring alpha decodes the image, which is far more expensive than the check. A template
# compiles once per format x locale target and again on every watch-mode edit. The key includes
# mtime and size so an edited asset is re-measured.
_CACHE: dict[tuple[str, int, int], OpaqueBox | None] = {}


def _measure(path: Path) -> OpaqueBox | None:
    try:
        stat = path.stat()
    except OSError:  # pragma: no cover - the compiler checks existence first
        return None
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if key not in _CACHE:
        _CACHE[key] = opaque_box(path)
    return _CACHE[key]


def padding_warning(
    asset_path: Path,
    *,
    node_id: str,
    fit: str,
    file: str | None = None,
    keypath: str | None = None,
    line: int | None = None,
) -> Diagnostic | None:
    """Return an ``ARC-AST-020`` if this image is mostly padding for its fit mode, else ``None``.

    Only `contain` and `cover` are checked. `fill` stretches the canvas to the box without
    preserving aspect, so padding distorts the artwork rather than shrinking it.
    """
    if fit not in ("contain", "cover"):
        return None
    box = _measure(asset_path)
    if box is None or box.coverage >= COVERAGE_WARN_BELOW:
        return None
    return diagnostic(
        "ARC-AST-020",
        f"Asset {asset_path.name!r} on node {node_id!r} is "
        f"{box.canvas_width}x{box.canvas_height} but its opaque content is only "
        f"{box.width}x{box.height} ({box.coverage:.0%} of the canvas); "
        f"'fit: {fit}' scales the transparent padding, not the artwork",
        severity="warning",
        file=file,
        keypath=keypath,
        line=line,
        hint=(
            "Trim the asset to its alpha bounding box so the artwork fills the canvas it "
            "declares. The render follows 'fit' correctly; the artwork will appear smaller "
            "than the box implies."
        ),
    )
