from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


DEFAULT_API_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_MODE = "remote"


@dataclass
class CliConfig:
    mode: str = DEFAULT_MODE
    api_base_url: str = DEFAULT_API_BASE_URL
    learner_access_key: str | None = None
    active_profile_id: str | None = None
    active_goal_id: str | None = None
    refresh_interval_seconds: int = 15
    last_session_id: str | None = None
    last_task_id: str | None = None


def get_config_path() -> Path:
    configured = os.environ.get("AGENT_EDU_CLI_CONFIG_PATH")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".agent-edu" / "config.json"


def load_cli_config() -> CliConfig:
    path = get_config_path()
    if not path.exists():
        return _apply_env_overrides(CliConfig())
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _apply_env_overrides(CliConfig())
    return _apply_env_overrides(
        CliConfig(
            mode=str(payload.get("mode", DEFAULT_MODE)),
            api_base_url=str(payload.get("api_base_url", DEFAULT_API_BASE_URL)),
            learner_access_key=_normalize_optional(payload.get("learner_access_key")),
            active_profile_id=_normalize_optional(payload.get("active_profile_id")),
            active_goal_id=_normalize_optional(payload.get("active_goal_id")),
            refresh_interval_seconds=int(payload.get("refresh_interval_seconds", 15)),
            last_session_id=_normalize_optional(payload.get("last_session_id")),
            last_task_id=_normalize_optional(payload.get("last_task_id")),
        )
    )


def save_cli_config(config: CliConfig) -> None:
    path = get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), indent=2, sort_keys=True), encoding="utf-8")


def _apply_env_overrides(config: CliConfig) -> CliConfig:
    mode = os.environ.get("AGENT_EDU_CLI_MODE", config.mode).strip() or DEFAULT_MODE
    api_base_url = os.environ.get("AGENT_EDU_API_BASE_URL", config.api_base_url).strip() or DEFAULT_API_BASE_URL
    return CliConfig(
        mode=mode,
        api_base_url=api_base_url.rstrip("/"),
        learner_access_key=_normalize_optional(
            os.environ.get("AGENT_EDU_LEARNER_ACCESS_KEY", config.learner_access_key)
        ),
        active_profile_id=_normalize_optional(os.environ.get("AGENT_EDU_ACTIVE_PROFILE_ID", config.active_profile_id)),
        active_goal_id=_normalize_optional(os.environ.get("AGENT_EDU_ACTIVE_GOAL_ID", config.active_goal_id)),
        refresh_interval_seconds=config.refresh_interval_seconds,
        last_session_id=config.last_session_id,
        last_task_id=config.last_task_id,
    )


def _normalize_optional(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return str(value)
    cleaned = value.strip()
    return cleaned or None
