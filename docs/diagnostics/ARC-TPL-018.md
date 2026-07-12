# ARC-TPL-018 — Number coerced to string

A number was supplied for a variable declared as a string; it was stringified with a warning.

**Typical fix:** Quote the value in your data to make the string intent explicit, or declare the variable as a number.
