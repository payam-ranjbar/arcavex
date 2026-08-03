# Diagnostics

Every problem Arcavex reports is a **coded, located diagnostic** — an `ARC-XXX-NNN` code, a
human message, the file/position it applies to, and a typical fix. Codes are a public contract
(spec §9): they are stable, testable, and never scraped from prose. This page is the catalog map;
each code has its own one-paragraph reference under [`docs/diagnostics/`](diagnostics/), and the
engine can explain any of them on the spot.

## `arcavex explain`

```console
$ arcavex explain ARC-TPL-014
ARC-TPL-014 — Required or referenced variable is missing
A variable is required but not provided, or an expression references a variable
that is neither declared nor supplied.
fix: Add the value to your data file, give the variable a default, or guard the
reference with '| default(...)'.
```

`arcavex explain CODE --json` returns the same entry as versioned JSON. An unknown code exits `1`.

## Single source of truth

The catalog lives in code at `src/arcavex/services/diagnostics_catalog.py` — one entry per code
(title, summary, fix). The human-browsable `docs/diagnostics/<code>.md` files are **generated** from
it (`make docs-diagnostics`), and a test (`tests/unit/test_explain.py`) keeps the two in sync while
a coverage test asserts every code the engine can emit has an entry. As of this build there are
**143** documented codes, one Markdown file each. Do not hand-edit the `docs/diagnostics/*.md`
files — edit the catalog and regenerate.

## Exit codes

A command's exit code is the coarse category; the diagnostic code is the specific cause.

| Code | Meaning | Typical diagnostics |
|---|---|---|
| 0 | success (including warnings) | — |
| 1 | validation or authoring error | most `ARC-TPL`/`ARC-LAY`/`ARC-IR`/`ARC-FX`/`ARC-STY` |
| 2 | invalid CLI usage | (Typer usage errors) |
| 3 | missing template, asset, or font | `ARC-TPL-001`, `ARC-AST-001`, `ARC-RND-010` |
| 4 | resource budget exceeded | `ARC-RND-020`…`ARC-RND-023` |
| 5 | internal failure | `ARC-INT-999` |

## Code families

| Prefix | Count | Domain | Representative codes |
|---|---|---|---|
| `ARC-TPL` | 57 | Template loading, variables, formats, nodes, constructs, expressions, patches, locales, authoring | `ARC-TPL-014` missing variable, `ARC-TPL-051` unknown field, `ARC-TPL-061` repeat+if, `ARC-TPL-097` section defined twice, `ARC-TPL-100` undeclared locale |
| `ARC-LAY` | 17 | Anchor/layout solver, sizes, stacks, fit policies | `ARC-LAY-030` under-constrained, `ARC-LAY-052` sibling cycle, `ARC-LAY-054` stack child anchors, `ARC-LAY-050` overflow=error |
| `ARC-IR` | 8 | Dimensions, sizes, colors, duplicate ids, masks | `ARC-IR-011` invalid dimension, `ARC-IR-020` duplicate id, `ARC-IR-030` invalid color |
| `ARC-RND` | 8 | Fonts/glyphs, resource budgets, deferred render features | `ARC-RND-011` missing glyph, `ARC-RND-020..023` budget (exit 4) |
| `ARC-FX` | 8 | Effects, masks, shape generators | `ARC-FX-902` invalid params, `ARC-FX-910` unknown effect, `ARC-FX-913` unknown generator |
| `ARC-EXT` | 20 | Extension manifest, compat, imports, determinism, golden test | `ARC-EXT-001` duplicate component, `ARC-EXT-030` import surface, `ARC-EXT-050` dishonest bounds, `ARC-EXT-053` test harness I/O |
| `ARC-PRJ` | 6 | Project manifest, discovery, status, detach | `ARC-PRJ-001` no project, `ARC-PRJ-002` invalid manifest |
| `ARC-STY` | 4 | Style packs, presets, roles | `ARC-STY-001` unknown pack, `ARC-STY-010` unknown preset |
| `ARC-AST` | 4 | Asset resolution, decode, guards, traversal | `ARC-AST-003` decode guard, `ARC-AST-004` path escape |
| `ARC-EXP` | 4 | Exporters (write, encode, PDF, extension) | `ARC-EXP-001` export write failed, `ARC-EXP-011` unsupported extension |
| `ARC-LIB` | 4 | Versioned library publish/resolve | `ARC-LIB-002` version immutable, `ARC-LIB-003` ambiguous bare name |
| `ARC-RUN` | 2 | Recorded runs, rerun drift | `ARC-RUN-001` run not found, `ARC-RUN-002` input drift |
| `ARC-INT` | 1 | Wrapped internal error (exit 5) | `ARC-INT-999` |

Browse the full per-code detail under [`docs/diagnostics/`](diagnostics/), or ask the engine with
`arcavex explain <code>`. Diagnostics that surface while authoring templates are cross-referenced
throughout [template-schema.md](template-schema.md).
