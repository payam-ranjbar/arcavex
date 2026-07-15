# Phase 06 — DX & design review: trusted local extension SDK

**Reviewer role:** engine-extension developer, spec §7 / §6.3-equivalent DX rigor.
**Scope:** `arcavex.sdk`, `extension.toml`, the local directory loader, `arcavex ext ...`,
GoldenHarness, `docs/extension-guide.md`, `examples/extensions/paper-texture/`.
**Commit under review:** `9e02c15`.
**Method:** built a real, original effect extension (`vignette-darken`, a radial darkening
effect — not a copy of the reference example) end to end using only the guide, the CLI
`--help`, and SDK introspection; ran every command in `docs/extension-guide.md` verbatim;
deliberately broke the extension eight different ways and read every diagnostic; scaffolded
all eight component kinds to audit the onboarding artifact, not just the one the brief
suggested.

## Verdict: **Remediate**

The `effect` happy path — the one thing Phase 6's exit criteria actually requires — is
genuinely excellent: scaffold → validate → test → add → enable → render worked on the first
try, the diagnostics for seeded authoring mistakes are some of the best-taught error messages
in the project, and the trust-boundary framing is exactly right. But two findings are serious
enough to block acceptance as written: `ext scaffold` is broken for 6 of 8 documented
component kinds despite an explicit, unqualified "immediately-valid" promise in its own
docstring and `--help` text; and a component-name collision with a built-in — the exact case
the guide calls out by name — is silently accepted by both `ext validate` and `ext add`, only
surfacing later as a non-fatal, easy-to-miss line, with a render-time failure that gives no
hint of the real cause. Both are fixable without touching the parts that already work well.

## Findings

### DX-1 (P1) — `ext scaffold` is only "immediately-valid" for the `effect` kind; 6 of 8 kinds scaffold broken, non-instantiable code

The CLI documents `ext scaffold`'s promise plainly: *"Scaffold a new, immediately-valid
extension directory of the given kind."* `src/arcavex/services/extensions/scaffold.py`'s
module docstring repeats it: *"Writes a complete, immediately-valid extension directory ...
it validates and tests green out of the box."* Neither the guide, the CLI help, nor that
docstring caveats this to `effect` only, and the manifest table in the guide lists all eight
kinds (`effect, mask, shape, exporter, layout_solver, template_function, backend, decoder`) as
equally legitimate `[[components]] kind` values.

I scaffolded each of the eight kinds and ran `ext validate` / `ext test` on each, exactly as
an author exploring the tool would:

| kind | `ext validate` | `ext test` |
|---|---|---|
| `effect` | OK | PASS |
| `mask` | OK | **FAIL** — `ARC-EXT-052 Extension has no golden_test.py to run` |
| `shape` | **FAIL** — `ARC-EXT-023` (no param_schema) + `ARC-EXT-021` (abstract method `build` not implemented) | FAIL (validate already failing) |
| `exporter` | **FAIL** — `ARC-EXT-022` (format mismatch) + `ARC-EXT-021` (abstract method `export`) | **FAIL** — no golden_test.py |
| `layout_solver` | **FAIL** — `ARC-EXT-021` (abstract method `solve`) | **FAIL** — no golden_test.py |
| `template_function` | **FAIL** — `ARC-EXT-021` (abstract method `call`) | **FAIL** — no golden_test.py |
| `backend` | **FAIL** — `ARC-EXT-021` (abstract method `render`) | **FAIL** — no golden_test.py |
| `decoder` | **FAIL** — `ARC-EXT-021` (abstract method `decode`) | **FAIL** — no golden_test.py |

Root cause, in `scaffold.py::scaffold_files`: only `kind == "effect"` gets the real,
implemented reference module and a `golden_test.py`; `kind == "mask"` gets a real component
but no golden test at all; every other kind falls through to `_generic_module`, which emits a
bare subclass with a `"""TODO: implement the {contract} contract."""` docstring and **no
method bodies** — so the ABC's abstract methods are never overridden and the class cannot even
be instantiated. `ext validate`'s diagnostics for this are individually well-formed and
accurate (`ARC-EXT-021` correctly names the missing abstract method), but the artifact they're
describing is not a "minimal deterministic implementation an author edits inward," it's dead
code that fails before an author writes a single line.

