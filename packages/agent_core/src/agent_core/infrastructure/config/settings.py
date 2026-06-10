from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from agent_core.domain.errors import ConfigurationError


class Settings(BaseSettings):
    app_env: str = Field(alias="AGENT_EDU_APP_ENV", default="development")
    api_port: int = Field(alias="AGENT_EDU_API_PORT", default=8000)
    database_url: str = Field(alias="AGENT_EDU_DATABASE_URL")
    redis_url: str = Field(alias="AGENT_EDU_REDIS_URL")
    llm_provider: str = Field(alias="AGENT_EDU_LLM_PROVIDER", default="mock")
    llm_model: str = Field(alias="AGENT_EDU_LLM_MODEL", default="mock-tutor-v1")
    llm_api_key: SecretStr | None = Field(alias="AGENT_EDU_LLM_API_KEY", default=None)
    llm_base_url: str | None = Field(alias="AGENT_EDU_LLM_BASE_URL", default=None)
    llm_timeout_seconds: float = Field(alias="AGENT_EDU_LLM_TIMEOUT_SECONDS", default=30.0, gt=0)
    llm_max_retries: int = Field(alias="AGENT_EDU_LLM_MAX_RETRIES", default=2, ge=0, le=5)
    llm_temperature: float = Field(alias="AGENT_EDU_LLM_TEMPERATURE", default=0.2, ge=0.0, le=2.0)
    llm_max_output_tokens: int = Field(alias="AGENT_EDU_LLM_MAX_OUTPUT_TOKENS", default=1200, ge=1, le=8192)
    tutor_model: str | None = Field(alias="AGENT_EDU_TUTOR_MODEL", default=None)
    quiz_model: str | None = Field(alias="AGENT_EDU_QUIZ_MODEL", default=None)
    hint_model: str | None = Field(alias="AGENT_EDU_HINT_MODEL", default=None)
    embedding_provider: str | None = Field(alias="AGENT_EDU_EMBEDDING_PROVIDER", default=None)
    embedding_model: str | None = Field(alias="AGENT_EDU_EMBEDDING_MODEL", default=None)
    embedding_api_key: SecretStr | None = Field(alias="AGENT_EDU_EMBEDDING_API_KEY", default=None)
    embedding_base_url: str | None = Field(alias="AGENT_EDU_EMBEDDING_BASE_URL", default=None)
    embedding_dimensions: int | None = Field(alias="AGENT_EDU_EMBEDDING_DIMENSIONS", default=None, ge=1)
    embedding_timeout_seconds: float = Field(
        alias="AGENT_EDU_EMBEDDING_TIMEOUT_SECONDS",
        default=30.0,
        gt=0,
    )
    allowed_skills_raw: str = Field(alias="AGENT_EDU_ALLOWED_SKILLS", default="")
    reflection_max_depth: int = Field(alias="AGENT_EDU_REFLECTION_MAX_DEPTH", default=2)
    metrics_enabled: bool = Field(alias="AGENT_EDU_METRICS_ENABLED", default=False)
    operator_api_key: SecretStr | None = Field(alias="AGENT_EDU_OPERATOR_API_KEY", default=None)
    autonomy_worker_poll_interval_seconds: float = Field(
        alias="AGENT_EDU_AUTONOMY_WORKER_POLL_INTERVAL_SECONDS",
        default=15.0,
        gt=0,
    )
    external_http_tools_enabled: bool = Field(alias="AGENT_EDU_EXTERNAL_HTTP_TOOLS_ENABLED", default=False)
    external_http_tool_timeout_seconds: float = Field(
        alias="AGENT_EDU_EXTERNAL_HTTP_TOOL_TIMEOUT_SECONDS",
        default=10.0,
        gt=0,
        le=120.0,
    )
    memory_candidate_to_active_evidence_min: int = Field(
        alias="AGENT_EDU_MEMORY_CANDIDATE_TO_ACTIVE_EVIDENCE_MIN",
        default=2,
        ge=1,
        le=20,
    )
    memory_candidate_to_active_support_min: float = Field(
        alias="AGENT_EDU_MEMORY_CANDIDATE_TO_ACTIVE_SUPPORT_MIN",
        default=0.35,
        ge=0.0,
        le=1.0,
    )
    memory_candidate_to_active_confidence_min: float = Field(
        alias="AGENT_EDU_MEMORY_CANDIDATE_TO_ACTIVE_CONFIDENCE_MIN",
        default=0.55,
        ge=0.0,
        le=1.0,
    )
    memory_candidate_to_active_contradiction_max: float = Field(
        alias="AGENT_EDU_MEMORY_CANDIDATE_TO_ACTIVE_CONTRADICTION_MAX",
        default=0.25,
        ge=0.0,
        le=1.0,
    )
    memory_active_to_stable_evidence_min: int = Field(
        alias="AGENT_EDU_MEMORY_ACTIVE_TO_STABLE_EVIDENCE_MIN",
        default=4,
        ge=1,
        le=30,
    )
    memory_active_to_stable_stability_min: float = Field(
        alias="AGENT_EDU_MEMORY_ACTIVE_TO_STABLE_STABILITY_MIN",
        default=0.75,
        ge=0.0,
        le=1.0,
    )
    memory_active_to_stable_assessment_min: int = Field(
        alias="AGENT_EDU_MEMORY_ACTIVE_TO_STABLE_ASSESSMENT_MIN",
        default=1,
        ge=0,
        le=20,
    )
    memory_stable_demote_contradiction_min: float = Field(
        alias="AGENT_EDU_MEMORY_STABLE_DEMOTE_CONTRADICTION_MIN",
        default=0.35,
        ge=0.0,
        le=1.0,
    )
    memory_stable_demote_freshness_max: float = Field(
        alias="AGENT_EDU_MEMORY_STABLE_DEMOTE_FRESHNESS_MAX",
        default=0.35,
        ge=0.0,
        le=1.0,
    )
    memory_archive_freshness_max: float = Field(
        alias="AGENT_EDU_MEMORY_ARCHIVE_FRESHNESS_MAX",
        default=0.1,
        ge=0.0,
        le=1.0,
    )
    memory_archive_goal_relevance_max: float = Field(
        alias="AGENT_EDU_MEMORY_ARCHIVE_GOAL_RELEVANCE_MAX",
        default=0.35,
        ge=0.0,
        le=1.0,
    )
    memory_behavior_candidate_recurrence_min: int = Field(
        alias="AGENT_EDU_MEMORY_BEHAVIOR_CANDIDATE_RECURRENCE_MIN",
        default=1,
        ge=0,
        le=20,
    )
    memory_behavior_active_recurrence_min: int = Field(
        alias="AGENT_EDU_MEMORY_BEHAVIOR_ACTIVE_RECURRENCE_MIN",
        default=2,
        ge=0,
        le=20,
    )
    memory_behavior_active_to_stable_stability_min: float = Field(
        alias="AGENT_EDU_MEMORY_BEHAVIOR_ACTIVE_TO_STABLE_STABILITY_MIN",
        default=0.7,
        ge=0.0,
        le=1.0,
    )
    memory_reflection_effective_weight: float = Field(
        alias="AGENT_EDU_MEMORY_REFLECTION_EFFECTIVE_WEIGHT",
        default=0.18,
        ge=0.0,
        le=1.0,
    )
    memory_reflection_ineffective_weight: float = Field(
        alias="AGENT_EDU_MEMORY_REFLECTION_INEFFECTIVE_WEIGHT",
        default=0.14,
        ge=0.0,
        le=1.0,
    )
    memory_compression_min_group_size: int = Field(
        alias="AGENT_EDU_MEMORY_COMPRESSION_MIN_GROUP_SIZE",
        default=2,
        ge=2,
        le=20,
    )
    memory_maintenance_jobs_per_tick: int = Field(
        alias="AGENT_EDU_MEMORY_MAINTENANCE_JOBS_PER_TICK",
        default=5,
        ge=1,
        le=100,
    )
    memory_maintenance_batch_size: int = Field(
        alias="AGENT_EDU_MEMORY_MAINTENANCE_BATCH_SIZE",
        default=20,
        ge=1,
        le=1000,
    )
    memory_maintenance_lease_seconds: int = Field(
        alias="AGENT_EDU_MEMORY_MAINTENANCE_LEASE_SECONDS",
        default=300,
        ge=1,
        le=86400,
    )
    memory_maintenance_retry_max_attempts: int = Field(
        alias="AGENT_EDU_MEMORY_MAINTENANCE_RETRY_MAX_ATTEMPTS",
        default=3,
        ge=1,
        le=20,
    )
    skill_curator_job_enabled: bool = Field(alias="AGENT_EDU_SKILL_CURATOR_JOB_ENABLED", default=True)
    skill_curator_artifact_scan_limit: int = Field(
        alias="AGENT_EDU_SKILL_CURATOR_ARTIFACT_SCAN_LIMIT",
        default=20,
        ge=1,
        le=200,
    )
    skill_curator_usage_lookback_days: int = Field(
        alias="AGENT_EDU_SKILL_CURATOR_USAGE_LOOKBACK_DAYS",
        default=30,
        ge=1,
        le=365,
    )
    skill_curator_coverage_regression_enabled: bool = Field(
        alias="AGENT_EDU_SKILL_CURATOR_COVERAGE_REGRESSION_ENABLED",
        default=True,
    )
    skill_curator_coverage_drift_topic_min: int = Field(
        alias="AGENT_EDU_SKILL_CURATOR_COVERAGE_DRIFT_TOPIC_MIN",
        default=3,
        ge=1,
        le=1000,
    )
    skill_curator_coverage_hole_topic_min: int = Field(
        alias="AGENT_EDU_SKILL_CURATOR_COVERAGE_HOLE_TOPIC_MIN",
        default=2,
        ge=1,
        le=1000,
    )
    skill_curator_promote_successful_usage_min: int = Field(
        alias="AGENT_EDU_SKILL_CURATOR_PROMOTE_SUCCESSFUL_USAGE_MIN",
        default=5,
        ge=1,
        le=1000,
    )
    skill_curator_promote_observation_min: int = Field(
        alias="AGENT_EDU_SKILL_CURATOR_PROMOTE_OBSERVATION_MIN",
        default=2,
        ge=1,
        le=100,
    )
    skill_curator_max_negative_usage_rate: float = Field(
        alias="AGENT_EDU_SKILL_CURATOR_MAX_NEGATIVE_USAGE_RATE",
        default=0.2,
        ge=0.0,
        le=1.0,
    )
    skill_curator_negative_usage_min: int = Field(
        alias="AGENT_EDU_SKILL_CURATOR_NEGATIVE_USAGE_MIN",
        default=3,
        ge=1,
        le=1000,
    )
    skill_curator_negative_usage_rate_threshold: float = Field(
        alias="AGENT_EDU_SKILL_CURATOR_NEGATIVE_USAGE_RATE_THRESHOLD",
        default=0.4,
        ge=0.0,
        le=1.0,
    )
    skill_curator_resolver_failure_min: int = Field(
        alias="AGENT_EDU_SKILL_CURATOR_RESOLVER_FAILURE_MIN",
        default=3,
        ge=1,
        le=1000,
    )
    skill_curator_archive_stale_days: int = Field(
        alias="AGENT_EDU_SKILL_CURATOR_ARCHIVE_STALE_DAYS",
        default=30,
        ge=1,
        le=3650,
    )
    skill_curator_governance_evidence_enabled: bool = Field(
        alias="AGENT_EDU_SKILL_CURATOR_GOVERNANCE_EVIDENCE_ENABLED",
        default=True,
    )
    skill_curator_governance_evidence_lookback_days: int = Field(
        alias="AGENT_EDU_SKILL_CURATOR_GOVERNANCE_EVIDENCE_LOOKBACK_DAYS",
        default=30,
        ge=1,
        le=365,
    )
    skill_curator_governance_evidence_limit: int = Field(
        alias="AGENT_EDU_SKILL_CURATOR_GOVERNANCE_EVIDENCE_LIMIT",
        default=20,
        ge=1,
        le=200,
    )
    skill_curator_memory_conflict_severity_threshold: float = Field(
        alias="AGENT_EDU_SKILL_CURATOR_MEMORY_CONFLICT_SEVERITY_THRESHOLD",
        default=0.6,
        ge=0.0,
        le=1.0,
    )
    skill_curator_reflection_ineffective_min: int = Field(
        alias="AGENT_EDU_SKILL_CURATOR_REFLECTION_INEFFECTIVE_MIN",
        default=1,
        ge=1,
        le=100,
    )
    skill_curator_reflection_inconclusive_min: int = Field(
        alias="AGENT_EDU_SKILL_CURATOR_REFLECTION_INCONCLUSIVE_MIN",
        default=2,
        ge=1,
        le=100,
    )
    skill_curator_replacement_readiness_successful_usage_min: int = Field(
        alias="AGENT_EDU_SKILL_CURATOR_REPLACEMENT_READINESS_SUCCESSFUL_USAGE_MIN",
        default=3,
        ge=1,
        le=1000,
    )
    skill_curator_replacement_readiness_promote_observation_min: int = Field(
        alias="AGENT_EDU_SKILL_CURATOR_REPLACEMENT_READINESS_PROMOTE_OBSERVATION_MIN",
        default=2,
        ge=1,
        le=100,
    )
    skill_curator_replacement_readiness_max_negative_usage_rate: float = Field(
        alias="AGENT_EDU_SKILL_CURATOR_REPLACEMENT_READINESS_MAX_NEGATIVE_USAGE_RATE",
        default=0.2,
        ge=0.0,
        le=1.0,
    )
    skill_rollout_auto_governance_enabled: bool = Field(
        alias="AGENT_EDU_SKILL_ROLLOUT_AUTO_GOVERNANCE_ENABLED",
        default=True,
    )
    skill_rollout_auto_promote_enabled: bool = Field(
        alias="AGENT_EDU_SKILL_ROLLOUT_AUTO_PROMOTE_ENABLED",
        default=True,
    )
    skill_rollout_auto_rollback_enabled: bool = Field(
        alias="AGENT_EDU_SKILL_ROLLOUT_AUTO_ROLLBACK_ENABLED",
        default=True,
    )
    skill_rollout_auto_promote_surfaces_raw: str = Field(
        alias="AGENT_EDU_SKILL_ROLLOUT_AUTO_PROMOTE_SURFACES",
        default="review_scheduling,assessment_generation,replan",
    )
    skill_rollout_auto_rollback_surfaces_raw: str = Field(
        alias="AGENT_EDU_SKILL_ROLLOUT_AUTO_ROLLBACK_SURFACES",
        default="review_scheduling,assessment_generation,replan",
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    @property
    def allowed_skills(self) -> list[str]:
        return [item.strip() for item in self.allowed_skills_raw.split(",") if item.strip()]

    @property
    def llm_provider_name(self) -> str:
        return self.llm_provider.strip().casefold()

    @property
    def embedding_provider_name(self) -> str | None:
        if self.embedding_provider is None:
            return None
        value = self.embedding_provider.strip()
        return value.casefold() if value else None

    @property
    def tutor_model_name(self) -> str:
        return self.tutor_model or self.llm_model

    @property
    def quiz_model_name(self) -> str:
        return self.quiz_model or self.llm_model

    @property
    def hint_model_name(self) -> str:
        return self.hint_model or self.llm_model

    @property
    def skill_rollout_auto_promote_surfaces(self) -> list[str]:
        return [item.strip() for item in self.skill_rollout_auto_promote_surfaces_raw.split(",") if item.strip()]

    @property
    def skill_rollout_auto_rollback_surfaces(self) -> list[str]:
        return [item.strip() for item in self.skill_rollout_auto_rollback_surfaces_raw.split(",") if item.strip()]

    @property
    def embedding_api_key_value(self) -> str | None:
        if self.embedding_api_key is not None and self.embedding_api_key.get_secret_value().strip():
            return self.embedding_api_key.get_secret_value()
        if self.llm_api_key is not None and self.llm_api_key.get_secret_value().strip():
            return self.llm_api_key.get_secret_value()
        return None

    @property
    def embedding_base_url_value(self) -> str | None:
        if self.embedding_base_url is not None and self.embedding_base_url.strip():
            return self.embedding_base_url
        if self.llm_base_url is not None and self.llm_base_url.strip():
            return self.llm_base_url
        return None

    def validate_llm_configuration(self) -> None:
        if self.llm_provider_name != "mock":
            if self.llm_api_key is None or not self.llm_api_key.get_secret_value().strip():
                raise ConfigurationError("AGENT_EDU_LLM_API_KEY is required when AGENT_EDU_LLM_PROVIDER is not 'mock'.")
            if self.llm_base_url is None or not self.llm_base_url.strip():
                raise ConfigurationError("AGENT_EDU_LLM_BASE_URL is required when AGENT_EDU_LLM_PROVIDER is not 'mock'.")

    def validate_embedding_configuration(self) -> None:
        if self.embedding_provider_name is not None:
            if self.embedding_model is None or not self.embedding_model.strip():
                raise ConfigurationError(
                    "AGENT_EDU_EMBEDDING_MODEL is required when AGENT_EDU_EMBEDDING_PROVIDER is configured."
                )
            if self.embedding_api_key_value is None:
                raise ConfigurationError(
                    "AGENT_EDU_EMBEDDING_API_KEY or AGENT_EDU_LLM_API_KEY is required when AGENT_EDU_EMBEDDING_PROVIDER is configured."
                )
            if self.embedding_base_url_value is None:
                raise ConfigurationError(
                    "AGENT_EDU_EMBEDDING_BASE_URL or AGENT_EDU_LLM_BASE_URL is required when AGENT_EDU_EMBEDDING_PROVIDER is configured."
                )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
