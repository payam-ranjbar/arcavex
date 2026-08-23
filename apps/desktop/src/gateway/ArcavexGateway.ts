/** The one port between the workbench and the engine. Features depend on this, never on Tauri. */

import type {
  CheckResult,
  EngineHandshakeReport,
  HistoryReport,
  HitTestReport,
  LayerTreeReport,
  ProjectPolicyReport,
  ProjectSnapshotReport,
  ProjectUIMetadataReport,
  ProposalActionReport,
  ProposalListReport,
  SemanticTransaction,
  TransactionReport,
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

/** Everything that makes one rendered picture different from another. */
export interface RenderKey {
  readonly renderRevision: string;
  readonly format: string | null;
  readonly locale: string | null;
  readonly options: Readonly<Record<string, string>>;
}

export interface RenderOutput {
  readonly key: RenderKey;
  /** A WebView-loadable URL for the raster the engine produced; never a frontend-drawn scene. */
  readonly imageUrl: string;
  readonly widthPx: number;
  readonly heightPx: number;
  readonly contentSha256: string | null;
  readonly compileMs: number | null;
  readonly renderMs: number | null;
}

export interface RenderStatus {
  readonly state: RenderState;
  /** What the workbench is currently asking for; null before a project is open. */
  readonly key: RenderKey | null;
  /** The last successful raster, kept visible through validation and render failures. */
  readonly lastGood: RenderOutput | null;
  readonly jobId: number | null;
  readonly diagnostics: CheckResult["diagnostics"];
}

export type ActivityActor = "desktop" | "external";

export interface ActivityEntry {
  readonly id: string;
  /** Milliseconds since the Unix epoch; the workbench decides how to display it. */
  readonly at: number;
  readonly actor: ActivityActor;
  readonly summary: string;
  readonly projectRevision: string | null;
  readonly renderRevision: string | null;
  readonly diagnostics: CheckResult["diagnostics"];
}

export type LiveRenderMode = "every-change" | "manual";
export type AutomationMode = "unrestricted" | "review" | "read_only";
export type ExtensionMode = "unrestricted" | "disabled";

export interface WorkspacePreferences {
  readonly leftSidebarVisible: boolean;
  readonly rightInspectorVisible: boolean;
  readonly activityVisible: boolean;
}

export interface DesktopSettings {
  readonly version: number;
  readonly recentProjects: ReadonlyArray<string>;
  readonly themeId: string;
  readonly brandingId: string;
  readonly liveRender: LiveRenderMode;
  readonly automation: AutomationMode;
  readonly extensions: ExtensionMode;
  readonly checkForUpdates: boolean;
  readonly engineOverridePath: string | null;
  readonly workspace: WorkspacePreferences;
}

export type DesktopEvent =
  | { readonly version: number; readonly type: "engine"; readonly engine: EngineState }
  | { readonly version: number; readonly type: "project"; readonly snapshot: ProjectSnapshotReport }
  | { readonly version: number; readonly type: "render"; readonly render: RenderStatus }
  | { readonly version: number; readonly type: "activity"; readonly entry: ActivityEntry }
  | { readonly version: number; readonly type: "settings"; readonly settings: DesktopSettings };

export type DesktopEventListener = (event: DesktopEvent) => void;
export type Unsubscribe = () => void;

/** The active target is core state, so tree and hit-test requests never restate it. */
export type LayerTreeMode = "authored" | "rendered";

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
  /** Save the rendered picture to a file the person chooses; null when they cancel. */
  saveRenderAs(): Promise<string | null>;
  projectSnapshot(): Promise<ProjectSnapshotReport>;
  validateProject(): Promise<CheckResult>;

  activeTarget(): Promise<ProjectTarget>;
  setActiveTarget(target: ProjectTarget): Promise<ProjectTarget>;

  layerTree(mode: LayerTreeMode): Promise<LayerTreeReport>;
  hitTest(xPt: number, yPt: number): Promise<HitTestReport>;

  requestRender(): Promise<RenderStatus>;
  renderStatus(): Promise<RenderStatus>;

  uiMetadata(): Promise<ProjectUIMetadataReport>;
  setUiMetadata(metadata: ProjectUIMetadataValue): Promise<ProjectUIMetadataReport>;

  policy(): Promise<ProjectPolicyReport>;
  setPolicy(policy: AutomationPolicyValue): Promise<ProjectPolicyReport>;

  proposals(): Promise<ProposalListReport>;
  approveProposal(commandId: string): Promise<ProposalActionReport>;
  rejectProposal(commandId: string, reason: string): Promise<ProposalActionReport>;

  /**
   * Execute one semantic transaction.
   *
   * A refusal is a resolved report carrying a conflict or diagnostics, not a rejection: the
   * engine answering "no, and here is why" is a normal outcome the workbench renders.
   */
  editorApply(transaction: SemanticTransaction): Promise<TransactionReport>;
  editorApplyAuthorized(commandId: string): Promise<TransactionReport>;
  editorUndo(): Promise<TransactionReport>;
  editorRedo(): Promise<TransactionReport>;
  editorHistory(): Promise<HistoryReport>;

  activity(): Promise<ReadonlyArray<ActivityEntry>>;
  settings(): Promise<DesktopSettings>;
  updateSettings(patch: Partial<DesktopSettings>): Promise<DesktopSettings>;

  subscribe(listener: DesktopEventListener): Unsubscribe;
}
