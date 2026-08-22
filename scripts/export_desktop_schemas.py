"""Export deterministic JSON Schemas and populated fixtures for Arcavex desktop contracts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas" / "desktop"
FIXTURE_FILENAME = "desktop-contract-fixtures.json"

# A canonical absolute project path is by definition platform-specific, so the checked-in
# fixture carries this placeholder and every consumer materializes it before validating.
PROJECT_PATH_TOKEN = "<arcavex-fixture-project>"


def canonical_fixture_project_path() -> str:
    """Return the platform-canonical absolute path the fixture placeholder stands for."""
    return str(Path(ROOT.anchor) / "arcavex-fixture-project")


def _substitute(payload: Any, source: str, replacement: str) -> Any:
    """Rewrite one exact string value everywhere it appears in a JSON-shaped payload."""
    if isinstance(payload, str):
        return replacement if payload == source else payload
    if isinstance(payload, list):
        return [_substitute(item, source, replacement) for item in payload]
    if isinstance(payload, dict):
        return {key: _substitute(value, source, replacement) for key, value in payload.items()}
    return payload


def materialize_fixture(payload: Any) -> Any:
    """Replace the project-path placeholder with the path this platform can canonicalize."""
    return _substitute(payload, PROJECT_PATH_TOKEN, canonical_fixture_project_path())


def tokenize_fixture(payload: Any) -> Any:
    """Replace this platform's canonical project path with the portable placeholder."""
    return _substitute(payload, canonical_fixture_project_path(), PROJECT_PATH_TOKEN)


def _schema_models() -> dict[str, type[BaseModel]]:
    """Import contract models after making a source checkout directly runnable."""
    source = str(ROOT / "src")
    if source not in sys.path:
        sys.path.insert(0, source)
    from arcavex.kernel.api import (
        CheckResult,
        EngineHandshakeReport,
        HitTestReport,
        LayerTreeReport,
        PreviewProjectReport,
        ProjectPolicyReport,
        ProjectSnapshotReport,
        ProjectUIMetadataReport,
        ProposalActionReport,
        ProposalListReport,
    )
    from arcavex.kernel.editor import HistoryReport, SemanticTransaction, TransactionReport

    return {
        # The transaction schema is exported as well as the reports: the desktop composes one and
        # re-submits the inverse the engine returns, so it is a request contract, not only a wire
        # format the engine happens to emit.
        "editor-history.schema.json": HistoryReport,
        "editor-transaction-report.schema.json": TransactionReport,
        "editor-transaction.schema.json": SemanticTransaction,
        "engine-handshake.schema.json": EngineHandshakeReport,
        "hit-test.schema.json": HitTestReport,
        "layer-tree.schema.json": LayerTreeReport,
        "project-policy.schema.json": ProjectPolicyReport,
        "project-preview.schema.json": PreviewProjectReport,
        "project-proposal-action.schema.json": ProposalActionReport,
        "project-proposal-list.schema.json": ProposalListReport,
        "project-snapshot.schema.json": ProjectSnapshotReport,
        "project-ui-metadata.schema.json": ProjectUIMetadataReport,
        "project-validate.schema.json": CheckResult,
    }


def _canonical_json(payload: object) -> bytes:
    """Serialize with sorted keys, two-space indent, UTF-8, and one trailing newline."""
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    )


_SHA256 = "9f" * 32
_OTHER_SHA256 = "3c" * 32
_COMMAND_ID = "9f2c1d7e-4b3a-4c58-9e21-0d7a6f5b8c34"
_CREATED_AT = "2026-01-02T03:04:05.678901Z"

_DIAGNOSTIC = {
    "code": "ARC-PRJ-001",
    "severity": "warning",
    "message": "Fixture diagnostic covering the located branch.",
    "source": {"file": "project.yaml", "keypath": "targets[0]", "line": 12, "column": 3},
    "hint": "Fixtures exercise every optional diagnostic field.",
}

