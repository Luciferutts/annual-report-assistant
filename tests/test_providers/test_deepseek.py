"""DeepSeek setup visibility and credential routing without real services or accounts."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import openharness.cli as cli
from openharness.auth.manager import AuthManager
from openharness.auth.storage import load_credential, store_credential
from openharness.config.settings import (
    ProviderProfile,
    Settings,
    auth_source_provider_name,
    default_auth_source_for_provider,
    default_provider_profiles,
    load_settings,
)


@pytest.fixture(autouse=True)
def isolated_auth(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OPENHARNESS_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("OPENHARNESS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("OPENHARNESS_LOGS_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr("openharness.auth.storage._keyring_available", lambda: False)
    for name in (
        "DEEPSEEK_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
        "OPENHARNESS_MODEL", "OPENHARNESS_PROVIDER", "OPENHARNESS_API_FORMAT",
        "OPENHARNESS_BASE_URL", "ANTHROPIC_MODEL", "ANTHROPIC_BASE_URL", "OPENAI_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_builtin_deepseek_profile_and_auth_mapping():
    profile = default_provider_profiles()["deepseek"]
    assert profile.label == "DeepSeek（深度求索）"
    assert profile.provider == "deepseek"
    assert profile.api_format == "openai"
    assert profile.auth_source == "deepseek_api_key"
    assert profile.credential_slot == "deepseek"
    assert profile.default_model == profile.last_model == "deepseek-flash"
    assert profile.allowed_models == ["deepseek-flash"]
    assert profile.base_url == "https://api.deepseek.com/v1"
    assert auth_source_provider_name("deepseek_api_key") == "deepseek"
    assert default_auth_source_for_provider("deepseek", "openai") == "deepseek_api_key"


@pytest.mark.parametrize("existing_settings", [False, True], ids=["fresh", "existing"])
def test_setup_menu_contains_deepseek(tmp_path: Path, monkeypatch, existing_settings):
    if existing_settings:
        path = tmp_path / "config" / "settings.json"
        path.parent.mkdir()
        path.write_text(json.dumps({"active_profile": "claude-api", "profiles": {}}))

    seen = {}

    def choose(title, options, **kwargs):
        seen.update(dict(options))
        return "deepseek"

    monkeypatch.setattr(cli, "_can_use_questionary", lambda: False)
    monkeypatch.setattr(cli, "_select_from_menu", choose)

    target = cli._select_setup_workflow(AuthManager().get_profile_statuses())

    assert target == "deepseek"
    assert "DeepSeek（深度求索）" in seen["deepseek"]


def test_setup_prompts_for_own_key_and_activates_deepseek(tmp_path: Path, monkeypatch):
    path = tmp_path / "config" / "settings.json"
    path.parent.mkdir()
    path.write_text(json.dumps({
        "active_profile": "deepseek", "profiles": {}, "api_key": "old-openai-key",
    }))
    monkeypatch.setenv("OPENAI_API_KEY", "openai-environment-key")
    prompts = []

    def enter_key(flow):
        prompts.append(flow.prompt_text)
        return "deepseek-test-key"

    monkeypatch.setattr("openharness.auth.flows.ApiKeyFlow.run", enter_key)

    result = CliRunner().invoke(cli.app, ["setup", "deepseek"])

    assert result.exit_code == 0, result.output
    assert len(prompts) == 1
    assert "请输入 DeepSeek API Key" in prompts[0]
    assert "deepseek-test-key" not in result.output
    settings = load_settings()
    assert settings.active_profile == "deepseek"
    assert settings.model == "deepseek-flash"
    assert load_credential("profile:deepseek", "api_key", use_keyring=False) == "deepseek-test-key"
    assert load_credential("openai", "api_key", use_keyring=False) is None
    assert settings.resolve_auth().value == "deepseek-test-key"
    assert settings.resolve_auth().source == "file:profile:deepseek"
    assert AuthManager(settings).get_profile_statuses()["deepseek"]["configured"] is True


def test_deepseek_never_uses_openai_credentials(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-environment-key")
    store_credential("openai", "api_key", "openai-stored-key", use_keyring=False)
    settings = Settings(active_profile="deepseek", api_key="openai-flat-key")

    with pytest.raises(ValueError, match="deepseek_api_key"):
        settings.resolve_auth()
    with pytest.raises(ValueError, match="deepseek_api_key"):
        settings.resolve_api_key()
    manager = AuthManager(settings)
    assert manager.get_profile_statuses()["deepseek"]["configured"] is False
    assert manager.get_auth_status()["deepseek"]["configured"] is False


def test_deepseek_environment_key_is_recognized(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-environment-key")
    monkeypatch.setenv("OPENAI_API_KEY", "unrelated-key")
    settings = Settings(active_profile="deepseek")

    auth = settings.resolve_auth()

    assert auth.value == "deepseek-environment-key"
    assert auth.source == "env:DEEPSEEK_API_KEY"
    assert settings.resolve_api_key() == "deepseek-environment-key"
    manager = AuthManager(settings)
    assert manager.get_auth_source_statuses()["deepseek_api_key"]["configured"] is True
    assert manager.get_auth_status()["deepseek"]["configured"] is True
    assert manager.get_profile_statuses()["deepseek"]["configured"] is True


def test_existing_custom_deepseek_profile_and_key_are_preserved(tmp_path: Path, monkeypatch):
    profile = ProviderProfile(
        label="My DeepSeek", provider="openai", api_format="openai",
        auth_source="deepseek_api_key", credential_slot="deepseek",
        default_model="deepseek-flash", last_model="deepseek-flash",
        allowed_models=["deepseek-flash"], base_url="https://api.deepseek.com/v1",
    )
    path = tmp_path / "config" / "settings.json"
    path.parent.mkdir()
    path.write_text(json.dumps({
        "active_profile": "deepseek", "profiles": {"deepseek": profile.model_dump()},
    }))
    store_credential("profile:deepseek", "api_key", "existing-deepseek-key", use_keyring=False)

    def unexpected_prompt(flow):
        raise AssertionError("An existing DeepSeek key must not be overwritten")

    monkeypatch.setattr("openharness.auth.flows.ApiKeyFlow.run", unexpected_prompt)

    result = CliRunner().invoke(cli.app, ["setup", "deepseek"])

    assert result.exit_code == 0, result.output
    settings = load_settings()
    assert settings.resolve_profile()[1] == profile
    assert settings.resolve_auth().value == "existing-deepseek-key"


def test_deepseek_provider_login_and_logout_use_independent_slot(monkeypatch):
    monkeypatch.setattr("openharness.auth.flows.ApiKeyFlow.run", lambda self: "deepseek-test-key")

    result = CliRunner().invoke(cli.app, ["auth", "login", "deepseek"])

    assert result.exit_code == 0, result.output
    assert load_credential("profile:deepseek", "api_key", use_keyring=False) == "deepseek-test-key"
    assert load_credential("deepseek", "api_key", use_keyring=False) is None
    manager = AuthManager()
    manager.switch_provider("deepseek")
    assert manager.get_active_provider() == "deepseek"
    assert manager.get_auth_status()["deepseek"]["configured"] is True
    manager.clear_credential("deepseek")
    assert manager.get_profile_statuses()["deepseek"]["configured"] is False
