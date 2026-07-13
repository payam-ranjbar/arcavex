# ARC-TPL-097 — Section defined twice

A section (variables, formats, locales, or preview_data) is defined both inline in template.yaml and in its split sidecar file. Arcavex will not guess which wins — silent precedence between two definitions is exactly the ambiguity the split format exists to avoid.

**Typical fix:** Keep each section in exactly one place. Delete the inline section from template.yaml, or delete the sidecar file, so the section has a single definition.
