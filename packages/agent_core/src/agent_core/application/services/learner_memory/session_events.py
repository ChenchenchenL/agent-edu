"""Session event recording and learning signal extraction."""

from __future__ import annotations

from agent_core.domain.entities.memory import (
    MemoryEmbeddingRecord,
    MemoryEvent,
)
from agent_core.application.services.audit import AuditService
from agent_core.infrastructure.db.repositories import (
    MemoryEmbeddingRepository,
    MemoryEventRepository,
)
from agent_core.infrastructure.embedding.types import EmbeddingProvider


def infer_struggle_note(learner_message: str) -> str | None:
    lowered = learner_message.casefold()
    if any(token in lowered for token in ["don't understand", "dont understand", "confused", "stuck", "wrong"]):
        return learner_message[:220].strip()
    if "hint" in lowered or "help" in lowered:
        return f"Learner requested guided support: {learner_message[:180].strip()}"
    return None


def infer_progress_note(*, assistant_message: str, mode: str | None) -> str | None:
    if mode == "hint":
        return "Learner continued after requesting a guided hint."
    if assistant_message.strip():
        return f"Session advanced with a structured reply: {assistant_message[:180].strip()}"
    return None


def infer_concept_focus(learner_message: str) -> str | None:
    normalized = learner_message.replace("?", " ").replace(",", " ").split()
    if not normalized:
        return None
    return " ".join(normalized[: min(4, len(normalized))]).strip() or None


def build_event_summary(
    *,
    topic: str,
    concept_focus: str | None,
    struggle_note: str | None,
    progress_note: str | None,
    mode: str | None,
) -> str:
    summary_parts = [f"Topic: {topic}"]
    if concept_focus is not None:
        summary_parts.append(f"Concept focus: {concept_focus}")
    if struggle_note is not None:
        summary_parts.append(f"Struggle: {struggle_note}")
    if progress_note is not None:
        summary_parts.append(f"Progress: {progress_note}")
    summary_parts.append(f"Mode: {mode or 'chat'}")
    return " | ".join(summary_parts)


def build_profile_summary(
    *,
    topic: str,
    concept_focus: str | None,
    progress_note: str | None,
    struggle_note: str | None,
) -> str:
    summary = [f"Learner profile update for {topic}."]
    if concept_focus is not None:
        summary.append(f"Current concept trend: {concept_focus}.")
    if struggle_note is not None:
        summary.append(f"Recurring struggle: {struggle_note}.")
    if progress_note is not None:
        summary.append(f"Progress signal: {progress_note}.")
    return " ".join(summary)


def build_tags(*, mode: str | None, concept_focus: str | None, struggle_note: str | None) -> list[str]:
    tags = ["session", mode or "chat"]
    if concept_focus is not None:
        tags.append("concept")
    if struggle_note is not None:
        tags.append("struggle")
    return tags


