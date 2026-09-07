# Arcavex Desktop Foundation and Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a tested Windows-first Arcavex Desktop viewer that bundles a pinned standalone engine, opens canonical projects in place, renders live, exposes the authoritative layer hierarchy, and survives external AI/CLI edits.

**Architecture:** Extend the Python engine with versioned desktop contracts and MCP parity, generate TypeScript contracts from its JSON Schemas, and host a React workbench in Tauri 2. The Rust core owns the private MCP sidecar, project watcher, latest-wins render queue, settings, and typed event bridge; React depends only on a mockable gateway.

**Tech Stack:** Python 3.12, Pydantic 2, FastMCP, PyInstaller, Rust stable, Tauri 2, React 19, TypeScript, Vite, TanStack Query, Zustand, Vitest, Testing Library, Playwright, axe-core, GitHub Actions.

## Global Constraints

- Preserve the engine as an independently usable CLI/MCP product; desktop behavior enters through public Facade and MCP contracts.
- Open one existing project directory in place. Viewing must not rewrite source or copy the project.
- Keep engine, desktop, project, and render revisions distinct. UI-only metadata changes must not invalidate renders.
- Default automation and extension modes are unrestricted, and live render defaults to every active-target change. All three modes stay visible and changeable.
- Treat the Python sidecar as pinned release input, never as frontend implementation detail.
- Keep feature modules behind ports and registries; only `src/gateway` may invoke Tauri.
- Follow red-green-refactor for each production change and commit after every passing task.
- Do not stage or modify the user's unrelated `.claude/`, `.superpowers/`, or existing untracked files.

---

### Task 1: Establish reproducible toolchains and merge the standalone Windows engine

**Files:**
- Modify: `.gitignore`
- Modify: `pyproject.toml`
- Create/merge: `packaging/arcavex.spec`
- Create/merge: `packaging/build.py`
- Create/merge: `packaging/entry_arcavex.py`
- Create/merge: `packaging/verify_frozen.py`
- Create/merge: `packaging/README.md`
- Modify: `src/arcavex/services/style.py`
- Modify: `tests/e2e/test_packaged_install.py`
- Create: `rust-toolchain.toml`
- Create: `.nvmrc`

- [ ] Record the current Python test, lint, type, and architecture-contract baseline without changing code.
- [ ] Bring the reviewed PyInstaller commit from `worktree-pyinstaller-windows-exe` into this branch, resolving against the integrated engine instead of overwriting newer work.
- [ ] Run `uv run pytest tests/e2e/test_packaged_install.py tests/unit/test_packaging.py -q`; retain a failing assertion before applying any conflict fix.
- [ ] Pin Rust stable and Node 22, add frontend/Tauri build outputs to `.gitignore`, and verify the frozen executable supports both CLI arguments and `mcp serve` over stdio.
- [ ] Run `uv run ruff check src tests packaging`, `uv run mypy src/arcavex/kernel --strict`, `uv run lint-imports`, and the packaged-install tests.
- [ ] Commit as `build: establish pinned desktop toolchains and Windows sidecar`.

### Task 2: Add versioned engine handshake and schema export

**Files:**
- Modify: `src/arcavex/kernel/api.py`
- Create: `src/arcavex/services/desktop.py`
- Modify: `src/arcavex/bootstrap.py`
- Modify: `src/arcavex/clients/mcp_server.py`
- Modify: `src/arcavex/clients/cli.py`
- Create: `scripts/export_desktop_schemas.py`
- Create: `schemas/desktop/engine-handshake.schema.json`
- Create: `tests/unit/test_desktop_contracts.py`
- Create: `tests/mcp_sessions/test_desktop_contracts.py`

- [ ] Write failing tests that assert `EngineHandshakeReport` includes engine/build/artifact identity, response/MCP/IR/SDK versions, named capabilities, Arcavex-home paths, and doctor diagnostics.
- [ ] Add frozen Pydantic models `EngineIdentity`, `EnginePaths`, and `EngineHandshakeReport`; inject a `DesktopServiceProtocol` into `Facade` so the pure kernel keeps its import boundary.
- [ ] Implement artifact hashing and build metadata in `services/desktop.py`; wire it through bootstrap.
- [ ] Add `engine_handshake` to MCP and `arcavex desktop handshake --json` to CLI, both returning the identical model.
- [ ] Export deterministic JSON Schema with sorted keys and a trailing newline; test that two runs are byte-identical.
- [ ] Run targeted unit/MCP/CLI tests, strict mypy, and import-linter.
- [ ] Commit as `feat(engine): expose desktop handshake and schemas`.

