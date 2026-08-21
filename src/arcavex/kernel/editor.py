"""Semantic editor contracts: the typed vocabulary every project mutation travels in.

Phase 1 could queue a proposal but not execute one, so its payload was an opaque dict. Executing
mutations changes what the boundary has to guarantee, and these models are that guarantee:

- **A command says what to change, never how.** `set_text`, `reorder`, `group` — not "write these
  bytes at this line". The engine owns stable IDs, YAML shape, and anchor validity; a client that
  had to know them could not stay correct across an engine release.
- **A transaction is the unit of undo.** Moving three selected layers is one transaction with one
  inverse, not three edits a user has to undo three times.
- **Every envelope carries the revision it was composed against.** Without it the engine cannot
  tell a legitimate edit from one written against a project someone else has since changed, and
  last-write-wins silently destroys work.
- **Unknown keys are refused.** A misspelled field that is quietly dropped edits the wrong thing
  and reports success.

This module is kernel code: pydantic only, no services, no filesystem. It defines the contract;
`services.editor` executes it.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal, get_args

from pydantic import (
    UUID4,
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    field_validator,
)

#: Bumped when an existing command or report shape changes meaning, so a desktop built against an
#: older engine can refuse rather than misinterpret.
EDITOR_CONTRACT_VERSION = 1

#: A 64-character lowercase hex digest, the form every project and render revision takes.
_REVISION_PATTERN = r"^[0-9a-f]{64}$"

_Revision = Annotated[str, Field(pattern=_REVISION_PATTERN)]

#: A stable authored identifier. Instance ids (`title#0`) address rendered rows, not authored
#: nodes, so a mutation always names the authored id.
_LayerId = Annotated[str, Field(min_length=1)]

#: A positive extent in points. Zero or negative is not a resize.
_Extent = Annotated[FiniteFloat, Field(gt=0.0)]


class Actor(BaseModel):
    """Who submitted a mutation.

    Extra keys are allowed: an MCP client may carry its own identity fields, and the engine's job
    is to record them in history, not to have anticipated them.
    """

    model_config = ConfigDict(frozen=True, extra="allow")

    id: str = Field(min_length=1)
    display_name: str | None = None


class EditorTarget(BaseModel):
    """The format and locale a mutation is composed against.

    Structural edits apply to the authored document regardless of target, but validation and the
    render check that gate a commit need to know which target the user was looking at.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    format: str | None = None
    locale: str | None = None


# ---------------------------------------------------------------------------------- the commands


class _Command(BaseModel):
    """Shared configuration: frozen, and no key the model does not declare."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class SetTextCommand(_Command):
    """Replace the authored text of one text node."""

    kind: Literal["set_text"]
    layer_id: _LayerId
    text: str


class SetPropertyCommand(_Command):
    """Set one authored property, addressed by keypath relative to the node.

    The value stays `Any` because the property space is the template schema's, not this module's;
    the executing service validates it against the node kind before anything is written.
    """

    kind: Literal["set_property"]
    layer_id: _LayerId
    keypath: str = Field(min_length=1)
    value: Any = None


class SetVisibilityCommand(_Command):
    """Show or hide one node without deleting it."""

    kind: Literal["set_visibility"]
    layer_id: _LayerId
    visible: bool


class TranslateCommand(_Command):
    """Move one or more nodes by the same offset, which is what dragging a selection means."""

    kind: Literal["translate"]
    layer_ids: list[_LayerId] = Field(min_length=1)
    dx_pt: FiniteFloat
    dy_pt: FiniteFloat


class ResizeCommand(_Command):
    """Set the box of one node in points."""

    kind: Literal["resize"]
    layer_id: _LayerId
    w_pt: _Extent
    h_pt: _Extent


class RotateCommand(_Command):
    """Set the absolute rotation of one node in degrees."""

    kind: Literal["rotate"]
    layer_id: _LayerId
    degrees: FiniteFloat


class ReorderCommand(_Command):
    """Move a node to a new index among its siblings.

    The index is a position in the authored parent's child list. The desktop shows topmost-first
    paint order and converts; the engine never guesses which direction the caller meant.
    """

    kind: Literal["reorder"]
    layer_id: _LayerId
    parent_id: _LayerId
    index: int = Field(ge=0)


class ReparentCommand(_Command):
    """Move a node under a different parent at an explicit index."""

    kind: Literal["reparent"]
    layer_id: _LayerId
    parent_id: _LayerId
    index: int = Field(ge=0)


class DuplicateCommand(_Command):
    """Copy a node and its subtree, giving every copy a fresh stable id."""

    kind: Literal["duplicate"]
    layer_id: _LayerId


class DeleteCommand(_Command):
    """Remove one or more nodes and their subtrees."""

    kind: Literal["delete"]
    layer_ids: list[_LayerId] = Field(min_length=1)


class GroupCommand(_Command):
    """Wrap a set of siblings in a new group node."""

    kind: Literal["group"]
    layer_ids: list[_LayerId] = Field(min_length=1)
    group_id: _LayerId


class SetDisplayNameCommand(_Command):
    """Rename a layer for people.

    The stable id is a technical identifier that anchors, patches, and AI references depend on, so
    renaming is deliberately a separate, non-structural change to UI metadata.
    """

    kind: Literal["set_display_name"]
    layer_id: _LayerId
    display_name: str | None = None


class EffectSpec(BaseModel):
    """One effect entry in a node's effect list."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class SetEffectsCommand(_Command):
    """Replace a node's whole effect list, which is how ordering changes stay expressible."""

    kind: Literal["set_effects"]
    layer_id: _LayerId
    effects: list[EffectSpec] = Field(default_factory=list)


