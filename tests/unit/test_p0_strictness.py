"""P0-1 strictness: an unknown field is a located error in *every* authoring scope.

Before this, strictness was the exception rather than the rule — it held only where a whitelist
constant happened to exist, so a plausible-sounding invented field (``condition:`` on a node was
the observed case) validated clean, did nothing, and left the author building on a false model.

These tests pin three things:

* every scope rejects an unknown key, with the right code, keypath, and source line;
* the guard test below walks the whole authoring surface, so a *new* permissive scope fails CI
  rather than shipping — the check that would have caught the original defect;
* the repo's own templates all still validate.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arcavex.bootstrap import build_facade
from arcavex.kernel.diagnostics import Diagnostic, SourceLocation
from arcavex.services.template.compiler import Compiler

_REPO_ROOT = Path(__file__).resolve().parents[2]

# A minimal but complete template. Each scope test injects one junk key into a copy of this, so
# the only difference between a passing and a failing compile is the invented field itself.
_BASE = """version: 0.1.0
variables:
  title: {type: string, required: false, default: hi}
  items: {type: list, required: false, default: [a]}
formats:
  square:
    canvas: {width: 400px, height: 400px, dpi: 72}
root:
  type: group
  id: root
  children:
    - id: body
      type: text
      text: hi
      style: {font_size: 12px}
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: fill, h: fit_content}
"""


def _compile(tmp_path: Path, text: str) -> tuple[list[Diagnostic], Path]:
    template = tmp_path / "t.yaml"
    template.write_text(text, encoding="utf-8")
    return list(Compiler().compile(template, None, "square", None, None).diagnostics), template


def _line_of(text: str, needle: str) -> int:
    """Return the 1-based line in ``text`` holding ``needle`` (the planted junk key)."""
    for i, line in enumerate(text.splitlines(), start=1):
        if needle in line:
            return i
    raise AssertionError(f"{needle!r} not found in template text")


def _one(diags: list[Diagnostic], code: str) -> Diagnostic:
    matching = [d for d in diags if d.code == code]
    assert matching, f"expected {code}, got {[(d.code, d.message) for d in diags]}"
    return matching[0]


def _loc(diag: Diagnostic) -> SourceLocation:
    assert diag.source is not None, f"{diag.code} is unlocated: {diag.message}"
    return diag.source


# --------------------------------------------------------------------------------- the 7 scopes
# Each entry plants one junk key and states the code and keypath it must produce. The junk key
# is unique per scope so its source line can be located unambiguously.
_SCOPES: list[tuple[str, str, str, str, str]] = [
    (
        "template root",
        "version: 0.1.0",
        "version: 0.1.0\nbogus_top_key: 1",
        "ARC-TPL-065",
        "bogus_top_key",
    ),
    (
        "formats.<name>",
        "  square:\n",
        "  square:\n    bogus_format_key: 1\n",
        "ARC-TPL-066",
        "formats.square.bogus_format_key",
    ),
    (
        "formats.<name>.canvas",
        "canvas: {width: 400px, height: 400px, dpi: 72}",
        "canvas: {width: 400px, height: 400px, dpi: 72, bogus_canvas_key: 1}",
        "ARC-TPL-066",
        "formats.square.canvas.bogus_canvas_key",
    ),
    (
        "variables.<name>",
        "title: {type: string, required: false, default: hi}",
        "title: {type: string, required: false, default: hi, bogus_var_key: 1}",
        "ARC-TPL-067",
        "variables.title.bogus_var_key",
    ),
    (
        "node top level",
        "      text: hi\n",
        "      text: hi\n      bogus_node_key: 1\n",
        "ARC-TPL-064",
        "root.children[0].bogus_node_key",
    ),
    (
        "effects[] entry",
        "      text: hi\n",
        "      text: hi\n      effects:\n        - {name: blur, bogus_effect_key: 1}\n",
        "ARC-TPL-068",
        "root.children[0].effects[0].bogus_effect_key",
    ),
    (
        "style sub-block",
        "style: {font_size: 12px}",
        "style: {font_size: 12px, bogus_style_key: 1}",
        "ARC-TPL-051",
        "root.children[0].style.bogus_style_key",
    ),
]


@pytest.mark.parametrize(
    ("scope", "old", "new", "code", "keypath"),
    _SCOPES,
    ids=[s[0] for s in _SCOPES],
)
def test_every_scope_rejects_an_unknown_key(
    tmp_path: Path, scope: str, old: str, new: str, code: str, keypath: str
) -> None:
    """Each authoring scope reports the right code at the right keypath and source line."""
    text = _BASE.replace(old, new)
    assert text != _BASE, f"{scope}: fixture did not substitute"
    junk = keypath.rsplit(".", 1)[-1]
    diags, template = _compile(tmp_path, text)

    diag = _one(diags, code)
    loc = _loc(diag)
    assert loc.keypath == keypath, (scope, loc.keypath)
    assert loc.line == _line_of(text, junk), (scope, loc.line)
    assert junk in diag.message, (scope, diag.message)
    assert loc.file == str(template), (scope, loc.file)
    assert diag.severity == "error", (scope, diag.severity)


def test_baseline_template_compiles_clean(tmp_path: Path) -> None:
    """The fixture itself is valid, so each scope test isolates the planted junk key."""
    diags, _ = _compile(tmp_path, _BASE)
    assert not [d for d in diags if d.severity == "error"], diags


# ------------------------------------------------------------------- the observed regression
def test_condition_on_a_node_is_rejected_and_names_the_if_construct(tmp_path: Path) -> None:
    """The field that started this: an agent invented ``condition:``, shipped three nodes on
    it, and wrote it into handoff docs as a real engine constraint. Deleting every line
    produced a byte-identical render, proving it was inert."""
    text = _BASE.replace(
        "      text: hi\n",
        '      text: hi\n      condition: "{{ title }}"\n',
    )
    diags, _ = _compile(tmp_path, text)

    diag = _one(diags, "ARC-TPL-064")
    assert _loc(diag).keypath == "root.children[0].condition"
    assert "condition" in diag.message
    # The hint must point at the real mechanism, not merely reject the field.
    assert "if:" in (diag.hint or ""), diag.hint
    assert "node:" in (diag.hint or ""), diag.hint


# ------------------------------------------------------------------- wrong-scope alias hints
_ALIASES: list[tuple[str, str]] = [
    ("condition", "if:"),
    ("opacity", "style"),
    ("font_size", "style"),
    ("color", "style"),
    ("fill", "style"),
    ("width", "constraints.size.w"),
    ("height", "constraints.size.h"),
    ("x", "constraints.anchor"),
    ("y", "constraints.anchor"),
    ("rotation", "transform"),
    ("margin", "constraints.anchor"),
    ("z_index", "z"),
    ("hidden", "visible"),
    ("name", "id"),
    ("src", "asset"),
    ("content", "text"),
]


@pytest.mark.parametrize(("field", "expected"), _ALIASES, ids=[a[0] for a in _ALIASES])
def test_wrong_scope_field_hints_name_the_real_home(
    tmp_path: Path, field: str, expected: str
) -> None:
    """A wrong-scope hint is worth more than a generic rejection: it must name the real home."""
    text = _BASE.replace("      text: hi\n", f"      text: hi\n      {field}: 1\n")
    diags, _ = _compile(tmp_path, text)

    diag = _one(diags, "ARC-TPL-064")
    assert _loc(diag).keypath == f"root.children[0].{field}"
    assert expected in (diag.hint or ""), (field, diag.hint)


def test_field_belonging_to_another_node_kind_says_which_kind(tmp_path: Path) -> None:
    """A real field in the wrong kind is told which kind owns it, not just 'unknown'."""
    text = _BASE.replace("      text: hi\n", "      text: hi\n      children: []\n")
    diags, _ = _compile(tmp_path, text)

    diag = _one(diags, "ARC-TPL-064")
    assert "'group'" in (diag.hint or ""), diag.hint
    assert "'text'" in (diag.hint or ""), diag.hint


def test_unknown_node_field_lists_the_vocabulary_for_that_kind(tmp_path: Path) -> None:
    """The generic fallback lists this kind's fields — a text node's, not a group's."""
    text = _BASE.replace("      text: hi\n", "      text: hi\n      wibble: 1\n")
    diags, _ = _compile(tmp_path, text)

    hint = _one(diags, "ARC-TPL-064").hint or ""
    assert "paragraph" in hint and "runs" in hint, hint  # text-kind fields
    assert "children" not in hint, hint  # a group field, not offered here


