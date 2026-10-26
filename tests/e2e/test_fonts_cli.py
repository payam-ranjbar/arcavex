"""End-to-end font installation workflow.

Drives the Typer app in-process with an isolated ``$ARCAVEX_HOME`` — via the shared
``arcavex_home`` fixture — so no test ever writes into the developer's real font store. Covers
list → add → render → remove plus the refusals (bundled family, unknown family, unreadable file).

Several tests additionally suppress the in-repo ``library-seed/fonts`` root by patching
``_find_repo_root``, the marker walk ``find_font_dirs`` uses to locate it. That leaves the
isolated home as the ONLY font root, which is what makes "installing a font makes a new family
resolvable" a real assertion: the same render is exit 3 before the install and exit 0 after, so
the install is doing the work rather than the bundled seed masking it.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from arcavex.clients.cli import app
from arcavex.services.text import service as text_service

REPO_ROOT = Path(__file__).resolve().parents[2]
SEED_FONTS = REPO_ROOT / "library-seed" / "fonts"
# A real bundled face whose internal family name ('Lalezar') differs from any filename a test
# gives it — the trap 'font add' exists to close.
SAMPLE_FONT = SEED_FONTS / "Lalezar-Regular.ttf"
SAMPLE_FAMILY = "Lalezar"
BUNDLED_FAMILIES = {"Estedad", "Inter", "Lalezar", "Vazirmatn"}

runner = CliRunner()

_TEMPLATE = """\
version: 0.1.0
formats: {card: {canvas: {width: 240px, height: 120px, dpi: 96}}}
preview_data: {}
root:
  type: group
  id: root
  children:
    - id: title
      type: text
      text: "Salam"
      style: {font: %s, font_size: 24px, color: "#111111"}
      constraints:
        anchor: {top: parent.top, left: parent.left}
        size: {w: fill, h: fit_content}
"""


@pytest.fixture()
def home_only_fonts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop the in-repo ``library-seed/fonts`` root so the isolated home is the only font source."""
    monkeypatch.setattr(text_service, "_find_repo_root", lambda: None)


def _write_template(tmp_path: Path, family: str) -> Path:
    template = tmp_path / "tpl.yaml"
    template.write_text(_TEMPLATE % family, encoding="utf-8")
    return template


def _renamed_copy(tmp_path: Path, name: str) -> Path:
    """Copy the sample face under a filename whose stem is NOT the family name."""
    dest = tmp_path / name
    shutil.copyfile(SAMPLE_FONT, dest)
    return dest


