/**
 * One row of the hierarchy: a draggable, renamable, toggleable handle on a layer.
 *
 * Reordering uses the HTML drag events rather than pointer events, because that keeps the
 * platform's own affordances — including the ones assistive technology understands — instead of
 * reimplementing them. The panel's keyboard actions cover what dragging cannot.
 */

import { useState, type DragEvent, type ReactNode } from "react";

import type { DropPosition } from "./dropTarget.ts";
import type { LayerRow as Row } from "./layerTree.ts";

export interface LayerRowProps {
  readonly row: Row;
  readonly selected: boolean;
  readonly expanded: boolean;
  readonly editable: boolean;
  readonly dropPosition: DropPosition | null;
  readonly onSelect: (row: Row, additive: boolean) => void;
  readonly onToggleExpand: (key: string) => void;
  readonly onToggleVisibility: (row: Row) => void;
  readonly onRename: (row: Row, name: string) => void;
  readonly onDragStart: (row: Row) => void;
  readonly onDragOver: (row: Row, position: DropPosition) => void;
  readonly onDrop: (row: Row, position: DropPosition) => void;
  readonly onDragEnd: () => void;
}

const KIND_LABEL = { layer: "Layer", mask: "Mask", effect: "Effect" } as const;

/** Which third of the row the pointer is in — what "above", "inside", and "below" mean here. */
function positionWithin(event: DragEvent<HTMLElement>): DropPosition {
  const box = event.currentTarget.getBoundingClientRect();
  const offset = event.clientY - box.top;
  if (offset < box.height / 3) return "above";
  if (offset > (box.height * 2) / 3) return "below";
  return "inside";
}

export function LayerRow({
  row,
  selected,
  expanded,
  editable,
  dropPosition,
  onSelect,
  onToggleExpand,
  onToggleVisibility,
  onRename,
  onDragStart,
  onDragOver,
  onDrop,
  onDragEnd,
}: LayerRowProps): ReactNode {
  const [renaming, setRenaming] = useState(false);

  return (
    <li
      role="treeitem"
      aria-level={row.depth + 1}
      aria-selected={selected}
      {...(row.expandable ? { "aria-expanded": expanded } : {})}
      className="layers__row"
      data-kind={row.kind}
      data-locked={row.locked}
      data-hidden={!row.visible}
      {...(dropPosition ? { "data-drop": dropPosition } : {})}
      draggable={editable && !row.locked && row.kind === "layer"}
      onDragStart={() => onDragStart(row)}
      onDragOver={(event) => {
        event.preventDefault();
        onDragOver(row, positionWithin(event));
      }}
      onDrop={(event) => {
        event.preventDefault();
        onDrop(row, positionWithin(event));
      }}
      onDragEnd={onDragEnd}
      style={{ paddingInlineStart: `calc(var(--space-2) + ${row.depth} * var(--space-3))` }}
    >
      {row.expandable ? (
        <button
          type="button"
          className="layers__twisty"
          aria-label={`${expanded ? "Collapse" : "Expand"} ${row.displayName}`}
          onClick={() => onToggleExpand(row.key)}
        >
          {expanded ? "▾" : "▸"}
        </button>
      ) : (
        <span className="layers__twisty" aria-hidden="true" />
      )}

      {renaming ? (
        <input
          className="layers__rename"
          autoFocus
          defaultValue={row.displayName}
          aria-label={`Rename ${row.displayName}`}
          onBlur={(event) => {
            setRenaming(false);
            if (event.target.value !== row.displayName) onRename(row, event.target.value);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter") event.currentTarget.blur();
            if (event.key === "Escape") {
              // Restore the original first, so the blur commit below sees no change.
              event.currentTarget.value = row.displayName;
              event.currentTarget.blur();
            }
          }}
        />
      ) : (
        <button
          type="button"
          className="layers__label"
          onClick={(event) => onSelect(row, event.shiftKey)}
          onDoubleClick={() => {
            if (editable && !row.locked) setRenaming(true);
          }}
        >
          {row.color ? (
            <span className="layers__swatch" style={{ background: row.color }} aria-hidden="true" />
          ) : null}
          <span className="layers__name">{row.displayName}</span>
          <span className="layers__kind measure">{KIND_LABEL[row.kind]}</span>
        </button>
      )}

      {row.kind === "layer" && editable ? (
        <button
          type="button"
          className="layers__visibility"
          aria-label={`${row.visible ? "Hide" : "Show"} ${row.displayName}`}
          aria-pressed={!row.visible}
          disabled={row.locked}
          onClick={() => onToggleVisibility(row)}
        >
          {row.visible ? "◉" : "○"}
        </button>
      ) : null}

      {row.origin === "static" ? null : (
        <span className="layers__origin measure" title={`Produced by ${row.origin}`}>
          {row.origin}
        </span>
      )}
      {row.locked ? <span className="layers__flag">Locked</span> : null}
      {row.visible ? null : <span className="layers__flag">Hidden</span>}
    </li>
  );
}
