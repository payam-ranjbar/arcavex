"""Environment diagnostics for ``arcavex doctor`` (spec §3.7 / §6.1.3).

Every probe is isolated in its own try/except and contributes one check row (ok/warn/fail
with a detail and, when actionable, a hint). A broken Skia, ICU, or font database therefore
produces a readable report instead of a crash. The ICU probe surfaces the ``icudtl.dat``
remediation from ADR-0001.
"""

from __future__ import annotations

import importlib.metadata
import os
import sys
import tempfile
from pathlib import Path

from arcavex.kernel.api import DoctorCheck, DoctorReport
from arcavex.services.text import TextService

_MIN_PYTHON = (3, 11)


def engine_version() -> str:
    """Return the installed engine version from package metadata."""
    try:
        return importlib.metadata.version("arcavex")
    except importlib.metadata.PackageNotFoundError:  # pragma: no cover - always installed
        return "0.0.0+unknown"


def run_doctor(text_service: TextService | None = None) -> DoctorReport:
    """Run all environment probes and return a report.

    Args:
        text_service: An already-built text service to report bundled fonts from. When
            ``None``, the font probe builds one so ``doctor`` works standalone.
    """
    checks: list[DoctorCheck] = [
        _check_python(),
        _check_skia(),
        _check_icu(),
        _check_fonts(text_service),
        _check_exporters(),
        _check_cache(),
        _check_temp_dir(),
        _check_paths(),
        _check_config(),
    ]
    # 'ok' is true when no probe failed; warnings do not flip overall success.
    ok = all(c.status != "fail" for c in checks)
    return DoctorReport(ok=ok, engine_version=engine_version(), checks=checks)


def _check_python() -> DoctorCheck:
    version = ".".join(str(p) for p in sys.version_info[:3])
    if sys.version_info[:2] >= _MIN_PYTHON:
        return DoctorCheck(name="python", status="ok", detail=f"Python {version}")
    want = ".".join(str(p) for p in _MIN_PYTHON)
    return DoctorCheck(
        name="python",
        status="fail",
        detail=f"Python {version} is below the required {want}",
        hint=f"Install Python {want} or newer.",
    )


def _check_skia() -> DoctorCheck:
    try:
        import skia  # type: ignore[import-untyped]
    except Exception as exc:  # noqa: BLE001 - a broken import becomes a check row
        return DoctorCheck(
            name="skia",
            status="fail",
            detail=f"skia-python could not be imported: {exc!r}",
            hint="Reinstall skia-python (pinned >=144.0,<145).",
        )
    version = getattr(skia, "__version__", None)
    if version is None:
        try:
            version = importlib.metadata.version("skia-python")
        except importlib.metadata.PackageNotFoundError:
            version = "unknown"
    return DoctorCheck(name="skia", status="ok", detail=f"skia-python {version}")


def _check_icu() -> DoctorCheck:
    """Probe ICU by constructing a ``skia.Unicode`` (needed for text shaping)."""
    try:
        import skia  # type: ignore[import-untyped]

        skia.Unicode()
    except Exception as exc:  # noqa: BLE001 - broken ICU becomes an actionable check row
        base_dir = Path(sys.base_prefix)
        return DoctorCheck(
            name="icu",
            status="fail",
            detail=f"ICU/skia.Unicode is unavailable: {exc!r}",
            hint=(
                "Copy 'icudtl.dat' from the skia-python package in site-packages to next to "
                f"the base interpreter at {base_dir} (see ADR-0001)."
            ),
        )
    return DoctorCheck(name="icu", status="ok", detail="ICU available (skia.Unicode built)")


def _check_fonts(text_service: TextService | None) -> DoctorCheck:
    try:
        service = text_service if text_service is not None else TextService()
        families = sorted(service.families)
    except Exception as exc:  # noqa: BLE001 - a broken font DB becomes a check row
        return DoctorCheck(
            name="fonts",
            status="fail",
            detail=f"Font database could not be built: {exc!r}",
            hint="Ensure fonts are present under library-seed/fonts or $ARCAVEX_HOME/fonts.",
        )
    if not families:
        return DoctorCheck(
            name="fonts",
            status="warn",
            detail="No bundled font families were found",
            hint="Add .ttf fonts under library-seed/fonts or $ARCAVEX_HOME/fonts.",
        )
    listed = ", ".join(families)
    return DoctorCheck(
        name="fonts",
        status="ok",
        detail=f"{len(families)} bundled families: {listed}",
    )


