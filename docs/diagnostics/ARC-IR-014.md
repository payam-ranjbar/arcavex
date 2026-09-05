# ARC-IR-014 — Value has the wrong type or is out of range

A field received a value it cannot take: a word where a number is required ('font_weight: bold'), a quoted string where a YAML boolean is required ('italic: "no"' is a string, and used to be coerced to true), or a number outside the field's range ('opacity: 1.5'; opacity runs from 0 to 1). The message names the field and the kind of value it takes.

**Typical fix:** Provide a value of the kind the message names — a number within the stated range, or an unquoted true/false.