### Task 3: Implement project snapshots and independent revisions

**Files:**
- Modify: `src/arcavex/kernel/api.py`
- Modify: `src/arcavex/services/projects.py`
- Modify: `src/arcavex/services/orchestrator.py`
- Modify: `src/arcavex/bootstrap.py`
- Create: `src/arcavex/services/project_snapshot.py`
- Create: `tests/unit/test_project_snapshot.py`
- Create: `tests/property/test_project_revisions.py`
- Modify: `tests/mcp_sessions/test_desktop_contracts.py`
- Create: `schemas/desktop/project-snapshot.schema.json`

- [ ] Write fixtures proving `project_revision` changes for `project.ui.yaml` and policy changes, while `render_revision` changes only for render-affecting template/data/assets/overrides/pins.
- [ ] Define `RevisionManifestEntry`, `ProjectTarget`, `ProjectSourceFile`, and `ProjectSnapshotReport`; include canonical path, metadata, targets, defaults, status, hashes, capabilities, and diagnostics.
- [ ] Build canonical SHA-256 manifests using relative POSIX paths, normalized file bytes, stable ordering, and explicit missing-file diagnostics. Exclude `outputs`, caches, `.arcavex/pending`, and desktop app preferences.
- [ ] Add `Facade.project_snapshot()` and MCP `project_snapshot`; schema-export the model.
- [ ] Add property tests for traversal-order independence and tests that opening a project is read-only.
- [ ] Run target tests plus all existing project/preview tests.
- [ ] Commit as `feat(engine): add project snapshots and revision manifests`.

### Task 4: Add project UI metadata, policy, and proposal queue contracts

**Files:**
- Modify: `src/arcavex/kernel/api.py`
- Modify: `src/arcavex/services/projects.py`
- Create: `src/arcavex/services/project_policy.py`
- Create: `src/arcavex/services/proposals.py`
- Modify: `src/arcavex/services/orchestrator.py`
- Create: `tests/unit/test_project_ui_metadata.py`
- Create: `tests/unit/test_project_policy.py`
- Create: `tests/unit/test_proposals.py`
- Modify: `tests/mcp_sessions/test_desktop_contracts.py`

- [ ] Write failing round-trip tests for absent/default `project.ui.yaml`, display names, locks, colors, and project workspace state without affecting render revision.
- [ ] Add `AutomationMode` (`unrestricted`, `review`, `read_only`) and `ExtensionMode` (`unrestricted`, `disabled`) with approved defaults, persisted in `project.yaml` under a backward-compatible optional `automation` mapping.
- [ ] Define proposal list/approve/reject reports. Store proposals atomically under `.arcavex/pending/<command-id>.json`, recording base revision and actor; never include this queue in project or render hashes.
- [ ] On approval, recheck the base revision and reject stale proposals with a structured conflict diagnostic before any source write.
- [ ] Expose metadata, policy, and proposal operations through Facade and MCP; verify source remains untouched while a review proposal is pending.
- [ ] Commit as `feat(engine): add editor metadata and automation proposals`.

### Task 5: Make the layer hierarchy and hit testing first-class engine reports

**Files:**
- Modify: `src/arcavex/kernel/api.py`
- Modify: `src/arcavex/services/authoring.py`
- Modify: `src/arcavex/services/orchestrator.py`
- Modify: `src/arcavex/builtin/layout_anchors/solver.py`
- Create: `src/arcavex/services/layers.py`
- Create: `tests/unit/test_layer_tree.py`
- Create: `tests/unit/test_hit_test.py`
- Create: `tests/property/test_layer_paint_order.py`
- Modify: `tests/mcp_sessions/test_desktop_contracts.py`
- Create: `schemas/desktop/layer-tree.schema.json`

