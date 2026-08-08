"""Authoritative authored/rendered layer-tree contract tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from arcavex.bootstrap import build_facade
from arcavex.kernel import api
from arcavex.services.layers import _virtual_rows


def _project(tmp_path: Path, *, cards: str = "[]", show_badge: bool = False) -> Path:
    project = tmp_path / "campaign"
    template = project / "template"
    template.mkdir(parents=True)
    (project / "project.yaml").write_text(
        "name: layers\ntemplate: ./template\nformats: [square]\nlocales: [en]\n"
        "data: data.yaml\n",
        encoding="utf-8",
    )
    (project / "project.ui.yaml").write_text(
        'version: 1\nlayers:\n  foreground: {display_name: "Top card", locked: true, '
        'color: "#AABBCC"}\n',
        encoding="utf-8",
    )
    (project / "data.yaml").write_text(
        f"show_badge: {str(show_badge).lower()}\ncards: {cards}\n", encoding="utf-8"
    )
    (template / "template.yaml").write_text(
        """version: 0.1.0
variables:
  show_badge: {type: boolean, default: false}
  cards: {type: list, default: []}
formats:
  square: {canvas: {width: 200px, height: 200px, dpi: 72}}
locales:
  en: {direction: ltr, digits: en}
root:
  id: root
  type: group
  children:
    - id: background
      type: shape
      shape: rect
      z: -1
      constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: fill, h: fill}}
    - id: panel
      type: group
      z: 0
      constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: 100pt, h: 100pt}}
      children:
        - id: nested
          type: shape
          shape: rect
          constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: 20pt, h: 20pt}}
    - repeat: "{{ cards }}"
      as: card
      key: "{{ card.id }}"
      node:
        id: card
        type: shape
        shape: rect
        z: 2
        effects: [{name: blur, params: {radius: 1pt}}]
        constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: 30pt, h: 30pt}}
    - if: "{{ show_badge }}"
      node:
        id: badge
        type: shape
        shape: circle
        z: 5
        constraints:
          anchor: {bottom: parent.bottom, right: parent.right}
          size: {w: 20pt, h: 20pt}
    - id: foreground
      type: shape
      shape: rrect
      z: 10
      effects: [{name: blur, params: {radius: 2pt}}]
      mask: {component: rounded_rect, params: {radius: 4pt}}
      constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: 40pt, h: 40pt}}
    - id: invisible
      type: shape
      shape: rect
      visible: false
      z: 20
      constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: 50pt, h: 50pt}}
""",
        encoding="utf-8",
    )
    return project


def _project_state(project: Path) -> tuple[tuple[str, bytes, int], ...]:
    return tuple(
        (
            path.relative_to(project).as_posix(),
            path.read_bytes(),
            path.stat().st_mtime_ns,
        )
        for path in sorted(item for item in project.rglob("*") if item.is_file())
    )


def _nested_rotation_project(tmp_path: Path) -> Path:
    project = tmp_path / "nested-rotation"
    template = project / "template"
    template.mkdir(parents=True)
    (project / "project.yaml").write_text(
        "name: nested-rotation\ntemplate: ./template\nformats: [square]\nlocales: [en]\n",
        encoding="utf-8",
    )
    (template / "template.yaml").write_text(
        """version: 0.1.0
formats:
  square: {canvas: {width: 200pt, height: 200pt, dpi: 72}}
locales:
  en: {direction: ltr, digits: en}
root:
  id: root
  type: group
  children:
    - id: outer
      type: group
      transform: {rotate: 90, origin: center}
      constraints:
        anchor: {top: parent.top+40pt, left: parent.left+40pt}
        size: {w: 80pt, h: 80pt}
      children:
        - id: inner
          type: group
          transform: {rotate: 90, origin: center}
          constraints:
            anchor: {top: parent.top+10pt, left: parent.left+10pt}
            size: {w: 40pt, h: 40pt}
          children:
            - id: child
              type: shape
              shape: rect
              constraints:
                anchor: {top: parent.top+5pt, left: parent.left+5pt}
                size: {w: 10pt, h: 20pt}
