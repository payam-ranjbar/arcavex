# Arcavex Desktop Phase 2 Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Phase 1 viewer into a revision-safe graphic editor with direct text/transform/property editing, layer operations, multi-selection, transactions, and engine-owned undo/redo while preserving external AI/CLI collaboration.

**Architecture:** Add typed semantic transactions to the engine rather than editing YAML from React. The engine locks the canonical project, checks project revisions, validates operations in memory, writes atomically, returns inverse transactions, and branches history on external changes. Tauri forwards commands and events; React renders command state and optimistic interaction previews but never owns the authoritative document.

**Tech Stack:** Existing Python/Pydantic/FastMCP engine, ruamel.yaml round-trip authoring, cross-process file locks, Tauri/Rust command gateway, React/TypeScript pointer interactions, Vitest/Playwright, pytest/Hypothesis.

## Global Constraints

- Every mutation carries project path, target, base project revision, actor, command ID, and a typed payload.
- Never silently last-write-wins. Reject stale or overlapping changes with paths, files, and layer IDs.
- Validate structure and references before atomic replacement. A failed command writes nothing.
- Undo/redo uses engine-returned inverse transactions; external edits create a new history branch.
- Stable IDs and authored hierarchy remain authoritative. The UI cannot emulate reorder/reparent with text edits.
- Respect lock state and automation policy at the engine boundary. Review mode queues before mutation.
- Preserve unrestricted automation, unrestricted trusted extensions, and live rendering as defaults.
- Follow red-green-refactor and keep Phase 1 behavior green after every task.

---

### Task 1: Define semantic command, transaction, conflict, and history contracts

**Files:**
- Modify: `src/arcavex/kernel/api.py`
- Create: `src/arcavex/kernel/editor.py`
- Create: `tests/unit/test_editor_contracts.py`
- Create: `tests/property/test_editor_contract_roundtrip.py`
- Modify: `scripts/export_desktop_schemas.py`
- Create: `schemas/desktop/editor-transaction.schema.json`
- Regenerate: `apps/desktop/src/contracts/generated.ts`

- [ ] Write serialization tests covering set-text, set-property, set-visibility, translate, resize, rotate, reorder, reparent, duplicate, delete, group, set-display-name, and set-effects payloads.
- [ ] Define discriminated Pydantic command models, `Actor`, `EditorTarget`, `SemanticTransaction`, `ChangedPath`, `ConflictDetail`, `TransactionReport`, and `HistoryReport`.
- [ ] Require UUID command IDs, canonical project paths, base revisions, and finite numeric geometry; reject unknown payload keys.
- [ ] Include new project/render revisions, changed files/layers, diagnostics, and inverse transaction in successful reports.
- [ ] Export schemas and regenerate TypeScript discriminated unions; prove Python-to-TypeScript fixture compatibility.
- [ ] Commit as `feat(editor): define semantic transaction contracts`.

### Task 2: Add cross-process mutation locking and atomic transaction infrastructure

**Files:**
- Create: `src/arcavex/services/editor/__init__.py`
- Create: `src/arcavex/services/editor/locking.py`
- Create: `src/arcavex/services/editor/transaction.py`
- Create: `src/arcavex/services/editor/history.py`
- Modify: `src/arcavex/services/fsutil.py`
- Create: `tests/unit/editor/test_locking.py`
- Create: `tests/unit/editor/test_transaction_atomicity.py`
- Create: `tests/unit/editor/test_history.py`
- Create: `tests/e2e/test_editor_races.py`

- [ ] Write multiprocessing tests proving only one writer holds `.arcavex/project.lock`, timeouts produce diagnostics, and abandoned locks recover safely.
- [ ] Stage all transaction writes in project-local temporary files, validate the complete staged state, then atomically replace each target with rollback backups until commit succeeds.
- [ ] Compare the submitted base revision to a fresh snapshot under lock and return structured changed-file conflicts without writes.
- [ ] Store bounded, versioned history records under `.arcavex/history/` with forward/inverse transactions and before/after revisions.
- [ ] Detect an external revision between history entries and branch/clear redo instead of replaying across it.
- [ ] Commit as `feat(editor): add atomic locked transaction infrastructure`.

### Task 3: Implement source mapping and safe authored-tree primitives

**Files:**
- Create: `src/arcavex/services/editor/source_map.py`
- Create: `src/arcavex/services/editor/tree.py`
- Modify: `src/arcavex/services/template/overlays.py`
- Modify: `src/arcavex/services/authoring.py`
- Create: `tests/unit/editor/test_source_map.py`
- Create: `tests/unit/editor/test_tree_operations.py`
- Create: `tests/property/test_editor_tree.py`

