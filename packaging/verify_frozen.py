"""Prove the frozen ``arcavex.exe`` renders byte-identically to the installed engine.

Arcavex's core guarantee is that identical inputs produce identical bytes. Packaging is the
step most likely to break it quietly: a missing font falls back to a different family, absent
package metadata changes the PDF ``Producer`` string, a different ICU build reshapes Farsi
text. None of those raise an error — they just change pixels. So the packaged binary is only
trustworthy if its bytes are compared against the reference implementation, not merely run.

This renders the synthetic bilingual fixture matrix (3 formats x 2 locales, plus both A4 PDFs) with
the dev install and with the frozen binary, and compares SHA-256 digests. It also checks that
the MCP tool catalog is identical, since the binary's purpose is to serve that surface.

Usage:
    .venv/Scripts/python.exe packaging/verify_frozen.py
    .venv/Scripts/python.exe packaging/verify_frozen.py --exe dist/frozen/arcavex.exe
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POSTER = ROOT / "tests" / "fixtures" / "bilingual-poster"
DATA = POSTER / "data.yaml"
FORMATS = ("square", "story", "a4")
LOCALES = ("en", "fa")


def _run(
    cmd: list[str], cwd: Path | str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run ``cmd`` capturing text output, decoded as UTF-8.

    The encoding is explicit because the engine prints Rich box-drawing tables and Farsi
    sample text. Python would otherwise decode the pipe with the Windows ANSI codepage
    (cp1252), which cannot represent either: the decode raises inside subprocess's reader
    thread and ``stdout`` silently arrives as ``None`` rather than as an error.
    """
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _render(engine: list[str], fmt: str, locale: str, out: Path) -> None:
    """Render one format/locale with ``engine`` (a dev-python or frozen-exe argv prefix)."""
    cmd = [
        *engine,
        "render",
        str(POSTER),
        "--data",
        str(DATA),
        "--format",
        fmt,
        "--locale",
        locale,
        "-o",
        str(out),
    ]
    result = _run(cmd, ROOT)
    if result.returncode != 0 or not out.is_file():
        raise SystemExit(
            f"render failed ({fmt}/{locale}) for {engine[-1]}:\n{result.stdout}\n{result.stderr}"
        )


def _tool_catalog(engine: list[str]) -> list[str]:
    """Return the sorted MCP tool names the engine advertises."""
    result = _run([*engine, "mcp", "tools", "--json"], ROOT)
    if result.returncode != 0:
        raise SystemExit(f"mcp tools failed for {engine[-1]}:\n{result.stderr}")
    payload = json.loads(result.stdout)
    return sorted(tool["name"] for tool in payload["tools"])


def _check_relocated(exe: Path) -> list[str]:
    """Run the binary from outside the source tree and confirm it is still self-contained.

    A build tested only in place can appear complete while quietly reading the developer's own
    checkout: the style resolver walks parent directories looking for a ``pyproject.toml``, and
    an ``.exe`` sitting under ``dist/`` inside the repo finds the real one. The user who copies
    the folder elsewhere is the first to discover the resources were never bundled. So the
    binary is copied to a temp directory and re-probed there, where no checkout can be found.
    """
    app_dir = exe.parent
    with tempfile.TemporaryDirectory(prefix="arcavex-relocated-") as tmp:
        moved = Path(tmp) / app_dir.name
        shutil.copytree(app_dir, moved)
        relocated = str(moved / exe.name)
        problems: list[str] = []

        styles = _run([relocated, "style", "list"], tmp)
        if "pop-art" not in styles.stdout:
            problems.append("relocated:styles")
            print(f"  DIFF  relocated style list   {styles.stdout.strip()[:60]!r}")
        else:
            print("  ok    relocated style list   seeded packs resolved")

        doctor = _run([relocated, "doctor"], tmp)
        if "Vazirmatn" not in doctor.stdout:
            problems.append("relocated:fonts")
            print("  DIFF  relocated fonts        bundled families missing")
        else:
            print("  ok    relocated fonts        bundled families resolved")
        return problems


