# Task 4 Report: Project UI Metadata, Policy, and Proposal Queue Contracts

## Status

Implemented and verified on `codex/desktop-phase2` from reviewed Task 3 commit `2867014`.

## Implementation

### Project UI metadata

- Added frozen `LayerUIMetadata`, `ProjectWorkspaceState`, `ProjectUIMetadata`, and
  `ProjectUIMetadataReport` kernel contracts.
- `project.ui.yaml` is optional and versioned at `1`. A missing file returns in-memory defaults
  without writing or creating the sidecar.
- Layer metadata is keyed by non-empty stable authored IDs and supports an optional display name,
  a `false` lock default, and validated six-digit `#RRGGBB` colors.
- The project-local workspace mapping has an explicit field vocabulary: active format/locale,
  definition/rendered layer-tree mode, and selected authored layer IDs. Unknown app-global keys
  are rejected.
- Writes use the existing project-local atomic YAML path and omit optional/default noise while
  preserving all meaningful values on reload.
- `project.ui.yaml` remains in the project manifest and never enters the render manifest, so UI
  changes alter `project_revision` only.

### Automation and extension policy

- Added exact `AutomationMode` values `unrestricted`, `review`, and `read_only`, plus exact
  `ExtensionMode` values `unrestricted` and `disabled`.
- Added frozen, versioned `AutomationPolicy` with unrestricted defaults and
  `ProjectPolicyReport`.
- Extended `ProjectModel` backward-compatibly with a default policy. Old manifests read without
  writes and preserve the previous effective behavior.
- `project.yaml` omits the complete `automation` mapping at defaults. When one axis differs, the
  mapping persists `version: 1` and only non-default axes.
- `ProjectPolicyService` performs atomic manifest updates and returns freshly snapped project and
  render revisions. Policy changes affect only `project_revision`.

### Proposal queue

- Added frozen `ProposalActor`, `ProjectProposal`, `ProposalListReport`, and
  `ProposalActionReport` contracts.
- Proposal records contain version, canonical lowercase UUIDv4 command ID, canonical absolute
  project path, SHA-256 base project revision, actor identity, opaque JSON command payload,
  timezone-aware creation timestamp, and explicit `pending`/`authorized`/`rejected` state.
- Records are atomically serialized with deterministic JSON under
  `.arcavex/pending/<command-id>.json`; command IDs cannot choose or traverse filenames.
- Listing is deterministic by canonical command ID. A malformed JSON/contract/path/filename entry
  produces `ARC-PRJ-010` while other valid entries remain available.
- Approval reloads the proposal, re-snapshots the project under the operation, and authorizes only
  an exact base-revision match. A stale proposal returns `ARC-PRJ-011` and leaves both source and
  queue bytes unchanged.
- Approval only transitions the record to `authorized` and returns that proposal. The report has
  no `applied` claim and no YAML command execution exists in this task. This gives the Phase 2
  executor an explicit authorized state to execute and finalize later.
- Rejection persists a recoverable record with a reason, is idempotent for retries, and does not
  delete queue data.
- Pending, authorization, rejection, and malformed-queue writes stay under `.arcavex`, which the
  Task 3 snapshot service excludes from both revisions.

### Facade, MCP, capabilities, and diagnostics

- Added metadata get/set, policy get/set, and proposal list/approve/reject operations through the
  orchestrator protocol, concrete orchestrator, and exception-safe Facade.
- Added seven thin MCP wrappers using the exact shared frozen report models and verified their
  generated output schemas and live FastMCP dispatch.
- Added desktop capabilities `project.ui-metadata`, `project.policy`, and `project.proposals`.
- Added and generated catalog documentation for:
  - `ARC-PRJ-008` invalid project UI metadata
  - `ARC-PRJ-009` invalid proposal command ID
  - `ARC-PRJ-010` malformed proposal queue entry
  - `ARC-PRJ-011` stale proposal base revision
  - `ARC-PRJ-012` proposal unavailable for the requested state transition
  - `ARC-PRJ-013` invalid proposal record/content

