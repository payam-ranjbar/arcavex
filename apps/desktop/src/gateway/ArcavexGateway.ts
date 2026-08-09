/** The one port between the workbench and the engine. Features depend on this, never on Tauri. */

import type {
  CheckResult,
  EngineHandshakeReport,
  HitTestReport,
  LayerTreeReport,
  ProjectPolicyReport,
  ProjectSnapshotReport,
  ProjectUIMetadataReport,
  ProposalActionReport,
  ProposalListReport,
} from "../contracts/index.ts";

/** The event envelope version this frontend understands; the core refuses to emit any other. */
export const DESKTOP_EVENT_VERSION = 1;

// Reports default these sections server-side, so a report may omit them while a write may not.
export type ProjectUIMetadataValue = NonNullable<ProjectUIMetadataReport["metadata"]>;
export type AutomationPolicyValue = NonNullable<ProjectPolicyReport["policy"]>;

export interface ProjectTarget {
  readonly format: string | null;
  readonly locale: string | null;
}

export type EngineStatus = "starting" | "ready" | "restarting" | "incompatible" | "failed";

export interface EngineState {
  readonly status: EngineStatus;
  /** Present once a compatible handshake completed; null in every diagnostic mode. */
  readonly handshake: EngineHandshakeReport | null;
  readonly artifactPath: string | null;
  readonly restartCount: number;
  readonly message: string | null;
}

export type RenderState = "idle" | "rendering" | "current" | "stale" | "failed";

export interface RenderOutput {
  readonly target: ProjectTarget;
  /** A WebView-loadable URL for the raster the engine produced; never a frontend-drawn scene. */
  readonly imageUrl: string;
  readonly widthPx: number;
  readonly heightPx: number;
  readonly renderRevision: string | null;
  readonly contentSha256: string | null;
  readonly compileMs: number | null;
  readonly renderMs: number | null;
}

export interface RenderStatus {
  readonly state: RenderState;
  readonly target: ProjectTarget;
  /** The last successful raster, kept visible through validation and render failures. */
  readonly lastGood: RenderOutput | null;
  readonly jobId: string | null;
  readonly diagnostics: CheckResult["diagnostics"];
}

export type ActivityActor = "desktop" | "external" | "engine";

export interface ActivityEntry {
  readonly id: string;
  readonly at: string;
  readonly actor: ActivityActor;
  readonly summary: string;
  readonly projectRevision: string | null;
  readonly renderRevision: string | null;
  readonly diagnostics: CheckResult["diagnostics"];
}

export type LiveRenderMode = "every-change" | "manual";

export interface DesktopSettings {
  readonly recentProjects: ReadonlyArray<string>;
  readonly themeId: string;
  readonly brandingId: string;
  readonly liveRender: LiveRenderMode;
  readonly checkForUpdates: boolean;
  readonly engineOverridePath: string | null;
}

export type DesktopEvent =
  | { readonly version: number; readonly type: "engine"; readonly engine: EngineState }
  | { readonly version: number; readonly type: "project"; readonly snapshot: ProjectSnapshotReport }
  | { readonly version: number; readonly type: "render"; readonly render: RenderStatus }
  | { readonly version: number; readonly type: "activity"; readonly entry: ActivityEntry }
  | { readonly version: number; readonly type: "settings"; readonly settings: DesktopSettings };

export type DesktopEventListener = (event: DesktopEvent) => void;
export type Unsubscribe = () => void;

export interface LayerTreeRequest {
  readonly mode: "authored" | "rendered";
  readonly target?: ProjectTarget;
}

export interface HitTestRequest {
  readonly xPt: number;
  readonly yPt: number;
  readonly target?: ProjectTarget;
}

export interface RenderRequest {
  readonly target?: ProjectTarget;
  /** Render every declared target rather than only the active one. */
  readonly all?: boolean;
}

/**
 * Every engine operation the workbench may perform.
 *
 * Implementations are the Tauri adapter and the deterministic fake used by component tests;
 * no other module in the frontend may reach the engine by any other route.
 */
export interface ArcavexGateway {
  engineState(): Promise<EngineState>;
  restartEngine(): Promise<EngineState>;

  chooseProjectDirectory(): Promise<string | null>;
  openProject(path: string): Promise<ProjectSnapshotReport>;
  closeProject(): Promise<void>;
  projectSnapshot(): Promise<ProjectSnapshotReport>;
  validateProject(): Promise<CheckResult>;

  activeTarget(): Promise<ProjectTarget>;
  setActiveTarget(target: ProjectTarget): Promise<ProjectTarget>;

  layerTree(request: LayerTreeRequest): Promise<LayerTreeReport>;
  hitTest(request: HitTestRequest): Promise<HitTestReport>;

  requestRender(request: RenderRequest): Promise<RenderStatus>;
  renderStatus(): Promise<RenderStatus>;

  uiMetadata(): Promise<ProjectUIMetadataReport>;
  setUiMetadata(metadata: ProjectUIMetadataValue): Promise<ProjectUIMetadataReport>;

  policy(): Promise<ProjectPolicyReport>;
  setPolicy(policy: AutomationPolicyValue): Promise<ProjectPolicyReport>;

  proposals(): Promise<ProposalListReport>;
  approveProposal(commandId: string): Promise<ProposalActionReport>;
  rejectProposal(commandId: string, reason: string): Promise<ProposalActionReport>;

  activity(): Promise<ReadonlyArray<ActivityEntry>>;
  settings(): Promise<DesktopSettings>;
  updateSettings(patch: Partial<DesktopSettings>): Promise<DesktopSettings>;

  subscribe(listener: DesktopEventListener): Unsubscribe;
}
