# Using and writing extensions

Most work never needs an extension. Templates cover layout, text, effects, masks, shapes, locales,
and exports; an **extension** is Arcavex's *engine-development* mechanism (spec §7) — you reach for
one only when you need a new component (an effect, mask, shape, exporter, layout solver, template
function, renderer backend, or asset decoder) that the built-ins do not provide and a template cannot
express. Once added and enabled, the engine treats it exactly like a built-in.

This tutorial is the fast path; the complete reference — the SDK surface, the manifest, every
validation gate, the determinism rule, and the trust model — is
[extension-guide.md](../extension-guide.md).

## The trust model — read this first

**A Python extension is trusted local code.** It runs with the full permissions of the Arcavex
process, and Arcavex does not sandbox it. Validation catches compatibility and authoring mistakes,
never malice — review any extension you did not write, including one produced by an AI, like any
other local dependency before you enable it. A deliberately-hostile enabled extension is out of scope
for v1 (a WASM/OS-isolated runtime is future work). The full rationale is in the
[extension guide](../extension-guide.md#trust-boundary--read-this-first).

## Using an installed extension

Once an extension is added and enabled, its components register at engine start and a template uses
them by name — an effect in an `effects:` list, a mask in a `mask:` block, a shape via `generator:`,
and so on. List what is installed:

```console
$ arcavex ext list
paper-texture 0.1.0 disabled — effect:paper-texture
…
```

An added extension is recorded **disabled**; enable it to make its components available on the next
run:

```console
$ arcavex ext enable paper-texture
```

Built-ins are always enabled; disabling takes effect on the next process start (the loader only
registers enabled extensions when the engine boots).

## Writing one: the loop

```
scaffold → implement → validate → golden test → add → enable
```

`ext scaffold` writes a working, valid starter for any kind — a real deterministic component plus a
matching `golden_test.py` — so a fresh scaffold passes `validate` and `test` immediately:

```console
$ arcavex ext scaffold effect ./myfx
Created ./myfx (effect 'myfx') — validate, test, then add it

$ ls ./myfx
README.md  component.py  extension.toml  golden_test.py

$ arcavex ext validate ./myfx
OK myfx — components: myfx
```

Then implement your component in `component.py`, and run the gates:

```console
$ arcavex ext validate ./myfx    # manifest, compat, imports, determinism, param schema, shader
$ arcavex ext test     ./myfx    # re-runs validate, then golden_test.py in a crash-contained subprocess
$ arcavex ext add      ./myfx    # validates, copies into the Arcavex home, recorded DISABLED
$ arcavex ext enable   myfx      # active on the next run
```

## The two rules that matter

1. **Import only `arcavex.sdk`.** That one package re-exports every contract, helper, and IR value
   type an extension may use. Reaching into `arcavex.kernel`, `services`, `builtin`, or `clients` is
   an authoring error the validator flags (`ARC-EXT-030`) — it keeps your extension working across
   engine changes.
2. **Draw all randomness from `ctx.rng`.** Never `import random`, never read the wall clock or an
   undeclared file inside a component method. Non-determinism makes output a rerun cannot reproduce;
   the lint flags it (`ARC-EXT-031`). It is a best-effort AST heuristic, so a clean lint is a
   reliability aid, not a guarantee.

The `GoldenHarness` (which `ext test` drives) additionally checks **bounds-expansion honesty** — a
raster effect that paints wider than its declared `bounds_expansion` fails `ARC-EXT-050`, because the
real pipeline would clip that output.

A complete, reviewed example ships at
[`examples/extensions/paper-texture/`](../../examples/extensions/paper-texture/) — a raster effect
with a committed golden that scaffolds, validates, tests, adds, enables, and renders through a
template with no change to Arcavex core.

## Next

- The full reference → [extension-guide.md](../extension-guide.md).
- Every `ext` subcommand → [cli.md](../cli.md#ext).
- The extension diagnostics (`ARC-EXT-…`) → [diagnostics.md](../diagnostics.md).
