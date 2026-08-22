"""The editor service: where every Phase 2 guarantee composes into one execution path.

``apply`` takes a semantic transaction and runs the whole gauntlet under the project mutation
lock: fresh snapshot, revision guard, policy gate, command dispatch onto the authored AST,
compile-validation of the staged result, atomic replacement, and a history record carrying the
engine-authored inverse. A refusal at any stage leaves the project byte-identical and comes back
as a report, never an exception.

Two properties matter more than any single step:

- **The inverse restores bytes, not just meaning.** Undo must return the project to the exact
  revision the history entry recorded, or the redo chain breaks — so inverses are raw
  restorations (`set_property` of the prior authored value, `splice_children` of the prior
  entries) rather than semantic opposites that would leave an equivalent-but-different file.
- **Validation runs against the staged state.** The compiler sees the project as it would look
  after the transaction; only a staged state that compiles for the active target is allowed to
  replace the live one.

Editing addresses the *project-local* template. A library-pinned template is shared, versioned,
and read-only by design; editing it in place would change every project that pins it, so those
commands are refused with a pointer at ``project clone``.
"""

from __future__ import annotations

import copy
import io
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from arcavex.kernel.api import LayerUIMetadata
from arcavex.kernel.diagnostics import Diagnostic, DiagnosticError, diagnostic
from arcavex.kernel.editor import (
    COMMAND_KINDS,
    Actor,
    ChangedPath,
    ConflictDetail,
    HistoryReport,
    SemanticTransaction,
    TransactionReport,
)
from arcavex.services.editor.conflicts import conflict_between, remember_manifest
from arcavex.services.editor.history import HistoryStore
from arcavex.services.editor.locking import editor_lock
from arcavex.services.editor.source_map import index_tree, unwrap
from arcavex.services.editor.transaction import StagedWrite, apply_staged_writes
from arcavex.services.editor.tree import (
    delete_nodes,
    duplicate_node,
    group_nodes,
    reorder_node,
    reparent_node,
)
from arcavex.services.project_policy import ProjectPolicyService
from arcavex.services.project_snapshot import ProjectSnapshotService
from arcavex.services.projects import ProjectService
from arcavex.services.proposals import ProposalService
from arcavex.services.template.loader import load_yaml

#: Validates a staged project state for one target: (staged_root, format, locale) -> diagnostics.
StagedValidator = Callable[[Path, str | None, str | None], list[Diagnostic]]


@dataclass
class _Execution:
    """What one dispatch pass produces before anything touches the live project."""

    template_bytes: bytes
    inverse_commands: list[Any]
    changed_layer_ids: list[str]
    display_names: dict[str, str | None]


