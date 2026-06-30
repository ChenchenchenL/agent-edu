import asyncio
import os
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine

os.environ.setdefault("AGENT_EDU_DATABASE_URL", "sqlite+aiosqlite:///./test.db")
os.environ.setdefault("AGENT_EDU_REDIS_URL", "redis://redis:6379/0")
os.environ.setdefault(
    "AGENT_EDU_ALLOWED_SKILLS",
    "explain_concept,create_quiz,adaptive_hint,plan_study_path,schedule_review",
)

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_SRC = ROOT / "packages" / "agent_core" / "src"
if str(PACKAGE_SRC) not in sys.path:
    sys.path.insert(0, str(PACKAGE_SRC))

from agent_core.api.app import create_app  # noqa: E402
from agent_core.api import dependencies as api_dependencies  # noqa: E402
from agent_core.api.routes import health as health_routes  # noqa: E402
from agent_core.infrastructure.config.settings import get_settings  # noqa: E402
from agent_core.infrastructure.db.base import Base  # noqa: E402


class FakeRedisClient:
    async def ping(self) -> bool:
        return True


def clear_cached_application_state() -> None:
    get_settings.cache_clear()
    api_dependencies.get_engine.cache_clear()
    api_dependencies.get_session_factory.cache_clear()
    api_dependencies.get_redis_client.cache_clear()
    api_dependencies.get_skill_registry.cache_clear()
    api_dependencies.get_llm_provider.cache_clear()
    api_dependencies.get_llm_call_guard.cache_clear()
    api_dependencies.get_circuit_breaker.cache_clear()
    api_dependencies.get_alert_dispatcher.cache_clear()
    api_dependencies.get_embedding_provider.cache_clear()


async def prepare_database(database_url: str) -> None:
    engine = create_async_engine(database_url, future=True)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()


@pytest.fixture()
def app_client_factory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    clients: list[TestClient] = []

    def factory(*, env_overrides: dict[str, str | None] | None = None) -> TestClient:
        database_url = f"sqlite+aiosqlite:///{tmp_path / f'{uuid4().hex}.db'}"
        effective_env = {
            "AGENT_EDU_APP_ENV": "testing",
            "AGENT_EDU_DATABASE_URL": database_url,
            "AGENT_EDU_REDIS_URL": "redis://redis:6379/0",
            "AGENT_EDU_ALLOWED_SKILLS": "explain_concept,create_quiz,adaptive_hint,plan_study_path,schedule_review",
            "AGENT_EDU_LLM_PROVIDER": "mock",
            "AGENT_EDU_LLM_MODEL": "mock-tutor-v1",
            "AGENT_EDU_LLM_API_KEY": None,
            "AGENT_EDU_LLM_BASE_URL": None,
            "AGENT_EDU_EMBEDDING_PROVIDER": None,
            "AGENT_EDU_EMBEDDING_MODEL": None,
            "AGENT_EDU_EMBEDDING_API_KEY": None,
            "AGENT_EDU_EMBEDDING_BASE_URL": None,
            "AGENT_EDU_EMBEDDING_DIMENSIONS": None,
            "AGENT_EDU_METRICS_ENABLED": "0",
        }
        if env_overrides is not None:
            effective_env.update(env_overrides)

        for key, value in effective_env.items():
            if value is None:
                monkeypatch.delenv(key, raising=False)
            else:
                monkeypatch.setenv(key, value)

        clear_cached_application_state()
        asyncio.run(prepare_database(database_url))
        monkeypatch.setattr(health_routes, "get_redis_client", lambda: FakeRedisClient())

        client = TestClient(create_app())
        clients.append(client)
        return client

    yield factory

    for client in clients:
        client.close()
    clear_cached_application_state()


@pytest.fixture()
def client(app_client_factory) -> TestClient:
    return app_client_factory()
