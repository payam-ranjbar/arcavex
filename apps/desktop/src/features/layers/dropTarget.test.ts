/**
 * Drop resolution: the inversion between what the panel shows and what the engine indexes.
 *
 * The panel lists topmost paint order first; `reorder` takes an index into the authored child
 * list, which runs the other way. Every one of these tests is really the same question asked in
 * a different shape — did the conversion happen, and did it happen exactly once?
 */

import { describe, expect, it } from "vitest";

import { resolveDrop, type DropPosition } from "./dropTarget.ts";
import type { LayerRow } from "./layerTree.ts";

function row(overrides: Partial<LayerRow> & { key: string; depth: number }): LayerRow {
  return {
    kind: "layer",
    authoredId: overrides.key,
    instanceId: null,
    displayName: overrides.key,
    visible: true,
    locked: false,
    editable: true,
    hitTestable: true,
    color: null,
    origin: "static",
    hasChildren: false,
    expandable: false,
    ...overrides,
  };
}

// Displayed topmost-first: root › front (authored 2) › group › title › back (authored 0).
const ROOT = row({ key: "root", depth: 0, kind: "layer", hasChildren: true, expandable: true });
const FRONT = row({ key: "front", depth: 1 });
const GROUP = row({ key: "group", depth: 1, hasChildren: true, expandable: true });
const TITLE = row({ key: "title", depth: 2 });
const BACK = row({ key: "back", depth: 1 });
const ROWS = [ROOT, FRONT, GROUP, TITLE, BACK];

function drop(dragged: LayerRow, target: LayerRow, position: DropPosition) {
  return resolveDrop({ rows: ROWS, dragged, target: { row: target, position } });
}

describe("resolveDrop", () => {
  it("converts a visual position into an authored index", () => {
    // Dropping `back` above `front` means "make it topmost", which is the *last* authored child.
    const result = drop(BACK, FRONT, "above");

    expect(result).toEqual({
      ok: true,
      command: { kind: "reorder", layer_id: "back", parent_id: "root", index: 2 },
    });
  });

  it("dropping below the bottom row means the first authored child", () => {
    const result = drop(FRONT, BACK, "below");

    expect(result.ok).toBe(true);
    expect(result.ok && result.command).toEqual({
      kind: "reorder",
      layer_id: "front",
      parent_id: "root",
      index: 0,
    });
  });

  it("reparents when the destination is a different parent", () => {
    const result = drop(FRONT, TITLE, "above");

    expect(result.ok && result.command.kind).toBe("reparent");
    expect(result.ok && result.command).toMatchObject({ parent_id: "group" });
  });

  it("dropping inside a group puts the layer on top of its children", () => {
    const result = drop(FRONT, GROUP, "inside");

    expect(result.ok && result.command).toMatchObject({
      kind: "reparent",
      parent_id: "group",
      index: 1,
    });
  });

  it("refuses a drop onto the layer itself", () => {
    expect(drop(FRONT, FRONT, "above")).toEqual({ ok: false, reason: "into-self" });
  });

  it("refuses a drop into the layer's own descendant", () => {
    expect(drop(GROUP, TITLE, "inside")).toEqual({ ok: false, reason: "into-descendant" });
  });

  it("refuses a drop inside something that is not a group", () => {
    expect(drop(GROUP, FRONT, "inside")).toEqual({ ok: false, reason: "not-a-group" });
  });

  it("refuses to move a locked layer", () => {
    const locked = row({ key: "front", depth: 1, locked: true });
    const rows = [ROOT, locked, GROUP, TITLE, BACK];

    const result = resolveDrop({
      rows,
      dragged: locked,
      target: { row: BACK, position: "below" },
    });

    expect(result).toEqual({ ok: false, reason: "locked" });
  });

  it("refuses to drop into a locked group", () => {
    const lockedGroup = row({
      key: "group",
      depth: 1,
      locked: true,
      hasChildren: true,
      expandable: true,
    });
    const rows = [ROOT, FRONT, lockedGroup, TITLE, BACK];

    const result = resolveDrop({
      rows,
      dragged: FRONT,
      target: { row: lockedGroup, position: "inside" },
    });

    expect(result).toEqual({ ok: false, reason: "locked" });
  });

  it("emits nothing when the layer is dropped where it already is", () => {
    // `front` is already directly above `group`; dropping it there changes nothing.
    expect(drop(FRONT, GROUP, "above")).toEqual({ ok: false, reason: "no-change" });
    expect(drop(FRONT, FRONT, "below")).toEqual({ ok: false, reason: "into-self" });
  });

  it("never produces a negative index", () => {
    for (const position of ["above", "below", "inside"] as const) {
      for (const target of ROWS) {
        const result = resolveDrop({
          rows: ROWS,
          dragged: BACK,
          target: { row: target, position },
        });
        if (result.ok && "index" in result.command) {
          expect(result.command.index).toBeGreaterThanOrEqual(0);
        }
      }
    }
  });
});
