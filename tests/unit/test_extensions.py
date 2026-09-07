"""Tests for local extensions: manifest, validator, state lifecycle, and loader (spec §3.3, §7)."""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path
from typing import Any

import pytest

from arcavex.builtin.effects_core import builtin_effects
from arcavex.kernel.registry import Registries
from arcavex.services.extensions.loader import load_enabled_extensions, register_extension
from arcavex.services.extensions.manifest import parse_manifest, version_at_least
from arcavex.services.extensions.state import ExtensionState, source_path
from arcavex.services.extensions.validator import validate_extension

# A valid, deterministic raster effect that imports only the SDK.
_VALID_EFFECT = textwrap.dedent(
    '''
    from typing import ClassVar
    import numpy as np
    from arcavex.sdk import (
        BaseModel, ConfigDict, Effect, EffectKind, Field, Insets, RasterContext,
        image_to_rgba, rgba_to_image,
    )

    class Params(BaseModel):
        model_config = ConfigDict(frozen=True, extra="forbid")
        amount: float = Field(default=0.1, ge=0.0, le=1.0)

    class MyEffect(Effect):
        kind: ClassVar[EffectKind] = EffectKind.RASTER
        param_schema: ClassVar[type[BaseModel]] = Params
        def bounds_expansion(self, params): return Insets()
        def apply(self, ctx):
            assert isinstance(ctx, RasterContext)
            a = image_to_rgba(ctx.image).astype("int16")
            noise = ctx.rng.normal(0.0, ctx.params.amount * 255.0, size=(a.shape[0], a.shape[1], 1))
            a[..., :3] = np.clip(a[..., :3] + noise, 0, 255)
            return rgba_to_image(a.astype("uint8"))
    '''
)


def _manifest(name: str, *, kind: str = "effect", comp: str = "MyEffect",
              comp_name: str | None = None, engine_min: str = "0.1",
              ir_min: str = "1.0") -> str:
    comp_name = comp_name or name
    return (
        f'name = "{name}"\nversion = "0.1.0"\nir_min = "{ir_min}"\n'
        f'engine_min = "{engine_min}"\n\n[[components]]\nkind = "{kind}"\n'
        f'name = "{comp_name}"\nentry = "component:{comp}"\n'
    )


def _make_ext(root: Path, name: str, *, manifest: str | None = None,
              component: str = _VALID_EFFECT) -> Path:
    ext = root / name
    ext.mkdir(parents=True)
    (ext / "extension.toml").write_text(manifest or _manifest(name), encoding="utf-8")
    (ext / "component.py").write_text(component, encoding="utf-8")
    return ext


# --------------------------------------------------------------------------- manifest
def test_parse_valid_manifest(tmp_path: Path) -> None:
    ext = _make_ext(tmp_path, "good-effect")
    manifest, diags = parse_manifest(ext)
    assert manifest is not None and not diags
    assert manifest.name == "good-effect"
    assert manifest.components[0].kind == "effect"
    assert manifest.components[0].module == "component"
    assert manifest.components[0].class_name == "MyEffect"


def test_manifest_not_found(tmp_path: Path) -> None:
    manifest, diags = parse_manifest(tmp_path / "nope")
    assert manifest is None
    assert diags[0].code == "ARC-EXT-010"


def test_manifest_missing_field(tmp_path: Path) -> None:
    bad = (
        'name = "x"\nversion = "0.1.0"\n\n'
        '[[components]]\nkind="effect"\nname="x"\nentry="component:MyEffect"\n'
    )
    ext = _make_ext(tmp_path, "x", manifest=bad)
    manifest, diags = parse_manifest(ext)
    assert manifest is None
    assert any(d.code == "ARC-EXT-012" for d in diags)


def test_manifest_unknown_kind(tmp_path: Path) -> None:
    ext = _make_ext(tmp_path, "x", manifest=_manifest("x", kind="frobnicator"))
    _manifest_obj, diags = parse_manifest(ext)
    assert any(d.code == "ARC-EXT-013" for d in diags)


def test_manifest_duplicate_component(tmp_path: Path) -> None:
    m = (
        'name = "x"\nversion = "0.1.0"\nir_min = "1.0"\nengine_min = "0.1"\n\n'
        '[[components]]\nkind="effect"\nname="dup"\nentry="component:MyEffect"\n\n'
        '[[components]]\nkind="effect"\nname="dup"\nentry="component:MyEffect"\n'
    )
    ext = _make_ext(tmp_path, "x", manifest=m)
    _manifest_obj, diags = parse_manifest(ext)
    assert any(d.code == "ARC-EXT-014" for d in diags)


def test_manifest_bad_entry(tmp_path: Path) -> None:
    ext = _make_ext(tmp_path, "x", manifest=_manifest("x", comp="not a class"))
    manifest, diags = parse_manifest(ext)
    assert any(d.code == "ARC-EXT-011" for d in diags)


