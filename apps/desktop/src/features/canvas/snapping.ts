/**
 * Where a dragged selection wants to line up.
 *
 * Guides come from the geometry the engine already reported — the canvas edges and centre, and
 * every other layer's bounds — so snapping never invents alignment the document does not have.
 * The caller decides which layers contribute; excluding the ones being dragged is what stops a
 * selection from snapping to itself.
 */

import type { Guides } from "./interactionMachine.ts";
import type { RectPt, Size } from "./selection.ts";

/** Canvas edges and centre lines: the alignments every design has whether or not it uses them. */
export function canvasGuides(canvas: Size): Guides {
  return {
    x: [0, canvas.widthPt / 2, canvas.widthPt],
    y: [0, canvas.heightPt / 2, canvas.heightPt],
  };
}

/** Every edge and centre of the given rectangles, as snap candidates. */
export function guidesFromRects(rects: ReadonlyArray<RectPt>): Guides {
  const x: number[] = [];
  const y: number[] = [];
  for (const [left, top, width, height] of rects) {
    x.push(left, left + width / 2, left + width);
    y.push(top, top + height / 2, top + height);
  }
  return { x: unique(x), y: unique(y) };
}

export function mergeGuides(...groups: ReadonlyArray<Guides>): Guides {
  return {
    x: unique(groups.flatMap((group) => [...group.x])),
    y: unique(groups.flatMap((group) => [...group.y])),
  };
}

function unique(values: ReadonlyArray<number>): ReadonlyArray<number> {
  return [...new Set(values.map((value) => Math.round(value * 100) / 100))].sort((a, b) => a - b);
}
