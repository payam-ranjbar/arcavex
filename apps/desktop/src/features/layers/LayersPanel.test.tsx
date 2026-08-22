/** Layer ordering and presentation, which is where a layers panel is right or wrong. */

import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { LayerNodeReport, LayerTreeReport } from "../../contracts/index.ts";
import { FakeArcavexGateway } from "../../gateway/index.ts";
import { renderApp } from "../../shared/test/renderApp.tsx";
import { LayersPanel } from "./LayersPanel.tsx";
import { allExpandableKeys, flattenLayerTree, moveSelection } from "./layerTree.ts";

function layer(overrides: Partial<LayerNodeReport> & { id: string }): LayerNodeReport {
  return {
    authored_id: overrides.id,
    authored_index: 0,
    kind: "text",
    display_name: overrides.id,
    ...overrides,
  };
}

function tree(root: LayerNodeReport): LayerTreeReport {
  return { response_version: 1, ok: true, mode: "rendered", root };
}

const NESTED = tree(
  layer({
    id: "root",
    kind: "group",
    display_name: "Root",
    paint_index: 0,
    children: [
      layer({ id: "back", display_name: "Background", authored_index: 0, paint_index: 1 }),
      layer({
        id: "group",
        kind: "group",
        display_name: "Header",
        authored_index: 1,
        paint_index: 2,
        children: [
          layer({ id: "title", display_name: "Title", authored_index: 0, paint_index: 3 }),
          layer({ id: "rule", display_name: "Rule", authored_index: 1, paint_index: 4 }),
        ],
      }),
      layer({ id: "front", display_name: "Foreground", authored_index: 2, paint_index: 5 }),
    ],
  }),
);

describe("flattenLayerTree", () => {
  it("shows siblings highest painted first, because that is what on top means", () => {
    const rows = flattenLayerTree(NESTED, { expanded: allExpandableKeys(NESTED) });

    expect(rows.map((row) => row.displayName)).toEqual([
      "Root",
      "Foreground",
      "Header",
      "Rule",
      "Title",
      "Background",
    ]);
  });

  it("indents each level so nesting is visible without reading names", () => {
    const rows = flattenLayerTree(NESTED, { expanded: allExpandableKeys(NESTED) });

    expect(rows.find((row) => row.displayName === "Header")?.depth).toBe(1);
    expect(rows.find((row) => row.displayName === "Title")?.depth).toBe(2);
  });

  it("hides the children of a collapsed row", () => {
    const expanded = allExpandableKeys(NESTED);
    expanded.delete("group");

    const rows = flattenLayerTree(NESTED, { expanded });

    expect(rows.map((row) => row.displayName)).not.toContain("Title");
    expect(rows.map((row) => row.displayName)).toContain("Header");
  });

  it("lists a layer's mask and effects as subrows beneath it", () => {
    const withExtras = tree(
      layer({
        id: "root",
        kind: "group",
        display_name: "Root",
        children: [
          layer({
            id: "title",
            display_name: "Title",
            mask: { component: "rounded_rect", params: {} },
            effects: [
              { index: 0, name: "drop_shadow", category: "raster", params: {} },
              { index: 1, name: "grain", category: "raster", params: {} },
            ],
          }),
        ],
      }),
    );

    const rows = flattenLayerTree(withExtras, { expanded: allExpandableKeys(withExtras) });

    expect(rows.map((row) => [row.kind, row.displayName])).toEqual([
      ["layer", "Root"],
      ["layer", "Title"],
      ["mask", "rounded_rect"],
      ["effect", "drop_shadow"],
      ["effect", "grain"],
    ]);
  });

  it("marks a subrow as neither editable nor hit testable", () => {
    const withMask = tree(
      layer({ id: "title", display_name: "Title", mask: { component: "circle", params: {} } }),
    );

    const rows = flattenLayerTree(withMask, { expanded: allExpandableKeys(withMask) });

    expect(rows[1]).toMatchObject({ kind: "mask", editable: false, hitTestable: false });
  });

  it("falls back to authored order when a tree carries no paint indices", () => {
    const authored = tree(
      layer({
        id: "root",
        kind: "group",
        display_name: "Root",
        children: [
          layer({ id: "a", display_name: "First", authored_index: 0 }),
          layer({ id: "b", display_name: "Second", authored_index: 1 }),
        ],
      }),
    );

    const rows = flattenLayerTree(authored, { expanded: allExpandableKeys(authored) });

    expect(rows.map((row) => row.displayName)).toEqual(["Root", "Second", "First"]);
  });

  it("produces no rows for a tree with no root", () => {
    expect(
      flattenLayerTree(tree(null as unknown as LayerNodeReport), { expanded: new Set() }),
    ).toEqual([]);
  });
});