# ------------------------------------------------------- deferred fields keep their own code
def test_line_height_keeps_its_own_diagnostic(tmp_path: Path) -> None:
    """``line_height`` stays out of _STYLE_KEYS but keeps its dedicated ARC-TPL-053 (RR2-12)."""
    text = _BASE.replace(
        "      style: {font_size: 12px}\n",
        "      style: {font_size: 12px, line_height: 1.4}\n",
    )
    codes = {d.code for d in _compile(tmp_path, text)[0]}

    assert "ARC-TPL-053" in codes, codes
    assert "ARC-TPL-064" not in codes


def test_wrap_keeps_its_own_diagnostic(tmp_path: Path) -> None:
    """``wrap`` is authored-but-unsupported, so it stays inside the group whitelist and its
    specific ARC-LAY-056 wins over a generic unknown-field rejection."""
    text = _BASE.replace("  id: root\n", "  id: root\n  layout: vstack\n  wrap: true\n")
    codes = {d.code for d in _compile(tmp_path, text)[0]}

    assert "ARC-LAY-056" in codes, codes
    assert "ARC-TPL-064" not in codes


# ------------------------------------------------------------------------- the guard test
# Every authoring scope, as a mapping the compiler parses, paired with the edit that plants an
# unknown key in it. This is the test that would have caught P0-1: a scope added later without
# a whitelist fails here instead of silently accepting invented fields for eight phases.
_SURFACE: list[tuple[str, str, str]] = [
    ("template root", "version: 0.1.0", "version: 0.1.0\nzzz_junk: 1"),
    ("formats.<name>", "  square:\n", "  square:\n    zzz_junk: 1\n"),
    (
        "formats.<name>.canvas",
        "canvas: {width: 400px, height: 400px, dpi: 72}",
        "canvas: {width: 400px, height: 400px, dpi: 72, zzz_junk: 1}",
    ),
    (
        "variables.<name>",
        "title: {type: string, required: false, default: hi}",
        "title: {type: string, required: false, default: hi, zzz_junk: 1}",
    ),
    ("node top level", "      text: hi\n", "      text: hi\n      zzz_junk: 1\n"),
    (
        "effects[] entry",
        "      text: hi\n",
        "      text: hi\n      effects:\n        - {name: blur, zzz_junk: 1}\n",
    ),
    ("style", "style: {font_size: 12px}", "style: {font_size: 12px, zzz_junk: 1}"),
    ("paragraph", "      text: hi\n", "      text: hi\n      paragraph: {zzz_junk: 1}\n"),
    (
        "fit",
        "      text: hi\n",
        "      text: hi\n      fit: {policy: wrap, zzz_junk: 1}\n",
    ),
    (
        "constraints",
        "      constraints:\n",
        "      constraints:\n        zzz_junk: 1\n",
    ),
    (
        "constraints.size.<axis>",
        "size: {w: fill, h: fit_content}",
        "size: {w: {value: fill, zzz_junk: 1}, h: fit_content}",
    ),
    (
        "runs[] entry",
        "      text: hi\n",
        "      runs:\n        - {text: hi, zzz_junk: 1}\n",
    ),
    (
        "transform",
        "      text: hi\n",
        "      text: hi\n      transform: {rotate: 5, zzz_junk: 1}\n",
    ),
    (
        "mask",
        "      text: hi\n",
        "      text: hi\n      mask: {component: rounded_rect, zzz_junk: 1}\n",
    ),
    (
        "stack padding",
        "  id: root\n",
        "  id: root\n  layout: vstack\n  padding: {top: 4px, zzz_junk: 1}\n",
    ),
    (
        "'if' construct",
        "    - id: body\n",
        '    - if: "{{ title }}"\n      zzz_junk: 1\n      node:\n        id: body\n',
    ),
    (
        "'repeat' construct",
        "    - id: body\n",
        '    - repeat: "{{ items }}"\n      as: item\n      key: "{{ item }}"\n'
        "      zzz_junk: 1\n      node:\n        id: body\n",
    ),
    ("locales.<name>", "version: 0.1.0", "version: 0.1.0\nlocales:\n  fa: {zzz_junk: 1}\n"),
]