Compounding this: `ext test`'s own error hint for the missing file says *"the scaffold ships
one"* — which is only true for `effect`. An author scaffolding a `mask` (which otherwise
validates fine) hits this and has no template to follow, since even `mask`'s golden-test
gap has no example anywhere in the shipped tree to copy from (the `mask` contract has no
golden-test analog to paper-texture the way `effect` does).

**Must change:** either (a) give every kind a real, instantiable, golden-tested starter the
way `effect` and (partially) `mask` get, or (b) scope the "immediately-valid" claim honestly —
in the CLI help, the module docstring, and the guide — to the kinds that actually deliver on
it, and have `ext scaffold` say so for the rest (e.g. "stub for a contract with no reference
starter yet; see §7.1 for the ABC signature"). Silently shipping six broken stubs behind an
unqualified "immediately-valid" claim is the single biggest gap between promise and reality in
this phase.

### DX-2 (P1) — a component name colliding with a built-in is *not* caught by `ext validate` or `ext add`, contrary to the guide's explicit claim, and fails silently at render time

The guide states plainly: *"A duplicate (against a built-in or another extension) fails with
`ARC-EXT-001` naming both providers."* I named a component `blur` (a real built-in raster
effect) inside an otherwise-valid extension and ran the documented gates in order:

```
ext validate ./dup-name   → OK vignette-darken — components: blur       (exit 0)
ext add      ./dup-name   → Added vignette-darken (enable it next)      (exit 0)
ext enable   vignette-darken → Enabled vignette-darken (active on the next run) (exit 0)
```

Every gate the guide documents as part of the safety net reports success. The collision is
only detected when the loader actually boots (triggered here by `ext list`):

```
load ARC-EXT-001 Duplicate effect component 'blur': already provided by Blur,
cannot also register 'vignette-darken''s VignetteDarken
vignette-darken 0.1.0 enabled — effect:blur
```
`ext list` still exits **0**, and the line is prefixed `load` rather than `ERROR` like every
other diagnostic in this CLI — the JSON form does mark it `"severity": "error"`, but the
top-level `"ok"` is `true`, so a script gating on exit code or `ok` would never see it. Worse:
rendering a template that references the extension's intended name doesn't mention the
collision at all —

```
ERROR ARC-FX-910 Node 'background' references unknown effect 'vignette-darken'
  hint: Registered effects: blur, channel-offset, ... (built-ins only — the
  extension's component silently lost the naming collision and was dropped)
```

An author who followed the documented workflow exactly, got two "success" messages
(`ext add`, `ext enable`), and only discovers something is wrong at render time — with a
render error that gives zero indication that an extension tried and failed to register. This
directly contradicts the guide's own claim about when and how a duplicate "fails," and it's
the one seeded-failure scenario in the brief where the diagnostic quality doesn't matter,
because the diagnostic isn't shown to the author who needs it.

**Must change:** run the same duplicate-name check `ext list`'s loader does at `ext validate`
and/or `ext add` time, against the currently-registered built-ins and already-added
extensions — the guide already implies this is when it happens. At minimum, `ext add` must
refuse (or loudly warn) when adding a component name that already collides with something
currently enabled, and the render-time "unknown effect" diagnostic should be able to say "an
extension registered this name but lost to a duplicate — see `ext list`" when that's the
actual cause, rather than looking identical to a plain typo.

### DX-3 (P2) — the guide's "only surface you import" table under-documents the actual `__all__`, and `dir(arcavex.sdk)` leaks a confusable pair

The guide's table (six rows) is a reasonable teaching summary, but `arcavex.sdk.__all__` (the
actual contract) has 15 more public names the table never mentions, several of which are
directly useful and one of which the *scaffold itself imports*: `EffectKind` (used in every
scaffolded effect's `kind: ClassVar[EffectKind]` line — an author reading only the guide table
has no idea what this type is or where it comes from), plus `mm_to_pt`/`pt_to_px`/`px_to_pt`,
`load_png`/`save_png`, `RGBA`, `IDENTITY_MATRIX`/`LUMA`, `BoundsHonesty`/`GoldenResult`,
`ComponentKind`, and several contract value types (`DecodedAsset`, `DecodeGuards`,
`ExportOptions`, `ExportReport`, `MeasureFn`, `MeasureRequest`, `MeasureResult`, `Value`).

