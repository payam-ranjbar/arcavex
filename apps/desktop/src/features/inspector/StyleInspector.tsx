/**
 * Type and colour: the properties a designer actually reaches for.
 *
 * The engine has taken `font`, `font_size`, `font_weight`, `color`, `align`, `letter_spacing`,
 * `italic`, `opacity`, `fill`, `stroke`, `stroke_width` and `corner_radius` since Phase 1, and
 * the inspector offered none of them — a text layer could be moved and resized but not styled,
 * so any real design change meant leaving the application for a text editor.
 *
 * Every control here writes one `set_property` command against the node's authored `style`
 * mapping, which is what the engine reports and what the template stores. Values keep their
 * authored units: a size is `70px` or `24pt`, not a bare number, because rewriting `70px` as
 * `70` would silently change what it means.
 */

import type { ReactNode } from "react";

import type { LayerNodeReport } from "../../contracts/index.ts";
import { MIXED, NumberField, TextField, ToggleField, shared, type FieldValue } from "./fields.tsx";
import type { InspectorSectionProps } from "./TextInspector.tsx";

/** Alignments the engine accepts, in reading order. */
const ALIGNMENTS = ["start", "center", "end", "justify"] as const;

/** A style value as authored, or MIXED across a multi-selection. */
function styleValue<T>(
  layers: ReadonlyArray<LayerNodeReport>,
  key: string,
  read: (raw: unknown) => T,
): FieldValue<T> {
  return shared(layers.map((layer) => read((layer.style ?? {})[key])));
}

/** The same for `paragraph`, which is where the text renderer reads alignment and direction. */
function paragraphValue<T>(
  layers: ReadonlyArray<LayerNodeReport>,
  key: string,
  read: (raw: unknown) => T,
): FieldValue<T> {
  return shared(layers.map((layer) => read((layer.paragraph ?? {})[key])));
}

/** A style value is a scalar in the template; anything else is not something to show. */
function asText(raw: unknown): string {
  if (typeof raw === "string") return raw;
  if (typeof raw === "number" || typeof raw === "boolean") return String(raw);
  return "";
}

function asNumber(raw: unknown): number {
  const parsed = typeof raw === "number" ? raw : Number.parseFloat(asText(raw));
  return Number.isFinite(parsed) ? parsed : 0;
}

function asBoolean(raw: unknown): boolean {
  return raw === true;
}

/** The unit a value carries, shown in its label: a bare "Size" field next to "X (pt)" reads as
 * points, and typing 110 into a px document silently means 82.5pt. */
function unitOf(value: FieldValue<string>): string {
  if (value === MIXED) return "mixed";
  const match = /[a-z%]+$/i.exec(value);
  return match ? match[0] : "pt";
}

/** Keep the unit the value was authored with, so `70px` stays px when the number changes. */
function withUnit(previous: unknown, next: number): string | number {
  const match = /[a-z%]+$/i.exec(asText(previous));
  return match ? `${next}${match[0]}` : next;
}