@pytest.mark.parametrize(
    ("scope", "old", "new"), _SURFACE, ids=[s[0] for s in _SURFACE]
)
def test_guard_no_authoring_scope_silently_accepts_unknown_keys(
    tmp_path: Path, scope: str, old: str, new: str
) -> None:
    """The anti-regression net: *every* mapping an author can write rejects an invented key.

    Asserts only that the scope errors and names the offending key — not which code it uses —
    so the guard keeps holding if a scope is later given its own more specific diagnostic.
    """
    text = _BASE.replace(old, new, 1)
    assert text != _BASE, f"{scope}: fixture did not substitute"
    diags, _ = _compile(tmp_path, text)

    errors = [d for d in diags if d.severity == "error"]
    assert errors, f"{scope} silently accepted an unknown key"
    assert any("zzz_junk" in d.message for d in errors), (
        f"{scope} errored but did not name the offending key: "
        f"{[(d.code, d.message) for d in errors]}"
    )


# ------------------------------------------------------------------------- repo-wide sweep
def _repo_templates() -> list[Path]:
    """Every template the repo ships, found the way the loader identifies one."""
    found: set[Path] = set()
    for base in ("examples", "library-seed", "tests"):
        root = _REPO_ROOT / base
        if not root.is_dir():
            continue
        for path in root.rglob("*.yaml"):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:  # pragma: no cover - unreadable file
                continue
            # A template is the document that declares a node tree; data files, style packs,
            # and sidecars are reached through it.
            if text.startswith("root:") or "\nroot:\n" in text:
                found.add(path)
    return sorted(found)


