"""Build the standalone Windows ``arcavex.exe`` from ``packaging/arcavex.spec``.

Wraps PyInstaller with the one post-build step the spec cannot express: placing ``icudtl.dat``
beside the executable. See :func:`place_icu_beside_exe` for why that is not optional.

Usage:
    .venv/Scripts/python.exe packaging/build.py            # onedir (default, fast startup)
    .venv/Scripts/python.exe packaging/build.py --onefile  # single file, slower startup
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "packaging" / "arcavex.spec"
DIST = ROOT / "dist" / "frozen"
WORK = ROOT / "build" / "pyi"


def place_icu_beside_exe(app_dir: Path) -> None:
    """Copy ``icudtl.dat`` from ``_internal`` to sit beside ``arcavex.exe``.

    Skia's ``SkIcuLoader`` looks for the ICU data file next to the running executable, but
    PyInstaller 6 collects all data under ``_internal/``. Without this copy Skia prints
    ``SkIcuLoader: datafile missing`` on every run and silently falls back to its built-in ICU.
    Rendering still succeeds and is byte-identical either way, so this is about matching the
    installed engine's configuration exactly rather than fixing broken output — an engine that
    warns on every invocation reads as broken to a non-technical user, and a silent fallback is
    a difference between the packaged and installed engine that nothing else would catch.
    """
    internal = app_dir / "_internal" / "icudtl.dat"
    if not internal.is_file():
        raise SystemExit(f"expected bundled ICU data at {internal}, not found")
    shutil.copy2(internal, app_dir / "icudtl.dat")


def _dir_size_mb(path: Path) -> float:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / (1024 * 1024)


def main() -> int:
    """Run PyInstaller, apply the ICU placement, and report the artifact."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--onefile",
        action="store_true",
        help="Build a single self-extracting .exe instead of a directory.",
    )
    args = parser.parse_args()

    env = dict(os.environ)
    if args.onefile:
        env["ARCAVEX_PYI_ONEFILE"] = "1"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            str(SPEC),
            "--noconfirm",
            "--distpath",
            str(DIST),
            "--workpath",
            str(WORK),
        ],
        cwd=ROOT,
        env=env,
    )
    if result.returncode != 0:
        return result.returncode

    if args.onefile:
        exe = DIST / "arcavex.exe"
        # A onefile build unpacks to a temp dir at run time, so the ICU file lands beside the
        # unpacked bootloader rather than the .exe; Skia's built-in ICU is used instead.
        print(f"Built {exe} ({exe.stat().st_size / (1024 * 1024):.1f} MB)")
        print("note: onefile uses Skia's built-in ICU; output stays byte-identical.")
    else:
        app_dir = DIST / "arcavex"
        place_icu_beside_exe(app_dir)
        print(f"Built {app_dir / 'arcavex.exe'} ({_dir_size_mb(app_dir):.0f} MB total)")

    print("Verify with: .venv/Scripts/python.exe packaging/verify_frozen.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
