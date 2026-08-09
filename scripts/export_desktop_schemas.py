"""Export deterministic JSON Schemas for Arcavex desktop contracts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas" / "desktop"
FIXTURE_FILENAME = "desktop-contract-fixtures.json"


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

    return {
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


def export_schemas(schema_dir: Path = SCHEMA_DIR) -> set[str]:
    """Write canonical desktop schemas and return their stable filenames."""
    schema_dir.mkdir(parents=True, exist_ok=True)
    for filename, model in _schema_models().items():
        payload = json.dumps(
            model.model_json_schema(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8") + b"\n"
        (schema_dir / filename).write_bytes(payload)
    return set(_schema_models())


def _fixture_inputs() -> dict[str, dict[str, object]]:
    """Return minimal valid report inputs before Pydantic performs canonical serialization."""
    fixture = {"ok": True}
    return {
        "engine-handshake.schema.json": {
            **fixture,
            "identity": {"engine_version": "0.0.0-fixture"},
            "mcp_contract_version": "2025-06-18",
            "accepted_ir_versions": ["1.0"],
            "produced_ir_version": "1.0",
            "extension_sdk_version": "1.0",
            "capabilities": [],
            "paths": {
                "home": "/fixture",
                "assets": "/fixture/assets",
                "cache": "/fixture/cache",
                "extensions": "/fixture/extensions",
                "fonts": "/fixture/fonts",
                "styles": "/fixture/styles",
                "templates": "/fixture/templates",
            },
            "doctor": {"ok": True, "engine_version": "0.0.0-fixture", "checks": []},
        },
        **{
            filename: dict(fixture)
            for filename in _schema_models()
            if filename != "engine-handshake.schema.json"
        },
    }


def export_contract_fixtures(schema_dir: Path = SCHEMA_DIR) -> dict[str, object]:
    """Serialize valid Pydantic reports for TypeScript runtime-guard fixtures."""
    schema_dir.mkdir(parents=True, exist_ok=True)
    models = _schema_models()
    inputs = _fixture_inputs()
    fixtures = {
        filename: models[filename].model_validate(inputs[filename]).model_dump(mode="json")
        for filename in models
    }
    payload = (
        json.dumps(fixtures, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        + b"\n"
    )
    (schema_dir / FIXTURE_FILENAME).write_bytes(payload)
    return fixtures


def main() -> int:
    """Write every desktop schema with canonical ordering and one final LF newline."""
    export_schemas()
    export_contract_fixtures()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
