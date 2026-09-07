# PyInstaller spec for the standalone Windows `arcavex.exe` (spec §6, ADR-0001).
#
# The frozen binary must reproduce the installed engine EXACTLY — same fonts, same ICU, same
# reported engine version — because Arcavex guarantees byte-identical output for identical
# inputs and the PDF exporter embeds `Arcavex <engine_version>` as the PDF Producer string.
# Anything that changes those inputs changes output bytes, so each `datas` entry below is
# load-bearing, not convenience.
#
# Build:   .venv/Scripts/python.exe -m PyInstaller packaging/arcavex.spec --noconfirm
# Onefile: set ARCAVEX_PYI_ONEFILE=1 first (slower startup; see packaging/README.md).

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, copy_metadata

ROOT = Path(SPECPATH).resolve().parent  # noqa: F821 - SPECPATH is injected by PyInstaller
ONEFILE = os.environ.get("ARCAVEX_PYI_ONEFILE") == "1"

# ---------------------------------------------------------------------------- data payload
datas = []

# Package metadata. `services.doctor.engine_version()` reads it via importlib.metadata; without
# it a frozen build reports "0.0.0+unknown" and every exported PDF differs from the installed
# engine's bytes. `skia-python`'s metadata backs the `doctor` skia-version probe.
datas += copy_metadata("arcavex")
datas += copy_metadata("skia-python")

# ICU. skia-python ships `icudtl.dat` at the site-packages root, beside `skia*.pyd`; Skia loads
# it relative to that directory, which maps to the bundle root once frozen.
import skia  # noqa: E402 - imported for its install location, after PyInstaller hooks are set

_site_packages = Path(skia.__file__).resolve().parent
_icu = _site_packages / "icudtl.dat"
if not _icu.is_file():
    raise SystemExit(f"icudtl.dat not found beside skia at {_site_packages}; cannot build")
datas += [(str(_icu), ".")]

# Bundled fonts, placed exactly where `services.text._packaged_fonts_dir()` looks in an
# installed wheel: `<package root>/arcavex/_bundled/fonts`. Under PyInstaller the frozen
# `arcavex.services.text.service.__file__` is `<bundle>/arcavex/services/text/service.py`, so
# `parents[2] / "_bundled" / "fonts"` resolves inside the bundle — the wheel's discovery rule
# works unchanged, with no frozen-mode branch in engine code.
_fonts = ROOT / "library-seed" / "fonts"
if not _fonts.is_dir():
    raise SystemExit(f"bundled fonts missing at {_fonts}; cannot build")
datas += [(str(path), "arcavex/_bundled/fonts") for path in sorted(_fonts.iterdir()) if path.is_file()]

# Seeded style packs, mirroring the wheel's force-include and found by the same rule
# (`services.style._packaged_styles_dir`). Without these the binary resolves zero style packs
# once it is moved out of a source checkout — the repo-marker walk silently finds the developer's
# own tree when the .exe happens to sit inside it, which masks the failure during local testing.
_styles = ROOT / "library-seed" / "styles"
if not _styles.is_dir():
    raise SystemExit(f"bundled style packs missing at {_styles}; cannot build")
datas += [
    (str(path), f"arcavex/_bundled/styles/{path.parent.name}")
    for path in sorted(_styles.rglob("*.yaml"))
]

# ------------------------------------------------------------------------- hidden imports
# `bootstrap` imports every built-in statically, so the built-in registry needs no help here.
# These cover what static analysis cannot see: the MCP server's optional transports and the
# third-party packages that resolve submodules at run time.
hiddenimports = []
hiddenimports += collect_submodules("arcavex")
hiddenimports += collect_submodules("mcp")
hiddenimports += collect_submodules("ruamel.yaml")
# FastMCP imports the HTTP transport stack even when only stdio is used.
hiddenimports += collect_submodules("uvicorn")
hiddenimports += [
    "sse_starlette",
    "starlette",
    "pydantic_settings",
    "httpx",
    "httpx_sse",
]

# Trusted local extensions (spec §7) are imported at run time from `$ARCAVEX_HOME` by
# `services.extensions.loader`, which is not statically analysable. Their sanctioned import
# surface is `arcavex.sdk` + numpy + the standard library, so those must all be present in the
# bundle for a user-authored effect to load. numpy is a hard dependency and already collected;
# `encodings`/`codecs` come in with the interpreter.
hiddenimports += collect_submodules("numpy")

# ------------------------------------------------------------------------------ analysis
a = Analysis(  # noqa: F821 - PyInstaller injects the build API into spec files
    [str(ROOT / "packaging" / "entry_arcavex.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Test-only and dev-only trees. Excluding them keeps the binary smaller and, more
    # importantly, keeps pytest/hypothesis out of a user-facing artifact.
    excludes=["pytest", "hypothesis", "mypy", "ruff", "importlinter", "PIL", "tkinter"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)  # noqa: F821

_exe_kwargs = dict(
    name="arcavex",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX corrupts some native extensions and buys little; keep the bytes honest.
    console=True,  # The MCP server speaks JSON-RPC over stdio; it must have real std handles.
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

if ONEFILE:
    exe = EXE(  # noqa: F821
        pyz, a.scripts, a.binaries, a.datas, [], exclude_binaries=False, **_exe_kwargs
    )
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **_exe_kwargs)  # noqa: F821
    coll = COLLECT(  # noqa: F821
        exe, a.binaries, a.datas, strip=False, upx=False, name="arcavex"
    )
