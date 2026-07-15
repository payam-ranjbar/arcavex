# ARC-PRJ-007 — Template detached from the library

'template detach' copied a library template into the project. The project now references its own editable copy, so automatic version upgrades are no longer available for it (spec §5.4).

**Typical fix:** Edit the copied template directly. Re-pin the project to a library 'name@version' if you want upgrades back.
