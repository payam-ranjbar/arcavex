"""The font install/inspect service backing ``arcavex font`` and the facade (spec §4.3).

Rendering is confined to the fonts the engine has loaded — system fonts are never consulted,
because determinism requires it — so any typeface beyond the four bundled families must be
*installed* before a template may name it. This service is the supported way to do that:

* ``list_fonts`` reports every family the shaper will resolve, marking each **bundled** (shipped
  in the wheel / the dev checkout's ``library-seed/fonts``) or **installed** (added under the
  Arcavex home), and names the directory ``add`` writes to;
* ``add_font`` copies a font file into the home's ``fonts`` directory and reports the family name
  **as the engine resolves it** — the file stem and the internal family name routinely differ
  (``Lateef-Regular.ttf`` provides ``Lateef``) and a template must name the family, so reporting
  the stem would hand the author a name that does not render;
* ``remove_font`` deletes an installed family's files, and refuses a bundled one.

Family resolution is not re-implemented here: :func:`~arcavex.services.text.family_name` is the
one place a name is derived from a file, and the shaper registers each file under exactly that
name. Diagnostics live in the ``ARC-RND`` namespace because font resolution is a render-stack
concern, matching ``ARC-RND-010``. Every method returns a versioned kernel result model and never
raises across the facade boundary.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Literal

from arcavex.kernel.api import FontActionReport, FontFamilyInfo, FontFileInfo, FontListReport
from arcavex.kernel.diagnostics import Diagnostic, diagnostic
from arcavex.services.fsutil import home_dir
from arcavex.services.text import (
    FONT_GLOB,
    FONT_SUFFIX,
    family_name,
    find_font_dirs,
    installed_fonts_dir,
)

# Licence files are copied beside the font they cover, named ``LICENSE-<family>-<original stem>``
# so several families' licences coexist in one flat directory — the convention the bundled
# ``LICENSE-Inter-OFL.txt`` / ``LICENSE-Vazirmatn-OFL.txt`` already follow.
_LICENSE_PREFIX = "LICENSE-"


class FontService:
    """Inspect and manage the font store under the Arcavex home; all methods are boundary-safe."""

    def __init__(
        self, font_dirs: list[Path] | None = None, install_dir: Path | None = None
    ) -> None:
        """Bind the search directories and the install target.

        Args:
            font_dirs: Ordered font roots to report (defaults to :func:`find_font_dirs`, the
                exact list the shaper loads).
            install_dir: Directory ``add``/``remove`` operate on (defaults to
                :func:`installed_fonts_dir`, the Arcavex home's ``fonts``).

        Both default to the live resolvers rather than being captured at construction, so a test
        (or a caller) that repoints ``ARCAVEX_HOME`` is honoured on the next call.
        """
        self._font_dirs = font_dirs
        self._install_dir = install_dir

    @property
    def install_dir(self) -> Path:
        """The directory ``font add`` copies into — the Arcavex home's ``fonts`` directory."""
        return self._install_dir if self._install_dir is not None else installed_fonts_dir()

    def _dirs(self) -> list[Path]:
        return self._font_dirs if self._font_dirs is not None else find_font_dirs()

    # ---------------------------------------------------------------------- list
    def list_fonts(self) -> FontListReport:
        """Report every resolvable family, its files, and whether it is bundled or installed.

        A family is ``bundled`` if any of its files comes from a root outside the install
        directory and ``installed`` if any comes from inside it; both flags can be true at once
        (installing an extra weight of a bundled family is legitimate), so the two are reported
        separately rather than collapsed into one enum that would have to lie about that case.
        """
        try:
            install_dir = self.install_dir
            files: dict[str, list[FontFileInfo]] = {}
            for directory in self._dirs():
                installed = _same_dir(directory, install_dir)
                for path in sorted(directory.glob(FONT_GLOB)):
                    family = family_name(path)
                    if family is None:
                        continue
                    files.setdefault(family, []).append(
                        FontFileInfo(name=path.name, path=str(path), installed=installed)
                    )
            families = [
                _family_info(family, infos) for family, infos in sorted(files.items())
            ]
            return FontListReport(ok=True, install_dir=str(install_dir), families=families)
        except OSError as exc:
            return FontListReport(
                ok=False,
                install_dir=str(self.install_dir),
                diagnostics=[
                    diagnostic(
                        "ARC-RND-034",
                        f"Could not read the font directories: {exc}",
                        hint="Check that the Arcavex home is readable; 'arcavex doctor' reports "
                        "which home is in effect.",
                    )
                ],
            )

    # ----------------------------------------------------------------------- add
    def add_font(self, source: Path, license_path: Path | None = None) -> FontActionReport:
        """Copy a font file into the Arcavex home and report the family the engine will resolve.

        The family name is read from the file with the shaper's own resolver *before* the copy,
        so a file Skia cannot parse is refused rather than installed as dead weight. A re-add of
        the same filename overwrites, which is how a user replaces a font with a corrected build.
        """
        source = Path(source)
        install_dir = self.install_dir
        if not source.is_file():
            return _fail(
                "ARC-RND-030",
                f"Font file not found: {source}",
                file=str(source),
                hint="Pass the path to a .ttf file to install.",
                install_dir=str(install_dir),
            )
        if source.suffix.lower() != FONT_SUFFIX:
            return _fail(
                "ARC-RND-031",
                f"Unsupported font file type {source.suffix!r}: {source.name}",
                file=str(source),
                hint=f"Arcavex loads {FONT_SUFFIX} files only; convert the font to TrueType "
                "first.",
                install_dir=str(install_dir),
            )
        family = family_name(source)
        if family is None:
            return _fail(
                "ARC-RND-031",
                f"Font file could not be read as a typeface: {source.name}",
                file=str(source),
                hint="The file is not a usable TrueType font; re-download or re-export it.",
                install_dir=str(install_dir),
            )
        # Both inputs are validated before ANY copy: a bad --license path must not leave the font
        # installed behind a failure report, which would be a lie the user has to clean up.
        license_source = None if license_path is None else Path(license_path)
        if license_source is not None and not license_source.is_file():
            return _fail(
                "ARC-RND-030",
                f"Licence file not found: {license_source}",
                file=str(license_source),
                hint="Pass the path to the font's licence file, or omit --license.",
                install_dir=str(install_dir),
            )
        try:
            install_dir.mkdir(parents=True, exist_ok=True)
            dest = install_dir / source.name
            shutil.copyfile(source, dest)
            license_dest: Path | None = None
            if license_source is not None:
                license_dest = install_dir / f"{_LICENSE_PREFIX}{family}-{license_source.name}"
                shutil.copyfile(license_source, license_dest)
        except OSError as exc:
            return _fail(
                "ARC-RND-034",
                f"Could not install the font into the Arcavex home: {exc}",
                file=str(install_dir),
                hint="Check the Arcavex home is writable; 'arcavex doctor' reports which home "
                "is in effect.",
                install_dir=str(install_dir),
            )
        return FontActionReport(
            ok=True,
            family=family,
            files=[str(dest)],
            license=None if license_dest is None else str(license_dest),
            install_dir=str(install_dir),
        )

    # -------------------------------------------------------------------- remove
    def remove_font(self, family: str) -> FontActionReport:
        """Delete an installed family's files; refuse a bundled family.

        Bundled families ship with the engine and back the default font stacks, so removing one
        would break templates that never opted into anything unusual — and the files would return
        on the next reinstall anyway. A family that is bundled *and* has installed files is still
        refused: the render would silently change rather than fail, which is the harder failure
        to diagnose.
        """
        listing = self.list_fonts()
        if not listing.ok:
            return FontActionReport(
                ok=False, family=family, install_dir=listing.install_dir,
                diagnostics=list(listing.diagnostics),
            )
        match = next((f for f in listing.families if f.family == family), None)
        if match is None:
            installed = ", ".join(f.family for f in listing.families if f.installed) or "(none)"
            return _fail(
                "ARC-RND-033",
                f"No font family named {family!r} is installed",
                hint=f"Installed families: {installed}. 'arcavex font list' shows every family; "
                "names are case-sensitive and must be the family, not the file name.",
                install_dir=listing.install_dir,
            )
        if match.bundled:
            return _fail(
                "ARC-RND-032",
                f"Font family {family!r} is bundled with the engine and cannot be removed",
                hint="Bundled families ship with Arcavex; only families added with "
                "'arcavex font add' can be removed.",
                install_dir=listing.install_dir,
            )
        removed: list[str] = []
        try:
            for info in match.files:
                Path(info.path).unlink()
                removed.append(info.path)
            license_removed = self._remove_licenses(family, Path(listing.install_dir))
        except OSError as exc:
            return _fail(
                "ARC-RND-034",
                f"Could not remove the font from the Arcavex home: {exc}",
                file=listing.install_dir,
                hint="Check the Arcavex home is writable and no other process holds the file.",
                install_dir=listing.install_dir,
            )
        return FontActionReport(
            ok=True,
            family=family,
            files=removed,
            license=None if not license_removed else str(license_removed[0]),
            install_dir=listing.install_dir,
        )

    def _remove_licenses(self, family: str, install_dir: Path) -> list[Path]:
        """Delete the licence files installed alongside ``family``."""
        removed: list[Path] = []
        for path in sorted(install_dir.glob(f"{_LICENSE_PREFIX}{family}-*")):
            path.unlink()
            removed.append(path)
        return removed


def _same_dir(a: Path, b: Path) -> bool:
    """Whether two paths name the same directory, tolerating case/separator differences."""
    try:
        return a.resolve() == b.resolve()
    except OSError:  # pragma: no cover - unresolvable path is simply "not the install dir"
        return False


def _fail(
    code: str,
    message: str,
    *,
    file: str | None = None,
    hint: str | None = None,
    install_dir: str | None = None,
) -> FontActionReport:
    """Build a failed action report carrying one located diagnostic."""
    diag: Diagnostic = diagnostic(code, message, file=file, hint=hint)
    return FontActionReport(
        ok=False,
        install_dir=install_dir if install_dir is not None else str(home_dir() / "fonts"),
        diagnostics=[diag],
    )


__all__ = ["FontService"]


def _family_info(family: str, infos: list[FontFileInfo]) -> FontFamilyInfo:
    """Describe one resolvable family from its files.

    Every family the shaper resolves is ``available`` — that is what "may a template name it?"
    asks, and a bundled family answered ``installed: false`` was read as "no". ``source`` says in
    one word where it came from; a family with files on both sides reports both.
    """
    bundled = any(not f.installed for f in infos)
    installed = any(f.installed for f in infos)
    source: Literal["bundled", "installed", "bundled+installed"]
    if bundled and installed:
        source = "bundled+installed"
    elif installed:
        source = "installed"
    else:
        source = "bundled"
    return FontFamilyInfo(
        family=family,
        bundled=bundled,
        installed=installed,
        available=True,
        source=source,
        files=infos,
    )