describe("moveSelection", () => {
  const rows = flattenLayerTree(NESTED, { expanded: allExpandableKeys(NESTED) });

  it("selects the first row when nothing is selected yet", () => {
    expect(moveSelection(rows, null, 1)).toBe("root");
  });

  it("stops at the ends rather than wrapping around", () => {
    expect(moveSelection(rows, "root", -1)).toBe("root");
    expect(moveSelection(rows, rows.at(-1)!.key, 1)).toBe(rows.at(-1)!.key);
  });
});

describe("LayersPanel", () => {
  it("draws the engine's tree and selects the row that was clicked", async () => {
    let selected: string | null = null;
    renderApp(
      <LayersPanel selectedKey={null} onSelect={(row) => (selected = row?.authoredId ?? null)} />,
      { script: { layerTree: NESTED } },
    );

    await userEvent.click(await screen.findByRole("button", { name: /Foreground/u }));

    expect(selected).toBe("front");
  });

  it("moves the selection with the arrow keys", async () => {
    const seen: Array<string | null> = [];
    renderApp(
      <LayersPanel selectedKey={null} onSelect={(row) => seen.push(row?.authoredId ?? null)} />,
      { script: { layerTree: NESTED } },
    );

    await screen.findByRole("button", { name: /Foreground/u });
    const tree = within(document.body).getByRole("tree", { name: "Layers" });
    tree.focus();
    await userEvent.keyboard("{ArrowDown}");

    expect(seen).toEqual(["root"]);
  });

  it("collapses a row when its twisty is used", async () => {
    renderApp(<LayersPanel selectedKey={null} onSelect={() => {}} />, {
      script: { layerTree: NESTED },
    });

    expect(await screen.findByRole("button", { name: /Title/u })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Collapse Header" }));

    expect(screen.queryByRole("button", { name: /Title/u })).not.toBeInTheDocument();
  });

  it("marks a locked layer and a hidden layer for anyone scanning the tree", async () => {
    const flagged = tree(
      layer({
        id: "root",
        kind: "group",
        display_name: "Root",
        children: [
          layer({ id: "a", display_name: "Locked one", locked: true, paint_index: 2 }),
          layer({ id: "b", display_name: "Hidden one", visible: false, paint_index: 1 }),
        ],
      }),
    );
    renderApp(<LayersPanel selectedKey={null} onSelect={() => {}} />, {
      script: { layerTree: flagged },
    });

    const rows = await screen.findAllByRole("treeitem");
    expect(rows[1]).toHaveAttribute("data-locked", "true");
    expect(rows[2]).toHaveAttribute("data-hidden", "true");
  });

  it("asks the engine for the definition tree when that mode is chosen", async () => {
    const { gateway } = renderApp(<LayersPanel selectedKey={null} onSelect={() => {}} />, {
      script: { layerTree: NESTED },
    });

    await userEvent.click(await screen.findByRole("button", { name: "Definition" }));

    await screen.findByRole("tree", { name: "Layers" });
    expect(
      gateway.calls.filter((call) => call.method === "layerTree").map((c) => c.argument),
    ).toContain("authored");
  });

  it("says so when the engine cannot read the tree", async () => {
    const gateway = new FakeArcavexGateway();
    gateway.failNext("layerTree", new Error("no project is open"));

    renderApp(<LayersPanel selectedKey={null} onSelect={() => {}} />, { gateway });

    expect(await screen.findByRole("note")).toHaveTextContent("could not read");
  });
});

describe("LayersPanel editing", () => {
  const submitted: Array<ReadonlyArray<unknown>> = [];

  function renderEditable(selectedKey: string | null = "front", options: object = {}) {
    submitted.length = 0;
    return renderApp(
      <LayersPanel
        selectedKey={selectedKey}
        onSelect={() => {}}
        onSubmit={(commands) => submitted.push(commands)}
        {...options}
      />,
      { script: { layerTree: NESTED } },
    );
  }

  it("toggles a layer's visibility from its row", async () => {
    renderEditable();

    await userEvent.click(await screen.findByRole("button", { name: "Hide Foreground" }));

    expect(submitted[0]).toEqual([{ kind: "set_visibility", layer_id: "front", visible: false }]);
  });

  it("renames a layer on double-click and commits on Enter", async () => {
    renderEditable();

    await userEvent.dblClick(await screen.findByRole("button", { name: /^Foreground/u }));
    const field = screen.getByRole("textbox", { name: "Rename Foreground" });
    await userEvent.clear(field);
    await userEvent.type(field, "Hero{Enter}");

    expect(submitted[0]).toEqual([
      { kind: "set_display_name", layer_id: "front", display_name: "Hero" },
    ]);
  });

  it("abandons a rename on Escape", async () => {
    renderEditable();

    await userEvent.dblClick(await screen.findByRole("button", { name: /^Foreground/u }));
    const field = screen.getByRole("textbox", { name: "Rename Foreground" });
    await userEvent.clear(field);
    await userEvent.type(field, "Discarded{Escape}");

    expect(submitted).toHaveLength(0);
  });

  it("deletes and duplicates the selected layer", async () => {
    renderEditable();

    await userEvent.click(await screen.findByRole("button", { name: "Duplicate" }));
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));

    expect(submitted[0]).toEqual([{ kind: "duplicate", layer_id: "front" }]);
    expect(submitted[1]).toEqual([{ kind: "delete", layer_ids: ["front"] }]);
  });

  it("needs two layers before it will group", async () => {
    renderEditable();

    expect(await screen.findByRole("button", { name: "Group" })).toBeDisabled();
  });

  it("announces a structural change for assistive technology", async () => {
    renderEditable();

    await userEvent.click(await screen.findByRole("button", { name: "Hide Foreground" }));

    expect(screen.getByRole("status")).toHaveTextContent("Hid Foreground.");
  });

  it("refuses structural editing of a construct instance and says why", async () => {
    const repeated = tree(
      layer({
        id: "root",
        kind: "group",
        display_name: "Root",
        paint_index: 0,
        children: [
          layer({
            id: "card",
            display_name: "Card",
            origin: "repeat",
            instance_id: "card#0",
            paint_index: 1,
          }),
        ],
      }),
    );
    renderApp(
      <LayersPanel
        selectedKey="card"
        onSelect={() => {}}
        onSubmit={(commands) => submitted.push(commands)}
      />,
      { script: { layerTree: repeated } },
    );

    // Wait for the tree itself: the action bar renders immediately, so asserting on it first
    // would pass before the rows — and the selection they carry — have arrived.
    await screen.findByRole("button", { name: /^Card/u });
    expect(screen.getByRole("button", { name: "Delete" })).toBeDisabled();
    expect(screen.getByText(/Definition mode/i)).toBeInTheDocument();
  });

  it("stays read-only when no submit handler is wired", async () => {
    renderApp(<LayersPanel selectedKey="front" onSelect={() => {}} />, {
      script: { layerTree: NESTED },
    });

    await screen.findByRole("button", { name: /Foreground/u });
    expect(screen.queryByRole("group", { name: "Layer actions" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Hide Foreground" })).not.toBeInTheDocument();
  });

  it("disables editing for a read-only project", async () => {
    renderEditable("front", { editable: false });

    expect(await screen.findByRole("button", { name: "Delete" })).toBeDisabled();
  });
});
