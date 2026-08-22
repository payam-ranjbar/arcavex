/**
 * The command bus: every edit the workbench performs goes through here, exactly once.
 *
 * Its job is to compose a transaction the engine will accept — a fresh command id, the actor,
 * and the base revision the user was actually looking at — and then to hand back the
 * authoritative report without ever letting the UI treat its own optimistic state as truth.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

import { FakeArcavexGateway, FAKE_PROJECT_PATH } from "../../gateway/FakeArcavexGateway.ts";
import type { TransactionReport } from "../../contracts/index.ts";
import { CommandBus } from "./commands.ts";

const REVISION = "9f".repeat(32);
const NEXT_REVISION = "3c".repeat(32);

function accepted(overrides: Partial<TransactionReport> = {}): TransactionReport {
  return {
    response_version: 1,
    contract_version: 1,
    ok: true,
    canonical_path: FAKE_PROJECT_PATH,
    project_revision: NEXT_REVISION,
    render_revision: NEXT_REVISION,
    changed: [{ path: "template.yaml", change: "modified" }],
    changed_layer_ids: ["title"],
    diagnostics: [],
    ...overrides,
  };
}

function bus(gateway: FakeArcavexGateway): CommandBus {
  return new CommandBus({
    gateway,
    projectPath: () => FAKE_PROJECT_PATH,
    baseRevision: () => REVISION,
    target: () => ({ format: "poster-a3", locale: "en-US" }),
    actor: { id: "desktop", display_name: "Arcavex Desktop" },
  });
}

describe("CommandBus", () => {
  let gateway: FakeArcavexGateway;

  beforeEach(() => {
    gateway = new FakeArcavexGateway({ transaction: accepted() });
  });

  it("composes a transaction from the state the user was looking at", async () => {
    await bus(gateway).submit([{ kind: "set_text", layer_id: "title", text: "New" }]);

    const call = gateway.calls.find((entry) => entry.method === "editorApply");
    expect(call).toBeDefined();
    const transaction = call?.argument as Record<string, unknown>;
    expect(transaction.project_path).toBe(FAKE_PROJECT_PATH);
    expect(transaction.base_project_revision).toBe(REVISION);
    expect(transaction.actor).toEqual({ id: "desktop", display_name: "Arcavex Desktop" });
    expect(transaction.target).toEqual({ format: "poster-a3", locale: "en-US" });
    expect(transaction.commands).toHaveLength(1);
  });

  it("gives every transaction a distinct command id", async () => {
    const commandBus = bus(gateway);
    await commandBus.submit([{ kind: "set_text", layer_id: "title", text: "A" }]);
    await commandBus.submit([{ kind: "set_text", layer_id: "title", text: "B" }]);

    const ids = gateway.calls
      .filter((entry) => entry.method === "editorApply")
      .map((entry) => (entry.argument as Record<string, unknown>).command_id);
    expect(new Set(ids).size).toBe(2);
    expect(ids.every((id) => typeof id === "string" && id.length === 36)).toBe(true);
  });

  it("sends multiple commands as one transaction, because that is one undo step", async () => {
    await bus(gateway).submit([
      { kind: "translate", layer_ids: ["a", "b"], dx_pt: 4, dy_pt: 0 },
      { kind: "set_visibility", layer_id: "c", visible: false },
    ]);

    const applies = gateway.calls.filter((entry) => entry.method === "editorApply");
    expect(applies).toHaveLength(1);
    expect((applies[0]?.argument as { commands: unknown[] }).commands).toHaveLength(2);
  });

  it("reports busy while a command is in flight and idle afterwards", async () => {
    const commandBus = bus(gateway);
    const seen: boolean[] = [];
    commandBus.subscribe((state) => seen.push(state.busy));

    const pending = commandBus.submit([{ kind: "set_text", layer_id: "title", text: "New" }]);
    expect(commandBus.state.busy).toBe(true);
    await pending;

    expect(commandBus.state.busy).toBe(false);
    expect(seen).toContain(true);
    expect(seen.at(-1)).toBe(false);
  });

  it("surfaces a conflict as state rather than throwing", async () => {
    const conflicted = new FakeArcavexGateway({
      transaction: accepted({
        ok: false,
        project_revision: NEXT_REVISION,
        changed: [],
        conflict: {
          expected_project_revision: REVISION,
          actual_project_revision: NEXT_REVISION,
          changed: [{ path: "data/event.yaml", change: "modified" }],
          layer_ids: ["title"],
        },
      }),
    });

    const report = await bus(conflicted).submit([
      { kind: "set_text", layer_id: "title", text: "New" },
    ]);

    expect(report.ok).toBe(false);
    expect(bus(conflicted).state.busy).toBe(false);
    expect(report.conflict?.changed?.[0]?.path).toBe("data/event.yaml");
  });

  it("keeps a transport failure from wedging the bus", async () => {
    gateway.failNext("editorApply", new Error("the sidecar died"));
    const commandBus = bus(gateway);

    const report = await commandBus.submit([{ kind: "set_text", layer_id: "title", text: "New" }]);

    expect(report.ok).toBe(false);
    expect(report.diagnostics?.[0]?.message).toContain("the sidecar died");
    // Retry-safe: the next submit must go through rather than inherit a stuck busy flag.
    expect(commandBus.state.busy).toBe(false);
    const retry = await commandBus.submit([{ kind: "set_text", layer_id: "title", text: "New" }]);
    expect(retry.ok).toBe(true);
  });

  it("refuses to submit when no project is open", async () => {
    const commandBus = new CommandBus({
      gateway,
      projectPath: () => null,
      baseRevision: () => REVISION,
      target: () => ({ format: null, locale: null }),
      actor: { id: "desktop" },
    });

    const report = await commandBus.submit([{ kind: "set_text", layer_id: "title", text: "New" }]);

    expect(report.ok).toBe(false);
    expect(gateway.calls.some((entry) => entry.method === "editorApply")).toBe(false);
  });

  it("refuses to submit without a base revision, rather than guessing one", async () => {
    const commandBus = new CommandBus({
      gateway,
      projectPath: () => FAKE_PROJECT_PATH,
      baseRevision: () => null,
      target: () => ({ format: null, locale: null }),
      actor: { id: "desktop" },
    });

    const report = await commandBus.submit([{ kind: "set_text", layer_id: "title", text: "New" }]);

    expect(report.ok).toBe(false);
    expect(gateway.calls.some((entry) => entry.method === "editorApply")).toBe(false);
  });

  it("notifies subscribers of the last report so panels can render it", async () => {
    const commandBus = bus(gateway);
    const listener = vi.fn();
    commandBus.subscribe(listener);

    await commandBus.submit([{ kind: "set_text", layer_id: "title", text: "New" }]);

    const last = listener.mock.calls.at(-1)?.[0] as { lastReport?: TransactionReport };
    expect(last.lastReport?.ok).toBe(true);
  });

  it("routes undo and redo through the same bus", async () => {
    const commandBus = bus(gateway);

    await commandBus.undo();
    await commandBus.redo();

    expect(gateway.calls.map((entry) => entry.method)).toEqual(
      expect.arrayContaining(["editorUndo", "editorRedo"]),
    );
  });

  it("reports a queued command instead of pretending the edit landed", async () => {
    const queued = new FakeArcavexGateway({
      transaction: accepted({
        changed: [],
        changed_layer_ids: [],
        queued_command_id: "9f2c1d7e-4b3a-4c58-9e21-0d7a6f5b8c34",
      }),
    });

    const report = await bus(queued).submit([{ kind: "set_text", layer_id: "title", text: "New" }]);

    expect(report.ok).toBe(true);
    expect(report.queued_command_id).toBeTruthy();
    expect(report.changed).toEqual([]);
  });
});
