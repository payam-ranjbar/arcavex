"""Reference poster (task §9-§10): all 10 format x locale combos render, stay collision-free.

The flagship IPEN reproduction ships as a split template (schema/formats/locales/preview-data
sidecars) with per-locale data files. These tests pin the acceptance contract: every combo
compiles and renders exit-0, layout inspect reports no text overflow and no collisions among
the CONTENT boxes, and rendering is deterministic. Decorative underlays (background, the two
guest-band shapes, the band-riding heading) legitimately overlap content by design — the
rotated accent's axis-aligned bounding box especially — so the collision rule covers exactly
the content pairs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arcavex.bootstrap import build_facade
from arcavex.kernel.diagnostics import has_errors

_REPO = Path(__file__).resolve().parents[2]
_DIR = _REPO / "examples" / "reference-poster"
_TEMPLATE = _DIR / "template.yaml"

_FORMATS = ("portrait", "square", "story", "landscape", "a4")
_LOCALES = ("en", "fa")
_TARGETS = [(f, loc) for f in _FORMATS for loc in _LOCALES]

# Content boxes that must never collide with one another (or with the hero / guest row).
# The heading and band shapes are deliberately absent: the heading rides the band's diagonal
# and the rotated accent's AABB crosses content that visually clears it (verified by eye and
# by the accent's rotated-edge geometry during authoring).
_STRICT = {
    "logo",
    "org-caption",
    "headline",
    "subtitle",
    "date-value",
    "venue-box",
    "hero",
    "guests-row",
}


def _data(locale: str) -> Path:
    return _DIR / "data" / f"poster.{locale}.yaml"


def _walk(node) -> list:
    out = [node]
    for child in node.children:
        out.extend(_walk(child))
    return out


@pytest.mark.parametrize(("fmt", "locale"), _TARGETS)
def test_reference_poster_renders_all_combos(tmp_path: Path, fmt: str, locale: str) -> None:
    facade = build_facade()
    out = tmp_path / f"poster.{fmt}.{locale}.png"
    result = facade.render_file(_TEMPLATE, _data(locale), fmt, locale, output=out)
    assert result.ok, result.diagnostics
    assert out.is_file() and out.stat().st_size > 0
    assert not has_errors(result.diagnostics)


@pytest.mark.parametrize(("fmt", "locale"), _TARGETS)
def test_reference_poster_layout_is_clean(fmt: str, locale: str) -> None:
    report = build_facade().inspect_layout(_TEMPLATE, _data(locale), fmt, locale)
    assert report.ok, report.diagnostics

    # No text node lost content. Kind "none" is measurement info (every measured text node
    # carries a report) and "shrunk" is shrink_to_fit succeeding; loss is any other kind
    # (clip/truncate) or a measured extent genuinely beyond the box.
    overflowing = [
        n.id
        for n in _walk(report.root)
        if n.overflow is not None
        and (
            n.overflow.kind not in ("none", "shrunk")
            or n.overflow.measured_h_pt > n.overflow.box_h_pt + 0.5
            or n.overflow.measured_w_pt > n.overflow.box_w_pt + 0.5
        )
    ]
    assert not overflowing, f"{fmt}/{locale}: text overflow on {overflowing}"

    # No collisions among the content boxes (see _STRICT for the deliberate exclusions).
    bad = [
        (ov.a, ov.b)
        for ov in report.overlaps
        if ov.a.split("[")[0] in _STRICT and ov.b.split("[")[0] in _STRICT
    ]
    assert not bad, f"{fmt}/{locale}: content collisions {bad}"


def test_reference_poster_fa_portrait_is_deterministic(tmp_path: Path) -> None:
    facade = build_facade()
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    r1 = facade.render_file(_TEMPLATE, _data("fa"), "portrait", "fa", output=a)
    r2 = facade.render_file(_TEMPLATE, _data("fa"), "portrait", "fa", output=b)
    assert r1.ok and r2.ok
    assert a.read_bytes() == b.read_bytes()
    assert r1.content_sha256 == r2.content_sha256


def test_reference_poster_renders_from_preview_data(tmp_path: Path) -> None:
    # The template must stand alone: no --data means preview-data.yaml drives the render.
    facade = build_facade()
    out = tmp_path / "preview.png"
    result = facade.render_file(_TEMPLATE, None, "portrait", None, output=out)
    assert result.ok, result.diagnostics
    assert result.inferred.get("data") == "preview_data"
    assert out.stat().st_size > 0