- [ ] Write round-trip YAML tests that preserve comments, anchors, quoting, and unrelated formatting while locating every stable authored node.
- [ ] Implement parent/index lookup through direct, conditional, and repeated child wrappers without flattening authored constructs.
- [ ] Add primitives for insert, delete, duplicate-with-new-stable-IDs, reorder, reparent, and group.
- [ ] Reject root deletion/reparent, cycles, duplicate IDs, invalid target parents, locked nodes, and sibling-anchor dependencies that would become invalid.
- [ ] Property-test that successful operations preserve unique IDs and an acyclic connected tree, and that rejected operations leave bytes identical.
- [ ] Commit as `feat(editor): add source-mapped authored tree operations`.

### Task 4: Fix transform translation and implement scale/resize semantics

**Files:**
- Modify: `src/arcavex/kernel/ir/models.py`
- Modify: `src/arcavex/services/template/compiler.py`
- Modify: `src/arcavex/builtin/layout_anchors/solver.py`
- Modify: `src/arcavex/builtin/backend_skia/backend.py`
- Create: `tests/unit/editor/test_transforms.py`
- Modify: `tests/unit/test_layout_phase2.py`
- Add/update: `tests/golden/goldens/win-x86_64/editor-transforms.png`

- [ ] Add failing geometry and render tests proving authored translation changes layout/paint bounds, backend output, hit testing, and selection bounds consistently.
- [ ] Extend affine transform representation with finite `scale_x`/`scale_y`; define pivot behavior and reject zero/negative scale where node semantics cannot support it.
- [ ] Compose anchor placement, translation, scale, and rotation in one documented order shared by solver and backend.
- [ ] Implement resize commands as constraint/property changes where possible and transform scale otherwise; return the exact inverse.
- [ ] Add property tests for transform/inverse round trips and a Windows golden.
- [ ] Commit as `fix(engine): make translation and scale render consistently`.

### Task 5: Implement semantic mutation execution and MCP parity

**Files:**
- Create: `src/arcavex/services/editor/service.py`
- Modify: `src/arcavex/services/orchestrator.py`
- Modify: `src/arcavex/bootstrap.py`
- Modify: `src/arcavex/kernel/api.py`
- Modify: `src/arcavex/clients/mcp_server.py`
- Modify: `src/arcavex/clients/cli.py`
- Create: `tests/unit/editor/test_service.py`
- Create: `tests/mcp_sessions/test_editor_session.py`
- Create: `tests/e2e/test_editor_cli.py`

- [ ] Write one red test per command kind and assert expected changed paths, files, layer IDs, revisions, and inverse payload.
- [ ] Dispatch typed commands to tree/data/UI-metadata primitives. Compile every render-affecting staged change for the active target before commit.
- [ ] Enforce read-only/review/unrestricted policy: reject, queue, or execute respectively; approval re-enters the same executor under a fresh revision check.
- [ ] Expose `editor_apply`, `editor_undo`, `editor_redo`, and `editor_history` identically through Facade, MCP, and JSON CLI.
- [ ] Add race, stale proposal, locked layer, malformed template, and extension-crash failure tests.
- [ ] Commit as `feat(engine): execute revision-safe semantic edits`.

### Task 6: Add the desktop command bus, history, and conflict presentation

**Files:**
- Modify: `apps/desktop/src/gateway/ArcavexGateway.ts`
- Modify: `apps/desktop/src/gateway/TauriArcavexGateway.ts`
- Modify: `apps/desktop/src-tauri/src/gateway/mod.rs`
- Create: `apps/desktop/src/features/workspace/commands.ts`
- Create: `apps/desktop/src/features/workspace/history.ts`
- Create: `apps/desktop/src/features/diagnostics/ConflictDialog.tsx`
- Create: `apps/desktop/src/features/workspace/commands.test.ts`
- Create: `apps/desktop/src/features/diagnostics/ConflictDialog.test.tsx`

- [ ] Write tests for command IDs/actors/base revision capture, busy state, retry-safe transport errors, policy outcomes, undo/redo availability, and structured conflicts.
- [ ] Route all editing through one command bus that invalidates queries only from authoritative transaction reports and watcher events.
- [ ] Add keyboard-safe undo/redo with engine history state; never mutate cached snapshots directly.
- [ ] Present conflicting files/layers/paths and explicit reload/reapply choices without hiding external changes.
- [ ] Commit as `feat(desktop): add semantic command and history bus`.

### Task 7: Add inspector editing for text, properties, visibility, and effects

