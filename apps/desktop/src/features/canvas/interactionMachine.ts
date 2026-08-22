/**
 * What a pointer gesture on the canvas means, as a pure reducer.
 *
 * Direct manipulation is where an editor most easily lies to the user: a drag that submits twice,
 * a resize that turns the box inside out, an Escape that leaves a layer half-moved. Keeping the
 * entire decision here — no DOM, no engine, no React — makes each of those a sequence of events a
 * test can state outright.
 *
 * Two rules shape the design:
 *
 * - **Drag geometry is ephemeral.** While the pointer is down the machine tracks a local delta so
 *   the overlay can follow the cursor at frame rate. Nothing is submitted until release, and the
 *   authoritative bounds always come back from the engine afterwards. A rejected edit therefore
 *   snaps back with no extra work: the local delta is simply dropped.
 * - **One gesture, one transaction.** A move that touches five layers emits one `translate` over
 *   five ids, because that is one thing the user did and one thing they expect to undo.
 */

import type { EditorCommand } from "../workspace/index.ts";

export interface PointPt {
  readonly x: number;
  readonly y: number;
}

export interface BoxPt {
  readonly x: number;
  readonly y: number;
  readonly w: number;
  readonly h: number;
}

/** The eight resize handles, named by compass point. */
export type HandleName = "nw" | "n" | "ne" | "e" | "se" | "s" | "sw" | "w";

export type InteractionMode = "idle" | "pressed" | "moving" | "resizing" | "rotating" | "marquee";

export type PointerTarget =
  | { readonly kind: "canvas" }
  | { readonly kind: "layer"; readonly layerIds: ReadonlyArray<string> }
  | {
      readonly kind: "handle";
      readonly handle: HandleName;
      readonly layerIds: ReadonlyArray<string>;
    }
  | { readonly kind: "rotate"; readonly layerIds: ReadonlyArray<string> };

/** Candidate snap lines in canvas points, supplied by the caller. */
export interface Guides {
  readonly x: ReadonlyArray<number>;
  readonly y: ReadonlyArray<number>;
}

export type InteractionEvent =
  | {
      readonly type: "pointer-down";
      readonly pointPt: PointPt;
      readonly target: PointerTarget;
      readonly additive: boolean;
      readonly selectionBounds?: BoxPt | null;
      /** False for a locked layer or a read-only project: selectable, not movable. */
      readonly editable?: boolean;
      readonly guides?: Guides;
    }
  | {
      readonly type: "pointer-move";
      readonly pointPt: PointPt;
      /** Alt bypasses snapping, the convention every design tool shares. */
      readonly bypassSnap?: boolean;
    }
  | {
      readonly type: "pointer-up";
      readonly pointPt: PointPt;
      readonly target?: PointerTarget;
      readonly additive?: boolean;
      readonly editable?: boolean;
    }
  | { readonly type: "cancel" }
  | { readonly type: "capture-lost" };

export interface InteractionState {
  readonly mode: InteractionMode;
  readonly selection: ReadonlyArray<string>;
  /** Live offset while moving, for the overlay only. */
  readonly delta: { readonly dx: number; readonly dy: number } | null;
  /** Commands to submit; set exactly once, on the release that completes a gesture. */
  readonly pending: ReadonlyArray<EditorCommand> | null;
  readonly origin: PointPt | null;
  readonly current: PointPt | null;
  readonly startBounds: BoxPt | null;
  readonly handle: HandleName | null;
  readonly editable: boolean;
  readonly guides: Guides;
}

export const IDLE: InteractionState = {
  mode: "idle",
  selection: [],
  delta: null,
  pending: null,
  origin: null,
  current: null,
  startBounds: null,
  handle: null,
  editable: true,
  guides: { x: [], y: [] },
};

/** Movement below this (in canvas points) is a click, not a drag. */
export const CLICK_SLOP_PT = 2;

/** How close an edge must come to a guide before it snaps, in canvas points. */
export const SNAP_TOLERANCE_PT = 6;

/** Smallest box a resize may produce; zero would make a layer unselectable. */
export const MIN_EXTENT_PT = 1;

export function reduce(state: InteractionState, event: InteractionEvent): InteractionState {
  switch (event.type) {
    case "pointer-down":
      return {
        ...state,
        mode: "pressed",
        origin: event.pointPt,
        current: event.pointPt,
        startBounds: event.selectionBounds ?? null,
        handle: event.target.kind === "handle" ? event.target.handle : null,
        editable: event.editable ?? true,
        guides: event.guides ?? { x: [], y: [] },
        delta: null,
        pending: null,
        // Remember what was pressed so a release with no drag can select it.
        selection: state.selection,
        ...pressTarget(event.target),
      };

    case "pointer-move":
      return move(state, event);

    case "pointer-up":
      return release(state, event);

    case "cancel":
    case "capture-lost":
      // Abandon the gesture; the selection survives, because cancelling a drag is not deselecting.
      return { ...state, mode: "idle", delta: null, pending: null, origin: null, current: null };
  }
}

