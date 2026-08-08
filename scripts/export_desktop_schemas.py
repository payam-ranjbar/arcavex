"""Export deterministic JSON Schemas for Arcavex desktop contracts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas" / "desktop"


def _schema_models() -> dict[str, type[BaseModel]]:
    """Import contract models after making a source checkout directly runnable."""
    source = str(ROOT / "src")
    if source not in sys.path:
        sys.path.insert(0, source)
    from arcavex.kernel.api import EngineHandshakeReport

    return {"engine-handshake.schema.json": EngineHandshakeReport}


def main() -> int:
    """Write every desktop schema with canonical ordering and one final LF newline."""
    SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
    for filename, model in _schema_models().items():
        payload = json.dumps(
            model.model_json_schema(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8") + b"\n"
        (SCHEMA_DIR / filename).write_bytes(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
