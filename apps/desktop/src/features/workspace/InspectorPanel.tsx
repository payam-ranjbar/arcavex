/**
 * What the engine says about the selected layer, and — when editing is wired — what a person may
 * change about it.
 *
 * The measurements stay: resolved bounds, overflow, and the file the layer is defined in are what
 * make a render explicable, and no editable field replaces them. Editing is additive and optional,
 * so a caller that passes no `onSubmit` still gets exactly the Phase 1 read-only panel.
 */

import type { ReactNode } from "react";

import type { LayerNodeReport, LayerTreeReport } from "../../contracts/index.ts";
import type { AutomationMode, LayerTreeMode } from "../../gateway/index.ts";
import { InspectorRegistrySections, editability } from "../inspector/index.ts";
import type { EditorCommand } from "./commands.ts";

export interface InspectorPanelProps {
  readonly tree: LayerTreeReport | undefined;
  readonly selectedAuthoredId: string | null;
  /** Provided once editing is wired; absent leaves the panel read-only. */
  readonly onSubmit?: (commands: ReadonlyArray<EditorCommand>) => void;
  readonly automation?: AutomationMode;
  readonly treeMode?: LayerTreeMode;
  /** True while a transaction is in flight, so fields cannot queue conflicting edits. */
  readonly busy?: boolean;
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

export function InspectorPanel({
  tree,
  selectedAuthoredId,
  onSubmit,
  automation = "unrestricted",
  treeMode = "rendered",
  busy = false,
}: InspectorPanelProps): ReactNode {
  if (selectedAuthoredId === null) {
    return <p role="note">Select a layer on the canvas or in the tree.</p>;
  }
  const layer = tree?.root ? findLayer(tree.root, selectedAuthoredId) : null;
  if (!layer) {
    return <p role="note">That layer is not in the current tree.</p>;
  }

  const decision = editability({
    layer,
    locked: layer.locked === true,
    automation,
    treeMode,
  });

  return (
    <>
      {onSubmit ? (
        <InspectorRegistrySections
          layers={[layer]}
          disabled={!decision.editable || busy}
          disabledReason={decision.explanation}
          onSubmit={onSubmit}
        />
      ) : null}
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
    </>
  );
}
