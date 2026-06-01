import pytest

from agent_core.domain.errors import ConfigurationError
from agent_core.infrastructure.config.settings import Settings


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
