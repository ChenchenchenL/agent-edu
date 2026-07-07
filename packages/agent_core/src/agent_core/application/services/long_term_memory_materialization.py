from __future__ import annotations

import re
from dataclasses import dataclass, replace

from agent_core.application.services.audit import AuditService
from agent_core.application.services.memory_extraction import (
    MemoryExtractionValidationResult,
    ValidatedMemoryExtractionCandidate,
    validate_structured_memory_extraction,
)
from agent_core.application.services.memory_normalization import MemoryNormalizer
from agent_core.application.services.memory import LongTermMemoryUpsertResult, MemoryService
from agent_core.domain.entities.autonomy import TaskAttempt
from agent_core.domain.entities.memory import BehaviorMemory, KnowledgeMemory
from agent_core.domain.entities.memory import MemoryEvent
from agent_core.domain.entities.planning import DailyTask
from agent_core.domain.entities.reflection import ReflectionRecord
from agent_core.domain.entities.reflection_v2 import ReflectionOutcomeEvaluation
from agent_core.domain.entities.session.quiz import SessionQuizAnswerAttempt
from agent_core.infrastructure.observability.metrics import observe_long_term_memory_materialization


@dataclass(frozen=True)
class LongTermMemoryMaterializationResult:
    knowledge: list[LongTermMemoryUpsertResult]
    behavior: list[LongTermMemoryUpsertResult]
    skipped_reason: str | None = None
    rejected_count: int = 0