EditorCommand = Annotated[
    (
        SetTextCommand
        | SetPropertyCommand
        | SetVisibilityCommand
        | TranslateCommand
        | ResizeCommand
        | RotateCommand
        | ReorderCommand
        | ReparentCommand
        | DuplicateCommand
        | DeleteCommand
        | GroupCommand
        | SetDisplayNameCommand
        | SetEffectsCommand
    ),
    Field(discriminator="kind"),
]

#: Every kind the union accepts, derived from the union itself so the two cannot drift.
COMMAND_KINDS: tuple[str, ...] = tuple(
    get_args(member.model_fields["kind"].annotation)[0]
    for member in get_args(get_args(EditorCommand)[0])
)


class _CommandEnvelope(BaseModel):
    """Adapter that gives the bare union a validating entry point."""

    model_config = ConfigDict(frozen=True)

    command: EditorCommand


def parse_command(payload: dict[str, Any]) -> Any:
    """Validate one command payload into its typed model.

    Raises:
        pydantic.ValidationError: when the kind is unknown or the payload does not fit it.
    """
    return _CommandEnvelope.model_validate({"command": payload}).command


# --------------------------------------------------------------------------------- the envelope


class SemanticTransaction(BaseModel):
    """One atomic set of commands, composed against one project revision.

    Everything needed to decide whether the mutation may run travels with it, so the engine never
    has to consult ambient state to answer "is this still safe?".
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal[1] = 1
    command_id: UUID4
    project_path: str
    base_project_revision: _Revision
    actor: Actor
    target: EditorTarget = Field(default_factory=EditorTarget)
    commands: list[EditorCommand] = Field(min_length=1)

    @field_validator("project_path")
    @classmethod
    def _canonical_project_path(cls, value: str) -> str:
        path = Path(value)
        if not path.is_absolute() or str(path.resolve()) != value:
            raise ValueError("project_path must be a canonical absolute path")
        return value


# ---------------------------------------------------------------------------------- the reports

#: What happened to a file. `modified` covers a rewritten file; `created` and `deleted` exist so a
#: caller can tell a new override layer from an edited one.
ChangeKind = Literal["created", "modified", "deleted"]


class ChangedPath(BaseModel):
    """One project-relative path a transaction touched."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str = Field(min_length=1)
    change: ChangeKind = "modified"


class ConflictDetail(BaseModel):
    """Why a mutation was refused, in enough detail to show the user what moved underneath them."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    expected_project_revision: _Revision
    actual_project_revision: _Revision
    changed: list[ChangedPath] = Field(default_factory=list)
    layer_ids: list[str] = Field(default_factory=list)


class TransactionReport(BaseModel):
    """The result of submitting one transaction. Never raises; a refusal is a report."""

    model_config = ConfigDict(frozen=True)

    response_version: int = 1
    contract_version: int = EDITOR_CONTRACT_VERSION
    ok: bool
    command_id: UUID4 | None = None
    canonical_path: str | None = None
    project_revision: str | None = None
    render_revision: str | None = None
    changed: list[ChangedPath] = Field(default_factory=list)
    changed_layer_ids: list[str] = Field(default_factory=list)
    #: The transaction that undoes this one. Authored by the engine, because only the engine knows
    #: the previous authored state.
    inverse: SemanticTransaction | None = None
    #: Present exactly when the mutation was refused for a revision conflict.
    conflict: ConflictDetail | None = None
    #: Present when a review-mode policy queued the command instead of executing it.
    queued_command_id: UUID4 | None = None
    diagnostics: list[Any] = Field(default_factory=list)


class HistoryEntry(BaseModel):
    """One applied transaction, as history shows it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    command_id: UUID4
    actor: Actor
    summary: str
    before_project_revision: _Revision
    after_project_revision: _Revision
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _aware_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a timezone")
        return value


class HistoryReport(BaseModel):
    """The undo/redo state of one project."""

    model_config = ConfigDict(frozen=True)

    response_version: int = 1
    contract_version: int = EDITOR_CONTRACT_VERSION
    ok: bool
    canonical_path: str | None = None
    entries: list[HistoryEntry] = Field(default_factory=list)
    can_undo: bool = False
    can_redo: bool = False
    #: True when an edit from outside this history ended the redo line. Replaying across someone
    #: else's work would overwrite it, so redo stops rather than guessing.
    branched_by_external_edit: bool = False
    diagnostics: list[Any] = Field(default_factory=list)