/** The rectangle the overlay should draw: the live gesture's, or the selection's at rest. */
export function selectionRect(state: InteractionState): BoxPt | null {
  if (state.mode === "marquee" && state.origin && state.current) {
    return normalize(state.origin, state.current);
  }
  if (!state.startBounds) return null;
  if (state.mode === "moving" && state.delta) {
    return {
      ...state.startBounds,
      x: state.startBounds.x + state.delta.dx,
      y: state.startBounds.y + state.delta.dy,
    };
  }
  if (state.mode === "resizing" && state.handle && state.origin && state.current) {
    return resized(state.startBounds, state.handle, state.origin, state.current, state.guides);
  }
  return state.startBounds;
}

/** Where one handle sits, so the overlay and hit-testing agree on its position. */
export function handleFor(handle: string, box: BoxPt): PointPt {
  const midX = box.x + box.w / 2;
  const midY = box.y + box.h / 2;
  const right = box.x + box.w;
  const bottom = box.y + box.h;
  switch (handle) {
    case "nw":
      return { x: box.x, y: box.y };
    case "n":
      return { x: midX, y: box.y };
    case "ne":
      return { x: right, y: box.y };
    case "e":
      return { x: right, y: midY };
    case "se":
      return { x: right, y: bottom };
    case "s":
      return { x: midX, y: bottom };
    case "sw":
      return { x: box.x, y: bottom };
    default:
      return { x: box.x, y: midY };
  }
}

export const HANDLES: ReadonlyArray<HandleName> = ["nw", "n", "ne", "e", "se", "s", "sw", "w"];

// ------------------------------------------------------------------------------------ internals

interface PressTarget {
  readonly pressedIds: ReadonlyArray<string>;
  readonly pressedKind: PointerTarget["kind"];
  readonly pressedAdditive?: boolean;
}

function pressTarget(target: PointerTarget): {
  readonly pressedIds: ReadonlyArray<string>;
  readonly pressedKind: PointerTarget["kind"];
} {
  return {
    pressedIds: target.kind === "canvas" ? [] : target.layerIds,
    pressedKind: target.kind,
  };
}

type StateWithPress = InteractionState & Partial<PressTarget>;

function move(
  state: InteractionState,
  event: Extract<InteractionEvent, { type: "pointer-move" }>,
): InteractionState {
  const pressed = state as StateWithPress;
  if (state.mode === "idle" || !state.origin) return state;

  const dx = event.pointPt.x - state.origin.x;
  const dy = event.pointPt.y - state.origin.y;
  const escalated = state.mode !== "pressed";
  // The slop radius decides whether a press *becomes* a drag. Once it has, tracking continues
  // inside the radius too — otherwise dragging back to the origin would leave the last delta
  // standing and the release would submit a move the user visibly undid.
  const moved = escalated || Math.hypot(dx, dy) >= CLICK_SLOP_PT;
  const next = { ...state, current: event.pointPt };

  if (!moved) return next;

  const kind = pressed.pressedKind ?? "canvas";
  if (kind === "canvas") return { ...next, mode: "marquee" };
  if (!state.editable) return next; // selectable, but not draggable
  if (kind === "handle") return { ...next, mode: "resizing" };
  if (kind === "rotate") return { ...next, mode: "rotating" };

  const snapped = snapDelta(state.startBounds, { dx, dy }, state.guides, event.bypassSnap === true);
  return { ...next, mode: "moving", delta: snapped };
}

function release(
  state: InteractionState,
  event: Extract<InteractionEvent, { type: "pointer-up" }>,
): InteractionState {
  const pressed = state as StateWithPress;

  // A release with no press before it is a plain click: pure selection.
  if (state.mode === "idle" || state.mode === "pressed") {
    const target = event.target ?? targetFromPress(pressed);
    return { ...IDLE, selection: nextSelection(state.selection, target, event.additive === true) };
  }

  if (state.mode === "marquee") {
    // The caller resolves which layers the rectangle covers; the machine only reports the box.
    return { ...state, mode: "idle", origin: state.origin, current: state.current, pending: null };
  }

  const ids = pressed.pressedIds ?? [];
  const commands = completedCommands(state, ids);
  return {
    ...state,
    mode: "idle",
    delta: null,
    pending: commands.length > 0 ? commands : null,
  };
}

