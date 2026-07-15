"""Local trusted-extension support: manifest, state, loader, validator, and lifecycle service.

This package implements the engine-development mechanism of spec §3.3 and §7: an extension is a
local directory with an ``extension.toml`` manifest and Python entry modules that register
components into the same registries the built-ins use. Extensions are trusted local code (spec
§7.3) — validation catches compatibility and authoring errors, not malice, and nothing here is a
security sandbox.
"""

from __future__ import annotations

from arcavex.services.extensions.loader import load_enabled_extensions, register_extension
from arcavex.services.extensions.service import ExtensionService
from arcavex.services.extensions.validator import validate_extension

__all__ = [
    "ExtensionService",
    "load_enabled_extensions",
    "register_extension",
    "validate_extension",
]