class LongTermMemoryMaterializationService:
    def __init__(self, memory_service: MemoryService, audit_service: AuditService | None = None) -> None:
        self._memory_service = memory_service
        self._audit_service = audit_service

    async def materialize_from_chat_turn(
        self,
        *,
        session_id: str,
        learner_profile_id: str,
        learner_goal_id: str | None,
        learner_message: str,
        assistant_message: str,
        source_message_id: str,
        mode: str | None,
        subject: str | None,
        session_title: str | None,
        memory_events: list[MemoryEvent],
        persist_embeddings: bool = True,
    ) -> LongTermMemoryMaterializationResult:
        profile_event = next((item for item in memory_events if item.memory_scope == "profile"), None)
        if profile_event is None:
            observe_long_term_memory_materialization(
                source_type="chat_turn",
                status="skipped",
                reason_code="missing_profile_memory_event",
            )
            return LongTermMemoryMaterializationResult(knowledge=[], behavior=[], skipped_reason="missing_profile_memory_event")

        knowledge = self._memory_service.build_knowledge_memory_candidate(
            learner_profile_id=learner_profile_id,
            learner_goal_id=learner_goal_id,
            learner_message=learner_message,
            assistant_message=assistant_message,
            source_message_id=source_message_id,
            mode=mode,
            subject=subject,
            session_title=session_title,
            source_event_ids=[profile_event.id],
            provenance_type="session_event",
            provenance_source_id=profile_event.id,
        )
        behavior = self._memory_service.build_behavior_memory_candidate(
            learner_profile_id=learner_profile_id,
            learner_goal_id=learner_goal_id,
            learner_message=learner_message,
            assistant_message=assistant_message,
            source_message_id=source_message_id,
            mode=mode,
            subject=subject,
            session_title=session_title,
            source_event_ids=[profile_event.id],
            provenance_type="session_event",
            provenance_source_id=profile_event.id,
        )
        knowledge_results = []
        behavior_results = []
        if knowledge is not None:
            result = await self._memory_service.upsert_knowledge_memory(knowledge, persist_embedding=persist_embeddings)
            if result.action not in {"skipped", "skipped_suppressed"}:
                await self._memory_service.upsert_session_memory_event_evidence(
                    memory=result.memory,
                    memory_type="knowledge",
                    event=profile_event,
                )
            knowledge_results.append(result)
        if behavior is not None:
            result = await self._memory_service.upsert_behavior_memory(behavior, persist_embedding=persist_embeddings)
            if result.action not in {"skipped", "skipped_suppressed"}:
                await self._memory_service.upsert_session_memory_event_evidence(
                    memory=result.memory,
                    memory_type="behavior",
                    event=profile_event,
                )
            behavior_results.append(result)
        observe_long_term_memory_materialization(source_type="chat_turn", status="succeeded")
        return LongTermMemoryMaterializationResult(knowledge=knowledge_results, behavior=behavior_results)

    async def materialize_from_task_outcome(
        self,
        *,
        learner_profile_id: str,
        task: DailyTask,
        attempt: TaskAttempt,
        persist_embeddings: bool = True,
    ) -> LongTermMemoryMaterializationResult:
        if attempt.outcome_status not in {"completed", "failed", "skipped"}:
            observe_long_term_memory_materialization(
                source_type="task_outcome",
                status="skipped",
                reason_code="non_terminal_task_status",
            )
            return LongTermMemoryMaterializationResult(knowledge=[], behavior=[], skipped_reason="non_terminal_task_status")

        learner_message = attempt.result_note or task.title
        assistant_message = task.instructions
        knowledge = self._memory_service.build_knowledge_memory_candidate(
            learner_profile_id=learner_profile_id,
            learner_goal_id=task.learner_goal_id,
            learner_message=learner_message,
            assistant_message=assistant_message,
            source_message_id=None,
            mode=task.execution_mode,
            subject=task.topic_focus,
            session_title=task.title,
            source_event_ids=[],
            provenance_type="task_attempt",
            provenance_source_id=attempt.id,
        )
        behavior = None
        if attempt.outcome_status in {"failed", "skipped"}:
            behavior_message = learner_message
            if "stuck" not in behavior_message.casefold() and "confused" not in behavior_message.casefold():
                behavior_message = f"Learner was stuck on {task.topic_focus}: {behavior_message}"
            behavior = self._memory_service.build_behavior_memory_candidate(
                learner_profile_id=learner_profile_id,
                learner_goal_id=task.learner_goal_id,
                learner_message=behavior_message,
                assistant_message=assistant_message,
                source_message_id=None,
                mode=task.execution_mode,
                subject=task.topic_focus,
                session_title=task.title,
                source_event_ids=[],
                provenance_type="task_attempt",
                provenance_source_id=attempt.id,
            )
        elif attempt.outcome_status == "completed":
            if attempt.result_note:
                note_lower = attempt.result_note.casefold()
                # Enhanced negative context detection using regex
                hint_negation_patterns = [
                    r"no hint", r"without hint", r"didn't need hint", r"don't need hint",
                    r"didn't use hint", r"skip.*hint", r"avoid.*hint", r"no need.*hint",
                    r"didn't require hint", r"no hint.*needed"
                ]
                is_hint = "hint" in note_lower and not any(
                    re.search(pattern, note_lower) for pattern in hint_negation_patterns
                )
                # Step-by-step detection (less prone to false positives)
                is_step = any(kw in note_lower for kw in ["step-by-step", "step by step", "deduction", "deduced"])
                # Enhanced negative context detection for review
                review_negation_patterns = [
                    r"no review", r"no need to review", r"without review", r"didn't review",
                    r"skip.*review", r"avoid.*review", r"no need.*review", r"didn't need review",
                    r"no review.*needed"
                ]
                is_review = any(kw in note_lower for kw in ["review", "reviewed"]) and not any(
                    re.search(pattern, note_lower) for pattern in review_negation_patterns
                )

                if is_hint or is_step or is_review:
                    if is_hint:
                        category = "guided_progress"
                        summary_msg = f"Learner successfully utilized hints for support on {task.topic_focus}: {attempt.result_note}"
                        tags = ["behavior", task.execution_mode, "guided_progress", "success_pattern", "positive"]
                    elif is_step:
                        category = "response_preference"
                        summary_msg = f"Learner successfully applied a step-by-step reasoning strategy on {task.topic_focus}: {attempt.result_note}"
                        tags = ["behavior", task.execution_mode, "response_preference", "success_pattern", "positive"]
                    else:  # is_review
                        category = "guided_progress"
                        summary_msg = f"Learner successfully reviewed prior material or quizzes before assessment on {task.topic_focus}: {attempt.result_note}"
                        tags = ["behavior", task.execution_mode, "guided_progress", "success_pattern", "positive"]

                    raw_candidate = self._memory_service.build_behavior_memory_candidate(
                        learner_profile_id=learner_profile_id,
                        learner_goal_id=task.learner_goal_id,
                        learner_message=summary_msg,
                        assistant_message=assistant_message,
                        source_message_id=None,
                        mode=task.execution_mode,
                        subject=task.topic_focus,
                        session_title=task.title,
                        source_event_ids=[],
                        provenance_type="task_attempt",
                        provenance_source_id=attempt.id,
                    )
                    if raw_candidate is not None:
                        behavior = replace(
                            raw_candidate,
                            behavior_category=category,
                            behavior_key=MemoryNormalizer.normalize_topic_key(f"{category}:{task.topic_focus or task.title or 'session'}"),
                            title=f"{category.replace('_', ' ').title()} for {task.topic_focus or task.title or 'session'}",
                            summary=summary_msg,
                            tags=tags,
                            importance_score=0.40,
                            confidence_score=0.40,
                            freshness_score=0.40,
                        )

        knowledge_results = []
        behavior_results = []
        if knowledge is not None:
            result = await self._memory_service.upsert_knowledge_memory(knowledge, persist_embedding=persist_embeddings)
            if result.action not in {"skipped", "skipped_suppressed"}:
                await self._memory_service.upsert_task_attempt_evidence(
                    memory=result.memory,
                    memory_type="knowledge",
                    attempt=attempt,
                )
            knowledge_results.append(result)
        if behavior is not None:
            result = await self._memory_service.upsert_behavior_memory(behavior, persist_embedding=persist_embeddings)
            if result.action not in {"skipped", "skipped_suppressed"}:
                await self._memory_service.upsert_task_attempt_evidence(
                    memory=result.memory,
                    memory_type="behavior",
                    attempt=attempt,
                )
            behavior_results.append(result)
        observe_long_term_memory_materialization(source_type="task_outcome", status="succeeded")
        return LongTermMemoryMaterializationResult(knowledge=knowledge_results, behavior=behavior_results)

    async def materialize_from_reflection_outcome(
        self,
        *,
        reflection: ReflectionRecord,
        evaluation: ReflectionOutcomeEvaluation,
        persist_embeddings: bool = True,
    ) -> LongTermMemoryMaterializationResult:
        if evaluation.evaluation_status not in {"effective", "ineffective"}:
            observe_long_term_memory_materialization(
                source_type="reflection_outcome",
                status="skipped",
                reason_code="unsupported_evaluation_status",
            )
            return LongTermMemoryMaterializationResult(knowledge=[], behavior=[], skipped_reason="unsupported_evaluation_status")
        topic = self._topic_from_reflection(reflection)
        if topic is None:
            observe_long_term_memory_materialization(
                source_type="reflection_outcome",
                status="skipped",
                reason_code="missing_reflection_topic",
            )
            return LongTermMemoryMaterializationResult(knowledge=[], behavior=[], skipped_reason="missing_reflection_topic")

        learner_message = reflection.evidence_summary or reflection.summary
        assistant_message = reflection.recommended_next_step
        knowledge = self._memory_service.build_knowledge_memory_candidate(
            learner_profile_id=reflection.learner_profile_id,
            learner_goal_id=reflection.learner_goal_id,
            learner_message=learner_message,
            assistant_message=assistant_message,
            source_message_id=None,
            mode="reflection",
            subject=topic,
            session_title=reflection.summary,
            source_event_ids=[],
            provenance_type="reflection",
            provenance_source_id=evaluation.id,
        )
        behavior = None
        if evaluation.evaluation_status == "ineffective":
            behavior = self._memory_service.build_behavior_memory_candidate(
                learner_profile_id=reflection.learner_profile_id,
                learner_goal_id=reflection.learner_goal_id,
                learner_message=learner_message,
                assistant_message=assistant_message,
                source_message_id=None,
                mode="reflection",
                subject=topic,
                session_title=reflection.summary,
                source_event_ids=[],
                provenance_type="reflection",
                provenance_source_id=evaluation.id,
            )

        knowledge_results = []
        behavior_results = []
        if knowledge is not None:
            result = await self._memory_service.upsert_knowledge_memory(knowledge, persist_embedding=persist_embeddings)
            if result.action not in {"skipped", "skipped_suppressed"}:
                await self._memory_service.upsert_reflection_outcome_evidence(
                    memory=result.memory,
                    memory_type="knowledge",
                    reflection=reflection,
                    evaluation=evaluation,
                )
            knowledge_results.append(result)
        if behavior is not None:
            result = await self._memory_service.upsert_behavior_memory(behavior, persist_embedding=persist_embeddings)
            if result.action not in {"skipped", "skipped_suppressed"}:
                await self._memory_service.upsert_reflection_outcome_evidence(
                    memory=result.memory,
                    memory_type="behavior",
                    reflection=reflection,
                    evaluation=evaluation,
                )
            behavior_results.append(result)
        observe_long_term_memory_materialization(source_type="reflection_outcome", status="succeeded")
        return LongTermMemoryMaterializationResult(knowledge=knowledge_results, behavior=behavior_results)

    async def materialize_from_structured_extraction(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None,
        raw_candidates: list[dict[str, object]],
        provenance_source_id: str | None,
        persist_embeddings: bool = True,
    ) -> LongTermMemoryMaterializationResult:
        validation = validate_structured_memory_extraction(raw_candidates)
        await self._record_structured_extraction_rejections(
            validation=validation,
            provenance_source_id=provenance_source_id,
        )
        if not validation.candidates:
            observe_long_term_memory_materialization(
                source_type="structured_extraction",
                status="skipped",
                reason_code="structured_extraction_no_valid_candidates",
            )
            return LongTermMemoryMaterializationResult(
                knowledge=[],
                behavior=[],
                skipped_reason="structured_extraction_no_valid_candidates",
                rejected_count=len(validation.rejected),
            )
        knowledge_results: list[LongTermMemoryUpsertResult] = []
        behavior_results: list[LongTermMemoryUpsertResult] = []
        for candidate in validation.candidates:
            if candidate.memory_type == "knowledge":
                result = await self._materialize_structured_knowledge_candidate(
                    learner_profile_id=learner_profile_id,
                    learner_goal_id=learner_goal_id,
                    candidate=candidate,
                    provenance_source_id=provenance_source_id,
                    persist_embeddings=persist_embeddings,
                )
                knowledge_results.append(result)
            else:
                result = await self._materialize_structured_behavior_candidate(
                    learner_profile_id=learner_profile_id,
                    learner_goal_id=learner_goal_id,
                    candidate=candidate,
                    provenance_source_id=provenance_source_id,
                    persist_embeddings=persist_embeddings,
                )
                behavior_results.append(result)
        observe_long_term_memory_materialization(source_type="structured_extraction", status="succeeded")
        return LongTermMemoryMaterializationResult(
            knowledge=knowledge_results,
            behavior=behavior_results,
            rejected_count=len(validation.rejected),
        )

    async def _record_structured_extraction_rejections(
        self,
        *,
        validation: MemoryExtractionValidationResult,
        provenance_source_id: str | None,
    ) -> None:
        if self._audit_service is None:
            return
        for rejected in validation.rejected:
            await self._audit_service.record(
                event_type="long_term_memory.extraction.validation_failed",
                resource_type="long_term_memory_extraction",
                resource_id=provenance_source_id,
                actor="system",
                event_data={
                    "source_type": "structured_extraction",
                    "source_id": provenance_source_id,
                    "candidate_index": rejected.index,
                    "reason_code": rejected.reason_code,
                    "reason": rejected.reason,
                },
            )

    async def _materialize_structured_knowledge_candidate(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None,
        candidate: ValidatedMemoryExtractionCandidate,
        provenance_source_id: str | None,
        persist_embeddings: bool,
    ) -> LongTermMemoryUpsertResult:
        knowledge_level = "foundation" if candidate.semantic_category == "prerequisite" else "core"
        memory = KnowledgeMemory.build(
            learner_profile_id=learner_profile_id,
            learner_goal_id=learner_goal_id,
            knowledge_key=candidate.topic_key,
            title=candidate.title,
            summary=candidate.summary,
            details=candidate.details,
            knowledge_level=knowledge_level,
            time_horizon="early" if knowledge_level == "foundation" else "mid",
            importance_score=candidate.importance_score,
            confidence_score=candidate.confidence_score,
            freshness_score=0.50,
            prerequisite_keys=[],
            source_event_ids=[],
            source_memory_ids=[],
            tags=["structured_extraction", candidate.evidence_role, *candidate.tags],
        )
        memory = KnowledgeMemory(
            **{
                **memory.__dict__,
                "semantic_category": candidate.semantic_category,
                "provenance_type": "system_inference",
                "provenance_source_id": provenance_source_id,
            }
        )
        return await self._memory_service.upsert_knowledge_memory(memory, persist_embedding=persist_embeddings)

    async def _materialize_structured_behavior_candidate(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None,
        candidate: ValidatedMemoryExtractionCandidate,
        provenance_source_id: str | None,
        persist_embeddings: bool,
    ) -> LongTermMemoryUpsertResult:
        behavior_category = candidate.behavior_category or "response_preference"
        behavior_key = MemoryNormalizer.normalize_topic_key(f"{behavior_category}:{candidate.topic}")
        memory = BehaviorMemory.build(
            learner_profile_id=learner_profile_id,
            learner_goal_id=learner_goal_id,
            behavior_key=behavior_key,
            behavior_category=behavior_category,
            title=candidate.title,
            summary=candidate.summary,
            details=candidate.details,
            behavior_level="recurrent" if behavior_category in {"support_request", "error_pattern"} else "persistent",
            time_horizon="mid",
            importance_score=candidate.importance_score,
            confidence_score=candidate.confidence_score,
            freshness_score=0.40,
            source_event_ids=[],
            source_memory_ids=[],
            tags=["structured_extraction", candidate.evidence_role, *candidate.tags],
            intervention_effect=None,
        )
        memory = BehaviorMemory(
            **{
                **memory.__dict__,
                "semantic_category": candidate.semantic_category,
                "provenance_type": "system_inference",
                "provenance_source_id": provenance_source_id,
            }
        )
        return await self._memory_service.upsert_behavior_memory(memory, persist_embedding=persist_embeddings)

    async def materialize_from_answer_attempt(
        self,
        *,
        attempt: SessionQuizAnswerAttempt,
        persist_embeddings: bool = True,
    ) -> LongTermMemoryMaterializationResult:
        """Materializes knowledge and behavior memory candidates from a quiz answer attempt.

        Args:
            attempt: The SessionQuizAnswerAttempt entity.
            persist_embeddings: Whether to persist vector embeddings.

        Returns:
            LongTermMemoryMaterializationResult containing upsert results.
        """
        knowledge = None
        topic_key_normalized = MemoryNormalizer.normalize_topic_key(attempt.topic_key)

        if attempt.is_correct is False or attempt.misconception_codes:
            knowledge = KnowledgeMemory.build(
                learner_profile_id=attempt.learner_profile_id,
                learner_goal_id=attempt.learner_goal_id,
                knowledge_key=topic_key_normalized,
                title=f"Struggle with {attempt.topic_key}",
                summary=f"Learner struggles with {attempt.topic_key}.",
                details=f"Question: {attempt.question_prompt}\nReference Answer: {attempt.reference_answer}\nLearner Answer: {attempt.learner_answer}",
                knowledge_level="core",
                time_horizon="mid",
                importance_score=0.5,
                confidence_score=0.4,
                freshness_score=1.0,
                prerequisite_keys=[],
                source_event_ids=[],
                source_memory_ids=[],
                tags=["quiz_attempt", "struggle"],
            )
            knowledge = replace(
                knowledge,
                provenance_type="quiz_answer_attempt",
                provenance_source_id=attempt.id,
            )
        elif attempt.is_correct is True:
            knowledge = KnowledgeMemory.build(
                learner_profile_id=attempt.learner_profile_id,
                learner_goal_id=attempt.learner_goal_id,
                knowledge_key=topic_key_normalized,
                title=f"Mastery of {attempt.topic_key}",
                summary=f"Learner demonstrated understanding of {attempt.topic_key}.",
                details=f"Question: {attempt.question_prompt}\nLearner Answer: {attempt.learner_answer}",
                knowledge_level="core",
                time_horizon="mid",
                importance_score=0.4,
                confidence_score=0.4,
                freshness_score=1.0,
                prerequisite_keys=[],
                source_event_ids=[],
                source_memory_ids=[],
                tags=["quiz_attempt", "success"],
            )
            knowledge = replace(
                knowledge,
                provenance_type="quiz_answer_attempt",
                provenance_source_id=attempt.id,
            )
        elif attempt.grading_status == "needs_review":
            knowledge = KnowledgeMemory.build(
                learner_profile_id=attempt.learner_profile_id,
                learner_goal_id=attempt.learner_goal_id,
                knowledge_key=topic_key_normalized,
                title=f"Pending review for {attempt.topic_key}",
                summary=f"Learner attempt on {attempt.topic_key} requires human review.",
                details=f"Question: {attempt.question_prompt}\nLearner Answer: {attempt.learner_answer}",
                knowledge_level="core",
                time_horizon="mid",
                importance_score=0.3,
                confidence_score=0.3,
                freshness_score=1.0,
                prerequisite_keys=[],
                source_event_ids=[],
                source_memory_ids=[],
                tags=["quiz_attempt", "needs_review"],
            )
            knowledge = replace(
                knowledge,
                provenance_type="quiz_answer_attempt",
                provenance_source_id=attempt.id,
            )

        behavior = None
        if attempt.is_correct is True and not attempt.hint_used:
            behavior_category = "guided_progress"
            summary = f"Learner independently solved problems on {attempt.topic_key}."
            behavior_tags = ["quiz_attempt", "behavior", "success_pattern", "positive"]
            behavior_importance = 0.4
        elif attempt.hint_used or (attempt.learner_answer and len(attempt.learner_answer.strip()) < 3):
            behavior_category = "support_request" if attempt.hint_used else "response_preference"
            if attempt.learner_answer and len(attempt.learner_answer.strip()) < 3 and attempt.hint_used:
                summary = "Learner often submits short guesses before requesting hints."
            elif attempt.hint_used:
                summary = "Learner used hints during quiz."
            else:
                summary = f"Learner submits short guess '{attempt.learner_answer}'."
            behavior_tags = ["quiz_attempt", "behavior"]
            behavior_importance = 0.4
        else:
            behavior_category = None
            summary = None
            behavior_tags = []

        if behavior_category is not None and summary is not None:
            behavior = BehaviorMemory.build(
                learner_profile_id=attempt.learner_profile_id,
                learner_goal_id=attempt.learner_goal_id,
                behavior_key=MemoryNormalizer.normalize_topic_key(f"{behavior_category}:{attempt.topic_key}"),
                behavior_category=behavior_category,
                title=f"Behavior pattern for {attempt.topic_key}",
                summary=summary,
                details=f"Question: {attempt.question_prompt}\nLearner Answer: {attempt.learner_answer}\nHint Used: {attempt.hint_used}\nHint Count: {attempt.hint_count}",
                behavior_level="recurrent",
                time_horizon="mid",
                importance_score=behavior_importance,
                confidence_score=0.4,
                freshness_score=0.4,
                source_event_ids=[],
                source_memory_ids=[],
                tags=behavior_tags,
                intervention_effect=None,
            )
            behavior = replace(
                behavior,
                provenance_type="quiz_answer_attempt",
                provenance_source_id=attempt.id,
            )

        knowledge_results = []
        behavior_results = []
        if knowledge is not None:
            result = await self._memory_service.upsert_knowledge_memory(knowledge, persist_embedding=persist_embeddings)
            if result.action not in {"skipped", "skipped_suppressed"}:
                await self._memory_service.upsert_quiz_answer_attempt_evidence(
                    memory=result.memory,
                    memory_type="knowledge",
                    attempt=attempt,
                )
            knowledge_results.append(result)
        if behavior is not None:
            result = await self._memory_service.upsert_behavior_memory(behavior, persist_embedding=persist_embeddings)
            if result.action not in {"skipped", "skipped_suppressed"}:
                await self._memory_service.upsert_quiz_answer_attempt_evidence(
                    memory=result.memory,
                    memory_type="behavior",
                    attempt=attempt,
                )
            behavior_results.append(result)

        observe_long_term_memory_materialization(source_type="quiz_answer_attempt", status="succeeded")
        return LongTermMemoryMaterializationResult(knowledge=knowledge_results, behavior=behavior_results)

    @staticmethod
    def _topic_from_reflection(reflection: ReflectionRecord) -> str | None:
        task = reflection.evidence_payload.get("task") or {}
        workflow = reflection.evidence_payload.get("workflow") or {}
        topic = str(task.get("topic_focus") or workflow.get("topic_focus") or "").strip()
        return topic or None
