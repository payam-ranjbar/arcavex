/** Who changed what, labelled by actor, newest first. */

import type { ReactNode } from "react";

import { useActivity } from "../projects/index.ts";

const ACTOR_LABEL = {
  desktop: "This bench",
  external: "External",
} as const;

/** Local wall-clock time; the core reports epoch milliseconds and takes no view on format. */
function formatTime(at: number): string {
  return new Date(at).toLocaleTimeString();
}

export function ActivityPanel(): ReactNode {
  const activity = useActivity();
  const entries = [...(activity.data ?? [])].reverse();

  if (entries.length === 0) {
    return <p role="note">Nothing has changed since this project was opened.</p>;
  }

  return (
    <ol className="activity">
      {entries.map((entry) => (
        <li key={entry.id} className="activity__entry" data-actor={entry.actor}>
          <span className="activity__time measure">{formatTime(entry.at)}</span>
          <span className="activity__actor">{ACTOR_LABEL[entry.actor]}</span>
          <span className="activity__summary">{entry.summary}</span>
          {entry.renderRevision ? (
            <span className="activity__revision measure" title={entry.renderRevision}>
              {entry.renderRevision.slice(0, 8)}
            </span>
          ) : null}
        </li>
      ))}
    </ol>
  );
}
