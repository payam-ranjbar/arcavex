/**
 * The pointer state machine: what a gesture means, decided without a DOM.
 *
 * Direct manipulation is where an editor is most likely to lie to the user — a drag that submits
 * twice, a resize that flips inside out, an escape that leaves the layer half-moved. Keeping the
 * whole decision in a pure reducer means every one of those can be tested as a sequence of
 * events rather than a screenshot.
 */

import { describe, expect, it } from "vitest";

import {
  IDLE,
  handleFor,
  reduce,
  selectionRect,
  type InteractionState,
} from "./interactionMachine.ts";

const BOX = { x: 100, y: 100, w: 200, h: 100 } as const;

function afterPress(overrides: Partial<Parameters<typeof reduce>[1]> = {}): InteractionState {
  return reduce(IDLE, {
    type: "pointer-down",
    pointPt: { x: 150, y: 150 },
    target: { kind: "layer", layerIds: ["title"] },
    additive: false,
    selectionBounds: BOX,
    ...overrides,
  } as Parameters<typeof reduce>[1]);
}

describe("selection", () => {
  it("selects the layer under a click", () => {
    const state = reduce(IDLE, {
      type: "pointer-up",
      pointPt: { x: 150, y: 150 },
      target: { kind: "layer", layerIds: ["title"] },
      additive: false,
    });

    expect(state.selection).toEqual(["title"]);
    expect(state.mode).toBe("idle");
  });

  it("replaces the selection on a plain click and extends it with shift", () => {
    const first = reduce(IDLE, {
      type: "pointer-up",
      pointPt: { x: 1, y: 1 },
      target: { kind: "layer", layerIds: ["title"] },
      additive: false,
    });
    const added = reduce(first, {
      type: "pointer-up",
      pointPt: { x: 2, y: 2 },
      target: { kind: "layer", layerIds: ["badge"] },
      additive: true,
    });
    const replaced = reduce(added, {
      type: "pointer-up",
      pointPt: { x: 3, y: 3 },
      target: { kind: "layer", layerIds: ["logo"] },
      additive: false,
    });

    expect(added.selection).toEqual(["title", "badge"]);
    expect(replaced.selection).toEqual(["logo"]);
  });

  it("toggles a already-selected layer out with shift", () => {
    const both = reduce(
      reduce(IDLE, {
        type: "pointer-up",
        pointPt: { x: 1, y: 1 },
        target: { kind: "layer", layerIds: ["title"] },
        additive: false,
      }),
      {
        type: "pointer-up",
        pointPt: { x: 2, y: 2 },
        target: { kind: "layer", layerIds: ["badge"] },
        additive: true,
      },
    );

    const removed = reduce(both, {
      type: "pointer-up",
      pointPt: { x: 2, y: 2 },
      target: { kind: "layer", layerIds: ["badge"] },
      additive: true,
    });

    expect(removed.selection).toEqual(["title"]);
  });

  it("clears the selection when the canvas background is clicked", () => {
    const selected = reduce(IDLE, {
      type: "pointer-up",
      pointPt: { x: 1, y: 1 },
      target: { kind: "layer", layerIds: ["title"] },
      additive: false,
    });

    const cleared = reduce(selected, {
      type: "pointer-up",
      pointPt: { x: 5, y: 5 },
      target: { kind: "canvas" },
      additive: false,
    });

    expect(cleared.selection).toEqual([]);
  });
});

describe("marquee", () => {
  it("becomes a marquee once the pointer moves past the click threshold on the background", () => {
    const pressed = afterPress({ target: { kind: "canvas" } });
    const moved = reduce(pressed, { type: "pointer-move", pointPt: { x: 220, y: 200 } });

    expect(moved.mode).toBe("marquee");
    expect(selectionRect(moved)).toEqual({ x: 150, y: 150, w: 70, h: 50 });
  });

  it("normalizes a marquee dragged up and to the left", () => {
    const pressed = afterPress({ target: { kind: "canvas" } });
    const moved = reduce(pressed, { type: "pointer-move", pointPt: { x: 100, y: 100 } });

    expect(selectionRect(moved)).toEqual({ x: 100, y: 100, w: 50, h: 50 });
  });

  it("stays a click when the pointer barely moves", () => {
    const pressed = afterPress({ target: { kind: "canvas" } });
    const nudged = reduce(pressed, { type: "pointer-move", pointPt: { x: 150.5, y: 150.5 } });

    expect(nudged.mode).toBe("pressed");
  });
});

