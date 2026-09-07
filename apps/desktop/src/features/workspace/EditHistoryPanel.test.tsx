/**
 * The undo surface: what a person can step back, and what happened to the last edit.
 *
 * Two behaviours are worth pinning down. Availability comes from the engine, so a disabled Undo
 * must be disabled because the engine said so rather than because the browser lost count. And a
 * refused edit has to be *visible* — a conflict that only appears in a log is indistinguishable,
 * from the user's chair, from an edit that silently did nothing.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { seriousViolations } from "../../shared/test/axe.ts";
import { EditHistoryPanel } from "./EditHistoryPanel.tsx";
import { EMPTY_HISTORY, type HistoryState } from "./history.ts";
import type { TransactionReport } from "../../contracts/index.ts";

function panel(overrides: Partial<Parameters<typeof EditHistoryPanel>[0]> = {}) {
  const props = {
    history: { ...EMPTY_HISTORY, canUndo: true, canRedo: true } as HistoryState,
    busy: false,
    lastReport: null as TransactionReport | null,
    onUndo: vi.fn(),
    onRedo: vi.fn(),
    ...overrides,
  };
  return { props, ...render(<EditHistoryPanel {...props} />) };
}

describe("EditHistoryPanel", () => {
  it("undoes and redoes through the engine", async () => {
    const user = userEvent.setup();
    const { props } = panel();

    await user.click(screen.getByRole("button", { name: "Undo" }));
    await user.click(screen.getByRole("button", { name: "Redo" }));

    expect(props.onUndo).toHaveBeenCalledOnce();
    expect(props.onRedo).toHaveBeenCalledOnce();
  });

  it("disables what the engine says is unavailable", () => {
    panel({ history: EMPTY_HISTORY });

    expect(screen.getByRole("button", { name: "Undo" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Redo" })).toBeDisabled();
  });

  it("explains a redo that someone else's edit took away", () => {
    panel({ history: { ...EMPTY_HISTORY, canUndo: true, branchedByExternalEdit: true } });

    expect(screen.getByText(/edit from outside this window/i)).toBeVisible();
  });

  it("refuses to submit two edits at once while one is in flight", () => {
    panel({ busy: true });

    expect(screen.getByRole("button", { name: "Undo" })).toBeDisabled();
  });

  it("names the files a conflict was about", () => {
    panel({
      lastReport: {
        ok: false,
        conflict: {
          expected_project_revision: "a".repeat(64),
          actual_project_revision: "b".repeat(64),
          changed: [{ path: "data/event.yaml", change: "modified" }],
        },
      },
    });

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("data/event.yaml");
  });

  it("shows a refusal's diagnostics rather than a generic failure", () => {
    panel({
      lastReport: {
        ok: false,
        diagnostics: [
          {
            code: "ARC-EDT-009",
            severity: "error",
            message: "The project's automation policy is read-only.",
          },
        ],
      },
    });

    expect(screen.getByRole("alert")).toHaveTextContent("read-only");
    expect(screen.getByRole("alert")).toHaveTextContent("ARC-EDT-009");
  });

  it("says nothing at all when the last edit was applied", () => {
    panel({ lastReport: { ok: true } });

    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("binds the platform undo and redo chords", async () => {
    const user = userEvent.setup();
    const { props } = panel();

    await user.keyboard("{Control>}z{/Control}");
    await user.keyboard("{Control>}y{/Control}");

    expect(props.onUndo).toHaveBeenCalledOnce();
    expect(props.onRedo).toHaveBeenCalledOnce();
  });

  it("ignores the chords while typing into a field", async () => {
    const user = userEvent.setup();
    const { props } = panel();
    render(<input aria-label="Headline" />);

    await user.click(screen.getByRole("textbox", { name: "Headline" }));
    await user.keyboard("{Control>}z{/Control}");

    // The field's own undo belongs to the field; stealing it would lose the user's typing.
    expect(props.onUndo).not.toHaveBeenCalled();
  });

  it("has no serious accessibility violations", async () => {
    const { container } = panel({
      lastReport: {
        ok: false,
        diagnostics: [{ code: "ARC-EDT-001", severity: "error", message: "Locked." }],
      },
    });

    expect(await seriousViolations(container)).toEqual([]);
  });
});

describe("EditHistoryPanel reload", () => {
  it("offers the reload its own conflict message tells people to do", async () => {
    // The message read "Reload to see the current version" and the application had no reload
    // control anywhere — an instruction that could not be followed.
    const user = userEvent.setup();
    const onReload = vi.fn();
    render(
      <EditHistoryPanel
        history={EMPTY_HISTORY}
        busy={false}
        lastReport={{
          ok: false,
          conflict: {
            expected_project_revision: "a".repeat(64),
            actual_project_revision: "b".repeat(64),
            changed: [{ path: "template.yaml", change: "modified" }],
          },
        }}
        onUndo={vi.fn()}
        onRedo={vi.fn()}
        onReload={onReload}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Reload" }));

    expect(onReload).toHaveBeenCalledOnce();
  });
});