""",
        encoding="utf-8",
    )
    return project


def _target_patch_project(tmp_path: Path) -> Path:
    project = tmp_path / "target-patches"
    template = project / "template"
    template.mkdir(parents=True)
    (project / "project.yaml").write_text(
        "name: target-patches\ntemplate: ./template\n"
        "formats: [square, story]\nlocales: [en, fa]\n",
        encoding="utf-8",
    )
    (template / "template.yaml").write_text(
        """version: 0.1.0
root:
  id: root
  type: group
  children:
    - id: base
      type: shape
      shape: rect
      constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: 10pt, h: 10pt}}
    - id: move
      type: shape
      shape: rect
      constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: 10pt, h: 10pt}}
    - id: anchor
      type: shape
      shape: rect
      constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: 10pt, h: 10pt}}
    - id: format-remove
      type: shape
      shape: rect
      constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: 10pt, h: 10pt}}
    - id: project-remove
      type: shape
      shape: rect
      constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: 10pt, h: 10pt}}
""",
        encoding="utf-8",
    )
    (template / "formats.yaml").write_text(
        """square:
  canvas: {width: 200pt, height: 200pt, dpi: 72}
  patch:
    - set: nodes.base.z
      value: 7
    - remove: nodes.format-remove
    - insert_after: nodes.base
      node:
        id: format-only
        type: shape
        shape: rect
        z: 3
        constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: 10pt, h: 10pt}}
story:
  canvas: {width: 100pt, height: 200pt, dpi: 72}
""",
        encoding="utf-8",
    )
    (template / "locales.yaml").write_text(
        """en: {direction: ltr, digits: en}
fa:
  direction: rtl
  digits: fa
  patch:
    - set: nodes.base.visible
      value: false
    - insert_after: nodes.format-only
      node:
        id: locale-only
        type: shape
        shape: rect
        z: 2
        constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: 10pt, h: 10pt}}
