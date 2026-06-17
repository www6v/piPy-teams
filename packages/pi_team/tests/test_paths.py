"""Tests for pi_team extension path resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from pi_team.paths import default_extension_path, resolve_extension_path


def test_default_extension_path_exists() -> None:
    path = default_extension_path()
    assert path.name == "team_extension.py"
    assert path.is_file()


def test_resolve_extension_path_env_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    custom = tmp_path / "custom_team_extension.py"
    custom.write_text("# stub\n", encoding="utf-8")
    monkeypatch.setenv("PIPY_TEAMS_EXTENSION", str(custom))
    assert resolve_extension_path() == custom