# ------------------------------------------------------------------------------------ list
def test_font_list_shows_bundled_families(arcavex_home: Path) -> None:
    """'font list' reports the four bundled families, each marked bundled and not installed."""
    result = runner.invoke(app, ["font", "list", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    families = {f["family"]: f for f in payload["families"]}
    assert BUNDLED_FAMILIES <= set(families)
    for name in BUNDLED_FAMILIES:
        assert families[name]["bundled"] is True
        assert families[name]["installed"] is False
        assert families[name]["files"], f"{name} reports no files"


def test_font_list_names_the_install_directory(arcavex_home: Path) -> None:
    """The report names the directory 'font add' writes to; 'doctor' reports only a count."""
    result = runner.invoke(app, ["font", "list", "--json"])
    assert result.exit_code == 0, result.output
    install_dir = Path(json.loads(result.stdout)["install_dir"])
    assert install_dir == arcavex_home / "fonts"


def test_font_list_human_output_marks_bundled_vs_installed(arcavex_home: Path) -> None:
    result = runner.invoke(app, ["font", "list"])
    assert result.exit_code == 0, result.output
    assert "Inter" in result.output
    assert "bundled" in result.output
    # The install directory is printed so a first-run user learns where to add fonts.
    assert "fonts" in result.output


# --------------------------------------------------------------------------------- metrics
def test_font_metrics_json_reports_positive_metrics(arcavex_home: Path) -> None:
    """'font metrics FAMILY SIZE' reports every measurement a box-sizing agent needs."""
    result = runner.invoke(app, ["font", "metrics", "Inter", "40pt", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["response_version"] == 1
    assert payload["ok"] is True
    assert payload["family"] == payload["resolved_family"] == "Inter"
    assert payload["fallback"] is False
    assert payload["size_pt"] == pytest.approx(40.0)
    for key in (
        "ascent_pt",
        "descent_pt",
        "line_height_pt",
        "cap_height_pt",
        "x_height_pt",
        "advance_pt",
    ):
        assert payload[key] > 0, key


def test_font_metrics_px_states_the_dpi_basis(arcavex_home: Path) -> None:
    """A px size is resolved at the reported dpi; the report names both pt and px."""
    result = runner.invoke(
        app, ["font", "metrics", "Inter", "54px", "--dpi", "96", "--json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["dpi"] == 96
    assert payload["size_pt"] == pytest.approx(40.5)  # 54 * 72 / 96
    assert payload["size_px"] == pytest.approx(54.0)


def test_font_metrics_bare_number_is_pixels(arcavex_home: Path) -> None:
    result = runner.invoke(app, ["font", "metrics", "Inter", "40", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["size_px"] == pytest.approx(40.0)


def test_font_metrics_human_output_lists_metrics(arcavex_home: Path) -> None:
    result = runner.invoke(app, ["font", "metrics", "Inter", "40pt"])
    assert result.exit_code == 0, result.output
    for label in ("ascent", "descent", "line height", "cap height", "x-height", "Inter"):
        assert label in result.output


def test_font_metrics_unknown_family_errors_but_names_the_fallback(
    arcavex_home: Path,
) -> None:
    """An unknown family is ARC-RND-010 (exit 3), and the report says what it measured instead."""
    result = runner.invoke(app, ["font", "metrics", "Nonesuch", "40pt", "--json"])
    assert result.exit_code == 3, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["fallback"] is True
    assert payload["resolved_family"] == "Inter"
    diag = payload["diagnostics"][0]
    assert diag["code"] == "ARC-RND-010" and diag["severity"] == "error"


def test_font_metrics_rejects_a_bad_size(arcavex_home: Path) -> None:
    result = runner.invoke(app, ["font", "metrics", "Inter", "huge", "--json"])
    assert result.exit_code == 1, result.output
    assert json.loads(result.stdout)["diagnostics"][0]["code"] == "ARC-IR-011"


# ------------------------------------------------------------------------------------- add
def test_font_add_reports_family_as_the_engine_resolves_it(
    arcavex_home: Path, tmp_path: Path
) -> None:
    """The reported name is the internal family, never the file stem."""
    source = _renamed_copy(tmp_path, "MyCoolFont-Regular.ttf")
    result = runner.invoke(app, ["font", "add", str(source), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["family"] == SAMPLE_FAMILY
    assert payload["family"] != source.stem
    assert (arcavex_home / "fonts" / "MyCoolFont-Regular.ttf").is_file()


def test_font_add_reported_family_is_what_the_shaper_registers(
    arcavex_home: Path, tmp_path: Path
) -> None:
    """The reported family is exactly the name the font database registers the file under.

    This is the guarantee that matters: 'font add' and the shaper must not drift, so the name a
    template writes is the name that resolves.
    """
    source = _renamed_copy(tmp_path, "Unrelated-Name.ttf")
    result = runner.invoke(app, ["font", "add", str(source), "--json"])
    assert result.exit_code == 0, result.output
    reported = json.loads(result.stdout)["family"]
    loaded = text_service.TextService([arcavex_home / "fonts"])
    assert reported in loaded.families


def test_font_add_makes_family_resolvable_by_a_later_render(
    arcavex_home: Path, tmp_path: Path, home_only_fonts: None
) -> None:
    """With no bundled root, a render naming the family fails before the add and succeeds after."""
    template = _write_template(tmp_path, SAMPLE_FAMILY)
    out = tmp_path / "out.png"

    before = runner.invoke(app, ["render", str(template), "--format", "card", "-o", str(out)])
    assert before.exit_code == 3, before.output  # exit 3 = missing font
    assert not out.exists()

    added = runner.invoke(app, ["font", "add", str(SAMPLE_FONT), "--json"])
    assert added.exit_code == 0, added.output
    assert json.loads(added.stdout)["family"] == SAMPLE_FAMILY

    after = runner.invoke(app, ["render", str(template), "--format", "card", "-o", str(out)])
    assert after.exit_code == 0, after.output
    assert out.is_file() and out.stat().st_size > 0


def test_font_add_copies_the_license_alongside(arcavex_home: Path, tmp_path: Path) -> None:
    """--license keeps the bundled OFL convention for installed fonts."""
    license_file = tmp_path / "OFL.txt"
    license_file.write_text("SIL Open Font License", encoding="utf-8")
    result = runner.invoke(
        app, ["font", "add", str(SAMPLE_FONT), "--license", str(license_file), "--json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    installed_license = Path(payload["license"])
    assert installed_license.is_file()
    assert installed_license.parent == arcavex_home / "fonts"
    assert installed_license.name.startswith(f"LICENSE-{SAMPLE_FAMILY}-")


def test_font_add_rejects_a_missing_file(arcavex_home: Path, tmp_path: Path) -> None:
    """A path that is not there exits 3 — the same 'missing input' class as a missing asset."""
    result = runner.invoke(app, ["font", "add", str(tmp_path / "nope.ttf"), "--json"])
    assert result.exit_code == 3, result.output
    assert json.loads(result.stdout)["diagnostics"][0]["code"] == "ARC-RND-030"


def test_font_add_rejects_a_file_skia_cannot_read(arcavex_home: Path, tmp_path: Path) -> None:
    """A .ttf that is not a typeface is refused rather than installed as dead weight."""
    fake = tmp_path / "not-a-font.ttf"
    fake.write_text("this is not a font", encoding="utf-8")
    result = runner.invoke(app, ["font", "add", str(fake), "--json"])
    assert result.exit_code != 0
    assert json.loads(result.stdout)["diagnostics"][0]["code"] == "ARC-RND-031"
    assert not (arcavex_home / "fonts" / "not-a-font.ttf").exists()


def test_font_add_with_a_bad_license_path_installs_nothing(
    arcavex_home: Path, tmp_path: Path
) -> None:
    """Both inputs are validated before any copy, so a failure never leaves the font behind."""
    result = runner.invoke(
        app,
        ["font", "add", str(SAMPLE_FONT), "--license", str(tmp_path / "missing.txt"), "--json"],
    )
    assert result.exit_code != 0
    assert json.loads(result.stdout)["diagnostics"][0]["code"] == "ARC-RND-030"
    assert not (arcavex_home / "fonts" / SAMPLE_FONT.name).exists()


def test_font_add_rejects_an_unsupported_extension(arcavex_home: Path, tmp_path: Path) -> None:
    otf = tmp_path / "Some-Face.otf"
    otf.write_bytes(SAMPLE_FONT.read_bytes())
    result = runner.invoke(app, ["font", "add", str(otf), "--json"])
    assert result.exit_code != 0
    assert json.loads(result.stdout)["diagnostics"][0]["code"] == "ARC-RND-031"


# ---------------------------------------------------------------------------------- remove
def test_font_remove_refuses_a_bundled_family(arcavex_home: Path) -> None:
    """A bundled family backs the default stacks; removing it would break untouched templates."""
    result = runner.invoke(app, ["font", "remove", "Inter", "--json"])
    assert result.exit_code != 0
    assert json.loads(result.stdout)["diagnostics"][0]["code"] == "ARC-RND-032"
    assert (SEED_FONTS / "Inter-Regular.ttf").is_file()  # untouched on disk


def test_font_remove_deletes_an_installed_family(
    arcavex_home: Path, tmp_path: Path, home_only_fonts: None
) -> None:
    """With no bundled root the added family is installed-only, so removal is allowed."""
    assert runner.invoke(app, ["font", "add", str(SAMPLE_FONT)]).exit_code == 0
    installed = arcavex_home / "fonts" / SAMPLE_FONT.name
    assert installed.is_file()

    result = runner.invoke(app, ["font", "remove", SAMPLE_FAMILY, "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is True and payload["family"] == SAMPLE_FAMILY
    assert not installed.exists()

    listing = runner.invoke(app, ["font", "list", "--json"])
    assert SAMPLE_FAMILY not in {f["family"] for f in json.loads(listing.stdout)["families"]}


def test_font_remove_also_drops_the_installed_license(
    arcavex_home: Path, tmp_path: Path, home_only_fonts: None
) -> None:
    license_file = tmp_path / "OFL.txt"
    license_file.write_text("SIL Open Font License", encoding="utf-8")
    added = runner.invoke(
        app, ["font", "add", str(SAMPLE_FONT), "--license", str(license_file), "--json"]
    )
    assert added.exit_code == 0, added.output
    installed_license = Path(json.loads(added.stdout)["license"])
    assert installed_license.is_file()

    assert runner.invoke(app, ["font", "remove", SAMPLE_FAMILY]).exit_code == 0
    assert not installed_license.exists()


def test_font_remove_unknown_family_lists_what_is_installed(arcavex_home: Path) -> None:
    result = runner.invoke(app, ["font", "remove", "Nonesuch", "--json"])
    assert result.exit_code != 0
    diag = json.loads(result.stdout)["diagnostics"][0]
    assert diag["code"] == "ARC-RND-033"
    assert "Installed families" in (diag["hint"] or "")


# ------------------------------------------------------------------------------ diagnostic
def test_missing_font_diagnostic_names_font_add_and_the_nearest_family(
    arcavex_home: Path, tmp_path: Path
) -> None:
    """ARC-RND-010 now points at the fix ('font add') and suggests the nearest installed name."""
    template = _write_template(tmp_path, "Intr")
    result = runner.invoke(
        app, ["render", str(template), "--format", "card", "-o", str(tmp_path / "o.png"), "--json"]
    )
    assert result.exit_code == 3, result.output
    diag = next(
        d for d in json.loads(result.stdout)["diagnostics"] if d["code"] == "ARC-RND-010"
    )
    hint = diag["hint"] or ""
    assert "arcavex font add" in hint
    assert "Inter" in hint  # nearest match to the typo 'Intr'