class EditorService:
    """Executes semantic transactions against one project at a time."""

    def __init__(
        self,
        projects: ProjectService,
        snapshots: ProjectSnapshotService,
        policies: ProjectPolicyService,
        proposals: ProposalService,
        validate_staged: StagedValidator,
    ) -> None:
        self._projects = projects
        self._snapshots = snapshots
        self._policies = policies
        self._proposals = proposals
        self._validate_staged = validate_staged

    # ------------------------------------------------------------------------------ public API

    def apply(self, payload: dict[str, Any]) -> TransactionReport:
        """Validate and execute one transaction. Never raises."""
        try:
            transaction = SemanticTransaction.model_validate(payload)
        except ValidationError as error:
            return TransactionReport(
                ok=False,
                diagnostics=[
                    diagnostic("ARC-EDT-010", _malformed_message(error), hint=_malformed_hint())
                ],
            )
        return self._apply_transaction(transaction, gate_policy=True, record_history=True)

    def apply_authorized(self, project: Path, command_id: str) -> TransactionReport:
        """Execute a proposal a person has authorized, under a fresh revision check."""
        listed = self._proposals.list_proposals(project=project)
        match = next(
            (p for p in listed.proposals if str(p.command_id) == command_id.lower()), None
        )
        if match is None or match.state != "authorized":
            return TransactionReport(
                ok=False,
                diagnostics=[
                    diagnostic(
                        "ARC-PRJ-012",
                        f"No authorized proposal {command_id!r} to execute.",
                        hint="List proposals, approve the pending command, then execute it.",
                    )
                ],
            )
        return self.apply_bypassing_policy(dict(match.command_payload))

    def apply_bypassing_policy(self, payload: dict[str, Any]) -> TransactionReport:
        """Execute without the policy gate — for authorized proposals and history replay."""
        try:
            transaction = SemanticTransaction.model_validate(payload)
        except ValidationError:
            return TransactionReport(
                ok=False,
                diagnostics=[
                    diagnostic(
                        "ARC-EDT-010",
                        "The stored command payload is not a valid editor transaction.",
                        hint="Re-submit the edit against the current project revision.",
                    )
                ],
            )
        return self._apply_transaction(transaction, gate_policy=False, record_history=True)

    def undo(self, project: Path) -> TransactionReport:
        """Apply the engine-authored inverse of the newest applied history entry."""
        return self._replay(project, direction="undo")

    def redo(self, project: Path) -> TransactionReport:
        """Re-apply the forward transaction of the oldest undone history entry."""
        return self._replay(project, direction="redo")

    def history(self, project: Path) -> HistoryReport:
        """The undo/redo state as MCP and the desktop report it. Never raises."""
        try:
            loaded = self._projects.load(Path(project))
            snapshot = self._snapshots.snapshot(project=loaded.root)
            revision = snapshot.project_revision or ""
            state = HistoryStore(loaded.root).state(current_revision=revision)
        except DiagnosticError as error:
            return HistoryReport(ok=False, diagnostics=list(error.diagnostics))
        return HistoryReport(
            ok=True,
            canonical_path=str(loaded.root.resolve()),
            entries=state.entries,
            can_undo=state.can_undo,
            can_redo=state.can_redo,
            branched_by_external_edit=state.branched_by_external_edit,
            diagnostics=list(state.diagnostics),
        )

    # ------------------------------------------------------------------------------- execution

    def _apply_transaction(
        self, transaction: SemanticTransaction, *, gate_policy: bool, record_history: bool
    ) -> TransactionReport:
        try:
            loaded = self._projects.load(Path(transaction.project_path))
        except DiagnosticError as error:
            return TransactionReport(
                ok=False,
                command_id=transaction.command_id,
                diagnostics=list(error.diagnostics),
            )
        root = loaded.root

        try:
            with editor_lock(root):
                return self._apply_locked(
                    root, transaction, gate_policy=gate_policy, record_history=record_history
                )
        except DiagnosticError as error:
            return TransactionReport(
                ok=False,
                command_id=transaction.command_id,
                canonical_path=str(root.resolve()),
                diagnostics=list(error.diagnostics),
            )

    def _apply_locked(
        self,
        root: Path,
        transaction: SemanticTransaction,
        *,
        gate_policy: bool,
        record_history: bool,
    ) -> TransactionReport:
        canonical = str(root.resolve())
        fresh = self._snapshots.snapshot(project=root)
        if not fresh.ok or fresh.project_revision is None:
            return TransactionReport(
                ok=False,
                command_id=transaction.command_id,
                canonical_path=canonical,
                diagnostics=list(fresh.diagnostics),
            )
        remember_manifest(root, fresh.project_revision, list(fresh.project_manifest))

        conflict = conflict_between(
            root,
            transaction.base_project_revision,
            fresh.project_revision,
            fresh_manifest=list(fresh.project_manifest),
        )
        if conflict is not None:
            return TransactionReport(
                ok=False,
                command_id=transaction.command_id,
                canonical_path=canonical,
                project_revision=fresh.project_revision,
                render_revision=fresh.render_revision,
                conflict=conflict,
                # Also as a diagnostic: a conflict used to arrive with an empty diagnostics list,
                # so a client rendering that list -- which is how every other refusal here
                # arrives -- showed nothing and the edit looked like it had silently done nothing.
                diagnostics=[_conflict_diagnostic(conflict)],
            )

        if gate_policy:
            gated = self._gate(root, transaction, canonical, fresh.project_revision)
            if gated is not None:
                return gated

        try:
            execution = self._execute_commands(root, transaction)
        except DiagnosticError as error:
            return TransactionReport(
                ok=False,
                command_id=transaction.command_id,
                canonical_path=canonical,
                project_revision=fresh.project_revision,
                diagnostics=list(error.diagnostics),
            )

        target = transaction.target
        changed: list[ChangedPath] = []
        touched = ["template.yaml"] if execution.template_bytes else []
        if execution.display_names:
            touched.append("project.ui.yaml")
        before_files = _read_files(root, touched)
        if execution.template_bytes:

            def validate(staged_root: Path) -> None:
                diagnostics = self._validate_staged(staged_root, target.format, target.locale)
                errors = [d for d in diagnostics if d.severity == "error"]
                if errors:
                    raise DiagnosticError(*errors)

            try:
                changed = apply_staged_writes(
                    root,
                    [StagedWrite(relative="template.yaml", content=execution.template_bytes)],
                    validate=validate,
                )
            except DiagnosticError as error:
                return TransactionReport(
                    ok=False,
                    command_id=transaction.command_id,
                    canonical_path=canonical,
                    project_revision=fresh.project_revision,
                    diagnostics=list(error.diagnostics),
                )

        if execution.display_names:
            changed.extend(self._apply_display_names(root, execution.display_names))
        after_files = _read_files(root, touched)

        after = self._snapshots.snapshot(project=root)
        after_revision = after.project_revision or fresh.project_revision
        remember_manifest(root, after_revision, list(after.project_manifest))

        inverse = SemanticTransaction(
            command_id=uuid4(),
            project_path=transaction.project_path,
            base_project_revision=after_revision,
            actor=transaction.actor,
            target=transaction.target,
            # Reversed: undoing restores the last change first, the way it was made.
            commands=list(reversed(execution.inverse_commands)),
        )

        if record_history:
            HistoryStore(root).record(
                forward=transaction,
                inverse=inverse,
                before_project_revision=fresh.project_revision,
                after_project_revision=after_revision,
                summary=_summarize(transaction),
                before_files=before_files,
                after_files=after_files,
            )

        return TransactionReport(
            ok=True,
            command_id=transaction.command_id,
            canonical_path=canonical,
            project_revision=after_revision,
            render_revision=after.render_revision,
            changed=changed,
            changed_layer_ids=sorted(set(execution.changed_layer_ids)),
            inverse=inverse,
        )

    def _gate(
        self,
        root: Path,
        transaction: SemanticTransaction,
        canonical: str,
        revision: str,
    ) -> TransactionReport | None:
        policy = self._policies.get_policy(project=root).policy
        if policy.mode == "unrestricted":
            return None
        if policy.mode == "read_only":
            return TransactionReport(
                ok=False,
                command_id=transaction.command_id,
                canonical_path=canonical,
                project_revision=revision,
                diagnostics=[
                    diagnostic(
                        "ARC-EDT-009",
                        "The project's automation policy is read-only; the edit was refused "
                        "and nothing was changed.",
                        hint="Change the automation mode in project settings to allow edits.",
                    )
                ],
            )
        # Review mode: queue the whole transaction for a person to approve.
        self._proposals.enqueue(
            project=root,
            command_id=str(transaction.command_id),
            base_project_revision=transaction.base_project_revision,
            actor=Actor.model_validate(transaction.actor.model_dump()),
            command_payload=transaction.model_dump(mode="json"),
            created_at=datetime.now(tz=UTC),
        )
        return TransactionReport(
            ok=True,
            command_id=transaction.command_id,
            canonical_path=canonical,
            project_revision=revision,
            queued_command_id=transaction.command_id,
        )

    # -------------------------------------------------------------------------------- dispatch

    def _execute_commands(
        self, root: Path, transaction: SemanticTransaction
    ) -> _Execution:
        loaded = self._projects.load(root)
        template_dir, _ref, is_library = self._projects.resolve_template(loaded)

        touches_template = any(c.kind != "set_display_name" for c in transaction.commands)
        # A template the project does not contain cannot be edited here, whether it is a
        # published library version or a path pointing outside the project directory. Both are
        # shared, and this editor writes only inside the project it was handed -- so the write
        # would land on a new template.yaml *inside* the project, silently creating a second
        # template the project does not use. Left unchecked the staged validation failed first,
        # with "File not found" naming a path inside .arcavex/staging that nobody wrote.
        outside_project = touches_template and not _is_inside(template_dir, root)
        if touches_template and (is_library or outside_project):
            shared = (
                "This project pins a shared library template"
                if is_library
                else f"This project's template lives outside the project ({template_dir})"
            )
            raise DiagnosticError(
                diagnostic(
                    "ARC-EDT-008",
                    f"{shared}, which semantic editing cannot change in place: the edit would "
                    "alter every project that pins it.",
                    hint=(
                        "Copy the template into the project first — 'arcavex template detach' "
                        "(or the arcavex_template_detach tool) — which gives the project its own "
                        "editable template.yaml."
                    ),
                )
            )

        metadata = self._projects.load_ui_metadata(loaded)
        locked_ids = {
            layer_id for layer_id, layer in metadata.layers.items() if layer.locked
        }

        raw = load_yaml(template_dir) if touches_template else None
        tree_root = raw.get("root") if raw is not None and hasattr(raw, "get") else None
        if touches_template and not hasattr(tree_root, "get"):
            raise DiagnosticError(
                diagnostic(
                    "ARC-TPL-004",
                    "Template has no 'root' node to edit",
                    file=str(template_dir),
                    hint="An editable template defines a 'root:' group node.",
                )
            )

        inverse_commands: list[Any] = []
        changed_layer_ids: list[str] = []
        display_names: dict[str, str | None] = {}
        for command in transaction.commands:
            if command.kind == "set_display_name":
                previous = metadata.layers.get(command.layer_id, LayerUIMetadata()).display_name
                display_names[command.layer_id] = command.display_name
                inverse_commands.append(
                    {
                        "kind": "set_display_name",
                        "layer_id": command.layer_id,
                        "display_name": previous,
                    }
                )
                changed_layer_ids.append(command.layer_id)
                continue
            inverse_commands.extend(
                _dispatch(tree_root, command, locked_ids, changed_layer_ids)
            )

        template_bytes = b""
        if touches_template:
            template_bytes = _dump_bytes(raw)

        return _Execution(
            template_bytes=template_bytes,
            inverse_commands=inverse_commands,
            changed_layer_ids=changed_layer_ids,
            display_names=display_names,
        )

    def _apply_display_names(
        self, root: Path, names: dict[str, str | None]
    ) -> list[ChangedPath]:
        loaded = self._projects.load(root)
        metadata = self._projects.load_ui_metadata(loaded)
        layers = dict(metadata.layers)
        for layer_id, display_name in names.items():
            existing = layers.get(layer_id, LayerUIMetadata())
            layers[layer_id] = existing.model_copy(update={"display_name": display_name})
        self._projects.save_ui_metadata(loaded, metadata.model_copy(update={"layers": layers}))
        return [ChangedPath(path="project.ui.yaml", change="modified")]

    # ----------------------------------------------------------------------------- undo / redo

    def _replay(self, project: Path, *, direction: str) -> TransactionReport:
        try:
            loaded = self._projects.load(Path(project))
        except DiagnosticError as error:
            return TransactionReport(ok=False, diagnostics=list(error.diagnostics))
        root = loaded.root

        try:
            with editor_lock(root):
                snapshot = self._snapshots.snapshot(project=root)
                revision = snapshot.project_revision or ""
                store = HistoryStore(root)
                step = (
                    store.undo(current_revision=revision)
                    if direction == "undo"
                    else store.redo(current_revision=revision)
                )
                if step is None:
                    return TransactionReport(
                        ok=False,
                        canonical_path=str(root.resolve()),
                        project_revision=revision,
                        diagnostics=[
                            diagnostic(
                                "ARC-EDT-011",
                                f"Nothing to {direction}: the history is empty here, or an "
                                "external edit moved the project past it.",
                                hint="Check the activity stream for the external change.",
                            )
                        ],
                    )
                writes = [
                    StagedWrite(relative=relative, content=content)
                    for relative, content in step.restore_files.items()
                ]
                # Restoring recorded bytes needs no compile gate: this state existed and was
                # validated when it was live.
                changed = apply_staged_writes(root, writes)
                restored_snapshot = self._snapshots.snapshot(project=root)
                restored = restored_snapshot.project_revision or revision
                remember_manifest(root, restored, list(restored_snapshot.project_manifest))
                if direction == "undo":
                    store.mark_undone(step.entry.command_id, restored_revision=restored)
                else:
                    store.mark_redone(step.entry.command_id, restored_revision=restored)
                return TransactionReport(
                    ok=True,
                    command_id=step.entry.command_id,
                    canonical_path=str(root.resolve()),
                    project_revision=restored,
                    render_revision=restored_snapshot.render_revision,
                    changed=changed,
                )
        except DiagnosticError as error:
            return TransactionReport(
                ok=False,
                canonical_path=str(root.resolve()),
                diagnostics=list(error.diagnostics),
            )