def test_version_at_least() -> None:
    assert version_at_least("0.1.0.dev0", "0.1")
    assert version_at_least("1.0", "1.0")
    assert not version_at_least("0.1", "0.2")


# ------------------------------------------------------------------------- validator
def test_validate_good_extension(tmp_path: Path) -> None:
    ext = _make_ext(tmp_path, "good-ext")
    result = validate_extension(ext)
    assert result.ok, [d.model_dump() for d in result.diagnostics]
    assert result.components == ["good-ext"]


def test_validate_incompatible_engine(tmp_path: Path) -> None:
    ext = _make_ext(tmp_path, "future", manifest=_manifest("future", engine_min="99.0"))
    result = validate_extension(ext)
    assert not result.ok
    assert any(d.code == "ARC-EXT-020" for d in result.diagnostics)


def test_validate_disallowed_import(tmp_path: Path) -> None:
    src = "from arcavex.kernel.ir.units import Rect\n" + _VALID_EFFECT
    ext = _make_ext(tmp_path, "reachy", component=src)
    result = validate_extension(ext)
    assert not result.ok
    assert any(d.code == "ARC-EXT-030" for d in result.diagnostics)


def test_validate_determinism_random(tmp_path: Path) -> None:
    src = _VALID_EFFECT.replace(
        "        assert isinstance(ctx, RasterContext)",
        "        import random\n        _ = random.random()\n"
        "        assert isinstance(ctx, RasterContext)",
    )
    ext = _make_ext(tmp_path, "randy", component=src)
    result = validate_extension(ext)
    assert not result.ok
    assert any(d.code == "ARC-EXT-031" for d in result.diagnostics)


def test_validate_determinism_wall_clock(tmp_path: Path) -> None:
    src = "import time\n" + _VALID_EFFECT.replace(
        "        assert isinstance(ctx, RasterContext)",
        "        _ = time.time()\n        assert isinstance(ctx, RasterContext)",
    )
    ext = _make_ext(tmp_path, "clocky", component=src)
    result = validate_extension(ext)
    assert any(d.code == "ARC-EXT-031" for d in result.diagnostics)


def test_validate_bad_param_schema(tmp_path: Path) -> None:
    src = textwrap.dedent(
        '''
        from typing import ClassVar
        from arcavex.sdk import Effect, EffectKind, Insets, RasterContext

        class MyEffect(Effect):
            kind: ClassVar[EffectKind] = EffectKind.RASTER
            param_schema = dict  # not a pydantic BaseModel
            def bounds_expansion(self, params): return Insets()
            def apply(self, ctx): return ctx.image
        '''
    )
    ext = _make_ext(tmp_path, "schemaless", component=src)
    result = validate_extension(ext)
    assert not result.ok
    assert any(d.code == "ARC-EXT-023" for d in result.diagnostics)


def test_validate_name_mismatch(tmp_path: Path) -> None:
    src = textwrap.dedent(
        '''
        from typing import ClassVar
        import skia
        from arcavex.sdk import BaseModel, ConfigDict, MaskGenerator, Rect

        class P(BaseModel):
            model_config = ConfigDict(frozen=True, extra="forbid")

        class MyMask(MaskGenerator):
            name: ClassVar[str] = "wrong-name"
            param_schema: ClassVar[type[BaseModel]] = P
            def build(self, params, bounds):
                path = skia.Path()
                path.addRect(skia.Rect.MakeXYWH(bounds.x, bounds.y, bounds.w, bounds.h))
                return path
        '''
    )
    ext = _make_ext(
        tmp_path, "mm",
        manifest=_manifest("mm", kind="mask", comp="MyMask", comp_name="right-name"),
        component=src,
    )
    result = validate_extension(ext)
    assert not result.ok
    assert any(d.code == "ARC-EXT-022" for d in result.diagnostics)


def test_validate_shader_compile_failure(tmp_path: Path) -> None:
    src = _VALID_EFFECT.replace(
        "class MyEffect(Effect):",
        'class MyEffect(Effect):\n    SKSL = "this is not valid sksl {{{"',
    )
    ext = _make_ext(tmp_path, "shady", component=src)
    result = validate_extension(ext)
    assert not result.ok
    assert any(d.code == "ARC-EXT-032" for d in result.diagnostics)


# ----------------------------------------------------------------------------- state
def test_state_lifecycle(arcavex_home: Path) -> None:
    state = ExtensionState()
    assert state.records() == []
    rec = state.add("a", "0.1.0")
    assert rec.enabled is False  # add is disabled by default (spec §3.3)
    state.add("b", "0.2.0")
    assert [r.name for r in state.records()] == ["a", "b"]  # sorted, deterministic
    updated = state.set_enabled("a", True)
    assert updated is not None and updated.enabled
    assert state.get("a").enabled and not state.get("b").enabled
    assert state.set_enabled("missing", True) is None
    assert state.remove("a") is True
    assert state.get("a") is None


