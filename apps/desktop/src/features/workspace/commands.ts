/**
 * The one route from a user gesture to a project mutation.
 *
 * Every edit — an inspector field, a canvas drag, a layer reorder — composes commands and hands
 * them here. Centralizing it buys three things the features must not each reinvent:
 *
 * - **One transaction per gesture.** Moving three selected layers is one undo step, so the bus
 *   takes a list of commands and sends exactly one transaction.
 * - **The revision the user was looking at.** The base revision is read at submit time from the
 *   authoritative snapshot, never remembered from an earlier render, so a stale edit is caught
 *   by the engine rather than silently overwriting someone else's work.
 * - **A refusal is a value.** A conflict, a policy refusal, or a dead sidecar all resolve to a
 *   report the workbench can render. The bus never throws at its callers and never leaves the
 *   busy flag stuck, because the next gesture has to work.
 *
 * The bus deliberately holds no document state. The authoritative snapshot, layer tree, and
 * render come back through the gateway's events; treating an optimistic local edit as truth is
 * exactly how a UI and an engine drift apart.
 */

import type {
  Actor,
  Diagnostic,
  HistoryReport,
  SemanticTransaction,
  TransactionReport,
} from "../../contracts/index.ts";
import type { ArcavexGateway, ProjectTarget } from "../../gateway/index.ts";

/** One command in the engine's semantic vocabulary, as the generated union defines it. */
export type EditorCommand = SemanticTransaction["commands"][number];

export interface CommandBusOptions {
  readonly gateway: ArcavexGateway;
  /** The open project's canonical path, or null when nothing is open. */
  readonly projectPath: () => string | null;
  /** The project revision the workbench is currently displaying. */
  readonly baseRevision: () => string | null;
  readonly target: () => ProjectTarget;
  readonly actor: Actor;
}

export interface CommandBusState {
  /** True while a transaction is in flight; the workbench disables conflicting gestures. */
  readonly busy: boolean;
  /** The most recent report, successful or refused, for panels that render outcomes. */
  readonly lastReport: TransactionReport | null;
}

export type CommandBusListener = (state: CommandBusState) => void;

export class CommandBus {
  private readonly options: CommandBusOptions;
  private readonly listeners = new Set<CommandBusListener>();
  private current: CommandBusState = { busy: false, lastReport: null };

  constructor(options: CommandBusOptions) {
    this.options = options;
  }

  get state(): CommandBusState {
    return this.current;
  }

  subscribe(listener: CommandBusListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /** Submit one gesture's commands as a single transaction. */
  async submit(commands: ReadonlyArray<EditorCommand>): Promise<TransactionReport> {
    const projectPath = this.options.projectPath();
    if (projectPath === null) {
      return this.finish(refusal("No project is open, so there is nothing to edit."));
    }
    const baseRevision = this.options.baseRevision();
    if (baseRevision === null) {
      // Guessing a revision would defeat the conflict guard entirely: the engine would accept an
      // edit composed against a document state the user never saw.
      return this.finish(
        refusal("The project revision is not known yet; wait for the project to load."),
      );
    }

    const transaction: SemanticTransaction = {
      version: 1,
      command_id: crypto.randomUUID(),
      project_path: projectPath,
      base_project_revision: baseRevision,
      actor: this.options.actor,
      target: this.options.target(),
      commands: [...commands],
    };

    return this.run(() => this.options.gateway.editorApply(transaction));
  }

  undo(): Promise<TransactionReport> {
    return this.run(() => this.options.gateway.editorUndo());
  }

  redo(): Promise<TransactionReport> {
    return this.run(() => this.options.gateway.editorRedo());
  }

  /** Execute a proposal a person approved in review mode. */
  applyAuthorized(commandId: string): Promise<TransactionReport> {
    return this.run(() => this.options.gateway.editorApplyAuthorized(commandId));
  }

  history(): Promise<HistoryReport> {
    return this.options.gateway.editorHistory();
  }

  private async run(operation: () => Promise<TransactionReport>): Promise<TransactionReport> {
    this.publish({ busy: true, lastReport: this.current.lastReport });
    try {
      return this.finish(await operation());
    } catch (error) {
      // A transport failure is the sidecar dying mid-command, not a bug in the caller. It must
      // land as a readable report and leave the bus usable, because the retry is the whole point.
      return this.finish(refusal(error instanceof Error ? error.message : String(error)));
    }
  }

  private finish(report: TransactionReport): TransactionReport {
    this.publish({ busy: false, lastReport: report });
    return report;
  }

  private publish(state: CommandBusState): void {
    this.current = state;
    for (const listener of this.listeners) listener(state);
  }
}

function refusal(message: string): TransactionReport {
  const diagnostic: Diagnostic = {
    code: "ARC-EDT-010",
    severity: "error",
    message,
  };
  return {
    response_version: 1,
    contract_version: 1,
    ok: false,
    changed: [],
    changed_layer_ids: [],
    diagnostics: [diagnostic],
  };
}
