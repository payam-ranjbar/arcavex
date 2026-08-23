/** Canvas geometry, and the rule that the frontend asks the engine what it clicked. */

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { HitTestReport } from "../../contracts/index.ts";
import { FakeArcavexGateway } from "../../gateway/index.ts";
import { renderApp } from "../../shared/test/renderApp.tsx";
import { CanvasViewport } from "./CanvasViewport.tsx";
import {
  canvasPointFromClient,
  clampScale,
  fitViewport,
  isInsideCanvas,
  MAX_SCALE,
  MIN_SCALE,
  pan,
  rectToCss,
  zoomAt,
} from "./selection.ts";

const A3 = { widthPt: 842, heightPt: 1191 };

describe("fitViewport", () => {
  it("centres the whole canvas at the largest scale that still fits", () => {
    const viewport = fitViewport(A3, { widthCss: 1000, heightCss: 800 }, 0);

    expect(viewport.scale).toBeCloseTo(800 / 1191, 5);
    expect(viewport.panXCss).toBeCloseTo((1000 - 842 * viewport.scale) / 2, 5);
    expect(viewport.panYCss).toBeCloseTo(0, 5);
  });

  it("leaves breathing room around the canvas", () => {
    const padded = fitViewport(A3, { widthCss: 1000, heightCss: 800 }, 40);
    const tight = fitViewport(A3, { widthCss: 1000, heightCss: 800 }, 0);

    expect(padded.scale).toBeLessThan(tight.scale);
  });

  it("survives a canvas with no size rather than dividing by zero", () => {
    expect(fitViewport({ widthPt: 0, heightPt: 0 }, { widthCss: 800, heightCss: 600 })).toEqual({
      scale: 1,
      panXCss: 0,
      panYCss: 0,
    });
  });
});

describe("zoomAt", () => {
  it("keeps the point under the cursor under the cursor", () => {
    const start = { scale: 1, panXCss: 10, panYCss: 20 };
    const anchor = { x: 300, y: 200 };
    const before = canvasPointFromClient(
      { clientX: anchor.x, clientY: anchor.y },
      { left: 0, top: 0 },
      start,
    );

    const zoomed = zoomAt(start, 2.5, anchor);
    const after = canvasPointFromClient(
      { clientX: anchor.x, clientY: anchor.y },
      { left: 0, top: 0 },
      zoomed,
    );

    expect(after.xPt).toBeCloseTo(before.xPt, 6);
    expect(after.yPt).toBeCloseTo(before.yPt, 6);
  });

  it("never zooms past the limits", () => {
    expect(zoomAt({ scale: 1, panXCss: 0, panYCss: 0 }, 1e6, { x: 0, y: 0 }).scale).toBe(MAX_SCALE);
    expect(zoomAt({ scale: 1, panXCss: 0, panYCss: 0 }, 1e-6, { x: 0, y: 0 }).scale).toBe(
      MIN_SCALE,
    );
    expect(clampScale(0)).toBe(MIN_SCALE);
  });
});

describe("canvasPointFromClient", () => {
  it("maps a click to canvas points independently of device pixel ratio", () => {
    // Client coordinates and getBoundingClientRect are both CSS pixels, so a 2x display
    // produces the same canvas point as a 1x one for the same physical spot.
    const viewport = { scale: 2, panXCss: 40, panYCss: 60 };

    const point = canvasPointFromClient(
      { clientX: 240, clientY: 260 },
      { left: 0, top: 0 },
      viewport,
    );

    expect(point).toEqual({ xPt: 100, yPt: 100 });
  });

  it("accounts for where the viewport sits in the window", () => {
    const point = canvasPointFromClient(
      { clientX: 300, clientY: 400 },
      { left: 100, top: 200 },
      { scale: 1, panXCss: 0, panYCss: 0 },
    );

    expect(point).toEqual({ xPt: 200, yPt: 200 });
  });

  it("survives panning", () => {
    const panned = pan({ scale: 1, panXCss: 0, panYCss: 0 }, 25, -15);

    expect(panned).toEqual({ scale: 1, panXCss: 25, panYCss: -15 });
  });
});

describe("rectToCss", () => {
  it("places an engine rectangle where the picture is", () => {
    const box = rectToCss([10, 20, 300, 64], { scale: 2, panXCss: 5, panYCss: 7 });

    expect(box).toEqual({ left: 25, top: 47, width: 600, height: 128 });
  });
});

