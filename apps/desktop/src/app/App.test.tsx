/** The root composes only through the gateway port, including in every failure mode. */

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { FakeArcavexGateway, FAKE_PROJECT_PATH } from "../gateway/index.ts";
import { renderApp } from "../shared/test/renderApp.tsx";
import { App } from "./App.tsx";

describe("App", () => {
  it("offers a way in before a project is open", async () => {
    const gateway = new FakeArcavexGateway();
    gateway.failNext("projectSnapshot", new Error("no project is open"));

    renderApp(<App />, { gateway });

    expect(
      await screen.findByRole("button", { name: "Choose a project folder" }),
    ).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /fixture-poster/u })).toBeInTheDocument();
  });

  it("opens the project the user picked from the folder chooser", async () => {
    const gateway = new FakeArcavexGateway();
    gateway.failNext("projectSnapshot", new Error("no project is open"));
    renderApp(<App />, { gateway });

    await userEvent.click(await screen.findByRole("button", { name: "Choose a project folder" }));

    await waitFor(() => {
      expect(gateway.calls.map((call) => call.method)).toContain("openProject");
    });
    expect(gateway.calls.find((call) => call.method === "openProject")?.argument).toBe(
      FAKE_PROJECT_PATH,
    );
  });

  it("does not open anything when the folder chooser is cancelled", async () => {
    const gateway = new FakeArcavexGateway({ chosenDirectory: null });
    gateway.failNext("projectSnapshot", new Error("no project is open"));
    renderApp(<App />, { gateway });

    await userEvent.click(await screen.findByRole("button", { name: "Choose a project folder" }));

    await waitFor(() => {
      expect(gateway.calls.map((call) => call.method)).toContain("chooseProjectDirectory");
    });
    expect(gateway.calls.map((call) => call.method)).not.toContain("openProject");
  });

  it("shows the bench once a project is open", async () => {
    renderApp(<App />);

    expect(await screen.findByTestId("workbench")).toBeInTheDocument();
    expect(screen.getByRole("main", { name: "Canvas" })).toBeInTheDocument();
  });

  it("says the engine is unreachable rather than pretending the bench is usable", async () => {
    const gateway = new FakeArcavexGateway();
    gateway.failNext("engineState", new Error("sidecar exited"));
    gateway.failNext("projectSnapshot", new Error("no project is open"));

    renderApp(<App />, { gateway });

    expect(await screen.findByRole("alert")).toHaveTextContent("engine could not be reached");
  });

  it("surfaces an incompatible engine on the way in", async () => {
    const gateway = new FakeArcavexGateway({
      engine: {
        status: "incompatible",
        handshake: null,
        message: "Bundled engine reports MCP contract 2024-11-05.",
      },
    });
    gateway.failNext("projectSnapshot", new Error("no project is open"));

    renderApp(<App />, { gateway });

    expect(await screen.findByRole("alert")).toHaveTextContent("2024-11-05");
  });

  it("lets the Definition mode the Layers panel offers actually reach the inspector", async () => {
    // The fixture's layers are instances of a repeated definition, so every inspector field is
    // disabled until the tree is switched to Definition — and the disabled field says exactly
    // that. If the two panels do not share the mode, that instruction cannot be followed and
    // the product tells the user to do something impossible.
    renderApp(<App />, { gateway: new FakeArcavexGateway() });

    await userEvent.click(await screen.findByRole("button", { name: /^Title/ }));
    expect(await screen.findByRole("textbox", { name: "Content" })).toBeDisabled();

    await userEvent.click(screen.getByRole("button", { name: "Definition" }));

    await waitFor(() => {
      expect(screen.getByRole("textbox", { name: "Content" })).toBeEnabled();
    });
  });
});
