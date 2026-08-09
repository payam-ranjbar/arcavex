/**
 * Canvas geometry: how a point on screen becomes a point the engine can hit-test.
 *
 * The rendered bitmap is the truth. This maps between it and the pointer, and nothing here
 * models the scene — the frontend never learns what a layer looks like, only where it is.
 */

export interface Size {
  readonly widthPt: number;
  readonly heightPt: number;
}

export interface Viewport {
  /** CSS pixels per canvas point. */
  readonly scale: number;
  /** Where the canvas origin sits inside the viewport, in CSS pixels. */
  readonly panXCss: number;
  readonly panYCss: number;
}

export interface ViewportBox {
  readonly widthCss: number;
  readonly heightCss: number;
}

export type RectPt = readonly [number, number, number, number];

export const MIN_SCALE = 0.02;
export const MAX_SCALE = 32;
/** Breathing room around a fitted canvas, in CSS pixels. */
export const FIT_PADDING = 24;

export function clampScale(scale: number): number {
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, scale));
}

/** Centre the whole canvas in the viewport at the largest scale that still fits. */
export function fitViewport(canvas: Size, box: ViewportBox, padding = FIT_PADDING): Viewport {
  const available = {
    width: Math.max(1, box.widthCss - padding * 2),
    height: Math.max(1, box.heightCss - padding * 2),
  };
  if (canvas.widthPt <= 0 || canvas.heightPt <= 0) {
    return { scale: 1, panXCss: 0, panYCss: 0 };
  }
  const scale = clampScale(
    Math.min(available.width / canvas.widthPt, available.height / canvas.heightPt),
  );
  return {
    scale,
    panXCss: (box.widthCss - canvas.widthPt * scale) / 2,
    panYCss: (box.heightCss - canvas.heightPt * scale) / 2,
  };
}

/**
 * Zoom about a fixed point on screen, so what is under the cursor stays under the cursor.
 *
 * Zooming about the viewport centre instead would slide the detail being inspected away, which
 * is the single most irritating thing a canvas can do.
 */
export function zoomAt(
  viewport: Viewport,
  factor: number,
  anchorCss: { readonly x: number; readonly y: number },
): Viewport {
  const scale = clampScale(viewport.scale * factor);
  const applied = scale / viewport.scale;
  return {
    scale,
    panXCss: anchorCss.x - (anchorCss.x - viewport.panXCss) * applied,
    panYCss: anchorCss.y - (anchorCss.y - viewport.panYCss) * applied,
  };
}

export function pan(viewport: Viewport, deltaXCss: number, deltaYCss: number): Viewport {
  return {
    scale: viewport.scale,
    panXCss: viewport.panXCss + deltaXCss,
    panYCss: viewport.panYCss + deltaYCss,
  };
}

/**
 * Convert a pointer position into canvas points.
 *
 * Client coordinates and `getBoundingClientRect` are both in CSS pixels, so device pixel ratio
 * never enters this calculation: a hit test is identical on a 1x and a 2x display.
 */
export function canvasPointFromClient(
  client: { readonly clientX: number; readonly clientY: number },
  rect: { readonly left: number; readonly top: number },
  viewport: Viewport,
): { readonly xPt: number; readonly yPt: number } {
  return {
    xPt: (client.clientX - rect.left - viewport.panXCss) / viewport.scale,
    yPt: (client.clientY - rect.top - viewport.panYCss) / viewport.scale,
  };
}

/** Place an engine-reported rectangle on screen, in CSS pixels. */
export function rectToCss(
  rect: RectPt,
  viewport: Viewport,
): {
  readonly left: number;
  readonly top: number;
  readonly width: number;
  readonly height: number;
} {
  const [x, y, width, height] = rect;
  return {
    left: x * viewport.scale + viewport.panXCss,
    top: y * viewport.scale + viewport.panYCss,
    width: width * viewport.scale,
    height: height * viewport.scale,
  };
}

/** Whether a point in canvas points falls inside the canvas at all. */
export function isInsideCanvas(
  point: { readonly xPt: number; readonly yPt: number },
  canvas: Size,
): boolean {
  return (
    point.xPt >= 0 && point.yPt >= 0 && point.xPt <= canvas.widthPt && point.yPt <= canvas.heightPt
  );
}
