from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from agent_core.domain.errors import ConfigurationError


SKILL_ROLLOUT_AUTO_GOVERNANCE_SURFACES: tuple[str, ...] = (
    "chat",
    "hint",
    "quiz",
    "plan_generation",
    "review_scheduling",
    "assessment_generation",
    "replan",
)
SKILL_ROLLOUT_AUTO_GOVERNANCE_SURFACES_RAW = ",".join(SKILL_ROLLOUT_AUTO_GOVERNANCE_SURFACES)
SKILL_ROLLOUT_AUTO_GOVERNANCE_SURFACES_ALLOWED = frozenset(SKILL_ROLLOUT_AUTO_GOVERNANCE_SURFACES)
SKILL_REPLACEMENT_AUTO_EXECUTION_SURFACES: tuple[str, ...] = (
    "review_scheduling",
    "assessment_generation",
    "replan",
)
SKILL_REPLACEMENT_AUTO_EXECUTION_SURFACES_RAW = ",".join(SKILL_REPLACEMENT_AUTO_EXECUTION_SURFACES)
SKILL_REPLACEMENT_AUTO_EXECUTION_SURFACES_ALLOWED = SKILL_ROLLOUT_AUTO_GOVERNANCE_SURFACES_ALLOWED


def _parse_csv_items(raw_value: str) -> list[str]:
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def _validate_allowed_csv_items(
    *,
    raw_value: str,
    allowed_values: frozenset[str],
    field_name: str,
) -> str:
    invalid_values = sorted({item for item in _parse_csv_items(raw_value) if item not in allowed_values})
    if invalid_values:
        invalid_values_text = ", ".join(invalid_values)
        allowed_values_text = ", ".join(sorted(allowed_values))
        raise ValueError(
            f"{field_name} contains unsupported values: {invalid_values_text}. "
            f"Allowed values: {allowed_values_text}."
        )
    return raw_value


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
    memory_promotion_eligibility_score_min: float = Field(
        alias="AGENT_EDU_MEMORY_PROMOTION_ELIGIBILITY_SCORE_MIN",
        default=0.75,
        ge=0.0,
        le=1.0,
    )
    memory_promotion_eligibility_independent_source_min: int = Field(
        alias="AGENT_EDU_MEMORY_PROMOTION_ELIGIBILITY_INDEPENDENT_SOURCE_MIN",
        default=3,
        ge=1,
        le=20,
    )
    memory_promotion_eligibility_high_signal_min: int = Field(
        alias="AGENT_EDU_MEMORY_PROMOTION_ELIGIBILITY_HIGH_SIGNAL_MIN",
        default=1,
        ge=1,
        le=20,
    )
    memory_promotion_eligibility_span_hours_min: float = Field(
        alias="AGENT_EDU_MEMORY_PROMOTION_ELIGIBILITY_SPAN_HOURS_MIN",
        default=24.0,
        ge=0.0,
        le=168.0,
    )
    memory_promotion_eligibility_retrieval_weight: float = Field(
        alias="AGENT_EDU_MEMORY_PROMOTION_ELIGIBILITY_RETRIEVAL_WEIGHT",
        default=0.65,
        ge=0.0,
        le=1.0,
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
    reflection_skill_evolution_curator_enabled: bool = Field(
        alias="AGENT_EDU_REFLECTION_SKILL_EVOLUTION_CURATOR_ENABLED",
        default=True,
    )
    reflection_skill_auto_staging_enabled: bool = Field(
        alias="AGENT_EDU_REFLECTION_SKILL_AUTO_STAGING_ENABLED",
        default=False,
    )
    reflection_skill_auto_stage_score_delta_min: float = Field(
        alias="AGENT_EDU_REFLECTION_SKILL_AUTO_STAGE_SCORE_DELTA_MIN",
        default=0.10,
        ge=0.0,
        le=1.0,
    )
    reflection_skill_auto_stage_24h_limit: int = Field(
        alias="AGENT_EDU_REFLECTION_SKILL_AUTO_STAGE_24H_LIMIT",
        default=3,
        ge=1,
        le=100,
    )
    skill_replacement_auto_execution_enabled: bool = Field(
        alias="AGENT_EDU_SKILL_REPLACEMENT_AUTO_EXECUTION_ENABLED",
        default=False,
    )
    skill_replacement_auto_execution_scan_limit: int = Field(
        alias="AGENT_EDU_SKILL_REPLACEMENT_AUTO_EXECUTION_SCAN_LIMIT",
        default=20,
        ge=1,
        le=1000,
    )
    skill_replacement_auto_execution_surfaces_raw: str = Field(
        alias="AGENT_EDU_SKILL_REPLACEMENT_AUTO_EXECUTION_SURFACES",
        default=SKILL_REPLACEMENT_AUTO_EXECUTION_SURFACES_RAW,
    )
    skill_replacement_auto_execution_24h_limit: int = Field(
        alias="AGENT_EDU_SKILL_REPLACEMENT_AUTO_EXECUTION_24H_LIMIT",
        default=3,
        ge=1,
        le=100,
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
        default=SKILL_ROLLOUT_AUTO_GOVERNANCE_SURFACES_RAW,
    )
    skill_rollout_auto_rollback_surfaces_raw: str = Field(
        alias="AGENT_EDU_SKILL_ROLLOUT_AUTO_ROLLBACK_SURFACES",
        default=SKILL_ROLLOUT_AUTO_GOVERNANCE_SURFACES_RAW,
    )
    rate_limit_enabled: bool = Field(alias="AGENT_EDU_RATE_LIMIT_ENABLED", default=False)
    rate_limit_per_minute: int = Field(alias="AGENT_EDU_RATE_LIMIT_PER_MINUTE", default=60, ge=1, le=10000)
    llm_call_limit_enabled: bool = Field(alias="AGENT_EDU_LLM_CALL_LIMIT_ENABLED", default=False)
    llm_call_limit_per_hour: int = Field(alias="AGENT_EDU_LLM_CALL_LIMIT_PER_HOUR", default=500, ge=1, le=100000)
    llm_circuit_breaker_enabled: bool = Field(alias="AGENT_EDU_LLM_CIRCUIT_BREAKER_ENABLED", default=False)
    llm_circuit_breaker_failure_threshold: int = Field(
        alias="AGENT_EDU_LLM_CIRCUIT_BREAKER_FAILURE_THRESHOLD", default=5, ge=1, le=100,
    )
    llm_circuit_breaker_cooldown_seconds: float = Field(
        alias="AGENT_EDU_LLM_CIRCUIT_BREAKER_COOLDOWN_SECONDS", default=60.0, gt=0, le=3600,
    )
    alert_log_path: str | None = Field(alias="AGENT_EDU_ALERT_LOG_PATH", default=None)
    alert_webhook_url: str | None = Field(alias="AGENT_EDU_ALERT_WEBHOOK_URL", default=None)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)

    @field_validator(
        "skill_rollout_auto_promote_surfaces_raw",
        "skill_rollout_auto_rollback_surfaces_raw",
        "skill_replacement_auto_execution_surfaces_raw",
    )
    @classmethod
    def validate_skill_rollout_auto_governance_surfaces(
        cls,
        value: str,
        info: ValidationInfo,
    ) -> str:
        field = cls.model_fields[info.field_name]
        field_name = field.alias or info.field_name
        return _validate_allowed_csv_items(
            raw_value=value,
            allowed_values=SKILL_ROLLOUT_AUTO_GOVERNANCE_SURFACES_ALLOWED,
            field_name=field_name,
        )

    @property
    def allowed_skills(self) -> list[str]:
        return _parse_csv_items(self.allowed_skills_raw)

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
        return _parse_csv_items(self.skill_rollout_auto_promote_surfaces_raw)

    @property
    def skill_rollout_auto_rollback_surfaces(self) -> list[str]:
        return _parse_csv_items(self.skill_rollout_auto_rollback_surfaces_raw)

    @property
    def skill_replacement_auto_execution_surfaces(self) -> list[str]:
        return _parse_csv_items(self.skill_replacement_auto_execution_surfaces_raw)

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
