"""Build identity: version, commit, and the channel that gates the CLI surface."""

from __future__ import annotations

from arcavex.build_info import build_channel, engine_label, engine_version


def test_build_channel_is_source_in_a_checkout() -> None:
    """A checkout/editable install embeds no build.json, so it is a source build."""
    assert build_channel() == "source"


def test_engine_label_includes_the_channel() -> None:
    """``--version`` and the installed skill header both report how the engine was built."""
    label = engine_label()
    assert label.startswith(f"{engine_version()} (commit ")
    assert ", channel source)" in label