## TDD Evidence

### Baseline

- Command:
  `uv run pytest tests/unit/test_project_snapshot.py tests/property/test_project_revisions.py tests/unit/test_projects.py tests/mcp_sessions/test_desktop_contracts.py -q -rs`
- Result: exit `0`; 46 focused tests passed, with the known Windows file-symlink skip and the
  pre-existing FastMCP/Pydantic warning.

### RED/GREEN cycles

1. UI metadata contracts and I/O
   - RED: `uv run pytest tests/unit/test_project_ui_metadata.py -q`
   - Exact failure: collection stopped with `ImportError: cannot import name 'LayerUIMetadata'`.
   - GREEN: the same command passed 8 tests after adding frozen models and atomic project service
     I/O.
   - Hardening RED: an empty layer key did not raise validation; the paired policy-default test
     also failed.
   - Hardening GREEN: `uv run pytest tests/unit/test_project_policy.py
     tests/unit/test_project_ui_metadata.py -q` passed 14 tests.

2. Project policy
   - RED: `uv run pytest tests/unit/test_project_policy.py -q`
   - Exact failure: collection stopped with
     `ImportError: cannot import name 'AutomationPolicy'`.
   - GREEN: the same command passed 4 initial tests after adding modes, optional manifest
     persistence, and the policy service.
   - Serializer RED: a review-only policy unexpectedly wrote
     `extensions: unrestricted`.
   - Serializer GREEN: the unrestricted axis is now omitted while `version: 1` and `mode: review`
     persist.

3. Proposal queue
   - RED: `uv run pytest tests/unit/test_proposals.py -q`
   - Exact failure: collection stopped with `ImportError: cannot import name 'ProjectProposal'`.
   - GREEN: the same command passed 9 initial queue/revision/state tests.
   - Review RED:
     `uv run pytest tests/unit/test_proposals.py -q -k "invalid_proposal_content or cannot_be_stored"`
     failed twice: an invalid revision was misclassified as `ARC-PRJ-009`, and a non-JSON object
     escaped as `PydanticSerializationError`.
   - Review GREEN: proposal plus diagnostics suites passed 23 tests after adding
     `ARC-PRJ-013` and pre-write JSON validation.

4. Facade and MCP parity
   - RED: `uv run pytest tests/mcp_sessions/test_desktop_contracts.py -q`
   - Exact failure: collection stopped with
     `ImportError: cannot import name 'ProjectUIMetadataReport'`.
   - GREEN: the same command passed 10 tests after protocol/Facade/orchestrator/MCP wiring,
     shared output-schema assertions, and live dispatch tests.

5. Diagnostic catalog
   - RED:
     `uv run pytest tests/unit/test_explain.py::test_every_emitted_code_is_documented -q`
   - Exact failure: undocumented codes `ARC-PRJ-008` through `ARC-PRJ-012`.
   - GREEN: emitted-code coverage, generated-page parity, and index-count tests passed after
     catalog registration and page generation. `ARC-PRJ-013` was added during the review fix and
     the complete diagnostics suite passed afterward.

6. MCP catalog regression
   - The covering regression run passed every behavior except
     `test_catalog_lists_every_declared_tool`, which still expected 27 tools and observed 34.
   - After updating the explicit parity count for the seven Task 4 tools, the covering suite
     reached 100%.

7. Static RED/GREEN
   - Initial Ruff reported three import-order issues, two `datetime.UTC` modernizations, and one
     line-length issue.
   - Safe formatting plus one wrapped assertion produced final `All checks passed!` output.

## Final Verification

- Focused UI/policy/proposal/snapshot/MCP and relevant project regressions:
  - Command: `uv run pytest tests/unit/test_project_ui_metadata.py
    tests/unit/test_project_policy.py tests/unit/test_proposals.py
    tests/unit/test_project_snapshot.py tests/property/test_project_revisions.py
    tests/unit/test_projects.py tests/e2e/test_cli_projects.py tests/e2e/test_preview.py
    tests/e2e/test_phase04_remediation.py tests/e2e/test_provenance.py tests/mcp_sessions -q -rs`
  - Result: exit `0`; reached `[100%]`; one expected Windows project-snapshot symlink skip and the
    pre-existing FastMCP/Pydantic warning.
