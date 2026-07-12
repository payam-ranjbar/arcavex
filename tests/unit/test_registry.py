"""Registry duplicate-detection and lookup tests."""

from __future__ import annotations

import pytest

from arcavex.kernel.diagnostics import DiagnosticError
from arcavex.kernel.registry import Registries, Registry


class _Fake:
    def __init__(self, tag: str) -> None:
        self.tag = tag


def test_register_and_get() -> None:
    reg: Registry[_Fake] = Registry("thing")
    item = _Fake("a")
    reg.register("a", item)
    assert reg.get("a") is item
    assert reg.has("a")
    assert reg.names() == ["a"]


def test_duplicate_names_both() -> None:
    reg: Registry[_Fake] = Registry("thing")
    reg.register("dup", _Fake("first"))
    with pytest.raises(DiagnosticError) as exc:
        reg.register("dup", _Fake("second"))
    diag = exc.value.diagnostics[0]
    assert diag.code == "ARC-EXT-001"
    assert "dup" in diag.message


def test_missing_lookup_diagnostic() -> None:
    reg: Registry[_Fake] = Registry("thing")
    with pytest.raises(DiagnosticError) as exc:
        reg.get("nope")
    assert exc.value.diagnostics[0].code == "ARC-EXT-002"


def test_stable_name_order() -> None:
    reg: Registry[_Fake] = Registry("thing")
    for name in ["c", "a", "b"]:
        reg.register(name, _Fake(name))
    assert reg.names() == ["a", "b", "c"]


def test_registries_container_has_all() -> None:
    regs = Registries()
    for attr in (
        "effects",
        "masks",
        "shapes",
        "exporters",
        "layouts",
        "template_fns",
        "backends",
        "decoders",
    ):
        assert hasattr(regs, attr)
