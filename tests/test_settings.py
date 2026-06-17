import pytest
from pydantic import ValidationError

from agent_core.domain.errors import ConfigurationError
from agent_core.infrastructure.config.settings import (
    SKILL_ROLLOUT_AUTO_GOVERNANCE_SURFACES,
    Settings,
)


def test_settings_default_rollout_auto_governance_surfaces(monkeypatch):
    monkeypatch.setenv("AGENT_EDU_DATABASE_URL", "sqlite+aiosqlite:///./test.db")
    monkeypatch.setenv("AGENT_EDU_REDIS_URL", "redis://redis:6379/0")
    monkeypatch.delenv("AGENT_EDU_SKILL_ROLLOUT_AUTO_PROMOTE_SURFACES", raising=False)
    monkeypatch.delenv("AGENT_EDU_SKILL_ROLLOUT_AUTO_ROLLBACK_SURFACES", raising=False)

    settings = Settings(_env_file=None)

    expected = list(SKILL_ROLLOUT_AUTO_GOVERNANCE_SURFACES)
    assert settings.skill_rollout_auto_promote_surfaces == expected
    assert settings.skill_rollout_auto_rollback_surfaces == expected


def test_settings_rollout_auto_governance_surfaces_trim_empty_items(monkeypatch):
    monkeypatch.setenv("AGENT_EDU_DATABASE_URL", "sqlite+aiosqlite:///./test.db")
    monkeypatch.setenv("AGENT_EDU_REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("AGENT_EDU_SKILL_ROLLOUT_AUTO_PROMOTE_SURFACES", " chat, , hint,")
    monkeypatch.setenv("AGENT_EDU_SKILL_ROLLOUT_AUTO_ROLLBACK_SURFACES", "quiz, , replan, ")

    settings = Settings(_env_file=None)

    assert settings.skill_rollout_auto_promote_surfaces == ["chat", "hint"]
    assert settings.skill_rollout_auto_rollback_surfaces == ["quiz", "replan"]


@pytest.mark.parametrize(
    ("env_key", "env_value"),
    [
        ("AGENT_EDU_SKILL_ROLLOUT_AUTO_PROMOTE_SURFACES", "chat,hnit"),
        ("AGENT_EDU_SKILL_ROLLOUT_AUTO_ROLLBACK_SURFACES", "quiz,unknown_surface"),
    ],
)
def test_settings_reject_invalid_rollout_auto_governance_surface(monkeypatch, env_key, env_value):
    monkeypatch.setenv("AGENT_EDU_DATABASE_URL", "sqlite+aiosqlite:///./test.db")
    monkeypatch.setenv("AGENT_EDU_REDIS_URL", "redis://redis:6379/0")
    monkeypatch.delenv("AGENT_EDU_SKILL_ROLLOUT_AUTO_PROMOTE_SURFACES", raising=False)
    monkeypatch.delenv("AGENT_EDU_SKILL_ROLLOUT_AUTO_ROLLBACK_SURFACES", raising=False)
    monkeypatch.setenv(env_key, env_value)

    with pytest.raises(ValidationError, match="unsupported values"):
        Settings(_env_file=None)


def test_settings_load_dashscope_provider_configuration(monkeypatch):
    monkeypatch.setenv("AGENT_EDU_DATABASE_URL", "sqlite+aiosqlite:///./test.db")
    monkeypatch.setenv("AGENT_EDU_REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("AGENT_EDU_LLM_PROVIDER", "Aliyun")
    monkeypatch.setenv("AGENT_EDU_LLM_MODEL", "qwen3.5-flash")
    monkeypatch.setenv("AGENT_EDU_LLM_API_KEY", "secret")
    monkeypatch.setenv("AGENT_EDU_LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setenv("AGENT_EDU_TUTOR_MODEL", "qwen3.5-flash")
    monkeypatch.setenv("AGENT_EDU_QUIZ_MODEL", "qwen3.5-flash")
    monkeypatch.setenv("AGENT_EDU_HINT_MODEL", "qwen3.5-flash")
    monkeypatch.setenv("AGENT_EDU_EMBEDDING_PROVIDER", "Aliyun")
    monkeypatch.setenv("AGENT_EDU_EMBEDDING_MODEL", "text-embedding-v4")
    monkeypatch.setenv("AGENT_EDU_EMBEDDING_API_KEY", "secret")

    settings = Settings(_env_file=None)
    settings.validate_llm_configuration()
    settings.validate_embedding_configuration()

    assert settings.llm_provider == "Aliyun"
    assert settings.llm_provider_name == "aliyun"
    assert settings.tutor_model_name == "qwen3.5-flash"
    assert settings.quiz_model_name == "qwen3.5-flash"
    assert settings.hint_model_name == "qwen3.5-flash"
    assert settings.llm_api_key is not None
    assert settings.embedding_api_key_value == "secret"
    assert settings.embedding_provider_name == "aliyun"
    assert settings.embedding_base_url_value == "https://dashscope.aliyuncs.com/compatible-mode/v1"


def test_settings_require_api_key_for_non_mock_provider(monkeypatch):
    monkeypatch.setenv("AGENT_EDU_DATABASE_URL", "sqlite+aiosqlite:///./test.db")
    monkeypatch.setenv("AGENT_EDU_REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("AGENT_EDU_LLM_PROVIDER", "dashscope_compatible")
    monkeypatch.setenv("AGENT_EDU_LLM_MODEL", "qwen3.5-flash")
    monkeypatch.delenv("AGENT_EDU_LLM_API_KEY", raising=False)
    monkeypatch.setenv("AGENT_EDU_LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")

    settings = Settings(_env_file=None)

    with pytest.raises(ConfigurationError):
        settings.validate_llm_configuration()


def test_settings_require_embedding_model_when_provider_is_configured(monkeypatch):
    monkeypatch.setenv("AGENT_EDU_DATABASE_URL", "sqlite+aiosqlite:///./test.db")
    monkeypatch.setenv("AGENT_EDU_REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("AGENT_EDU_LLM_API_KEY", "secret")
    monkeypatch.setenv("AGENT_EDU_LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setenv("AGENT_EDU_EMBEDDING_PROVIDER", "dashscope_compatible")
    monkeypatch.delenv("AGENT_EDU_EMBEDDING_MODEL", raising=False)

    settings = Settings(_env_file=None)

    with pytest.raises(ConfigurationError):
        settings.validate_embedding_configuration()
