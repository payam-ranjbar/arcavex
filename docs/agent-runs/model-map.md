# Agent / model mapping for this build

The task's preferred assignments and what actually ran in this environment.

The task's preferred assignments and what actually ran. **Mapping changed mid-build** (during
Phase 3) at the user's direction — see the two tables.

### Phases -1 through 3 (implementation + review + remediation + re-review)

| Responsibility | Preferred | Actual model used | Notes |
|---|---|---|---|
| Orchestration | — | Fable 5 (`claude-fable-5`, main session) | Reads spec, writes briefs, verifies, runs acceptance commands |
| Main implementation | Opus | Opus (`model: "opus"` subagents) | |
| Code review | Fable 5 | Fable 5 (`model: "fable"` subagents) | |
| Design / DX review | Fable 5 | Fable 5 (`model: "fable"` subagents) | |
| Remediation | Opus | Opus (`model: "opus"` subagents) | |
| Fresh re-review | Fable 5 | Fable 5 (`model: "fable"` subagents) | |

### From Phase 3 code-review onward (user directive, 2026-07-13)

The user set the session model to Opus 4.8 and directed: all subagents on Opus, DX/design
reviews on Sonnet, and skip the dedicated fresh re-review stage for a faster prototype (the
orchestrator performs verification of each remediation directly before committing).

| Responsibility | Model used | Notes |
|---|---|---|
| Orchestration | Opus 4.8 (main session) | |
| Main implementation | Opus (`model: "opus"`) | |
| Code review | Opus (`model: "opus"`) | changed from Fable 5 |
| Design / DX review | Sonnet (`model: "sonnet"`) | changed from Fable 5 |
| Remediation | Opus (`model: "opus"`) | |
| Fresh re-review | (skipped) | orchestrator verifies remediation directly |

Every phase's actual runs are recorded in `docs/agent-runs/phase-XX-*.md`. Deviations are
noted in that phase's report; none is claimed silently. The Phase 3 code review was initially
launched on Fable 5, stopped before producing output, and relaunched on Opus per the directive.
