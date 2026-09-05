# ARC-TPL-072 — Unknown format preset

'template new --format' (or the MCP tool's 'formats' argument) named a canvas preset that does not exist. The presets are square, story, portrait, landscape (pixels at 96 dpi) and a4, a3, a2, letter, tabloid (millimetres at 300 dpi with a 3mm bleed). Nothing is written when a name is unknown.

**Typical fix:** Use one of the preset names, or scaffold with the defaults and declare the canvas you need with 'template patch --set formats.<name> --value {"canvas": {...}}'.
