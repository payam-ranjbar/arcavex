/**
 * Pointer-to-canvas conversion for direct manipulation.
 *
 * `selection.ts` already maps a client point onto the canvas for hit testing. Manipulation needs
 * two more things from the same transform, and both are places a canvas editor commonly goes
 * subtly wrong:
 *
 * - **Deltas, not just points.** Dragging cares about how far the pointer moved in canvas points,
 *   which is the CSS delta divided by scale — never the difference of two independently rounded
 *   points, which drifts as you zoom.
 * - **Device pixel ratio is irrelevant here, and saying so matters.** The overlay is laid out in
 *   CSS pixels, so DPR never enters the arithmetic; the *raster* is a DPR-scaled image the browser
 *   handles. Mixing the two is what makes handles sit slightly off their edges on a 150% display.
 */

import type { Viewport } from "./selection.ts";

export interface PointPt {
  readonly x: number;
  readonly y: number;
}

/** A client-space point in canvas points, for the same viewport hit testing uses. */
export function pointerToCanvas(
  client: { readonly clientX: number; readonly clientY: number },
  rect: { readonly left: number; readonly top: number },
  viewport: Viewport,
): PointPt {
  return {
    x: (client.clientX - rect.left - viewport.panXCss) / viewport.scale,
    y: (client.clientY - rect.top - viewport.panYCss) / viewport.scale,
  };
}

/** A movement in CSS pixels expressed in canvas points. */
export function deltaToCanvas(
  dxCss: number,
  dyCss: number,
  viewport: Viewport,
): { readonly dx: number; readonly dy: number } {
  return { dx: dxCss / viewport.scale, dy: dyCss / viewport.scale };
}

/** A canvas-point length in CSS pixels — how big a handle must be drawn to stay grabbable. */
export function lengthToCss(lengthPt: number, viewport: Viewport): number {
  return lengthPt * viewport.scale;
}

/** A CSS-pixel length in canvas points, so hit tolerances stay constant on screen at any zoom. */
export function lengthToCanvas(lengthCss: number, viewport: Viewport): number {
  return lengthCss / viewport.scale;
}
