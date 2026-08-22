/**
 * Undo/redo availability, read from the engine rather than counted in the browser.
 *
 * The temptation is to keep a local stack: the workbench knows what it just did, after all. It
 * would be wrong. An AI client editing over MCP shares this project's timeline, so a local stack
 * would offer to undo an edit that is no longer the newest, or refuse an undo that is perfectly
 * valid. `can_undo` and `can_redo` come from the engine's history for the project's *current*
 * revision, and `branched_by_external_edit` is why redo can vanish without the user doing
 * anything — which is worth saying out loud in the UI rather than silently disabling a button.
 */

import type { HistoryReport } from "../../contracts/index.ts";

export interface HistoryState {
  readonly canUndo: boolean;
  readonly canRedo: boolean;
  /** True when someone else's edit ended the redo line; the UI explains rather than just greys. */
  readonly branchedByExternalEdit: boolean;
  readonly entries: NonNullable<HistoryReport["entries"]>;
}

export const EMPTY_HISTORY: HistoryState = {
  canUndo: false,
  canRedo: false,
  branchedByExternalEdit: false,
  entries: [],
};

/** Project an engine history report into the state the workbench renders. */
export function historyState(report: HistoryReport | null): HistoryState {
  if (report === null || report.ok !== true) return EMPTY_HISTORY;
  return {
    canUndo: report.can_undo === true,
    canRedo: report.can_redo === true,
    branchedByExternalEdit: report.branched_by_external_edit === true,
    entries: report.entries ?? [],
  };
}

/** Why redo is unavailable, or null when it is available or simply unused. */
export function redoUnavailableReason(state: HistoryState): string | null {
  if (state.canRedo) return null;
  if (state.branchedByExternalEdit) {
    return "An edit from outside this window ended the redo line.";
  }
  return null;
}

/** The keyboard chords the workbench binds, named once so the UI and its tests agree. */
export function isUndoChord(event: KeyboardEvent): boolean {
  return modifier(event) && !event.shiftKey && event.key.toLowerCase() === "z";
}

export function isRedoChord(event: KeyboardEvent): boolean {
  if (!modifier(event)) return false;
  const key = event.key.toLowerCase();
  // Both spellings: Ctrl+Y is the Windows convention, Ctrl+Shift+Z the cross-platform one.
  return key === "y" || (event.shiftKey && key === "z");
}

function modifier(event: KeyboardEvent): boolean {
  return event.ctrlKey || event.metaKey;
}