class SessionEventRecorder:
    """Records session-level memory events with optional embedding and audit."""

    def __init__(
        self,
        repository: MemoryEventRepository,
        *,
        embedding_provider: EmbeddingProvider | None = None,
        embedding_repository: MemoryEmbeddingRepository | None = None,
        audit_service: AuditService | None = None,
    ) -> None:
        self._repository = repository
        self._embedding_provider = embedding_provider
        self._embedding_repository = embedding_repository
        self._audit_service = audit_service

    @property
    def embedding_provider_name(self) -> str | None:
        return self._embedding_provider.provider_name if self._embedding_provider is not None else None

    @property
    def embedding_model_name(self) -> str | None:
        return self._embedding_provider.model_name if self._embedding_provider is not None else None

    async def record_session_event(
        self,
        *,
        session_id: str,
        learner_profile_id: str,
        memory_scope: str,
        memory_level: str,
        summary: str,
        progress_note: str | None,
        struggle_note: str | None,
        concept_focus: str | None,
        source_message_id: str | None,
        tags: list[str],
    ) -> MemoryEvent:
        event = MemoryEvent.build(
            session_id=session_id,
            learner_profile_id=learner_profile_id,
            event_type="session.note",
            memory_scope=memory_scope,
            memory_level=memory_level,
            summary=summary,
            progress_note=progress_note,
            struggle_note=struggle_note,
            concept_focus=concept_focus,
            source_message_id=source_message_id,
            tags=tags,
        )
        embedding_record: MemoryEmbeddingRecord | None = None
        failure_stage = "memory_event.persist"
        try:
            await self._repository.create(event)
            if self._embedding_provider is not None and self._embedding_repository is not None:
                failure_stage = "embedding.generate"
                vector = (await self._embedding_provider.embed_texts([summary]))[0]
                embedding_record = MemoryEmbeddingRecord.build(
                    memory_event_id=event.id,
                    session_id=session_id,
                    learner_profile_id=learner_profile_id,
                    memory_scope=memory_scope,
                    memory_level=memory_level,
                    provider=self._embedding_provider.provider_name,
                    model=self._embedding_provider.model_name,
                    vector=vector,
                    summary=summary,
                )
                failure_stage = "embedding.persist"
                await self._embedding_repository.create(embedding_record)
            if self._audit_service is not None:
                failure_stage = "audit.persist"
                await self._audit_service.record(
                    event_type="memory.event.recorded",
                    resource_type="memory_event",
                    resource_id=event.id,
                    actor="system",
                    event_data={
                        "memory_event_id": event.id,
                        "session_id": session_id,
                        "learner_profile_id": learner_profile_id,
                        "source_message_id": source_message_id,
                        "memory_scope": memory_scope,
                        "memory_level": memory_level,
                        "concept_focus": concept_focus,
                        "tags": tags,
                        "embedding_provider": embedding_record.provider if embedding_record is not None else None,
                        "embedding_model": embedding_record.model if embedding_record is not None else None,
                        "embedding_dimensions": embedding_record.dimensions if embedding_record is not None else None,
                    },
                )
            return event
        except Exception as exc:
            if self._audit_service is not None:
                await self._audit_service.record_durable(
                    event_type="memory.event.record.failed",
                    resource_type="memory_event",
                    resource_id=event.id,
                    actor="system",
                    event_data={
                        "memory_event_id": event.id,
                        "session_id": session_id,
                        "learner_profile_id": learner_profile_id,
                        "source_message_id": source_message_id,
                        "memory_scope": memory_scope,
                        "memory_level": memory_level,
                        "failure_stage": failure_stage,
                        "embedding_provider": self.embedding_provider_name,
                        "embedding_model": self.embedding_model_name,
                        "error": str(exc),
                    },
                )
            raise

    def extract_learning_signals(
        self,
        *,
        learner_message: str,
        assistant_message: str,
        mode: str | None,
        subject: str | None,
        session_title: str | None,
    ) -> list[dict[str, str | list[str] | None]]:
        topic = subject or session_title or infer_concept_focus(learner_message)
        struggle_note = infer_struggle_note(learner_message)
        progress_note = infer_progress_note(assistant_message=assistant_message, mode=mode)
        concept_focus = infer_concept_focus(learner_message) or topic
        summary = build_event_summary(
            topic=topic or "current topic",
            concept_focus=concept_focus,
            struggle_note=struggle_note,
            progress_note=progress_note,
            mode=mode,
        )
        events: list[dict[str, str | list[str] | None]] = [
            {
                "memory_scope": "session",
                "memory_level": "episodic",
                "summary": summary,
                "progress_note": progress_note,
                "struggle_note": struggle_note,
                "concept_focus": concept_focus,
                "tags": build_tags(mode=mode, concept_focus=concept_focus, struggle_note=struggle_note),
            }
        ]
        if progress_note is not None or struggle_note is not None:
            events.append(
                {
                    "memory_scope": "profile",
                    "memory_level": "semantic",
                    "summary": build_profile_summary(
                        topic=topic or "current topic",
                        concept_focus=concept_focus,
                        progress_note=progress_note,
                        struggle_note=struggle_note,
                    ),
                    "progress_note": progress_note,
                    "struggle_note": struggle_note,
                    "concept_focus": concept_focus,
                    "tags": build_tags(mode=mode, concept_focus=concept_focus, struggle_note=struggle_note)
                    + ["profile"],
                }
            )
        return events