describe("isInsideCanvas", () => {
  it("rejects a click on the bench beside the proof", () => {
    expect(isInsideCanvas({ xPt: 100, yPt: 100 }, A3)).toBe(true);
    expect(isInsideCanvas({ xPt: -1, yPt: 100 }, A3)).toBe(false);
    expect(isInsideCanvas({ xPt: 100, yPt: 2000 }, A3)).toBe(false);
  });
});

describe("CanvasViewport", () => {
  it("shows the raster the engine produced, not a drawing of its own", async () => {
    renderApp(<CanvasViewport canvas={A3} selectionBounds={null} onHit={() => {}} />);

    const proof = await screen.findByRole("img");
    expect(proof).toHaveAttribute("src", expect.stringContaining("fixture-poster.png"));
    expect(proof).toHaveAccessibleName(expect.stringContaining("1684 by 2382"));
  });

  it("keeps the last good proof visible when the render failed", async () => {
    const lastGood = await new FakeArcavexGateway().renderStatus();

    renderApp(<CanvasViewport canvas={A3} selectionBounds={null} onHit={() => {}} />, {
      script: {
        renderStatus: {
          ...lastGood,
          state: "failed",
          diagnostics: [{ code: "ARC-TPL-001", message: "unknown key", severity: "error" }],
        },
      },
    });

    // The picture stays on screen, dimmed, because it is still the best one there is.
    const proof = await screen.findByRole("img");
    expect(proof).toHaveAttribute("data-state", "failed");
    expect(screen.getByText("Failed")).toBeInTheDocument();
  });

  it("says why the render failed when there is no picture to fall back on", async () => {
    // A first render that fails leaves nothing to dim, and the canvas said "Nothing rendered
    // yet." — reporting absence when it meant failure, with the reason in a panel far below the
    // fold. Someone watching an empty black canvas cannot know an effect name is wrong.
    const lastGood = await new FakeArcavexGateway().renderStatus();

    renderApp(<CanvasViewport canvas={A3} selectionBounds={null} onHit={() => {}} />, {
      script: {
        renderStatus: {
          ...lastGood,
          state: "failed",
          lastGood: null,
          diagnostics: [
            {
              code: "ARC-FX-910",
              message: "Node 'wordmark' references unknown effect 'wow-flutter'",
              severity: "error",
              hint: "Registered effects: blur, grain, halftone.",
            },
          ],
        },
      },
    });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("ARC-FX-910");
    expect(alert).toHaveTextContent("unknown effect 'wow-flutter'");
    expect(alert).toHaveTextContent("Registered effects");
    expect(screen.queryByText("Nothing rendered yet.")).toBeNull();
  });

  it("says what state the proof is in and which revision it represents", async () => {
    renderApp(<CanvasViewport canvas={A3} selectionBounds={null} onHit={() => {}} />);

    expect(await screen.findByText("Current")).toBeInTheDocument();
    expect(screen.getByText("3c3c3c3c3c3c")).toBeInTheDocument();
    expect(screen.getByText("poster-a3")).toBeInTheDocument();
  });

  it("asks the engine what was clicked rather than deciding for itself", async () => {
    const hits: Array<string | null> = [];
    const hitTest = {
      response_version: 1,
      ok: true,
      candidates: [
        {
          id: "title#0",
          authored_id: "title",
          instance_id: "title#0",
          kind: "text",
          display_name: "Title",
          editable: true,
          locked: false,
          bounds_pt: [10, 20, 300, 64],
          paint_bounds_pt: [8, 18, 304, 68],
        },
      ],
    } as unknown as HitTestReport;

    const { gateway } = renderApp(
      <CanvasViewport
        canvas={A3}
        selectionBounds={null}
        onHit={(candidate) => hits.push(candidate?.authored_id ?? null)}
      />,
      { script: { hitTest } },
    );

    await screen.findByRole("img");
    await userEvent.click(screen.getByTestId("canvas-surface"));

    await waitFor(() => expect(hits).toEqual(["title"]));
    expect(gateway.calls.some((call) => call.method === "hitTest")).toBe(true);
  });

  it("draws selection bounds the engine reported", async () => {
    const { container } = renderApp(
      <CanvasViewport canvas={A3} selectionBounds={[10, 20, 300, 64]} onHit={() => {}} />,
    );

    await screen.findByRole("img");
    expect(container.querySelector(".canvas__selection")).toBeInTheDocument();
  });

  it("draws nothing over the canvas when nothing is selected", async () => {
    const { container } = renderApp(
      <CanvasViewport canvas={A3} selectionBounds={null} onHit={() => {}} />,
    );

    await screen.findByRole("img");
    expect(container.querySelector(".canvas__selection")).not.toBeInTheDocument();
  });
});
