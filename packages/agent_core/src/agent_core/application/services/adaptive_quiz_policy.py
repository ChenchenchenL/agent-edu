"""Adaptive quiz policy service.

Determines effective difficulty, question count, and focus areas based on
learner mastery, recent attempt outcomes, and active strategy cards.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import logging
from typing import Any

from agent_core.domain.entities.learner.autonomy import LearnerTopicMastery
from agent_core.domain.entities.session.quiz import SessionQuizAnswerAttempt
from agent_core.domain.entities.reflection_v2 import LearnerGoalStrategyCard

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class AdaptiveQuizPolicyOutput:
    """Output values computed by the AdaptiveQuizPolicyService."""
    effective_difficulty: str
    question_count: int
    topic_subskill_distribution: dict[str, float]
    remediation_focus: list[str]
    desired_misconception_probes: list[str]
    feedback_style: str
    skill_directives: dict[str, Any]
    adaptation_rationale: str


class AdaptiveQuizPolicyService:
    """Service to decide adaptive quiz policies based on learner state."""

    def resolve_policy(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None,
        session_id: str,
        topic_key: str,
        requested_difficulty: str | None,
        requested_question_count: int | None,
        current_mastery: LearnerTopicMastery | None,
        recent_attempts: list[SessionQuizAnswerAttempt],
        active_strategy_card: LearnerGoalStrategyCard | None = None,
        long_term_memory_interpretation: str | None = None,
        runtime_directives: dict[str, Any] | None = None,
    ) -> AdaptiveQuizPolicyOutput:
        """Resolves adaptive quiz settings by evaluating learner topic mastery and attempts.

        Args:
            learner_profile_id: The ID of the learner profile.
            learner_goal_id: The ID of the learner goal.
            session_id: The ID of the current learning session.
            topic_key: The subject topic key.
            requested_difficulty: The difficulty requested by client/user.
            requested_question_count: The number of questions requested by client/user.
            current_mastery: Current topic mastery evidence, if any.
            recent_attempts: Recent quiz answer attempts for the topic.
            active_strategy_card: Active strategy card for the goal, if any.
            long_term_memory_interpretation: Summarized LTM context, if any.
            runtime_directives: Dynamic runtime overrides to merge.

        Returns:
            AdaptiveQuizPolicyOutput containing adaptive settings.
        """
        # 1. Map Mastery Band
        recent_failures = sum(1 for att in recent_attempts if att.is_correct is False)
        
        if current_mastery is None:
            if recent_failures >= 2:
                mastery_band = "remedial"
            else:
                mastery_band = "standard"
        else:
            score = current_mastery.mastery_score
            conf = current_mastery.confidence
            ev_count = current_mastery.evidence_count

            if score < 0.45 or recent_failures >= 2:
                mastery_band = "remedial"
            elif score < 0.65:
                mastery_band = "reinforced"
            elif score < 0.75:
                mastery_band = "standard"
            elif score >= 0.85 and conf >= 0.75 and ev_count >= 4:
                mastery_band = "advanced"
            elif score >= 0.75 and conf >= 0.65:
                mastery_band = "stable"
            else:
                mastery_band = "standard"

        # 2. Adaptive Difficulty Shift
        diff_levels = ["easy", "medium", "hard"]
        req_diff = requested_difficulty if requested_difficulty in diff_levels else "medium"
        diff_idx = diff_levels.index(req_diff)

        diff_shift = 0
        if mastery_band == "remedial":
            diff_shift -= 1
        elif mastery_band in ("stable", "advanced"):
            diff_shift += 1

        strategy_bias_note = ""
        if active_strategy_card is not None:
            if active_strategy_card.difficulty_bias == "supportive":
                diff_shift -= 1
                strategy_bias_note = " (strategy difficulty_bias=supportive applied)"
            elif active_strategy_card.difficulty_bias == "challenging":
                diff_shift += 1
                strategy_bias_note = " (strategy difficulty_bias=challenging applied)"

        effective_idx = max(0, min(2, diff_idx + diff_shift))
        effective_difficulty = diff_levels[effective_idx]

        # 3. Adaptive Question Count
        base_count = requested_question_count if requested_question_count is not None else 3
        if mastery_band == "remedial":
            effective_count = base_count + 2
        elif mastery_band in ("stable", "advanced"):
            effective_count = max(2, base_count - 1)
        else:
            effective_count = base_count
        # Bound count safely
        effective_count = max(1, min(10, effective_count))

        # 4. Remediation Focus and Misconceptions
        misconception_counter = Counter()
        for att in recent_attempts:
            for code in att.misconception_codes:
                if code:
                    misconception_counter[code] += 1

        repeated_misconceptions = [code for code, freq in misconception_counter.items() if freq >= 2]
        
        remediation_focus: list[str] = []
        if repeated_misconceptions:
            remediation_focus.extend(f"misconception:{code}" for code in repeated_misconceptions)
            
            # Add subskills from attempts with these misconceptions
            rem_subskills = set()
            for att in recent_attempts:
                if any(code in repeated_misconceptions for code in att.misconception_codes):
                    rem_subskills.update(att.subskill_keys)
            remediation_focus.extend(sorted(rem_subskills))
        else:
            # Add general failed subskills
            failed_subskills = set()
            for att in recent_attempts:
                if att.is_correct is False:
                    failed_subskills.update(att.subskill_keys)
            remediation_focus.extend(sorted(failed_subskills))

        # 5. Topic/Subskill Distribution
        all_subskills = set()
        for att in recent_attempts:
            all_subskills.update(att.subskill_keys)

        topic_subskill_distribution: dict[str, float] = {}
        if not all_subskills:
            topic_subskill_distribution[topic_key] = 1.0
        else:
            rem_subs = [s for s in all_subskills if s in remediation_focus]
            if rem_subs:
                # Remediation subskills get 0.7 total weight
                rem_weight = 0.7 / len(rem_subs)
                for s in rem_subs:
                    topic_subskill_distribution[s] = round(rem_weight, 2)
                
                other_subs = [s for s in all_subskills if s not in remediation_focus]
                if other_subs:
                    other_weight = 0.3 / (len(other_subs) + 1)
                    topic_subskill_distribution[topic_key] = round(other_weight, 2)
                    for s in other_subs:
                        topic_subskill_distribution[s] = round(other_weight, 2)
                else:
                    topic_subskill_distribution[topic_key] = 0.3
            else:
                total_elements = len(all_subskills) + 1
                weight = 1.0 / total_elements
                topic_subskill_distribution[topic_key] = round(weight, 2)
                for s in all_subskills:
                    topic_subskill_distribution[s] = round(weight, 2)

        # 6. Feedback Style
        if mastery_band == "remedial":
            feedback_style = "scaffolded"
        elif mastery_band == "reinforced":
            feedback_style = "detailed"
        elif mastery_band == "stable":
            feedback_style = "concise"
        elif mastery_band == "advanced":
            feedback_style = "challenging"
        else:
            feedback_style = "standard"

        # 7. Skill Directives
        skill_directives: dict[str, Any] = {}
        if mastery_band == "remedial":
            skill_directives["scaffold_questions"] = True
            skill_directives["remediation_mode"] = True
        if repeated_misconceptions:
            skill_directives["target_misconceptions"] = repeated_misconceptions
        if long_term_memory_interpretation:
            skill_directives["memory_context"] = long_term_memory_interpretation

        # 8. Adaptation Rationale
        rationale_parts = [f"Mastery band resolved as '{mastery_band}'."]
        if mastery_band == "remedial":
            rationale_parts.append("Low mastery or multiple failures: lowered difficulty and increased question count for scaffolding.")
        elif mastery_band in ("stable", "advanced"):
            rationale_parts.append("High mastery/confidence: raised difficulty or decreased count to optimize flow.")
        
        if strategy_bias_note:
            rationale_parts.append(strategy_bias_note.strip())

        if repeated_misconceptions:
            rationale_parts.append(f"Targeting repeated misconception(s): {', '.join(repeated_misconceptions)}.")

        adaptation_rationale = " ".join(rationale_parts)

        # 9. Merge runtime directives (only override default policy when allowed)
        if runtime_directives:
            if "difficulty" in runtime_directives:
                override_diff = runtime_directives["difficulty"]
                if override_diff in diff_levels:
                    effective_difficulty = override_diff
                    adaptation_rationale += " Difficulty overridden by runtime directives."
                else:
                    _LOGGER.warning(
                        "Runtime directives contained invalid difficulty=%s, ignoring override.",
                        override_diff,
                    )
            if "question_count" in runtime_directives:
                try:
                    override_count = int(runtime_directives["question_count"])
                    effective_count = max(1, min(10, override_count))
                    adaptation_rationale += " Question count overridden by runtime directives."
                except (ValueError, TypeError):
                    _LOGGER.warning(
                        "Runtime directives contained invalid question_count=%s, ignoring override.",
                        runtime_directives["question_count"],
                    )
            if "feedback_style" in runtime_directives:
                feedback_style = runtime_directives["feedback_style"]
            if "skill_directives" in runtime_directives:
                if isinstance(runtime_directives["skill_directives"], list):
                    skill_directives["directives"] = runtime_directives["skill_directives"]
                elif isinstance(runtime_directives["skill_directives"], dict):
                    skill_directives.update(runtime_directives["skill_directives"])

        return AdaptiveQuizPolicyOutput(
            effective_difficulty=effective_difficulty,
            question_count=effective_count,
            topic_subskill_distribution=topic_subskill_distribution,
            remediation_focus=remediation_focus,
            desired_misconception_probes=repeated_misconceptions,
            feedback_style=feedback_style,
            skill_directives=skill_directives,
            adaptation_rationale=adaptation_rationale,
        )
