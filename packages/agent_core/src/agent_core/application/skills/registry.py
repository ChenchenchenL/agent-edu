from __future__ import annotations

from dataclasses import dataclass

from agent_core.application.services.skill.capability_catalog import resolve_capability_to_legacy
from agent_core.domain.errors import ValidationError


@dataclass(frozen=True)
class SkillDescriptor:
    name: str
    description: str


@dataclass(frozen=True)
class RuntimeSkillHandlerDescriptor:
    key: str
    execution_kind: str
    surfaces: tuple[str, ...]


class SkillRegistry:
    _mode_to_skill = {
        "chat": "explain_concept",
        "hint": "adaptive_hint",
        "quiz": "create_quiz",
        "plan_generation": "plan_study_path",
        "review_scheduling": "schedule_review",
    }
    _catalog = {
        "explain_concept": SkillDescriptor(
            name="explain_concept",
            description="Explain a concept in a structured teaching style.",
        ),
        "create_quiz": SkillDescriptor(
            name="create_quiz",
            description="Generate a short structured quiz for a learner topic.",
        ),
        "adaptive_hint": SkillDescriptor(
            name="adaptive_hint",
            description="Provide a learner hint adjusted to the current context.",
        ),
        "plan_study_path": SkillDescriptor(
            name="plan_study_path",
            description="Generate a structured study path from a learner goal.",
        ),
        "schedule_review": SkillDescriptor(
            name="schedule_review",
            description="Create spaced review tasks from completed learning work.",
        ),
    }
    _runtime_handlers = {
        "explain_concept": RuntimeSkillHandlerDescriptor(
            key="explain_concept",
            execution_kind="tutor_reply",
            surfaces=("chat",),
        ),
        "adaptive_hint": RuntimeSkillHandlerDescriptor(
            key="adaptive_hint",
            execution_kind="tutor_reply",
            surfaces=("hint",),
        ),
        "create_quiz": RuntimeSkillHandlerDescriptor(
            key="create_quiz",
            execution_kind="quiz_draft",
            surfaces=("quiz", "assessment_generation"),
        ),
        "plan_study_path": RuntimeSkillHandlerDescriptor(
            key="plan_study_path",
            execution_kind="study_plan",
            surfaces=("plan_generation", "replan"),
        ),
        "schedule_review": RuntimeSkillHandlerDescriptor(
            key="schedule_review",
            execution_kind="review_schedule",
            surfaces=("review_scheduling",),
        ),
        "llm_explain_concept_v1": RuntimeSkillHandlerDescriptor(
            key="llm_explain_concept_v1",
            execution_kind="tutor_reply",
            surfaces=("chat",),
        ),
        "llm_adaptive_hint_v1": RuntimeSkillHandlerDescriptor(
            key="llm_adaptive_hint_v1",
            execution_kind="tutor_reply",
            surfaces=("hint",),
        ),
        "llm_create_quiz_v1": RuntimeSkillHandlerDescriptor(
            key="llm_create_quiz_v1",
            execution_kind="quiz_draft",
            surfaces=("quiz", "assessment_generation"),
        ),
    }

    def __init__(self, skills: list[SkillDescriptor]) -> None:
        self._skills = skills
        self._skills_by_name = {skill.name: skill for skill in skills}

    @classmethod
    def from_allowed_skills(cls, allowed_skills: list[str]) -> "SkillRegistry":
        skills = [cls._catalog[name] for name in allowed_skills if name in cls._catalog]
        return cls(skills)

    def list_skills(self) -> list[SkillDescriptor]:
        return list(self._skills)

    def has_skill(self, name: str) -> bool:
        return name in self._skills_by_name

    def default_handler_for_skill(self, name: str) -> str:
        if not self.has_skill(name):
            raise ValidationError(f"Skill '{name}' is not enabled.")
        return name

    def has_runtime_handler(self, key: str) -> bool:
        return key in self._runtime_handlers

    def supports_runtime_handler(self, key: str, *, surface: str) -> bool:
        handler = self._runtime_handlers.get(key)
        return handler is not None and surface in handler.surfaces

    def runtime_handler_execution_kind(self, key: str) -> str:
        handler = self._runtime_handlers.get(key)
        if handler is None:
            raise ValidationError(f"Runtime skill handler '{key}' is not registered.")
        return handler.execution_kind

    def trace_for_mode(self, mode: str | None) -> list[str]:
        skill_name = self._mode_to_skill.get(mode or "")
        if skill_name is None:
            expected = ", ".join(sorted(self._mode_to_skill))
            raise ValidationError(f"Unsupported mode. Expected one of: {expected}.")
        if skill_name not in self._skills_by_name:
            raise ValidationError(f"Skill '{skill_name}' is not enabled for mode '{mode}'.")
        return [skill_name]

    def default_skill_for_capability(
        self,
        capability: str,
        surface: str | None = None,
    ) -> str | None:
        """Resolve a capability to its legacy skill name via the bridge catalog."""
        resolved = resolve_capability_to_legacy(capability, surface=surface)
        if resolved is None:
            return None
        legacy_skill_name, _ = resolved
        if not self.has_skill(legacy_skill_name):
            return None
        return legacy_skill_name

    def supports_capability(
        self,
        capability: str,
        surface: str | None = None,
    ) -> bool:
        return self.default_skill_for_capability(capability, surface=surface) is not None

    def default_handler_for_capability(
        self,
        capability: str,
        surface: str | None = None,
    ) -> str | None:
        """Resolve a capability to its legacy implementation binding."""
        legacy_skill_name = self.default_skill_for_capability(capability, surface=surface)
        if legacy_skill_name is None:
            return None
        return self.default_handler_for_skill(legacy_skill_name)
