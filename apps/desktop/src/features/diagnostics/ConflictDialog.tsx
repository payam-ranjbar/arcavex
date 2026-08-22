/**
 * What the user sees when the project moved underneath their edit.
 *
 * A conflict is not an error to apologise for — it is the collaboration model working. Someone
 * else (an AI client, a CLI command, an editor) changed the project between the moment this
 * window read it and the moment the user acted. The dialog's whole job is to make that concrete:
 * name the files that moved and the layers involved, and offer the two honest choices.
 *
 * It deliberately does not offer to "force" the edit. Overwriting is exactly the last-write-wins
 * behaviour the revision guard exists to prevent, and a button labelled "overwrite" would let a
 * user destroy work they cannot see.
 */

import type { ReactNode } from "react";

import "./conflict.css";

import type { ConflictDetail } from "../../contracts/index.ts";

export interface ConflictDialogProps {
  readonly conflict: ConflictDetail;
  /** Discard the local attempt and re-read the project as it now stands. */
  readonly onReload: () => void;
  /** Keep the edit in hand and re-submit it against the current revision. */
  readonly onReapply: () => void;
  readonly onDismiss: () => void;
}

const CHANGE_LABEL: Record<string, string> = {
  created: "added",
  modified: "changed",
  deleted: "removed",
};

export function ConflictDialog({
  conflict,
  onReload,
  onReapply,
  onDismiss,
}: ConflictDialogProps): ReactNode {
  const changed = conflict.changed ?? [];
  const layers = conflict.layer_ids ?? [];

  return (
    <div
      className="conflict"
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="conflict-title"
      aria-describedby="conflict-body"
    >
      <h2 id="conflict-title" className="conflict__title">
        The project changed while you were editing
      </h2>
      <div id="conflict-body" className="conflict__body">
        <p>
          Your edit was composed against an earlier version of this project, so it was not applied.
          Nothing has been changed by you.
        </p>
        {changed.length > 0 ? (
          <>
            <h3 className="eyebrow">Changed by someone else</h3>
            <ul className="conflict__files">
              {changed.map((entry) => (
                <li key={entry.path}>
                  <span className="conflict__path measure">{entry.path}</span>
                  <span className="conflict__change">
                    {CHANGE_LABEL[entry.change ?? "modified"] ?? "changed"}
                  </span>
                </li>
              ))}
            </ul>
          </>
        ) : (
          // An unremembered base revision cannot be diffed; saying so beats implying nothing moved.
          <p className="conflict__unknown">
            The engine could not determine which files changed — the version your edit was based on
            is older than its record.
          </p>
        )}
        {layers.length > 0 ? (
          <p className="conflict__layers">
            Layers involved: <span className="measure">{layers.join(", ")}</span>
          </p>
        ) : null}
      </div>
      <div className="conflict__actions">
        <button
          type="button"
          className="conflict__action conflict__action--primary"
          onClick={onReload}
        >
          Reload the project
        </button>
        <button type="button" className="conflict__action" onClick={onReapply}>
          Re-apply my edit
        </button>
        <button
          type="button"
          className="conflict__action conflict__action--quiet"
          onClick={onDismiss}
        >
          Leave it for now
        </button>
      </div>
    </div>
  );
}