def test_remove_drops_the_record_before_deleting_the_copy(
    arcavex_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If deleting the stored copy fails, the record must already be gone. A record pointing at
    nothing is an extension that fails to load at every engine start and an ``ext list`` row with
    no components; a directory nothing points at is inert, and the next add replaces it."""
    from arcavex.services.extensions.service import ExtensionService

    service = ExtensionService()
    ext = _make_ext(tmp_path, "stubborn")
    assert service.add_extension(ext).ok
    stored = source_path("stubborn")
    assert stored.is_dir()

    def refuse(path: Any, *args: Any, **kwargs: Any) -> None:
        raise OSError(13, "Permission denied", str(path))

    monkeypatch.setattr("arcavex.services.extensions.service.shutil.rmtree", refuse)
    report = service.remove_extension("stubborn")
    assert not report.ok
    assert [d.code for d in report.diagnostics] == ["ARC-EXT-060"]
    assert report.diagnostics[0].source is not None
    assert report.diagnostics[0].source.file == str(stored)
    assert ExtensionState().get("stubborn") is None  # the record went first
    assert stored.is_dir()  # the copy is left for the person to delete, as the hint says


def test_remove_without_a_stored_copy_still_drops_the_record(arcavex_home: Path) -> None:
    """A copy deleted by hand (the old workaround) must not make the record unremovable."""
    from arcavex.services.extensions.service import ExtensionService

    ExtensionState().add("handmade", "0.1.0")
    report = ExtensionService().remove_extension("handmade")
    assert report.ok and report.removed_path is None
    assert ExtensionState().get("handmade") is None


# ---------------------------------------------------------------------------- loader
def test_loader_registers_enabled_extension(arcavex_home: Path, tmp_path: Path) -> None:
    """An enabled extension's effect lands in the registry exactly like a built-in."""
    ext = _make_ext(tmp_path, "loaded-fx")
    _install(ext, "loaded-fx", enabled=True)
    registries = Registries()
    diags = load_enabled_extensions(registries)
    assert diags == []
    assert registries.effects.has("loaded-fx")


def test_loader_skips_disabled_extension(arcavex_home: Path, tmp_path: Path) -> None:
    """A disabled extension is not registered — disabling takes effect on the next start."""
    ext = _make_ext(tmp_path, "off-fx")
    _install(ext, "off-fx", enabled=False)
    registries = Registries()
    load_enabled_extensions(registries)
    assert not registries.effects.has("off-fx")


def test_loader_duplicate_vs_builtin(tmp_path: Path) -> None:
    """An extension effect named after a built-in is rejected, naming both providers."""
    ext = _make_ext(tmp_path, "blur", manifest=_manifest("blur", comp_name="blur"))
    registries = Registries()
    for name, effect in builtin_effects().items():
        registries.effects.register(name, effect)
    diags = register_extension(registries, ext)
    assert any(d.code == "ARC-EXT-001" for d in diags)


def test_loader_duplicate_vs_extension(tmp_path: Path) -> None:
    """Two extensions declaring the same component name collide (ARC-EXT-001)."""
    a = _make_ext(tmp_path / "a", "dup-a", manifest=_manifest("dup-a", comp_name="shared"))
    b = _make_ext(tmp_path / "b", "dup-b", manifest=_manifest("dup-b", comp_name="shared"))
    registries = Registries()
    assert register_extension(registries, a) == []
    diags = register_extension(registries, b)
    assert any(d.code == "ARC-EXT-001" for d in diags)


def _install(ext_dir: Path, name: str, *, enabled: bool) -> None:
    """Copy an extension into the isolated Arcavex home and record its state."""
    import shutil

    dest = source_path(name)
    shutil.copytree(ext_dir, dest)
    ExtensionState().add(name, "0.1.0", enabled=enabled)


# ------------------------------------------------------------------------- collisions
def test_validate_collision_with_builtin_names(tmp_path: Path) -> None:
    """With an injected built-in name map, a colliding component fails validate (DX-2)."""
    ext = _make_ext(tmp_path, "blur", manifest=_manifest("blur", comp_name="blur"))
    taken = {"effect": {"blur": "built-in 'blur'"}}
    result = validate_extension(ext, taken=taken)
    assert not result.ok
    dup = next(d for d in result.diagnostics if d.code == "ARC-EXT-001")
    assert "built-in 'blur'" in dup.message and "blur" in dup.message


def test_validate_no_collision_when_name_free(tmp_path: Path) -> None:
    """The collision gate does not fire for a name nothing else claims."""
    ext = _make_ext(tmp_path, "fresh-fx")
    taken = {"effect": {"blur": "built-in 'blur'"}}
    result = validate_extension(ext, taken=taken)
    assert result.ok, [d.model_dump() for d in result.diagnostics]


def test_service_rejects_builtin_collision(arcavex_home: Path, tmp_path: Path) -> None:
    """The service builds the taken-map from injected built-ins; add and validate both refuse."""
    from arcavex.services.extensions.service import ExtensionService

    service = ExtensionService(builtin_names={"effect": frozenset({"blur"})})
    ext = _make_ext(tmp_path, "blur", manifest=_manifest("blur", comp_name="blur"))
    assert not service.validate_extension(ext).ok
    add = service.add_extension(ext)
    assert not add.ok
    assert any(d.code == "ARC-EXT-001" for d in add.diagnostics)


def test_service_add_rejects_collision_with_other_extension(
    arcavex_home: Path, tmp_path: Path
) -> None:
    """A second extension reusing a first extension's component name is refused at add (CR-3)."""
    from arcavex.services.extensions.service import ExtensionService

    service = ExtensionService()
    a = _make_ext(tmp_path / "a", "ext-a", manifest=_manifest("ext-a", comp_name="shared"))
    assert service.add_extension(a).ok
    b = _make_ext(tmp_path / "b", "ext-b", manifest=_manifest("ext-b", comp_name="shared"))
    add = service.add_extension(b)
    assert not add.ok
    dup = next(d for d in add.diagnostics if d.code == "ARC-EXT-001")
    assert "extension 'ext-a'" in dup.message


# ------------------------------------------------------------------- test-harness failures
def _testable_ext(root: Path, name: str) -> Path:
    """A valid extension carrying a trivial golden_test.py, so ``test`` reaches the subprocess."""
    ext = _make_ext(root, name)
    (ext / "golden_test.py").write_text("print('ok')\n", encoding="utf-8")
    return ext


def test_child_env_pins_utf8_over_the_inherited_environment(
    arcavex_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The child is spawned with UTF-8 pinned, merged over the inherited environment.

    Asserting the spawn arguments directly keeps the contract explicit: a future refactor that
    drops ``encoding`` or the env would otherwise only show up as a Windows-only crash.
    """
    from arcavex.services.extensions.service import ExtensionService

    ext = _testable_ext(tmp_path, "envy")
    seen: dict[str, Any] = {}

    def _fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen.update(kwargs)
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    monkeypatch.setenv("ARCAVEX_MARKER", "inherited")
    assert ExtensionService().test_extension(ext).ok
    assert seen["encoding"] == "utf-8"
    assert seen["errors"] == "replace"
    assert seen["env"]["PYTHONIOENCODING"] == "utf-8"
    assert seen["env"]["PYTHONUTF8"] == "1"
    assert seen["env"]["ARCAVEX_MARKER"] == "inherited"  # merged over, not replacing


def test_unreadable_output_is_a_harness_error_not_a_test_failure(
    arcavex_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Output the harness could not read reports ARC-EXT-053, never ARC-EXT-052.

    Simulates the historical Windows failure: a reader thread dies mid-stream and leaves the
    captured stream unset, which used to reach the caller as a confident 'your test failed'.
    """
    from arcavex.services.extensions.service import ExtensionService

    ext = _testable_ext(tmp_path, "unreadable")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], returncode=0, stdout=None, stderr=None),
    )
    report = ExtensionService().test_extension(ext)
    assert not report.ok and not report.passed
    assert [d.code for d in report.diagnostics] == ["ARC-EXT-053"]


def test_unspawnable_child_is_a_harness_error(
    arcavex_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A subprocess that cannot be started is ARC-EXT-053, not a failing extension test."""
    from arcavex.services.extensions.service import ExtensionService

    ext = _testable_ext(tmp_path, "unspawnable")

    def _boom(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise OSError(8, "Exec format error")

    monkeypatch.setattr(subprocess, "run", _boom)
    report = ExtensionService().test_extension(ext)
    assert not report.ok
    assert [d.code for d in report.diagnostics] == ["ARC-EXT-053"]
    assert "Exec format error" in report.diagnostics[0].message


# --------------------------------------------------------------------- SDK path coercion
def test_save_and_load_png_accept_str_path(tmp_path: Path) -> None:
    """save_png/load_png coerce a plain str path instead of raising AttributeError (DX-4)."""
    import numpy as np

    from arcavex.sdk import load_png, rgba_to_image, save_png

    img = rgba_to_image(np.zeros((4, 4, 4), dtype=np.uint8))
    target = str(tmp_path / "nested" / "out.png")  # a plain string, nested dir created by save
    save_png(img, target)
    assert load_png(target).width() == 4