# ------------------------------------------------------------------------------------ dispatch


def _is_inside(candidate: Path, root: Path) -> bool:
    """True when ``candidate`` is the project directory or lives under it."""
    try:
        candidate.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _conflict_diagnostic(conflict: ConflictDetail) -> Diagnostic:
    """State a revision conflict in the same shape as every other refusal on this surface."""
    moved = ", ".join(f"{changed.path} ({changed.change})" for changed in conflict.changed)
    detail = f" Changed since: {moved}." if moved else ""
    return diagnostic(
        "ARC-EDT-012",
        "The project moved under this edit, so nothing was changed."
        f"{detail}",
        hint=(
            "Re-read the project, compose the edit against the current revision, and re-submit."
        ),
    )


def _malformed_message(error: ValidationError) -> str:
    """Name every problem with a submitted transaction, in one answer.

    A caller composing a transaction has no schema in front of it: the MCP tool catalog carries
    the tool's name, not the field names of the payload. A count of validation errors is
    therefore unusable — worse than unusable, because adding a correct field uncovers nested
    errors and pushes the count *up*, which reads as moving away from success.

    So each problem is reported as ``field: what is wrong``, and nothing else is needed to fix it.
    """
    problems: list[str] = []
    for detail in error.errors():
        location = ".".join(str(part) for part in detail.get("loc", ())) or "(payload)"
        problems.append(f"{location}: {detail.get('msg', 'is invalid')}")

    # Nested command errors repeat per union member; the same field said twice helps nobody.
    unique: list[str] = []
    for problem in problems:
        if problem not in unique:
            unique.append(problem)

    listed = "; ".join(unique[:12])
    if len(unique) > 12:
        listed += f"; and {len(unique) - 12} more"
    return f"Invalid editor transaction; nothing was executed. {listed}"


