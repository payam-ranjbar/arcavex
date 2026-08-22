# Editing in Arcavex Desktop

Arcavex Desktop edits the project's **source files**, not a document model held in the window.
Every gesture — typing in the inspector, dragging on the canvas, reordering a layer — becomes a
semantic transaction the engine applies to `template.yaml` and `project.ui.yaml`, preserving
comments, key order, and formatting. Close the window and the diff is one a person would have
written by hand.

That choice is what makes the rest of this document necessary. The files are shared: a CLI, an
MCP client driving an assistant, and this window are separate processes over one project, and the
editor's job is to make their collisions boring.

## One gesture, one transaction

A gesture submits exactly one transaction, carrying:

- the **commands** it means (`set_text`, `translate`, `reorder`, `group`, …),
- the **project revision the window was showing**, and
- the **actor** that made it.

Dragging three selected layers is one transaction, so it is one undo step. The revision is read at
submit time from the authoritative snapshot — never remembered from an earlier render — so an edit
composed against a document state someone has since changed is refused rather than applied over
their work.

Nothing is optimistically applied in the window. The engine writes, then reports; the canvas,
layer tree, and inspector refresh from that report. A UI that trusted its own optimistic copy
would drift from the engine the first time an edit was refused.

## When an edit is refused

Refusals are values, not errors: they land in the **Edits** panel with their code and message.

| Code | What happened |
|---|---|
| [`ARC-EDT-001`](../diagnostics/ARC-EDT-001.md) | Another process holds the project's mutation lock. Nothing was changed. |
| [`ARC-EDT-002`](../diagnostics/ARC-EDT-002.md) | A write failed partway and every file was rolled back from its backup. |
| [`ARC-EDT-004`](../diagnostics/ARC-EDT-004.md) | The command names a layer, parent, or field that does not exist or cannot take it. |
| [`ARC-EDT-005`](../diagnostics/ARC-EDT-005.md) | The edit would delete the root or reparent a node into its own descendant. |
| [`ARC-EDT-006`](../diagnostics/ARC-EDT-006.md) | The layer is locked. |
| [`ARC-EDT-007`](../diagnostics/ARC-EDT-007.md) | Deleting it would orphan sibling constraints that anchor to it; the dependents are named. |
| [`ARC-EDT-008`](../diagnostics/ARC-EDT-008.md) | The project pins a shared library template, which editing in place would change for every project pinning it. |
| [`ARC-EDT-009`](../diagnostics/ARC-EDT-009.md) | The project's automation mode is read-only. |
| [`ARC-EDT-010`](../diagnostics/ARC-EDT-010.md) | The transaction itself is malformed. |
| [`ARC-EDT-011`](../diagnostics/ARC-EDT-011.md) | There is nothing to undo or redo in that direction. |

A refused transaction writes nothing. That is the guarantee the staged writer exists for: files
are replaced atomically after the edited project compiles, and any failure restores every file it
had already replaced. An edit that would not render is refused before anything reaches disk.

### Conflicts name files

When the project moved between composing an edit and applying it, the report carries a **conflict**
rather than a diagnostic, and the conflict names the files that changed:

> The project changed underneath this edit, so nothing was written.
> `data/event.yaml` modified

"Someone changed the project" is not something a person can resolve; *that file changed* is.
Reload, redo the edit, and it applies — the conflict is a rebase, not a dead end.

## What cannot be edited, and why it says so

Some things are refused by design, and the UI states the reason instead of hiding the control:

- **A rendered instance of a `repeat` or `if` construct.** One visible instance has no single
  authored definition, so editing it would change every instance without saying so. Switch the
  Layers panel to **Definition** to edit the authored layer; the inspector follows that switch.
- **A locked layer.** The lock lives in the project's UI metadata and covers the whole subtree.
- **A pinned library template.** Clone it into the project (`arcavex project clone`) first.
- **A read-only project.** The automation mode refuses semantic mutations at the engine boundary
  for every client — desktop, MCP, and CLI alike — so a read-only project is read-only everywhere.

In **review** mode, an edit is not applied but queued as a proposal for a person to approve in the
Proposals panel.

## Undo and redo belong to the project

Undo is not a stack in the window. The engine keeps a history on disk beside the project, and
`can_undo`/`can_redo` are answers about the project's **current revision**:

- Undo reverses the most recent transaction **whoever made it** — this window, a CLI, or an
  assistant over MCP. A per-process stack would let each one undo into a state the other had
  already moved past.
- Undo and redo restore **recorded bytes**, not inverse commands, so what comes back is exactly
  what was there. A semantic inverse cannot promise that.
- An edit made outside Arcavex — a file typed into a text editor — moves the project to a revision
  the history never saw, which **closes the line** rather than replaying over that work. The panel
  says so ("an edit from outside this window ended the redo line") instead of silently greying the
  button.

Keyboard: `Ctrl+Z` undoes, `Ctrl+Y` or `Ctrl+Shift+Z` redoes. The chords are ignored while a text
field has focus, because a field's undo belongs to the field.

## Working alongside a CLI or an assistant

Every writer — this window included — takes a cross-process file lock for the whole
read-modify-write cycle, so two writers never interleave. The loser waits; if the wait runs out it
is told (`ARC-EDT-001`) rather than proceeding. A writer that dies holding the lock does not lock
the project forever: the lock is presumed abandoned after a threshold far longer than any real
edit.

The activity stream reports edits this window did not make, so an assistant working in the same
project is visible rather than mysterious.

## How these guarantees are tested

These are not aspirations; each is a gate:

- `tests/e2e/test_editor_external_collaboration.py` — two real processes over one project: stale
  edits conflict and name the file, a rebase succeeds, undo stops at an edit it never saw, a held
  lock makes the second writer wait, and a refusal or a killed writer leaves every byte in place.
- `tests/e2e/test_editor_races.py` — concurrent writers never lose an update.
- `tests/e2e/test_editor_cli.py` — the same editor surface over the JSON CLI.
- `apps/desktop/e2e/editor-workflow.spec.ts` — one gesture, one transaction, carrying the revision
  the window was showing.
- `scripts/verify_desktop_bundle.ps1` — the **installed** application applies a real edit and undoes
  it back to the original bytes, headlessly, against the engine the installer shipped.

See also: [Diagnostics](../diagnostics.md) · [Architecture](../architecture.md) ·
[Testing](../testing.md)
