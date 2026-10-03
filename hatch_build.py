"""Embed the same engine identity and skill in wheels and source distributions."""

from __future__ import annotations

import runpy
import tempfile
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):  # noqa: ANN001
        if version == "editable":
            return
        root = Path(self.root)
        stage = runpy.run_path(str(root / "packaging" / "payload.py"))["stage_payload"]
        self._payload = tempfile.TemporaryDirectory(prefix="arcavex-payload-")
        payload = stage(root, Path(self._payload.name))
        if self.target_name == "wheel":
            build_data["force_include"][str(payload / "build.json")] = "arcavex/_bundled/build.json"
            build_data["force_include"][str(payload / "skill")] = "arcavex/_bundled/skill"
        else:
            build_data["force_include"][str(payload / "build.json")] = "build-identity.json"

    def finalize(self, version, build_data, artifact_path):  # noqa: ANN001
        if hasattr(self, "_payload"):
            self._payload.cleanup()
