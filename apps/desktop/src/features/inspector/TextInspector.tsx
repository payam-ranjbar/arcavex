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

/** The expressions a text value pulls from data, e.g. `{{ title_line_1 }}`. */
function bindingsIn(value: string): ReadonlyArray<string> {
  return [...value.matchAll(/\{\{\s*([^}]+?)\s*\}\}/g)].map((match) => match[1] ?? "");
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
  // Typing over a binding is a legitimate edit and a lossy one: the layer stops following
  // data.yaml and stops picking up locale overrides, so a translated render quietly reverts to
  // whatever was typed. Saying so costs a line; not saying it cost a tester their Farsi headline.
  const bindings = value === MIXED ? [] : bindingsIn(value);
  // What this text actually became for the current format and locale. Without it the only way
  // to check a wording change was to render a full-size image and look at it.
  const resolved = textLayers.length === 1 ? (textLayers[0]?.resolved_text ?? null) : null;

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
      {bindings.length > 0 ? (
        <p className="inspector__hint" role="note">
          This text comes from data ({bindings.map((name) => `{{ ${name} }}`).join(", ")}). Typing
          here replaces the binding with a literal, and the layer stops following data and locale
          overrides.
        </p>
      ) : null}
      {resolved !== null && resolved !== "" && resolved !== value ? (
        <p className="inspector__hint">
          Renders as: <span className="measure">{resolved}</span>
        </p>
      ) : null}
      {value === MIXED ? (
        <p className="inspector__hint">
          The selected layers have different text. Typing replaces all of them.
        </p>
      ) : null}
    </section>
  );
}
