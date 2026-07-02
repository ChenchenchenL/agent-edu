"""Long-term memory candidate construction and topic alignment."""

from __future__ import annotations

from agent_core.application.services.memory_normalization import MemoryNormalizer
from agent_core.application.services.learner_memory.quality import clamp_score
from agent_core.application.services.learner_memory.session_events import (
    infer_concept_focus,
    infer_progress_note,
    infer_struggle_note,
)
from agent_core.domain.entities.memory import (
    BehaviorMemory,
    KnowledgeMemory,
)


def normalize_key(value: str) -> str:
    return MemoryNormalizer.normalize_topic_key(value)


def topic_tokens(value: str) -> list[str]:
    return MemoryNormalizer.topic_tokens(value)


def topic_matches(
    topic_key: str,
    candidate_key: str,
    *,
    title: str | None = None,
    tags: list[str] | None = None,
) -> bool:
    return topic_alignment_score(
        topic_key,
        candidate_key,
        title=title,
        tags=tags,
        extras=None,
    ) >= 0.55


def topic_alignment_score(
    topic_key: str,
    candidate_key: str,
    *,
    title: str | None,
    tags: list[str] | None,
    extras: list[str] | None,
) -> float:
    normalized_topic = normalize_key(topic_key)
    normalized_candidate = normalize_key(candidate_key)
    if normalized_topic == normalized_candidate:
        return 1.0
    topic_tkns = set(topic_tokens(topic_key))
    candidate_tkns = set(topic_tokens(candidate_key))
    if not topic_tkns:
        return 0.0
    overlap = len(topic_tkns & candidate_tkns) / max(len(topic_tkns), 1)
    substring_bonus = 0.2 if normalized_topic and (
        normalized_topic in normalized_candidate or normalized_candidate in normalized_topic
    ) else 0.0
    support_tkns = set(topic_tokens(title or ""))
    support_tkns.update(topic_tokens(" ".join(tags or [])))
    support_tkns.update(topic_tokens(" ".join(extras or [])))
    support_overlap = len(topic_tkns & support_tkns) / max(len(topic_tkns), 1) if support_tkns else 0.0
    support_bonus = 0.15 if topic_tkns & support_tkns else 0.0
    if support_overlap >= 0.5:
        support_bonus += 0.25
    return clamp_score(overlap + substring_bonus + support_bonus)


def classify_knowledge_level(*, topic: str, assistant_message: str, learner_message: str) -> str:
    lowered = f"{topic} {assistant_message} {learner_message}".casefold()
    if any(token in lowered for token in ["definition", "basics", "intro", "introduction", "foundation"]):
        return "foundation"
    if any(token in lowered for token in ["advanced", "proof", "theorem", "deep"]):
        return "advanced"
    if any(token in lowered for token in ["apply", "application", "practice", "exercise"]):
        return "application"
    return "core"


def classify_knowledge_horizon(
    *,
    knowledge_level: str,
    struggle_note: str | None,
    progress_note: str | None,
) -> str:
    if knowledge_level == "foundation":
        return "early"
    if struggle_note is not None and progress_note is None:
        return "early"
    if knowledge_level == "application":
        return "long"
    return "mid"


def classify_behavior_category(
    *,
    mode: str | None,
    struggle_note: str | None,
    progress_note: str | None,
) -> str:
    return MemoryNormalizer.classify_behavior_category(
        mode=mode,
        struggle_note=struggle_note,
        progress_note=progress_note,
    )


def classify_behavior_level(
    *,
    mode: str | None,
    struggle_note: str | None,
    progress_note: str | None,
) -> str:
    if mode == "hint" or struggle_note is not None:
        return "recurrent"
    if progress_note is not None:
        return "surface"
    return "persistent"


def classify_behavior_horizon(
    *,
    behavior_level: str,
    struggle_note: str | None,
    progress_note: str | None,
) -> str:
    if behavior_level in {"persistent", "critical"}:
        return "long"
    if struggle_note is not None or progress_note is not None:
        return "mid"
    return "early"


def build_memory_details(*, learner_message: str, assistant_message: str) -> str:
    return f"Learner: {learner_message[:280].strip()} | Assistant: {assistant_message[:280].strip()}"


def build_knowledge_summary(
    *,
    topic: str,
    concept_focus: str | None,
    progress_note: str | None,
    struggle_note: str | None,
    assistant_message: str,
) -> str:
    parts = [f"Knowledge: {topic}"]
    if concept_focus is not None:
        parts.append(f"Concept: {concept_focus}")
    if progress_note is not None:
        parts.append(f"Progress: {progress_note}")
    if struggle_note is not None:
        parts.append(f"Struggle: {struggle_note}")
    if assistant_message.strip():
        parts.append(f"Teaching: {assistant_message[:180].strip()}")
    return " | ".join(parts)


def build_behavior_title(*, behavior_category: str, subject: str | None, session_title: str | None) -> str:
    topic = subject or session_title or "learning session"
    return f"{behavior_category.replace('_', ' ').title()} for {topic}"


