/** A deterministic in-memory gateway so every component test runs without an engine process. */

import {
  desktopContractFixtures,
  type CheckResult,
  type DesktopContractName,
  type HitTestReport,
  type LayerTreeReport,
  type ProjectPolicyReport,
  type ProjectSnapshotReport,
  type ProjectUIMetadataReport,
  type ProposalActionReport,
  type ProposalListReport,
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
  type RenderKey,
  type RenderStatus,
  type Unsubscribe,
} from "./ArcavexGateway.ts";

/** Seeded from the generated fixtures so the fake can never drift from the real contracts. */
function fixture<T>(name: DesktopContractName): T {
  return structuredClone(desktopContractFixtures[name]) as unknown as T;
}

export const FAKE_PROJECT_PATH = "/workspace/fixture-poster";

export interface FakeGatewayScript {
  readonly engine?: Partial<EngineState>;
  readonly snapshot?: ProjectSnapshotReport;
  readonly layerTree?: LayerTreeReport;
  readonly hitTest?: HitTestReport;
  readonly validate?: CheckResult;
  readonly uiMetadata?: ProjectUIMetadataReport;
  readonly policy?: ProjectPolicyReport;
  readonly proposals?: ProposalListReport;
  readonly settings?: Partial<DesktopSettings>;
  readonly renderStatus?: RenderStatus;
  readonly activity?: ReadonlyArray<ActivityEntry>;
  /** Directory the open dialog returns; null models a cancelled dialog. */
  readonly chosenDirectory?: string | null;
}

export interface RecordedCall {
  readonly method: string;
  readonly argument?: unknown;
}

/**
 * One event without its envelope version, which `emit` supplies.
 *
 * The distribution over the union matters: a plain `Omit` would collapse the variants to their
 * shared keys and reject every payload.
 */
export type UnversionedDesktopEvent = DesktopEvent extends infer Variant
  ? Variant extends DesktopEvent
    ? Omit<Variant, "version">
    : never
  : never;

const DEFAULT_TARGET: ProjectTarget = { format: "poster-a3", locale: "en-US" };

const DEFAULT_SETTINGS: DesktopSettings = {
  version: 1,
  recentProjects: [FAKE_PROJECT_PATH],
  themeId: "arcavex-dark",
  brandingId: "arcavex",
  liveRender: "every-change",
  automation: "unrestricted",
  extensions: "unrestricted",
  checkForUpdates: false,
  engineOverridePath: null,
  workspace: {
    leftSidebarVisible: true,
    rightInspectorVisible: true,
    activityVisible: false,
  },
};

function defaultRenderStatus(target: ProjectTarget): RenderStatus {
  const key: RenderKey = {
    renderRevision: "3c".repeat(32),
    format: target.format,
    locale: target.locale,
    options: {},
  };
  return {
    state: "current",
    key,
    lastGood: {
      key,
      imageUrl: "arcavex://localhost/outputs/fixture-poster.png",
      widthPx: 1684,
      heightPx: 2382,
      contentSha256: "9f".repeat(32),
      compileMs: 13,
      renderMs: 84,
    },
    jobId: 1,
    diagnostics: [],
  };
}

export class FakeArcavexGateway implements ArcavexGateway {
  readonly calls: RecordedCall[] = [];

  private readonly listeners = new Set<DesktopEventListener>();
  private readonly failures = new Map<string, Error>();
  private readonly script: FakeGatewayScript;

  private engine: EngineState;
  private target: ProjectTarget;
  private settingsState: DesktopSettings;
  private render: RenderStatus;
  private openPath: string | null = null;

  constructor(script: FakeGatewayScript = {}) {
    this.script = script;
    this.engine = {
      status: "ready",
      handshake: fixture("EngineHandshakeReport"),
      artifactPath: "/opt/arcavex/arcavex",
      restartCount: 0,
      message: null,
      ...script.engine,
    };
    this.target = DEFAULT_TARGET;
    this.settingsState = { ...DEFAULT_SETTINGS, ...script.settings };
    this.render = script.renderStatus ?? defaultRenderStatus(this.target);
  }

  /** Make the next call to one method reject, modelling engine and filesystem failures. */
  failNext(method: keyof ArcavexGateway, error: Error): void {
    this.failures.set(method, error);
  }

  /** Publish an event exactly as the Rust core would, for watcher and scheduler scenarios. */
  emit(event: UnversionedDesktopEvent): void {
    const envelope = { ...event, version: DESKTOP_EVENT_VERSION } as DesktopEvent;
    for (const listener of [...this.listeners]) listener(envelope);
  }

  private record<T>(method: keyof ArcavexGateway, value: T, argument?: unknown): Promise<T> {
    this.calls.push(argument === undefined ? { method } : { method, argument });
    const failure = this.failures.get(method);
    if (failure) {
      this.failures.delete(method);
      return Promise.reject(failure);
    }
    return Promise.resolve(value);
  }

