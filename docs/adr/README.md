# Architecture Decision Records

Non-obvious, hard-to-reverse decisions are recorded here as numbered ADRs — each with its context,
the decision taken, and the consequences. They are the "why" behind engine behavior that the
reference docs describe as "what". The process for adding one is in
[contributing.md](../contributing.md#adr-process).

| ADR | Title | Status | Shapes |
|---|---|---|---|
| [0001](0001-skia-python-144-platform-baseline.md) | skia-python 144 platform baseline and textlayout binding constraints | Accepted | The text stack: RTL via BiDi isolates, fit policies computed by Arcavex, paragraph-level metrics, `line_height` deferral (`ARC-TPL-053`), ICU handling, the ARM64 caveat. |
| [0002](0002-direction-inheritance-and-data-layering.md) | Direction inheritance, null-as-value, and locale data layering | Accepted | Group `direction` inheritance, explicit `null` binding null in every layer, and the four-layer effective-data precedence (preview/defaults → locale overlay → `--data` → sidecar). |

Both are referenced throughout the reference docs — see
[template-schema.md](../template-schema.md#locales-data-layering-and-patches),
[known-limitations.md](../known-limitations.md), and
[architecture.md](../architecture.md#architecture-decisions).
