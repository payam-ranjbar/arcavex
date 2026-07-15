# ARC-PRJ-006 — Template upgrade or detach unavailable

The operation needs a library-pinned template. The project's template is a local path (or is already detached), so version upgrades do not apply, or a detach target already exists.

**Typical fix:** Pin the project to a library 'name@version' to enable upgrades, or remove an existing detached copy before detaching again.