Separately, `dir(arcavex.sdk)` (what an author actually sees in a REPL/IDE autocomplete, since
`__init__.py` imports submodules by name as a side effect) surfaces internal submodule names
not in `__all__` at all — `color`, `context`, `params`, `rng`, `surface`, `golden`,
`registration`, `component_kinds` — and one of these, `component_kinds` (a **function**), sits
one capitalization away from `COMPONENT_KINDS` (the actual documented **dict constant**). The
guide never mentions `component_kinds` exists; an author who autocompletes into it (easy to do
reaching for `COMPONENT_KINDS`) gets a working-looking but wrong object with no signal they
picked the undocumented one.

**Should change:** either add `__all__`-driven `dir()` filtering (or `del` the submodule
names after import) so `dir(arcavex.sdk)` matches the documented surface exactly, and expand
the guide's table to cover the full `__all__` (at minimum add `EffectKind`, since the scaffold
depends on an author knowing what it is).

### DX-4 (P2) — `save_png`/`load_png` type-hinted `Path` but not coerced; passing a `str` throws a raw, unhelpful traceback

Building a fixture for my golden test, the natural first call was
`save_png(img, 'fixtures/input.png')` (a plain string — the common case in ad hoc scripts).
That raises:

```
AttributeError: 'str' object has no attribute 'parent'
  at src/arcavex/sdk/golden.py:76, in save_png: path.parent.mkdir(...)
```

No ARC-EXT diagnostic, no hint, just an internal implementation detail (`path.parent`)
leaking through a raw `AttributeError`. This is dev-time SDK usage, not authoring-time
validation, so it's lower severity than DX-1/2, but it's the kind of first-five-minutes
friction that makes a new SDK feel unfinished.

**Should change:** coerce `path: Path` inputs with `Path(path)` at the top of `save_png` and
`load_png` (and anywhere else in the SDK typed against `Path`), or raise a clear `TypeError`
naming the expected type.

### DX-5 (P2) — the scaffold's `golden_test.py` has no committed-golden workflow at all, despite telling the author to add one

The scaffolded `golden_test.py`'s own comment says: *"Add a committed golden image (see
`GoldenHarness.save` / `GoldenHarness.check`) once the look settles."* But the file has no
`fixtures/` or `golden/` directory, no `--update` flag, and hardcodes `golden=None` — the
entire committed-golden mechanism the reference example (`paper-texture`) demonstrates has to
be built from scratch by hand, by reverse-engineering `examples/extensions/paper-texture/golden_test.py`
(which I did, successfully, but only because the reference example happened to be available to
copy from — the guide itself gives no code for this, only prose).

**Should change:** either have the scaffold ship the fixtures/golden layout and `--update` flag
by default (even with `golden=None`-equivalent scaffolding, e.g. an empty `golden/` dir and the
`--update`-aware `main()` shape from paper-texture), or have the guide show the actual
`harness.save(...)` / `--update` code pattern instead of only naming the method.

### DX-6 (P3) — guide says "`save` regenerates the golden," but the real, discoverable command is `python golden_test.py --update`