def _malformed_hint() -> str:
    """The shape of a transaction, so a caller can compose one without guessing."""
    return (
        "A transaction is {command_id: <uuid>, project_path: <absolute path>, "
        "base_project_revision: <revision from project_snapshot>, actor: {id: <string>}, "
        "target: {format: <name>, locale: <name or null>}, commands: [{kind: <command>, ...}]}. "
        f"Command kinds: {', '.join(sorted(COMMAND_KINDS))}."
    )


def _dispatch(
    tree_root: Any,
    command: Any,
    locked_ids: set[str],
    changed_layer_ids: list[str],
) -> list[dict[str, Any]]:
    """Apply one command to the AST and return the raw inverse command payload(s)."""
    kind = command.kind
    if kind in {"set_text", "set_property", "set_visibility", "set_effects"}:
        return _apply_field_command(tree_root, command, locked_ids, changed_layer_ids)
    if kind in {"translate", "resize", "rotate"}:
        return _apply_geometry_command(tree_root, command, locked_ids, changed_layer_ids)
    return _apply_structural_command(tree_root, command, locked_ids, changed_layer_ids)


def _located_node(tree_root: Any, layer_id: str, locked_ids: set[str]) -> Any:
    tree = index_tree(tree_root)
    location = tree.nodes.get(layer_id)
    if location is None:
        raise DiagnosticError(
            diagnostic(
                "ARC-EDT-004",
                f"No node with id {layer_id!r} exists in the authored tree.",
                hint="Inspect the layer tree for current ids, then retry.",
            )
        )
    chain = [layer_id]
    current = location
    while current.parent_id is not None:
        chain.append(current.parent_id)
        current = tree.nodes[current.parent_id]
    held = [node_id for node_id in chain if node_id in locked_ids]
    if held:
        raise DiagnosticError(
            diagnostic(
                "ARC-EDT-006",
                f"Layer {layer_id!r} is protected by a lock on {held[0]!r}.",
                hint="Unlock the layer in the Layers panel, or edit something else.",
            )
        )
    return location.node


