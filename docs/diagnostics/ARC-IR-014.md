# ARC-IR-014 — Value has the wrong type

A field received a value of a kind it cannot take: a word where a number is required ('font_weight: bold'), or a quoted string where a YAML boolean is required ('italic: "no"' is a string, and used to be coerced to true). The message names the field and the kind of value it takes.

**Typical fix:** Provide a value of the kind the message names: a number, or an unquoted true/false.
