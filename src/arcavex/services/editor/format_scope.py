"""Format-scoped writes: one format's override, expressed as ops in ``formats.<name>.patch``.

A template's node tree is shared by every format; the per-format differences live in
``formats.<name>.patch``, an ordered list of ``set``/``remove`` ops the compiler applies to the
authored tree before laying that format out. A transaction with ``scope: "format"`` therefore
never touches the node it names: each field command becomes a ``set`` op for the target format,
and undoing it drops the op, or restores the op's previous value, rather than restoring the node.

Three decisions shape the ops written here:

- **The authored node decides an op's path; the format's effective node decides its value.** A
  ``set`` op may create the final field it names, but every segment before it must already exist
  in the tree the compiler applies the op to (``overlays._do_set``). Overriding
  ``transform.translate`` on a node with no ``transform`` therefore has to write the whole
  ``transform`` mapping. Deciding that against the *authored* node keeps the op path stable
  across edits, so a second drag in the same format replaces the first op instead of stacking a
  narrower one on top; taking the value from the *effective* node (authored plus the format's
  existing ops) makes that second drag continue from where the first left the node.
- **One op per path.** A path that already has a ``set`` op gets its value replaced in place,
  which keeps any comment on the op and keeps the diff to the one line that changed.
- **``remove: true`` drops the override.** In shared scope it deletes a key from the node; here
  it deletes this format's op for the path, so the format falls back to the shared value. That is
  what the inverse of "the override did not exist before" has to say, and it is the edit a person
  means by "stop overriding this for the story". The patch grammar's own ``remove`` verb (hide a
  field in one format) has no editor command; it is written by hand.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from arcavex.kernel.diagnostics import DiagnosticError, diagnostic
from arcavex.kernel.editor import SemanticTransaction
from arcavex.services.editor.source_map import index_tree
from arcavex.services.template.overlays import PatchLog, apply_patches

#: Commands with no per-format form. Structure is shared by construction — a format patch can
#: insert or remove nodes, but the editor's reorder/reparent/duplicate/delete/group vocabulary has
#: no honest translation into "for this format only" without duplicating the subtree per format.
#: A display name is project-wide UI metadata in project.ui.yaml, so it is not per-format either.
UNSCOPABLE_KINDS: frozenset[str] = frozenset(
    {
        "reorder",
        "reparent",
        "duplicate",
        "delete",
        "group",
        "splice_children",
        "set_display_name",
    }
)

#: Above this many characters a scalar override is written in block style, so a long headline
#: does not wrap mid-flow-mapping the way ruamel's default width makes it.
_FLOW_SCALAR_LIMIT = 60


def check_scope(transaction: SemanticTransaction) -> None:
    """Refuse a format-scoped transaction that can never be written, before any lock is taken.

    Raises:
        DiagnosticError: ``ARC-EDT-013`` when the scope is ``format`` but the target names no
            format; ``ARC-EDT-014`` when a command has no per-format form.
    """
    if transaction.scope != "format":
        return
    if not transaction.target.format:
        raise DiagnosticError(
            diagnostic(
                "ARC-EDT-013",
                "scope is 'format' but target.format names no format, so there is no "
                "formats.<name>.patch to write. Nothing was changed.",
                hint=(
                    "Set target: {format: <name>} to the format this change is for, or use "
                    "scope: shared to edit the authored node every format renders."
                ),
            )
        )
    unscopable = sorted({c.kind for c in transaction.commands if c.kind in UNSCOPABLE_KINDS})
    if unscopable:
        listed = ", ".join(unscopable)
        raise DiagnosticError(
            diagnostic(
                "ARC-EDT-014",
                f"{listed}: this command is shared by every format and cannot be written for "
                f"format {transaction.target.format!r} alone. Nothing was changed.",
                hint=(
                    "Use scope: shared for structural changes and display names. A per-format "
                    "structure needs a hand-written formats.<name>.patch (insert_before / "
                    "insert_after / remove ops) via arcavex_template_patch."
                ),
            )
        )


@dataclass(frozen=True)
class _Write:
    """One desired field value on one node, before it is narrowed to a patch op."""

    layer_id: str
    segments: tuple[str, ...]
    value: Any = None
    remove: bool = False


class FormatPatch:
    """The ``formats.<name>`` spec being edited, and the effective tree its ops produce."""

    def __init__(
        self,
        *,
        format_name: str,
        spec: Any,
        authored_root: Any,
        template_file: Path,
    ) -> None:
        self.format_name = format_name
        self._spec = spec
        self._authored_root = authored_root
        self._template_file = template_file
        self._effective_root: Any = None
        self._rebuild_effective()

    @classmethod
    def open(
        cls,
        formats: Any,
        format_name: str,
        authored_root: Any,
        template_file: Path,
    ) -> FormatPatch:
        """Locate the format's spec, refusing anything a patch cannot be written into.

        Raises:
            DiagnosticError: ``ARC-EDT-013`` when the template defines no such format, or its
                spec or existing patch list is not the shape a patch can be added to.
        """
        if not isinstance(formats, dict) or format_name not in formats:
            known = sorted(str(name) for name in formats) if isinstance(formats, dict) else []
            listed = ", ".join(known) if known else "none"
            raise DiagnosticError(
                diagnostic(
                    "ARC-EDT-013",
                    f"The template defines no format {format_name!r} to patch (formats: "
                    f"{listed}). Nothing was changed.",
                    file=str(template_file),
                    hint=(
                        "Set target.format to one of the formats the template defines, or add "
                        "the format to the template first."
                    ),
                )
            )
        spec = formats[format_name]
        patch = spec.get("patch") if isinstance(spec, dict) else None
        if not isinstance(spec, dict) or (patch is not None and not isinstance(patch, list)):
            raise DiagnosticError(
                diagnostic(
                    "ARC-EDT-013",
                    f"formats.{format_name} is not a mapping with a 'patch' list, so no "
                    "override can be added to it. Nothing was changed.",
                    file=str(template_file),
                    keypath=f"formats.{format_name}",
                    hint="Make formats.<name> a mapping; its 'patch' key, if present, is a list.",
                )
            )
        return cls(
            format_name=format_name,
            spec=spec,
            authored_root=authored_root,
            template_file=template_file,
        )

    @property
    def location(self) -> str:
        """The keypath the transaction is confined to, as the report states it."""
        return f"formats.{self.format_name}.patch"

    # ---------------------------------------------------------------------------- commands

    def apply(
        self,
        command: Any,
        *,
        locate: Callable[[str], Any],
        changed_layer_ids: list[str],
    ) -> list[dict[str, Any]]:
        """Write one field or geometry command as override op(s); return the inverse command(s).

        ``locate`` resolves a layer id to its authored node, raising for an unknown id or a
        locked subtree exactly as the shared path does — a lock holds whatever the scope.
        """
        inverses: list[dict[str, Any]] = []
        for write in self._writes_for(command):
            authored = locate(write.layer_id)
            changed_layer_ids.append(write.layer_id)
            if write.remove:
                inverses.append(self._drop_override(write, authored))
            else:
                inverses.append(self._set_override(write, authored))
        return inverses

    def _writes_for(self, command: Any) -> list[_Write]:
        kind = command.kind
        if kind == "set_text":
            return [_Write(command.layer_id, ("text",), command.text)]
        if kind == "set_visibility":
            return [_Write(command.layer_id, ("visible",), command.visible)]
        if kind == "set_effects":
            effects = [
                {"name": effect.name, "params": dict(effect.params), "enabled": effect.enabled}
                for effect in command.effects
            ]
            return [_Write(command.layer_id, ("effects",), effects)]
        if kind == "set_property":
            segments = tuple(command.keypath.split("."))
            if command.remove:
                return [_Write(command.layer_id, segments, remove=True)]
            return [_Write(command.layer_id, segments, copy.deepcopy(command.value))]
        if kind == "translate":
            writes: list[_Write] = []
            for layer_id in command.layer_ids:
                transform = self._effective_node(layer_id).get("transform")
                current = (
                    transform.get("translate", [0.0, 0.0])
                    if isinstance(transform, dict)
                    else [0.0, 0.0]
                )
                writes.append(
                    _Write(
                        layer_id,
                        ("transform", "translate"),
                        [float(current[0]) + command.dx_pt, float(current[1]) + command.dy_pt],
                    )
                )
            return writes
        if kind == "rotate":
            return [_Write(command.layer_id, ("transform", "rotate"), command.degrees)]
        if kind == "resize":
            return [
                _Write(command.layer_id, ("constraints", "size", "w"), f"{command.w_pt:g}pt"),
                _Write(command.layer_id, ("constraints", "size", "h"), f"{command.h_pt:g}pt"),
            ]
        raise DiagnosticError(  # pragma: no cover - check_scope refuses these first
            diagnostic("ARC-EDT-014", f"{kind}: this command cannot be written for one format.")
        )

    # --------------------------------------------------------------------------- overrides

    def _set_override(self, write: _Write, authored: Any) -> dict[str, Any]:
        segments, value = self._narrow(write, authored)
        path = self._path(write.layer_id, segments)
        keypath = ".".join(segments)
        ops = self._ops()
        existing = _op_setting(ops, path)
        if existing is not None:
            previous = copy.deepcopy(_plain(existing.get("value")))
            existing["value"] = value
            inverse = {
                "kind": "set_property",
                "layer_id": write.layer_id,
                "keypath": keypath,
                "value": previous,
            }
        else:
            self._ensure_ops().append(_new_op(path, value))
            inverse = {
                "kind": "set_property",
                "layer_id": write.layer_id,
                "keypath": keypath,
                "remove": True,
            }
        _assign(self._effective_node(write.layer_id), segments, copy.deepcopy(value))
        return inverse

    def _drop_override(self, write: _Write, authored: Any) -> dict[str, Any]:
        segments, _value = self._narrow(write, authored)
        path = self._path(write.layer_id, segments)
        keypath = ".".join(segments)
        ops = self._ops()
        existing = _op_setting(ops, path)
        if ops is None or existing is None:
            # Nothing overrides this path for the format: a no-op, as removing an absent key
            # is in shared scope, and its own inverse.
            return {
                "kind": "set_property",
                "layer_id": write.layer_id,
                "keypath": keypath,
                "remove": True,
            }
        previous = copy.deepcopy(_plain(existing.get("value")))
        ops.remove(existing)
        if not ops:
            # An empty list would read as an interrupted edit, and the compiler ignores it.
            del self._spec["patch"]
        self._rebuild_effective()
        return {
            "kind": "set_property",
            "layer_id": write.layer_id,
            "keypath": keypath,
            "value": previous,
        }

    def _narrow(self, write: _Write, authored: Any) -> tuple[tuple[str, ...], Any]:
        """The deepest op the compiler can apply for this write: its path and its value.

        Every container before the final segment must exist in the authored node; the op is
        written at the first one that does not, carrying the format's effective value there with
        the requested leaf merged in.
        """
        segments = write.segments
        container = authored
        depth = 0
        for segment in segments[:-1]:
            nested = container.get(segment) if isinstance(container, dict) else None
            if not isinstance(nested, dict):
                break
            container = nested
            depth += 1
        if depth == len(segments) - 1:
            return segments, write.value
        head = segments[: depth + 1]
        effective = _read(self._effective_node(write.layer_id), head)
        merged: dict[str, Any] = copy.deepcopy(effective) if isinstance(effective, dict) else {}
        _assign(merged, segments[depth + 1 :], write.value)
        return head, merged

    # --------------------------------------------------------------------------- internals

    def _path(self, layer_id: str, segments: tuple[str, ...]) -> str:
        return ".".join(("nodes", layer_id, *segments))

    def _ops(self) -> Any:
        ops = self._spec.get("patch")
        return ops if isinstance(ops, list) else None

    def _ensure_ops(self) -> Any:
        ops = self._ops()
        if ops is None:
            # A flow-style spec (`square: {canvas: {...}}`) would carry the whole patch list on
            # one wrapped line; block style is how every authored patch list reads.
            if isinstance(self._spec, CommentedMap) and self._spec.fa.flow_style():
                self._spec.fa.set_block_style()
            ops = CommentedSeq()
            self._spec["patch"] = ops
        return ops

    def _effective_node(self, layer_id: str) -> Any:
        location = index_tree(self._effective_root).nodes.get(layer_id)
        if location is None:
            raise DiagnosticError(
                diagnostic(
                    "ARC-EDT-004",
                    f"No node with id {layer_id!r} exists in the authored tree.",
                    hint="Inspect the layer tree for current ids, then retry.",
                )
            )
        return location.node

    def _rebuild_effective(self) -> None:
        """The authored tree as this format sees it: its existing ops applied, in order."""
        self._effective_root = _plain(self._authored_root)
        ops = self._ops()
        if ops:
            apply_patches(
                self._effective_root,
                _plain(list(ops)),
                f"format:{self.format_name}",
                self._template_file,
                self.location,
                PatchLog(),
            )


# ------------------------------------------------------------------------------------ helpers


def _op_setting(ops: Any, path: str) -> Any:
    if not isinstance(ops, list):
        return None
    for op in ops:
        if isinstance(op, dict) and op.get("set") == path:
            return op
    return None


def _new_op(path: str, value: Any) -> Any:
    op = CommentedMap()
    op["set"] = path
    op["value"] = value
    scalar = value is None or isinstance(value, (str, int, float, bool))
    if scalar and len(str(value)) <= _FLOW_SCALAR_LIMIT:
        op.fa.set_flow_style()
    return op


def _read(node: Any, segments: tuple[str, ...]) -> Any:
    current = node
    for segment in segments:
        if not isinstance(current, dict) or segment not in current:
            return None
        current = current[segment]
    return current


def _assign(node: Any, segments: tuple[str, ...], value: Any) -> None:
    current = node
    for segment in segments[:-1]:
        nested = current.get(segment)
        if not isinstance(nested, dict):
            nested = {}
            current[segment] = nested
        current = nested
    current[segments[-1]] = value


def _plain(value: Any) -> Any:
    """Reduce ruamel containers to plain JSON-shaped data."""
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value