def _restore_field(layer_id: str, keypath: str, node: Any) -> dict[str, Any]:
    """A raw restoration of one top-level field: exact bytes back on undo."""
    head = keypath.split(".", 1)[0]
    if head in node:
        return {
            "kind": "set_property",
            "layer_id": layer_id,
            "keypath": head,
            "value": copy.deepcopy(_plain(node[head])),
        }
    return {"kind": "set_property", "layer_id": layer_id, "keypath": head, "remove": True}


def _apply_field_command(
    tree_root: Any, command: Any, locked_ids: set[str], changed_layer_ids: list[str]
) -> list[dict[str, Any]]:
    node = _located_node(tree_root, command.layer_id, locked_ids)
    changed_layer_ids.append(command.layer_id)

    if command.kind == "set_text":
        inverse = _restore_field(command.layer_id, "text", node)
        node["text"] = command.text
        return [inverse]
    if command.kind == "set_visibility":
        inverse = _restore_field(command.layer_id, "visible", node)
        node["visible"] = command.visible
        return [inverse]
    if command.kind == "set_effects":
        inverse = _restore_field(command.layer_id, "effects", node)
        if command.effects:
            node["effects"] = [
                {"name": effect.name, "params": dict(effect.params), "enabled": effect.enabled}
                for effect in command.effects
            ]
        else:
            node.pop("effects", None)
        return [inverse]

    # set_property
    inverse = _restore_field(command.layer_id, command.keypath, node)
    if command.remove:
        _remove_keypath(node, command.keypath)
    else:
        _set_keypath(node, command.keypath, copy.deepcopy(command.value))
    return [inverse]


