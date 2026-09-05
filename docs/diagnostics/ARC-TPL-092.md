# ARC-TPL-092 — Invalid patch operation

A patch op is malformed: it is not a mapping, does not have exactly one of set/remove/insert_before/insert_after, addresses a path outside the grammar, targets a node id or field that does not exist, or an insert has no 'node' body. A patch embedded in a format, a locale, or a project override addresses nodes only ('nodes.<id>[.<field>...]'). The top-level 'template patch' operation (CLI and MCP) may also address the template's sections: 'formats.<name>', 'variables.<name>', 'preview_data.<key>', 'locales.<name>' (each with an optional field path, list indexes included) and the whole 'style' value — with set/remove only.

**Typical fix:** Fix the patch op: address an existing authored node id (or, from 'template patch', a section entry such as 'formats.a3'), use one verb per op, and give inserts a 'node:' mapping.
