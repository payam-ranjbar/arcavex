# Phase 06 code review — Trusted local extension SDK

**Commit reviewed:** `9e02c15` (diff base `6ba7fd7`)
**Reviewer:** adversarial code review (execution-based)
**Date:** 2026-07-14

## Verdict: ACCEPT

Phase 6 meets its exit criterion. A reviewed local effect extension can be
scaffolded → validated → tested → added → enabled → used by a template with **no
core modification**, verified live in a fresh `ARCAVEX_HOME`. The determinism
lint, the bounds-honesty golden check, and the located `ARC-EXT` diagnostics all
work under execution. **The trust boundary is documented honestly — no sandbox
claim survives anywhere in the diff** (the phase's integrity requirement, spec
§7.3). No P0/P1 findings.

One P2 (scaffold overclaims validity for 6 of 8 component kinds) and four P3s are
recorded below; none block acceptance, and the P2 does not touch the primary
`effect` path the spec exit criterion exercises.

---

## Gates (all green)

| Gate | Command | Result |
|---|---|---|
| Tests | `pytest tests -q` | **514 passed**, exit 0 |
| Lint | `ruff check src tests` | pass |
| Types | `mypy src/arcavex/kernel --strict` | pass (12 files) |
| Contracts | `importlinter.cli lint` | pass — incl. the new **"SDK imports only the kernel"** contract |

Note: the Makefile `typecheck` gate is kernel-only. `mypy --strict` on `sdk/` +
`services/` (spec §9) cannot run under this interpreter because numpy's bundled
`.pyi` uses a 3.12+ `type` statement — a **pre-existing** tooling limitation
(services has imported numpy since earlier phases), not a Phase 6 regression.

---

## Trust-boundary honesty (spec §7.3 — the integrity requirement): PASS

Grepped the entire Phase 6 diff (code, docstrings, diagnostics, README,
`docs/extension-guide.md`) for `sandbox|malic|secur|protect|isolat|attack|threat|
untrusted|defen|exploit|harden|confin`. **Every single hit is an explicit
negation of a security claim**, e.g.:

- `extension-guide.md` leads with a bold: *"A Python extension is trusted local
  code… Arcavex does not sandbox it. Validation catches compatibility and
  authoring mistakes, never malice — review any extension you did not write…"*
- validator: *"None of this is a security sandbox… a deliberately malicious
  extension is out of scope (spec §7.3)."*
- loader / service: crash-contained subprocess framed as *"crash isolation for
  reliability, not confinement of hostile code."*
- import + determinism checks framed as **reproducibility/authoring** rules
  (spec §3.2), diagnostics say *"an authoring rule, not a security boundary."*
- §7.4 deferred untrusted (WASM/OS-isolated) runtime noted honestly in the guide.

The one line that reads *"This is not hedging; it is the security model"* is, in
context, an explicit statement that **the disclaimer itself is the posture** — it
disclaims a sandbox in the same paragraph. No sandbox-implying phrasing found.
No P1.

## Flagged deviation (SDK homes the effect runtime types): VERIFIED sound

The implementer moved `RasterContext`/`GeometryContext`/`ColorContext`/
`CompositeContext`, `SurfacePool`, the color transforms, and `effect_rng` into
`arcavex.sdk`, and `builtin/effects_core/context.py` now **re-exports** them.
Verified behavior-preserving:

- `arcavex.sdk.RasterContext is arcavex.builtin.effects_core.context.RasterContext`
  → **True** (single class object).
- The real render path constructs that class: `backend.py:198`
  `ctx = RasterContext(image, planned.params, rng, self._pool, self._dpi)`,
  imported from `effects_core.context` (the re-export).
- Therefore an extension's `isinstance(ctx, RasterContext)` narrowing is exact —
  the identity test is real, not cosmetic.

---

## Execution evidence per criterion