def _apply_geometry_command(
    tree_root: Any, command: Any, locked_ids: set[str], changed_layer_ids: list[str]
) -> list[dict[str, Any]]:
    layer_ids = command.layer_ids if command.kind == "translate" else [command.layer_id]
    inverses: list[dict[str, Any]] = []
    for layer_id in layer_ids:
        node = _located_node(tree_root, layer_id, locked_ids)
        changed_layer_ids.append(layer_id)
        if command.kind == "translate":
            inverses.append(_restore_field(layer_id, "transform", node))
            transform = node.setdefault("transform", {})
            current = transform.get("translate", [0.0, 0.0])
            transform["translate"] = [
                float(current[0]) + command.dx_pt,
                float(current[1]) + command.dy_pt,
            ]
        elif command.kind == "rotate":
            inverses.append(_restore_field(layer_id, "transform", node))
            transform = node.setdefault("transform", {})
            transform["rotate"] = command.degrees
        else:  # resize
            inverses.append(_restore_field(layer_id, "constraints", node))
            constraints = node.setdefault("constraints", {})
            size = constraints.setdefault("size", {})
            size["w"] = f"{command.w_pt:g}pt"
            size["h"] = f"{command.h_pt:g}pt"
    return inverses


def _apply_structural_command(
    tree_root: Any, command: Any, locked_ids: set[str], changed_layer_ids: list[str]
) -> list[dict[str, Any]]:
    tree = index_tree(tree_root)

    if command.kind == "reorder":
        location = tree.nodes.get(command.layer_id)
        if location is None:
            raise _unknown(command.layer_id)
        previous_index = location.index
        reorder_node(tree_root, command.layer_id, parent_id=command.parent_id, index=command.index)
        changed_layer_ids.append(command.layer_id)
        return [
            {
                "kind": "reorder",
                "layer_id": command.layer_id,
                "parent_id": command.parent_id,
                "index": previous_index,
            }
        ]

    if command.kind == "reparent":
        location = tree.nodes.get(command.layer_id)
        if location is None:
            raise _unknown(command.layer_id)
        previous_parent = location.parent_id
        previous_index = location.index
        _require_unlocked_ids(tree_root, [command.layer_id], locked_ids)
        reparent_node(
            tree_root, command.layer_id, parent_id=command.parent_id, index=command.index
        )
        changed_layer_ids.append(command.layer_id)
        return [
            {
                "kind": "reparent",
                "layer_id": command.layer_id,
                "parent_id": previous_parent,
                "index": previous_index,
            }
        ]

    if command.kind == "delete":
        entries: list[tuple[str, int, Any]] = []
        for layer_id in command.layer_ids:
            location = tree.nodes.get(layer_id)
            if location is None:
                raise _unknown(layer_id)
            if location.parent_id is None:
                _root_refusal()
            entries.append(
                (location.parent_id or "", location.index, copy.deepcopy(_plain(location.entry)))
            )
        delete_nodes(tree_root, list(command.layer_ids), locked_ids=locked_ids)
        changed_layer_ids.extend(command.layer_ids)
        return [
            {
                "kind": "splice_children",
                "parent_id": parent_id,
                "index": index,
                "remove_count": 0,
                "entries": [entry],
            }
            for parent_id, index, entry in entries
        ]

    if command.kind == "duplicate":
        renames = duplicate_node(tree_root, command.layer_id)
        new_root_id = renames[command.layer_id]
        changed_layer_ids.append(new_root_id)
        return [{"kind": "delete", "layer_ids": [new_root_id]}]

    if command.kind == "group":
        locations = [tree.nodes.get(layer_id) for layer_id in command.layer_ids]
        if any(location is None for location in locations):
            missing = next(
                layer
                for layer, location in zip(command.layer_ids, locations, strict=True)
                if location is None
            )
            raise _unknown(missing)
        originals = [
            copy.deepcopy(_plain(location.entry)) for location in locations if location
        ]
        first_index = min(location.index for location in locations if location)
        parent_id = locations[0].parent_id if locations[0] else None
        group_nodes(tree_root, list(command.layer_ids), group_id=command.group_id)
        changed_layer_ids.extend([*command.layer_ids, command.group_id])
        return [
            {
                "kind": "splice_children",
                "parent_id": parent_id or "",
                "index": first_index,
                "remove_count": 1,
                "entries": originals,
            }
        ]

    # splice_children: the generic restore, and its own inverse is the slice it replaces.
    location = tree.nodes.get(command.parent_id)
    if location is None:
        raise _unknown(command.parent_id)
    children = location.node.get("children")
    if not isinstance(children, list):
        children = []
        location.node["children"] = children
    removed = [
        copy.deepcopy(_plain(entry))
        for entry in children[command.index : command.index + command.remove_count]
    ]
    children[command.index : command.index + command.remove_count] = [
        copy.deepcopy(entry) for entry in command.entries
    ]
    for entry in command.entries:
        node = unwrap(entry)
        if isinstance(node, dict) and isinstance(node.get("id"), str):
            changed_layer_ids.append(node["id"])
    return [
        {
            "kind": "splice_children",
            "parent_id": command.parent_id,
            "index": command.index,
            "remove_count": len(command.entries),
            "entries": removed,
        }
    ]


