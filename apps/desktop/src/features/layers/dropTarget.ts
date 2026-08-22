/**
 * Where a dragged layer row would land, and what that means to the engine.
 *
 * This module exists for one reason: the panel shows **topmost paint order first**, and the
 * engine's `reorder` takes an index into the parent's **authored child list**, which runs the
 * other way. Every "drop above this row" therefore has to be converted, and doing that inline in
 * a component is how a layers panel ends up moving things the wrong direction on some code path
 * nobody tested.
 *
 * The rules a drop must satisfy, all enforced here rather than discovered by the engine:
 *
 * - A layer cannot be dropped into itself or into its own descendants — that detaches the subtree.
 * - Only a group can receive children.
 * - A locked layer does not move, and a locked destination does not receive.
 * - Dropping a layer exactly where it already sits is not an edit, and must produce no command.
 */

import type { EditorCommand } from "../workspace/index.ts";
import type { LayerRow } from "./layerTree.ts";

/** Where the pointer sits relative to the row it is over. */
export type DropPosition = "above" | "below" | "inside";

export interface DropTarget {
  readonly row: LayerRow;
  readonly position: DropPosition;
}

export interface DropContext {
  /** Rows as displayed: topmost paint order first. */
  readonly rows: ReadonlyArray<LayerRow>;
  readonly dragged: LayerRow;
  readonly target: DropTarget;
}

export type DropRejection =
  "into-self" | "into-descendant" | "not-a-group" | "locked" | "no-change";

export type DropResult =
  | { readonly ok: true; readonly command: EditorCommand }
  | { readonly ok: false; readonly reason: DropRejection };

export const REJECTION_MESSAGE: Record<DropRejection, string> = {
  "into-self": "A layer cannot be moved inside itself.",
  "into-descendant": "A layer cannot be moved inside one of its own children.",
  "not-a-group": "Only a group can contain other layers.",
  locked: "That layer is locked.",
  "no-change": "The layer is already there.",
};

/** Decide what a drop means, or why it is refused. */
export function resolveDrop(context: DropContext): DropResult {
  const { rows, dragged, target } = context;

  if (target.row.key === dragged.key) return refuse("into-self");
  if (isDescendant(rows, dragged, target.row)) return refuse("into-descendant");
  if (dragged.locked) return refuse("locked");

  const parentId =
    target.position === "inside" ? target.row.authoredId : parentIdOf(rows, target.row);
  if (parentId === null) return refuse("not-a-group");

  if (target.position === "inside" && target.row.kind !== "layer") return refuse("not-a-group");
  // A leaf cannot receive children; only a row the tree reports as having them is a container.
  if (target.position === "inside" && !target.row.hasChildren) return refuse("not-a-group");

  const destination = rows.find((row) => row.authoredId === parentId);
  if (destination?.locked === true) return refuse("locked");

  const siblings = childrenOf(rows, parentId);
  const visualIndex = dropIndexAmongSiblings(siblings, dragged, target);
  if (visualIndex === null) return refuse("no-change");

  // The panel lists topmost first; the engine indexes the authored child list, which paints
  // bottom-up. Converting here keeps that inversion in exactly one place.
  //
  // Within one parent the list keeps its length, so visual position `i` of `n` siblings is
  // authored index `n - 1 - i`. A reparent grows the destination from `m` to `m + 1`, which
  // makes the same position `m - i`.
  const sameParent = removesFromSameParent(siblings, dragged);
  const authoredIndex = sameParent
    ? siblings.length - 1 - visualIndex
    : siblings.length - visualIndex;
  const index = Math.max(0, authoredIndex);

  const movingWithinParent = parentIdOf(rows, dragged) === parentId;
  const command: EditorCommand = movingWithinParent
    ? { kind: "reorder", layer_id: dragged.authoredId, parent_id: parentId, index }
    : { kind: "reparent", layer_id: dragged.authoredId, parent_id: parentId, index };
  return { ok: true, command };
}

// ------------------------------------------------------------------------------------ internals

function refuse(reason: DropRejection): DropResult {
  return { ok: false, reason };
}

function parentIdOf(rows: ReadonlyArray<LayerRow>, row: LayerRow): string | null {
  const at = rows.indexOf(row);
  for (let index = at - 1; index >= 0; index -= 1) {
    const candidate = rows[index];
    if (candidate && candidate.depth === row.depth - 1) return candidate.authoredId;
  }
  return null;
}

function childrenOf(rows: ReadonlyArray<LayerRow>, parentId: string): ReadonlyArray<LayerRow> {
  const parentIndex = rows.findIndex((row) => row.authoredId === parentId);
  if (parentIndex === -1) return [];
  const parent = rows[parentIndex];
  if (!parent) return [];
  const children: LayerRow[] = [];
  for (let index = parentIndex + 1; index < rows.length; index += 1) {
    const row = rows[index];
    if (!row || row.depth <= parent.depth) break;
    if (row.depth === parent.depth + 1) children.push(row);
  }
  return children;
}

function isDescendant(
  rows: ReadonlyArray<LayerRow>,
  ancestor: LayerRow,
  candidate: LayerRow,
): boolean {
  const start = rows.indexOf(ancestor);
  if (start === -1) return false;
  for (let index = start + 1; index < rows.length; index += 1) {
    const row = rows[index];
    if (!row || row.depth <= ancestor.depth) return false;
    if (row.key === candidate.key) return true;
  }
  return false;
}

/** The visual position among siblings the drop implies, or null when it changes nothing. */
function dropIndexAmongSiblings(
  siblings: ReadonlyArray<LayerRow>,
  dragged: LayerRow,
  target: DropTarget,
): number | null {
  if (target.position === "inside") return 0;

  const at = siblings.findIndex((row) => row.key === target.row.key);
  if (at === -1) return 0;
  const desired = target.position === "above" ? at : at + 1;
  const current = siblings.findIndex((row) => row.key === dragged.key);
  if (current !== -1 && (desired === current || desired === current + 1)) return null;
  return desired;
}

function removesFromSameParent(siblings: ReadonlyArray<LayerRow>, dragged: LayerRow): boolean {
  return siblings.some((row) => row.key === dragged.key);
}
