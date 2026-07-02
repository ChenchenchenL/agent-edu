from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent_core.api.dependencies import get_alert_dispatcher, get_session_factory
from agent_core.api.error_handlers import register_error_handlers
from agent_core.api.rate_limit import RateLimitMiddleware
from agent_core.api.routes.goals import router as goals_router
from agent_core.api.routes.autonomy import router as autonomy_router
from agent_core.api.routes.health import router as health_router
from agent_core.api.routes.memory import router as memory_router
from agent_core.api.routes.planning import router as planning_router
from agent_core.api.routes.profiles import router as profiles_router
from agent_core.api.routes.quiz import router as quiz_router
from agent_core.api.routes.reflection import router as reflection_router
from agent_core.api.routes.sessions import router as sessions_router
from agent_core.api.routes.skills import router as skills_router
from agent_core.api.routes.workspace import router as workspace_router
from agent_core.api.routes.audit import router as audit_router
from agent_core.application.services.skills import refresh_skill_observability_metrics
from agent_core.infrastructure.config.settings import get_settings
from agent_core.infrastructure.db.repositories import SkillArtifactRepository, SkillCuratorRecommendationRepository
from agent_core.infrastructure.observability.metrics import (
    PrometheusHttpMiddleware,
    build_metrics_response,
)

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="agent-edu-api",
        version="0.1.0",
        docs_url="/docs" if settings.app_env != "production" else None,
        redoc_url="/redoc" if settings.app_env != "production" else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if settings.metrics_enabled:
        app.add_middleware(PrometheusHttpMiddleware)
        app.add_api_route("/metrics", build_metrics_response, methods=["GET"], include_in_schema=False)

        async def _refresh_skill_metrics_on_startup() -> None:
            session_factory = get_session_factory()
            try:
                async with session_factory() as session:
                    await refresh_skill_observability_metrics(
                        artifact_repository=SkillArtifactRepository(session),
                        recommendation_repository=SkillCuratorRecommendationRepository(session),
                    )
            except Exception:
                logger.exception("Failed to refresh skill observability metrics at startup.")

        app.router.add_event_handler("startup", _refresh_skill_metrics_on_startup)

    if settings.rate_limit_enabled:
        app.add_middleware(
            RateLimitMiddleware,
            per_minute=settings.rate_limit_per_minute,
            alert_dispatcher=get_alert_dispatcher(),
        )

    register_error_handlers(app)
    app.include_router(health_router)
    app.include_router(skills_router, prefix="/api/v1")
    app.include_router(profiles_router, prefix="/api/v1")
    app.include_router(workspace_router, prefix="/api/v1")
    app.include_router(goals_router, prefix="/api/v1")
    app.include_router(autonomy_router, prefix="/api/v1")
    app.include_router(memory_router, prefix="/api/v1")
    app.include_router(planning_router, prefix="/api/v1")
    app.include_router(reflection_router, prefix="/api/v1")
    app.include_router(sessions_router, prefix="/api/v1")
    app.include_router(quiz_router, prefix="/api/v1")
    app.include_router(audit_router, prefix="/api/v1")

    return app