""",
        encoding="utf-8",
    )
    return project


def test_layer_tree_report_is_a_public_versioned_kernel_contract() -> None:
    """A desktop client must be able to consume one shared versioned report model."""
    report_type = getattr(api, "LayerTreeReport", None)

    assert report_type is not None, "LayerTreeReport is not exposed by arcavex.kernel.api"
    report = report_type(ok=True, mode="authored", root=None)
    assert report.model_dump(mode="json") == {
        "response_version": 1,
        "ok": True,
        "mode": "authored",
        "format": None,
        "locale": None,
        "canvas_pt": [0.0, 0.0],
        "canvas_px": [0, 0],
        "dpi": 0,
        "root": None,
        "diagnostics": [],
    }


def test_layer_node_contract_separates_authored_and_rendered_identity() -> None:
    """Conflating compiler instance IDs with authored IDs must break desktop selection."""
    source_type = getattr(api, "LayerSource", None)
    effect_type = getattr(api, "LayerEffect", None)
    mask_type = getattr(api, "LayerMask", None)
    node_type = getattr(api, "LayerNodeReport", None)

    assert all(item is not None for item in (source_type, effect_type, mask_type, node_type))
    node = node_type(
        id="card[alpha]",
        authored_id="card",
        instance_id="card[alpha]",
        parent_id="root",
        authored_index=1,
        paint_index=3,
        z=7,
        kind="shape",
        origin="repeat",
        collection="{{ cards }}",
        loop_var="card",
        key="{{ card.slug }}",
        display_name="Feature card",
        visible=True,
        locked=True,
        color="#AABBCC",
        editable=False,
        hit_testable=True,
        virtual=False,
        bounds_pt=(10.0, 20.0, 30.0, 40.0),
        bounds_px=(20.0, 40.0, 60.0, 80.0),
        paint_bounds_pt=(8.0, 18.0, 34.0, 44.0),
        paint_bounds_px=(16.0, 36.0, 68.0, 88.0),
        absolute_transform=(1.0, 0.0, 0.0, 1.0, 10.0, 20.0),
        rotate_deg=0.0,
        source=source_type(file="C:/campaign/template.yaml", keypath="root.children.1", line=9),
        effects=[effect_type(index=0, name="shadow", category="raster", params={"blur": 4})],
        mask=mask_type(component="rounded", params={"radius": 8}),
    )

    assert node.model_dump(mode="json") == {
        "id": "card[alpha]",
        "authored_id": "card",
        "instance_id": "card[alpha]",
        "parent_id": "root",
        "authored_index": 1,
        "paint_index": 3,
        "z": 7,
        "kind": "shape",
        "origin": "repeat",
        "condition": None,
        "collection": "{{ cards }}",
        "loop_var": "card",
        "key": "{{ card.slug }}",
        "display_name": "Feature card",
        "visible": True,
        "locked": True,
        "color": "#AABBCC",
        "editable": False,
        "hit_testable": True,
        "virtual": False,
        "bounds_pt": [10.0, 20.0, 30.0, 40.0],
        "bounds_px": [20.0, 40.0, 60.0, 80.0],
        "paint_bounds_pt": [8.0, 18.0, 34.0, 44.0],
        "paint_bounds_px": [16.0, 36.0, 68.0, 88.0],
        "absolute_transform": [1.0, 0.0, 0.0, 1.0, 10.0, 20.0],
        "rotate_deg": 0.0,
        "overflow": None,
        "source": {"file": "C:/campaign/template.yaml", "keypath": "root.children.1", "line": 9},
        "effects": [{"index": 0, "name": "shadow", "category": "raster", "params": {"blur": 4}}],
        "mask": {"component": "rounded", "params": {"radius": 8}},
        "children": [],
    }
    with pytest.raises(ValidationError):
        node.instance_id = "card[beta]"


def test_layer_tree_schema_export_is_deterministic_and_model_derived() -> None:
    """A stale or nondeterministic checked-in desktop schema must fail the contract gate."""
    root = Path(__file__).resolve().parents[2]
    script = root / "scripts" / "export_desktop_schemas.py"
    schema_path = root / "schemas" / "desktop" / "layer-tree.schema.json"

    first = subprocess.run([sys.executable, str(script)], cwd=root, check=True)
    assert first.returncode == 0
    first_bytes = schema_path.read_bytes()
    second = subprocess.run([sys.executable, str(script)], cwd=root, check=True)

    assert second.returncode == 0
    assert schema_path.read_bytes() == first_bytes
    assert first_bytes.endswith(b"\n")
    assert json.loads(first_bytes) == api.LayerTreeReport.model_json_schema()


def test_authored_tree_keeps_uninstantiated_constructs_metadata_and_virtual_rows(
    tmp_path: Path,
) -> None:
    """Dropping false/empty definitions or treating virtual rows as layers must fail."""
    facade = build_facade()

    report = facade.layer_tree(
        project=_project(tmp_path), mode="authored", format_name="square", locale="en"
    )

    assert report.ok, [diagnostic.model_dump() for diagnostic in report.diagnostics]
    assert report.root is not None
    assert [child.id for child in report.root.children] == [
        "invisible",
        "foreground",
        "badge",
        "card",
        "panel",
        "background",
    ]
    by_id = {child.id: child for child in report.root.children}
    assert (by_id["badge"].origin, by_id["badge"].condition) == (
        "if",
        "{{ show_badge }}",
    )
    assert by_id["badge"].instance_id is None
    assert by_id["badge"].bounds_pt is None
    assert (
        by_id["card"].origin,
        by_id["card"].collection,
        by_id["card"].loop_var,
        by_id["card"].key,
    ) == ("repeat", "{{ cards }}", "card", "{{ card.id }}")
    assert by_id["card"].instance_id is None
    assert by_id["panel"].children[0].id == "nested"
    foreground = by_id["foreground"]
    assert (foreground.display_name, foreground.locked, foreground.color, foreground.editable) == (
        "Top card",
        True,
        "#AABBCC",
        False,
    )
    virtual_state = [
        (row.kind, row.visible, row.hit_testable, row.virtual)
        for row in foreground.children
    ]
    assert virtual_state == [
        ("mask", True, False, True),
        ("effect", True, False, True),
    ]
    assert foreground.source is not None
    assert foreground.source.keypath == "root.children[4]"
    assert foreground.source.line is not None


def test_virtual_rows_use_reserved_namespace_with_injective_owner_encoding(
    tmp_path: Path,
) -> None:
    """Virtual IDs must be unreachable by real nodes and unambiguous for slash-bearing owners."""
    project = _project(tmp_path)
    template = project / "template" / "template.yaml"
    template.write_text(
        template.read_text(encoding="utf-8").replace(
            "id: foreground",
            "id: owner/with/slash",
        ),
        encoding="utf-8",
    )

    report = build_facade().layer_tree(
        project=project,
        mode="authored",
        format_name="square",
        locale="en",
    )

    assert report.root is not None
    owner = next(row for row in report.root.children if row.id == "owner/with/slash")
    assert [row.id for row in owner.children] == [
        "@arcavex/virtual/owner%2Fwith%2Fslash/mask",
        "@arcavex/virtual/owner%2Fwith%2Fslash/effect/0",
    ]
    assert all(row.id.startswith("@arcavex/virtual/") for row in owner.children)


def test_virtual_rows_inherit_owner_state_and_deep_copy_nested_payloads() -> None:
    """Virtual presentation rows must not expose mutable aliases back into their owner."""
    owner = api.LayerNodeReport(
        id="owner",
        authored_id="owner",
        instance_id="owner",
        parent_id="root",
        authored_index=0,
        kind="shape",
        display_name="Owner",
        visible=False,
        locked=True,
        editable=False,
        hit_testable=False,
        effects=[
            api.LayerEffect(
                index=0,
                name="custom",
                category="raster",
                params={"nested": {"levels": [1]}},
            )
        ],
        mask=api.LayerMask(
            component="custom-mask",
            params={"nested": {"levels": [1]}},
        ),
    )

    mask_row, effect_row = _virtual_rows(owner, 0)

    states = [
        (row.visible, row.locked, row.editable, row.hit_testable)
        for row in (mask_row, effect_row)
    ]
    assert states == [
        (False, True, False, False),
        (False, True, False, False),
    ]
    assert mask_row.mask is not None and owner.mask is not None
    assert mask_row.mask is not owner.mask
    assert mask_row.mask.params is not owner.mask.params
    assert mask_row.mask.params["nested"] is not owner.mask.params["nested"]
    assert effect_row.effects[0] is not owner.effects[0]
    assert effect_row.effects[0].params is not owner.effects[0].params
    assert effect_row.effects[0].params["nested"] is not owner.effects[0].params["nested"]


def test_compiler_and_layout_carry_authored_identity_as_noncanonical_provenance(
    tmp_path: Path,
) -> None:
    """Deriving a repeated node's authored identity by parsing its instance ID must fail."""
    facade = build_facade()
    project = _project(tmp_path, cards="[{id: alpha}, {id: beta}]")
    compiled = facade._compiler.compile(
        project / "template", project / "data.yaml", "square", "en", None
    )
    assert compiled.document is not None
    repeated = [child for child in compiled.document.root.children if child.id.startswith("card[")]

    assert [(node.id, node.authored_node_id) for node in repeated] == [
        ("card[alpha]", "card"),
        ("card[beta]", "card"),
    ]
    layout = facade._registries.layouts.get("anchors").solve(
        compiled.document, facade._measure
    )
    repeated_layout = [
        child for child in layout.root.children if child.source_node_id.startswith("card[")
    ]
    assert [(node.source_node_id, node.authored_node_id) for node in repeated_layout] == [
        ("card[alpha]", "card"),
        ("card[beta]", "card"),
    ]


