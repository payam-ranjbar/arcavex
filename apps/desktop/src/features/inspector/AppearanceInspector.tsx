/** Visibility and the human-facing name — the two non-geometric properties every layer has. */

import type { ReactNode } from "react";

import { MIXED, TextField, ToggleField, shared } from "./fields.tsx";
import type { InspectorSectionProps } from "./TextInspector.tsx";

export function AppearanceInspector({
  layers,
  disabled,
  disabledReason,
  onSubmit,
}: InspectorSectionProps): ReactNode {
  if (layers.length === 0) return null;

  const visible = shared(layers.map((layer) => layer.visible !== false));
  const displayName = shared(layers.map((layer) => layer.display_name));
  const single = layers.length === 1 ? (layers[0] ?? null) : null;

  return (
    <section className="inspector__section" aria-labelledby="inspector-appearance">
      <h3 className="eyebrow" id="inspector-appearance">
        Appearance
      </h3>
      <ToggleField
        id="inspector-visible"
        label="Visible"
        value={visible}
        disabled={disabled}
        disabledReason={disabledReason}
        onCommit={(next) =>
          onSubmit(
            layers.map((layer) => ({
              kind: "set_visibility" as const,
              layer_id: layer.authored_id,
              visible: next,
            })),
          )
        }
      />
      <TextField
        id="inspector-display-name"
        label="Name"
        value={single ? displayName : MIXED}
        disabled={disabled || single === null}
        disabledReason={
          single === null && layers.length > 1 ? "Rename one layer at a time." : disabledReason
        }
        onCommit={(next) =>
          single
            ? onSubmit([
                {
                  kind: "set_display_name" as const,
                  layer_id: single.authored_id,
                  // An empty box means "no custom name", which is a removal, not the empty string.
                  display_name: next.trim() === "" ? null : next,
                },
              ])
            : undefined
        }
      />
      {single ? (
        <p className="inspector__hint">
          Renaming is display-only. The identifier{" "}
          <span className="measure">{single.authored_id}</span> is what anchors, patches, and AI
          references use, and it does not change.
        </p>
      ) : null}
    </section>
  );
}
