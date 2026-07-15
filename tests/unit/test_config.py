"""Runtime config precedence tests (§6.3, DX-8): CLI/env/project.yaml/config.toml/default."""

from __future__ import annotations

from pathlib import Path

from arcavex.services.config import RuntimeConfig, config_path


def _config(dpi: int | None) -> dict:
    return {"render": {"dpi": dpi}} if dpi is not None else {}


def test_default_is_per_format_dpi() -> None:
    resolved = RuntimeConfig(env={}, config={}).resolve_dpi()
    assert resolved.value is None and resolved.source == "default"


def test_config_toml_layer() -> None:
    resolved = RuntimeConfig(env={}, config=_config(120)).resolve_dpi()
    assert resolved.value == 120 and resolved.source == "config.toml"


def test_project_yaml_beats_config() -> None:
    resolved = RuntimeConfig(env={}, config=_config(120)).resolve_dpi(project=200)
    assert resolved.value == 200 and resolved.source == "project.yaml"


def test_env_beats_project_and_config() -> None:
    cfg = RuntimeConfig(env={"ARCAVEX_DPI": "300"}, config=_config(120))
    resolved = cfg.resolve_dpi(project=200)
    assert resolved.value == 300 and resolved.source == "env ARCAVEX_DPI"


def test_cli_flag_beats_everything() -> None:
    cfg = RuntimeConfig(env={"ARCAVEX_DPI": "300"}, config=_config(120))
    resolved = cfg.resolve_dpi(cli=72, project=200)
    assert resolved.value == 72 and resolved.source == "cli"


def test_malformed_env_falls_through() -> None:
    cfg = RuntimeConfig(env={"ARCAVEX_DPI": "not-a-number"}, config=_config(120))
    resolved = cfg.resolve_dpi()
    assert resolved.value == 120 and resolved.source == "config.toml"


def test_load_reads_config_toml_from_home(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ARCAVEX_HOME", str(tmp_path))
    (tmp_path / "config.toml").write_text("[render]\ndpi = 144\n", encoding="utf-8")
    assert config_path() == tmp_path / "config.toml"
    resolved = RuntimeConfig.load().resolve_dpi()
    assert resolved.value == 144 and resolved.source == "config.toml"


def test_missing_config_is_no_layer(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ARCAVEX_HOME", str(tmp_path))
    resolved = RuntimeConfig.load().resolve_dpi()
    assert resolved.value is None and resolved.source == "default"
