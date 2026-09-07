/**
 * The structural operations a layers panel offers: visibility, group, duplicate, delete.
 *
 * Rendered as real buttons rather than a context menu, so every operation is reachable by
 * keyboard and announced by a screen reader. Each is disabled with a stated reason rather than
 * hidden — a missing button is indistinguishable from a broken one.
 */

import type { ReactNode } from "react";

import type { EditorCommand } from "../workspace/index.ts";
import type { LayerRow } from "./layerTree.ts";

export interface LayerActionsProps {
  readonly selection: ReadonlyArray<LayerRow>;
  /** Every row on screen, topmost first, so a move can find the selection's neighbours. */
  readonly rows?: ReadonlyArray<LayerRow>;
  readonly disabled: boolean;
  readonly disabledReason: string | null;
  readonly onSubmit: (commands: ReadonlyArray<EditorCommand>) => void;
}

/** The authored id of a row's parent, read off the flattened tree by depth. */
function parentOf(rows: ReadonlyArray<LayerRow>, row: LayerRow): string | null {
  const at = rows.indexOf(row);
  for (let index = at - 1; index >= 0; index -= 1) {
    const candidate = rows[index];
    if (candidate && candidate.depth === row.depth - 1) return candidate.authoredId;
  }
  return null;
}

/** A fresh group id derived from the selection, so the name is predictable rather than random. */
export function groupIdFor(selection: ReadonlyArray<LayerRow>): string {
  const first = selection[0];
  return first ? `${first.authoredId}-group` : "group";
}

export function LayerActions({
  selection,
  rows = [],
  disabled,
  disabledReason,
  onSubmit,
}: LayerActionsProps): ReactNode {
  const ids = selection.map((row) => row.authoredId);
  const locked = selection.some((row) => row.locked);
  const blocked = disabled || locked || ids.length === 0;
  const reason = locked ? "That layer is locked." : disabledReason;
  const allVisible = selection.every((row) => row.visible);

  // Dragging a row already reorders, but nothing on screen said so: a designer looking for
  // "move this behind that" found Group, Duplicate and Delete and concluded it was impossible.
  // These do the same thing one step at a time, which is also the only route by keyboard.
  const only = selection.length === 1 ? (selection[0] ?? null) : null;
  const parentId = only ? parentOf(rows, only) : null;
  const siblings =
    only && parentId !== null ? rows.filter((row) => parentOf(rows, row) === parentId) : [];
  const at = only ? siblings.findIndex((row) => row.key === only.key) : -1;

  function move(direction: -1 | 1): void {
    if (!only || at === -1 || parentId === null) return;
    // The panel lists topmost first and the engine indexes the authored list the other way, so
    // moving up the list means a higher authored index.
    const authored = siblings.length - 1 - at;
    const index = Math.max(
      0,
      Math.min(siblings.length - 1, authored + (direction === -1 ? 1 : -1)),
    );
    onSubmit([{ kind: "reorder", layer_id: only.authoredId, parent_id: parentId, index }]);
  }

  return (
    <div className="layers__actions" role="group" aria-label="Layer actions">
      <button
        type="button"
        disabled={blocked}
        onClick={() =>
          onSubmit(
            selection.map((row) => ({
              kind: "set_visibility" as const,
              layer_id: row.authoredId,
              visible: !allVisible,
            })),
          )
        }
      >
        {allVisible ? "Hide" : "Show"}
      </button>
      <button
        type="button"
        disabled={blocked || ids.length < 2}
        onClick={() =>
          onSubmit([{ kind: "group", layer_ids: ids, group_id: groupIdFor(selection) }])
        }
      >
        Group
      </button>
      <button
        type="button"
        disabled={blocked || ids.length !== 1}
        onClick={() => {
          const only = ids[0];
          if (only !== undefined) onSubmit([{ kind: "duplicate", layer_id: only }]);
        }}
      >
        Duplicate
      </button>
      <button
        type="button"
        disabled={blocked || only === null || at <= 0}
        onClick={() => move(-1)}
        title="Bring the layer forward"
      >
        Move up
      </button>
      <button
        type="button"
        disabled={blocked || only === null || at === -1 || at >= siblings.length - 1}
        onClick={() => move(1)}
        title="Send the layer backward"
      >
        Move down
      </button>
      <button
        type="button"
        disabled={blocked}
        onClick={() => onSubmit([{ kind: "delete", layer_ids: ids }])}
      >
        Delete
      </button>
      {reason !== null && ids.length > 0 ? (
        <p className="layers__reason" role="note">
          {reason}
        </p>
      ) : null}
    </div>
  );
}
