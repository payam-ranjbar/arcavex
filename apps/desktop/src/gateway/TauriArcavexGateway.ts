/** The only module permitted to speak Tauri. Everything else depends on `ArcavexGateway`. */

import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

import type {
  CheckResult,
  HitTestReport,
  LayerTreeReport,
  ProjectPolicyReport,
  ProjectSnapshotReport,
  ProjectUIMetadataReport,
  ProposalActionReport,
  ProposalListReport,
} from "../contracts/index.ts";
import {
  DESKTOP_EVENT_VERSION,
  type ActivityEntry,
  type ArcavexGateway,
  type AutomationPolicyValue,
  type DesktopEvent,
  type DesktopEventListener,
  type DesktopSettings,
  type EngineState,
  type LayerTreeMode,
  type ProjectTarget,
  type ProjectUIMetadataValue,
  type RenderStatus,
  type Unsubscribe,
} from "./ArcavexGateway.ts";

/** Single Tauri event channel; a versioned envelope lets the core evolve without guessing. */
export const DESKTOP_EVENT_CHANNEL = "arcavex:desktop-event";

export class TauriArcavexGateway implements ArcavexGateway {
  engineState(): Promise<EngineState> {
    return invoke("engine_state");
  }

  restartEngine(): Promise<EngineState> {
    return invoke("restart_engine");
  }

  chooseProjectDirectory(): Promise<string | null> {
    return invoke("choose_project_directory");
  }

  openProject(path: string): Promise<ProjectSnapshotReport> {
    return invoke("open_project", { path });
  }

  closeProject(): Promise<void> {
    return invoke("close_project");
  }

  projectSnapshot(): Promise<ProjectSnapshotReport> {
    return invoke("project_snapshot");
  }

  validateProject(): Promise<CheckResult> {
    return invoke("validate_project");
  }

  activeTarget(): Promise<ProjectTarget> {
    return invoke("active_target");
  }

  setActiveTarget(target: ProjectTarget): Promise<ProjectTarget> {
    return invoke("set_active_target", { target });
  }

  layerTree(mode: LayerTreeMode): Promise<LayerTreeReport> {
    return invoke("layer_tree", { mode });
  }

  hitTest(xPt: number, yPt: number): Promise<HitTestReport> {
    return invoke("hit_test", { xPt, yPt });
  }

  requestRender(): Promise<RenderStatus> {
    return invoke("request_render");
  }

  renderStatus(): Promise<RenderStatus> {
    return invoke("render_status");
  }

  uiMetadata(): Promise<ProjectUIMetadataReport> {
    return invoke("ui_metadata");
  }

  setUiMetadata(metadata: ProjectUIMetadataValue): Promise<ProjectUIMetadataReport> {
    return invoke("set_ui_metadata", { metadata });
  }

  policy(): Promise<ProjectPolicyReport> {
    return invoke("project_policy");
  }

  setPolicy(policy: AutomationPolicyValue): Promise<ProjectPolicyReport> {
    return invoke("set_project_policy", { policy });
  }

  proposals(): Promise<ProposalListReport> {
    return invoke("list_proposals");
  }

  approveProposal(commandId: string): Promise<ProposalActionReport> {
    return invoke("approve_proposal", { commandId });
  }

  rejectProposal(commandId: string, reason: string): Promise<ProposalActionReport> {
    return invoke("reject_proposal", { commandId, reason });
  }

  activity(): Promise<ReadonlyArray<ActivityEntry>> {
    return invoke("activity");
  }

  settings(): Promise<DesktopSettings> {
    return invoke("settings");
  }

  updateSettings(patch: Partial<DesktopSettings>): Promise<DesktopSettings> {
    return invoke("update_settings", { patch });
  }

  subscribe(listener: DesktopEventListener): Unsubscribe {
    let cancelled = false;
    const pending = listen<DesktopEvent>(DESKTOP_EVENT_CHANNEL, ({ payload }) => {
      // An envelope from an incompatible core is dropped rather than guessed at.
      if (payload.version === DESKTOP_EVENT_VERSION) listener(payload);
    });
    void pending.then((unlisten) => {
      if (cancelled) unlisten();
    });
    return () => {
      cancelled = true;
      void pending.then((unlisten) => {
        unlisten();
      });
    };
  }
}
