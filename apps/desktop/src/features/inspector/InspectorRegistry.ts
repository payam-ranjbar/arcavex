/**
 * Which inspectors apply to a selection, and what they are allowed to do with it.
 *
 * Registering by capability rather than hard-coding a panel layout is what lets an inspector be
 * added — by a later phase or an extension — without editing the shell. It also lets the shell
 * answer the two questions every editable field needs answered before it renders:
 *
 * - **Does this property exist on this kind of node?** Text has no `shape`; a group has no `text`.
 *   An inspector that does not apply is not rendered at all.
 * - **May the user change it right now?** A locked layer, a read-only automation policy, or a
 *   rendered-mode instance that maps to no single authored node all mean "no" — and each has a
 *   different reason, which the field shows instead of silently doing nothing.
 */

import type { LayerNodeReport } from "../../contracts/index.ts";
import type { AutomationMode, LayerTreeMode } from "../../gateway/index.ts";

export type LayerKind = NonNullable<LayerNodeReport["kind"]>;

/** Why a field cannot be edited, or null when it can. */
export type EditabilityReason =
  "locked" | "read-only-policy" | "rendered-instance" | "no-selection" | null;

export interface EditabilityInput {
  readonly layer: LayerNodeReport | null;
  readonly locked: boolean;
  readonly automation: AutomationMode;
  readonly treeMode: LayerTreeMode;
}

export interface Editability {
  readonly editable: boolean;
  readonly reason: EditabilityReason;
  /** A sentence for the user; null when editing is allowed. */
  readonly explanation: string | null;
}

const EXPLANATIONS: Record<NonNullable<EditabilityReason>, string> = {
  locked: "This layer is locked. Unlock it in the Layers panel to edit it.",
  "read-only-policy": "This project's automation mode is read-only.",
  "rendered-instance":
    "This is a rendered instance of a repeated or conditional definition. Switch the Layers " +
    "panel to Definition to edit the authored layer.",
  "no-selection": "Select a layer to edit its properties.",
};

/** Decide whether the current selection may be edited, and say why not when it may not. */
export function editability(input: EditabilityInput): Editability {
  const reason = firstReason(input);
  return {
    editable: reason === null,
    reason,
    explanation: reason === null ? null : EXPLANATIONS[reason],
  };
}

function firstReason(input: EditabilityInput): EditabilityReason {
  if (input.layer === null) return "no-selection";
  if (input.automation === "read_only") return "read-only-policy";
  if (input.locked) return "locked";
  // A rendered row produced by `repeat`/`if` has an instance id distinct from its authored id;
  // editing it would silently change every instance, so structural edits wait for Definition mode.
  if (input.treeMode === "rendered" && isMultiInstance(input.layer)) return "rendered-instance";
  return null;
}

function isMultiInstance(layer: LayerNodeReport): boolean {
  return layer.origin === "repeat" || layer.origin === "if";
}

export interface InspectorSection {
  readonly id: string;
  readonly title: string;
  /** Node kinds this section applies to; empty means every kind. */
  readonly kinds: ReadonlyArray<LayerKind>;
}

/**
 * The sections the shell renders, in order.
 *
 * Kept as data rather than JSX so tests — and later, extensions — can reason about which
 * inspectors a selection gets without rendering the workbench.
 */
export const INSPECTOR_SECTIONS: ReadonlyArray<InspectorSection> = [
  { id: "text", title: "Text", kinds: ["text"] },
  { id: "transform", title: "Transform", kinds: [] },
  { id: "appearance", title: "Appearance", kinds: [] },
  { id: "effects", title: "Effects", kinds: [] },
];

/** The sections that apply to one layer kind, in render order. */
export function sectionsFor(kind: LayerKind | null): ReadonlyArray<InspectorSection> {
  if (kind === null) return [];
  return INSPECTOR_SECTIONS.filter(
    (section) => section.kinds.length === 0 || section.kinds.includes(kind),
  );
}
