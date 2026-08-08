# Public-readiness fix list

Findings from an end-to-end adversarial use session: two complete poster systems (three
natively-composed ratios each, bilingual EN/FA, one custom raster extension, ~40 renders across four
design revisions) authored entirely through the MCP + CLI surfaces by an AI agent — the exact primary
persona in spec §1.4.

Baseline at time of audit: `main` @ `2e0f8b7`, **591 passed / 1 skipped / 0 failed**, `doctor` 9/9,
142 diagnostic codes. The engineering is sound. Everything below is about the *authoring contract*,
which is what a public user actually touches.

**Release gate proposed:** P0 + P1 ship before any public link. P2 ships before the pitch mentions AI
authoring. P3 is post-launch.

---

## Status

Every item below is implemented on `integration/public-readiness`, branched from `2e0f8b7`. Suite:
**726 passed, 1 skipped** (from 590 + 1 at the audit baseline). `ruff`, `mypy --strict` on the
kernel, and `lint-imports` all clean.

| Item | State | Where |
|---|---|---|
| P0-1 strictness sweep | done | `fix/p0-1-strictness` |
| P0-2 pin dependencies | done | `f0f1c39` |
| P1-1 `ext test` encoding | done | `fix/p1-1-ext-encoding` |
| P1-2 `ARC-LAY-057` | done | `fix/p1-2-maxlines` |
| P1-3 Raise → Lower | done | `fdc02d0` |
| P1-4 `max_lines` under `wrap` | done | `5bd5ff5` |
| P2-1 overlap `kind` | done | `fix/p2-1-overlap-kind` |
| P2-2 `font` command | done | `fix/p2-2-font-cmd` |
| P2-3 / P2-4 encoding sweep | done | `0b9fa04` |
| P3-1 `ARC-AST-020` warning | done (tier one) | `b26b441` |
| P3-1 `fit: content-box`, `asset prep` | **not built** — tier two, see [backlog.md](backlog.md) | — |
| P3-2 judgement boundary | documented | `59c3123` |
| P3-2 `audit` command | **not built** — candidate only, see [backlog.md](backlog.md) | — |

Three findings changed on contact with the code, and the entries below have been corrected in place
rather than left as written:

1. **P2-4 was not an encoding problem.** `python -m importlinter.cli lint` dispatches nothing at
   all — it exits 0 with no output even against a deliberately broken contract. The gate had never
   run, on any platform.
2. **P3-1's ~60% threshold fires on `examples/hello-poster/logo.png`** (0.483). Shipped at 0.40,
   calibrated against every asset in the repository.
3. **The audit's baseline of "591 passed"** was 590 passed + 1 skipped; `addopts = "-q"` plus a
   second `-q` suppresses the summary line, which is the likely origin.

---

## P0-1 — Unknown fields are silently accepted in six of seven authoring scopes

**Severity: release-blocking.** This is the single highest-leverage defect in the repo.

### Symptom

An agent invents a plausible field. The engine answers `OK template is valid`. The field does
nothing. The agent builds a mental model on it and — observed, not hypothetical — writes the
invented behaviour into handoff documentation as though it were an engine constraint.

### Reproduction

```bash
arcavex validate probe.yaml --format t
```

| Scope | Junk key planted | Result |
|---|---|---|
| template root | `bogus_top_key` | **silently accepted** |
| `formats.<name>` | `bogus_format_key` | **silently accepted** |
| `formats.<name>.canvas` | `bogus_canvas_key` | **silently accepted** |
| `variables.<name>` | `bogus_var_key` | **silently accepted** |
| **node top level** | `condition:`, `junk_key` | **silently accepted** |
| `effects[]` entry | `bogus_effect_key` | **silently accepted** |
| `style` / `paragraph` / `fit` / `constraints` / `size` / `run` | `font_wieght` | correctly rejected, `ARC-TPL-051`, valid fields listed |
| `locales.<name>` | unknown setting | correctly rejected |

Strictness is currently the **exception**, not the rule. It holds exactly where a whitelist constant
happens to exist.

This directly contradicts the shipped promise in the `ARC-TPL-051` catalog entry
(`services/diagnostics_catalog.py:218`):

