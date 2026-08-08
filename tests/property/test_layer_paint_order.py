"""Property tests for authoritative solver paint order and layer presentation."""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from arcavex.bootstrap import build_facade


@pytest.fixture(scope="module")
def facade():  # noqa: ANN201
    return build_facade()


@given(st.lists(st.integers(min_value=-5, max_value=5), min_size=1, max_size=8))
@settings(
    max_examples=24,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_layer_presentation_is_reverse_solver_order_for_all_z_ties(
    facade, tmp_path: Path, z_values: list[int]
) -> None:  # noqa: ANN001
    """Sorting by source alone, descending z alone, or unstable ties must fail."""
    project = tmp_path / "paint-order"
    template = project / "template"
    template.mkdir(parents=True, exist_ok=True)
    (project / "project.yaml").write_text(
        "name: paint-order\ntemplate: ./template\nformats: [square]\nlocales: []\n",
        encoding="utf-8",
    )
    children = "".join(
        f"""    - id: n{index}
      type: shape
      shape: rect
      z: {z}
      constraints: {{anchor: {{top: parent.top, left: parent.left}}, size: {{w: 10pt, h: 10pt}}}}
"""
        for index, z in enumerate(z_values)
    )
    (template / "template.yaml").write_text(
        """version: 0.1.0
formats:
  square: {canvas: {width: 100px, height: 100px, dpi: 72}}
root:
  id: root
  type: group
  children:
"""
        + children,
        encoding="utf-8",
    )

    report = facade.layer_tree(project=project, mode="rendered", format_name="square")

    assert report.ok
    assert report.root is not None
    solver_order = sorted(range(len(z_values)), key=lambda index: (z_values[index], index))
    expected_presentation = [f"n{index}" for index in reversed(solver_order)]
    paint_index = {f"n{index}": position for position, index in enumerate(solver_order)}
    assert [child.id for child in report.root.children] == expected_presentation
    assert {child.id: child.paint_index for child in report.root.children} == paint_index
