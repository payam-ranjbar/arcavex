# ARC-EXT-011 — Invalid extension manifest

The extension.toml is not valid TOML, a field has the wrong type, or a name/entry is not a valid identifier ('module:Class').

**Typical fix:** Fix the flagged field; the manifest needs name, version, ir_min, engine_min, and a list of [[components]] tables with a valid kind, name, and 'module:Class' entry.
