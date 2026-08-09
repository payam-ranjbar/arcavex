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
import { useHitTest, useRenderStatus } from "../projects/index.ts";
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
}

export function CanvasViewport({ canvas, selectionBounds, onHit }: CanvasViewportProps): ReactNode {
  const render = useRenderStatus();
  const hitTest = useHitTest();
  const surface = useRef<HTMLDivElement>(null);
  const [viewport, setViewport] = useState<Viewport>({ scale: 1, panXCss: 0, panYCss: 0 });
  const dragging = useRef<{ x: number; y: number } | null>(null);

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

  function onPointerDown(event: PointerEvent<HTMLDivElement>): void {
    // Middle button and space-free drag pans; a plain click asks the engine what is there.
    if (event.button === 1) {
      dragging.current = { x: event.clientX, y: event.clientY };
      event.currentTarget.setPointerCapture(event.pointerId);
    }
  }

  function onPointerMove(event: PointerEvent<HTMLDivElement>): void {
    const origin = dragging.current;
    if (!origin) return;
    setViewport((current) => pan(current, event.clientX - origin.x, event.clientY - origin.y));
    dragging.current = { x: event.clientX, y: event.clientY };
  }

  function onPointerUp(event: PointerEvent<HTMLDivElement>): void {
    if (dragging.current) {
      dragging.current = null;
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
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

        {selection ? (
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