def test_rendered_tree_uses_instances_solver_paint_order_and_authored_provenance(
    tmp_path: Path,
) -> None:
    """Re-expanding definitions or presenting source order instead of paint order must fail."""
    facade = build_facade()
    project = _project(
        tmp_path,
        cards="[{id: alpha}, {id: beta}]",
        show_badge=True,
    )

    report = facade.layer_tree(
        project=project, mode="rendered", format_name="square", locale="en"
    )
    repeated = facade.layer_tree(
        project=project, mode="rendered", format_name="square", locale="en"
    )

    assert report.ok
    assert report.model_dump(mode="json") == repeated.model_dump(mode="json")
    assert report.root is not None
    assert [child.id for child in report.root.children] == [
        "invisible",
        "foreground",
        "badge",
        "card[beta]",
        "card[alpha]",
        "panel",
        "background",
    ]
    by_id = {child.id: child for child in report.root.children}
    beta = by_id["card[beta]"]
    assert (
        beta.authored_id,
        beta.instance_id,
        beta.parent_id,
        beta.authored_index,
        beta.paint_index,
        beta.z,
        beta.origin,
    ) == ("card", "card[beta]", "root", 2, 3, 2, "repeat")
    assert beta.bounds_pt is not None and beta.paint_bounds_pt is not None
    assert beta.bounds_px == beta.bounds_pt
    assert beta.absolute_transform == (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    assert beta.source is not None
    assert beta.source.keypath == "root.children[2].node"
    assert by_id["foreground"].editable is False
    assert by_id["invisible"].visible is False
    assert by_id["invisible"].hit_testable is False
    assert all(child.id not in {"card", "missing"} for child in report.root.children)


def test_nested_rotations_report_cumulative_canvas_geometry_and_hit_bounds(
    tmp_path: Path,
) -> None:
    """Ignoring either rotated ancestor must move selection away from rendered pixels."""
    facade = build_facade()
    project = _nested_rotation_project(tmp_path)

    tree = facade.layer_tree(
        project=project, mode="rendered", format_name="square", locale="en"
    )

    assert tree.ok, [diagnostic.model_dump() for diagnostic in tree.diagnostics]
    assert tree.root is not None
    outer = next(child for child in tree.root.children if child.id == "outer")
    inner = next(child for child in outer.children if child.id == "inner")
    child = next(row for row in inner.children if row.id == "child")
    assert child.absolute_transform == pytest.approx((-1.0, 0.0, 0.0, -1.0, 160.0, 140.0))
    assert child.bounds_pt == pytest.approx((95.0, 65.0, 10.0, 20.0))
    assert child.paint_bounds_pt == pytest.approx((95.0, 65.0, 10.0, 20.0))

    layout = facade.inspect_layout(project / "template", None, "square", "en")
    assert layout.root is not None
    layout_outer = next(row for row in layout.root.children if row.id == "outer")
    layout_inner = next(row for row in layout_outer.children if row.id == "inner")
    layout_child = next(row for row in layout_inner.children if row.id == "child")
    assert layout_child.absolute_transform == pytest.approx(child.absolute_transform)
    assert layout_child.bounds_pt == pytest.approx(child.bounds_pt)
    assert layout_child.paint_bounds_pt == pytest.approx(child.paint_bounds_pt)

    hit = facade.hit_test(
        project=project,
        x_pt=100.0,
        y_pt=70.0,
        format_name="square",
        locale="en",
    )

    selected = next(candidate for candidate in hit.candidates if candidate.id == "child")
    assert selected.bounds_pt == pytest.approx((95.0, 65.0, 10.0, 20.0))
    assert selected.paint_bounds_pt == pytest.approx((95.0, 65.0, 10.0, 20.0))


def test_layer_trees_use_effective_format_locale_ast_and_shared_patch_sources(
    tmp_path: Path,
) -> None:
    """Re-reading the unpatched root must disagree with the requested compiler target."""
    facade = build_facade()
    project = _target_patch_project(tmp_path)

    authored = facade.layer_tree(
        project=project, mode="authored", format_name="square", locale="fa"
    )
    rendered = facade.layer_tree(
        project=project, mode="rendered", format_name="square", locale="fa"
    )
    baseline = facade.layer_tree(
        project=project, mode="authored", format_name="story", locale="en"
    )

    assert authored.ok and rendered.ok and baseline.ok
    assert authored.root is not None and rendered.root is not None and baseline.root is not None
    authored_by_id = {row.id: row for row in authored.root.children}
    rendered_by_id = {row.id: row for row in rendered.root.children}
    assert set(authored_by_id) == {
        "base",
        "move",
        "anchor",
        "project-remove",
        "format-only",
        "locale-only",
    }
    assert (authored_by_id["base"].z, authored_by_id["base"].visible) == (7, False)
    assert set(row.id for row in baseline.root.children) == {
        "base",
        "move",
        "anchor",
        "format-remove",
        "project-remove",
    }

    template_file = project / "template" / "template.yaml"
    formats_file = project / "template" / "formats.yaml"
    locales_file = project / "template" / "locales.yaml"
    base_source = authored_by_id["base"].source
    format_source = authored_by_id["format-only"].source
    locale_source = authored_by_id["locale-only"].source
    assert base_source is not None and Path(base_source.file) == template_file
    assert base_source.keypath == "root.children[0]" and base_source.line is not None
    assert format_source is not None and Path(format_source.file) == formats_file
    assert format_source.keypath == "formats.square.patch[2].node"
    assert format_source.line is not None
    assert locale_source is not None and Path(locale_source.file) == locales_file
    assert locale_source.keypath == "locales.fa.patch[1].node" and locale_source.line is not None
    for node_id in ("base", "format-only", "locale-only"):
        assert rendered_by_id[node_id].source == authored_by_id[node_id].source


def test_layer_trees_apply_project_patch_set_remove_and_reorder_with_provenance(
    tmp_path: Path,
) -> None:
    """Project overrides must define the hierarchy consumed by both desktop modes."""
    facade = build_facade()
    project = _target_patch_project(tmp_path)
    overrides = project / "overrides"
    overrides.mkdir()
    patch_file = overrides / "template.patch.yaml"
    patch_file.write_text(
        """- set: nodes.base.z
  value: 9
- remove: nodes.project-remove
- remove: nodes.move
- insert_after: nodes.anchor
  node:
    id: move
    type: shape
    shape: rect
    constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: 10pt, h: 10pt}}
- insert_before: nodes.anchor
  node:
    id: inserted
    type: shape
    shape: rect
    constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: 10pt, h: 10pt}}
""",
        encoding="utf-8",
    )

    authored = facade.layer_tree(
        project=project, mode="authored", format_name="story", locale="en"
    )
    rendered = facade.layer_tree(
        project=project, mode="rendered", format_name="story", locale="en"
    )

    assert authored.ok and rendered.ok
    assert authored.root is not None and rendered.root is not None
    assert [(row.id, row.authored_index) for row in authored.root.children] == [
        ("base", 0),
        ("format-remove", 4),
        ("move", 3),
        ("anchor", 2),
        ("inserted", 1),
    ]
    assert [(row.id, row.authored_index) for row in rendered.root.children] == [
        ("base", 0),
        ("format-remove", 4),
        ("move", 3),
        ("anchor", 2),
        ("inserted", 1),
    ]
    assert all(row.id != "project-remove" for row in authored.root.children)
    authored_by_id = {row.id: row for row in authored.root.children}
    rendered_by_id = {row.id: row for row in rendered.root.children}
    assert authored_by_id["base"].z == rendered_by_id["base"].z == 9
    unchanged_source = authored_by_id["format-remove"].source
    assert unchanged_source is not None
    assert Path(unchanged_source.file) == project / "template" / "template.yaml"
    assert unchanged_source.keypath == "root.children[3]"
    for node_id, patch_index in (("move", 3), ("inserted", 4)):
        source = authored_by_id[node_id].source
        assert source is not None and Path(source.file) == patch_file
        assert source.keypath == f"project.patch[{patch_index}].node"
        assert source.line is not None
        assert rendered_by_id[node_id].source == source


def test_project_dpi_drives_layer_and_hit_pixel_projections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Using the template canvas DPI must disagree with render_project's effective output."""
    monkeypatch.delenv("ARCAVEX_DPI", raising=False)
    project = _project(tmp_path)
    manifest = project / "project.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8") + "dpi: 144\n",
        encoding="utf-8",
    )
    facade = build_facade()

    tree = facade.layer_tree(
        project=project,
        mode="rendered",
        format_name="square",
        locale="en",
    )
    hit = facade.hit_test(
        project=project,
        x_pt=10.0,
        y_pt=10.0,
        format_name="square",
        locale="en",
    )

    assert tree.root is not None
    background = next(row for row in tree.root.children if row.id == "background")
    assert (tree.dpi, tree.canvas_pt, tree.canvas_px) == (144, (200.0, 200.0), (400, 400))
    assert background.bounds_pt == pytest.approx((0.0, 0.0, 200.0, 200.0))
    assert background.bounds_px == pytest.approx((0.0, 0.0, 400.0, 400.0))
    assert background.paint_bounds_px == pytest.approx((0.0, 0.0, 400.0, 400.0))
    assert hit.point_pt == (10.0, 10.0)
    assert hit.point_px == (20.0, 20.0)