def _require_unlocked_ids(tree_root: Any, layer_ids: list[str], locked_ids: set[str]) -> None:
    for layer_id in layer_ids:
        _located_node(tree_root, layer_id, locked_ids)


def _root_refusal() -> None:
    raise DiagnosticError(
        diagnostic(
            "ARC-EDT-005",
            "The root node cannot be deleted.",
            hint="This operation is never valid; nothing was changed.",
        )
    )


def _unknown(layer_id: str) -> DiagnosticError:
    return DiagnosticError(
        diagnostic(
            "ARC-EDT-004",
            f"No node with id {layer_id!r} exists in the authored tree.",
            hint="Inspect the layer tree for current ids, then retry.",
        )
    )


def _set_keypath(node: Any, keypath: str, value: Any) -> None:
    parts = keypath.split(".")
    current = node
    for part in parts[:-1]:
        nested = current.get(part)
        if not isinstance(nested, dict):
            nested = {}
            current[part] = nested
        current = nested
    current[parts[-1]] = value


def _remove_keypath(node: Any, keypath: str) -> None:
    parts = keypath.split(".")
    current = node
    for part in parts[:-1]:
        nested = current.get(part)
        if not isinstance(nested, dict):
            return
        current = nested
    current.pop(parts[-1], None)


def _plain(value: Any) -> Any:
    """Reduce ruamel containers to plain JSON-shaped data for storage in a transaction."""
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def _dump_bytes(raw: Any) -> bytes:
    from arcavex.services.template.loader import _yaml  # round-trip settings shared with dump_yaml

    buffer = io.BytesIO()
    _yaml().dump(raw, buffer)
    return buffer.getvalue()


def _summarize(transaction: SemanticTransaction) -> str:
    kinds = [command.kind.replace("_", " ") for command in transaction.commands]
    if len(kinds) == 1:
        return kinds[0]
    return f"{len(kinds)} edits: {', '.join(dict.fromkeys(kinds))}"


def _read_files(root: Path, relatives: list[str]) -> dict[str, bytes | None]:
    """Exact current bytes per path; ``None`` records that the file does not exist."""
    files: dict[str, bytes | None] = {}
    for relative in relatives:
        path = root / relative
        files[relative] = path.read_bytes() if path.is_file() else None
    return files