_LEAF_LAYER = {
    "id": "title#0",
    "authored_id": "title",
    "instance_id": "title#0",
    "parent_id": "root",
    "authored_index": 0,
    "paint_index": 1,
    "z": 10,
    "kind": "text",
    "origin": "repeat",
    "collection": "items",
    "loop_var": "item",
    "key": "0",
    "display_name": "Title",
    "color": "#3A7BD5",
    "bounds_pt": [10.0, 20.0, 300.0, 64.0],
    "bounds_px": [20.0, 40.0, 600.0, 128.0],
    "paint_bounds_pt": [8.0, 18.0, 304.0, 68.0],
    "paint_bounds_px": [16.0, 36.0, 608.0, 136.0],
    "absolute_transform": [1.0, 0.0, 0.0, 1.0, 10.0, 20.0],
    "rotate_deg": 1.5,
    "overflow": {
        "kind": "shrink",
        "measured_w_pt": 310.0,
        "measured_h_pt": 70.0,
        "box_w_pt": 300.0,
        "box_h_pt": 64.0,
    },
    "source": {"file": "template.yaml", "keypath": "layers.title", "line": 42},
    "effects": [
        {
            "index": 0,
            "name": "drop_shadow",
            "category": "raster",
            "params": {"blur_pt": 4.0, "color": "#00000055", "enabled": True},
        }
    ],
    "mask": {"component": "rounded_rect", "params": {"radius_pt": 12.0}},
}


def _desktop_capabilities() -> list[str]:
    """Read the engine's real capability names so fixtures can never advertise invented ones."""
    source = str(ROOT / "src")
    if source not in sys.path:
        sys.path.insert(0, source)
    from arcavex.services.desktop import DESKTOP_CAPABILITIES

    return list(DESKTOP_CAPABILITIES)