def build_behavior_summary(
    *,
    behavior_category: str,
    learner_message: str,
    progress_note: str | None,
    struggle_note: str | None,
) -> str:
    parts = [f"Behavior: {behavior_category}"]
    if struggle_note is not None:
        parts.append(f"Struggle: {struggle_note}")
    if progress_note is not None:
        parts.append(f"Progress: {progress_note}")
    parts.append(f"Learner: {learner_message[:180].strip()}")
    return " | ".join(parts)


def build_knowledge_tags(
    *,
    mode: str | None,
    subject: str | None,
    concept_focus: str | None,
    struggle_note: str | None,
) -> list[str]:
    tags = ["knowledge", mode or "chat"]
    if subject is not None:
        tags.append(subject.casefold())
    if concept_focus is not None:
        tags.append(concept_focus.casefold())
    if struggle_note is not None:
        tags.append("struggle")
    return tags


def build_behavior_tags(
    *,
    mode: str | None,
    subject: str | None,
    struggle_note: str | None,
    progress_note: str | None,
) -> list[str]:
    tags = ["behavior", mode or "chat"]
    if subject is not None:
        tags.append(subject.casefold())
    if struggle_note is not None:
        tags.append("struggle")
    if progress_note is not None:
        tags.append("progress")
    return tags


def build_behavior_intervention_effect(
    *,
    mode: str | None,
    progress_note: str | None,
    struggle_note: str | None,
) -> str | None:
    if mode == "hint":
        return "Learner responded to guided hinting."
    if progress_note is not None and struggle_note is not None:
        return "Learner advanced after a supported explanation."
    if progress_note is not None:
        return "Learner advanced with direct explanation."
    if struggle_note is not None:
        return "Learner showed a repeated struggle pattern."
    return None


def build_knowledge_memory(
    *,
    learner_profile_id: str,
    learner_goal_id: str | None,
    learner_message: str,
    assistant_message: str,
    source_message_id: str | None,
    mode: str | None,
    subject: str | None,
    session_title: str | None,
    source_event_ids: list[str] | None = None,
    provenance_type: str | None = None,
    provenance_source_id: str | None = None,
) -> KnowledgeMemory | None:
    topic = subject or session_title or infer_concept_focus(learner_message)
    if topic is None:
        return None
    concept_focus = infer_concept_focus(learner_message) or topic
    struggle_note = infer_struggle_note(learner_message)
    progress_note = infer_progress_note(assistant_message=assistant_message, mode=mode)
    knowledge_level = classify_knowledge_level(
        topic=topic,
        assistant_message=assistant_message,
        learner_message=learner_message,
    )
    time_horizon = classify_knowledge_horizon(
        knowledge_level=knowledge_level,
        struggle_note=struggle_note,
        progress_note=progress_note,
    )
    semantic_category = MemoryNormalizer.classify_semantic_category(
        memory_type="knowledge",
        knowledge_level=knowledge_level,
    )
    importance_score = clamp_score(
        0.45
        + (0.2 if subject is not None else 0.0)
        + (0.15 if progress_note is not None else 0.0)
        + (0.15 if concept_focus and concept_focus.casefold() != topic.casefold() else 0.0)
    )
    confidence_score = clamp_score(
        0.4
        + (0.2 if assistant_message.strip() else 0.0)
        + (0.2 if source_message_id is not None else 0.0)
        + (0.1 if progress_note is not None else 0.0)
        + (0.1 if struggle_note is not None else 0.0)
    )
    summary = build_knowledge_summary(
        topic=topic,
        concept_focus=concept_focus,
        progress_note=progress_note,
        struggle_note=struggle_note,
        assistant_message=assistant_message,
    )
    prerequisite_keys = [subject.casefold()] if subject is not None and subject.casefold() != topic.casefold() else []
    memory = KnowledgeMemory.build(
        learner_profile_id=learner_profile_id,
        learner_goal_id=learner_goal_id,
        knowledge_key=normalize_key(topic),
        title=topic,
        summary=summary,
        details=build_memory_details(learner_message=learner_message, assistant_message=assistant_message),
        knowledge_level=knowledge_level,
        time_horizon=time_horizon,
        importance_score=importance_score,
        confidence_score=confidence_score,
        freshness_score=1.0,
        prerequisite_keys=prerequisite_keys,
        source_event_ids=list(source_event_ids if source_event_ids is not None else ([source_message_id] if source_message_id is not None else [])),
        source_memory_ids=[],
        tags=build_knowledge_tags(
            mode=mode,
            subject=subject,
            concept_focus=concept_focus,
            struggle_note=struggle_note,
        ),
    )
    memory_values = {
        **memory.__dict__,
        "semantic_category": semantic_category,
    }
    if provenance_type is None and provenance_source_id is None:
        return KnowledgeMemory(**memory_values)
    return KnowledgeMemory(
        **{
            **memory_values,
            "provenance_type": provenance_type or memory.provenance_type,
            "provenance_source_id": provenance_source_id,
        }
    )


