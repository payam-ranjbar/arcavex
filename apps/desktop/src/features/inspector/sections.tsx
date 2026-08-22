/** Renders the inspectors that apply to a selection, in registry order. */

import type { ReactNode } from "react";

import "./inspector.css";

import { AppearanceInspector } from "./AppearanceInspector.tsx";
import { EffectsInspector } from "./EffectsInspector.tsx";
import { sectionsFor } from "./InspectorRegistry.ts";
import { TextInspector, type InspectorSectionProps } from "./TextInspector.tsx";
import { TransformInspector } from "./TransformInspector.tsx";

const RENDERERS = {
  text: TextInspector,
  transform: TransformInspector,
  appearance: AppearanceInspector,
  effects: EffectsInspector,
} as const;

export function InspectorRegistrySections(props: InspectorSectionProps): ReactNode {
  const primary = props.layers[0];
  if (!primary) return null;
  // Section applicability is decided by the primary selection's kind; a mixed-kind selection
  // still gets the universal sections, and kind-specific ones filter themselves out.
  const sections = sectionsFor(primary.kind);

  return (
    <>
      {sections.map((section) => {
        const Renderer = RENDERERS[section.id as keyof typeof RENDERERS];
        return <Renderer key={section.id} {...props} />;
      })}
    </>
  );
}
