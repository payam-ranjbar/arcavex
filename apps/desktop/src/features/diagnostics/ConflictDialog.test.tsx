/** A conflict has to be legible: what moved, which layers, and what the user can do about it. */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { ConflictDetail } from "../../contracts/index.ts";
import { seriousViolations } from "../../shared/test/axe.ts";
import { ConflictDialog } from "./ConflictDialog.tsx";

const CONFLICT: ConflictDetail = {
  expected_project_revision: "9f".repeat(32),
  actual_project_revision: "3c".repeat(32),
  changed: [
    { path: "data/event.yaml", change: "modified" },
    { path: "overrides/square.patch.yaml", change: "created" },
  ],
  layer_ids: ["title", "subtitle"],
};

function renderDialog(conflict: ConflictDetail = CONFLICT) {
  const handlers = { onReload: vi.fn(), onReapply: vi.fn(), onDismiss: vi.fn() };
  const result = render(<ConflictDialog conflict={conflict} {...handlers} />);
  return { ...result, ...handlers };
}

describe("ConflictDialog", () => {
  it("names every file that changed and how", () => {
    renderDialog();

    expect(screen.getByText("data/event.yaml")).toBeInTheDocument();
    expect(screen.getByText("overrides/square.patch.yaml")).toBeInTheDocument();
    expect(screen.getAllByText(/changed|added/)).not.toHaveLength(0);
  });

  it("names the layers involved", () => {
    renderDialog();

    expect(screen.getByText("title, subtitle")).toBeInTheDocument();
  });

  it("says so plainly when the engine could not determine what changed", () => {
    renderDialog({ ...CONFLICT, changed: [], layer_ids: [] });

    expect(screen.getByText(/could not determine which files changed/i)).toBeInTheDocument();
  });

  it("offers reload and re-apply, and never an overwrite", async () => {
    const { onReload, onReapply } = renderDialog();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: /reload the project/i }));
    await user.click(screen.getByRole("button", { name: /re-apply my edit/i }));

    expect(onReload).toHaveBeenCalledOnce();
    expect(onReapply).toHaveBeenCalledOnce();
    // Forcing the write is precisely the last-write-wins destruction the guard prevents.
    expect(screen.queryByRole("button", { name: /overwrite|force/i })).toBeNull();
  });

  it("reassures the user that nothing of theirs was written", () => {
    renderDialog();

    expect(screen.getByText(/nothing has been changed by you/i)).toBeInTheDocument();
  });

  it("is an accessible alert dialog", async () => {
    const { container } = renderDialog();

    expect(screen.getByRole("alertdialog")).toHaveAccessibleName(
      /the project changed while you were editing/i,
    );
    expect(await seriousViolations(container)).toEqual([]);
  });
});
