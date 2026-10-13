"""Bootstrap the opt-in isolated deployment without shell-evaluating secrets."""

import json
import os
from pathlib import Path
import re
import sys

import yaml

REQUIRED = {"OPENROUTER_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_USERS"}
OPTIONAL = {"TELEGRAM_HOME_CHANNEL"}


def read_credentials(path):
    try:
        credentials = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        raise ValueError("Cannot read credentials JSON; check the dedicated secret file.") from None
    if not isinstance(credentials, dict) or not REQUIRED <= credentials.keys():
        raise ValueError("Credentials must include the three required keys.")
    if credentials.keys() - REQUIRED - OPTIONAL:
        raise ValueError("Credentials contain unsupported keys.")
    if any(not isinstance(value, str) or not value.strip() or "\n" in value
           or "\x00" in value for value in credentials.values()):
        raise ValueError("Credential values must be nonempty single-line strings.")
    if not re.fullmatch(r"[1-9]\d*(,[1-9]\d*)*", credentials["TELEGRAM_ALLOWED_USERS"]):
        raise ValueError("Use positive numeric Telegram user IDs, separated by commas without spaces.")
    if "TELEGRAM_HOME_CHANNEL" in credentials and not re.fullmatch(
        r"-?[1-9]\d*", credentials["TELEGRAM_HOME_CHANNEL"]
    ):
        raise ValueError("Telegram home channel must be a numeric chat ID.")
    return credentials


def prepare_data(home):
    for name in ("home", "workspace", "cron", "sessions", "logs", "hooks", "memories", "skills"):
        (home / name).mkdir(parents=True, exist_ok=True)
    # Hermes reloads this file with override=True. Keep all secrets in /run/secrets.
    env = home / ".env"
    if env.exists() and any(line.strip() and not line.lstrip().startswith("#")
                            for line in env.read_text().splitlines()):
        raise ValueError("This deployment requires an empty/comment-only /opt/data/.env.")
    env.touch(mode=0o600, exist_ok=True)
    config_path = home / "config.yaml"
    if not config_path.exists():
        config_path.write_text(yaml.safe_dump({
            "model": {"provider": "openrouter", "default": "anthropic/claude-sonnet-4.6"},
            "terminal": {"backend": "local", "cwd": "/opt/data/workspace"},
            "browser": {"inactivity_timeout": 120},
        }, sort_keys=False))
    config = yaml.safe_load(config_path.read_text())
    if not isinstance(config, dict):
        raise ValueError("Config must be a YAML mapping.")
    terminal = config.get("terminal", {})
    browser = config.get("browser", {})
    if not isinstance(terminal, dict) or terminal.get("backend") != "local":
        raise ValueError("The isolated deployment requires terminal.backend: local.")
    if not isinstance(browser, dict) or browser.get("cloud_provider"):
        raise ValueError("The isolated deployment requires the local Chromium browser.")
    soul = home / "SOUL.md"
    if not soul.exists():
        soul.write_text(Path("/opt/hermes/docker/SOUL.md").read_text())


def main():
    os.umask(0o077)
    try:
        credentials = read_credentials("/run/secrets/hermes_credentials")
        prepare_data(Path("/opt/data"))
    except (ValueError, OSError, yaml.YAMLError):
        # Do not print parser errors: they can include secret or config values.
        print("Isolated startup refused: check credentials, file permissions, and local-only config."
              " See docs/ISOLATED_MAC.md.", file=sys.stderr)
        return 1
    os.environ.update(credentials)
    os.environ.update({
        "GATEWAY_ALLOW_ALL_USERS": "false", "TELEGRAM_ALLOW_ALL_USERS": "false",
        "GATEWAY_ALLOWED_USERS": "", "TELEGRAM_WEBHOOK_URL": "",
        "BROWSER_CDP_URL": "", "BROWSERBASE_API_KEY": "", "CAMOFOX_URL": "",
        "TERMINAL_ENV": "local", "TERMINAL_CWD": "/opt/data/workspace",
    })
    os.execv("/bin/bash", ["bash", "/opt/hermes/docker/entrypoint.sh", *sys.argv[1:]])


if __name__ == "__main__":
    sys.exit(main())
