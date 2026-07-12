# Phase 00 brief — Core model and direct CLI slice (spec §11 Phase 0)

## Scope

Everything needed so that this works on a fresh checkout with only `uv pip install -e .`:

```bash
arcavex render examples/hello-poster/template.yaml --data examples/hello-poster/data.yaml --format square -o out.png
```

Deliverables:

1. **Packaging**: `pyproject.toml` (name `arcavex`, version `0.1.0.dev0`, `requires-python >=3.11`,
   deps: `skia-python>=144.0,<145`, `pydantic>=2`, `typer`, `ruamel.yaml`, `rich`;
   dev extra: `pytest`, `hypothesis`, `ruff`, `mypy`, `import-linter`, `pillow`, `numpy`, `watchfiles`, `mcp`).
   Console script `arcavex = arcavex.clients.cli:main`. `Makefile` with `test`, `lint`, `typecheck` targets.
2. **Kernel IR** (`src/arcavex/kernel/ir/`): pydantic-v2 models per spec §3.1 —
   `CompiledDocument` (ir_version "1.0", canvas w/h/dpi/bleed, color_policy, seed, fonts, root),
   node types (group/text/image/shape/path core fields: id, type, transform, constraints, style,
   effects, mask, visible, z), `LayoutDocument`/`LayoutNode` (source_node_id, bounds,
   absolute_transform, paint_bounds, overflow, resolved content, children).
   `ir/units.py`: `Dim` supporting `mm`, `pt`, `px`, `%` parsing ("40pt", "210mm", "62%", bare
   numbers = px), conversion to pt via dpi (px→pt = px*72/dpi; mm→pt = mm*72/25.4), `Insets`,
   `Rect`, `Matrix3`. `ir/colors.py`: parse hex (#RGB/#RRGGBB/#RRGGBBAA), rgb()/rgba(), named CSS
   basic colors; store normalized RGBA floats. `ir/canonical.py`: canonical hashing — UTF-8 NFC,
   units normalized to pt, sorted mapping keys, stable list order, normalized float repr
   (repr of round(x, 6)), no absolute paths; sha256 hex output.
3. **Diagnostics** (`kernel/diagnostics.py`): `Diagnostic` model per §3.6 (code, severity
   error|warning|info, message, source {file, keypath, line}, hint). `DiagnosticError` exception
   carrying diagnostics. Code registry with namespaces ARC-TPL/IR/LAY/FX/RND/EXP/AST/EXT/PRJ/INT.
   Nothing crosses `kernel.api` as a raw exception: facade wraps unexpected exceptions as
   ARC-INT-999.
4. **Contracts** (`kernel/contracts/`): all eight ABCs per §3.2 (Effect, MaskGenerator,
   ShapeGenerator, Exporter, LayoutSolver, TemplateFunction, RendererBackend, AssetDecoder)
   with typed param-schema class vars. Only LayoutSolver, RendererBackend, Exporter,
   TemplateFunction need working implementations this phase; others are contract + registry only.
5. **Registry** (`kernel/registry/`): one typed registry per contract; duplicate name at
   register time = bootstrap diagnostic naming both providers.
6. **Bootstrap** (`src/arcavex/bootstrap.py`): composition root building registries, registering
   built-ins, returning the facade. Kernel imports nothing from builtins/clients (enforce with
   import-linter config in pyproject).
7. **Template loader + compiler v0** (`src/arcavex/services/template/`): ruamel.yaml safe
   loading with line numbers; one-file template model (version, variables, formats, preview_data,
   root). Variables: type string|number|boolean|list|object|color|image, required flag, default,
   doc. Expression evaluator v0 (`{{ ... }}` only): hand-rolled tokenizer+parser+evaluator (no
   eval), literals, variable paths with dots/indexes, arithmetic + - * / %, comparisons, boolean
   and/or/not, ternary `a if cond else b`, string concat, `len()`, `upper()`, `lower()`,
   `format()`, default operator `x | default(v)`; iteration cap 1000, per-expression 10ms budget;
   exact-match expression keeps native type, interpolation stringifies. `\{{` escape. Missing
   variable -> ARC-TPL error with file/keypath/line + hint. Structural constructs `if:`/`repeat:`
   can be deferred to Phase 1 (do not fake them).
   Compiler: (template, data, format) -> CompiledDocument; resolves units against format canvas,
   normalizes colors, validates node ids unique + stable; semantic validation pass.
8. **Layout v0** (`extensions/builtin/layout_anchors/` as python package
   `arcavex_builtin.layout_anchors` or `src/arcavex/builtin/layout_anchors/` — choose the
   simplest layout that keeps import-linter clean; built-ins may live inside the arcavex
   distribution per spec §3.3): LayoutSolver "anchors" v0 — absolute positioning inside parent:
   anchors top/left/right/bottom/center_x/center_y referencing parent edges with +/- pt offsets,
   size modes fixed / % / fill / fit_content (text measures via measure fn), each node must
   resolve exactly one x, one y, w, h; under/over-constrained -> ARC-LAY error with node id.
   Stacks (hstack/vstack) come in Phase 2 — do not stub them silently; reject with a clear
   "not supported yet" diagnostic if authored.
9. **Text measurement seed** (`src/arcavex/services/text/`): FontDB loading TTFs from
   `library-seed/fonts/` in-repo (resolved relative to package via importlib resources or repo
   path) + optional `$ARCAVEX_HOME/fonts`; builds TypefaceFontProvider + FontCollection
   (`setDefaultFontManager`), one shared `skia.Unicode()`. Paragraph build/measure/paint helper
   with families, size, weight (via skia.FontStyle), color, align (left/right/center), RTL base
   direction via U+2067/U+2069 isolates (rtl flag). This is the ONLY shaper.
10. **Renderer backend v0** (skia): renders LayoutDocument — group (clip optional), shape
    rect/rrect/circle with fill + stroke, text via paragraph paint, image (skia.Image from CAS
    path — Phase 0 may resolve template-relative asset paths directly; full CAS lands later).
    Draw order: document order + z within siblings. Raster surface at canvas px size
    (pt * dpi / 72, rounded).
11. **Exporter**: PNG (skia encode). Stable bytes: no timestamps/metadata.
12. **API facade v0** (`kernel/api.py`): `render_file(template, data, format, output, ...) ->
    RenderResult` and `validate_template(...) -> [Diagnostic]`; returns diagnostics, never raises
    raw exceptions.
13. **CLI v0** (`src/arcavex/clients/cli.py`, Typer): `arcavex render TEMPLATE --data D --format F
    -o OUT` and `arcavex validate TEMPLATE --data D [--format F]`. Exit codes per §6.1.3
    (0 ok/warnings, 1 validation error, 2 usage, 3 missing dep/font/asset, 4 budget, 5 internal).
    `--json` on both. Rich human output with located diagnostics.
14. **Example** `examples/hello-poster/`: one-file template + data yaml — colored background,
    accent rounded rect, title + subtitle text (Inter), one image node optional. Must render.
15. **Tests** (`tests/`): unit tests for units (incl. hypothesis round-trip property), colors,
    canonical hashing stability, expression evaluator (values, precedence, budget, missing var),
    registry duplicate detection, compiler basic + diagnostics located, layout resolution +
    error cases; platform capability test converted from the feasibility probe
    (skia import, textlayout, font load, fa/en paragraph metrics > 0, RuntimeEffect compile,
    PNG bytes deterministic, PDF header) in `tests/unit/test_platform.py`;
    e2e test invoking the CLI via subprocess rendering hello-poster to a tmp dir and checking
    PNG signature + exit code 0; a failing-template CLI test asserting exit code 1 and a
    diagnostic with file+line in `--json` output.

## Non-goals (later phases — do not implement, do not stub as fake successes)

split templates; styles; locales; format patches; repeat/if; watch preview; layout stacks;
effects; masks; projects/runs; MCP; extensions loading from $ARCAVEX_HOME; JPEG/WebP/PDF export;
derived cache. If authored input requests one, emit a located "not supported in this build"
error diagnostic.

## Platform notes (verified in Phase -1 — do not rediscover)

- skia-python 144.0.post2, Windows, venv at `.venv` (Python 3.12). Run everything with
  `C:\Users\payam\Projects\Arcavex\.venv\Scripts\python.exe`.
- `skia.textlayout` minimal API: ParagraphStyle{setStrutStyle,setTextAlign,setTextStyle};
  TextStyle{setFontFamilies,setFontSize,setFontStyle,setColor,setLetterSpacing,setLocale,...};
  Paragraph{layout, paint, Height, Width, LongestLine, Max/MinIntrinsicWidth,
  AlphabeticBaseline, ExceedMaxLines}. NO setTextDirection / maxLines / line metrics.
- `ParagraphBuilder.make(paragraphStyle, fontCollection, skia.Unicode())` — 3 args.
- `FontCollection.setDefaultFontManager(TypefaceFontProvider)` confines fallback to bundled fonts.
- RTL base direction: wrap text U+2067..U+2069; map start/end alignment by direction.
- `canvas.drawRoundRect(rect, rx, ry, paint)` — no RRect overload.
- ICU: `icudtl.dat` must exist beside the BASE interpreter; already in place on this machine.
  Bootstrap should not crash if missing — surface as diagnostic (doctor comes Phase 1).
- `skia.Typeface.MakeFromFile(path)`; `skia.Image.open(path)`; `surface.makeImageSnapshot()
  .encodeToData(skia.EncodedImageFormat.kPNG, 100)`.

## Standards

ruff (line 100) clean; mypy --strict on `src/arcavex/kernel` (others best effort this phase);
Google docstrings on public API; module docstring stating single responsibility; conventional
commit granularity is orchestrator's job — do NOT run git commands. No `print` outside clients.
No network access at runtime. Determinism: no wall clock, no random without seed, dict order
explicit.

## Acceptance commands (run from repo root; orchestrator will re-run)

```powershell
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\python.exe -m arcavex.clients.cli render examples/hello-poster/template.yaml --data examples/hello-poster/data.yaml --format square -o outputs-tmp/hello.png
.venv\Scripts\python.exe -m arcavex.clients.cli validate examples/hello-poster/template.yaml --data examples/hello-poster/data.yaml --json
.venv\Scripts\python.exe -m ruff check src tests
```

(console script `arcavex` also works after `uv pip install -e ".[dev]"`)

## Exit criteria

Hello poster renders from a one-file template with no project or config; the PNG is visually
correct (text visible, positioned, colored background); repeated render produces identical
bytes; failing inputs produce located diagnostics and correct exit codes; tests pass.
