/** Coded diagnostics from validation and the last render, with their source location. */

import type { ReactNode } from "react";

import type { Diagnostic } from "../../contracts/index.ts";
import { useProjectSnapshot, useRenderStatus } from "../projects/index.ts";

function location(diagnostic: Diagnostic): string | null {
  const source = diagnostic.source;
  if (!source?.file) return null;
  const line = source.line === null || source.line === undefined ? "" : `:${source.line}`;
  return `${source.file}${line}`;
}

export function DiagnosticsPanel(): ReactNode {
  const snapshot = useProjectSnapshot();
  const render = useRenderStatus();

  const diagnostics: ReadonlyArray<Diagnostic> = [
    ...(snapshot.data?.diagnostics ?? []),
    ...(render.data?.diagnostics ?? []),
  ];

  if (diagnostics.length === 0) {
    return <p role="note">No diagnostics. The project validates and the last render succeeded.</p>;
  }

  return (
    <ul className="diagnostics">
      {diagnostics.map((diagnostic, index) => (
        <li
          key={`${diagnostic.code}-${index}`}
          className="diagnostics__row"
          data-severity={diagnostic.severity ?? "error"}
        >
          <span className="diagnostics__code measure">{diagnostic.code}</span>
          <span className="diagnostics__message">{diagnostic.message}</span>
          {location(diagnostic) ? (
            <span className="diagnostics__where measure">{location(diagnostic)}</span>
          ) : null}
          {diagnostic.hint ? <span className="diagnostics__hint">{diagnostic.hint}</span> : null}
        </li>
      ))}
    </ul>
  );
}
