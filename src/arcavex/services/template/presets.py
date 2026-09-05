"""Canvas presets for ``arcavex template new --format`` (and the MCP ``formats`` argument).

A scaffold used to declare exactly ``square`` and ``story``, so an author who wanted a print
poster had to know the canvas grammar before writing a line — and an assistant working over MCP
alone, which could not declare a format at all, shipped a 9:16 "window poster" in place of an A3.
The table below is the single source of truth for the preset names: the scaffold reads it, the
unknown-preset diagnostic quotes it, and ``docs/template-schema.md`` tabulates it (a test pins the
two). Screen presets are pixels at 96 dpi; print presets are millimetres at 300 dpi with a 3 mm
bleed so the PDF exporter emits a print-ready bleed box.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FormatPreset:
    """One named canvas: authored width/height strings, dpi, optional bleed, and a one-liner."""

    name: str
    width: str
    height: str
    dpi: int
    bleed: str | None
    doc: str

    def canvas(self) -> dict[str, object]:
        """The ``canvas:`` mapping this preset declares, as an author would write it."""
        spec: dict[str, object] = {"width": self.width, "height": self.height, "dpi": self.dpi}
        if self.bleed is not None:
            spec["bleed"] = self.bleed
        return spec


_PRESETS: tuple[FormatPreset, ...] = (
    FormatPreset("square", "1080px", "1080px", 96, None, "Social square (1:1)"),
    FormatPreset("story", "1080px", "1920px", 96, None, "Story / reel (9:16)"),
    FormatPreset("portrait", "1080px", "1350px", 96, None, "Social portrait (4:5)"),
    FormatPreset("landscape", "1920px", "1080px", 96, None, "Landscape / slide (16:9)"),
    FormatPreset("a4", "210mm", "297mm", 300, "3mm", "ISO A4 print, portrait"),
    FormatPreset("a3", "297mm", "420mm", 300, "3mm", "ISO A3 print, portrait"),
    FormatPreset("a2", "420mm", "594mm", 300, "3mm", "ISO A2 print, portrait"),
    FormatPreset("letter", "215.9mm", "279.4mm", 300, "3mm", "US Letter print, portrait"),
    FormatPreset("tabloid", "279.4mm", "431.8mm", 300, "3mm", "US Tabloid print, portrait"),
)

#: Preset name -> preset, in the order the docs list them.
FORMAT_PRESETS: dict[str, FormatPreset] = {preset.name: preset for preset in _PRESETS}

#: What ``template new`` declares when no ``--format`` is given.
DEFAULT_SCAFFOLD_FORMATS: tuple[str, ...] = ("square", "story")


def preset_names() -> str:
    """The preset names as one comma-separated string, for hints and help text."""
    return ", ".join(FORMAT_PRESETS)
