"""Property tests for the editor contract: what survives the wire, and what never gets through.

A transaction crosses a process boundary twice — desktop to engine as JSON, engine to desktop as
an inverse it will later send back — so equality after a round trip is not a formality. If a float
or a nested effect param drifts, undo replays something subtly different from what was undone.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from arcavex.kernel.editor import SemanticTransaction, parse_command

_PROJECT_PATH = str(Path(Path(__file__).anchor) / "arcavex-property-project")

_layer_ids = st.text(
    alphabet=st.characters(min_codepoint=48, max_codepoint=122), min_size=1, max_size=24
)
# Single-precision values so the JSON text round-trips exactly rather than through a shortest-repr
# that a 64-bit float can lose; the bounds are chosen to be exactly representable at that width.
_finite = st.floats(allow_nan=False, allow_infinity=False, width=32)
_extent = st.floats(
    min_value=0.0078125, max_value=1048576.0, allow_nan=False, allow_infinity=False, width=32
)


def _commands() -> st.SearchStrategy[dict[str, Any]]:
    return st.one_of(
        st.builds(
            lambda layer, text: {"kind": "set_text", "layer_id": layer, "text": text},
            _layer_ids,
            st.text(max_size=80),
        ),
        st.builds(
            lambda layers, dx, dy: {
                "kind": "translate",
                "layer_ids": layers,
                "dx_pt": dx,
                "dy_pt": dy,
            },
            st.lists(_layer_ids, min_size=1, max_size=4),
            _finite,
            _finite,
        ),
        st.builds(
            lambda layer, w, h: {"kind": "resize", "layer_id": layer, "w_pt": w, "h_pt": h},
            _layer_ids,
            _extent,
            _extent,
        ),
        st.builds(
            lambda layer, degrees: {"kind": "rotate", "layer_id": layer, "degrees": degrees},
            _layer_ids,
            _finite,
        ),
        st.builds(
            lambda layer, parent, index: {
                "kind": "reorder",
                "layer_id": layer,
                "parent_id": parent,
                "index": index,
            },
            _layer_ids,
            _layer_ids,
            st.integers(min_value=0, max_value=64),
        ),
        st.builds(
            lambda layer, name, params: {
                "kind": "set_effects",
                "layer_id": layer,
                "effects": [{"name": name, "params": params}],
            },
            _layer_ids,
            _layer_ids,
            st.dictionaries(
                st.text(min_size=1, max_size=8), st.one_of(_finite, st.booleans()), max_size=4
            ),
        ),
    )


@given(payload=_commands())
def test_a_command_survives_a_json_round_trip_unchanged(payload: dict[str, Any]) -> None:
    command = parse_command(payload)

    assert parse_command(json.loads(command.model_dump_json())) == command


@given(commands=st.lists(_commands(), min_size=1, max_size=6))
def test_a_transaction_survives_a_json_round_trip_unchanged(
    commands: list[dict[str, Any]],
) -> None:
    """The inverse the engine returns is re-submitted verbatim, so this is the undo path."""
    transaction = SemanticTransaction.model_validate(
        {
            "command_id": "9f2c1d7e-4b3a-4c58-9e21-0d7a6f5b8c34",
            "project_path": _PROJECT_PATH,
            "base_project_revision": "a1" * 32,
            "actor": {"id": "property"},
            "commands": commands,
        }
    )

    restored = SemanticTransaction.model_validate(json.loads(transaction.model_dump_json()))

    assert restored == transaction


@given(
    payload=_commands(),
    key=st.text(
        alphabet=st.characters(min_codepoint=97, max_codepoint=122), min_size=1, max_size=8
    ),
)
def test_an_undeclared_key_is_always_refused(payload: dict[str, Any], key: str) -> None:
    """Silently dropping an unrecognized field would edit something other than what was asked."""
    if key in payload:
        return
    with pytest.raises(ValidationError):
        parse_command({**payload, key: "unexpected"})


@given(bad=st.sampled_from([math.nan, math.inf, -math.inf]), layer=_layer_ids)
def test_no_geometry_command_accepts_a_non_finite_number(bad: float, layer: str) -> None:
    for payload in (
        {"kind": "translate", "layer_ids": [layer], "dx_pt": bad, "dy_pt": 0.0},
        {"kind": "resize", "layer_id": layer, "w_pt": bad, "h_pt": 1.0},
        {"kind": "rotate", "layer_id": layer, "degrees": bad},
    ):
        with pytest.raises(ValidationError):
            parse_command(payload)
