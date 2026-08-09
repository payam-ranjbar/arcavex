/** The authoritative hierarchy, shown the way a layers panel is read: topmost first. */

import { useMemo, useState, type KeyboardEvent, type ReactNode } from "react";

import type { LayerTreeMode } from "../../gateway/index.ts";
import { useLayerTree } from "../projects/index.ts";
import { allExpandableKeys, flattenLayerTree, moveSelection, type LayerRow } from "./layerTree.ts";

import "./layers.css";

export interface LayersPanelProps {
  readonly selectedKey: string | null;
  readonly onSelect: (row: LayerRow | null) => void;
}

const KIND_LABEL: Record<LayerRow["kind"], string> = {
  layer: "Layer",
  mask: "Mask",
  effect: "Effect",
};

export function LayersPanel({ selectedKey, onSelect }: LayersPanelProps): ReactNode {
  const [mode, setMode] = useState<LayerTreeMode>("rendered");
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set());
  const tree = useLayerTree(mode);

  // Everything is open by default: a layer panel that starts collapsed hides the work.
  const expanded = useMemo(() => {
    if (!tree.data) return new Set<string>();
    const keys = allExpandableKeys(tree.data);
    for (const key of collapsed) keys.delete(key);
    return keys;
  }, [tree.data, collapsed]);

  const rows = useMemo(
    () => (tree.data ? flattenLayerTree(tree.data, { expanded }) : []),
    [tree.data, expanded],
  );

  function toggle(key: string): void {
    setCollapsed((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function onKeyDown(event: KeyboardEvent<HTMLUListElement>): void {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    const nextKey = moveSelection(rows, selectedKey, event.key === "ArrowDown" ? 1 : -1);
    const next = rows.find((row) => row.key === nextKey);
    onSelect(next ?? null);
  }

  if (tree.isError) {
    return <p role="note">The engine could not read this project&apos;s layer tree.</p>;
  }

  return (
    <div className="layers">
      <div className="layers__modes" role="group" aria-label="Layer tree mode">
        {(["rendered", "authored"] as const).map((candidate) => (
          <button
            key={candidate}
            type="button"
            aria-pressed={mode === candidate}
            onClick={() => setMode(candidate)}
          >
            {candidate === "rendered" ? "Rendered" : "Definition"}
          </button>
        ))}
      </div>

      <ul
        className="layers__rows"
        role="tree"
        aria-label="Layers"
        tabIndex={0}
        onKeyDown={onKeyDown}
      >
        {rows.map((row) => (
          <li
            key={row.key}
            role="treeitem"
            aria-level={row.depth + 1}
            aria-selected={row.key === selectedKey}
            {...(row.expandable ? { "aria-expanded": expanded.has(row.key) } : {})}
            className="layers__row"
            data-kind={row.kind}
            data-locked={row.locked}
            data-hidden={!row.visible}
            style={{ paddingInlineStart: `calc(var(--space-2) + ${row.depth} * var(--space-3))` }}
          >
            {row.expandable ? (
              <button
                type="button"
                className="layers__twisty"
                aria-label={`${expanded.has(row.key) ? "Collapse" : "Expand"} ${row.displayName}`}
                onClick={() => toggle(row.key)}
              >
                {expanded.has(row.key) ? "▾" : "▸"}
              </button>
            ) : (
              <span className="layers__twisty" aria-hidden="true" />
            )}

            <button type="button" className="layers__label" onClick={() => onSelect(row)}>
              {row.color ? (
                <span
                  className="layers__swatch"
                  style={{ background: row.color }}
                  aria-hidden="true"
                />
              ) : null}
              <span className="layers__name">{row.displayName}</span>
              <span className="layers__kind measure">{KIND_LABEL[row.kind]}</span>
            </button>

            {row.origin === "static" ? null : (
              <span className="layers__origin measure" title={`Produced by ${row.origin}`}>
                {row.origin}
              </span>
            )}
            {row.locked ? <span className="layers__flag">Locked</span> : null}
            {row.visible ? null : <span className="layers__flag">Hidden</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}
