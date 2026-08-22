/**
 * The authoritative hierarchy, shown the way a layers panel is read: topmost first — and, once
 * editing is wired, the place structure is changed.
 *
 * Two decisions keep this honest. Visual order is inverted from authored order, and that
 * conversion lives entirely in `dropTarget.ts` rather than being re-derived per interaction. And
 * structural editing is disabled in Rendered mode for rows a `repeat`/`if` construct produced,
 * because one visible instance does not map to one authored definition — editing it would change
 * every instance without saying so.
 */

import { useMemo, useState, type KeyboardEvent, type ReactNode } from "react";

import type { LayerTreeMode } from "../../gateway/index.ts";
import type { EditorCommand } from "../workspace/index.ts";
import { useLayerTree } from "../projects/index.ts";
import { LayerActions } from "./LayerActions.tsx";
import { LayerRow } from "./LayerRow.tsx";
import { REJECTION_MESSAGE, resolveDrop, type DropPosition } from "./dropTarget.ts";
import {
  allExpandableKeys,
  flattenLayerTree,
  moveSelection,
  type LayerRow as Row,
} from "./layerTree.ts";

import "./layers.css";

export interface LayersPanelProps {
  readonly selectedKey: string | null;
  readonly onSelect: (row: Row | null) => void;
  /** Absent leaves the panel read-only, exactly as Phase 1 behaved. */
  readonly onSubmit?: (commands: ReadonlyArray<EditorCommand>) => void;
  /** False for a read-only project. */
  readonly editable?: boolean;
  /**
   * The tree mode, when the workbench owns it.
   *
   * Rendered and Definition are not a panel-local preference: the inspector refuses to edit a
   * repeated instance and tells the user to switch *this* control, so the two have to be looking
   * at the same mode or that instruction cannot be followed. Left absent, the panel keeps its
   * own mode, which is what a standalone render wants.
   */
  readonly mode?: LayerTreeMode;
  readonly onModeChange?: (mode: LayerTreeMode) => void;
}

export function LayersPanel({
  selectedKey,
  onSelect,
  onSubmit,
  editable = true,
  mode: controlledMode,
  onModeChange,
}: LayersPanelProps): ReactNode {
  const [ownMode, setOwnMode] = useState<LayerTreeMode>("rendered");
  const mode = controlledMode ?? ownMode;
  const setMode = (next: LayerTreeMode): void => {
    setOwnMode(next);
    onModeChange?.(next);
  };
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set());
  const [dragged, setDragged] = useState<Row | null>(null);
  const [dropTarget, setDropTarget] = useState<{ key: string; position: DropPosition } | null>(
    null,
  );
  const [announcement, setAnnouncement] = useState("");
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

  const selectedRow = rows.find((row) => row.key === selectedKey) ?? null;
  // A rendered instance of a construct has no single authored definition to restructure.
  const structural =
    onSubmit !== undefined &&
    editable &&
    (mode === "authored" || (selectedRow?.origin ?? "static") === "static");
  const structuralReason =
    onSubmit === undefined || !editable
      ? null
      : structural
        ? null
        : "Switch to Definition mode to restructure repeated or conditional layers.";

  function toggle(key: string): void {
    setCollapsed((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function submit(commands: ReadonlyArray<EditorCommand>, summary: string): void {
    onSubmit?.(commands);
    setAnnouncement(summary);
  }

  function onKeyDown(event: KeyboardEvent<HTMLUListElement>): void {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    const nextKey = moveSelection(rows, selectedKey, event.key === "ArrowDown" ? 1 : -1);
    const next = rows.find((row) => row.key === nextKey);
    onSelect(next ?? null);
  }

  function completeDrop(row: Row, position: DropPosition): void {
    setDropTarget(null);
    const source = dragged;
    setDragged(null);
    if (!source || !structural) return;

    const result = resolveDrop({ rows, dragged: source, target: { row, position } });
    if (!result.ok) {
      setAnnouncement(REJECTION_MESSAGE[result.reason]);
      return;
    }
    submit([result.command], `Moved ${source.displayName}.`);
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

      {onSubmit ? (
        <LayerActions
          selection={selectedRow ? [selectedRow] : []}
          disabled={!structural}
          disabledReason={structuralReason}
          onSubmit={(commands) => submit(commands, "Applied a layer change.")}
        />
      ) : null}

      <ul
        className="layers__rows"
        role="tree"
        aria-label="Layers"
        tabIndex={0}
        onKeyDown={onKeyDown}
      >
        {rows.map((row) => (
          <LayerRow
            key={row.key}
            row={row}
            selected={row.key === selectedKey}
            expanded={expanded.has(row.key)}
            editable={structural}
            dropPosition={dropTarget?.key === row.key ? dropTarget.position : null}
            onSelect={(selected) => onSelect(selected)}
            onToggleExpand={toggle}
            onToggleVisibility={(target) =>
              submit(
                [
                  {
                    kind: "set_visibility",
                    layer_id: target.authoredId,
                    visible: !target.visible,
                  },
                ],
                `${target.visible ? "Hid" : "Showed"} ${target.displayName}.`,
              )
            }
            onRename={(target, name) =>
              submit(
                [
                  {
                    kind: "set_display_name",
                    layer_id: target.authoredId,
                    display_name: name.trim() === "" ? null : name,
                  },
                ],
                `Renamed ${target.displayName}.`,
              )
            }
            onDragStart={setDragged}
            onDragOver={(target, position) => setDropTarget({ key: target.key, position })}
            onDrop={completeDrop}
            onDragEnd={() => {
              setDragged(null);
              setDropTarget(null);
            }}
          />
        ))}
      </ul>

      {/* Structural changes are invisible to a screen reader unless they are announced. */}
      <p className="layers__status" role="status" aria-live="polite">
        {announcement}
      </p>
    </div>
  );
}