def test_repo_ships_templates_to_sweep() -> None:
    """Guards the sweep below against silently matching nothing."""
    assert len(_repo_templates()) >= 8, _repo_templates()


# Codes a shipped template may legitimately still produce under a *bare* facade, with the
# reason. ARC-FX-910 predates this change: the graphic-style-lab and future-archive examples
# reference effects supplied by an extension ('cinema-emulsion', 'archive-print'), which a
# facade built without that extension installed cannot resolve. Verified against the
# unmodified compiler, so it is not fallout from the strictness sweep.
_SWEEP_EXEMPT: dict[str, str] = {
    "ARC-FX-910": "example uses an extension-provided effect; bare facade has no extensions",
}

_STRICTNESS_CODES = frozenset({
    "ARC-TPL-051", "ARC-TPL-064", "ARC-TPL-065",
    "ARC-TPL-066", "ARC-TPL-067", "ARC-TPL-068",
})


@pytest.mark.parametrize(
    "template", _repo_templates(), ids=lambda p: p.relative_to(_REPO_ROOT).as_posix()
)
def test_shipped_templates_still_validate(template: Path) -> None:
    """No template the repo ships carries a junk field that the new strictness now rejects."""
    facade = build_facade()
    errors = [d for d in facade.validate_template(template) if d.severity == "error"]

    unknown_field = [d for d in errors if d.code in _STRICTNESS_CODES]
    assert not unknown_field, [
        (d.code, d.message, d.source.keypath if d.source else None) for d in unknown_field
    ]
    unexpected = [d for d in errors if d.code not in _SWEEP_EXEMPT]
    assert not unexpected, [(d.code, d.message) for d in unexpected]
