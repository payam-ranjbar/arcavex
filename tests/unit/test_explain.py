"""Explain tests: emitted-code coverage, lookup, and docs/diagnostics mirror."""

from __future__ import annotations

import re
from pathlib import Path

from arcavex.bootstrap import build_facade
from arcavex.services.diagnostics_catalog import CATALOG, documented_codes, render_markdown

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src" / "arcavex"
_DOCS = _REPO_ROOT / "docs" / "diagnostics"
_CODE_RE = re.compile(r'"(ARC-[A-Z]+-[0-9]+)"')


def _emitted_codes() -> set[str]:
    codes: set[str] = set()
    for path in _SRC.rglob("*.py"):
        codes |= set(_CODE_RE.findall(path.read_text(encoding="utf-8")))
    return codes


def _raise_site_codes() -> set[str]:
    """Codes that appear as a literal *outside* the catalog module — i.e. a real raise-site.

    The catalog module registers every code as a literal, so it must be excluded to tell a code
    the engine can actually produce apart from one that is merely defined.
    """
    codes: set[str] = set()
    for path in _SRC.rglob("*.py"):
        if path.name == "diagnostics_catalog.py":
            continue
        codes |= set(_CODE_RE.findall(path.read_text(encoding="utf-8")))
    return codes


# Codes registered + documented but intentionally not raised by the current engine. Each needs a
# reason here so a genuinely-unreachable *new* code (as ARC-EXP-001 was — registered and
# documented, yet an unwritable output path fell through to ARC-INT-999, DX-2) is caught by
# ``test_registered_codes_are_reachable`` instead of shipping a diagnostic that can never appear.
_REACHABILITY_EXEMPT: dict[str, str] = {
    "ARC-FX-900": "legacy compatibility placeholder; effects now compile and report ARC-FX-9xx",
    "ARC-LAY-014": "reserved 'unsupported anchor edge'; no current build rejects an edge here",
    "ARC-RND-900": "reserved 'masks not supported' placeholder; masks shipped, so it is unraised",
    "ARC-TPL-052": "reserved 'stacks not supported' placeholder; superseded once stacks shipped",
    "ARC-TPL-091": "reserved 'locale not supported' placeholder; locale shipped in Phase 2",
    "ARC-TPL-094": "reserved 'style opt-in not supported' placeholder; style shipped later",
    "ARC-TPL-095": "reserved 'format patch not supported' placeholder; patch shipped later",
}


def test_every_emitted_code_is_documented() -> None:
    """The coverage guarantee: emitted codes are a subset of documented codes."""
    missing = _emitted_codes() - documented_codes()
    assert not missing, f"undocumented diagnostic codes: {sorted(missing)}"


def test_registered_codes_are_reachable() -> None:
    """Every documented code has a raise-site, or an explicit reachability exemption (DX-2).

    ARC-EXP-001 shipped registered and documented but with no raise-site, so an unwritable
    output path leaked as ARC-INT-999/exit 5. This guards that class of defect: a new catalog
    code must either be raised somewhere in the engine or be listed — with a reason — in
    ``_REACHABILITY_EXEMPT``.
    """
    reachable = _raise_site_codes() | set(_REACHABILITY_EXEMPT)
    unreachable = documented_codes() - reachable
    assert not unreachable, (
        f"registered codes with no raise-site and no reachability exemption: {sorted(unreachable)}"
    )


def test_reachability_exemptions_stay_honest() -> None:
    """An exemption must name a real, genuinely-unraised code — drop it once a raise-site exists."""
    raised = _raise_site_codes()
    stale = sorted(set(_REACHABILITY_EXEMPT) & raised)
    assert not stale, f"exempted codes that are actually raised (remove the exemption): {stale}"
    unknown = sorted(set(_REACHABILITY_EXEMPT) - documented_codes())
    assert not unknown, f"reachability exemptions for unknown codes: {unknown}"


def test_explain_known_code() -> None:
    facade = build_facade()
    help_ = facade.explain_diagnostic("ARC-TPL-014")
    assert help_.found
    assert help_.title and help_.summary and help_.fix


def test_explain_is_case_insensitive() -> None:
    facade = build_facade()
    assert facade.explain_diagnostic("arc-tpl-014").found


def test_explain_unknown_code_is_helpful() -> None:
    facade = build_facade()
    help_ = facade.explain_diagnostic("ARC-ZZZ-000")
    assert not help_.found
    assert help_.message


def test_docs_diagnostics_mirror_catalog() -> None:
    """Each catalog entry has a matching, up-to-date docs/diagnostics/<code>.md file."""
    for code, doc in CATALOG.items():
        md = _DOCS / f"{code}.md"
        assert md.is_file(), f"missing docs file for {code}"
        assert md.read_text(encoding="utf-8") == render_markdown(doc)


def test_no_orphan_docs_files() -> None:
    doc_codes = {p.stem for p in _DOCS.glob("*.md")}
    assert doc_codes == documented_codes()


def test_new_remediation_codes_are_documented() -> None:
    """CR-3/DX-1/DX-5 added new codes; every one must have a catalog entry."""
    for code in ("ARC-TPL-061", "ARC-TPL-099", "ARC-LAY-040"):
        assert code in documented_codes()


def test_lay012_explain_mentions_expression_boundary() -> None:
    """DX-6: the LAY-012 entry now names the real cause (an expression in a constraint)."""
    facade = build_facade()
    help_ = facade.explain_diagnostic("ARC-LAY-012")
    assert help_.found and help_.summary is not None
    lowered = help_.summary.lower()
    assert "expression" in lowered and "constraint" in lowered
    # The entry adds value beyond the one-line inline hint (it is substantially longer).
    assert len(help_.summary) > 120
