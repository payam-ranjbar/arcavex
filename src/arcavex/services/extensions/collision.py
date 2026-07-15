"""Component-name collision detection at authoring time (spec §3.3, DX-2/CR-3).

Component names are globally unique per kind: a local extension may not register a name a
built-in already uses, nor one another added extension already declares. The loader catches this
at engine start, but that is too late for an author — ``ext validate`` and ``ext add`` run this
check up front so the collision surfaces at the command that introduces it, naming **both**
providers (the incumbent by extension name, or as a built-in) so the author knows what to rename.

This is an authoring/compatibility rule, not a security check: it prevents one component silently
shadowing another, nothing more.
"""

from __future__ import annotations

from pathlib import Path

from arcavex.kernel.diagnostics import Diagnostic, diagnostic
from arcavex.services.extensions.manifest import ExtensionManifest

# taken[kind_keyword][component_name] -> a human label for the incumbent provider, e.g.
# "built-in 'blur'" or "extension 'print-effects'".
TakenNames = dict[str, dict[str, str]]


def check_collisions(
    manifest: ExtensionManifest, ext_dir: Path, taken: TakenNames
) -> list[Diagnostic]:
    """Return an ``ARC-EXT-001`` for every manifest component whose name is already taken.

    ``taken`` maps each kind to the names already claimed and by whom. It must exclude the
    extension being checked, so re-validating an already-added extension does not flag it against
    its own stored copy.
    """
    diagnostics: list[Diagnostic] = []
    for spec in manifest.components:
        incumbent = taken.get(spec.kind, {}).get(spec.name)
        if incumbent is None:
            continue
        diagnostics.append(
            diagnostic(
                "ARC-EXT-001",
                f"Duplicate {spec.kind} component {spec.name!r}: already provided by "
                f"{incumbent}, cannot also register {manifest.name!r}'s {spec.class_name}",
                file=str(ext_dir),
                hint="Component names are globally unique per kind; rename the extension's "
                "component (and its manifest name) to something not already registered.",
            )
        )
    return diagnostics


__all__ = ["TakenNames", "check_collisions"]
