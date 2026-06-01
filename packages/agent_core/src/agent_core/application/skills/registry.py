from __future__ import annotations

from dataclasses import dataclass

from agent_core.domain.errors import ValidationError


@dataclass(frozen=True)
class SkillDescriptor:
    name: str
    description: str


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

    def trace_for_mode(self, mode: str | None) -> list[str]:
        skill_name = self._mode_to_skill.get(mode or "")
        if skill_name is None:
            expected = ", ".join(sorted(self._mode_to_skill))
            raise ValidationError(f"Unsupported mode. Expected one of: {expected}.")
        if skill_name not in self._skills_by_name:
            raise ValidationError(f"Skill '{skill_name}' is not enabled for mode '{mode}'.")
        return [skill_name]
