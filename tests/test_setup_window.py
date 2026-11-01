"""Desktop setup saves the selected provider key before switching profiles."""

from pathlib import Path
import runpy

import pytest

from openharness.auth.manager import AuthManager
from openharness.auth.storage import load_credential


def test_setup_window_saves_deepseek_in_its_own_slot(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr("openharness.auth.storage._keyring_available", lambda: False)
    namespace = runpy.run_path(str(Path(__file__).parents[1] / "scripts/setup_window.py"))

    namespace["configure_api_profile"]("deepseek", "  test-deepseek-key  ")

    assert AuthManager().get_active_profile() == "deepseek"
    assert load_credential("profile:deepseek", "api_key", use_keyring=False) == "test-deepseek-key"
    assert load_credential("openai", "api_key", use_keyring=False) is None


def test_setup_window_rejects_blank_key_before_saving(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(tmp_path))
    namespace = runpy.run_path(str(Path(__file__).parents[1] / "scripts/setup_window.py"))

    with pytest.raises(ValueError, match="API Key"):
        namespace["configure_api_profile"]("deepseek", "  ")

    assert not (tmp_path / "credentials.json").exists()
