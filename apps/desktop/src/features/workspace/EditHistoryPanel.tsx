/**
 * Undo, redo, and the fate of the last edit.
 *
 * Availability is the engine's answer, never a local count: an assistant editing over MCP shares
 * this project's timeline, so a browser-side stack would offer to undo an edit that is no longer
 * the newest. `history.ts` explains that; this panel only renders it.
 *
 * The outcome half exists because a refusal that is not shown is indistinguishable from an edit
 * that quietly did nothing. A conflict names the files that moved, a refusal shows its code and
 * message, and a success says nothing at all — the canvas already said it.
 */

import { useEffect, type ReactNode } from "react";

import type { TransactionReport } from "../../contracts/index.ts";
import { isRedoChord, isUndoChord, redoUnavailableReason, type HistoryState } from "./history.ts";

import "./workbench.css";

export interface EditHistoryPanelProps {
  readonly history: HistoryState;
  /** True while a transaction is in flight; a second one would race the first. */
  readonly busy: boolean;
  readonly lastReport: TransactionReport | null;
  readonly onUndo: () => void;
  readonly onRedo: () => void;
}

/** Typing fields own their own undo; stealing the chord there would lose the user's text. */
function isEditingText(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  return target.tagName === "INPUT" || target.tagName === "TEXTAREA";
}

export function EditHistoryPanel({
  history,
  busy,
  lastReport,
  onUndo,
  onRedo,
}: EditHistoryPanelProps): ReactNode {
  const canUndo = history.canUndo && !busy;
  const canRedo = history.canRedo && !busy;

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent): void {
      if (isEditingText(event.target)) return;
      if (isUndoChord(event) && canUndo) {
        event.preventDefault();
        onUndo();
      } else if (isRedoChord(event) && canRedo) {
        event.preventDefault();
        onRedo();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [canUndo, canRedo, onUndo, onRedo]);

  const redoReason = redoUnavailableReason(history);

  return (
    <div className="edits">
      <div className="edits__controls" role="group" aria-label="Edit history">
        <button type="button" disabled={!canUndo} onClick={onUndo}>
          Undo
        </button>
        <button type="button" disabled={!canRedo} onClick={onRedo}>
          Redo
        </button>
      </div>

      {redoReason === null ? null : <p className="edits__note">{redoReason}</p>}

      <Outcome report={lastReport} />
    </div>
  );
}

function Outcome({ report }: { readonly report: TransactionReport | null }): ReactNode {
  if (report === null || report.ok === true) return null;

  const conflict = report.conflict ?? null;
  const diagnostics = report.diagnostics ?? [];

  return (
    <div className="edits__outcome" role="alert">
      {conflict === null ? null : (
        <>
          <p>
            The project changed underneath this edit, so nothing was written. Reload to see the
            current version, then make the edit again.
          </p>
          <ul>
            {(conflict.changed ?? []).map((changed) => (
              <li key={changed.path}>
                <code>{changed.path}</code> {changed.change}
              </li>
            ))}
          </ul>
        </>
      )}

      {diagnostics.map((diagnostic) => (
        <p key={`${diagnostic.code}-${diagnostic.message}`}>
          <span className="edits__code">{diagnostic.code}</span> {diagnostic.message}
        </p>
      ))}
    </div>
  );
}
