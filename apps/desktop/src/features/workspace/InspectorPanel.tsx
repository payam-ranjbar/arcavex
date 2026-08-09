/** What the engine says about the selected layer. Read-only in Phase 1, and honest about it. */

import type { ReactNode } from "react";

import type { LayerNodeReport, LayerTreeReport } from "../../contracts/index.ts";

export interface InspectorPanelProps {
  readonly tree: LayerTreeReport | undefined;
  readonly selectedAuthoredId: string | null;
}

function findLayer(node: LayerNodeReport, authoredId: string): LayerNodeReport | null {
  if (node.authored_id === authoredId) return node;
  for (const child of node.children ?? []) {
    const found = findLayer(child, authoredId);
    if (found) return found;
  }
  return null;
}

/** Points, to two decimals, because that is the unit the engine lays out in. */
function pt(value: number): string {
  return `${value.toFixed(2)} pt`;
}

export function InspectorPanel({ tree, selectedAuthoredId }: InspectorPanelProps): ReactNode {
  if (selectedAuthoredId === null) {
    return <p role="note">Select a layer on the canvas or in the tree.</p>;
  }
  const layer = tree?.root ? findLayer(tree.root, selectedAuthoredId) : null;
  if (!layer) {
    return <p role="note">That layer is not in the current tree.</p>;
  }

  return (
    <dl className="inspector">
      <dt>Name</dt>
      <dd>{layer.display_name}</dd>

      <dt>Identifier</dt>
      <dd className="measure">{layer.authored_id}</dd>

      <dt>Kind</dt>
      <dd>{layer.kind}</dd>

      {layer.bounds_pt ? (
        <>
          <dt>Position</dt>
          <dd className="measure">
            {pt(layer.bounds_pt[0])}, {pt(layer.bounds_pt[1])}
          </dd>
          <dt>Size</dt>
          <dd className="measure">
            {pt(layer.bounds_pt[2])} × {pt(layer.bounds_pt[3])}
          </dd>
        </>
      ) : null}

      {layer.rotate_deg ? (
        <>
          <dt>Rotation</dt>
          <dd className="measure">{layer.rotate_deg.toFixed(2)}°</dd>
        </>
      ) : null}

      {layer.overflow ? (
        <>
          <dt>Text overflow</dt>
          <dd>
            {layer.overflow.kind} — measured {pt(layer.overflow.measured_w_pt)} ×{" "}
            {pt(layer.overflow.measured_h_pt)} in {pt(layer.overflow.box_w_pt)} ×{" "}
            {pt(layer.overflow.box_h_pt)}
          </dd>
        </>
      ) : null}

      {layer.mask ? (
        <>
          <dt>Mask</dt>
          <dd>{layer.mask.component}</dd>
        </>
      ) : null}

      {(layer.effects ?? []).length > 0 ? (
        <>
          <dt>Effects</dt>
          <dd>
            <ol>
              {(layer.effects ?? []).map((effect) => (
                <li key={effect.index}>
                  {effect.name}
                  {effect.category ? ` · ${effect.category}` : ""}
                </li>
              ))}
            </ol>
          </dd>
        </>
      ) : null}

      {layer.source?.file ? (
        <>
          <dt>Defined in</dt>
          <dd className="measure">
            {layer.source.file}
            {layer.source.line === null || layer.source.line === undefined
              ? ""
              : `:${layer.source.line}`}
          </dd>
        </>
      ) : null}
    </dl>
  );
}
