# Agent / model mapping for this build

The task's preferred assignments and what actually ran in this environment.

| Responsibility | Preferred | Actual model used | Notes |
|---|---|---|---|
| Orchestration | — | Fable 5 (`claude-fable-5`, main session) | Reads spec, writes briefs, verifies, runs acceptance commands |
| Main implementation | Opus | Opus (`model: "opus"` subagents) | |
| Code review | Fable 5 | Fable 5 (`model: "fable"` subagents) | |
| Design / DX review | Fable 5 | Fable 5 (`model: "fable"` subagents) | |
| Remediation | Opus | Opus (`model: "opus"` subagents) | |
| Fresh re-review | Fable 5 | Fable 5 (`model: "fable"` subagents) | |

Every phase's actual runs are recorded in `docs/agent-runs/phase-XX-*.md`. If any run
deviates from this mapping (for example a model was unavailable), the deviation is noted
in that phase's report; none is claimed silently.