- [ ] Write authored-tree tests for nested groups, `if`, `repeat`, masks/effects subrows, UI names/locks/colors, and highest-painted-first sibling presentation.
- [ ] Write rendered-tree tests asserting stable authored IDs, unique instance IDs, parent/child links, authored index, resolved paint index, `z`, visibility, editability, bounds, paint bounds, transforms, and source origin.
- [ ] Extend inspection/layout provenance only as needed and compose `LayerTreeReport` in a service that consumes existing compiler and layout contracts.
- [ ] Implement geometry hit testing as reverse paint-order containment over paint bounds, returning ordered `HitCandidate` values with authored/instance IDs.
- [ ] Add Facade/MCP `layer_tree` and `hit_test`, export schemas, and prove MCP output validates against the same model.
- [ ] Run unit/property/MCP tests and existing layout/golden tests.
- [ ] Commit as `feat(engine): expose authoritative layer trees and hit testing`.

### Task 6: Close desktop-required MCP parity and generate TypeScript contracts

**Files:**
- Modify: `src/arcavex/clients/mcp_server.py`
- Modify: `tests/mcp_sessions/test_schema_parity.py`
- Create: `tests/mcp_sessions/test_project_viewer_session.py`
- Create: `scripts/generate_desktop_contracts.mjs`
- Create: `apps/desktop/src/contracts/generated.ts`
- Create: `apps/desktop/src/contracts/index.ts`
- Create: `apps/desktop/src/contracts/generated.test.ts`
- Create: `apps/desktop/package.json`
- Create: `apps/desktop/package-lock.json`
- Create: `apps/desktop/tsconfig.json`

- [ ] Add failing parity tests for project validate/preview plus every desktop contract from Tasks 2-5.
- [ ] Register the missing MCP tools with stable names and typed arguments; keep server functions parse-and-present only.
- [ ] Export all desktop schemas and generate discriminated, readonly TypeScript declarations.
- [ ] Add `npm run contracts:check` that regenerates into a temporary directory and fails on drift.
- [ ] Test known fixture payloads through Pydantic serialization and TypeScript runtime guards.
- [ ] Commit as `feat(contracts): generate desktop types from MCP schemas`.

### Task 7: Scaffold the Tauri application and enforce module boundaries

**Files:**
- Create: `apps/desktop/index.html`
- Create: `apps/desktop/vite.config.ts`
- Create: `apps/desktop/eslint.config.js`
- Create: `apps/desktop/src/main.tsx`
- Create: `apps/desktop/src/app/App.tsx`
- Create: `apps/desktop/src/app/providers.tsx`
- Create: `apps/desktop/src/gateway/ArcavexGateway.ts`
- Create: `apps/desktop/src/gateway/TauriArcavexGateway.ts`
- Create: `apps/desktop/src/gateway/FakeArcavexGateway.ts`
- Create: `apps/desktop/src/shared/test/renderApp.tsx`
- Create: `apps/desktop/src-tauri/Cargo.toml`
- Create: `apps/desktop/src-tauri/tauri.conf.json`
- Create: `apps/desktop/src-tauri/src/main.rs`
- Create: `apps/desktop/src-tauri/src/lib.rs`
- Create: `apps/desktop/src-tauri/capabilities/default.json`
- Create: `apps/desktop/tests/architecture.test.ts`

- [ ] Write a failing dependency-boundary test that rejects `@tauri-apps/*` imports outside `src/gateway` and rejects cross-feature deep imports.
- [ ] Scaffold one Windows-first Tauri 2 app with no localhost server in packaged mode and least-privilege capabilities.
- [ ] Define the complete `ArcavexGateway` port and a deterministic fake gateway used by all component tests.
- [ ] Add lint, format, typecheck, test, and architecture scripts to `package.json`; make each pass on the shell.
- [ ] Commit as `feat(desktop): establish Tauri React application boundaries`.

### Task 8: Build the Rust MCP transport and resilient sidecar supervisor

**Files:**
- Create: `apps/desktop/src-tauri/src/engine/mod.rs`
- Create: `apps/desktop/src-tauri/src/engine/framing.rs`
- Create: `apps/desktop/src-tauri/src/engine/client.rs`
- Create: `apps/desktop/src-tauri/src/engine/supervisor.rs`
- Create: `apps/desktop/src-tauri/src/gateway/mod.rs`
- Create: `apps/desktop/src-tauri/src/events/mod.rs`
- Create: `apps/desktop/src-tauri/tests/fake_mcp.rs`
- Create: `apps/desktop/src-tauri/tests/sidecar_supervisor.rs`
- Create: `apps/desktop/src-tauri/binaries/engine-lock.json`

