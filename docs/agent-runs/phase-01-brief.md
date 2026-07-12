# Phase 01 brief — Authoring loop (spec §11 Phase 1)

## Scope

Building on the accepted Phase 0 slice:

1. **Split templates** (§4.1.1): a template may be a directory with `template.yaml` (required)
   plus optional `schema.yaml` (variables), `formats.yaml`, `locales.yaml` (parse+validate the
   file shape but locale APPLICATION stays Phase 2 — accepting the file must not silently drop
   it: if a locale is REQUESTED (--locale) in Phase 1, emit the existing not-supported-yet
   diagnostic), `preview-data.yaml`. Passing the directory or its template.yaml is equivalent.
   Duplicate inline/split definition of the same section = located error (ARC-TPL). Same
   semantics one-file vs split.
2. **Structural constructs** (§4.1.2): `repeat:` (over expression, `as:` name, mandatory
   `key:` expression for object collections; expanded IDs `<authored-id>[<key>]`; index-derived
   key allowed only with explicit `key: "{{ loop.index }}"` + stability warning; iteration cap
   1000) and `if:` conditional nodes. Loop context exposes `loop.index` (0-based), `loop.first`,
   `loop.last`, and the `as` variable. Nested repeats compose.
3. **Registered template functions** (§3.2 TemplateFunction, §4.4): evaluator resolves function
   calls through the registry ONLY (no hardcoded parallel table). Built-ins in
   `builtin/template_fns/`: `upper`, `lower`, `format(fmt, *args)` (printf-style {}), `len`,
   `min`, `max`, `round`, `locale_digits(text, locale)` (fa: ۰۱۲۳۴۵۶۷۸۹ incl. decimal/percent
   forms), `contrast_color(color)` (returns "#000000"/"#ffffff" by WCAG relative luminance).
   Pure, deterministic, no I/O; validated by property tests where meaningful.
4. **Variable schema enforcement** (§4.1.1): declared `type` (string, number, boolean, color,
   image, list, object) checked against supplied data with located diagnostics; a variable
   REFERENCED in the template but not declared and not supplied = ARC-TPL error listing where
   referenced. `enum:` optional values list. Defaults type-checked too.
5. **`arcavex doctor`** (§3.7/§6.1.3): checks python version, skia import + version, ICU/
   icudtl.dat availability (with the copy-remediation hint from ADR-0001), font DB families
   found (counts + names), writable temp dir, and reports engine version. Human table + --json.
6. **`arcavex explain ARC-XXX-NNN`**: prints the diagnostic code's docs entry (one concise
   paragraph + typical fix). Docs entries live in `docs/diagnostics/` as one md per code,
   loaded from package data; `explain` errors helpfully on unknown codes. Every code the
   engine can currently emit MUST have an entry (add a test that enumerates emitted codes vs
   docs files).
7. **`arcavex template new NAME`** (§6.1.3, §6.3): scaffolds a minimal renderable one-file
   template directory (template.yaml + data.yaml + README snippet) that renders out of the box.
   `arcavex template check PATH` = validate without data (schema+structure+preview_data).
   `arcavex template inspect PATH --json` returns variables (name/type/required/default/doc),
   formats, node IDs (with types), functions available, example data (preview_data), version.
   `arcavex template split PATH` converts one-file → split directory losslessly (refuses when
   already split; keeps comments where ruamel allows).
8. **`arcavex preview`** (§6.1.1/§6.3): `arcavex preview TEMPLATE --data D --format F [--watch]`.
   Non-watch: renders to a stable per-template temp path (hash of absolute template path under
   $ARCAVEX_HOME/cache/preview/ or OS temp), prints the path, exit codes as render.
   `--watch`: watchfiles-based loop watching template file/dir + data file + referenced local
   assets; on change: incremental re-render, print one line
   `changed=<file> compile=<ms> render=<ms> -> <preview-path>` and on failure keep last good
   preview + print first actionable diagnostic (§6.3). Ctrl+C exits 0 cleanly. Debounce ~100ms.
   Loop latency target: < 2 s for hello-poster on this machine (measure and report).
9. **JSON/exit codes**: all new commands honor --json/--no-color/--quiet with versioned
   response models; exit codes per §6.1.3.
10. **Tests**: split-template equivalence + duplicate-section error; repeat/if compilation
    incl. stable expanded IDs, key warning, nesting, cap; function registry resolution +
    each built-in fn (locale_digits property test: digits map bijectively; contrast_color
    known pairs); variable type enforcement matrix; doctor --json shape; explain coverage test
    (emitted codes ⊆ documented codes); template new → renders; inspect --json golden;
    split → semantics preserved (compile both, compare CompiledDocument canonical hash);
    watch-mode test (spawn watch, touch data file, poll preview mtime changes, terminate —
    keep timeout-safe on Windows); CLI transcript tests for new commands.

## Carry-over from Phase 0 re-review (fix in this phase)

- RR-1: unknown/typo'd variable `type:` value (e.g. "strnig") must be a located error, not a
  silent skip of type checking.
- RR-2: soften ARC-TPL-015 number-vs-string friction: a number supplied for a declared string
  coerces with a warning (locale-aware stringification is the Phase 1 rule anyway); all other
  mismatches stay errors.
- RR-3: render-time ARC-AST-002 and layout solver diagnostics should carry source locations
  (node keypath/line from compile metadata).
- RR-4: aggregate all non-goal-section diagnostics in one validate run instead of fail-fast.
- RR-5: announce the default output name BEFORE rendering (§6.3 letter).
- CR-13 (ticket): canonical float normalization must be resolved before canonical_hash gains a
  production caller (Phase 4 provenance) — align int/float text forms; note in code TODO with
  this ticket reference. Not required to close Phase 1.

## Non-goals

Locale APPLICATION/direction/digit auto-policy (Phase 2 — but locales.yaml parsing shape may
land), styles (Phase 3), format patches (Phase 2), layout stacks (Phase 2), inspect-layout
command (Phase 2), effects/masks (Phase 3), projects/library/publish (Phase 4), MCP (Phase 5).

## Constraints

- Registry-resolved template functions replace ANY hardcoded evaluator function table
  (Phase 0 remediation may have already done this — check first).
- No second YAML parse path: split loader reuses the ruamel loader with line info.
- Watch preview must not create recorded runs and must write atomically (temp+rename) so a
  viewer never sees a torn PNG.
- Determinism: preview path stable across runs for the same template path.
- Keep ruff/mypy-strict-kernel/lint-imports clean; keep ALL existing tests green.

## Acceptance commands

```powershell
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\arcavex.exe template new outputs-tmp/accept/my-card
.venv\Scripts\arcavex.exe render outputs-tmp/accept/my-card --format <its-format> -o outputs-tmp/accept/card.png
.venv\Scripts\arcavex.exe template inspect examples/hello-poster --json
.venv\Scripts\arcavex.exe template split outputs-tmp/accept/my-card
.venv\Scripts\arcavex.exe preview examples/hello-poster/template.yaml --data examples/hello-poster/data.yaml --format square
.venv\Scripts\arcavex.exe doctor --json
.venv\Scripts\arcavex.exe explain ARC-TPL-014
```

Plus a scripted watch session (start, modify data, observe re-render line, terminate).

## Exit criteria (spec Phase 1)

Save-to-preview loop works under two seconds and reports seeded authoring errors with source
locations; template new/inspect/split/check, doctor, explain work as documented; repeat/if
produce stable IDs; all template functions resolve via registry.
