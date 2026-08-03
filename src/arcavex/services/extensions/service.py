"""The extension authoring/lifecycle service backing ``arcavex ext`` and the facade (spec §7.2).

Implements scaffold / validate / test / add / enable / disable / list over the added-extension
state under the Arcavex home. It returns versioned kernel result models and never raises across
the facade boundary. ``test`` runs the extension's golden fixtures in a **subprocess** so a crash
in the effect is contained (spec §8.5) — that is crash containment for reliability, not a security
sandbox: the code is trusted local code (spec §7.3).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from arcavex.kernel.api import (
    ExtensionActionReport,
    ExtensionComponentInfo,
    ExtensionListReport,
    ExtensionScaffoldReport,
    ExtensionSummary,
    ExtensionTestReport,
    ExtensionValidateReport,
)
from arcavex.kernel.diagnostics import Diagnostic, diagnostic
from arcavex.sdk.registration import COMPONENT_KINDS
from arcavex.services.extensions.collision import TakenNames
from arcavex.services.extensions.manifest import parse_manifest
from arcavex.services.extensions.scaffold import scaffold_files
from arcavex.services.extensions.state import ExtensionState, source_path
from arcavex.services.extensions.validator import validate_extension

# The conventional test script an extension ships; ``ext test`` runs it in a subprocess.
GOLDEN_TEST_NAME = "golden_test.py"
_TEST_TIMEOUT_S = 120
# Pin UTF-8 on both ends of the test pipe. Without it the child encodes its output with the console
# codepage and the harness decodes it with the locale's — cp1252 on the reference Windows platform
# (docs/known-limitations.md) — so one non-ASCII character in a test's output broke the harness
# rather than the extension. The child gets these on top of the inherited environment.
_CHILD_UTF8_ENV = {"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}


class ExtensionService:
    """Local-extension lifecycle over the state directory; all methods are boundary-safe."""

    def __init__(
        self,
        env: dict[str, str] | None = None,
        builtin_names: dict[str, frozenset[str]] | None = None,
    ) -> None:
        """Bind the environment and the built-in component names for collision detection.

        ``builtin_names`` maps each component kind to the names the built-ins occupy; bootstrap
        supplies it (the composition root is the only layer that may see the built-ins). Without
        it, ``validate``/``add`` still catch collisions against other added extensions, and the
        loader remains the backstop for built-in collisions at engine start.
        """
        self._env = env
        self._state = ExtensionState(env)
        self._builtin_names = builtin_names or {}

    def _taken_names(self, exclude: str | None) -> TakenNames:
        """Build the name -> incumbent-label map for every kind, excluding one extension.

        Merges the built-in names (labelled ``built-in 'name'``) with the components every other
        added extension declares (labelled ``extension 'ext-name'``). ``exclude`` drops the
        extension being validated/added so it never collides with its own stored copy.
        """
        taken: TakenNames = {}
        for kind, names in self._builtin_names.items():
            slot = taken.setdefault(kind, {})
            for n in names:
                slot[n] = f"built-in {n!r}"
        for record in self._state.records():
            if record.name == exclude:
                continue
            manifest, _diags = parse_manifest(source_path(record.name, self._env))
            if manifest is None:
                continue
            for comp in manifest.components:
                # A built-in incumbent wins the label (it is registered first); setdefault keeps it.
                taken.setdefault(comp.kind, {}).setdefault(
                    comp.name, f"extension {record.name!r}"
                )
        return taken

    # ---------------------------------------------------------------------- list
    def list_extensions(
        self, load_diagnostics: list[Diagnostic] | None = None
    ) -> ExtensionListReport:
        """List every added extension with its enabled state and declared components."""
        summaries: list[ExtensionSummary] = []
        for record in self._state.records():
            components: list[ExtensionComponentInfo] = []
            manifest, _diags = parse_manifest(source_path(record.name, self._env))
            if manifest is not None:
                components = [
                    ExtensionComponentInfo(kind=c.kind, name=c.name) for c in manifest.components
                ]
            summaries.append(
                ExtensionSummary(
                    name=record.name,
                    version=record.version,
                    enabled=record.enabled,
                    components=components,
                )
            )
        return ExtensionListReport(
            ok=True, extensions=summaries, load_diagnostics=list(load_diagnostics or [])
        )

    # ------------------------------------------------------------------ scaffold
    def scaffold_extension(
        self, kind: str, target: Path, name: str | None = None
    ) -> ExtensionScaffoldReport:
        """Write a complete, immediately-valid extension directory of ``kind`` at ``target``."""
        target = Path(target)
        if kind not in COMPONENT_KINDS:
            allowed = ", ".join(COMPONENT_KINDS)
            return ExtensionScaffoldReport(
                ok=False,
                diagnostics=[
                    diagnostic(
                        "ARC-EXT-013",
                        f"Unknown component kind {kind!r}",
                        hint=f"kind must be one of: {allowed}.",
                    )
                ],
            )
        if target.exists() and any(target.iterdir()):
            return ExtensionScaffoldReport(
                ok=False,
                diagnostics=[
                    diagnostic(
                        "ARC-EXT-060",
                        f"Scaffold target already exists and is not empty: {target}",
                        file=str(target),
                        hint="Choose a new directory, or remove the existing one first.",
                    )
                ],
            )
        ext_name = name or target.name
        files = scaffold_files(ext_name, kind)
        target.mkdir(parents=True, exist_ok=True)
        for filename, contents in files.items():
            (target / filename).write_text(contents, encoding="utf-8")
        return ExtensionScaffoldReport(
            ok=True,
            path=str(target),
            kind=kind,
            name=ext_name,
            files=sorted(files),
        )

    # ------------------------------------------------------------------ validate
    def validate_extension(self, path: Path) -> ExtensionValidateReport:
        """Run every validation gate over an extension directory. Never raises."""
        ext_dir = Path(path)
        manifest, _diags = parse_manifest(ext_dir)
        exclude = manifest.name if manifest is not None else None
        try:
            result = validate_extension(ext_dir, taken=self._taken_names(exclude))
        except Exception as exc:  # noqa: BLE001 - boundary must not leak
            return ExtensionValidateReport(
                ok=False,
                diagnostics=[
                    diagnostic(
                        "ARC-EXT-011",
                        f"Extension validation failed unexpectedly: {exc!r}",
                        file=str(path),
                        hint="Check the extension directory and manifest.",
                    )
                ],
            )
        return ExtensionValidateReport(
            ok=result.ok,
            name=result.name,
            components=result.components,
            diagnostics=result.diagnostics,
        )

    # ---------------------------------------------------------------------- test
    def test_extension(self, path: Path) -> ExtensionTestReport:
        """Validate the extension, then run its ``golden_test.py`` in a subprocess.

        ``test`` implies ``validate`` (DX-7): the golden test only exercises what it calls, so it
        cannot catch a disallowed import, a determinism-lint hit, or a bad param schema. Running
        validation first means a green ``ext test`` never gives false confidence about those gates.
        """
        ext_dir = Path(path)
        manifest, _diags = parse_manifest(ext_dir)
        name = manifest.name if manifest is not None else None
        exclude = manifest.name if manifest is not None else None
        validation = validate_extension(ext_dir, taken=self._taken_names(exclude))
        if not validation.ok:
            return ExtensionTestReport(ok=False, name=name, diagnostics=validation.diagnostics)
        test_file = ext_dir / GOLDEN_TEST_NAME
        if not test_file.is_file():
            return ExtensionTestReport(
                ok=False,
                name=name,
                diagnostics=[
                    diagnostic(
                        "ARC-EXT-052",
                        f"Extension has no {GOLDEN_TEST_NAME} to run",
                        file=str(ext_dir),
                        hint=f"Add a {GOLDEN_TEST_NAME} that drives a GoldenHarness and exits "
                        "non-zero on failure (the scaffold ships one).",
                    )
                ],
            )
        environ = self._env if self._env is not None else dict(os.environ)
        try:
            completed = subprocess.run(
                [sys.executable, GOLDEN_TEST_NAME],
                cwd=str(ext_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env={**environ, **_CHILD_UTF8_ENV},
                timeout=_TEST_TIMEOUT_S,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ExtensionTestReport(
                ok=False,
                name=name,
                output=f"timed out after {_TEST_TIMEOUT_S}s",
                diagnostics=[
                    diagnostic(
                        "ARC-EXT-052",
                        "Extension golden test timed out",
                        file=str(ext_dir),
                        hint="The test should be a fast, bounded golden run.",
                    )
                ],
            )
        except OSError as exc:
            # The harness could not even start the child, so the extension's result is unknown.
            return self._harness_failure(
                ext_dir, name, f"Extension test harness could not start the test subprocess: {exc}"
            )
        if completed.stdout is None or completed.stderr is None:
            # A reader thread died mid-stream. Decoding can no longer cause that (errors="replace"
            # never raises), but a pipe-level error still can, and it used to surface as empty
            # output attached to a confident ARC-EXT-052.
            return self._harness_failure(
                ext_dir, name, "Extension test harness could not read the test subprocess output"
            )
        output = (completed.stdout or "") + (completed.stderr or "")
        passed = completed.returncode == 0
        diagnostics: list[Diagnostic] = []
        if not passed:
            diagnostics.append(
                diagnostic(
                    "ARC-EXT-052",
                    f"Extension golden test failed (exit {completed.returncode})",
                    file=str(ext_dir),
                    hint="See the captured test output for the failing check.",
                )
            )
        return ExtensionTestReport(
            ok=passed, name=name, passed=passed, output=output.strip(), diagnostics=diagnostics
        )

    def _harness_failure(
        self, ext_dir: Path, name: str | None, message: str
    ) -> ExtensionTestReport:
        """Report an ``ext test`` failure the harness itself caused, apart from ARC-EXT-052.

        The extension's own result is unknown when the harness cannot run or read the child, so
        reporting ARC-EXT-052 there would falsely accuse the author of shipping a failing test.
        """
        return ExtensionTestReport(
            ok=False,
            name=name,
            diagnostics=[
                diagnostic(
                    "ARC-EXT-053",
                    message,
                    file=str(ext_dir),
                    hint="This is an Arcavex-side failure, not a failing test. Re-run the command; "
                    "if it persists, check the extension directory is readable and that Arcavex "
                    "can start a subprocess.",
                )
            ],
        )

    # ----------------------------------------------------------------------- add
    def add_extension(self, path: Path) -> ExtensionActionReport:
        """Validate an extension and, if it passes, copy it into the state and record it disabled.

        Adding never enables (spec §3.3 lifecycle add → validate → disabled → enable); a re-add of
        an already-enabled extension preserves its enabled flag so updating its code and re-adding
        does not silently disable it.
        """
        ext_dir = Path(path)
        pre, _diags = parse_manifest(ext_dir)
        exclude = pre.name if pre is not None else None
        validation = validate_extension(ext_dir, taken=self._taken_names(exclude))
        if not validation.ok or validation.name is None:
            return ExtensionActionReport(
                ok=False, name=validation.name, diagnostics=validation.diagnostics
            )
        manifest, _diags = parse_manifest(ext_dir)
        assert manifest is not None  # validation.ok implies a parseable manifest
        prior = self._state.get(manifest.name)
        dest = source_path(manifest.name, self._env)
        try:
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(
                ext_dir, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
            )
        except OSError as exc:
            return ExtensionActionReport(
                ok=False,
                name=manifest.name,
                diagnostics=[
                    diagnostic(
                        "ARC-EXT-060",
                        f"Could not copy extension into the Arcavex home: {exc}",
                        file=str(dest),
                        hint="Check the Arcavex home is writable.",
                    )
                ],
            )
        enabled = prior.enabled if prior is not None else False
        record = self._state.add(manifest.name, manifest.version, enabled=enabled)
        return ExtensionActionReport(ok=True, name=record.name, enabled=record.enabled)

    # -------------------------------------------------------------------- enable
    def enable_extension(self, name: str) -> ExtensionActionReport:
        """Enable an added extension after re-validating its stored source (spec §3.3).

        Registration happens at the next process start; enabling only flips the flag. Re-validating
        here refuses to enable an extension whose stored source is broken, so a later engine start
        is not left reporting a load failure.
        """
        record = self._state.get(name)
        if record is None:
            return self._unknown(name)
        validation = validate_extension(
            source_path(name, self._env), taken=self._taken_names(name)
        )
        if not validation.ok:
            return ExtensionActionReport(
                ok=False,
                name=name,
                enabled=record.enabled,
                diagnostics=validation.diagnostics,
            )
        updated = self._state.set_enabled(name, True)
        assert updated is not None
        return ExtensionActionReport(ok=True, name=name, enabled=updated.enabled)

    # ------------------------------------------------------------------- disable
    def disable_extension(self, name: str) -> ExtensionActionReport:
        """Disable an added extension; the loader drops its registration on the next start."""
        record = self._state.get(name)
        if record is None:
            return self._unknown(name)
        updated = self._state.set_enabled(name, False)
        assert updated is not None
        return ExtensionActionReport(ok=True, name=name, enabled=updated.enabled)

    def _unknown(self, name: str) -> ExtensionActionReport:
        added = ", ".join(r.name for r in self._state.records()) or "(none)"
        return ExtensionActionReport(
            ok=False,
            name=name,
            diagnostics=[
                diagnostic(
                    "ARC-EXT-040",
                    f"No added extension named {name!r}",
                    hint=f"Add it first with 'arcavex ext add <path>'. Added: {added}.",
                )
            ],
        )


__all__ = ["ExtensionService", "GOLDEN_TEST_NAME"]
