/**
 * Turn the engine's layer tree into the rows a panel draws.
 *
 * The engine owns the hierarchy. This flattens it for display and applies one presentation
 * rule the engine deliberately does not: siblings are shown highest-painted first, because that
 * is what "on top" means to anyone who has used a layers panel.
 */

import type { LayerNodeReport, LayerTreeReport } from "../../contracts/index.ts";

export type LayerRowKind = "layer" | "mask" | "effect";

export interface LayerRow {
  /** Unique within one flattening; subrows derive theirs from the layer they belong to. */
  readonly key: string;
  readonly kind: LayerRowKind;
  readonly authoredId: string;
  readonly instanceId: string | null;
  readonly displayName: string;
  readonly depth: number;
  readonly visible: boolean;
  readonly locked: boolean;
  readonly editable: boolean;
  readonly hitTestable: boolean;
  readonly color: string | null;
  /** `repeat` and `if` rows came from a construct, not from an authored layer of their own. */
  readonly origin: LayerNodeReport["origin"];
  readonly hasChildren: boolean;
  readonly expandable: boolean;
}

export interface FlattenOptions {
  /** Keys of expanded rows. A row not listed is collapsed. */
  readonly expanded: ReadonlySet<string>;
}

/** Highest painted first: the layer drawn last is the one sitting on top. */
function topmostFirst(nodes: ReadonlyArray<LayerNodeReport>): LayerNodeReport[] {
  return [...nodes].sort((left, right) => {
    const leftIndex = left.paint_index ?? left.authored_index;
    const rightIndex = right.paint_index ?? right.authored_index;
    return rightIndex - leftIndex;
  });
}

function subrows(node: LayerNodeReport, depth: number): LayerRow[] {
  const rows: LayerRow[] = [];
  const base = {
    authoredId: node.authored_id,
    instanceId: node.instance_id ?? null,
    depth: depth + 1,
    visible: node.visible ?? true,
    locked: node.locked ?? false,
    editable: false,
    hitTestable: false,
    color: null,
    origin: node.origin ?? "static",
    hasChildren: false,
    expandable: false,
  } as const;

  if (node.mask) {
    rows.push({ ...base, key: `${node.id}::mask`, kind: "mask", displayName: node.mask.component });
  }
  for (const effect of node.effects ?? []) {
    rows.push({
      ...base,
      key: `${node.id}::effect:${effect.index}`,
      kind: "effect",
      displayName: effect.name,
    });
  }
  return rows;
}

/** Flatten the tree into display order, honouring which rows the user has expanded. */
export function flattenLayerTree(
  report: LayerTreeReport,
  options: FlattenOptions,
): ReadonlyArray<LayerRow> {
  const rows: LayerRow[] = [];

  const walk = (node: LayerNodeReport, depth: number): void => {
    const children = node.children ?? [];
    const own = subrows(node, depth);
    const expandable = children.length > 0 || own.length > 0;
    rows.push({
      key: node.id,
      kind: "layer",
      authoredId: node.authored_id,
      instanceId: node.instance_id ?? null,
      displayName: node.display_name,
      depth,
      visible: node.visible ?? true,
      locked: node.locked ?? false,
      editable: node.editable ?? true,
      hitTestable: node.hit_testable ?? true,
      color: node.color ?? null,
      origin: node.origin ?? "static",
      hasChildren: children.length > 0,
      expandable,
    });

    if (!expandable || !options.expanded.has(node.id)) return;
    rows.push(...own);
    for (const child of topmostFirst(children)) walk(child, depth + 1);
  };

  if (report.root) walk(report.root, 0);
  return rows;
}

/** Every key from the root down, for an expand-all default on a freshly opened project. */
export function allExpandableKeys(report: LayerTreeReport): Set<string> {
  const keys = new Set<string>();
  const walk = (node: LayerNodeReport): void => {
    if ((node.children ?? []).length > 0 || node.mask || (node.effects ?? []).length > 0) {
      keys.add(node.id);
    }
    for (const child of node.children ?? []) walk(child);
  };
  if (report.root) walk(report.root);
  return keys;
}

/** The row a keyboard move lands on, or the current one when there is nowhere to go. */
export function moveSelection(
  rows: ReadonlyArray<LayerRow>,
  currentKey: string | null,
  direction: 1 | -1,
): string | null {
  if (rows.length === 0) return null;
  const index = rows.findIndex((row) => row.key === currentKey);
  if (index === -1) return rows[direction === 1 ? 0 : rows.length - 1]!.key;
  const next = index + direction;
  if (next < 0 || next >= rows.length) return currentKey;
  return rows[next]!.key;
}