def _check_exporters() -> DoctorCheck:
    """Confirm every built-in exporter can encode a surface (PNG/JPEG/WebP raster + PDF).

    A tiny surface is encoded through each format so a Skia build missing an encoder (or the PDF
    backend) is reported here rather than only failing at the end of a real render.
    """
    try:
        import skia  # type: ignore[import-untyped]

        surface = skia.Surface(4, 4)
        surface.getCanvas().clear(skia.Color4f(1, 1, 1, 1))
        image = surface.makeImageSnapshot()
        raster = {
            "png": skia.EncodedImageFormat.kPNG,
            "jpeg": skia.EncodedImageFormat.kJPEG,
            "webp": skia.EncodedImageFormat.kWEBP,
        }
        missing = [name for name, fmt in raster.items() if image.encodeToData(fmt, 90) is None]
        stream = skia.DynamicMemoryWStream()
        document = skia.PDF.MakeDocument(stream, skia.PDF.Metadata())
        if document is None:
            missing.append("pdf")
        else:
            document.beginPage(8, 8)
            document.endPage()
            document.close()
            if not bytes(stream.detachAsData()):
                missing.append("pdf")
    except Exception as exc:  # noqa: BLE001 - a broken encoder becomes a check row
        return DoctorCheck(
            name="exporters",
            status="fail",
            detail=f"Exporter self-test failed: {exc!r}",
            hint="Reinstall skia-python; the build must include PNG/JPEG/WebP and PDF support.",
        )
    if missing:
        return DoctorCheck(
            name="exporters",
            status="fail",
            detail=f"Unavailable exporters: {', '.join(missing)}",
            hint="Reinstall skia-python built with the missing encoder(s).",
        )
    return DoctorCheck(
        name="exporters",
        status="ok",
        detail="png, jpeg, webp, pdf all available",
    )


def _check_cache() -> DoctorCheck:
    """Report the derived-asset cache directory and its resolved byte budget (§4.7)."""
    from arcavex.services.cache import cache_root
    from arcavex.services.config import RuntimeConfig

    budget = RuntimeConfig.load().resolve_cache_bytes(256_000_000)
    root = cache_root()
    return DoctorCheck(
        name="cache",
        status="ok",
        detail=f"derived cache={root}; budget={budget} bytes (disposable)",
    )


def _check_temp_dir() -> DoctorCheck:
    try:
        tmp = Path(tempfile.gettempdir())
        fd, name = tempfile.mkstemp(prefix="arcavex-doctor-", dir=str(tmp))
        os.close(fd)
        os.unlink(name)
    except Exception as exc:  # noqa: BLE001 - unwritable temp becomes a check row
        return DoctorCheck(
            name="temp_dir",
            status="fail",
            detail=f"Temp directory is not writable: {exc!r}",
            hint="Set TMP/TEMP to a writable directory.",
        )
    return DoctorCheck(name="temp_dir", status="ok", detail=f"Writable temp dir: {tmp}")


def _check_paths() -> DoctorCheck:
    """Report where Arcavex reads/writes: ARCAVEX_HOME and the preview cache (DX-9).

    The value's source (the ARCAVEX_HOME environment variable or the built-in default) is
    named so an author can see which of the §6.3 precedence layers is in effect.
    """
    home = os.environ.get("ARCAVEX_HOME")
    if home:
        home_dir = Path(home)
        source = "env ARCAVEX_HOME"
        preview_cache = home_dir / "cache" / "preview"
    else:
        home_dir = Path(tempfile.gettempdir()) / "arcavex"
        source = "default (OS temp)"
        preview_cache = home_dir / "cache" / "preview"
    return DoctorCheck(
        name="paths",
        status="ok",
        detail=f"home={home_dir} [{source}]; preview cache={preview_cache}",
    )


def _check_config() -> DoctorCheck:
    """Report the resolved runtime config source (§6.3 precedence, DX-8).

    Shows whether a ``config.toml`` is present and which precedence layer the default render DPI
    resolves from (an ``ARCAVEX_DPI`` env var, the config file, or the built-in per-format
    default) — so the config chain is inspectable without a project in hand.
    """
    from arcavex.services.config import RuntimeConfig, config_path

    resolved = RuntimeConfig.load().resolve_dpi()
    path = config_path()
    presence = "present" if path.is_file() else "absent"
    dpi = "per-format" if resolved.value is None else str(resolved.value)
    return DoctorCheck(
        name="config",
        status="ok",
        detail=f"config.toml {presence} ({path}); default dpi={dpi} [{resolved.source}]",
    )