describe("move", () => {
  it("tracks a live delta without submitting", () => {
    const pressed = afterPress();
    const moved = reduce(pressed, { type: "pointer-move", pointPt: { x: 170, y: 140 } });

    expect(moved.mode).toBe("moving");
    expect(moved.delta).toEqual({ dx: 20, dy: -10 });
    expect(moved.pending).toBeNull();
  });

  it("produces exactly one translate on release", () => {
    const moved = reduce(afterPress(), { type: "pointer-move", pointPt: { x: 170, y: 140 } });
    const released = reduce(moved, { type: "pointer-up", pointPt: { x: 170, y: 140 } });

    expect(released.pending).toEqual([
      { kind: "translate", layer_ids: ["title"], dx_pt: 20, dy_pt: -10 },
    ]);
    expect(released.mode).toBe("idle");
    expect(released.delta).toBeNull();
  });

  it("moves every selected layer by the same delta", () => {
    const pressed = reduce(IDLE, {
      type: "pointer-down",
      pointPt: { x: 150, y: 150 },
      target: { kind: "layer", layerIds: ["title", "badge"] },
      additive: false,
      selectionBounds: BOX,
    });
    const released = reduce(
      reduce(pressed, { type: "pointer-move", pointPt: { x: 160, y: 150 } }),
      { type: "pointer-up", pointPt: { x: 160, y: 150 } },
    );

    expect(released.pending).toEqual([
      { kind: "translate", layer_ids: ["title", "badge"], dx_pt: 10, dy_pt: 0 },
    ]);
  });

  it("submits nothing when the pointer returns to where it started", () => {
    const moved = reduce(afterPress(), { type: "pointer-move", pointPt: { x: 170, y: 150 } });
    const back = reduce(moved, { type: "pointer-move", pointPt: { x: 150, y: 150 } });
    const released = reduce(back, { type: "pointer-up", pointPt: { x: 150, y: 150 } });

    expect(released.pending).toBeNull();
  });
});

describe("resize", () => {
  it("offers eight handles around the selection", () => {
    expect(
      ["nw", "n", "ne", "e", "se", "s", "sw", "w"].map((handle) => handleFor(handle, BOX)),
    ).toHaveLength(8);
  });

  it("drags the south-east handle into an absolute resize", () => {
    const pressed = reduce(IDLE, {
      type: "pointer-down",
      pointPt: { x: 300, y: 200 },
      target: { kind: "handle", handle: "se", layerIds: ["photo"] },
      additive: false,
      selectionBounds: BOX,
    });
    const released = reduce(
      reduce(pressed, { type: "pointer-move", pointPt: { x: 340, y: 260 } }),
      { type: "pointer-up", pointPt: { x: 340, y: 260 } },
    );

    expect(released.pending).toEqual([{ kind: "resize", layer_id: "photo", w_pt: 240, h_pt: 160 }]);
  });

  it("drags a west handle without inverting the box", () => {
    const pressed = reduce(IDLE, {
      type: "pointer-down",
      pointPt: { x: 100, y: 150 },
      target: { kind: "handle", handle: "w", layerIds: ["photo"] },
      additive: false,
      selectionBounds: BOX,
    });
    const moved = reduce(pressed, { type: "pointer-move", pointPt: { x: 160, y: 150 } });

    // Width shrinks from the left edge; height is untouched by an east/west handle.
    expect(selectionRect(moved)).toEqual({ x: 160, y: 100, w: 140, h: 100 });
  });

  it("clamps a resize dragged past the opposite edge to a minimum, never negative", () => {
    const pressed = reduce(IDLE, {
      type: "pointer-down",
      pointPt: { x: 300, y: 200 },
      target: { kind: "handle", handle: "se", layerIds: ["photo"] },
      additive: false,
      selectionBounds: BOX,
    });
    const released = reduce(reduce(pressed, { type: "pointer-move", pointPt: { x: 20, y: 20 } }), {
      type: "pointer-up",
      pointPt: { x: 20, y: 20 },
    });

    const [command] = released.pending ?? [];
    expect(command).toMatchObject({ kind: "resize" });
    expect((command as { w_pt: number }).w_pt).toBeGreaterThan(0);
    expect((command as { h_pt: number }).h_pt).toBeGreaterThan(0);
  });
});