def test_project_without_formats_matches_render_project_diagnostic(
    tmp_path: Path,
) -> None:
    """Desktop target selection must not turn an empty format list into an IndexError."""
    project = _project(tmp_path)
    manifest = project / "project.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace("formats: [square]", "formats: []"),
        encoding="utf-8",
    )
    facade = build_facade()

    run = facade.render_project(project=project)
    tree = facade.layer_tree(project=project, mode="authored")
    hit = facade.hit_test(project=project, x_pt=0.0, y_pt=0.0)

    assert not run.ok and len(run.diagnostics) == 1
    expected = run.diagnostics[0]
    assert expected.code == "ARC-PRJ-002"
    for report in (tree, hit):
        assert not report.ok
        assert report.diagnostics == [expected]


def test_authored_repeat_definition_is_invariant_for_zero_or_one_instance(
    tmp_path: Path,
) -> None:
    """A singleton repeat must not leak one rendered instance into definition mode."""
    facade = build_facade()
    empty = facade.layer_tree(
        project=_project(tmp_path / "empty", cards="[]"),
        mode="authored",
        format_name="square",
        locale="en",
    )
    singleton = facade.layer_tree(
        project=_project(tmp_path / "single", cards="[{id: only}]"),
        mode="authored",
        format_name="square",
        locale="en",
    )
    assert empty.root is not None and singleton.root is not None
    empty_card = next(child for child in empty.root.children if child.id == "card")
    singleton_card = next(child for child in singleton.root.children if child.id == "card")

    for card in (empty_card, singleton_card):
        assert card.id == "card"
        assert card.authored_id == "card"
        assert card.instance_id is None
        assert card.paint_index is None
        assert card.bounds_pt is None
        assert card.paint_bounds_pt is None
        assert card.absolute_transform is None
        assert card.hit_testable is False
        effect = next(child for child in card.children if child.kind == "effect")
        assert effect.effects[0].category is None