- [ ] Write Rust tests for JSON-RPC request correlation, notifications, partial/invalid frames, stderr capture, timeout, clean shutdown, crash, bounded exponential restart, and incompatible handshake.
- [ ] Spawn the platform-resolved pinned binary with piped stdio and a process-tree-safe shutdown path; serialize writes and route responses by request ID.
- [ ] Verify artifact SHA-256 and handshake before marking the engine ready. Enter diagnostic mode instead of crashing when incompatible.
- [ ] Expose typed Tauri commands only through gateway state and emit a versioned event envelope for lifecycle/activity changes.
- [ ] Run `cargo fmt --check`, `cargo clippy --all-targets -- -D warnings`, and `cargo test --all-targets`.
- [ ] Commit as `feat(desktop): supervise the pinned MCP engine sidecar`.

### Task 9: Implement watcher, latest-wins render scheduler, settings, and recents

**Files:**
- Create: `apps/desktop/src-tauri/src/projects/mod.rs`
- Create: `apps/desktop/src-tauri/src/projects/watcher.rs`
- Create: `apps/desktop/src-tauri/src/rendering/mod.rs`
- Create: `apps/desktop/src-tauri/src/rendering/scheduler.rs`
- Create: `apps/desktop/src-tauri/src/settings/mod.rs`
- Create: `apps/desktop/src-tauri/src/settings/model.rs`
- Create: `apps/desktop/src-tauri/tests/watcher.rs`
- Create: `apps/desktop/src-tauri/tests/render_scheduler.rs`
- Create: `apps/desktop/src-tauri/tests/settings.rs`

- [ ] Write deterministic-clock tests for write-burst coalescing, own-event deduplication, external actor classification, queued-job replacement, stale active-result rejection, last-good retention, and sidecar restart recovery.
- [ ] Watch only the open canonical project, normalize paths, debounce stable change sets, refresh snapshot revisions, and publish typed project events.
- [ ] Implement one active-target latest-wins queue keyed by render revision/format/locale/options; publish output only when the completion key remains current.
- [ ] Persist recents, app workspace, branding/theme, automation, extension, live-render, updater, and engine override settings atomically under platform app data.
- [ ] Add tests for corrupt settings fallback and approved defaults.
- [ ] Commit as `feat(desktop): add project sync and latest-wins rendering`.

### Task 10: Build the branded extensible workbench shell

**Files:**
- Create: `apps/desktop/src/app/contributions.ts`
- Create: `apps/desktop/src/features/workspace/Workbench.tsx`
- Create: `apps/desktop/src/features/workspace/workbench.css`
- Create: `apps/desktop/src/features/projects/WelcomeScreen.tsx`
- Create: `apps/desktop/src/features/capabilities/CapabilityGate.tsx`
- Create: `apps/desktop/src/theme/types.ts`
- Create: `apps/desktop/src/theme/validate.ts`
- Create: `apps/desktop/src/theme/ThemeProvider.tsx`
- Create: `apps/desktop/src/theme/builtins.ts`
- Create: `apps/desktop/src/theme/tokens.css`
- Create: `apps/desktop/src/features/settings/AppearanceSettings.tsx`
- Create: `apps/desktop/src/features/workspace/Workbench.test.tsx`
- Create: `apps/desktop/src/theme/theme.test.tsx`

- [ ] Write component tests for command/panel/inspector/settings contribution registration, keyboard traversal, compact layouts, and capability-disabled controls.
- [ ] Implement a deliberate dark studio visual system using semantic tokens, a restrained accent, typographic hierarchy, visible focus, and dense but readable panels.
- [ ] Add built-in Dark, Light, and High Contrast manifests plus JSON theme import validation and safe fallback.
- [ ] Add a versioned branding profile controlling product name, mark, accent, and about metadata independently of theme.
- [ ] Verify axe finds no serious violations in welcome, workbench, and settings surfaces.
- [ ] Commit as `feat(desktop): build the branded extensible workbench`.

### Task 11: Complete the Phase 1 project viewer