describe("rotate", () => {
  it("turns a rotate-handle drag into an absolute angle", () => {
    const pressed = reduce(IDLE, {
      type: "pointer-down",
      pointPt: { x: 200, y: 60 },
      target: { kind: "rotate", layerIds: ["badge"] },
      additive: false,
      selectionBounds: BOX,
    });
    // Straight right of the centre (200,150) is 90° clockwise from straight up.
    const released = reduce(
      reduce(pressed, { type: "pointer-move", pointPt: { x: 400, y: 150 } }),
      { type: "pointer-up", pointPt: { x: 400, y: 150 } },
    );

    expect(released.pending).toEqual([{ kind: "rotate", layer_id: "badge", degrees: 90 }]);
  });
});

describe("cancellation", () => {
  it("abandons a move on Escape without submitting", () => {
    const moved = reduce(afterPress(), { type: "pointer-move", pointPt: { x: 190, y: 150 } });
    const cancelled = reduce(moved, { type: "cancel" });

    expect(cancelled.mode).toBe("idle");
    expect(cancelled.pending).toBeNull();
    expect(cancelled.delta).toBeNull();
    // The selection survives: cancelling a drag is not deselecting.
    expect(cancelled.selection).toEqual(moved.selection);
  });

  it("abandons a gesture when pointer capture is lost", () => {
    const moved = reduce(afterPress(), { type: "pointer-move", pointPt: { x: 190, y: 150 } });
    const lost = reduce(moved, { type: "capture-lost" });

    expect(lost.mode).toBe("idle");
    expect(lost.pending).toBeNull();
  });

  it("ignores a move that arrives with no gesture in progress", () => {
    const state = reduce(IDLE, { type: "pointer-move", pointPt: { x: 10, y: 10 } });

    expect(state).toEqual(IDLE);
  });
});

describe("editability", () => {
  it("does not start a gesture on a locked selection", () => {
    const pressed = reduce(IDLE, {
      type: "pointer-down",
      pointPt: { x: 150, y: 150 },
      target: { kind: "layer", layerIds: ["locked"] },
      additive: false,
      selectionBounds: BOX,
      editable: false,
    });
    const moved = reduce(pressed, { type: "pointer-move", pointPt: { x: 200, y: 200 } });

    expect(moved.mode).not.toBe("moving");
    expect(reduce(moved, { type: "pointer-up", pointPt: { x: 200, y: 200 } }).pending).toBeNull();
  });

  it("still selects a locked layer, because inspecting it is allowed", () => {
    const state = reduce(IDLE, {
      type: "pointer-up",
      pointPt: { x: 150, y: 150 },
      target: { kind: "layer", layerIds: ["locked"] },
      additive: false,
      editable: false,
    });

    expect(state.selection).toEqual(["locked"]);
  });
});

describe("snapping", () => {
  it("snaps a move to a guide within tolerance", () => {
    const pressed = afterPress({ guides: { x: [204], y: [] } });
    const moved = reduce(pressed, { type: "pointer-move", pointPt: { x: 152, y: 150 } });

    // The box's left edge lands on 102 without snapping; the guide at 104 pulls it there.
    expect(selectionRect(moved)?.x).toBe(104);
  });

  it("bypasses snapping while Alt is held", () => {
    const pressed = afterPress({ guides: { x: [204], y: [] } });
    const moved = reduce(pressed, {
      type: "pointer-move",
      pointPt: { x: 152, y: 150 },
      bypassSnap: true,
    });

    expect(selectionRect(moved)?.x).toBe(102);
  });
});