**(4) Loader lifecycle** — fresh `ARCAVEX_HOME`, two-invocation checks:
- `ext add examples/extensions/paper-texture` → recorded **disabled**
  (`enabled:false` in `ext list --json` and `state.toml`).
- `ext enable` → next fresh process renders a template using `paper-texture`
  successfully (**exit 0**).
- `ext disable` → next fresh process **fails** the same template with
  `ARC-FX-910 … unknown effect 'paper-texture'` and lists the registered effects
  (which no longer include it), **real exit 1**. This proves the extension effect
  genuinely registers into the same effect registry as built-ins and that
  disabling deregisters on next start.
- Duplicate name across two enabled extensions → `ARC-EXT-001` in
  `list_extensions.load_diagnostics` naming both providers.
- `engine_min = "99.0"` → `ARC-EXT-020` located, exit 1.
- ext→ext dependency: structurally prevented (no `depends` manifest field;
  `from arcavex.*` flagged `ARC-EXT-030`; the sibling synthetic package is not
  importable at validate time → `ARC-EXT-021`).

**(5) Validator — every seeded failure fires a located `ARC-EXT` + exit 1:**

| Seeded fault | Code |
|---|---|
| Invalid TOML | ARC-EXT-011 |
| Missing `engine_min` | ARC-EXT-012 |
| `from arcavex.services…` import | ARC-EXT-030 |
| `import random` | ARC-EXT-031 |
| `time.time()` + `open().read()` in `apply` | ARC-EXT-031 ×3 |
| `param_schema = dict` | ARC-EXT-023 |
| `engine_min=99.0` | ARC-EXT-020 |
| broken SkSL (`SKSL` attr) | ARC-EXT-032 |

**(6) GoldenHarness bounds honesty:** a scratch effect declaring `Insets()` (zero)
but painting the whole padded canvas opaque **fails** `ARC-EXT-050` naming the
discrepancy on all four sides (*"paints ~24.0pt but declares 0.0pt (under-declared
— output would be clipped)"*), `ext test` exit 1. The honest `paper-texture`
(true zero expansion) passes.

**(7) E2E exit criterion:** `scaffold effect → validate → test → add → enable →
render` all green live; the shipped e2e test `test_full_extension_lifecycle_and_render`
asserts the same and renders a template whose node applies the scaffolded effect.
No core file touched.

**(8) Determinism:** `effect_rng` is the **sha256 tree** (`sha256(seed\0node\0idx)`
→ `default_rng`), never Python `hash()`/`random`. Verified: same
`(seed,node,idx)` → identical stream; different `node_id` → independent stream.
The reference golden test asserts same-seed byte-identity.

**(9) MCP:** 24 registered tools, **none** for extension authoring (no scaffold/
add/enable/validate). Authoring stays CLI/API-only (spec §6.2) as required.

**(10) Architecture / regression:** kernel purity + SDK-boundary + client-boundary
enforced by passing import-linter contracts; loader/validator/manifest/state live
under `services.extensions`; CLI `ext` subcommands parse-and-present through the
facade. Regression spot renders: `hello-poster` exit 0, `pop-art-grid` exit 0.
All 19 `ARC-EXT-001…060` codes referenced in code have doc pages (coverage
complete; the catalog coverage test passes in the suite).

---

## Findings

### CR-1 (P2) — Scaffold overclaims "immediately-valid" for 6 of 8 kinds
`services/extensions/scaffold.py` module docstring and `ExtensionService.
scaffold_extension` docstring both promise a *"complete, immediately-valid… it
validates and tests green out of the box"* directory. True only for `effect` and
`mask`. Verified: `ext scaffold {exporter|shape|layout_solver|template_function}`
then `ext validate` **fails immediately** — the `_generic_module` stub sets only a
`name` ClassVar, leaving the contract's abstract methods (and, for shape, the
`param_schema`) unimplemented → `ARC-EXT-021`/`022`/`023`. `backend` and `decoder`
are the same generic path.
- Impact: a user scaffolding any non-effect/mask kind gets a starter that does not
  pass the very next command, contradicting the promise the CLI prints
  (*"validate, test, then add it"*). The `scaffold_files` helper docstring is
  honest ("other kinds get a minimal contract stub"), so the defect is the
  overclaiming higher-level docstrings **and** the non-working starter.