> "Unknown fields are rejected rather than silently ignored, so a misspelled property cannot quietly
> do nothing."

True for inner blocks. False at node level — which is precisely where an AI author invents fields.

Field-level proof that the inert field was inert: deleting every `condition:` line from a working
template produced a **byte-identical** render (`55d74e5b…` before and after).

### Root cause

`services/template/compiler.py` defines `_STYLE_KEYS`, `_PARAGRAPH_KEYS`, `_FIT_KEYS`,
`_CONSTRAINT_KEYS`, `_SIZE_MAP_KEYS`, `_RUN_KEYS` (lines ~108–120) — and **no `_NODE_KEYS`**, no root
key set, no format/canvas/variable/effect key set.

The hook already exists and is already called. `_build_node` line 1084 calls
`_reject_unsupported_constructs(raw, template, keypath)`, and that method
(`compiler.py:1613`) is a vestigial Phase-0 stub:

```python
def _reject_unsupported_constructs(self, raw, template, keypath) -> None:
    # All Phase-0 node-level constructs are now supported; effects/masks/shapes are parsed.
    return None
```

It was emptied when Phase 0 ended and never refilled.

### Fix

Reuse the existing checker (`compiler.py:2495`, the `ARC-TPL-051` raiser — it already emits located
errors with a sorted valid-field hint). Add whitelists and call it at each scope.

Node vocabulary, harvested from every `raw.get(...)` the compiler performs:

```python
_NODE_COMMON_KEYS = frozenset({
    "id", "type", "style", "style_role", "constraints", "effects", "effect_preset",
    "mask", "transform", "visible", "z", "clip", "direction",
})
_NODE_KIND_KEYS = {
    "text":   frozenset({"text", "runs", "paragraph", "fit"}),
    "image":  frozenset({"asset", "fit"}),
    "shape":  frozenset({"shape", "generator", "params", "d"}),
    "group":  frozenset({"children", "layout"}),
    "hstack": frozenset({"children", "layout", "gap", "padding",
                         "main_align", "cross_align", "wrap"}),
    "vstack": frozenset({"children", "layout", "gap", "padding",
                         "main_align", "cross_align", "wrap"}),
    "path":   frozenset({"d"}),
}
_ROOT_KEYS     = frozenset({"version", "style", "variables", "formats", "locales",
                            "preview_data", "root", "seed", "functions"})
_FORMAT_KEYS   = frozenset({"canvas", "patch"})
_CANVAS_KEYS   = frozenset({"width", "height", "dpi", "bleed"})
_VARIABLE_KEYS = frozenset({"type", "required", "default", "doc"})
_EFFECT_KEYS   = frozenset({"name", "params", "preset"})
```

Verify each set against the compiler before landing — the list above is harvested, not authoritative.

### New diagnostics

`ARC-TPL-051` currently says "style, paragraph, fit, constraints, size, or run block". Generalise its
text, and add scope-specific codes so `explain` can be precise (next free numbers in range):

| Code | Meaning |
|---|---|
| `ARC-TPL-064` | Unknown node field — hint lists valid fields **for that node kind** |
| `ARC-TPL-065` | Unknown template root field |
| `ARC-TPL-066` | Unknown format / canvas field |
| `ARC-TPL-067` | Unknown variable-declaration field |
| `ARC-TPL-068` | Unknown effect-entry field |

`ARC-TPL-064` must special-case `condition` by name, because it is the single most likely invention
(every LLM knows `condition` from other template languages):

> `Node 'org-3' has unknown field 'condition'. Arcavex has no per-node condition; gate a node with
> the structural 'if:' / 'node:' construct.`

Do the same for other high-probability inventions: `opacity` at node level (belongs in `style`),
`width`/`height` at node level (belongs in `constraints.size`), `x`/`y` (belongs in
`constraints.anchor`), `rotation` (it is `transform`), `font_size` at node level (belongs in `style`).
A wrong-scope hint is worth more than a generic rejection.

### Migration

This is a breaking change for any template carrying junk. Ship it as the headline of `0.2.0`, and add
one release note: *"Templates that silently carried unknown fields now fail validation. This is the
fix for fields that quietly did nothing."*

