/**
 * The effect list: order matters, so the whole list is replaced rather than patched.
 *
 * Effects apply in sequence and each one sees the previous one's output, so "disable the second
 * effect" and "move it after the third" are both list edits. The engine's `set_effects` takes the
 * full list for exactly that reason, and this panel composes it.
 */

import type { ReactNode } from "react";

import type { LayerNodeReport } from "../../contracts/index.ts";
import type { EditorCommand } from "../workspace/index.ts";
import type { InspectorSectionProps } from "./TextInspector.tsx";

type EffectEntry = NonNullable<LayerNodeReport["effects"]>[number];

/** An effect as the engine takes it.
 *
 * `enabled` belongs *inside* `params` — the same place the tree reports it. Sending it beside
 * `params` produced `ARC-TPL-068 Node has unknown effect field 'enabled'`: the application
 * writing a field its own engine rejects, so the toggle simply never worked.
 */
function toSpec(effect: EffectEntry, enabled: boolean) {
  return {
    name: effect.name,
    params: { ...((effect.params ?? {}) as Record<string, unknown>), enabled },
  };
}

export function EffectsInspector({
  layers,
  disabled,
  disabledReason,
  onSubmit,
}: InspectorSectionProps): ReactNode {
  const single = layers.length === 1 ? (layers[0] ?? null) : null;
  if (single === null) {
    return layers.length > 1 ? (
      <section className="inspector__section" aria-labelledby="inspector-effects">
        <h3 className="eyebrow" id="inspector-effects">
          Effects
        </h3>
        <p className="inspector__hint">Select one layer to edit its effects.</p>
      </section>
    ) : null;
  }

  const effects = single.effects ?? [];
  const layerId = single.authored_id;

  const replace = (next: ReadonlyArray<ReturnType<typeof toSpec>>): void => {
    const command: EditorCommand = {
      kind: "set_effects",
      layer_id: layerId,
      effects: [...next],
    };
    onSubmit([command]);
  };

  const move = (index: number, delta: number): void => {
    const target = index + delta;
    if (target < 0 || target >= effects.length) return;
    const specs = effects.map((effect) => toSpec(effect, isEnabled(effect)));
    const [moved] = specs.splice(index, 1);
    specs.splice(target, 0, moved!);
    replace(specs);
  };

  return (
    <section className="inspector__section" aria-labelledby="inspector-effects">
      <h3 className="eyebrow" id="inspector-effects">
        Effects
      </h3>
      {effects.length === 0 ? (
        <p className="inspector__hint">This layer has no effects.</p>
      ) : (
        <ol className="inspector__effects">
          {effects.map((effect, index) => (
            <li key={`${effect.name}-${index}`} className="inspector__effect">
              <label className="field field--inline">
                <input
                  type="checkbox"
                  className="field__checkbox"
                  checked={isEnabled(effect)}
                  disabled={disabled}
                  onChange={(event) =>
                    replace(
                      effects.map((entry, position) =>
                        toSpec(entry, position === index ? event.target.checked : isEnabled(entry)),
                      ),
                    )
                  }
                />
                <span className="field__label">{effect.name}</span>
              </label>
              <span className="inspector__effect-actions">
                <button
                  type="button"
                  className="inspector__effect-move"
                  aria-label={`Move ${effect.name} earlier`}
                  disabled={disabled || index === 0}
                  onClick={() => move(index, -1)}
                >
                  ↑
                </button>
                <button
                  type="button"
                  className="inspector__effect-move"
                  aria-label={`Move ${effect.name} later`}
                  disabled={disabled || index === effects.length - 1}
                  onClick={() => move(index, 1)}
                >
                  ↓
                </button>
              </span>
            </li>
          ))}
        </ol>
      )}
      {disabledReason ? <p className="field__reason">{disabledReason}</p> : null}
    </section>
  );
}

/** The engine reports `enabled` inside params; absent means on. */
function isEnabled(effect: EffectEntry): boolean {
  const params = (effect.params ?? {}) as Record<string, unknown>;
  return params.enabled !== false;
}