export function StyleInspector({
  layers,
  disabled,
  disabledReason,
  onSubmit,
}: InspectorSectionProps): ReactNode {
  const styled = layers.filter((layer) => layer.kind === "text" || layer.kind === "shape");
  if (styled.length === 0) return null;

  const text = styled.filter((layer) => layer.kind === "text");
  const shapes = styled.filter((layer) => layer.kind === "shape");

  function set(key: string, value: unknown): void {
    onSubmit(
      styled.map((layer) => ({
        kind: "set_property" as const,
        layer_id: layer.authored_id,
        keypath: `style.${key}`,
        value,
      })),
    );
  }

  function setPerLayer(key: string, next: (layer: LayerNodeReport) => unknown): void {
    onSubmit(
      styled.map((layer) => ({
        kind: "set_property" as const,
        layer_id: layer.authored_id,
        keypath: `style.${key}`,
        value: next(layer),
      })),
    );
  }

  // Alignment belongs to `paragraph`. The schema also accepts `style.align`, which is how this
  // panel used to write it — producing a value the engine stores, never reads, and never applies,
  // so the buttons highlighted nothing and the text never moved.
  const alignment = paragraphValue(text, "align", asText);
  const colour = styleValue(styled, "color", asText);

  return (
    <section className="inspector__section" aria-labelledby="inspector-style">
      <h3 className="eyebrow" id="inspector-style">
        {text.length > 0 ? "Type" : "Appearance"}
      </h3>

      {text.length > 0 ? (
        <>
          <TextField
            id="inspector-style-font"
            label="Font"
            value={styleValue(text, "font", asText)}
            disabled={disabled}
            disabledReason={disabledReason}
            onCommit={(next) => set("font", next)}
          />
          <NumberField
            id="inspector-style-size"
            label={`Size (${unitOf(styleValue(text, "font_size", asText))})`}
            value={styleValue(text, "font_size", asNumber)}
            disabled={disabled}
            disabledReason={disabledReason}
            onCommit={(next) =>
              setPerLayer("font_size", (layer) => withUnit((layer.style ?? {}).font_size, next))
            }
          />
          <NumberField
            id="inspector-style-weight"
            label="Weight"
            value={styleValue(text, "font_weight", asNumber)}
            disabled={disabled}
            disabledReason={disabledReason}
            onCommit={(next) => set("font_weight", next)}
          />
          <NumberField
            id="inspector-style-tracking"
            label={`Letter spacing (${unitOf(styleValue(text, "letter_spacing", asText))})`}
            value={styleValue(text, "letter_spacing", asNumber)}
            disabled={disabled}
            disabledReason={disabledReason}
            onCommit={(next) =>
              setPerLayer("letter_spacing", (layer) =>
                withUnit((layer.style ?? {}).letter_spacing ?? "0px", next),
              )
            }
          />

          <div className="inspector__row" role="group" aria-label="Alignment">
            {ALIGNMENTS.map((option) => (
              <button
                key={option}
                type="button"
                aria-pressed={alignment !== MIXED && alignment === option}
                disabled={disabled}
                onClick={() =>
                  onSubmit(
                    text.map((layer) => ({
                      kind: "set_property" as const,
                      layer_id: layer.authored_id,
                      keypath: "paragraph.align",
                      value: option,
                    })),
                  )
                }
              >
                {option}
              </button>
            ))}
          </div>

          <ToggleField
            id="inspector-style-italic"
            label="Italic"
            value={styleValue(text, "italic", asBoolean)}
            disabled={disabled}
            disabledReason={disabledReason}
            onCommit={(next) => set("italic", next)}
          />
        </>
      ) : null}

      {/* The swatch alone is the browser's own picker: no hex field, no document palette, and
          three decimal RGB spinners. Designers work in hex and the poster's palette is already
          in the file, so the field takes a typed value and the swatch stays for sampling. */}
      <div className="inspector__colour">
        <label className="inspector__field" htmlFor="inspector-style-color">
          <span>{text.length > 0 ? "Colour" : "Fill"}</span>
          <input
            id="inspector-style-color"
            type="color"
            value={colour === MIXED || colour === "" ? "#000000" : colour}
            disabled={disabled}
            onChange={(event) =>
              set(text.length > 0 ? "color" : "fill", event.currentTarget.value.toUpperCase())
            }
          />
        </label>
        <TextField
          id="inspector-style-color-hex"
          label="Hex"
          value={colour}
          disabled={disabled}
          disabledReason={disabledReason}
          onCommit={(next) => {
            const hex = next.trim().replace(/^#?/, "#").toUpperCase();
            if (/^#[0-9A-F]{6}$/.test(hex)) set(text.length > 0 ? "color" : "fill", hex);
          }}
        />
      </div>

      <NumberField
        id="inspector-style-opacity"
        label="Opacity"
        value={styleValue(styled, "opacity", (raw) => (raw === undefined ? 1 : asNumber(raw)))}
        disabled={disabled}
        disabledReason={disabledReason}
        onCommit={(next) => set("opacity", Math.min(1, Math.max(0, next)))}
      />

      {shapes.length > 0 ? (
        <NumberField
          id="inspector-style-radius"
          label="Corner radius"
          value={styleValue(shapes, "corner_radius", asNumber)}
          disabled={disabled}
          disabledReason={disabledReason}
          onCommit={(next) =>
            setPerLayer("corner_radius", (layer) =>
              withUnit((layer.style ?? {}).corner_radius ?? "0px", next),
            )
          }
        />
      ) : null}
    </section>
  );
}