### Tests

- Parametrised: for each of the 7 scopes, planting a junk key produces the right code, at the right
  keypath, with the right line number.
- Regression: `condition:` on a node yields `ARC-TPL-064` naming `if:`.
- Every wrong-scope alias produces its targeted hint.
- Sweep every template under `examples/` and `library-seed/` — they must all still validate.

**Effort:** ~1 day including the alias table.

---

## P1-1 — `ext test` crashes on Windows, the declared reference platform

**Severity: release-blocking.** Breaks the gate the extension guide instructs authors to run.

### Symptom

```
UnicodeDecodeError: 'charmap' codec can't decode byte 0x90 in position 306
ERROR ARC-EXT-052 Extension golden test failed (exit 2)
```

The extension is fine — `ext validate` passes and the effect renders correctly. The harness cannot
read its own child process. `ARC-EXT-052` then reports a *test failure*, which is a false accusation:
the honest report is a harness I/O error.

### Root cause

`services/extensions/service.py:209–213`:

```python
completed = subprocess.run(
    ...,
    capture_output=True,
    text=True,          # <-- no encoding= : decodes with the ANSI codepage (cp1252 on Windows)
)
```

Any non-cp1252 byte in the child's stdout/stderr kills the reader thread.

### Fix

```python
completed = subprocess.run(
    ...,
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
)
```

Also set `env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}` on the child so it emits
UTF-8 in the first place, and separate the diagnostics: a decode/spawn failure is a harness error
(propose **`ARC-EXT-053`, "Extension test harness could not read test output"**), not `ARC-EXT-052`.

### Tests

- An extension whose `golden_test.py` prints non-ASCII (e.g. `print("café ✓")`) runs green.
- One that prints raw bytes to stdout does not crash the harness.

**Effort:** ~1 hour. Highest value-per-line fix in the repo.

---

## P1-2 — `ARC-LAY-050` misreports a `max_lines` violation as a box-height overflow

**Severity: high.** Cost a full debugging cycle during the session.

### Symptom

A footer line that was too long reported:

```
ARC-LAY-050 Text node 'footer-venue-2' overflows its box (169.9x20.0pt into 187.5x15.0pt)
  hint: Enlarge the box, shrink the text, or set overflow to clip/allow.
```

Width fits (169.9 ≤ 187.5). So the message points at height. I enlarged the box to 22.5pt — still
failed, reporting the same `20.0pt` measurement. Enlarging further would never have worked: the real
cause was that the text had shrunk to its `min_size` floor and *still* wrapped to 2 lines, violating
`max_lines: 1`. The reported `20.0pt` was the two-line block height.

The hint actively misdirects: "Enlarge the box" cannot fix a `max_lines` violation.

### Fix

Distinguish the two failure modes at the raise site:

- Box-geometry overflow → keep `ARC-LAY-050`.
- Shrink floor reached and line count still over `max_lines` → new **`ARC-LAY-057`**:

> `Text node 'footer-venue-2' still needs 2 lines at its 10px shrink floor but 'max_lines' is 1.`
> `hint: Widen the box, lower 'fit.min_size', or raise 'max_lines'. Enlarging the box height will not help.`

Report *measured line count vs max_lines*, not a height pair, when that is the actual constraint.

### Tests

- Copy that fits width but needs 2 lines at the floor → `ARC-LAY-057`, never `ARC-LAY-050`.
- Copy genuinely too tall for its box → still `ARC-LAY-050`.

**Effort:** ~half a day.

---

## P2-1 — Overlap reporting cannot distinguish a shadow halo from a real collision

**Severity: high for the AI persona.** This is the primary geometry signal for an agent that cannot
see, and it currently cries wolf.

### Symptom

`layout inspect` reported overlaps continuously across all six cells. Every one had to be
hand-filtered and confirmed by eye. Representative:

