/** The application root: a way in before a project is open, the bench once one is. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, type ReactNode } from "react";

import { CapabilityProvider } from "../features/capabilities/index.ts";
import { WelcomeScreen } from "../features/projects/index.ts";
import { AppearanceSettings } from "../features/settings/index.ts";
import { Workbench } from "../features/workspace/index.ts";
import { createRegistry, type ContributionRegistry } from "./contributions.ts";
import { useGateway } from "./providers.tsx";

export function App(): ReactNode {
  const gateway = useGateway();
  const queryClient = useQueryClient();

  const engine = useQuery({ queryKey: ["engine-state"], queryFn: () => gateway.engineState() });
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => gateway.settings() });
  const snapshot = useQuery({
    queryKey: ["project-snapshot"],
    queryFn: () => gateway.projectSnapshot(),
    // No project open is an expected state, not an error worth retrying.
    retry: false,
  });

  const open = useMutation({
    mutationFn: (path: string) => gateway.openProject(path),
    onSuccess: () => queryClient.invalidateQueries(),
  });
  const browse = useMutation({
    mutationFn: async () => {
      const path = await gateway.chooseProjectDirectory();
      return path === null ? null : gateway.openProject(path);
    },
    onSuccess: () => queryClient.invalidateQueries(),
  });

  const capabilities = engine.data?.handshake?.capabilities ?? [];
  const registry = useContributions();

  if (engine.isPending) {
    return (
      <main aria-busy="true">
        <p>Starting the Arcavex engine…</p>
      </main>
    );
  }

  const engineMessage = engine.isError
    ? "The engine could not be reached."
    : (engine.data.message ?? null);

  if (!snapshot.data) {
    return (
      <CapabilityProvider capabilities={capabilities}>
        <WelcomeScreen
          recentProjects={settings.data?.recentProjects ?? []}
          onBrowse={() => browse.mutate()}
          onOpen={(path) => open.mutate(path)}
          engineMessage={engineMessage}
        />
      </CapabilityProvider>
    );
  }

  return (
    <CapabilityProvider capabilities={capabilities}>
      <Workbench registry={registry}>
        <p>{snapshot.data.name ?? snapshot.data.canonical_path}</p>
      </Workbench>
    </CapabilityProvider>
  );
}

/**
 * Register the shell's own contributions.
 *
 * The viewer's panels register here too, which is why the shell itself imports none of them.
 */
function useContributions(): ContributionRegistry {
  return useMemo(() => {
    const registry = createRegistry();
    registry.addSettings({
      id: "appearance",
      title: "Appearance",
      order: 10,
      render: () => <AppearanceSettings />,
    });
    return registry;
  }, []);
}
