# Phase 06 brief — Trusted local extension SDK (spec §11 Phase 6, §7)

## Scope

1. **The SDK** (`arcavex.sdk`, §7.1): a stable public module re-exporting the contracts and
   helpers an extension author needs — the SPI ABCs (Effect, MaskGenerator, ShapeGenerator,
   Exporter, LayoutSolver, TemplateFunction, RendererBackend, AssetDecoder), param-schema
   helpers (pydantic base + unit-aware field helpers), deterministic RNG (the seeded tree
   helper), path/surface utilities, registration helpers, and a **GoldenHarness** for testing
   effects/exporters. Extensions import ONLY `arcavex.sdk` + explicitly documented IR value
   types (Rect, Insets, Dim, Color, Path2D, etc.) — NOT internal modules. Document the exact
   allowed import surface.
2. **Multi-component manifest** (`extension.toml`, §3.3): name, version, ir_min, engine_min,
   and a `[[components]]` list each with kind (effect|mask|shape|exporter|layout_solver|
   template_function|backend|decoder), name, entry ("module:Class"). Component names globally
   unique by kind; duplicate at bootstrap → diagnostic naming both providers. Extension→
   extension dependencies prohibited in v1.
3. **Local directory loader** (§3.3): loads an extension from a directory containing
   extension.toml + Python modules. NOT python entry points — a custom directory loader that
   imports the entry modules and registers components. Loads from `$ARCAVEX_HOME/extensions/
   sources/<name>/` with state in `$ARCAVEX_HOME/extensions/state.toml` (added/enabled).
   Lifecycle add → validate → disabled → enable (spec §3.3); disabling removes registration
   on next process start; built-ins enabled by default. Trusted local code — validation
   catches compat/authoring errors, NOT malice (no sandbox claim).
4. **Workflow + CLI** (§7.2): `arcavex ext scaffold <kind> <target> [--name]`,
   `arcavex ext validate <path>`, `arcavex ext test <path>`, `arcavex ext add <path>`,
   `arcavex ext enable <name>`, `arcavex ext disable <name>`, `arcavex ext list`.
   Facade: list_extensions, scaffold_extension, add_extension, validate_extension,
   test_extension, enable_extension, disable_extension. (MCP does NOT expose extension
   authoring — §6.2 defers; keep it CLI/API only.)
5. **Validation** (§7.2): manifest shape, component names, engine/IR compatibility (ir_min/
   engine_min vs current), param schemas present + valid pydantic, imports (only sdk + allowed
   IR types — AST-scan and flag disallowed imports as authoring errors, NOT security), the
   determinism lint (flag `import random`, `time.time`/wall-clock, undeclared filesystem reads
   in effect apply — §3.2 determinism rule), and shader compilation for SkSL effects. Located
   ARC-EXT diagnostics.
6. **GoldenHarness** (§7.1, §8.5): a test helper an extension ships with that renders its
   component against fixtures and checks output + the effect **bounds-expansion honesty**
   (tight vs padded render diff — the declared expansion must match reality). `arcavex ext
   test` runs the extension's golden fixtures in a crash-contained way (subprocess or guarded)
   and reports.
7. **Reference extension** (§11 Phase 6 exit): ship a real, reviewed example extension under
   `examples/extensions/<name>/` (e.g. a `paper-texture` raster effect or a `dot-grid` mask) —
   a complete extension.toml + implementation + golden fixtures + README — that can be added
   and used by a template WITHOUT modifying arcavex core. A test proves: scaffold→validate→
   test→add→enable→render-a-template-using-it, all green.
8. **Extension docs** (§12): docs/extension-guide.md — the SDK surface, the manifest format,
   the workflow, the determinism rules, the trust boundary (trusted local code, review like
   any dependency; NOT a sandbox — §7.3), and the deferred untrusted runtime note (§7.4).

## Non-goals
Hostile-extension isolation / WASM runtime (§7.4 — explicitly deferred; do NOT claim sandbox).
JPEG/WebP/PDF + hardening (Phase 7). MCP extension tools (deferred). GPU.

## Carry-over
Open P3s from phase-05 (check reviews): CR-5 data-validation compile-only (documented);
the clients.watch→services.template.loader import (noted in CR-3) — if cheap, make watch use
a facade method instead so the two-client contract needs no allow_indirect exception; else
leave with a note.

## Constraints
- Extensions import ONLY arcavex.sdk + documented IR types — enforce in validation AND keep the
  sdk itself import-clean (sdk may import kernel.contracts + kernel.ir; NOT services/builtin/
  clients). Add an import-linter contract for the sdk boundary.
- Built-ins already obey the contracts; the loader path must treat a local extension exactly
  like a built-in once registered (same registry, same pipeline).
- Trusted local code: NO sandbox language anywhere. Validation = reliability, not security.
- Determinism: a loaded effect obeys the seeded-RNG rule; the determinism lint enforces it.
- All existing tests green; new ARC-EXT codes documented.

## Acceptance commands
```powershell
.venv\Scripts\python.exe -m pytest tests -q
.venv\Scripts\arcavex.exe ext scaffold effect outputs-tmp/ext/paper-texture
.venv\Scripts\arcavex.exe ext validate outputs-tmp/ext/paper-texture
.venv\Scripts\arcavex.exe ext test outputs-tmp/ext/paper-texture
.venv\Scripts\arcavex.exe ext add examples/extensions/<name>
.venv\Scripts\arcavex.exe ext enable <name>
.venv\Scripts\arcavex.exe ext list --json
# then render a template that uses the extension's component
```
Plus seeded failures: manifest shape error, duplicate component name, incompatible engine_min,
disallowed import, determinism-lint hit (import random in apply), bad param schema — located
ARC-EXT diagnostics, correct exit codes.

## Exit criteria (spec Phase 6)
A reviewed local effect extension can be scaffolded, validated, tested, added, enabled, and
used by a template WITHOUT modifying Arcavex core; the determinism lint and bounds-honesty
golden check work; the trust boundary is documented honestly (no sandbox claim).