- Not on the phase's required path (`effect` works; spec §7/§11 examples are
  effects), hence P2 not P1.
- Fix: either ship minimal working stubs for all eight kinds, or make the two
  docstrings + the CLI success hint state that non-effect/mask kinds are TODO
  stubs needing implementation before they validate.

### CR-2 (P3) — Determinism lint is shallow (honest, but note the limit)
`_scan_determinism` flags `random` module-wide but wall-clock/filesystem reads
**only** inside methods literally named `apply/build/solve/call/export/decode/
render`. `import time` is not flagged at module scope, and a read hidden in a
helper (`def _compute(self): return time.time()`) or behind an alias escapes.
`open()` is caught only as a bare `Name`; `Path(x).open()` (tail `open`, not in
`_FS_READS`) escapes. This is inherent to an AST heuristic and matches the honest
"improves reliability, not a guarantee" framing — but `extension-guide.md` should
state that the lint is best-effort so authors don't read it as exhaustive.

### CR-3 (P3) — Duplicate diagnostic names incumbent by class, not extension
`ARC-EXT-001` reports the incumbent provider via `type(registry.get(name)).
__name__` (the component **class**), not its extension name. Two extensions
shipping identically-named classes yield *"already provided by DupeFx, cannot also
register 'dupe-b''s DupeFx"* — the first extension is not identifiable. Spec §3.3
("naming both providers") is arguably satisfied by class name, but recording the
incumbent's extension name (a small provenance map in the loader) would
disambiguate.

### CR-4 (P3) — SDK reaches two kernel modules beyond "contracts + ir"
The brief's item 3 says the SDK imports only `kernel.contracts` + `kernel.ir`. It
also imports `kernel.diagnostics` (`Diagnostic`, `diagnostic` — for
`GoldenResult`) and `kernel.registry` (`Registries` — for `register_component`).
Both are pure-kernel and spec-sanctioned (§7.1 lists registration helpers and the
GoldenHarness), and the import-linter contract (which forbids only services/
builtin/clients/bootstrap) permits and passes them — so this is not a mechanized
violation. Worth a design question only: `register_component`/`Registries` is
loader-facing, never called by an extension (which has no `Registries` handle), so
it is dead surface on the extension-facing SDK.

### CR-5 (P3) — Generated run outputs committed to the repo
Phase 6 committed five timestamped `outputs/<ts>/` run directories
(`manifest.json` + `template.square.png`). `.gitignore` covers only
`outputs/working/` and `outputs-tmp/`, so real run outputs are accumulating in git
across phases (many already tracked at HEAD). Add `outputs/` (excepting any
intentionally-kept fixture) to `.gitignore` and drop the tracked run dirs.

---

## Carry-overs (from the brief)
- **watch → services.template.loader** two-client import: left with a note — the
  `allow_indirect_imports = "true"` exception on the client contract carries an
  explanatory comment (per brief "else leave with a note"). Acceptable.
- **CR-5 data-validation compile-only**: untouched, remains documented. Acceptable
  (not Phase 6 scope).

## Commands run
```
.venv/Scripts/python.exe -m pytest tests -q                    # 514 passed
.venv/Scripts/python.exe -m ruff check src tests               # pass
.venv/Scripts/python.exe -m mypy src/arcavex/kernel --strict   # pass
.venv/Scripts/python.exe -m importlinter.cli lint              # pass
# fresh ARCAVEX_HOME lifecycle: scaffold/validate/test/add/enable/list/render
# 8 seeded validation failures; duplicate-name; lying-bounds effect
# regression renders: hello-poster, pop-art-grid
```
