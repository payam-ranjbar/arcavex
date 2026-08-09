/** The root composes only through the gateway port, including in every failure mode. */

import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FakeArcavexGateway } from "../gateway/index.ts";
import { renderApp } from "../shared/test/renderApp.tsx";
import { App } from "./App.tsx";

describe("App", () => {
  it("reports the engine identity it read through the gateway", async () => {
    const { gateway } = renderApp(<App />);

    expect(await screen.findByTestId("engine-status")).toHaveTextContent("ready");
    expect(gateway.calls.map((call) => call.method)).toContain("engineState");
  });

  it("shows a diagnostic surface instead of a workbench when the engine is unreachable", async () => {
    const gateway = new FakeArcavexGateway();
    gateway.failNext("engineState", new Error("sidecar exited"));

    renderApp(<App />, { gateway });

    expect(await screen.findByRole("alert")).toHaveTextContent("engine could not be reached");
  });

  it("surfaces an incompatible engine without pretending the workbench is usable", async () => {
    renderApp(<App />, {
      script: {
        engine: {
          status: "incompatible",
          handshake: null,
          message: "Bundled engine reports MCP contract 2024-11-05.",
        },
      },
    });

    expect(await screen.findByTestId("engine-status")).toHaveTextContent("incompatible");
    expect(screen.getByRole("alert")).toHaveTextContent("2024-11-05");
  });
});