`docs/extension-guide.md`'s GoldenHarness section: *"comparing to a committed golden image
(`ARC-EXT-051` on mismatch); `save` regenerates the golden."* There is no `arcavex ext ...
save` command, and `save` isn't runnable as written — it's `GoldenHarness.save(...)`, a Python
method, wired into a project-specific `--update` CLI flag that only the paper-texture README
documents. `check()`'s own diagnostic hint (`ARC-EXT-051`) repeats "regenerate the golden with
`GoldenHarness.save`" — same gap.

**Nice to fix:** say `python golden_test.py --update` (the actual, runnable command) in the
guide and in the `ARC-EXT-051` hint, the way the paper-texture README already does correctly.

### DX-7 (P3) — `ext test` alone does not enforce import-surface, determinism-lint, or param-schema rules; running it out of order gives false confidence

I ran `ext test` (skipping `ext validate`) against extensions with a disallowed import and a
broken `param_schema`. Both **passed** — `ext test` only exercises what `golden_test.py`
itself calls, and the scaffolded `golden_test.py` constructs the real params class directly
rather than going through the declared `param_schema`, and never imports anything the
validator would flag. This is defensible (each gate has a distinct job), and the documented
workflow order (`validate` before `test`) protects an author who follows it — but the guide
never says `test` skips these checks, so an author iterating with `ext test` alone in an edit
loop (very natural once things are "working") gets a false green light.

**Nice to fix:** a one-line callout in the guide: "`ext test` does not re-run `validate`'s
import/determinism/schema checks — always `ext validate` before relying on a green `ext test`."

### DX-8 (P3) — the guide's own tutorial reuses the reference example's exact name

`docs/extension-guide.md`'s workflow section has the reader run
`arcavex ext scaffold effect ./paper-texture`, the identical name as the shipped
`examples/extensions/paper-texture/` reference extension referenced two paragraphs later. A
reader who follows the tutorial literally and then also tries the reference example collides
on the extension name at `ext add` time.

**Nice to fix:** use a distinct example name in the workflow snippet (e.g. `my-effect`).

## What impressed

- **Trust-boundary framing is exactly right.** The guide, the `ext add` `--help` text, and the
  `ARC-EXT-030`/`031` diagnostic hints all say the same thing in the same words: this is a
  reliability/reproducibility check, not a security sandbox, and an extension is reviewed like
  any other local dependency. It never once uses alarmist language, and it never once implies
  more protection than exists. This matches spec §7.3 precisely.
- **The seeded-failure diagnostics for the `effect` path are genuinely excellent teaching
  artifacts.** Missing manifest field, bad `kind`, incompatible `engine_min`, disallowed
  import, `import random`, and bad `param_schema` all produced located (file/line), plain-
  English, actionable diagnostics with correct exit codes — every one of them told me exactly
  what to change.
- **The bounds-expansion honesty check is the standout feature of this phase.** I deliberately
  made an effect bleed alpha 3pt outward while declaring zero expansion; the harness reported
  the exact measured-vs-declared value per side ("top: paints ~3.0pt but declares 0.0pt —
  under-declared, output would be clipped") — this is precisely the kind of check that would
  be nearly impossible to hand-write correctly, and it worked first try.
- **The documented `effect` workflow has zero drift.** I ran every command in
  `docs/extension-guide.md`'s workflow section verbatim, plus `arcavex ext --help` and every
  subcommand's `--help`, and every one of them behaved exactly as documented.
- **Once loaded, an extension is genuinely indistinguishable from a built-in.** My
  `vignette-darken` effect referenced from a template's `effects:` list, next to nothing
  extension-specific in the YAML, rendered correctly on the first try with no Arcavex core
  change — the "same registry, same pipeline" promise holds up in practice, not just in the
  architecture description.
- **`arcavex explain <code>` and `docs/diagnostics/ARC-EXT-*.md` are complete** for every code
  I hit, including the ones from my seeded failures.

## Extension-author walkthrough (condensed log)

1. `arcavex ext scaffold effect outputs-tmp/dx6/vignette --name vignette-darken` — succeeded,
   produced a working (if generic "grain" rather than my requested vignette) starter that
   validated and tested green immediately.
2. Rewrote `component.py` as a real radial vignette using only `arcavex.sdk` + `dir()`/
   `inspect.signature()` introspection (no kernel source read) — validated and tested green.
3. Built a committed golden fixture + `--update` workflow by hand, copying the pattern from
   `examples/extensions/paper-texture/golden_test.py` (see DX-5).
4. `ext add` → `ext enable` → referenced `vignette-darken` from a copy of
   `examples/hello-poster/template.yaml`'s `background` node → `arcavex render` → viewed the
   PNG: a correct radial darkening toward the corners, composed cleanly with the built-in shape
   node, no core change required (screenshot verified visually).
5. Ran all eight deliberate-mistake scenarios from the brief (missing field, bad kind,
   duplicate name, bad `engine_min`, disallowed import, `import random`, bad `param_schema`,
   bounds-expansion lie) — six were caught cleanly and well by `ext validate`/`ext test`; the
   duplicate-name case was **not** caught until much later and with no useful signal at the
   point of actual use (DX-2).
6. Scaffolded all eight component kinds to check the onboarding artifact generally, not just
   the one kind the brief's example uses — found six of eight fail `ext validate` outright and
   a seventh (`mask`) fails `ext test` for a missing file its own error message claims exists
   (DX-1).

## Guide accuracy audit

Every command literally written in `docs/extension-guide.md` was run verbatim and matched its
documented behavior: `arcavex ext scaffold effect ./paper-texture`, `validate`, `test`, `add`,
`enable`, `list`, `disable` — all exit codes and output shapes as described. The manifest TOML
example is illustrative (not meant to be copy-run) and is structurally consistent with what
`ext validate` accepts. The two prose gaps found (DX-6: "`save`" vs. the real `--update`
command; DX-8: name reuse with the reference example) are the only drift found in the guide
text itself — everything else in this review is about SDK/tooling behavior versus what the
guide (correctly) claims it does.
