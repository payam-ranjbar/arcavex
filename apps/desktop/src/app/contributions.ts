/**
 * How features add to the shell without the shell knowing them.
 *
 * Phase 1 deliberately exposes no third-party React plugin API: this registry is internal, so
 * the workbench stays extensible without committing to a UI extension ABI that cannot change.
 */

import type { ReactNode } from "react";

/** Where a contributed panel is mounted. These are the shell's five stable regions. */
export type PanelRegion = "sidebar" | "inspector" | "activity";

interface Contribution {
  readonly id: string;
  readonly title: string;
  /** Lower sorts first; ties break on title so ordering is never accidental. */
  readonly order?: number;
  /** An engine capability this contribution needs. Absent means always available. */
  readonly capability?: string;
}

export interface CommandContribution extends Contribution {
  /** Shown in the command bar when true; commands default to hidden there. */
  readonly primary?: boolean;
  readonly run: () => void;
}

export interface PanelContribution extends Contribution {
  readonly region: PanelRegion;
  readonly render: () => ReactNode;
}

export interface SettingsContribution extends Contribution {
  readonly render: () => ReactNode;
}

export interface ContributionRegistry {
  readonly addCommand: (command: CommandContribution) => void;
  readonly addPanel: (panel: PanelContribution) => void;
  readonly addSettings: (section: SettingsContribution) => void;
  readonly commands: () => ReadonlyArray<CommandContribution>;
  readonly panels: (region: PanelRegion) => ReadonlyArray<PanelContribution>;
  readonly settings: () => ReadonlyArray<SettingsContribution>;
}

function byOrderThenTitle<T extends Contribution>(left: T, right: T): number {
  const difference = (left.order ?? 100) - (right.order ?? 100);
  return difference === 0 ? left.title.localeCompare(right.title) : difference;
}

/** Reject a duplicate id rather than let one contribution silently replace another. */
function insert<T extends Contribution>(into: T[], contribution: T, kind: string): void {
  if (into.some((existing) => existing.id === contribution.id)) {
    throw new Error(`a ${kind} with id "${contribution.id}" is already registered`);
  }
  into.push(contribution);
}

export function createRegistry(): ContributionRegistry {
  const commands: CommandContribution[] = [];
  const panels: PanelContribution[] = [];
  const sections: SettingsContribution[] = [];

  return {
    addCommand: (command) => insert(commands, command, "command"),
    addPanel: (panel) => insert(panels, panel, "panel"),
    addSettings: (section) => insert(sections, section, "settings section"),
    commands: () => [...commands].sort(byOrderThenTitle),
    panels: (region) => panels.filter((panel) => panel.region === region).sort(byOrderThenTitle),
    settings: () => [...sections].sort(byOrderThenTitle),
  };
}
