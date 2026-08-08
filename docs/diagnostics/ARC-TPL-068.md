# ARC-TPL-068 — Unknown effect-entry field

An entry in a node's 'effects:' list carries a field the engine does not read. An entry is a bare effect name, an inline '{name, params}', or a '{preset: name}' reference into the style pack's effect presets.

**Typical fix:** Put per-effect settings inside 'params:', and reference a style-pack preset with 'preset:'.