**Files:**
- Create: `apps/desktop/src/features/inspector/InspectorRegistry.ts`
- Create: `apps/desktop/src/features/inspector/TextInspector.tsx`
- Create: `apps/desktop/src/features/inspector/TransformInspector.tsx`
- Create: `apps/desktop/src/features/inspector/AppearanceInspector.tsx`
- Create: `apps/desktop/src/features/inspector/EffectsInspector.tsx`
- Modify: `apps/desktop/src/features/workspace/InspectorPanel.tsx`
- Create: `apps/desktop/src/features/inspector/inspectors.test.tsx`

- [ ] Write tests for mixed multi-selection values, validation, keyboard commit/cancel, locked/read-only states, and focus retention after rerender.
- [ ] Register inspectors by capability and node kind; render unsupported properties read-only with a reason.
- [ ] Implement text, numeric/property, visibility, translation, size, rotation, display-name, and typed effect-list editors.
- [ ] Coalesce continuous field changes into one semantic transaction on commit while preserving live local feedback.
- [ ] Commit as `feat(desktop): add semantic property inspectors`.

### Task 8: Implement direct canvas manipulation and multi-selection

**Files:**
- Modify: `apps/desktop/src/features/canvas/CanvasViewport.tsx`
- Create: `apps/desktop/src/features/canvas/SelectionOverlay.tsx`
- Create: `apps/desktop/src/features/canvas/interactionMachine.ts`
- Create: `apps/desktop/src/features/canvas/coordinates.ts`
- Create: `apps/desktop/src/features/canvas/snapping.ts`
- Create: `apps/desktop/src/features/canvas/interactionMachine.test.ts`
- Create: `apps/desktop/e2e/editor-canvas.spec.ts`

- [ ] Write pointer-state tests for click, shift selection, marquee, move, eight resize handles, rotate handle, escape cancellation, pointer capture loss, and zoom/DPR coordinate conversion.
- [ ] Keep drag geometry ephemeral in React; submit one typed transaction on pointer release and snap back to authoritative bounds on rejection.
- [ ] Support multi-selection bounding boxes and same-delta translation, honoring lock/editability state.
- [ ] Add optional guide/edge/center snapping with Alt bypass and visible accessible status announcements.
- [ ] Commit as `feat(desktop): add direct canvas manipulation`.

### Task 9: Implement Layers panel editing operations

**Files:**
- Modify: `apps/desktop/src/features/layers/LayersPanel.tsx`
- Create: `apps/desktop/src/features/layers/LayerRow.tsx`
- Create: `apps/desktop/src/features/layers/dropTarget.ts`
- Create: `apps/desktop/src/features/layers/LayerActions.tsx`
- Modify: `apps/desktop/src/features/layers/LayersPanel.test.tsx`
- Create: `apps/desktop/e2e/editor-layers.spec.ts`

- [ ] Write keyboard and pointer tests for visibility, rename, reorder, reparent, group, ungroup, duplicate, delete, multi-select, and invalid drop targets.
- [ ] Translate top-to-bottom visual paint ordering into explicit engine reorder positions; never infer YAML indices in the component.
- [ ] Keep definition/rendered modes; disable structural edits in rendered mode when an instance cannot map safely to one authored definition.
- [ ] Announce structural changes and validation failures accessibly, restore focus, and preserve expansion state by stable ID.
- [ ] Commit as `feat(desktop): add editable layer hierarchy`.

### Task 10: Complete Phase 2 integration, failure injection, and release gates

**Files:**
- Create: `apps/desktop/e2e/editor-workflow.spec.ts`
- Create: `tests/e2e/test_editor_external_collaboration.py`
- Modify: `.github/workflows/ci.yml`
- Modify: `.github/workflows/release-desktop.yml`
- Modify: `README.md`
- Create: `docs/desktop/editor.md`

- [ ] Test a complete packaged workflow: open fixture, select by canvas, edit text, move/resize/rotate, reorder/reparent/group/duplicate/delete, undo/redo, external CLI edit, conflict, reload, and final render.
- [ ] Inject sidecar death during a command, malformed source, concurrent AI/UI mutations, stale render completion, locked node, extension crash, and updater failure; assert no source corruption and last-good preview retention.
- [ ] Add Python, Rust, TypeScript, Playwright, schema-drift, golden, packaged-sidecar, and packaged-desktop editor checks as required CI/release gates.
- [ ] Run all Python quality checks and tests, all frontend lint/type/coverage/e2e checks, all Rust format/clippy/tests, frozen-engine build, and Windows NSIS verification from clean outputs.
- [ ] Inspect final light/dark/high-contrast UI, keyboard-only editing, and 100%/150%/200% Windows scaling.
- [ ] Commit as `feat(desktop): complete Phase 2 graphic editing`.