def _fixture_inputs() -> dict[str, dict[str, Any]]:
    """Return populated report inputs that reach every union, map, tuple, and pattern branch."""
    return {
        "engine-handshake.schema.json": {
            "ok": True,
            "identity": {
                "engine_version": "0.0.0-fixture",
                "build_commit": _SHA256[:40],
                "artifact_path": "/fixture/bin/arcavex",
                "artifact_sha256": _SHA256,
            },
            "mcp_contract_version": "2025-06-18",
            "accepted_ir_versions": ["1.0"],
            "produced_ir_version": "1.0",
            "extension_sdk_version": "1.0",
            "capabilities": _desktop_capabilities(),
            "paths": {
                "home": "/fixture",
                "assets": "/fixture/assets",
                "cache": "/fixture/cache",
                "extensions": "/fixture/extensions",
                "fonts": "/fixture/fonts",
                "styles": "/fixture/styles",
                "templates": "/fixture/templates",
            },
            "doctor": {
                "ok": True,
                "engine_version": "0.0.0-fixture",
                "checks": [
                    {"name": "fonts", "status": "ok", "detail": "3 families"},
                    {
                        "name": "cache",
                        "status": "warn",
                        "detail": "cache directory is empty",
                        "hint": "Render once to populate it.",
                    },
                ],
            },
            "diagnostics": [_DIAGNOSTIC],
        },
        "hit-test.schema.json": {
            "ok": True,
            "format": "poster-a3",
            "locale": "fa-IR",
            "point_pt": [120.5, 240.25],
            "point_px": [241.0, 480.5],
            "candidates": [
                {
                    "id": "title#0",
                    "authored_id": "title",
                    "instance_id": "title#0",
                    "parent_id": "root",
                    "kind": "text",
                    "display_name": "Title",
                    "editable": True,
                    "locked": False,
                    "bounds_pt": [10.0, 20.0, 300.0, 64.0],
                    "paint_bounds_pt": [8.0, 18.0, 304.0, 68.0],
                }
            ],
            "diagnostics": [_DIAGNOSTIC],
        },
        "layer-tree.schema.json": {
            "ok": True,
            "mode": "rendered",
            "format": "poster-a3",
            "locale": "fa-IR",
            "canvas_pt": [842.0, 1191.0],
            "canvas_px": [1684, 2382],
            "dpi": 144,
            "root": {
                "id": "root",
                "authored_id": "root",
                "instance_id": "root#0",
                "authored_index": 0,
                "paint_index": 0,
                "kind": "group",
                "display_name": "Root",
                "locked": True,
                "editable": False,
                "hit_testable": False,
                "virtual": False,
                "children": [_LEAF_LAYER],
            },
            "diagnostics": [_DIAGNOSTIC],
        },
        "project-policy.schema.json": {
            "ok": True,
            "canonical_path": PROJECT_PATH_TOKEN,
            "policy": {"version": 1, "mode": "review", "extensions": "disabled"},
            "project_revision": _SHA256,
            "render_revision": _OTHER_SHA256,
            "diagnostics": [_DIAGNOSTIC],
        },
        "project-preview.schema.json": {
            "ok": True,
            "previews": [
                {
                    "ok": True,
                    "output_path": "/fixture/outputs/poster-a3.fa-IR.png",
                    "changed_file": "data.yaml",
                    "compile_ms": 12.5,
                    "render_ms": 84.25,
                    "content_sha256": _SHA256,
                    "inferred": {"format": "poster-a3", "locale": "fa-IR"},
                    "diagnostics": [_DIAGNOSTIC],
                }
            ],
            "diagnostics": [_DIAGNOSTIC],
        },
        "project-proposal-action.schema.json": {
            "ok": True,
            "canonical_path": PROJECT_PATH_TOKEN,
            "project_revision": _SHA256,
            "proposal": _proposal(),
            "diagnostics": [_DIAGNOSTIC],
        },
        "project-proposal-list.schema.json": {
            "ok": True,
            "canonical_path": PROJECT_PATH_TOKEN,
            "proposals": [_proposal(), _proposal(state="rejected")],
            "diagnostics": [_DIAGNOSTIC],
        },
        "project-snapshot.schema.json": {
            "ok": True,
            "canonical_path": PROJECT_PATH_TOKEN,
            "name": "fixture-project",
            "template": "poster/editorial",
            "style": "studio-dark",
            "data": "data.yaml",
            "dpi": 144,
            "formats": ["poster-a3", "story"],
            "locales": ["en-US", "fa-IR"],
            "targets": [
                {"format": "poster-a3", "locale": "fa-IR"},
                {"format": "story"},
            ],
            "default_target": {"format": "poster-a3", "locale": "en-US"},
            "status": "ready",
            "tags": ["fixture", "desktop"],
            "project_revision": _SHA256,
            "render_revision": _OTHER_SHA256,
            "project_manifest": [{"path": "project.yaml", "sha256": _SHA256, "bytes": 512}],
            "render_manifest": [{"path": "template.yaml", "sha256": _OTHER_SHA256, "bytes": 2048}],
            "source_files": [
                {
                    "path": "project.yaml",
                    "resolved_path": "project.yaml",
                    "role": "project",
                    "project_owned": True,
                    "sha256": _SHA256,
                },
                {
                    "path": "assets/logo.png",
                    "resolved_path": "/fixture/assets/logo.png",
                    "role": "asset",
                    "project_owned": False,
                },
            ],
            "capabilities": ["project.snapshot", "project.preview"],
            "diagnostics": [_DIAGNOSTIC],
        },
        "project-ui-metadata.schema.json": {
            "ok": True,
            "canonical_path": PROJECT_PATH_TOKEN,
            "metadata": {
                "version": 1,
                "layers": {
                    "title": {"display_name": "Headline", "locked": True, "color": "#3A7BD5"},
                    "logo": {"locked": False},
                },
                "workspace": {
                    "active_format": "poster-a3",
                    "active_locale": "fa-IR",
                    "layer_tree_mode": "rendered",
                    "selected_layer_ids": ["title", "logo"],
                },
            },
            "project_revision": _SHA256,
            "render_revision": _OTHER_SHA256,
            "diagnostics": [_DIAGNOSTIC],
        },
        "project-validate.schema.json": {"ok": False, "diagnostics": [_DIAGNOSTIC]},
        "editor-transaction.schema.json": _editor_transaction(),
        "editor-transaction-report.schema.json": {
            "ok": True,
            "command_id": _COMMAND_ID,
            "canonical_path": PROJECT_PATH_TOKEN,
            "project_revision": _OTHER_SHA256,
            "render_revision": _SHA256,
            "changed": [
                {"path": "template.yaml", "change": "modified"},
                {"path": "overrides/square.patch.yaml", "change": "created"},
                {"path": "overrides/story.patch.yaml", "change": "deleted"},
            ],
            "changed_layer_ids": ["title", "subtitle"],
            # The success path carries an inverse and no conflict, because a report that claimed
            # both would describe a state the engine cannot produce.
            "inverse": _editor_transaction(
                command_id="0a3f6b21-5c7d-4e9a-8b12-3f4d5e6a7b8c",
                base_project_revision=_OTHER_SHA256,
            ),
            "diagnostics": [_DIAGNOSTIC],
        },
        "editor-history.schema.json": {
            "ok": True,
            "canonical_path": PROJECT_PATH_TOKEN,
            "entries": [
                {
                    "command_id": _COMMAND_ID,
                    "actor": {"id": "desktop", "display_name": "Arcavex Desktop"},
                    "summary": "Set text of 'title'",
                    "before_project_revision": _SHA256,
                    "after_project_revision": _OTHER_SHA256,
                    "created_at": _CREATED_AT,
                }
            ],
            "can_undo": True,
            "can_redo": False,
            "branched_by_external_edit": True,
            "diagnostics": [_DIAGNOSTIC],
        },
    }