def build_behavior_memory(
    *,
    learner_profile_id: str,
    learner_goal_id: str | None,
    learner_message: str,
    assistant_message: str,
    source_message_id: str | None,
    mode: str | None,
    subject: str | None,
    session_title: str | None,
    source_event_ids: list[str] | None = None,
    provenance_type: str | None = None,
    provenance_source_id: str | None = None,
) -> BehaviorMemory | None:
    struggle_note = infer_struggle_note(learner_message)
    progress_note = infer_progress_note(assistant_message=assistant_message, mode=mode)
    if struggle_note is None and progress_note is None and mode != "hint":
        return None
    behavior_category = classify_behavior_category(mode=mode, struggle_note=struggle_note, progress_note=progress_note)
    semantic_category = MemoryNormalizer.classify_semantic_category(
        memory_type="behavior",
        behavior_category=behavior_category,
    )
    behavior_level = classify_behavior_level(mode=mode, struggle_note=struggle_note, progress_note=progress_note)
    time_horizon = classify_behavior_horizon(
        behavior_level=behavior_level,
        struggle_note=struggle_note,
        progress_note=progress_note,
    )
    importance_score = clamp_score(
        0.35
        + (0.25 if struggle_note is not None else 0.0)
        + (0.2 if mode == "hint" else 0.0)
        + (0.1 if progress_note is not None else 0.0)
        + (0.05 if subject is not None else 0.0)
    )
    confidence_score = clamp_score(
        0.35
        + (0.2 if source_message_id is not None else 0.0)
        + (0.15 if struggle_note is not None else 0.0)
        + (0.15 if progress_note is not None else 0.0)
        + (0.1 if assistant_message.strip() else 0.0)
    )
    memory = BehaviorMemory.build(
        learner_profile_id=learner_profile_id,
        learner_goal_id=learner_goal_id,
        behavior_key=normalize_key(f"{behavior_category}:{subject or session_title or 'session'}"),
        behavior_category=behavior_category,
        title=build_behavior_title(
            behavior_category=behavior_category,
            subject=subject,
            session_title=session_title,
        ),
        summary=build_behavior_summary(
            behavior_category=behavior_category,
            learner_message=learner_message,
            progress_note=progress_note,
            struggle_note=struggle_note,
        ),
        details=build_memory_details(learner_message=learner_message, assistant_message=assistant_message),
        behavior_level=behavior_level,
        time_horizon=time_horizon,
        importance_score=importance_score,
        confidence_score=confidence_score,
        freshness_score=1.0,
        source_event_ids=list(source_event_ids if source_event_ids is not None else ([source_message_id] if source_message_id is not None else [])),
        source_memory_ids=[],
        tags=build_behavior_tags(
            mode=mode,
            subject=subject,
            struggle_note=struggle_note,
            progress_note=progress_note,
        ),
        intervention_effect=build_behavior_intervention_effect(
            mode=mode,
            progress_note=progress_note,
            struggle_note=struggle_note,
        ),
    )
    memory_values = {
        **memory.__dict__,
        "semantic_category": semantic_category,
    }
    if provenance_type is None and provenance_source_id is None:
        return BehaviorMemory(**memory_values)
    return BehaviorMemory(
        **{
            **memory_values,
            "provenance_type": provenance_type or memory.provenance_type,
            "provenance_source_id": provenance_source_id,
        }
    )


class CandidateBuilderService:
    """Builds long-term memory candidates from learning interactions."""

    def build_knowledge_memory_candidate(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None,
        learner_message: str,
        assistant_message: str,
        source_message_id: str | None,
        mode: str | None,
        subject: str | None,
        session_title: str | None,
        source_event_ids: list[str] | None = None,
        provenance_type: str | None = None,
        provenance_source_id: str | None = None,
    ) -> KnowledgeMemory | None:
        return build_knowledge_memory(
            learner_profile_id=learner_profile_id,
            learner_goal_id=learner_goal_id,
            learner_message=learner_message,
            assistant_message=assistant_message,
            source_message_id=source_message_id,
            mode=mode,
            subject=subject,
            session_title=session_title,
            source_event_ids=source_event_ids,
            provenance_type=provenance_type,
            provenance_source_id=provenance_source_id,
        )

    def build_behavior_memory_candidate(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None,
        learner_message: str,
        assistant_message: str,
        source_message_id: str | None,
        mode: str | None,
        subject: str | None,
        session_title: str | None,
        source_event_ids: list[str] | None = None,
        provenance_type: str | None = None,
        provenance_source_id: str | None = None,
    ) -> BehaviorMemory | None:
        return build_behavior_memory(
            learner_profile_id=learner_profile_id,
            learner_goal_id=learner_goal_id,
            learner_message=learner_message,
            assistant_message=assistant_message,
            source_message_id=source_message_id,
            mode=mode,
            subject=subject,
            session_title=session_title,
            source_event_ids=source_event_ids,
            provenance_type=provenance_type,
            provenance_source_id=provenance_source_id,
        )
