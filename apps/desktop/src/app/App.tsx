/** The application root: a way in before a project is open, the bench once one is. */

import { useMemo, useState, type ReactNode } from "react";

import { ActivityPanel } from "../features/activity/index.ts";
import { CanvasViewport } from "../features/canvas/index.ts";
import { CapabilityProvider } from "../features/capabilities/index.ts";
import { DiagnosticsPanel } from "../features/diagnostics/index.ts";
import { LayersPanel } from "../features/layers/index.ts";
import {
  OpenProject,
  ProposalsPanel,
  useBrowseForProject,
  useDesktopEvents,
  useLayerTree,
  useOpenProject,
  useProjectSnapshot,
  useRequestRender,
  useSettings,
  WelcomeScreen,
} from "../features/projects/index.ts";
import { AppearanceSettings, RuntimeSettings } from "../features/settings/index.ts";
import { VariantBar } from "../features/variants/index.ts";
import { InspectorPanel, Workbench } from "../features/workspace/index.ts";
import { useGateway } from "./providers.tsx";
import { createRegistry, type ContributionRegistry } from "./contributions.ts";
import { useQuery } from "@tanstack/react-query";

interface Selection {
  /** The tree row key, so the layers panel can highlight exactly what was hit. */
  readonly key: string | null;
  readonly authoredId: string | null;
}

const NO_SELECTION: Selection = { key: null, authoredId: null };

export function App(): ReactNode {
  const gateway = useGateway();
  useDesktopEvents();

  const engine = useQuery({ queryKey: ["engine-state"], queryFn: () => gateway.engineState() });
  const settings = useSettings();
  const snapshot = useProjectSnapshot();
  const tree = useLayerTree("rendered");
  const open = useOpenProject();
  const browse = useBrowseForProject();
  const render = useRequestRender();

  const [selection, setSelection] = useState<Selection>(NO_SELECTION);

  const capabilities = engine.data?.handshake?.capabilities ?? [];
  const selectedLayer = useSelectedBounds(tree.data, selection.authoredId);
  const registry = useContributions(selection, setSelection, () => render.mutate());

  if (engine.isPending) {
    return (
      <main aria-busy="true">
        <p>Starting the Arcavex engineâ€¦</p>
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

  const canvas = {
    widthPt: tree.data?.canvas_pt?.[0] ?? 0,
    heightPt: tree.data?.canvas_pt?.[1] ?? 0,
  };

  return (
    <CapabilityProvider capabilities={capabilities}>
      <Workbench registry={registry}>
        <VariantBar />
        <CanvasViewport
          canvas={canvas}
          selectionBounds={selectedLayer}
          onHit={(candidate) =>
            setSelection(
              candidate === null
                ? NO_SELECTION
                : { key: candidate.id, authoredId: candidate.authored_id },
            )
          }
        />
      </Workbench>
    </CapabilityProvider>
  );
}

/** The selected layer's bounds, straight from the engine's tree â€” never computed here. */
function useSelectedBounds(
  tree: ReturnType<typeof useLayerTree>["data"],
  authoredId: string | null,
): readonly [number, number, number, number] | null {
  return useMemo(() => {
    if (!tree?.root || authoredId === null) return null;
    const find = (
      node: NonNullable<typeof tree.root>,
    ): readonly [number, number, number, number] | null => {
      if (node.authored_id === authoredId) return node.bounds_pt ?? null;
      for (const child of node.children ?? []) {
        const found = find(child);
        if (found) return found;
      }
      return null;
    };
    return find(tree.root);
  }, [tree, authoredId]);
}

/**
 * Register every panel the viewer contributes.
 *
 * The shell imports none of these; it only knows the registry, which is what makes adding a
 * Phase 2 panel a matter of registering it rather than editing the workbench.
 */
function useContributions(
  selection: Selection,
  setSelection: (selection: Selection) => void,
  requestRender: () => void,
): ContributionRegistry {
  const tree = useLayerTree("rendered");

  return useMemo(() => {
    const registry = createRegistry();

    registry.addCommand({
      id: "render",
      title: "Render",
      primary: true,
      order: 10,
      capability: "render.preview",
      run: requestRender,
    });

    registry.addPanel({
      id: "project",
      title: "Project",
      region: "sidebar",
      order: 10,
      render: () => <OpenProject />,
    });
    registry.addPanel({
      id: "layers",
      title: "Layers",
      region: "sidebar",
      order: 20,
      capability: "layers.tree",
      render: () => (
        <LayersPanel
          selectedKey={selection.key}
          onSelect={(row) =>
            setSelection(row === null ? NO_SELECTION : { key: row.key, authoredId: row.authoredId })
          }
        />
      ),
    });

    registry.addPanel({
      id: "properties",
      title: "Properties",
      region: "inspector",
      order: 10,
      render: () => <InspectorPanel tree={tree.data} selectedAuthoredId={selection.authoredId} />,
    });
    registry.addPanel({
      id: "diagnostics",
      title: "Diagnostics",
      region: "inspector",
      order: 20,
      render: () => <DiagnosticsPanel />,
    });
    registry.addPanel({
      id: "runtime",
      title: "Modes",
      region: "inspector",
      order: 30,
      render: () => <RuntimeSettings />,
    });
    registry.addPanel({
      id: "proposals",
      title: "Proposals",
      region: "inspector",
      order: 40,
      render: () => <ProposalsPanel />,
    });

    registry.addPanel({
      id: "activity",
      title: "Activity",
      region: "activity",
      order: 10,
      render: () => <ActivityPanel />,
    });

    registry.addSettings({
      id: "appearance",
      title: "Appearance",
      order: 10,
      render: () => <AppearanceSettings />,
    });
    return registry;
  }, [selection, setSelection, requestRender, tree.data]);
}