**Files:**
- Create: `apps/desktop/src/features/projects/projectQueries.ts`
- Create: `apps/desktop/src/features/projects/OpenProject.tsx`
- Create: `apps/desktop/src/features/variants/VariantBar.tsx`
- Create: `apps/desktop/src/features/canvas/CanvasViewport.tsx`
- Create: `apps/desktop/src/features/canvas/selection.ts`
- Create: `apps/desktop/src/features/layers/LayersPanel.tsx`
- Create: `apps/desktop/src/features/layers/layerTree.ts`
- Create: `apps/desktop/src/features/workspace/InspectorPanel.tsx`
- Create: `apps/desktop/src/features/activity/ActivityPanel.tsx`
- Create: `apps/desktop/src/features/diagnostics/DiagnosticsPanel.tsx`
- Create: `apps/desktop/src/features/settings/RuntimeSettings.tsx`
- Create: `apps/desktop/src/features/projects/ProposalsPanel.tsx`
- Create: `apps/desktop/src/features/canvas/CanvasViewport.test.tsx`
- Create: `apps/desktop/src/features/layers/LayersPanel.test.tsx`
- Create: `apps/desktop/src/features/projects/viewer.integration.test.tsx`
- Create: `apps/desktop/e2e/viewer.spec.ts`

- [ ] Write fake-gateway tests for opening/restoring projects, active target changes, current/rendering/stale/failed state, last-good preservation, and external edits.
- [ ] Implement authored/rendered Layers modes with highest-painted siblings first, nested groups, effects/masks subrows, visibility/lock indicators, keyboard navigation, and synchronized selection.
- [ ] Display the rendered bitmap with pan/zoom/fit, engine hit testing, selection bounds, DPR-safe coordinates, and no frontend-owned scene model.
- [ ] Show properties, effects, masks, fonts, extensions, diagnostics, and actor-labelled activity from engine snapshots/events.
- [ ] Keep unrestricted/review/read-only automation, extension mode, and live/manual rendering visibly persistent. Add proposal approve/reject flows.
- [ ] Run Vitest, axe checks, and Playwright against the real dev gateway fixture.
- [ ] Commit as `feat(desktop): complete the live project viewer`.

### Task 12: Automate Windows packaging, updater, and independent releases

**Files:**
- Modify: `.github/workflows/ci.yml`
- Replace: `.github/workflows/release.yml`
- Create: `.github/workflows/release-engine.yml`
- Create: `.github/workflows/release-desktop.yml`
- Create: `.github/release-please-config.json`
- Create: `.release-please-manifest.json`
- Create: `apps/desktop/CHANGELOG.md`
- Create: `apps/desktop/src-tauri/tauri.windows.conf.json`
- Create: `scripts/stage_engine_sidecar.ps1`
- Create: `scripts/verify_desktop_bundle.ps1`
- Create: `tests/e2e/test_engine_sidecar.py`

- [ ] Add CI matrix jobs for Python, TypeScript, Rust, contract drift, packaged sidecar, and Windows desktop smoke tests; cache only dependency/build artifacts keyed by lockfiles.
- [ ] Pin every GitHub Action to an immutable commit SHA and set least-privilege job permissions.
- [ ] Configure manifest Release Please for independent `engine-v*` and `desktop-v*` tags.
- [ ] Build the Windows x64 NSIS installer with the exact lock-manifest sidecar; verify launch, handshake, open fixture, render preview, restart, and standalone executable use.
- [ ] Require Tauri updater signatures. Make Authenticode conditional for self/friends beta, but prevent a production-ready label without it.
- [ ] Generate checksums, SBOM, attestations, updater metadata, and draft releases; publish only after every required gate succeeds.
- [ ] Commit as `ci: automate verified engine and desktop releases`.

### Task 13: Phase 1 full verification checkpoint

**Files:**
- Modify only if a failing verification exposes a defect covered by this phase.

- [ ] Run `uv run ruff check src tests packaging scripts`.
- [ ] Run `uv run mypy src/arcavex/kernel --strict` and `uv run lint-imports`.
- [ ] Run `uv run pytest tests -q`, including contract, property, MCP, golden, packaged-engine, and failure-injection tests.
- [ ] Run `npm ci`, `npm run lint`, `npm run typecheck`, `npm run test:coverage`, `npm run contracts:check`, and `npm run e2e` in `apps/desktop`.
- [ ] Run `cargo fmt --check`, `cargo clippy --all-targets -- -D warnings`, and `cargo test --all-targets` in `apps/desktop/src-tauri`.
- [ ] Build the frozen engine and Tauri NSIS installer from clean output directories; execute `scripts/verify_desktop_bundle.ps1`.
- [ ] Inspect the packaged UI at desktop widths and high contrast, and retain logs/screenshots as CI artifacts.
- [ ] Commit any verification-only corrections, then record exact commands and outcomes in the final handoff.
