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
  readonly disabled: boolean;
  readonly disabledReason: string | null;
  readonly onSubmit: (commands: ReadonlyArray<EditorCommand>) => void;
}

/** A fresh group id derived from the selection, so the name is predictable rather than random. */
export function groupIdFor(selection: ReadonlyArray<LayerRow>): string {
  const first = selection[0];
  return first ? `${first.authoredId}-group` : "group";
}

export function LayerActions({
  selection,
  disabled,
  disabledReason,
  onSubmit,
}: LayerActionsProps): ReactNode {
  const ids = selection.map((row) => row.authoredId);
  const locked = selection.some((row) => row.locked);
  const blocked = disabled || locked || ids.length === 0;
  const reason = locked ? "That layer is locked." : disabledReason;
  const allVisible = selection.every((row) => row.visible);

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
