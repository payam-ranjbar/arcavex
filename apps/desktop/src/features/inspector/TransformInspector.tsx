/**
 * Position, size, and rotation.
 *
 * The numbers shown are the engine's resolved layout bounds, but the commands sent are semantic:
 * dragging position emits a *relative* translate (the engine composes it onto whatever transform
 * the node already has), while size and rotation are absolute. That split matches how the engine
 * models them — translation accumulates, extents and angle are stated — and keeps a multi-select
 * move meaning "move all of these by the same delta".
 */

import type { ReactNode } from "react";

import { NumberField, round, shared, type FieldValue } from "./fields.tsx";
import type { InspectorSectionProps } from "./TextInspector.tsx";

function bounds(layer: { readonly bounds_pt?: readonly number[] | null }): readonly number[] {
  return layer.bounds_pt ?? [0, 0, 0, 0];
}

function at(layers: InspectorSectionProps["layers"], index: number): FieldValue<number> {
  return shared(layers.map((layer) => round(bounds(layer)[index] ?? 0)));
}

export function TransformInspector({
  layers,
  disabled,
  disabledReason,
  onSubmit,
}: InspectorSectionProps): ReactNode {
  if (layers.length === 0) return null;

  const x = at(layers, 0);
  const y = at(layers, 1);
  const width = at(layers, 2);
  const height = at(layers, 3);
  const rotation = shared(layers.map((layer) => round(layer.rotate_deg ?? 0)));
  const single = layers.length === 1 ? (layers[0] ?? null) : null;

  const moveTo = (axis: 0 | 1, next: number) =>
    onSubmit([
      {
        kind: "translate" as const,
        layer_ids: layers.map((layer) => layer.authored_id),
        // Relative to where the engine says each layer currently sits, so a multi-selection
        // keeps its internal spacing instead of collapsing onto one coordinate.
        dx_pt: axis === 0 ? next - (bounds(layers[0]!)[0] ?? 0) : 0,
        dy_pt: axis === 1 ? next - (bounds(layers[0]!)[1] ?? 0) : 0,
      },
    ]);

  return (
    <section className="inspector__section" aria-labelledby="inspector-transform">
      <h3 className="eyebrow" id="inspector-transform">
        Transform
      </h3>
      <div className="inspector__grid">
        <NumberField
          id="inspector-x"
          label="X"
          suffix="pt"
          value={x}
          disabled={disabled}
          onCommit={(next) => moveTo(0, next)}
        />
        <NumberField
          id="inspector-y"
          label="Y"
          suffix="pt"
          value={y}
          disabled={disabled}
          onCommit={(next) => moveTo(1, next)}
        />
        <NumberField
          id="inspector-width"
          label="Width"
          suffix="pt"
          value={width}
          disabled={disabled || single === null}
          disabledReason={
            single === null && layers.length > 1 ? "Resize one layer at a time." : disabledReason
          }
          onCommit={(next) =>
            single
              ? onSubmit([
                  {
                    kind: "resize" as const,
                    layer_id: single.authored_id,
                    w_pt: next,
                    h_pt: round(bounds(single)[3] ?? 1) || 1,
                  },
                ])
              : undefined
          }
        />
        <NumberField
          id="inspector-height"
          label="Height"
          suffix="pt"
          value={height}
          disabled={disabled || single === null}
          onCommit={(next) =>
            single
              ? onSubmit([
                  {
                    kind: "resize" as const,
                    layer_id: single.authored_id,
                    w_pt: round(bounds(single)[2] ?? 1) || 1,
                    h_pt: next,
                  },
                ])
              : undefined
          }
        />
        <NumberField
          id="inspector-rotation"
          label="Rotation"
          suffix="degrees"
          value={rotation}
          disabled={disabled}
          disabledReason={disabledReason}
          onCommit={(next) =>
            onSubmit(
              layers.map((layer) => ({
                kind: "rotate" as const,
                layer_id: layer.authored_id,
                degrees: next,
              })),
            )
          }
        />
      </div>
    </section>
  );
}