```
overlaps:
  strip ∩ tag       at (71.2, 257.2, 205.5, 10.5)pt    <- drop-shadow halo, visually clean
  strip ∩ tag-text  at (90.0, 265.5, 174.0, 2.2)pt     <- torn-paper amplitude, visually clean
  org-3 ∩ strip     at (73.5, 161.2, 390.0, 21.8)pt    <- halo, ~41px above the strip's ink
  footer-venue-1 ∩ footer-venue-2                       <- GENUINE 4px text collision
```

The genuine defect is indistinguishable from the noise, so the useful signal gets filtered away with
the rest. In practice the audit had to fall back on human vision — which defeats the purpose.

### Root cause

`kernel/api.py:2637`, `_collect_overlaps`:

```python
ra, rb = a.paint_bounds, b.paint_bounds
```

`paint_bounds` is inflated by effect growth (`layout_anchors/solver.py:119–123`) so the renderer
allocates room for blur and tear amplitude. Correct for allocation; wrong as the sole basis for
collision reporting.

### Fix

`paint_bounds_pt` / `paint_bounds_px` are already on the public model (`kernel/api.py:806–807`), so no
new geometry is needed — only classification. Add a `kind` field to `SiblingOverlap`:

| kind | Condition | Meaning |
|---|---|---|
| `content` | layout `bounds` intersect | genuine collision — act on it |
| `halo` | only `paint_bounds` intersect | effect spill — usually fine |

Then:
- CLI human output groups them and prints `halo` overlaps under a dimmed "effect spill" subheading.
- `--json` and the MCP result carry `kind` so an agent can filter without heuristics.
- Print both `bounds` and `paint_bounds` per node in `layout inspect` text output (today only
  `bounds` is shown, which is why the halo numbers looked inexplicable).

This turns "12 overlaps, all probably fine" into "1 content overlap, 11 halo" — actionable by a blind
agent, no vision required.

### Tests

- Two adjacent text boxes overlapping by 4px → exactly one `content` overlap.
- A drop-shadowed strip beside a clean neighbour → exactly one `halo` overlap, zero `content`.
- The reference poster's rotated-band AABB case is reclassified without weakening its e2e assertions.

**Effort:** ~1 day including CLI/MCP plumbing.

---

## P2-2 — No font installation command

**Severity: medium.** First-run blocker for any non-bundled typeface.

### Symptom

Rendering a template that names an uninstalled family fails. Nothing in `--help` explains how to
install one; the answer (drop a `.ttf` into `$ARCAVEX_HOME/fonts/`) is only in
`docs/quick-start.md` prose. `doctor` reports the family *count* but never the path to add to.

### Fix

Add a `font` command group, mirroring the existing `ext` group's shape:

| Command | Behaviour |
|---|---|
| `arcavex font list [--json]` | families, per-family files, bundled vs installed |
| `arcavex font add PATH [--license PATH]` | copy into `$ARCAVEX_HOME/fonts/`, report the family name **as the engine will resolve it** |
| `arcavex font remove FAMILY` | remove an installed (never a bundled) family |

`font add` reporting the resolved family name closes a real trap: the file stem and the family name
often differ, and templates must name the family.

Extend `ARC-RND-010` (font not found) to list the nearest installed families and name `font add` in
its hint.

**Effort:** ~half a day.

---

## P3-1 — Image preparation has no home in the engine

**Severity: medium.** Recurring manual work; one silent-wrong-output trap.

### Symptom

Two throwaway scripts had to be written outside the engine to complete an ordinary poster:
chroma-key + despill for a green-screen subject, and alpha-trim for logos.

The trap: a 512×512 logo PNG whose artwork occupies a 452×114 band. `fit: contain` correctly scaled
the *canvas*; the mark rendered as an unreadable smudge. **The engine did exactly as instructed and
the output was wrong, with no diagnostic.**

### Fix

Two tiers.

*Cheap, high value — do this one first:*
`asset add` already decodes the image. Compute the alpha bounding box at ingest and store it in the
sidecar. When an image node uses `fit: contain|cover` and the asset's opaque bbox covers less than
~60% of its canvas, emit a warning:

> **Shipped at 40%, not 60%.** Measured against every asset in the repository, a 60% threshold
> fires on `examples/hello-poster/logo.png` (872x581 of artwork in a 1024x1024 canvas, 0.483) — a
> real but minor loss of size, not this failure. A warning that fires on the project's own
> quick-start teaches the reader to ignore it. 0.40 leaves a clear gap on both sides of the 0.197
> case that prompted the diagnostic, and a test sweeps every bundled asset so the number stays
> calibrated. The warning also lives at **compile** time rather than ingest, so `validate` reports
> it before a pixel is drawn and every surface inherits it.

> **`ARC-AST-020`** — `Asset 'igsa-logo.png' is 512x512 but its opaque content is only 452x114
> (20% of the canvas); 'fit: contain' will scale the transparent padding, not the artwork.`
> `hint: Trim to the alpha bounding box, or set fit: content-box.`

*Larger, backlog:* a `fit: content-box` mode that fits the opaque bbox rather than the canvas — which
removes the need to pre-trim at all — and `asset prep` subcommands (`trim-alpha`, `chroma-key`,
`focal-crop`) feeding the annotations `asset annotate` already accepts.

**Effort:** warning ~half a day; `content-box` ~2 days; `asset prep` ~1 week.

---

## P3-2 — Validation cannot see typography, only geometry

**Severity: this is the product-positioning gap, not a bug.**

Across four design revisions, **every** design judgement came from a human/model looking at pixels:
dead zones, a 4px offset echo reading as a bevel, a logo too small to read, page grain too loud at
feed scale, a Farsi line floating with no edge relationship. The engine reported clean validation for
every one of those drafts, including the ones that were rejected outright.

This is not a defect — the engine does what it claims. It is the distance between "deterministic
rendering engine" (true, excellent) and "Photoshop for AI" (implies judgement). Two options:

1. **Recommended: adjust the pitch.** Lead as the deterministic, inspectable, provenance-tracked
   rendering substrate an AI designer runs *on*. Nobody else has byte-reproducible design output with
   a real agent API. Design judgement is a layer above, and probably a separate product that consumes
   this one — building taste into the renderer would compromise the determinism that makes it
   valuable.
2. **Or add a narrow, deterministic `audit` command** — and only checks that are objective and
   testable, never taste:
   - WCAG contrast per text node against its resolved backdrop
   - minimum rendered cap-height at a declared viewing scale ("this 15px label is illegible in feed")
   - declared safe-area assertions (`safe_area:` per format, so story 14/20/6 is machine-checked
     rather than hand-computed as it was here)
   - optical-margin deviation between text left edges in one column

Anything beyond that becomes opinion and does not belong in a deterministic engine.

**Effort:** pitch change, zero. `audit` with those four checks, ~1 week.

---

---

## P0-2 — `mcp` is an unpinned dependency; a fresh install can produce a repo that cannot collect its own tests

**Severity: release-blocking.** Found while implementing P1-1, not in the original audit.

### Symptom

`pyproject.toml:32` declares the dev extra as bare `"mcp"` with no version constraint. `mcp` 2.0.0 removed `mcp.server.fastmcp`, which `src/arcavex/clients/mcp_server.py` imports. When a fresh `uv pip install -e ".[dev]"` resolves to 2.0.0, **the entire test suite fails at collection** — a new contributor's first command on a clean clone errors out.

### Evidence

Observed directly. Six worktree venvs were created from the same `pyproject.toml` within minutes of each other and resolved to **three different states**:

| Worktree venv | `mcp` version | `mcp.server.fastmcp` |
|---|---|---|
| four of six | 1.28.1 | OK |
| one | 1.29.0 | OK |
| one | 2.0.0 | **missing — suite could not collect** |

The developer's main `.venv` has 1.28.1 and works, which is why this is invisible day to day.

The sharper framing: **a project whose headline guarantee is byte-identical determinism does not pin its own development dependencies, and they demonstrably resolve differently across installs on the same machine within the same hour.** That is the first thing a sceptical reader will check.

### Fix

Pin `mcp` to a compatible range in `pyproject.toml` (`mcp>=1.28,<2` at minimum; prefer `==1.28.1` to match what CI and the developer machine actually verified). Audit the other dev extras — `pytest`, `hypothesis`, `ruff`, `mypy`, `import-linter`, `pillow` are all bare — and pin or range them the same way. Consider committing a `uv.lock` so contributor environments are reproducible rather than resolved fresh.