function completedCommands(
  state: InteractionState,
  ids: ReadonlyArray<string>,
): ReadonlyArray<EditorCommand> {
  if (ids.length === 0 || !state.startBounds || !state.origin || !state.current) return [];

  if (state.mode === "moving" && state.delta) {
    const { dx, dy } = state.delta;
    if (dx === 0 && dy === 0) return [];
    return [{ kind: "translate", layer_ids: [...ids], dx_pt: dx, dy_pt: dy }];
  }

  if (state.mode === "resizing" && state.handle) {
    const box = resized(state.startBounds, state.handle, state.origin, state.current, state.guides);
    if (box.w === state.startBounds.w && box.h === state.startBounds.h) return [];
    const first = ids[0];
    if (first === undefined) return [];
    return [{ kind: "resize", layer_id: first, w_pt: box.w, h_pt: box.h }];
  }

  if (state.mode === "rotating") {
    const first = ids[0];
    if (first === undefined) return [];
    return [
      { kind: "rotate", layer_id: first, degrees: angleFor(state.startBounds, state.current) },
    ];
  }

  return [];
}

function targetFromPress(state: StateWithPress): PointerTarget {
  const ids = state.pressedIds ?? [];
  if ((state.pressedKind ?? "canvas") === "canvas" || ids.length === 0) return { kind: "canvas" };
  return { kind: "layer", layerIds: ids };
}

function nextSelection(
  selection: ReadonlyArray<string>,
  target: PointerTarget,
  additive: boolean,
): ReadonlyArray<string> {
  if (target.kind === "canvas") return additive ? selection : [];
  const ids = target.layerIds;
  if (!additive) return [...ids];
  const next = [...selection];
  for (const id of ids) {
    const at = next.indexOf(id);
    if (at === -1) next.push(id);
    else next.splice(at, 1);
  }
  return next;
}

function normalize(a: PointPt, b: PointPt): BoxPt {
  return {
    x: Math.min(a.x, b.x),
    y: Math.min(a.y, b.y),
    w: Math.abs(b.x - a.x),
    h: Math.abs(b.y - a.y),
  };
}

/** Resize about the dragged handle, keeping the opposite edge fixed and the box positive. */
function resized(
  start: BoxPt,
  handle: HandleName,
  origin: PointPt,
  current: PointPt,
  guides: Guides,
): BoxPt {
  const dx = current.x - origin.x;
  const dy = current.y - origin.y;
  const west = handle.includes("w");
  const east = handle.includes("e");
  const north = handle.startsWith("n");
  const south = handle.startsWith("s");

  let { x, y, w, h } = start;
  if (east) w = start.w + dx;
  if (west) {
    w = start.w - dx;
    x = start.x + dx;
  }
  if (south) h = start.h + dy;
  if (north) {
    h = start.h - dy;
    y = start.y + dy;
  }

  // Clamp rather than allow a negative box: an inside-out rectangle is not a resize, and a zero
  // extent would leave the layer unselectable.
  if (w < MIN_EXTENT_PT) {
    if (west) x = start.x + start.w - MIN_EXTENT_PT;
    w = MIN_EXTENT_PT;
  }
  if (h < MIN_EXTENT_PT) {
    if (north) y = start.y + start.h - MIN_EXTENT_PT;
    h = MIN_EXTENT_PT;
  }

  void guides;
  return { x, y, w, h };
}

/** Absolute angle in degrees, measured clockwise from straight up about the box centre. */
function angleFor(box: BoxPt, point: PointPt): number {
  const cx = box.x + box.w / 2;
  const cy = box.y + box.h / 2;
  const degrees = (Math.atan2(point.x - cx, cy - point.y) * 180) / Math.PI;
  return Math.round(degrees * 100) / 100;
}

/** Pull a move onto a guide when an edge or centre lands within tolerance. */
function snapDelta(
  start: BoxPt | null,
  delta: { dx: number; dy: number },
  guides: Guides,
  bypass: boolean,
): { dx: number; dy: number } {
  if (bypass || !start) return delta;
  return {
    dx: snapAxis(delta.dx, [start.x, start.x + start.w / 2, start.x + start.w], guides.x),
    dy: snapAxis(delta.dy, [start.y, start.y + start.h / 2, start.y + start.h], guides.y),
  };
}

function snapAxis(
  delta: number,
  edges: ReadonlyArray<number>,
  guides: ReadonlyArray<number>,
): number {
  let best: number | null = null;
  for (const edge of edges) {
    for (const guide of guides) {
      const correction = guide - (edge + delta);
      if (Math.abs(correction) <= SNAP_TOLERANCE_PT) {
        if (best === null || Math.abs(correction) < Math.abs(best)) best = correction;
      }
    }
  }
  return best === null ? delta : delta + best;
}
