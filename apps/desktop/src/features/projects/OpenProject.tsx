/** The open project's identity and revisions, and the way to leave it. */

import type { ReactNode } from "react";

import { useGateway } from "../../app/providers.tsx";
import { useProjectSnapshot } from "./projectQueries.ts";

export function OpenProject(): ReactNode {
  const gateway = useGateway();
  const snapshot = useProjectSnapshot();

  if (!snapshot.data) {
    return <p role="note">No project is open.</p>;
  }

  const project = snapshot.data;
  return (
    <div className="open-project">
      <p className="open-project__name">{project.name ?? "Untitled project"}</p>
      <p className="open-project__path measure" title={project.canonical_path ?? ""}>
        {project.canonical_path}
      </p>

      <dl className="open-project__revisions">
        <dt>Project</dt>
        <dd className="measure" title={project.project_revision ?? ""}>
          {project.project_revision?.slice(0, 12) ?? "unknown"}
        </dd>
        <dt>Render</dt>
        <dd className="measure" title={project.render_revision ?? ""}>
          {project.render_revision?.slice(0, 12) ?? "unknown"}
        </dd>
      </dl>

      <button type="button" onClick={() => void gateway.closeProject()}>
        Close project
      </button>
    </div>
  );
}
