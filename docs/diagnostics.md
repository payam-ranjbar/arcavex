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
**201** documented codes, one Markdown file each. Do not hand-edit the `docs/diagnostics/*.md`
files — edit the catalog and regenerate.

## Unknown fields are always rejected

Every mapping you can author is checked against a known vocabulary. A field the engine does not
read is a **located error**, never a silent no-op — so a misspelling (`font_wieght`) and an
invented field (`condition:` on a node) both fail validation instead of quietly doing nothing.

| Scope | Code |
|---|---|
| template root | `ARC-TPL-065` |
| `formats.<name>` and its `canvas` | `ARC-TPL-066` |
| `variables.<name>` declaration | `ARC-TPL-067` |
| node top level | `ARC-TPL-064` |
| `effects[]` entry | `ARC-TPL-068` |
| node sub-blocks — `style`, `paragraph`, `fit`, `constraints`, `size`, `runs[]`, `transform`, `mask`, `padding`, and the `repeat`/`if` constructs | `ARC-TPL-051` |
| `locales.<name>` | `ARC-TPL-099` |

`ARC-TPL-064` goes further than rejecting the field: where an invented name has an obvious real
home it says so, rather than only listing the vocabulary.

```console
$ arcavex validate poster.yaml
ERROR ARC-TPL-064 Node 'org-3' has unknown field 'condition'
  poster.yaml:48  root.children[2].condition
  hint: Arcavex has no per-node condition; gate a node with the structural 'if:' / 'node:'
        construct in the parent's 'children:' list.
```

The same applies to `opacity`/`color`/`font_size` (they belong in `style`), `width`/`height`
(`constraints.size`), `x`/`y` (`constraints.anchor`), and `rotation` (`transform`). A field that
is real but belongs to a different node kind names that kind.

A field that is *authored but deliberately unsupported* keeps its own, more specific
diagnostic instead: `line_height` reports `ARC-TPL-053` and a stack's `wrap` reports
`ARC-LAY-056`.

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
| `ARC-TPL` | 67 | Template loading, variables, formats, nodes, constructs, expressions, patches, locales, authoring | `ARC-TPL-014` missing variable, `ARC-TPL-051` unknown sub-block field, `ARC-TPL-064` unknown node field, `ARC-TPL-061` repeat+if, `ARC-TPL-097` section defined twice, `ARC-TPL-100` undeclared locale |
| `ARC-LAY` | 20 | Anchor/layout solver, sizes, stacks, fit policies | `ARC-LAY-030` under-constrained, `ARC-LAY-033` fill overshoots its parent, `ARC-LAY-052` sibling cycle, `ARC-LAY-054` stack child anchors, `ARC-LAY-050` overflow=error, `ARC-LAY-057` max_lines at the shrink floor |
| `ARC-IR` | 10 | Dimensions, sizes, colors, transforms, duplicate ids, masks, finite coordinates | `ARC-IR-011` invalid dimension, `ARC-IR-015` invalid hit-test coordinate, `ARC-IR-020` duplicate id, `ARC-IR-030` invalid color |
| `ARC-RND` | 12 | Fonts/glyphs, font installation, resource budgets | `ARC-RND-010` family not found, `ARC-RND-011` missing glyph, `ARC-RND-020..023` budget (exit 4), `ARC-RND-031` unsupported font file |
| `ARC-FX` | 8 | Effects, masks, shape generators | `ARC-FX-902` invalid params, `ARC-FX-910` unknown effect, `ARC-FX-913` unknown generator |
| `ARC-EXT` | 21 | Extension manifest, compat, imports, determinism, golden test | `ARC-EXT-001` duplicate component, `ARC-EXT-030` import surface, `ARC-EXT-050` dishonest bounds, `ARC-EXT-053` test harness I/O |
| `ARC-PRJ` | 15 | Project manifest, discovery, status, snapshots, metadata, policy, proposals, detach | `ARC-PRJ-001` no project, `ARC-PRJ-008` invalid UI metadata, `ARC-PRJ-014` unsafe working path, `ARC-PRJ-015` placeholder copy still in project data |
| `ARC-STY` | 4 | Style packs, presets, roles | `ARC-STY-001` unknown pack, `ARC-STY-010` unknown preset |
| `ARC-AST` | 5 | Asset resolution, decode, guards, traversal, shape advice | `ARC-AST-003` decode guard, `ARC-AST-004` path escape, `ARC-AST-020` mostly-transparent asset under contain/cover |
| `ARC-EXP` | 4 | Exporters (write, encode, PDF, extension) | `ARC-EXP-001` export write failed, `ARC-EXP-011` unsupported extension |
| `ARC-LIB` | 4 | Versioned library publish/resolve | `ARC-LIB-002` version immutable, `ARC-LIB-003` ambiguous bare name |
| `ARC-RUN` | 2 | Recorded runs, rerun drift | `ARC-RUN-001` run not found, `ARC-RUN-002` input drift |
| `ARC-SKL` | 4 | Bundled design-skill installation | `ARC-SKL-001` unknown target, `ARC-SKL-003` already installed |
<<<<<<< HEAD
| `ARC-MCP` | 7 | Registering the MCP server with an AI host (001-004), and MCP tool-call arguments (010+) | `ARC-MCP-002` host not found, `ARC-MCP-003` already registered, `ARC-MCP-010` unknown argument, `ARC-MCP-011` missing argument, `ARC-MCP-012` invalid value |
| `ARC-EDT` | 14 | Semantic editor: locking, transactions, structure, policy, history | `ARC-EDT-001` project locked by another writer, `ARC-EDT-005` cycle refused, `ARC-EDT-007` orphaned anchors, `ARC-EDT-009` policy refusal |
=======
>>>>>>> 2013aeb (feat(editor): add an explicit write scope to semantic transactions)
| `ARC-INT` | 4 | Engine/build identity and wrapped internal error (exit 5) | `ARC-INT-010` build commit unavailable, `ARC-INT-011` no executable artifact, `ARC-INT-999` internal error |

Browse the full per-code detail under [`docs/diagnostics/`](diagnostics/), or ask the engine with
`arcavex explain <code>`. Diagnostics that surface while authoring templates are cross-referenced
throughout [template-schema.md](template-schema.md).