- Ruff:
  - `uv run ruff check src tests scripts`
  - `All checks passed!`
- Strict kernel mypy:
  - `uv run mypy src/arcavex/kernel --strict`
  - `Success: no issues found in 13 source files`.
- Import contracts:
  - `uv run lint-imports`
  - `Contracts: 5 kept, 0 broken` across 98 analyzed files and 307 dependencies.
- Diagnostics:
  - `uv run pytest tests/unit/test_explain.py -q`
  - 12 tests passed.
- Diff hygiene:
  - `git diff --check`
  - exit `0` with no output.
- Full non-golden suite on the final post-review tree:
  - `uv run pytest tests -q --ignore=tests/golden -rs`
  - exit `0`; 758 collected, 756 passed, 2 expected platform symlink skips, one pre-existing
    FastMCP/Pydantic warning; wall time 113.1 seconds.

## Files

### Production

- `src/arcavex/kernel/api.py`
- `src/arcavex/services/projects.py`
- `src/arcavex/services/project_policy.py`
- `src/arcavex/services/proposals.py`
- `src/arcavex/services/orchestrator.py`
- `src/arcavex/services/desktop.py`
- `src/arcavex/clients/mcp_server.py`

### Tests

- `tests/unit/test_project_ui_metadata.py`
- `tests/unit/test_project_policy.py`
- `tests/unit/test_proposals.py`
- `tests/mcp_sessions/test_desktop_contracts.py`
- `tests/mcp_sessions/test_schema_parity.py`

### Diagnostics and report

- `src/arcavex/services/diagnostics_catalog.py`
- `docs/diagnostics.md`
- `docs/diagnostics/ARC-PRJ-008.md`
- `docs/diagnostics/ARC-PRJ-009.md`
- `docs/diagnostics/ARC-PRJ-010.md`
- `docs/diagnostics/ARC-PRJ-011.md`
- `docs/diagnostics/ARC-PRJ-012.md`
- `docs/diagnostics/ARC-PRJ-013.md`
- `.superpowers/sdd/2026-08-08-arcavex-desktop-foundation-phase1/task-4-report.md`

## Self-review

- Re-read the Task 4 brief and every binding decision against the final diff.
- Confirmed missing UI metadata and default policy reads are non-writing and backward-compatible.
- Confirmed metadata/policy bytes change only `project_revision`, and all proposal queue writes
  change neither revision.
- Confirmed the review-mode pending test compares all non-queue source bytes before/after enqueue.
- Confirmed stale approval compares both source bytes and queue bytes and leaves both identical.
- Confirmed no approval response contains or implies `applied`; authorized state is explicit.
- Confirmed all writes use atomic same-directory replacement and deterministic serialization.
- Confirmed malformed queue entries cannot suppress valid entries and all emitted diagnostics are
  catalogued/generated.
- Confirmed clients import only `kernel.api` plus bootstrap and the kernel imports no services.
- Confirmed no `.superpowers/runtime` output is present in the worktree status.
- The code-review skill calls for a reviewer subagent, but no multi-agent tools are available in
  this session. Review therefore used the complete diff, mutation-oriented test additions, the
  binding-decision checklist, and all requested gates.

## Concerns

- No unresolved Task 4 implementation concern.
- The full/focused suites retain the pre-existing FastMCP/Pydantic
  `IncompleteFieldDefinitionWarning`.
- This Windows process cannot create the two tested symlinks, so those narrowly scoped tests skip
  with explicit platform reasons.
- Proposal authorization deliberately does not execute commands. Phase 2 must recheck the project
  revision under its mutation lock, execute the authorized payload, and then finalize/archive the
  record.
