"""Performance benchmark harness (spec §8.2) — measure, don't guess.

Runs the pipeline stages the spec sets p95 targets for and prints the measured actuals on the
current machine: template compile, a 1080×1350 render with raster effects, an A4 @ 300 dpi render
with a 4-deep effect chain, peak process RSS during that render, and CLI cold start to a
render-ready engine. Nothing here asserts a target — it reports what the machine does so the
numbers in docs/performance.md are real. Re-run with ``python scripts/benchmark.py``.

The RSS probe reads the OS peak working set (Windows PSAPI / POSIX getrusage), so it includes
Skia's native allocations, not just the Python heap.
"""

from __future__ import annotations

import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))

from arcavex.bootstrap import build_facade  # noqa: E402

_POSTER = """\
version: 0.1.0
variables:
  title: {type: string, required: true}
formats:
  social:
    canvas: {width: 1080px, height: 1350px, dpi: 96}
  a4:
    canvas: {width: 210mm, height: 297mm, dpi: 300}
preview_data: {title: "Launch Night"}
root:
  type: group
  id: root
  children:
    - id: bg
      type: shape
      shape: rect
      style: {fill: "#1a1a2e"}
      # The spec's 1080x1350 scenario: three raster effects.
      effects:
        - {name: grain, params: {amount: 0.15}}
        - {name: noise, params: {amount: 0.08}}
        - {name: blur, params: {radius: 2pt}}
      constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: fill, h: fill}}
    - id: card
      type: shape
      shape: rrect
      style: {fill: "#e94560", corner_radius: 32px}
      constraints:
        anchor: {center_x: parent.center_x, center_y: parent.center_y}
        size: {w: 72%, h: 40%}
    - id: title
      type: text
      text: "{{ title }}"
      style: {font: Inter, font_size: 72px, font_weight: 800, color: "#ffffff", align: center}
      constraints:
        anchor: {center_x: parent.center_x, center_y: parent.center_y}
        size: {w: 64%, h: fit_content}
"""

_A4_DEEP = """\
version: 0.1.0
formats:
  a4:
    canvas: {width: 210mm, height: 297mm, dpi: 300}
root:
  type: group
  id: root
  children:
    - id: bg
      type: shape
      shape: rect
      style: {fill: "#0f3460"}
      effects:
        - {name: grain, params: {amount: 0.2}}
        - {name: noise, params: {amount: 0.1}}
        - {name: blur, params: {radius: 3pt}}
        - {name: drop-shadow, params: {dx: 0pt, dy: 6pt, blur: 18pt, color: "#000000"}}
      constraints: {anchor: {top: parent.top, left: parent.left}, size: {w: fill, h: fill}}
"""


def _peak_rss_mb() -> float:
    """Return the process peak working set in MiB (includes Skia native allocations)."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class _Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi = ctypes.windll.psapi
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_Counters),
            wintypes.DWORD,
        ]
        counters = _Counters()
        counters.cb = ctypes.sizeof(_Counters)
        psapi.GetProcessMemoryInfo(
            kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        )
        return counters.PeakWorkingSetSize / (1024 * 1024)
    import resource

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux reports KiB, macOS reports bytes.
    return peak / 1024 if sys.platform.startswith("linux") else peak / (1024 * 1024)


def _timeit(fn, runs: int) -> tuple[float, float]:
    """Return (median_ms, p95_ms) over ``runs`` calls to ``fn``."""
    samples = []
    for _ in range(runs):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000.0)
    samples.sort()
    p95 = samples[min(len(samples) - 1, int(round(0.95 * (len(samples) - 1))))]
    return statistics.median(samples), p95


def _cold_start_ms() -> float:
    """Time a fresh interpreter from launch to a render-ready engine (import + facade build)."""
    code = (
        "import time; t=time.perf_counter();"
        "from arcavex.bootstrap import build_facade; build_facade();"
        "print(time.perf_counter()-t)"
    )
    # text=True alone decodes with the ANSI codepage, so one non-cp1252 byte from the child
    # raises UnicodeDecodeError in the reader. The env vars make the child emit UTF-8.
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(_REPO),
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"cold-start probe failed (exit {result.returncode}):\n{result.stderr.strip()}"
        )
    return float(result.stdout.strip()) * 1000.0


def main() -> None:
    facade = build_facade()
    with TemporaryDirectory() as td:
        tmp = Path(td)
        poster = tmp / "poster.yaml"
        poster.write_text(_POSTER, encoding="utf-8")
        a4 = tmp / "a4.yaml"
        a4.write_text(_A4_DEEP, encoding="utf-8")

        compile_median, compile_p95 = _timeit(
            lambda: facade.validate_template(poster, format_name="social"), runs=30
        )

        def render_social() -> None:
            facade.render_file(poster, format_name="social", output=tmp / "social.png")

        social_median, social_p95 = _timeit(render_social, runs=7)

        def render_a4() -> None:
            facade.render_file(a4, format_name="a4", output=tmp / "a4.png")

        render_a4()  # warm once, then measure
        a4_median, a4_p95 = _timeit(render_a4, runs=5)
        peak_rss = _peak_rss_mb()

    cold = _cold_start_ms()

    print(f"{'operation':<44}{'target':<14}{'median':<12}{'p95'}")
    print("-" * 82)
    _row("template compile (event poster)", "<= 50 ms", compile_median, compile_p95, "ms")
    _row("render 1080x1350, raster effects", "<= 1500 ms", social_median, social_p95, "ms")
    _row("render A4@300, 4-deep chain", "<= 6000 ms", a4_median, a4_p95, "ms")
    print(f"{'peak RSS (A4@300 render)':<44}{'<= 1536 MiB':<14}{peak_rss:.0f} MiB")
    print(f"{'CLI cold start to render-ready':<44}{'<= 400 ms':<14}{cold:.0f} ms")


def _row(label: str, target: str, median: float, p95: float, unit: str) -> None:
    print(f"{label:<44}{target:<14}{median:<12.1f}{p95:.1f} {unit}")


if __name__ == "__main__":
    main()
