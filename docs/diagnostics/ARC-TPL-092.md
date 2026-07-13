# ARC-TPL-092 — Invalid patch operation

A format or locale patch is malformed: an op is not a mapping, does not have exactly one of set/remove/insert_before/insert_after, addresses a path that is not 'nodes.<id>[.<field>...]', targets a node id or field that does not exist, or an insert has no 'node' body.

**Typical fix:** Fix the patch op: address an existing authored node id, use one verb per op, and give inserts a 'node:' mapping.
