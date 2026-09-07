# ARC-PRJ-015 — Project data still holds scaffold placeholder copy

'project new' seeds a project's data from the template's own data.yaml, and a template made by 'template new' ships placeholder values there ('TITLE GOES HERE', 'SUBTITLE GOES HERE'). One or more variables still hold exactly those values, so the project's render and preview print the placeholder — while a preview of the bare template shows its preview_data instead, which is why the two can disagree. This is a warning: the render succeeds and the message names the variables.

**Typical fix:** Write the real copy: 'arcavex data set <variable> "..."' (MCP: arcavex_data_set) or 'data import', or edit the project's data file directly, then render again.