def test_authored_tree_survives_compile_diagnostics(tmp_path: Path) -> None:
    """Definition browsing must remain useful when the active target does not compile."""
    project = _project(tmp_path)
    template = project / "template" / "template.yaml"
    template.write_text(
        template.read_text(encoding="utf-8").replace("name: blur", "name: missing-effect"),
        encoding="utf-8",
    )

    report = build_facade().layer_tree(
        project=project, mode="authored", format_name="square", locale="en"
    )

    assert report.ok is False
    assert report.diagnostics
    assert report.root is not None
    assert {child.id for child in report.root.children} >= {"card", "foreground", "badge"}


def test_authored_tree_survives_layout_diagnostics_with_typed_render_failures(
    tmp_path: Path,
) -> None:
    """A layout failure must not discard the compiler's effective source hierarchy."""
    project = _project(tmp_path)
    template = project / "template" / "template.yaml"
    source = template.read_text(encoding="utf-8")
    source = source.replace(
        "constraints: {anchor: {top: parent.top, left: parent.left}, "
        "size: {w: fill, h: fill}}",
        "constraints: {anchor: {top: panel.bottom, left: parent.left}, "
        "size: {w: 10pt, h: 10pt}}",
        1,
    )
    source = source.replace(
        "constraints: {anchor: {top: parent.top, left: parent.left}, "
        "size: {w: 100pt, h: 100pt}}",
        "constraints: {anchor: {top: background.bottom, left: parent.left}, "
        "size: {w: 100pt, h: 100pt}}",
        1,
    )
    template.write_text(source, encoding="utf-8")
    facade = build_facade()

    authored = facade.layer_tree(
        project=project, mode="authored", format_name="square", locale="en"
    )
    rendered = facade.layer_tree(
        project=project, mode="rendered", format_name="square", locale="en"
    )
    hit = facade.hit_test(
        project=project,
        x_pt=12.0,
        y_pt=34.0,
        format_name="square",
        locale="en",
    )

    assert isinstance(authored, api.LayerTreeReport)
    assert not authored.ok
    assert authored.mode == "authored"
    assert authored.root is not None
    assert {child.id for child in authored.root.children} >= {"background", "panel"}
    assert [diagnostic.code for diagnostic in authored.diagnostics] == ["ARC-LAY-052"]
    assert authored.diagnostics[0].source is not None

    assert isinstance(rendered, api.LayerTreeReport)
    assert not rendered.ok
    assert rendered.mode == "rendered"
    assert rendered.root is None
    assert [diagnostic.code for diagnostic in rendered.diagnostics] == ["ARC-LAY-052"]

    assert isinstance(hit, api.HitTestReport)
    assert not hit.ok
    assert hit.point_pt == (12.0, 34.0)
    assert hit.candidates == []
    assert [diagnostic.code for diagnostic in hit.diagnostics] == ["ARC-LAY-052"]


