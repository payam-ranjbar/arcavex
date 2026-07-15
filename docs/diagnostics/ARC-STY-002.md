# ARC-STY-002 — Invalid style pack

A style pack file is not a mapping, or contains keys outside the supported set (version, palettes, fonts, effect_presets, shape_presets, roles).

**Typical fix:** Fix the pack so it is a YAML mapping using only the supported top-level keys.
