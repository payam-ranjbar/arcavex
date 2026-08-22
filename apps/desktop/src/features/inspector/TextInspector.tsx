/** The text of a text layer: the edit a person reaches for first. */

import type { ReactNode } from "react";

import type { LayerNodeReport } from "../../contracts/index.ts";
import type { EditorCommand } from "../workspace/index.ts";
import { MIXED, TextField, shared, type FieldValue } from "./fields.tsx";

export interface InspectorSectionProps {
  readonly layers: ReadonlyArray<LayerNodeReport>;
  readonly disabled: boolean;
  readonly disabledReason: string | null;
  readonly onSubmit: (commands: ReadonlyArray<EditorCommand>) => void;
}

/** The authored text the engine reported, or mixed across a multi-selection. */
function textValue(layers: ReadonlyArray<LayerNodeReport>): FieldValue<string> {
  const values = layers.map((layer) => layer.text ?? "");
  return shared(values);
}

export function TextInspector({
  layers,
  disabled,
  disabledReason,
  onSubmit,
}: InspectorSectionProps): ReactNode {
  const textLayers = layers.filter((layer) => layer.kind === "text");
  if (textLayers.length === 0) return null;

  const value = textValue(textLayers);

  return (
    <section className="inspector__section" aria-labelledby="inspector-text">
      <h3 className="eyebrow" id="inspector-text">
        Text
      </h3>
      <TextField
        id="inspector-text-value"
        label="Content"
        multiline
        value={value}
        disabled={disabled}
        disabledReason={disabledReason}
        onCommit={(next) =>
          onSubmit(
            textLayers.map((layer) => ({
              kind: "set_text" as const,
              layer_id: layer.authored_id,
              text: next,
            })),
          )
        }
      />
      {value === MIXED ? (
        <p className="inspector__hint">
          The selected layers have different text. Typing replaces all of them.
        </p>
      ) : null}
    </section>
  );
}