def test_authored_tree_preserves_unknown_node_kind_with_compile_diagnostics(
    tmp_path: Path,
) -> None:
    """A forward/invalid source kind must remain inspectable even though it cannot render."""
    project = _project(tmp_path)
    template = project / "template" / "template.yaml"
    template.write_text(
        template.read_text(encoding="utf-8").replace(
            "id: background\n      type: shape",
            "id: background\n      type: future-shape",
        ),
        encoding="utf-8",
    )

    report = build_facade().layer_tree(
        project=project, mode="authored", format_name="square", locale="en"
    )

    assert not report.ok
    assert report.root is not None
    background = next(child for child in report.root.children if child.id == "background")
    assert background.kind == "future-shape"


def test_layer_tree_and_hit_test_open_project_read_only(tmp_path: Path) -> None:
    """Inspection must not create metadata, caches, or rewrite any project-owned input."""
    project = _project(tmp_path, cards="[{id: alpha}]")
    before = _project_state(project)
    facade = build_facade()

    assert facade.layer_tree(project=project, mode="authored", format_name="square").root
    assert facade.layer_tree(project=project, mode="rendered", format_name="square").root
    assert facade.hit_test(
        project=project, x_pt=1.0, y_pt=1.0, format_name="square"
    ).ok

    assert _project_state(project) == before
