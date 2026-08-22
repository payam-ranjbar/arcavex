/**
 * The rendered bitmap, and an overlay that communicates selection without redrawing anything.
 *
 * The raster is visual truth. The SVG on top draws selection bounds the engine reported and
 * nothing else; it is not a second renderer and never invents geometry.
 */

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type MouseEvent,
  type PointerEvent,
  type ReactNode,
  type WheelEvent,
} from "react";

import type { HitCandidate } from "../../contracts/index.ts";
import type { EditorCommand } from "../workspace/index.ts";
import { useHitTest, useRenderStatus } from "../projects/index.ts";
import { pointerToCanvas } from "./coordinates.ts";
import {
  IDLE,
  reduce,
  selectionRect,
  type HandleName,
  type InteractionState,
} from "./interactionMachine.ts";
import { SelectionOverlay } from "./SelectionOverlay.tsx";
import { canvasGuides } from "./snapping.ts";
import {
  canvasPointFromClient,
  fitViewport,
  isInsideCanvas,
  pan,
  rectToCss,
  zoomAt,
  type RectPt,
  type Size,
  type Viewport,
} from "./selection.ts";

import "./canvas.css";

const STATE_LABEL = {
  idle: "No render yet",
  rendering: "Rendering",
  current: "Current",
  stale: "Stale",
  failed: "Failed",
} as const;

export interface CanvasViewportProps {
  /** Canvas size in points, as the engine reported it for the active target. */
  readonly canvas: Size;
  readonly selectionBounds: RectPt | null;
  readonly onHit: (candidate: HitCandidate | null) => void;
  /** Authored ids currently selected, so a drag knows what it is moving. */
  readonly selectedLayerIds?: ReadonlyArray<string>;
  /** Absent leaves the canvas read-only, exactly as Phase 1 behaved. */
  readonly onSubmit?: (commands: ReadonlyArray<EditorCommand>) => void;
  /** False for a locked selection or a read-only project: selectable, not draggable. */
  readonly editable?: boolean;
}

