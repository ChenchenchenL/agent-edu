"""Evidence computation, evidence link sync, and evidence upsert."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from agent_core.application.services.audit import AuditService
from agent_core.application.services.memory_normalization import MemoryNormalizer
from agent_core.application.services.learner_memory.candidate_builders import topic_alignment_score
from agent_core.application.services.learner_memory.constants import (
    BEHAVIOR_EVIDENCE_WEIGHTS,
    KNOWLEDGE_EVIDENCE_WEIGHTS,
)
from agent_core.application.services.learner_memory.quality import clamp_score
from agent_core.domain.entities.autonomy import LearnerTopicMastery, TaskAttempt
from agent_core.domain.entities.memory import (
    BehaviorMemory,
    KnowledgeMemory,
    MemoryEvent,
    MemoryEvidenceLink,
)
from agent_core.domain.entities.reflection import ReflectionRecord
from agent_core.domain.entities.reflection_v2 import ReflectionOutcomeEvaluation
from agent_core.domain.entities.session.quiz import SessionQuizAnswerAttempt
from agent_core.infrastructure.db.repositories import (
    MemoryEventRepository,
    MemoryEvidenceLinkRepository,
    LearnerTopicMasteryRepository,
    TaskAttemptRepository,
)
from agent_core.infrastructure.embedding.types import EmbeddingProvider
from agent_core.infrastructure.observability.metrics import (
    observe_memory_evidence_upsert,
)


class EvidenceService:
    """Handles evidence computation, evidence link sync, and evidence upsert."""

    def __init__(
        self,
        *,
        evidence_link_repository: MemoryEvidenceLinkRepository | None = None,
        task_attempt_repository: TaskAttemptRepository | None = None,
        learner_topic_mastery_repository: LearnerTopicMasteryRepository | None = None,
        memory_event_repository: MemoryEventRepository | None = None,
        governance_config: dict[str, float | int] | None = None,
    ) -> None:
        self._evidence_link_repository = evidence_link_repository
        self._task_attempt_repository = task_attempt_repository
        self._learner_topic_mastery_repository = learner_topic_mastery_repository
        self._memory_event_repository = memory_event_repository
        self._governance_config = governance_config or {}

    async def sync_knowledge_evidence_links(
        self,
        *,
        memory: KnowledgeMemory,
        attempts: list[TaskAttempt],
        mastery: LearnerTopicMastery | None,
        events: list[MemoryEvent],
    ) -> None:
        if self._evidence_link_repository is None:
            return
        for attempt in attempts:
            evidence_role = MemoryNormalizer.classify_evidence_role(
                memory_type="knowledge",
                evidence_source_type="task_attempt",
                outcome_status=attempt.outcome_status,
            )
            weight = (
                KNOWLEDGE_EVIDENCE_WEIGHTS.task_attempt_assessment_link
                if attempt.task_type == "assessment"
                else KNOWLEDGE_EVIDENCE_WEIGHTS.task_attempt_default_link
            )
            if attempt.outcome_status == "completed" and attempt.task_type in {"practice", "review"}:
                weight = KNOWLEDGE_EVIDENCE_WEIGHTS.completed_practice_or_review_link
            await self._evidence_link_repository.upsert(
                MemoryEvidenceLink.build(
                    memory_type="knowledge",
                    memory_id=memory.id,
                    learner_profile_id=memory.learner_profile_id,
                    learner_goal_id=memory.learner_goal_id,
                    evidence_source_type="task_attempt",
                    evidence_source_id=attempt.id,
                    evidence_role=evidence_role,
                    signal_type=f"{attempt.task_type}:{attempt.outcome_status}",
                    weight=weight,
                    payload={
                        "task_type": attempt.task_type,
                        "outcome_status": attempt.outcome_status,
                        "score": attempt.score,
                        "result_note": attempt.result_note,
                    },
                    observed_at=attempt.created_at,
                )
            )
        if mastery is not None:
            await self._evidence_link_repository.upsert(
                MemoryEvidenceLink.build(
                    memory_type="knowledge",
                    memory_id=memory.id,
                    learner_profile_id=memory.learner_profile_id,
                    learner_goal_id=memory.learner_goal_id,
                    evidence_source_type="topic_mastery",
                    evidence_source_id=mastery.id,
                    evidence_role=MemoryNormalizer.classify_evidence_role(
                        memory_type="knowledge",
                        evidence_source_type="topic_mastery",
                    ),
                    signal_type="mastery_refresh",
                    weight=clamp_score(mastery.confidence),
                    payload={
                        "topic_key": mastery.topic_key,
                        "mastery_score": mastery.mastery_score,
                        "confidence": mastery.confidence,
                        "evidence_count": mastery.evidence_count,
                        "last_attempt_status": mastery.last_attempt_status,
                    },
                    observed_at=mastery.updated_at,
                )
            )
        for event in events:
            if event.memory_scope != "profile":
                continue
            evidence_role = MemoryNormalizer.classify_evidence_role(
                memory_type="knowledge",
                evidence_source_type="session_memory_event",
                has_progress=event.progress_note is not None,
                has_struggle=event.struggle_note is not None,
            )
            await self._evidence_link_repository.upsert(
                MemoryEvidenceLink.build(
                    memory_type="knowledge",
                    memory_id=memory.id,
                    learner_profile_id=memory.learner_profile_id,
                    learner_goal_id=memory.learner_goal_id,
                    evidence_source_type="session_memory_event",
                    evidence_source_id=event.id,
                    evidence_role=evidence_role,
                    signal_type=event.event_type,
                    weight=0.1 if event.progress_note is not None else 0.08 if event.struggle_note is not None else 0.05,
                    payload={
                        "memory_scope": event.memory_scope,
                        "memory_level": event.memory_level,
                        "summary": event.summary,
                        "concept_focus": event.concept_focus,
                    },
                    observed_at=event.created_at,
                )
            )

    async def sync_behavior_evidence_links(
        self,
        *,
        memory: BehaviorMemory,
        attempts: list[TaskAttempt],
        events: list[MemoryEvent],
    ) -> None:
        if self._evidence_link_repository is None:
            return
        for attempt in attempts:
            evidence_role = MemoryNormalizer.classify_evidence_role(
                memory_type="behavior",
                evidence_source_type="task_attempt",
                outcome_status=attempt.outcome_status,
            )
            weight = (
                BEHAVIOR_EVIDENCE_WEIGHTS.failed_or_skipped_task_link
                if attempt.outcome_status in {"failed", "skipped"}
                else BEHAVIOR_EVIDENCE_WEIGHTS.completed_task_link
            )
            await self._evidence_link_repository.upsert(
                MemoryEvidenceLink.build(
                    memory_type="behavior",
                    memory_id=memory.id,
                    learner_profile_id=memory.learner_profile_id,
                    learner_goal_id=memory.learner_goal_id,
                    evidence_source_type="task_attempt",
                    evidence_source_id=attempt.id,
                    evidence_role=evidence_role,
                    signal_type=f"{attempt.task_type}:{attempt.outcome_status}",
                    weight=weight,
                    payload={
                        "task_type": attempt.task_type,
                        "outcome_status": attempt.outcome_status,
                        "score": attempt.score,
                        "result_note": attempt.result_note,
                    },
                    observed_at=attempt.created_at,
                )
            )
        for event in events:
            if event.memory_scope != "profile":
                continue
            evidence_role = MemoryNormalizer.classify_evidence_role(
                memory_type="behavior",
                evidence_source_type="session_memory_event",
                has_progress=event.progress_note is not None,
                has_struggle=event.struggle_note is not None,
            )
            await self._evidence_link_repository.upsert(
                MemoryEvidenceLink.build(
                    memory_type="behavior",
                    memory_id=memory.id,
                    learner_profile_id=memory.learner_profile_id,
                    learner_goal_id=memory.learner_goal_id,
                    evidence_source_type="session_memory_event",
                    evidence_source_id=event.id,
                    evidence_role=evidence_role,
                    signal_type=event.event_type,
                    weight=0.12 if event.struggle_note is not None else 0.06,
                    payload={
                        "memory_scope": event.memory_scope,
                        "memory_level": event.memory_level,
                        "summary": event.summary,
                        "concept_focus": event.concept_focus,
                    },
                    observed_at=event.created_at,
                )
            )

    async def upsert_session_memory_event_evidence(
        self,
        *,
        memory: KnowledgeMemory | BehaviorMemory,
        memory_type: str,
        event: MemoryEvent,
    ) -> None:
        if self._evidence_link_repository is None:
            return
        if memory_type == "knowledge":
            evidence_role = MemoryNormalizer.classify_evidence_role(
                memory_type="knowledge",
                evidence_source_type="session_memory_event",
                has_progress=event.progress_note is not None,
                has_struggle=event.struggle_note is not None,
            )
            weight = (
                KNOWLEDGE_EVIDENCE_WEIGHTS.progress_event
                if event.progress_note is not None
                else KNOWLEDGE_EVIDENCE_WEIGHTS.struggle_event
                if event.struggle_note is not None
                else KNOWLEDGE_EVIDENCE_WEIGHTS.neutral_event_refresh
            )
        else:
            evidence_role = MemoryNormalizer.classify_evidence_role(
                memory_type="behavior",
                evidence_source_type="session_memory_event",
                has_progress=event.progress_note is not None,
                has_struggle=event.struggle_note is not None,
            )
            weight = (
                BEHAVIOR_EVIDENCE_WEIGHTS.struggle_event_link
                if event.struggle_note is not None
                else BEHAVIOR_EVIDENCE_WEIGHTS.neutral_event_link
            )
        await self._evidence_link_repository.upsert(
            MemoryEvidenceLink.build(
                memory_type=memory_type,
                memory_id=memory.id,
                learner_profile_id=memory.learner_profile_id,
                learner_goal_id=memory.learner_goal_id,
                evidence_source_type="session_memory_event",
                evidence_source_id=event.id,
                evidence_role=evidence_role,
                signal_type=event.event_type,
                weight=weight,
                payload={
                    "memory_scope": event.memory_scope,
                    "memory_level": event.memory_level,
                    "summary": event.summary,
                    "concept_focus": event.concept_focus,
                    "source_message_id": event.source_message_id,
                },
                observed_at=event.created_at,
            )
        )

    async def upsert_task_attempt_evidence(
        self,
        *,
        memory: KnowledgeMemory | BehaviorMemory,
        memory_type: str,
        attempt: TaskAttempt,
    ) -> None:
        if self._evidence_link_repository is None:
            return
        if memory_type == "knowledge":
            evidence_role = MemoryNormalizer.classify_evidence_role(
                memory_type="knowledge",
                evidence_source_type="task_attempt",
                outcome_status=attempt.outcome_status,
            )
            weight = (
                KNOWLEDGE_EVIDENCE_WEIGHTS.task_attempt_assessment_link
                if attempt.task_type == "assessment"
                else KNOWLEDGE_EVIDENCE_WEIGHTS.task_attempt_default_link
            )
        else:
            is_positive = getattr(memory, "is_positive_behavior", False)
            evidence_role = MemoryNormalizer.classify_evidence_role(
                memory_type="behavior",
                evidence_source_type="task_attempt",
                outcome_status=attempt.outcome_status,
                is_positive_behavior=is_positive,
            )
            weight = (
                BEHAVIOR_EVIDENCE_WEIGHTS.failed_or_skipped_task_link
                if attempt.outcome_status in {"failed", "skipped"}
                else BEHAVIOR_EVIDENCE_WEIGHTS.completed_task_link
            )
        await self._evidence_link_repository.upsert(
            MemoryEvidenceLink.build(
                memory_type=memory_type,
                memory_id=memory.id,
                learner_profile_id=memory.learner_profile_id,
                learner_goal_id=memory.learner_goal_id,
                evidence_source_type="task_attempt",
                evidence_source_id=attempt.id,
                evidence_role=evidence_role,
                signal_type=f"{attempt.task_type}:{attempt.outcome_status}",
                weight=weight,
                payload={
                    "task_type": attempt.task_type,
                    "outcome_status": attempt.outcome_status,
                    "score": attempt.score,
                    "result_note": attempt.result_note,
                    "daily_task_id": attempt.daily_task_id,
                    "workflow_run_id": attempt.workflow_run_id,
                },
                observed_at=attempt.created_at,
            )
        )

    async def upsert_quiz_answer_attempt_evidence(
        self,
        *,
        memory: KnowledgeMemory | BehaviorMemory,
        memory_type: str,
        attempt: SessionQuizAnswerAttempt,
    ) -> None:
        if self._evidence_link_repository is None:
            return
        evidence_role = MemoryNormalizer.classify_evidence_role(
            memory_type=memory_type,
            evidence_source_type="quiz_answer_attempt",
            outcome_status="completed" if attempt.is_correct else "failed",
        )
        base_weight = 0.5
        if attempt.grading_status == "needs_review":
            base_weight *= 0.5
        elif attempt.confidence is not None and attempt.confidence >= 0.8:
            base_weight = min(1.0, base_weight * 1.2)
        weight = clamp_score(base_weight)
        payload = {
            "score": attempt.score,
            "difficulty": attempt.metadata.get("difficulty", "medium") if attempt.metadata else "medium",
            "misconception_codes": list(attempt.misconception_codes),
            "hint_count": attempt.hint_count,
            "question_id": attempt.question_id,
        }
        await self._evidence_link_repository.upsert(
            MemoryEvidenceLink.build(
                memory_type=memory_type,
                memory_id=memory.id,
                learner_profile_id=memory.learner_profile_id,
                learner_goal_id=memory.learner_goal_id,
                evidence_source_type="quiz_answer_attempt",
                evidence_source_id=attempt.id,
                evidence_role=evidence_role,
                signal_type="quiz_attempt",
                weight=weight,
                payload=payload,
                observed_at=attempt.created_at,
            )
        )

    async def upsert_reflection_bridge_evidence(
        self,
        *,
        memory_type: str,
        memory_id: str,
        learner_profile_id: str,
        learner_goal_id: str | None,
        reflection: ReflectionRecord,
        evaluation: ReflectionOutcomeEvaluation,
    ) -> None:
        if self._evidence_link_repository is None:
            return
        role = MemoryNormalizer.classify_evidence_role(
            memory_type=memory_type,
            evidence_source_type="reflection_outcome",
            evaluation_status=evaluation.evaluation_status,
        )
        weight_key = "reflection_effective_weight" if role == "supporting" else "reflection_ineffective_weight"
        await self._evidence_link_repository.upsert(
            MemoryEvidenceLink.build(
                memory_type=memory_type,
                memory_id=memory_id,
                learner_profile_id=learner_profile_id,
                learner_goal_id=learner_goal_id,
                evidence_source_type="reflection_outcome",
                evidence_source_id=evaluation.id,
                evidence_role=role,
                signal_type=f"reflection:{evaluation.evaluation_status}",
                weight=float(self._governance_config.get(weight_key, 0.1)),
                payload={
                    "reflection_record_id": reflection.id,
                    "evaluation_status": evaluation.evaluation_status,
                    "improvement_score": evaluation.improvement_score,
                },
                observed_at=evaluation.updated_at,
            )
        )
        observe_memory_evidence_upsert(
            memory_type=memory_type,
            evidence_source_type="reflection_outcome",
            evidence_role=role,
        )

    async def list_relevant_attempts(self, learner_goal_id: str | None, topic_key: str) -> list[TaskAttempt]:
        if learner_goal_id is None or self._task_attempt_repository is None:
            return []
        attempts = await self._task_attempt_repository.list_recent_by_goal(learner_goal_id, limit=50)
        return [
            item
            for item in attempts
            if topic_alignment_score(
                topic_key,
                item.topic_focus,
                title=item.result_note,
                tags=[item.task_type],
                extras=None,
            )
            >= 0.45
        ]

    async def get_relevant_mastery(self, learner_goal_id: str | None, topic_key: str) -> LearnerTopicMastery | None:
        if learner_goal_id is None or self._learner_topic_mastery_repository is None:
            return None
        return await self._learner_topic_mastery_repository.get_by_goal_and_topic(learner_goal_id, topic_key)

    async def list_relevant_events(self, learner_profile_id: str, topic_key: str) -> list[MemoryEvent]:
        if self._memory_event_repository is None:
            return []
        since = datetime.now(timezone.utc) - timedelta(days=90)
        events = await self._memory_event_repository.list_by_profile_since(learner_profile_id=learner_profile_id, since=since)
        return [
            item
            for item in events
            if topic_alignment_score(
                topic_key,
                item.concept_focus or item.summary,
                title=item.summary,
                tags=item.tags,
                extras=None,
            )
            >= 0.45
        ]

    def compute_knowledge_evidence(
        self,
        memory: KnowledgeMemory,
        attempts: list[TaskAttempt],
        mastery: LearnerTopicMastery | None,
        events: list[MemoryEvent],
    ) -> tuple[float, float, int, int, int, int]:
        support_score = 0.0
        contradiction_score = 0.0
        evidence_count = 0
        contradiction_count = 0
        assessment_count = 0
        task_count = 0
        for attempt in attempts:
            if attempt.outcome_status == "completed":
                if attempt.task_type == "assessment":
                    support_score += KNOWLEDGE_EVIDENCE_WEIGHTS.completed_assessment
                    assessment_count += 1
                elif attempt.task_type in {"practice", "review"}:
                    support_score += KNOWLEDGE_EVIDENCE_WEIGHTS.completed_practice_or_review
                else:
                    support_score += KNOWLEDGE_EVIDENCE_WEIGHTS.completed_other_task
                evidence_count += 1
                task_count += 1
            elif attempt.outcome_status == "failed":
                contradiction_score += (
                    KNOWLEDGE_EVIDENCE_WEIGHTS.failed_assessment
                    if attempt.task_type == "assessment"
                    else KNOWLEDGE_EVIDENCE_WEIGHTS.failed_other_task
                )
                contradiction_count += 1
                task_count += 1
        for event in events:
            if event.memory_scope == "profile":
                if event.progress_note is not None:
                    support_score += KNOWLEDGE_EVIDENCE_WEIGHTS.progress_event
                    evidence_count += 1
                if event.struggle_note is not None:
                    contradiction_score += KNOWLEDGE_EVIDENCE_WEIGHTS.struggle_event
                    contradiction_count += 1
                if event.progress_note is None and event.struggle_note is None:
                    support_score += KNOWLEDGE_EVIDENCE_WEIGHTS.neutral_event_refresh
                    evidence_count += 1
        if mastery is not None:
            if mastery.mastery_score >= 0.7 and mastery.confidence >= 0.6:
                support_score += KNOWLEDGE_EVIDENCE_WEIGHTS.strong_mastery
                evidence_count += 1
            elif mastery.mastery_score <= 0.4 and mastery.confidence >= 0.6:
                contradiction_score += KNOWLEDGE_EVIDENCE_WEIGHTS.weak_mastery
                contradiction_count += 1
        return (
            clamp_score(support_score),
            clamp_score(contradiction_score),
            evidence_count,
            contradiction_count,
            assessment_count,
            task_count,
        )

    def compute_behavior_evidence(
        self,
        memory: BehaviorMemory,
        attempts: list[TaskAttempt],
        events: list[MemoryEvent],
    ) -> tuple[float, float, int, int, int]:
        support_score = 0.0
        contradiction_score = 0.0
        evidence_count = 0
        contradiction_count = 0
        recurrence_count = 0
        session_ids = {event.session_id for event in events}
        recurrence_count = max(len(session_ids) - 1, 0)
        if recurrence_count > 0:
            support_score += min(
                recurrence_count * BEHAVIOR_EVIDENCE_WEIGHTS.recurrence_per_session,
                BEHAVIOR_EVIDENCE_WEIGHTS.max_recurrence_support,
            )
            evidence_count += recurrence_count
        for attempt in attempts:
            if attempt.outcome_status in {"failed", "skipped"}:
                support_score += BEHAVIOR_EVIDENCE_WEIGHTS.failed_or_skipped_task
                evidence_count += 1
            elif attempt.outcome_status == "completed":
                contradiction_score += BEHAVIOR_EVIDENCE_WEIGHTS.completed_task_contradiction
                contradiction_count += 1
        return (
            clamp_score(support_score),
            clamp_score(contradiction_score),
            evidence_count,
            contradiction_count,
            recurrence_count,
        )

    @staticmethod
    def compute_knowledge_stability(
        *,
        confidence_score: float,
        support_score: float,
        contradiction_score: float,
        freshness_score: float,
        goal_relevance_score: float,
        assessment_count: int,
    ) -> float:
        assessment_factor = 1.0 if assessment_count > 0 else 0.0
        return clamp_score(
            0.3 * confidence_score
            + 0.25 * support_score
            + 0.2 * assessment_factor
            + 0.15 * freshness_score
            + 0.1 * goal_relevance_score
            - 0.3 * contradiction_score
        )

    @staticmethod
    def compute_behavior_stability(
        *,
        confidence_score: float,
        support_score: float,
        contradiction_score: float,
        freshness_score: float,
        goal_relevance_score: float,
        recurrence_count: int,
        intervention_success_count: int,
        intervention_failure_count: int,
    ) -> float:
        recurrence_factor = clamp_score(recurrence_count / 3)
        intervention_factor = clamp_score((intervention_success_count + intervention_failure_count) / 4)
        return clamp_score(
            0.25 * confidence_score
            + 0.25 * support_score
            + 0.2 * recurrence_factor
            + 0.15 * intervention_factor
            + 0.15 * freshness_score
            - 0.25 * contradiction_score
            + 0.05 * goal_relevance_score
        )

    @staticmethod
    def adjust_knowledge_importance(
        *,
        memory: KnowledgeMemory,
        support_score: float,
        contradiction_score: float,
        assessment_count: int,
    ) -> float:
        delta = support_score * 0.12 + min(assessment_count, 2) * 0.04 - contradiction_score * 0.1
        return clamp_score(memory.importance_score * 0.88 + delta)

    @staticmethod
    def adjust_knowledge_confidence(
        *,
        memory: KnowledgeMemory,
        evidence_count: int,
        contradiction_count: int,
        mastery: LearnerTopicMastery | None,
    ) -> float:
        mastery_bonus = 0.08 if mastery is not None and mastery.confidence >= 0.6 else 0.0
        evidence_bonus = min(evidence_count, 5) * 0.04
        contradiction_penalty = min(contradiction_count, 4) * 0.06
        return clamp_score(memory.confidence_score * 0.82 + mastery_bonus + evidence_bonus - contradiction_penalty)

    @staticmethod
    def adjust_behavior_importance(
        *,
        memory: BehaviorMemory,
        support_score: float,
        contradiction_score: float,
        recurrence_count: int,
    ) -> float:
        delta = support_score * 0.14 + min(recurrence_count, 3) * 0.05 - contradiction_score * 0.08
        return clamp_score(memory.importance_score * 0.9 + delta)

    @staticmethod
    def adjust_behavior_confidence(
        *,
        memory: BehaviorMemory,
        evidence_count: int,
        contradiction_count: int,
        recurrence_count: int,
    ) -> float:
        recurrence_bonus = min(recurrence_count, 3) * 0.06
        evidence_bonus = min(evidence_count, 5) * 0.03
        contradiction_penalty = min(contradiction_count, 4) * 0.05
        return clamp_score(memory.confidence_score * 0.84 + recurrence_bonus + evidence_bonus - contradiction_penalty)

    async def list_evidence_links(self, *, memory_type: str, memory_id: str) -> list[MemoryEvidenceLink]:
        if self._evidence_link_repository is None:
            return []
        return await self._evidence_link_repository.list_by_memory(memory_type=memory_type, memory_id=memory_id)