def _editor_transaction(**overrides: Any) -> dict[str, Any]:
    """One transaction carrying every command kind, so each union member reaches a fixture."""
    payload: dict[str, Any] = {
        "version": 1,
        "command_id": _COMMAND_ID,
        "project_path": PROJECT_PATH_TOKEN,
        "base_project_revision": _SHA256,
        "actor": {"id": "desktop", "display_name": "Arcavex Desktop"},
        "target": {"format": "poster-a3", "locale": "fa-IR"},
        "commands": [
            {"kind": "set_text", "layer_id": "title", "text": "Building professional bridges"},
            {
                "kind": "set_property",
                "layer_id": "title",
                "keypath": "style.font_size",
                "value": "48pt",
            },
            {"kind": "set_visibility", "layer_id": "badge", "visible": False},
            {"kind": "translate", "layer_ids": ["title", "subtitle"], "dx_pt": 12.5, "dy_pt": -4.0},
            {"kind": "resize", "layer_id": "photo", "w_pt": 320.0, "h_pt": 240.0},
            {"kind": "rotate", "layer_id": "badge", "degrees": 15.0},
            {"kind": "reorder", "layer_id": "badge", "parent_id": "root", "index": 2},
            {"kind": "reparent", "layer_id": "badge", "parent_id": "header", "index": 0},
            {"kind": "duplicate", "layer_id": "badge"},
            {"kind": "delete", "layer_ids": ["draft-note"]},
            {"kind": "group", "layer_ids": ["title", "subtitle"], "group_id": "headline"},
            {"kind": "set_display_name", "layer_id": "title", "display_name": "Headline"},
            {
                "kind": "set_effects",
                "layer_id": "photo",
                "effects": [
                    {"name": "halftone", "params": {"dot_pt": 2.0}, "enabled": True},
                    {"name": "grain", "params": {}, "enabled": False},
                ],
            },
            {
                "kind": "splice_children",
                "parent_id": "root",
                "index": 2,
                "remove_count": 1,
                "entries": [{"id": "badge", "type": "shape", "shape": "rect"}],
            },
        ],
    }
    payload.update(overrides)
    return payload


