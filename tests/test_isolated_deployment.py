"""Security and bootstrap checks for the opt-in Compose deployment."""
import importlib.util
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("isolated_entrypoint", ROOT / "docker/isolated_entrypoint.py")
entrypoint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entrypoint)


def credentials(tmp_path, **updates):
    values = {"OPENROUTER_API_KEY": "dummy-test-key", "TELEGRAM_BOT_TOKEN": "dummy-test-token",
              "TELEGRAM_ALLOWED_USERS": "12345"}
    values.update(updates)
    path = tmp_path / "credentials.json"
    path.write_text(json.dumps(values))
    return path


@pytest.mark.parametrize("users", ["", "*", "@owner", "-123", "123,", "123, 456"])
def test_invalid_allowlist_refused(tmp_path, users):
    with pytest.raises(ValueError):
        entrypoint.read_credentials(credentials(tmp_path, TELEGRAM_ALLOWED_USERS=users))


def test_secrets_are_data_not_shell_code(tmp_path):
    value = "$(touch /tmp/not-executed);`id`"
    result = entrypoint.read_credentials(credentials(tmp_path, OPENROUTER_API_KEY=value))
    assert result["OPENROUTER_API_KEY"] == value


def test_unknown_settings_and_missing_secrets_refused(tmp_path):
    with pytest.raises(ValueError):
        entrypoint.read_credentials(credentials(tmp_path, GATEWAY_ALLOW_ALL_USERS="true"))
    path = tmp_path / "missing.json"
    path.write_text('{}')
    with pytest.raises(ValueError):
        entrypoint.read_credentials(path)


@pytest.mark.parametrize("config", [
    {"terminal": {"backend": "ssh"}},
    {"terminal": {"backend": "docker"}},
    {"terminal": {"backend": "local"}, "browser": {"cloud_provider": "browserbase"}},
    {"terminal": "local"}, [],
])
def test_remote_backends_refused(tmp_path, config):
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(config))
    with pytest.raises(ValueError):
        entrypoint.prepare_data(tmp_path)


def test_dotenv_cannot_override_security_settings(tmp_path):
    (tmp_path / ".env").write_text("TELEGRAM_ALLOW_ALL_USERS=true\n")
    with pytest.raises(ValueError):
        entrypoint.prepare_data(tmp_path)


def test_bootstrap_preserves_existing_user_config(tmp_path):
    (tmp_path / "SOUL.md").write_text("Existing instructions")
    config = {"terminal": {"backend": "local"}, "model": "user-model"}
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(config))
    entrypoint.prepare_data(tmp_path)
    entrypoint.prepare_data(tmp_path)
    assert yaml.safe_load((tmp_path / "config.yaml").read_text()) == config
    assert (tmp_path / "SOUL.md").read_text() == "Existing instructions"
    assert (tmp_path / ".env").read_text() == ""


def test_compose_has_only_dedicated_storage_and_no_host_access():
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
    service = compose["services"]["hermes"]
    assert service["user"] == "10001:10001"
    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in service["security_opt"]
    assert service["volumes"] == ["hermes_data:/opt/data"]
    assert service["secrets"] == ["hermes_credentials"]
    assert not any(key in service for key in ("ports", "network_mode", "privileged", "devices", "pid"))
    assert compose["networks"]["agent"]["driver"] == "bridge"
