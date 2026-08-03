"""Asset-shape advice: warnings about images that will render correctly but uselessly.

`ARC-AST-020` is the only diagnostic in the engine about what an image *contains* rather than
whether it can be read. It exists because of a failure the audit hit and could not have caught
any other way: a 512x512 logo whose artwork was a 452x114 band. `fit: contain` scaled the
canvas exactly as documented, the mark rendered as an unreadable smudge, and validation was
clean — the engine did as instructed and the output was wrong, with nothing to report.

It is raised at *compile* time, beside the asset-existence check, for one reason: that is the
only place every surface passes through. `validate` warns before a pixel is drawn, and render,
preview, project runs and the MCP tools inherit it without each having to remember to ask.

It is a warning, never an error. The measurement is objective (opaque area over canvas area),
the remedy is the author's, and the render still happens.
"""

from __future__ import annotations

from pathlib import Path

from arcavex.kernel.diagnostics import Diagnostic, diagnostic
from arcavex.services.assets.alpha import COVERAGE_WARN_BELOW, OpaqueBox, opaque_box

# Decoding to measure alpha is far more expensive than the check is worth repeating: a
# multi-format, multi-locale render compiles the same template once per target, and a watch
# loop recompiles on every keystroke. Keyed by the file's identity as the filesystem reports
# it, so an edited asset is re-measured rather than remembered wrongly.
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

    Only `contain` and `cover` are checked. `fill` stretches the canvas to the box with no
    aspect preservation, so padding distorts rather than shrinks the artwork — a different, and
    visible, problem this warning would only muddy.
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
            "declares. The render is not wrong — it is doing exactly what 'fit' asks — but the "
            "mark will appear far smaller than the box suggests."
        ),
    )