def _proposal(state: str = "pending") -> dict[str, Any]:
    """Return one queue record exercising UUID, SHA pattern, timestamp, and open maps."""
    return {
        "version": 1,
        "command_id": _COMMAND_ID,
        "project_path": PROJECT_PATH_TOKEN,
        "base_project_revision": _SHA256,
        "actor": {"id": "codex", "display_name": "Codex", "channel": "mcp"},
        "command_payload": {"op": "set_text", "layer": "title", "value": "Fixture"},
        "created_at": _CREATED_AT,
        "state": state,
        "rejection_reason": "Stale base revision." if state == "rejected" else None,
    }


def contract_fixtures() -> dict[str, Any]:
    """Serialize every report through Pydantic and hand back portable, tokenized payloads."""
    models = _schema_models()
    inputs = _fixture_inputs()
    return {
        filename: tokenize_fixture(
            models[filename].model_validate(materialize_fixture(inputs[filename])).model_dump(
                mode="json"
            )
        )
        for filename in models
    }


def rendered_payloads() -> dict[str, bytes]:
    """Return every managed filename mapped to the exact bytes it must contain."""
    payloads = {
        filename: _canonical_json(model.model_json_schema())
        for filename, model in _schema_models().items()
    }
    payloads[FIXTURE_FILENAME] = _canonical_json(contract_fixtures())
    return payloads


def export_schemas(schema_dir: Path = SCHEMA_DIR) -> set[str]:
    """Write canonical desktop schemas and return their stable filenames."""
    schema_dir.mkdir(parents=True, exist_ok=True)
    filenames = set(_schema_models())
    for filename, payload in rendered_payloads().items():
        if filename in filenames:
            (schema_dir / filename).write_bytes(payload)
    return filenames


def export_contract_fixtures(schema_dir: Path = SCHEMA_DIR) -> dict[str, Any]:
    """Write the runtime-guard fixture file and return its tokenized contents."""
    schema_dir.mkdir(parents=True, exist_ok=True)
    fixtures = contract_fixtures()
    (schema_dir / FIXTURE_FILENAME).write_bytes(_canonical_json(fixtures))
    return fixtures


def check_schemas(schema_dir: Path) -> list[str]:
    """Compare a directory against the canonical export without writing to it."""
    expected = rendered_payloads()
    present = {
        path.name
        for path in schema_dir.iterdir()
        if path.is_file() and (path.name.endswith(".schema.json") or path.name == FIXTURE_FILENAME)
    }
    differences = [f"missing: {name}" for name in sorted(set(expected) - present)]
    differences += [f"unexpected: {name}" for name in sorted(present - set(expected))]
    differences += [
        f"stale: {name}"
        for name in sorted(set(expected) & present)
        if (schema_dir / name).read_bytes() != expected[name]
    ]
    return differences


def main(argv: list[str] | None = None) -> int:
    """Write, or in check mode only compare, every desktop schema and fixture payload."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema-dir", type=Path, default=SCHEMA_DIR)
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare the directory against a fresh export instead of writing it",
    )
    arguments = parser.parse_args(argv)

    if not arguments.check:
        export_schemas(arguments.schema_dir)
        export_contract_fixtures(arguments.schema_dir)
        return 0

    if not arguments.schema_dir.is_dir():
        print(f"schema directory does not exist: {arguments.schema_dir}", file=sys.stderr)
        return 1
    differences = check_schemas(arguments.schema_dir)
    for difference in differences:
        print(f"desktop contract drift: {difference}", file=sys.stderr)
    return 1 if differences else 0


if __name__ == "__main__":
    raise SystemExit(main())
