# ARC-TPL-065 — Unknown template root field

The template's top level declares a section the engine does not read. Only 'version', 'variables', 'formats', 'locales', 'preview_data', 'style', 'root', and 'seed' are template sections; anything else would be silently ignored.

**Typical fix:** Remove the section or correct its name; the diagnostic lists the valid ones.
