"""Scaffold placeholder copy must not print on a project render unannounced (ARC-PRJ-015).

``project new`` seeds a project's data from the template's ``data.yaml``; a scaffolded template
ships placeholder copy there. A verifier reproduced the trap over MCP: the project render printed
"A scaffolded card" while ``render_preview`` of the same template (which uses ``preview_data``)
showed different copy, and nothing said so. Now the placeholders read as placeholders, and the
project's render, preview, and validate each carry a warning naming the variables still holding one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arcavex.bootstrap import build_facade
from arcavex.kernel.api import Facade
from arcavex.services.authoring import SCAFFOLD_PLACEHOLDERS, scaffold_placeholder_diagnostics


@pytest.fixture()
def project(tmp_path: Path, arcavex_home: Path) -> tuple[Facade, Path]:
    """A scaffolded template and a project pinning it by path, seeded from its data.yaml."""
    assert arcavex_home.is_dir()
    facade = build_facade()
    template = tmp_path / "card"
    assert facade.scaffold_template("card", template).ok
    target = tmp_path / "proj"
    created = facade.create_project(target, "proj", str(template))
    assert created.ok, [d.model_dump() for d in created.diagnostics]
    return facade, target


def _placeholder_warnings(diagnostics) -> list:  # noqa: ANN001
    return [d for d in diagnostics if d.code == "ARC-PRJ-015"]


def test_scaffold_placeholders_read_as_placeholders(tmp_path: Path) -> None:
    facade = build_facade()
    target = tmp_path / "card"
    assert facade.scaffold_template("card", target).ok
    data = (target / "data.yaml").read_text(encoding="utf-8")
    for value in SCAFFOLD_PLACEHOLDERS.values():
        assert value in data and value.upper() == value  # unmistakably a placeholder
    # The scaffold still renders with its own placeholder data.
    rendered = facade.render_file(target, target / "data.yaml", "square", output=tmp_path / "s.png")
    assert rendered.ok, [d.model_dump() for d in rendered.diagnostics]


def test_project_render_warns_and_names_the_placeholder_variables(
    project: tuple[Facade, Path],
) -> None:
    facade, target = project
    report = facade.render_project(project=target, formats=["square"])
    assert report.ok, [d.model_dump() for d in report.diagnostics]
    warnings = _placeholder_warnings(report.diagnostics)
    assert len(warnings) == 1
    warning = warnings[0]
    assert warning.severity == "warning"
    assert "'subtitle'" in warning.message and "'title'" in warning.message
    assert warning.hint is not None and "arcavex_data_set" in warning.hint
    assert warning.source is not None and warning.source.file is not None
    assert warning.source.file.endswith("proj.yaml")


def test_preview_and_validate_carry_the_same_warning(project: tuple[Facade, Path]) -> None:
    facade, target = project
    preview = facade.preview_project(project=target, formats=["square"])
    assert preview.ok
    assert len(_placeholder_warnings(preview.diagnostics)) == 1
    checked = facade.validate_project(project=target)
    assert checked.ok  # a warning, never an error
    assert len(_placeholder_warnings(checked.diagnostics)) == 1


def test_the_warning_shrinks_to_the_variables_still_holding_a_placeholder(
    project: tuple[Facade, Path],
) -> None:
    facade, target = project
    assert facade.set_data("title", "Golden Crust Bakery", project=target).ok
    report = facade.render_project(project=target, formats=["square"])
    warning = _placeholder_warnings(report.diagnostics)[0]
    assert "'subtitle'" in warning.message and "'title'" not in warning.message

    assert facade.set_data("subtitle", "Open daily from seven", project=target).ok
    report = facade.render_project(project=target, formats=["square"])
    assert report.ok and not _placeholder_warnings(report.diagnostics)


def test_detection_is_exact_and_best_effort(tmp_path: Path) -> None:
    data = tmp_path / "data.yaml"
    data.write_text('title: "TITLE GOES HERE!"\nsubtitle: "SUBTITLE GOES HERE"\n', encoding="utf-8")
    [warning] = scaffold_placeholder_diagnostics(data)
    assert "'subtitle'" in warning.message and "'title'" not in warning.message
    assert scaffold_placeholder_diagnostics(None) == []
    assert scaffold_placeholder_diagnostics(tmp_path / "missing.yaml") == []
    data.write_text("- not\n- a mapping\n", encoding="utf-8")
    assert scaffold_placeholder_diagnostics(data) == []
