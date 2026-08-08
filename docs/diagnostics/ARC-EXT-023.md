# ARC-EXT-023 — Extension component parameter schema invalid

An effect, mask, or shape component has no valid pydantic 'param_schema', so its authored parameters cannot be validated.

**Typical fix:** Set 'param_schema' to a pydantic v2 BaseModel subclass describing the parameters.
