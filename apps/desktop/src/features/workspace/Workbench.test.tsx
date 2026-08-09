/** The shell shows what features contribute, and disables what the engine cannot do. */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { createRegistry, type ContributionRegistry } from "../../app/contributions.ts";
import { seriousViolations } from "../../shared/test/axe.ts";
import { setViewportWidth } from "../../shared/test/setup.ts";
import { ThemeProvider } from "../../theme/ThemeProvider.tsx";
import { CapabilityProvider } from "../capabilities/index.ts";
import { Workbench } from "./Workbench.tsx";

function renderWorkbench(registry: ContributionRegistry, capabilities: ReadonlyArray<string> = []) {
  return render(
    <ThemeProvider>
      <CapabilityProvider capabilities={capabilities}>
        <Workbench registry={registry}>
          <p>Canvas</p>
        </Workbench>
      </CapabilityProvider>
    </ThemeProvider>,
  );
}

function populated(): ContributionRegistry {
  const registry = createRegistry();
  registry.addPanel({
    id: "layers",
    title: "Layers",
    region: "sidebar",
    order: 10,
    render: () => <p>Layer tree</p>,
  });
  registry.addPanel({
    id: "properties",
    title: "Properties",
    region: "inspector",
    order: 10,
    render: () => <p>Selected layer</p>,
  });
  registry.addPanel({
    id: "activity",
    title: "Activity",
    region: "activity",
    order: 10,
    render: () => <p>External edits</p>,
  });
  return registry;
}

describe("Workbench", () => {
  it("mounts each contributed panel in the region it asked for", () => {
    renderWorkbench(populated());

    expect(
      within(screen.getByRole("navigation", { name: "Project" })).getByText("Layer tree"),
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole("complementary", { name: "Inspector" })).getByText("Selected layer"),
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole("region", { name: "Activity" })).getByText("External edits"),
    ).toBeInTheDocument();
  });

  it("orders panels by their declared order, then by title", () => {
    const registry = createRegistry();
    registry.addPanel({
      id: "c",
      title: "Assets",
      region: "sidebar",
      order: 20,
      render: () => null,
    });
    registry.addPanel({
      id: "a",
      title: "Variants",
      region: "sidebar",
      order: 10,
      render: () => null,
    });
    registry.addPanel({
      id: "b",
      title: "Layers",
      region: "sidebar",
      order: 10,
      render: () => null,
    });

    renderWorkbench(registry);

    const titles = screen
      .getAllByRole("heading", { level: 2 })
      .map((heading) => heading.textContent);
    expect(titles).toEqual(["Layers", "Variants", "Assets"]);
  });

  it("refuses two contributions with the same id rather than silently replacing one", () => {
    const registry = createRegistry();
    registry.addPanel({ id: "layers", title: "Layers", region: "sidebar", render: () => null });

    expect(() =>
      registry.addPanel({ id: "layers", title: "Other", region: "sidebar", render: () => null }),
    ).toThrow(/already registered/u);
  });

  it("shows only primary commands in the command bar and runs the one clicked", async () => {
    const run = vi.fn();
    const registry = populated();
    registry.addCommand({ id: "render", title: "Render", primary: true, run });
    registry.addCommand({ id: "hidden", title: "Export", run: vi.fn() });

    renderWorkbench(registry);
    const commands = screen.getByRole("navigation", { name: "Commands" });

    expect(within(commands).queryByRole("button", { name: "Export" })).not.toBeInTheDocument();
    await userEvent.click(within(commands).getByRole("button", { name: "Render" }));
    expect(run).toHaveBeenCalledOnce();
  });

  it("disables a command the connected engine cannot perform, and says why", () => {
    const registry = populated();
    registry.addCommand({
      id: "render",
      title: "Render",
      primary: true,
      capability: "project.render",
      run: vi.fn(),
    });

    renderWorkbench(registry, ["project.snapshot"]);

    const button = screen.getByRole("button", { name: "Render" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title", expect.stringContaining("project.render"));
  });

  it("explains a panel the engine cannot support instead of hiding it", () => {
    const registry = createRegistry();
    registry.addPanel({
      id: "layers",
      title: "Layers",
      region: "sidebar",
      capability: "project.layer_tree",
      render: () => <p>Layer tree</p>,
    });

    renderWorkbench(registry, []);

    expect(screen.getByRole("heading", { name: "Layers" })).toBeInTheDocument();
    expect(screen.getByTestId("capability-unavailable")).toHaveTextContent(
      "needs an engine capability",
    );
    expect(screen.queryByText("Layer tree")).not.toBeInTheDocument();
  });

  it("enables everything when the engine reports the capability", () => {
    const registry = createRegistry();
    registry.addPanel({
      id: "layers",
      title: "Layers",
      region: "sidebar",
      capability: "project.layer_tree",
      render: () => <p>Layer tree</p>,
    });

    renderWorkbench(registry, ["project.layer_tree"]);

    expect(screen.getByText("Layer tree")).toBeInTheDocument();
    expect(screen.queryByTestId("capability-unavailable")).not.toBeInTheDocument();
  });

  it("folds the inspector away on a narrow window so the canvas keeps the room", () => {
    setViewportWidth(900);

    renderWorkbench(populated());

    expect(screen.getByTestId("workbench")).toHaveAttribute("data-compact", "true");
    expect(screen.queryByRole("complementary", { name: "Inspector" })).not.toBeInTheDocument();
    expect(screen.getByRole("main", { name: "Canvas" })).toBeInTheDocument();
  });

  it("reaches every region by keyboard in the order they are laid out", async () => {
    const registry = populated();
    registry.addCommand({ id: "render", title: "Render", primary: true, run: vi.fn() });
    registry.addPanel({
      id: "open",
      title: "Project",
      region: "sidebar",
      order: 1,
      render: () => <button type="button">Open project</button>,
    });

    renderWorkbench(registry);

    await userEvent.tab();
    expect(screen.getByRole("button", { name: "Render" })).toHaveFocus();
    await userEvent.tab();
    expect(screen.getByRole("button", { name: "Open project" })).toHaveFocus();
  });

  it("has no serious accessibility violations", async () => {
    const registry = populated();
    registry.addCommand({ id: "render", title: "Render", primary: true, run: vi.fn() });
    const { container } = renderWorkbench(registry);

    expect(await seriousViolations(container)).toEqual([]);
  });
});