Add a CI job that installs from a *clean* cache and runs the suite, so an incompatible upstream release fails CI rather than a new contributor's first afternoon.

**Effort:** ~1 hour to pin; ~half a day including the clean-cache CI job.

---

## P2-3 — `make docs-diagnostics` rewrites all 143 doc files with CRLF on Windows

**Severity: medium.** Found while implementing P1-1.

### Symptom

`Makefile:23` generates each diagnostic page with `Path(...).write_text(render_markdown(d), encoding="utf-8")`. `write_text` in text mode applies platform newline translation, so on Windows every `
` becomes `

`. Running the documented target rewrites all 143 files, producing a 100+ file spurious diff that buries the one page that actually changed.

The mirror test does not catch it because `read_text` normalises newlines on read, so the round-trip looks clean.

### Fix

Pass `newline="
"` explicitly in the target's generation expression. Add a test that asserts the generated bytes contain no `

`, since the existing read-based comparison is blind to it by construction.

### Note — the same bug class, three times

This is the third instance of one root cause found in a single session: `ext test` decoding child output with the ANSI codepage (P1-1), this target writing with platform newline translation, and `lint-imports` silently producing **zero output** until `PYTHONIOENCODING=utf-8` was forced, because its banner uses box-drawing characters.

For a tool whose declared reference platform is Windows, **encoding and newline handling should be a reviewed checklist item, not incidental**. Worth a single sweep: audit every `write_text`, `read_text`, and `subprocess.run(text=True)` in `src/` and `scripts/` for an explicit `encoding=` and, where the bytes are written, an explicit `newline=`.

**Effort:** ~1 hour for the target; ~half a day for the full sweep.

---

## P1-3 — `ARC-LAY-051` tells the author to do the exact opposite of the fix

**Severity: high.** Found while implementing P1-2. Same defect class, inverted advice.

### Symptom

`services/diagnostics_catalog.py:578`, the `shrink_to_fit` non-convergence hint:

> "**Raise** min_size so a fitting size exists, enlarge the box, or switch the policy to ..."

`min_size` is the **floor** of the shrink search — the smallest size the solver is permitted to try. When text does not fit *at* the floor, raising the floor removes the only candidates that could ever fit. Following the hint makes the failure strictly worse, monotonically.

### Evidence

Measured directly, one node, varying only `min_size`:

| `min_size` | resulting height | outcome |
|---|---|---|
| 40pt | 1056pt | fails, worst |
| 30pt | 612pt | fails |
| 24pt | 406pt | fails |
| 20pt | 264pt | fails |
| 12pt | 90pt | fails |
| **8pt** | — | **fits** |
| **5pt** | — | **fits** |

Raising is monotonically worse; lowering is the fix.

### Fix

One word: **"Raise"** → **"Lower"** in the catalog entry. Review the `ARC-LAY-051` raise-site hints in `solver.py` for the same inversion while there.

Add a test that asserts the hint recommends lowering, so the wording cannot silently invert again.

**Effort:** ~15 minutes including the test. Highest value-per-character fix in the repo.

---

## P1-4 — `max_lines` under `wrap` still reports the misleading height pair

**Severity: medium.** The unfixed remainder of P1-2, scoped out deliberately.

`ARC-LAY-057` covers `shrink_to_fit` only. A node using `policy: wrap` with `max_lines` and
`overflow: error` still raises `ARC-LAY-050` with the same measured-vs-box height pair that
misled the author originally. There is no shrink floor to name in that state, so `ARC-LAY-057`'s
wording does not apply as written — it needs its own message, or a generalised one.

**Effort:** ~half a day.

---

## P2-4 — `make contracts` can silently pass a broken contract set

**Severity: medium.** Found while implementing P1-2.

`python -m importlinter.cli lint` — the invocation the Makefile's `contracts` target uses — exits 0
and prints **nothing** in this environment. A target that prints nothing and exits 0 is
indistinguishable from a target that passed.

### Corrected during implementation — this was not an encoding bug

The diagnosis above assumed a console codepage killing import-linter's box-drawing banner, and
filed it as the fourth instance of the encoding root cause. That was wrong, and the truth is worse:
**`python -m importlinter.cli lint` dispatches nothing at all.** It exits 0 with zero output
regardless of encoding.

Verified rather than assumed — a deliberately forbidden `clients` → `kernel` contract was appended
to `pyproject.toml`, and:

| Invocation | Exit | Output |
|---|---|---|
| `python -m importlinter.cli lint` | **0** | none |
| `lint-imports` (console script) | 1 | names the violating import chain |

So the architecture gate inside `make verify` had never checked anything, on any platform, and no
amount of encoding work would have revealed that. The fix is the console script, guarded by
`tests/unit/test_toolchain.py`, which parses the recipe and fails if the no-op form returns.

The encoding problem is real but secondary: `lint-imports` produced 552 bytes without
`PYTHONIOENCODING=utf-8` against 1188 with it, so its output was being truncated too. Both are
fixed.

One reason this survived eight phases: `make` is not installed on the reference machine. Nobody
could run the target — they ran `lint-imports.exe` directly, which works.

**Effort:** as estimated; the diagnosis cost more than the fix.

## Cross-cutting: the meta-lesson for the diagnostics system

The catalog is genuinely good — 142 located codes, `explain` for every one, real fixes in the hints.
Three of the four defects above share one root pattern, and it is worth encoding as a rule:

> **Every authored key must reach either a behaviour or a diagnostic. A key that reaches neither is a
> bug in the engine, not in the template.**

Suggested guard so this cannot regress: a test that walks the template schema surface and asserts
every scope rejects an unknown key. That single test would have caught P0-1 and would have prevented
the vestigial `_reject_unsupported_constructs` stub from surviving eight phases.

Second, smaller rule, from P1-2 and P2-1: **a diagnostic's hint must be capable of fixing the
problem.** "Enlarge the box" for a `max_lines` violation, and an unlabelled halo overlap, both fail
this test.

---

## Sequencing

| Order | Item | Effort | Gate |
|---|---|---|---|
| 0 | P0-2 pin `mcp` (+ dev extras) | 1 hr | **blocks public link — a clean clone may not build** |
| 1 | P1-1 `ext test` encoding | 1 hr | ships in a patch release immediately |
| 2 | P0-1 strictness sweep + 5 new codes | 1 day | **blocks public link** |
| 3 | P1-2 `ARC-LAY-057` max_lines | 0.5 day | blocks public link |
| 3b | P1-3 `ARC-LAY-051` Raise→Lower | 15 min | blocks public link |
| 4 | P2-1 overlap `kind` | 1 day | blocks "AI-authoring" claim |
| 5 | P2-2 `font` command | 0.5 day | blocks public link |
| 5b | P2-3 `docs-diagnostics` CRLF + encoding sweep | 0.5 day | blocks public link |
| 6 | P3-1 `ARC-AST-020` alpha-bbox warning | 0.5 day | post-launch |
| 7 | P3-2 positioning decision | — | before any launch copy is written |

**≈ 5 engineering days** stands between the current state and a defensible public release. The
foundation underneath is already there.

---

## What is already right, and should not be touched

Recorded so a refactor does not erode it:

- **Determinism held across ~40 renders and four full redesigns.** Byte-identical every time,
  including across a design change that touched every node. This is the moat.
- **`layout inspect` earns its place.** It caught real overlaps and every `shrunk` overflow state that
  validation passed — the gap the spec claims exists, does exist, and is useful.
- **`ARC-TPL-053`** (`line_height` unsupported) is a model diagnostic: names the field, explains the
  platform reason, says when it arrives. More codes should read like this one.
- **`render_preview` returning the image as MCP content** is what made agentic iteration possible at
  all. Do not make it a path-only return.
- **The honesty of the docs.** `known-limitations.md` discloses two missed performance targets with
  real numbers; the extension guide refuses to claim a security sandbox; `rerun` refuses to claim
  bit-exactness across platforms. That earns more trust than a clean-looking claim would.