export function CanvasViewport({
  canvas,
  selectionBounds,
  onHit,
  selectedLayerIds = [],
  onSubmit,
  editable = true,
}: CanvasViewportProps): ReactNode {
  const render = useRenderStatus();
  const hitTest = useHitTest();
  const surface = useRef<HTMLDivElement>(null);
  const [viewport, setViewport] = useState<Viewport>({ scale: 1, panXCss: 0, panYCss: 0 });
  const dragging = useRef<{ x: number; y: number } | null>(null);
  const [interaction, setInteraction] = useState<InteractionState>(IDLE);

  const startBox = selectionBounds
    ? {
        x: selectionBounds[0],
        y: selectionBounds[1],
        w: selectionBounds[2],
        h: selectionBounds[3],
      }
    : null;

  /** Feed the machine and submit whatever a completed gesture produced. */
  const dispatch = useCallback(
    (event: Parameters<typeof reduce>[1]): void => {
      setInteraction((current) => {
        const next = reduce(current, event);
        if (next.pending && onSubmit) onSubmit(next.pending);
        return next.pending ? { ...next, pending: null } : next;
      });
    },
    [onSubmit],
  );

  // Escape cancels a gesture in flight; the layer snaps back to the engine's bounds because the
  // local delta was never authoritative in the first place.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent): void {
      if (event.key === "Escape") dispatch({ type: "cancel" });
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [dispatch]);

  const fit = useCallback(() => {
    const element = surface.current;
    if (!element) return;
    const rect = element.getBoundingClientRect();
    setViewport(fitViewport(canvas, { widthCss: rect.width, heightCss: rect.height }));
  }, [canvas]);

  useEffect(fit, [fit]);

  const output = render.data?.lastGood ?? null;
  const state = render.data?.state ?? "idle";

  function onWheel(event: WheelEvent<HTMLDivElement>): void {
    const element = surface.current;
    if (!element) return;
    const rect = element.getBoundingClientRect();
    setViewport((current) =>
      zoomAt(current, event.deltaY < 0 ? 1.1 : 1 / 1.1, {
        x: event.clientX - rect.left,
        y: event.clientY - rect.top,
      }),
    );
  }

  function canvasPoint(event: { clientX: number; clientY: number }) {
    const element = surface.current;
    if (!element) return null;
    return pointerToCanvas(event, element.getBoundingClientRect(), viewport);
  }

  function onPointerDown(event: PointerEvent<HTMLDivElement>): void {
    // Middle button pans; a primary press inside the selection begins a manipulation.
    if (event.button === 1) {
      dragging.current = { x: event.clientX, y: event.clientY };
      event.currentTarget.setPointerCapture(event.pointerId);
      return;
    }
    if (event.button !== 0 || !onSubmit) return;
    const point = canvasPoint(event);
    if (!point) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    dispatch({
      type: "pointer-down",
      pointPt: point,
      target:
        selectedLayerIds.length > 0 && insideBox(point, startBox)
          ? { kind: "layer", layerIds: selectedLayerIds }
          : { kind: "canvas" },
      additive: event.shiftKey,
      selectionBounds: startBox,
      editable,
      guides: canvasGuides(canvas),
    });
  }

  function onPointerMove(event: PointerEvent<HTMLDivElement>): void {
    const origin = dragging.current;
    if (origin) {
      setViewport((current) => pan(current, event.clientX - origin.x, event.clientY - origin.y));
      dragging.current = { x: event.clientX, y: event.clientY };
      return;
    }
    const point = canvasPoint(event);
    if (point) dispatch({ type: "pointer-move", pointPt: point, bypassSnap: event.altKey });
  }

  function onPointerUp(event: PointerEvent<HTMLDivElement>): void {
    if (dragging.current) {
      dragging.current = null;
      event.currentTarget.releasePointerCapture(event.pointerId);
      return;
    }
    const point = canvasPoint(event);
    if (point) dispatch({ type: "pointer-up", pointPt: point });
  }

  function onLostPointerCapture(): void {
    dispatch({ type: "capture-lost" });
  }

  function beginHandle(handle: HandleName, event: PointerEvent<HTMLElement>): void {
    const point = canvasPoint(event);
    if (!point || !onSubmit) return;
    event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    dispatch({
      type: "pointer-down",
      pointPt: point,
      target: { kind: "handle", handle, layerIds: selectedLayerIds },
      additive: false,
      selectionBounds: startBox,
      editable,
      guides: canvasGuides(canvas),
    });
  }

  function beginRotate(event: PointerEvent<HTMLElement>): void {
    const point = canvasPoint(event);
    if (!point || !onSubmit) return;
    event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    dispatch({
      type: "pointer-down",
      pointPt: point,
      target: { kind: "rotate", layerIds: selectedLayerIds },
      additive: false,
      selectionBounds: startBox,
      editable,
      guides: canvasGuides(canvas),
    });
  }

  async function onClick(event: MouseEvent<HTMLDivElement>): Promise<void> {
    const element = surface.current;
    if (!element || event.button !== 0) return;
    const rect = element.getBoundingClientRect();
    const point = canvasPointFromClient(event, rect, viewport);
    if (!isInsideCanvas(point, canvas)) {
      onHit(null);
      return;
    }
    // Geometry lives in the engine; the frontend asks rather than guessing from a scene model.
    const report = await hitTest.mutateAsync(point);
    onHit(report.candidates?.[0] ?? null);
  }

  const selection = selectionBounds ? rectToCss(selectionBounds, viewport) : null;

  return (
    <>
      <div
        ref={surface}
        className="canvas"
        data-testid="canvas-surface"
        role="application"
        aria-label="Canvas"
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onLostPointerCapture={onLostPointerCapture}
        onClick={(event) => void onClick(event)}
      >
        {output ? (
          <img
            className="canvas__proof"
            src={output.imageUrl}
            alt={`Rendered proof, ${output.widthPx} by ${output.heightPx} pixels`}
            data-state={state}
            style={{
              left: `${viewport.panXCss}px`,
              top: `${viewport.panYCss}px`,
              width: `${canvas.widthPt * viewport.scale}px`,
              height: `${canvas.heightPt * viewport.scale}px`,
            }}
          />
        ) : (
          <p className="canvas__empty">
            {state === "rendering" ? "Rendering the first proof…" : "Nothing rendered yet."}
          </p>
        )}

        {onSubmit ? (
          <SelectionOverlay
            box={selectionRect(interaction) ?? startBox}
            viewport={viewport}
            marquee={interaction.mode === "marquee" ? selectionRect(interaction) : null}
            editable={editable}
            onHandlePointerDown={beginHandle}
            onRotatePointerDown={beginRotate}
          />
        ) : selection ? (
          <svg className="canvas__overlay" aria-hidden="true">
            <rect
              x={selection.left}
              y={selection.top}
              width={selection.width}
              height={selection.height}
              className="canvas__selection"
            />
          </svg>
        ) : null}

        <div className="registration" data-state={state} aria-hidden="true" />
      </div>

      <div className="proof-strip" data-state={state}>
        <span className="proof-strip__state">{STATE_LABEL[state]}</span>
        {render.data?.key ? (
          <>
            <span>{render.data.key.format ?? "default format"}</span>
            <span>{render.data.key.locale ?? "no locale"}</span>
            <span title={render.data.key.renderRevision}>
              {render.data.key.renderRevision.slice(0, 12) || "no revision"}
            </span>
          </>
        ) : null}
        {output?.renderMs === null || output?.renderMs === undefined ? null : (
          <span>{output.renderMs} ms</span>
        )}
        <button type="button" onClick={fit} className="proof-strip__fit">
          Fit
        </button>
        <span className="proof-strip__zoom">{Math.round(viewport.scale * 100)}%</span>
      </div>
    </>
  );
}

/** Whether a canvas point falls inside the current selection box. */
function insideBox(
  point: { readonly x: number; readonly y: number },
  box: { readonly x: number; readonly y: number; readonly w: number; readonly h: number } | null,
): boolean {
  if (!box) return false;
  return (
    point.x >= box.x && point.x <= box.x + box.w && point.y >= box.y && point.y <= box.y + box.h
  );
}