  engineState(): Promise<EngineState> {
    return this.record("engineState", this.engine);
  }

  restartEngine(): Promise<EngineState> {
    this.engine = { ...this.engine, status: "ready", restartCount: this.engine.restartCount + 1 };
    return this.record("restartEngine", this.engine);
  }

  chooseProjectDirectory(): Promise<string | null> {
    const chosen =
      this.script.chosenDirectory === undefined ? FAKE_PROJECT_PATH : this.script.chosenDirectory;
    return this.record("chooseProjectDirectory", chosen);
  }

  openProject(path: string): Promise<ProjectSnapshotReport> {
    this.openPath = path;
    this.settingsState = {
      ...this.settingsState,
      recentProjects: [
        path,
        ...this.settingsState.recentProjects.filter((entry) => entry !== path),
      ],
    };
    return this.record("openProject", this.snapshotValue(), path);
  }

  closeProject(): Promise<void> {
    this.openPath = null;
    return this.record("closeProject", undefined);
  }

  projectSnapshot(): Promise<ProjectSnapshotReport> {
    return this.record("projectSnapshot", this.snapshotValue());
  }

  validateProject(): Promise<CheckResult> {
    return this.record("validateProject", this.script.validate ?? fixture("CheckResult"));
  }

  activeTarget(): Promise<ProjectTarget> {
    return this.record("activeTarget", this.target);
  }

  setActiveTarget(target: ProjectTarget): Promise<ProjectTarget> {
    this.target = target;
    this.render = { ...this.render, state: "stale" };
    return this.record("setActiveTarget", this.target, target);
  }

  layerTree(mode: LayerTreeMode): Promise<LayerTreeReport> {
    const tree = this.script.layerTree ?? fixture<LayerTreeReport>("LayerTreeReport");
    return this.record("layerTree", { ...tree, mode }, mode);
  }

  hitTest(xPt: number, yPt: number): Promise<HitTestReport> {
    return this.record("hitTest", this.script.hitTest ?? fixture("HitTestReport"), {
      xPt,
      yPt,
    });
  }

  requestRender(): Promise<RenderStatus> {
    this.render = { ...this.render, state: "current" };
    return this.record("requestRender", this.render);
  }

  renderStatus(): Promise<RenderStatus> {
    return this.record("renderStatus", this.render);
  }

  uiMetadata(): Promise<ProjectUIMetadataReport> {
    return this.record("uiMetadata", this.script.uiMetadata ?? fixture("ProjectUIMetadataReport"));
  }

  setUiMetadata(metadata: ProjectUIMetadataValue): Promise<ProjectUIMetadataReport> {
    const current =
      this.script.uiMetadata ?? fixture<ProjectUIMetadataReport>("ProjectUIMetadataReport");
    return this.record("setUiMetadata", { ...current, metadata }, metadata);
  }

  policy(): Promise<ProjectPolicyReport> {
    return this.record("policy", this.script.policy ?? fixture("ProjectPolicyReport"));
  }

  setPolicy(policy: AutomationPolicyValue): Promise<ProjectPolicyReport> {
    const current = this.script.policy ?? fixture<ProjectPolicyReport>("ProjectPolicyReport");
    return this.record("setPolicy", { ...current, policy }, policy);
  }

  proposals(): Promise<ProposalListReport> {
    return this.record("proposals", this.script.proposals ?? fixture("ProposalListReport"));
  }

  approveProposal(commandId: string): Promise<ProposalActionReport> {
    return this.record(
      "approveProposal",
      fixture<ProposalActionReport>("ProposalActionReport"),
      commandId,
    );
  }

  rejectProposal(commandId: string, reason: string): Promise<ProposalActionReport> {
    return this.record("rejectProposal", fixture<ProposalActionReport>("ProposalActionReport"), {
      commandId,
      reason,
    });
  }

  activity(): Promise<ReadonlyArray<ActivityEntry>> {
    return this.record("activity", this.script.activity ?? []);
  }

  settings(): Promise<DesktopSettings> {
    return this.record("settings", this.settingsState);
  }

  updateSettings(patch: Partial<DesktopSettings>): Promise<DesktopSettings> {
    this.settingsState = { ...this.settingsState, ...patch };
    return this.record("updateSettings", this.settingsState, patch);
  }

  subscribe(listener: DesktopEventListener): Unsubscribe {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  private snapshotValue(): ProjectSnapshotReport {
    const snapshot =
      this.script.snapshot ?? fixture<ProjectSnapshotReport>("ProjectSnapshotReport");
    return { ...snapshot, canonical_path: this.openPath ?? snapshot.canonical_path ?? null };
  }
}
