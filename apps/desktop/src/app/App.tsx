/** The application root. Phase 1 replaces this body with the contributed workbench shell. */

import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { useGateway } from "./providers.tsx";

export function App(): ReactNode {
  const gateway = useGateway();
  const engine = useQuery({ queryKey: ["engine-state"], queryFn: () => gateway.engineState() });

  if (engine.isPending) {
    return (
      <main aria-busy="true">
        <p>Starting the Arcavex engine…</p>
      </main>
    );
  }

  if (engine.isError) {
    return (
      <main>
        <h1>Arcavex Desktop</h1>
        <p role="alert">The engine could not be reached.</p>
      </main>
    );
  }

  return (
    <main>
      <h1>Arcavex Desktop</h1>
      <p>
        Engine <span data-testid="engine-status">{engine.data.status}</span>
        {engine.data.handshake ? ` · ${engine.data.handshake.identity.engine_version}` : ""}
      </p>
      {engine.data.message ? <p role="alert">{engine.data.message}</p> : null}
    </main>
  );
}
