/** The viewer as a whole, driven only through the gateway port. */

import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { App } from "../../app/App.tsx";
import { FakeArcavexGateway, FAKE_PROJECT_PATH } from "../../gateway/index.ts";
import { seriousViolations } from "../../shared/test/axe.ts";
import { renderApp } from "../../shared/test/renderApp.tsx";

function closedGateway(): FakeArcavexGateway {
  const gateway = new FakeArcavexGateway();
  gateway.failNext("projectSnapshot", new Error("no project is open"));
  return gateway;
}

describe("the project viewer", () => {
  it("puts the project on the bench once it is opened", async () => {
    renderApp(<App />);

    expect(await screen.findByTestId("workbench")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Layers" })).toBeInTheDocument();
    expect(await screen.findByRole("img")).toHaveAttribute(
      "src",
      expect.stringContaining("fixture-poster.png"),
    );
  });

  it("offers the recent project again after it is closed", async () => {
    const gateway = closedGateway();
    renderApp(<App />, { gateway });

    const recent = await screen.findByRole("button", { name: /fixture-poster/u });
    await userEvent.click(recent);

    await waitFor(() => {
      expect(gateway.calls.find((call) => call.method === "openProject")?.argument).toBe(
        FAKE_PROJECT_PATH,
      );
    });
  });

  it("shows the project's own revisions rather than one merged number", async () => {
    renderApp(<App />);

    const project = await screen.findByText("fixture-project");
    const panel = project.closest(".panel");
    // Project and render revisions move independently; showing one would hide that.
    expect(within(panel as HTMLElement).getByText("9f9f9f9f9f9f")).toBeInTheDocument();
    expect(within(panel as HTMLElement).getByText("3c3c3c3c3c3c")).toBeInTheDocument();
  });

  it("reloads the project when an external editor changes it", async () => {
    const { gateway } = renderApp(<App />);
    await screen.findByTestId("workbench");
    const before = gateway.calls.filter((call) => call.method === "projectSnapshot").length;

    act(() => {
      gateway.emit({
        type: "project",
        snapshot: {
          ok: true,
          response_version: 1,
          name: "fixture-project",
        },
      });
    });

    await waitFor(() => {
      expect(
        gateway.calls.filter((call) => call.method === "projectSnapshot").length,
      ).toBeGreaterThan(before);
    });
  });

  it("labels an external edit as external in the activity log", async () => {
    const { gateway } = renderApp(<App />, {
      script: {
        activity: [
          {
            id: "a1",
            at: 1_767_225_845_000,
            actor: "external",
            summary: "An external editor or AI client changed data.yaml",
            projectRevision: null,
            renderRevision: null,
            diagnostics: [],
          },
        ],
      },
    });
    await screen.findByTestId("workbench");

    const activity = screen.getByRole("region", { name: "Activity" });
    expect(await within(activity).findByText("External")).toBeInTheDocument();
    expect(within(activity).getByText(/changed data\.yaml/u)).toBeInTheDocument();
    expect(gateway.calls.some((call) => call.method === "activity")).toBe(true);
  });

  it("switches the target through the engine rather than re-rendering locally", async () => {
    const { gateway } = renderApp(<App />);
    await screen.findByTestId("workbench");

    await userEvent.selectOptions(screen.getByLabelText("Locale"), "fa-IR");

    await waitFor(() => {
      expect(gateway.calls.find((call) => call.method === "setActiveTarget")?.argument).toEqual({
        format: "poster-a3",
        locale: "fa-IR",
      });
    });
  });

  it("keeps the proof on screen and marked stale while the next one renders", async () => {
    const gateway = new FakeArcavexGateway();
    const current = await gateway.renderStatus();
    renderApp(<App />, { gateway });
    await screen.findByRole("img");

    act(() => {
      gateway.emit({ type: "render", render: { ...current, state: "stale" } });
    });

    expect(await screen.findByText("Stale")).toBeInTheDocument();
    expect(screen.getByRole("img")).toHaveAttribute("data-state", "stale");
  });

  it("asks the engine to render when the command is used", async () => {
    const { gateway } = renderApp(<App />);
    await screen.findByTestId("workbench");

    // The command is enabled because the engine's handshake advertises render.preview.
    await userEvent.click(await screen.findByRole("button", { name: "Render" }));

    await waitFor(() => {
      expect(gateway.calls.some((call) => call.method === "requestRender")).toBe(true);
    });
  });

  it("keeps every mode visible and changeable", async () => {
    const { gateway } = renderApp(<App />);
    await screen.findByTestId("workbench");

    const automation = await screen.findByLabelText("Automation mode");
    expect(automation).toHaveValue("review");

    await userEvent.selectOptions(screen.getByLabelText("Live render mode"), "manual");

    await waitFor(() => {
      expect(gateway.calls.find((call) => call.method === "updateSettings")?.argument).toEqual({
        liveRender: "manual",
      });
    });
  });

  it("approves a queued proposal", async () => {
    const proposals = await new FakeArcavexGateway().proposals();
    const { gateway } = renderApp(<App />, { script: { proposals } });
    await screen.findByTestId("workbench");

    await userEvent.click(await screen.findByRole("button", { name: "Approve" }));

    await waitFor(() => {
      expect(gateway.calls.some((call) => call.method === "approveProposal")).toBe(true);
    });
  });

  it("will not reject a proposal without saying why", async () => {
    const proposals = await new FakeArcavexGateway().proposals();
    const { gateway } = renderApp(<App />, { script: { proposals } });
    await screen.findByTestId("workbench");

    const reject = await screen.findByRole("button", { name: "Reject" });
    expect(reject).toBeDisabled();

    await userEvent.type(screen.getByLabelText("Reason"), "Conflicts with the headline");
    await userEvent.click(reject);

    await waitFor(() => {
      expect(
        gateway.calls.find((call) => call.method === "rejectProposal")?.argument,
      ).toMatchObject({ reason: "Conflicts with the headline" });
    });
  });

  it("has no serious accessibility violations with a project open", async () => {
    const { container } = renderApp(<App />);
    await screen.findByTestId("workbench");

    expect(await seriousViolations(container)).toEqual([]);
  });
});
