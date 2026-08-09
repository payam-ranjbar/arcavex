/** The shell: five stable regions, filled entirely by contributions. */

import { useEffect, useState, type ReactNode } from "react";

import type {
  CommandContribution,
  ContributionRegistry,
  PanelContribution,
  PanelRegion,
} from "../../app/contributions.ts";
import { CapabilityGate, useCapability } from "../capabilities/index.ts";
import { useTheme } from "../../theme/ThemeProvider.tsx";

import "./workbench.css";

/** Below this width the inspector folds away so the proof keeps the room. */
export const COMPACT_WIDTH = 1100;

function useCompactLayout(): boolean {
  const [compact, setCompact] = useState(
    () => typeof window !== "undefined" && window.innerWidth < COMPACT_WIDTH,
  );
  useEffect(() => {
    const query = window.matchMedia(`(max-width: ${COMPACT_WIDTH - 1}px)`);
    const update = (event: MediaQueryListEvent | MediaQueryList) => setCompact(event.matches);
    update(query);
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  return compact;
}

/**
 * A panel is a heading and its content, not a landmark.
 *
 * The shell already exposes four landmarks. Making every panel a fifth, sixth, and seventh
 * would bury them, and a panel named after the region containing it would be ambiguous to
 * anyone navigating by landmark.
 */
function Panel({ panel }: { readonly panel: PanelContribution }): ReactNode {
  return (
    <div className="panel">
      <header className="panel__header">
        <h2 className="panel__title" id={`panel-${panel.id}`}>
          {panel.title}
        </h2>
      </header>
      <div className="panel__body">
        <CapabilityGate
          capability={panel.capability}
          unavailableLabel={`${panel.title} needs an engine capability this build does not report.`}
        >
          {panel.render()}
        </CapabilityGate>
      </div>
    </div>
  );
}

function PanelRegionView({
  registry,
  region,
}: {
  readonly registry: ContributionRegistry;
  readonly region: PanelRegion;
}): ReactNode {
  return registry.panels(region).map((panel) => <Panel key={panel.id} panel={panel} />);
}

function CommandButton({ command }: { readonly command: CommandContribution }): ReactNode {
  const available = useCapability(command.capability);
  return (
    <button
      type="button"
      onClick={command.run}
      disabled={!available}
      title={
        available
          ? command.title
          : `The connected engine does not support ${command.capability ?? "this"}.`
      }
    >
      {command.title}
    </button>
  );
}

export interface WorkbenchProps {
  readonly registry: ContributionRegistry;
  /** The canvas region. Everything else is contributed. */
  readonly children: ReactNode;
}

export function Workbench({ registry, children }: WorkbenchProps): ReactNode {
  const { branding } = useTheme();
  const compact = useCompactLayout();

  return (
    <div className="workbench" data-compact={compact} data-testid="workbench">
      <header className="workbench__bar">
        <div className="workbench__brand">
          <span className="workbench__mark" aria-hidden="true">
            {branding.mark}
          </span>
          <h1 className="workbench__product">{branding.productName}</h1>
        </div>
        <nav className="workbench__commands" aria-label="Commands">
          {registry
            .commands()
            .filter((command) => command.primary)
            .map((command) => (
              <CommandButton key={command.id} command={command} />
            ))}
        </nav>
      </header>

      <nav className="workbench__sidebar" aria-label="Project">
        <PanelRegionView registry={registry} region="sidebar" />
      </nav>

      <main className="workbench__canvas" aria-label="Canvas">
        {children}
      </main>

      {compact ? null : (
        <aside className="workbench__inspector" aria-label="Inspector">
          <PanelRegionView registry={registry} region="inspector" />
        </aside>
      )}

      <section className="workbench__activity" aria-label="Activity">
        <PanelRegionView registry={registry} region="activity" />
      </section>
    </div>
  );
}
