/**
 * Inspector behaviour: what a field commits, when it refuses, and what it must never lose.
 *
 * The hard cases here are not the happy path. They are the ones that make an editor feel broken:
 * a rerender eating what you were typing, a multi-selection quietly overwriting values you could
 * not see, and a locked layer that accepts input and then does nothing.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { LayerNodeReport } from "../../contracts/index.ts";
import { seriousViolations } from "../../shared/test/axe.ts";
import { AppearanceInspector } from "./AppearanceInspector.tsx";
import { EffectsInspector } from "./EffectsInspector.tsx";
import { editability, sectionsFor } from "./InspectorRegistry.ts";
import { StyleInspector } from "./StyleInspector.tsx";
import { TextInspector } from "./TextInspector.tsx";
import { TransformInspector } from "./TransformInspector.tsx";

function layer(overrides: Partial<LayerNodeReport> = {}): LayerNodeReport {
  return {
    id: "title",
    authored_id: "title",
    kind: "text",
    text: "Old headline",
    display_name: "Headline",
    visible: true,
    bounds_pt: [10, 20, 300, 64],
    rotate_deg: 0,
    effects: [],
    children: [],
    ...overrides,
  } as LayerNodeReport;
}

const ENABLED = { disabled: false, disabledReason: null };

describe("InspectorRegistry", () => {
  it("offers text only for text layers", () => {
    expect(sectionsFor("text").map((section) => section.id)).toContain("text");
    expect(sectionsFor("shape").map((section) => section.id)).not.toContain("text");
    expect(sectionsFor("shape").map((section) => section.id)).toContain("transform");
  });

  it("explains every reason editing is unavailable", () => {
    const base = {
      layer: layer(),
      locked: false,
      automation: "unrestricted" as const,
      treeMode: "authored" as const,
    };

    expect(editability(base).editable).toBe(true);
    expect(editability({ ...base, layer: null }).reason).toBe("no-selection");
    expect(editability({ ...base, locked: true }).explanation).toMatch(/locked/i);
    expect(editability({ ...base, automation: "read_only" }).explanation).toMatch(/read-only/i);
    expect(
      editability({
        ...base,
        treeMode: "rendered",
        layer: layer({ origin: "repeat" }),
      }).explanation,
    ).toMatch(/definition/i);
  });

  it("treats a plain layer in rendered mode as editable", () => {
    // Only repeat/if instances are ambiguous; an ordinary node maps to one authored definition.
    const decision = editability({
      layer: layer(),
      locked: false,
      automation: "unrestricted",
      treeMode: "rendered",
    });

    expect(decision.editable).toBe(true);
  });
});

describe("TextInspector", () => {
  it("says what a data binding is, before it is typed over", () => {
    // The text of a designed layer is often a binding: {{ title_line_1 }} pulls from data.yaml
    // and picks up the locale override, so the Farsi render reads Farsi. Replacing it with a
    // literal is a legitimate edit, but a silent one cost a tester their Persian headline --
    // the Farsi poster came back reading "CROSSING" in the middle of otherwise correct RTL text.
    render(
      <TextInspector
        layers={[layer({ text: "{{ title_line_1 }}" })]}
        {...ENABLED}
        onSubmit={vi.fn()}
      />,
    );

    expect(screen.getByRole("note")).toHaveTextContent(/data/i);
    expect(screen.getByRole("note")).toHaveTextContent("title_line_1");
  });

  it("says nothing about bindings when the text is a plain literal", () => {
    render(
      <TextInspector layers={[layer({ text: "Old headline" })]} {...ENABLED} onSubmit={vi.fn()} />,
    );

    expect(screen.queryByRole("note")).toBeNull();
  });

  it("commits on Enter as one transaction", async () => {
    const onSubmit = vi.fn();
    render(<TextInspector layers={[layer()]} {...ENABLED} onSubmit={onSubmit} />);
    const user = userEvent.setup();

    const field = screen.getByLabelText("Content");
    await user.clear(field);
    await user.type(field, "New headline");
    await user.tab();

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit.mock.calls[0]?.[0]).toEqual([
      { kind: "set_text", layer_id: "title", text: "New headline" },
    ]);
  });

  it("reverts on Escape without committing", async () => {
    const onSubmit = vi.fn();
    render(<TextInspector layers={[layer()]} {...ENABLED} onSubmit={onSubmit} />);
    const user = userEvent.setup();

    const field = screen.getByLabelText("Content");
    await user.clear(field);
    await user.type(field, "Discarded{Escape}");

    expect(onSubmit).not.toHaveBeenCalled();
    expect(field).toHaveValue("Old headline");
  });

  it("does not commit when nothing changed", async () => {
    const onSubmit = vi.fn();
    render(<TextInspector layers={[layer()]} {...ENABLED} onSubmit={onSubmit} />);
    const user = userEvent.setup();

    await user.click(screen.getByLabelText("Content"));
    await user.tab();

    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("keeps what the user is typing across a rerender", async () => {
    const onSubmit = vi.fn();
    const { rerender } = render(
      <TextInspector layers={[layer()]} {...ENABLED} onSubmit={onSubmit} />,
    );
    const user = userEvent.setup();

    const field = screen.getByLabelText("Content");
    await user.clear(field);
    await user.type(field, "Half-typed");
    // A watcher event lands mid-edit and the panel rerenders with fresh engine data.
    rerender(<TextInspector layers={[layer()]} {...ENABLED} onSubmit={onSubmit} />);

    expect(field).toHaveValue("Half-typed");
  });

  it("shows mixed text across a multi-selection and replaces all of them on commit", async () => {
    const onSubmit = vi.fn();
    render(
      <TextInspector
        layers={[layer(), layer({ id: "sub", authored_id: "sub", text: "Other" })]}
        {...ENABLED}
        onSubmit={onSubmit}
      />,
    );
    const user = userEvent.setup();

    const field = screen.getByLabelText("Content");
    expect(field).toHaveAttribute("placeholder", "Mixed");
    expect(screen.getByText(/different text/i)).toBeInTheDocument();

    await user.type(field, "Unified");
    await user.tab();

    expect(onSubmit.mock.calls[0]?.[0]).toEqual([
      { kind: "set_text", layer_id: "title", text: "Unified" },
      { kind: "set_text", layer_id: "sub", text: "Unified" },
    ]);
  });

  it("renders nothing for a non-text selection", () => {
    const { container } = render(
      <TextInspector layers={[layer({ kind: "shape" })]} {...ENABLED} onSubmit={vi.fn()} />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("disables the field and states the reason when editing is not allowed", () => {
    render(
      <TextInspector
        layers={[layer()]}
        disabled
        disabledReason="This layer is locked."
        onSubmit={vi.fn()}
      />,
    );

    expect(screen.getByLabelText("Content")).toBeDisabled();
    expect(screen.getByText("This layer is locked.")).toBeInTheDocument();
  });
});

describe("TransformInspector", () => {
  it("emits a relative translate when a position field changes", async () => {
    const onSubmit = vi.fn();
    render(<TransformInspector layers={[layer()]} {...ENABLED} onSubmit={onSubmit} />);
    const user = userEvent.setup();

    const field = screen.getByLabelText(/^X/);
    await user.clear(field);
    await user.type(field, "50");
    await user.tab();

    expect(onSubmit.mock.calls[0]?.[0]).toEqual([
      { kind: "translate", layer_ids: ["title"], dx_pt: 40, dy_pt: 0 },
    ]);
  });

  it("emits an absolute resize that preserves the other axis", async () => {
    const onSubmit = vi.fn();
    render(<TransformInspector layers={[layer()]} {...ENABLED} onSubmit={onSubmit} />);
    const user = userEvent.setup();

    const field = screen.getByLabelText(/^Width/);
    await user.clear(field);
    await user.type(field, "320");
    await user.tab();

    expect(onSubmit.mock.calls[0]?.[0]).toEqual([
      { kind: "resize", layer_id: "title", w_pt: 320, h_pt: 64 },
    ]);
  });

  it("rejects a non-numeric entry by reverting instead of sending NaN", async () => {
    const onSubmit = vi.fn();
    render(<TransformInspector layers={[layer()]} {...ENABLED} onSubmit={onSubmit} />);
    const user = userEvent.setup();

    const field = screen.getByLabelText(/^Rotation/);
    await user.clear(field);
    await user.tab();

    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("rotates every selected layer to the same angle", async () => {
    const onSubmit = vi.fn();
    render(
      <TransformInspector
        layers={[layer(), layer({ id: "badge", authored_id: "badge" })]}
        {...ENABLED}
        onSubmit={onSubmit}
      />,
    );
    const user = userEvent.setup();

    const field = screen.getByLabelText(/^Rotation/);
    await user.clear(field);
    await user.type(field, "15");
    await user.tab();

    expect(onSubmit.mock.calls[0]?.[0]).toEqual([
      { kind: "rotate", layer_id: "title", degrees: 15 },
      { kind: "rotate", layer_id: "badge", degrees: 15 },
    ]);
  });

  it("refuses to resize a multi-selection and says why", () => {
    render(
      <TransformInspector
        layers={[layer(), layer({ id: "badge", authored_id: "badge" })]}
        {...ENABLED}
        onSubmit={vi.fn()}
      />,
    );

    expect(screen.getByLabelText(/^Width/)).toBeDisabled();
    expect(screen.getByText(/one layer at a time/i)).toBeInTheDocument();
  });
});

describe("AppearanceInspector", () => {
  it("toggles visibility for every selected layer", async () => {
    const onSubmit = vi.fn();
    render(
      <AppearanceInspector
        layers={[layer(), layer({ id: "badge", authored_id: "badge" })]}
        {...ENABLED}
        onSubmit={onSubmit}
      />,
    );
    const user = userEvent.setup();

    await user.click(screen.getByLabelText("Visible"));

    expect(onSubmit.mock.calls[0]?.[0]).toEqual([
      { kind: "set_visibility", layer_id: "title", visible: false },
      { kind: "set_visibility", layer_id: "badge", visible: false },
    ]);
  });

  it("shows an indeterminate checkbox when visibility is mixed", () => {
    render(
      <AppearanceInspector
        layers={[layer(), layer({ id: "badge", authored_id: "badge", visible: false })]}
        {...ENABLED}
        onSubmit={vi.fn()}
      />,
    );

    expect(screen.getByLabelText("Visible")).toBePartiallyChecked();
  });

  it("treats an emptied name as a removal, not an empty string", async () => {
    const onSubmit = vi.fn();
    render(<AppearanceInspector layers={[layer()]} {...ENABLED} onSubmit={onSubmit} />);
    const user = userEvent.setup();

    const field = screen.getByLabelText("Name");
    await user.clear(field);
    await user.tab();

    expect(onSubmit.mock.calls[0]?.[0]).toEqual([
      { kind: "set_display_name", layer_id: "title", display_name: null },
    ]);
  });

  it("says the stable identifier does not change", () => {
    render(<AppearanceInspector layers={[layer()]} {...ENABLED} onSubmit={vi.fn()} />);

    expect(screen.getByText(/does not change/i)).toBeInTheDocument();
  });
});

describe("EffectsInspector", () => {
  const withEffects = layer({
    kind: "image",
    effects: [
      { index: 0, name: "halftone", category: "raster", params: { dot_pt: 2 } },
      { index: 1, name: "grain", category: "raster", params: { enabled: false } },
    ],
  });

  it("replaces the whole list when one effect is disabled, because order is content", async () => {
    const onSubmit = vi.fn();
    render(<EffectsInspector layers={[withEffects]} {...ENABLED} onSubmit={onSubmit} />);
    const user = userEvent.setup();

    await user.click(screen.getByLabelText("halftone"));

    expect(onSubmit.mock.calls[0]?.[0]).toEqual([
      {
        kind: "set_effects",
        layer_id: "title",
        effects: [
          // `enabled` inside params, which is where the engine reads it and where the tree
          // reports it; beside params it was rejected as an unknown effect field.
          { name: "halftone", params: { dot_pt: 2, enabled: false } },
          { name: "grain", params: { enabled: false } },
        ],
      },
    ]);
  });

  it("reorders effects without losing their parameters", async () => {
    const onSubmit = vi.fn();
    render(<EffectsInspector layers={[withEffects]} {...ENABLED} onSubmit={onSubmit} />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: /move grain earlier/i }));

    const commands = onSubmit.mock.calls[0]?.[0] as Array<{ effects: Array<{ name: string }> }>;
    const command = commands[0]!;
    expect(command.effects.map((effect) => effect.name)).toEqual(["grain", "halftone"]);
  });

  it("cannot move the first effect earlier or the last later", () => {
    render(<EffectsInspector layers={[withEffects]} {...ENABLED} onSubmit={vi.fn()} />);

    expect(screen.getByRole("button", { name: /move halftone earlier/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /move grain later/i })).toBeDisabled();
  });

  it("asks for a single selection rather than guessing across layers", () => {
    render(
      <EffectsInspector
        layers={[withEffects, layer({ id: "other", authored_id: "other" })]}
        {...ENABLED}
        onSubmit={vi.fn()}
      />,
    );

    expect(screen.getByText(/select one layer/i)).toBeInTheDocument();
  });

  it("is accessible", async () => {
    const { container } = render(
      <EffectsInspector layers={[withEffects]} {...ENABLED} onSubmit={vi.fn()} />,
    );

    expect(await seriousViolations(container)).toEqual([]);
  });
});

describe("StyleInspector", () => {
  function styled(overrides: Partial<LayerNodeReport> = {}): LayerNodeReport {
    return layer({
      style: { font: "Archivo", font_size: "70px", font_weight: 400, color: "#FFFFFF" },
      paragraph: { align: "start", direction: "ltr" },
      ...overrides,
    });
  }

  it("changes the font family through set_property", async () => {
    const onSubmit = vi.fn();
    render(<StyleInspector layers={[styled()]} {...ENABLED} onSubmit={onSubmit} />);
    const user = userEvent.setup();

    const field = screen.getByLabelText("Font");
    await user.clear(field);
    await user.type(field, "Inter{Enter}");

    expect(onSubmit).toHaveBeenCalledWith([
      { kind: "set_property", layer_id: "title", keypath: "style.font", value: "Inter" },
    ]);
  });

  it("keeps the unit a size was authored with", async () => {
    // Rewriting `70px` as a bare `70` would silently reinterpret the size, since the engine
    // takes px and pt and a number alone means something else again.
    const onSubmit = vi.fn();
    render(<StyleInspector layers={[styled()]} {...ENABLED} onSubmit={onSubmit} />);
    const user = userEvent.setup();

    const field = screen.getByLabelText("Size");
    await user.clear(field);
    await user.type(field, "84{Enter}");

    expect(onSubmit).toHaveBeenCalledWith([
      { kind: "set_property", layer_id: "title", keypath: "style.font_size", value: "84px" },
    ]);
  });

  it("sets alignment from the reading-order buttons", async () => {
    const onSubmit = vi.fn();
    render(<StyleInspector layers={[styled()]} {...ENABLED} onSubmit={onSubmit} />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "end" }));

    // paragraph.align, not style.align: the schema accepts both and the renderer reads only
    // this one, so writing style.align stored a value that never moved any text.
    expect(onSubmit).toHaveBeenCalledWith([
      { kind: "set_property", layer_id: "title", keypath: "paragraph.align", value: "end" },
    ]);
  });

  it("offers fill rather than colour for a shape", () => {
    render(
      <StyleInspector
        layers={[styled({ kind: "shape", text: null })]}
        {...ENABLED}
        onSubmit={vi.fn()}
      />,
    );

    expect(screen.getByText("Fill")).toBeVisible();
    expect(screen.queryByLabelText("Font")).toBeNull();
  });

  it("shows nothing for a layer kind that has no style", () => {
    const { container } = render(
      <StyleInspector layers={[styled({ kind: "group" })]} {...ENABLED} onSubmit={vi.fn()} />,
    );

    expect(container).toBeEmptyDOMElement();
  });
});

describe("TextInspector resolved text", () => {
  it("shows what a binding actually rendered as", () => {
    render(
      <TextInspector
        layers={[layer({ text: "{{ title_line_1 }}", resolved_text: "BUILDING" })]}
        {...ENABLED}
        onSubmit={vi.fn()}
      />,
    );

    expect(screen.getByText(/Renders as/)).toBeVisible();
    expect(screen.getByText("BUILDING")).toBeVisible();
  });

  it("says nothing extra when the text is already literal", () => {
    render(
      <TextInspector
        layers={[layer({ text: "Plain words", resolved_text: "Plain words" })]}
        {...ENABLED}
        onSubmit={vi.fn()}
      />,
    );

    expect(screen.queryByText(/Renders as/)).toBeNull();
  });
});