def _check_extensions(exe: Path) -> list[str]:
    """Confirm the binary can load a third-party extension authored on the user's machine.

    This is the capability least likely to survive freezing, because the loader imports code
    that did not exist at build time: it registers a synthetic package whose ``__path__`` is a
    directory on disk and hands it to ``importlib``. Static analysis cannot see that, so it is
    only ever proven by running it. The check scaffolds an effect with the binary itself, adds
    and enables it against a throwaway ``ARCAVEX_HOME``, and asserts the new effect appears in
    the registry — the same registry a render resolves against.
    """
    with tempfile.TemporaryDirectory(prefix="arcavex-ext-") as tmp:
        env = dict(os.environ, ARCAVEX_HOME=str(Path(tmp) / "home"))
        binary = str(exe)
        name = "verifyhatch"  # Must not collide with a built-in effect (ARC-EXT-001).

        steps = (
            ([binary, "ext", "scaffold", "effect", f"./{name}", "--name", name], "scaffold"),
            ([binary, "ext", "validate", f"./{name}"], "validate"),
            ([binary, "ext", "add", f"./{name}"], "add"),
            ([binary, "ext", "enable", name], "enable"),
        )
        for cmd, label in steps:
            result = _run(cmd, tmp, env)
            if result.returncode != 0:
                print(f"  DIFF  extension {label:12} {(result.stdout or '').strip()[:70]}")
                return [f"extension:{label}"]

        listed = _run([binary, "effects", "list"], tmp, env)
        if name not in (listed.stdout or ""):
            print("  DIFF  extension registry   effect absent after enable")
            return ["extension:registry"]
        print("  ok    extension lifecycle   scaffold/validate/add/enable/register")
        return []


def main() -> int:
    """Render both engines across the matrix and report any digest divergence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--exe",
        default=str(ROOT / "dist" / "frozen" / "arcavex" / "arcavex.exe"),
        help="Path to the frozen executable to verify.",
    )
    args = parser.parse_args()

    exe = Path(args.exe).resolve()
    if not exe.is_file():
        raise SystemExit(f"frozen binary not found at {exe}; run packaging/build.py first")

    dev = [sys.executable, "-m", "arcavex.clients.cli"]
    frozen = [str(exe)]

    # Both A4 renders also go out as PDF, where the embedded Producer string carries the engine
    # version — the one output that would expose missing package metadata in the bundle.
    jobs = [(fmt, locale, "png") for fmt in FORMATS for locale in LOCALES]
    jobs += [("a4", locale, "pdf") for locale in LOCALES]

    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="arcavex-verify-") as tmp:
        tmpdir = Path(tmp)
        for fmt, locale, ext in jobs:
            label = f"{fmt}.{locale}.{ext}"
            dev_out = tmpdir / f"dev.{label}"
            exe_out = tmpdir / f"exe.{label}"
            _render(dev, fmt, locale, dev_out)
            _render(frozen, fmt, locale, exe_out)
            dev_hash, exe_hash = _digest(dev_out), _digest(exe_out)
            if dev_hash == exe_hash:
                print(f"  ok    {label:22} {dev_hash[:16]}")
            else:
                failures.append(label)
                print(f"  DIFF  {label:22} dev={dev_hash[:16]} exe={exe_hash[:16]}")

    failures.extend(_check_relocated(exe))
    failures.extend(_check_extensions(exe))

    dev_tools, exe_tools = _tool_catalog(dev), _tool_catalog(frozen)
    if dev_tools == exe_tools:
        print(f"  ok    mcp catalog            {len(exe_tools)} tools identical")
    else:
        failures.append("mcp catalog")
        missing = sorted(set(dev_tools) - set(exe_tools))
        extra = sorted(set(exe_tools) - set(dev_tools))
        print(f"  DIFF  mcp catalog            missing={missing} extra={extra}")

    if failures:
        print(f"\nFAILED: {len(failures)} divergence(s): {', '.join(failures)}")
        return 1
    print(f"\nPASS: {len(jobs)} renders byte-identical, MCP catalog identical.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
