# ARC-EDT-008 — Semantic editing requires a project-local template

The project pins a shared library template, which semantic editing cannot change in place: the edit would alter every project that pins the same version. Nothing was changed.

**Typical fix:** Clone the template into the project ('arcavex project clone') to get an editable project-local template.yaml.
