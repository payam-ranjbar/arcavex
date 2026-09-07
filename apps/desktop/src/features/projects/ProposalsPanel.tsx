/** Queued semantic commands awaiting a decision, when automation is in review mode. */

import { useState, type ReactNode } from "react";

import { useProposalActions, useProposals } from "./projectQueries.ts";

export function ProposalsPanel(): ReactNode {
  const proposals = useProposals();
  const { approve, reject } = useProposalActions();
  const [reasons, setReasons] = useState<Record<string, string>>({});

  const pending = (proposals.data?.proposals ?? []).filter(
    (proposal) => proposal.state === "pending",
  );

  if (proposals.isError) {
    return <p role="note">Proposals are unavailable while no project is open.</p>;
  }
  if (pending.length === 0) {
    return <p role="note">Nothing is waiting for approval.</p>;
  }

  return (
    <ul className="proposals">
      {pending.map((proposal) => {
        const reason = reasons[proposal.command_id] ?? "";
        return (
          <li key={proposal.command_id} className="proposals__entry">
            <p className="proposals__actor">
              {proposal.actor.display_name ?? proposal.actor.id} proposed a change
            </p>
            <p className="proposals__base measure" title={proposal.base_project_revision}>
              base {proposal.base_project_revision.slice(0, 12)}
            </p>
            <div className="proposals__actions">
              <button type="button" onClick={() => approve.mutate(proposal.command_id)}>
                Approve
              </button>
              <label htmlFor={`reason-${proposal.command_id}`}>Reason</label>
              <input
                id={`reason-${proposal.command_id}`}
                value={reason}
                onChange={(event) =>
                  setReasons((current) => ({
                    ...current,
                    [proposal.command_id]: event.target.value,
                  }))
                }
              />
              <button
                type="button"
                disabled={reason.trim() === ""}
                title={reason.trim() === "" ? "Say why before rejecting" : "Reject this proposal"}
                onClick={() =>
                  reject.mutate({ commandId: proposal.command_id, reason: reason.trim() })
                }
              >
                Reject
              </button>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
