from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from math import ceil
from time import perf_counter

from agent_core.application.services.audit import AuditService
from agent_core.application.services.goal_skill_binding_resolver import ActiveGoalSkillBinding, GoalSkillBindingResolver
from agent_core.application.services.memory import MemoryInterpretationResult
from agent_core.application.services.reflection_proposal_rollout_resolver import ReflectionProposalRolloutResolver
from agent_core.application.services.skills import SkillUsageService
from agent_core.application.services.strategy_cards import StrategyCardService
from agent_core.domain.entities.goal import LearnerGoal
from agent_core.domain.entities.planning import DailyTask, PlanStage, StudyPlan
from agent_core.domain.entities.skill import SkillResolution
from agent_core.domain.errors import ValidationError
from agent_core.infrastructure.llm.types import LLMProvider, StudyPlanDraft, StudyPlanStageDraft, StudyPlanTaskDraft
from agent_core.infrastructure.observability.metrics import observe_llm_operation, observe_plan_generation_fallback


@dataclass(frozen=True)
class MaterializedPlan:
    study_plan: StudyPlan
    stages: list[PlanStage]
    tasks: list[DailyTask]
    llm_draft: StudyPlanDraft


class PlannerService:
    def __init__(
        self,
        *,
        llm_provider: LLMProvider,
        audit_service: AuditService,
        strategy_card_service: StrategyCardService | None = None,
        rollout_resolver: ReflectionProposalRolloutResolver | None = None,
        goal_skill_binding_resolver: GoalSkillBindingResolver | None = None,
        skill_usage_service: SkillUsageService | None = None,
        planning_window_days: int = 14,
    ) -> None:
        self._llm_provider = llm_provider
        self._audit_service = audit_service
        self._strategy_card_service = strategy_card_service
        self._rollout_resolver = rollout_resolver
        self._goal_skill_binding_resolver = goal_skill_binding_resolver
        self._skill_usage_service = skill_usage_service
        self._planning_window_days = planning_window_days

    async def build_plan(
        self,
        *,
        goal: LearnerGoal,
        version: int,
        trigger_source: str,
        supersedes_plan_id: str | None,
        rollout_overlay: dict[str, object] | None = None,
        rollout_context: dict[str, object] | None = None,
        memory_interpretation: MemoryInterpretationResult | None = None,
    ) -> MaterializedPlan:
        skill_resolution = await self._resolve_plan_skill_for_runtime(goal)
        strategy_card = (
            await self._strategy_card_service.get_active(goal.id)
            if self._strategy_card_service is not None
            else None
        )
        strategy_summary = StrategyCardService.build_strategy_summary(strategy_card)
        if rollout_overlay is None and self._rollout_resolver is not None:
            active_overlay = await self._rollout_resolver.get_active_overlay(
                learner_goal_id=goal.id,
                surface="plan_generation",
                include_staged=False,
            )
            if active_overlay is not None:
                rollout_overlay = dict(active_overlay.payload)
                rollout_context = {
                    "rollout_id": active_overlay.rollout_id,
                    "proposal_id": active_overlay.proposal_id,
                    "surface": active_overlay.surface,
                    "status": active_overlay.status,
                }
        skill_directives: list[str] | None = None
        active_skill: ActiveGoalSkillBinding | None = None
        if self._goal_skill_binding_resolver is not None:
            active_skill = await self._goal_skill_binding_resolver.get_active_binding(
                learner_goal_id=goal.id,
                surface="plan_generation",
                topic_key=goal.subject,
                include_staged=False,
            )
            if active_skill is not None:
                skill_directives = list(active_skill.runtime_directives.get("skill_directives") or [])
        strategy_summary = self._merge_rollout_overlay(
            strategy_summary=strategy_summary,
            rollout_overlay=rollout_overlay,
        )
        strategy_summary = self._merge_memory_interpretation(
            strategy_summary=strategy_summary,
            memory_interpretation=memory_interpretation,
        )
        stage_blueprint = self._build_stage_blueprint(goal, strategy_summary=strategy_summary)
        task_blueprint = self._build_task_blueprint(goal=goal, stage_blueprint=stage_blueprint, strategy_summary=strategy_summary)
        llm_started_at = perf_counter()
        provider_name = getattr(self._llm_provider, "provider_name", "unknown")
        provider_error_code = None
        try:
            llm_draft = await self._llm_provider.generate_study_plan_draft(
                subject=goal.subject,
                target_outcome=goal.target_outcome,
                baseline_note=goal.baseline_note,
                weekly_study_minutes=goal.weekly_study_minutes,
                stage_blueprint=stage_blueprint,
                task_blueprint=task_blueprint,
                strategy_summary=strategy_summary,
                skill_directives=skill_directives,
            )
            observe_llm_operation(
                operation="study_plan",
                provider=llm_draft.provider,
                status="completed",
                latency_ms=llm_draft.latency_ms,
            )
        except Exception as exc:
            provider_error_code = type(exc).__name__
            observe_llm_operation(
                operation="study_plan",
                provider=provider_name,
                status="failed",
                latency_ms=int((perf_counter() - llm_started_at) * 1000),
            )
            await self._audit_service.record_durable(
                event_type="llm.study_plan.failed",
                resource_type="learner_goal",
                resource_id=goal.id,
                actor="system",
                event_data={
                    "learner_goal_id": goal.id,
                    "provider": provider_name,
                    "model": getattr(self._llm_provider, "model_name", None),
                    "error": str(exc),
                },
            )
            llm_draft = self._build_fallback_draft(
                goal=goal,
                stage_blueprint=stage_blueprint,
                task_blueprint=task_blueprint,
            )
        if llm_draft.fallback_used:
            observe_plan_generation_fallback()

        materialized_until = min(goal.deadline_date, date.today() + timedelta(days=self._planning_window_days - 1))
        study_plan = StudyPlan.build(
            learner_goal_id=goal.id,
            version=version,
            trigger_source=trigger_source,
            plan_summary=llm_draft.plan_summary,
            blueprint_payload={
                "window_days": self._planning_window_days,
                "stages": [
                    {
                        "position": index + 1,
                        "title": stage.title,
                        "objective": stage.objective,
                        "focus_topics": stage.focus_topics,
                        "start_date": stage_blueprint[index]["start_date"].isoformat(),
                        "end_date": stage_blueprint[index]["end_date"].isoformat(),
                    }
                    for index, stage in enumerate(llm_draft.stages)
                ],
                "tasks": [
                    {
                        "stage_position": task.stage_position,
                        "scheduled_for": task.scheduled_for.isoformat(),
                        "due_on": task.due_on.isoformat(),
                        "task_type": task.task_type,
                        "execution_mode": task.execution_mode,
                        "title": task.title,
                        "instructions": task.instructions,
                        "topic_focus": task.topic_focus,
                        "difficulty": task.difficulty,
                        "question_count": task.question_count,
                        "estimated_minutes": task.estimated_minutes,
                    }
                    for task in llm_draft.tasks
                ],
                "provider": llm_draft.provider,
                "model": llm_draft.model,
                "strategy_summary": strategy_summary,
                "memory_interpretation": self._serialize_memory_interpretation(memory_interpretation),
                "rollout_context": rollout_context,
                "retry_count": llm_draft.retry_count,
                "response_shape_valid": llm_draft.response_shape_valid,
                "fallback_used": llm_draft.fallback_used,
            },
            materialized_until_date=materialized_until,
            supersedes_plan_id=supersedes_plan_id,
        )
        stages = [
            PlanStage.build(
                study_plan_id=study_plan.id,
                position=index + 1,
                title=stage.title,
                objective=stage.objective,
                focus_topics=stage.focus_topics,
                start_date=stage_blueprint[index]["start_date"],
                end_date=stage_blueprint[index]["end_date"],
            )
            for index, stage in enumerate(llm_draft.stages)
        ]
        stage_ids_by_position = {stage.position: stage.id for stage in stages}
        tasks = [
            DailyTask.build(
                learner_goal_id=goal.id,
                study_plan_id=study_plan.id,
                plan_stage_id=stage_ids_by_position.get(task.stage_position),
                task_origin="planner",
                task_type=task.task_type,
                execution_mode=task.execution_mode,
                title=task.title,
                instructions=task.instructions,
                topic_focus=task.topic_focus,
                difficulty=task.difficulty,
                question_count=task.question_count,
                estimated_minutes=task.estimated_minutes,
                scheduled_for=task.scheduled_for,
                due_on=task.due_on,
            )
            for task in llm_draft.tasks
            if task.scheduled_for <= materialized_until
        ]
        await self._record_plan_skill_usage(
            goal=goal,
            llm_draft=llm_draft,
            error_code=provider_error_code,
            trigger_source=trigger_source,
            resolution=skill_resolution,
            skill_binding=active_skill,
        )
        return MaterializedPlan(
            study_plan=study_plan,
            stages=stages,
            tasks=tasks,
            llm_draft=llm_draft,
        )

    async def _resolve_plan_skill_for_runtime(self, goal: LearnerGoal) -> SkillResolution | None:
        if self._skill_usage_service is None:
            return None
        return await self._skill_usage_service.resolve_for_runtime(
            skill_name="plan_study_path",
            surface="plan_generation",
            resource_id=goal.id,
        )

    async def _record_plan_skill_usage(
        self,
        *,
        goal: LearnerGoal,
        llm_draft: StudyPlanDraft,
        error_code: str | None,
        trigger_source: str,
        resolution: SkillResolution | None,
        skill_binding: ActiveGoalSkillBinding | None,
    ) -> None:
        if self._skill_usage_service is None:
            return
        await self._skill_usage_service.record_usage(
            skill_name="plan_study_path",
            surface="plan_generation",
            outcome_status="completed",
            learner_profile_id=goal.learner_profile_id,
            learner_goal_id=goal.id,
            topic_key=goal.subject,
            trigger_source=trigger_source,
            latency_ms=llm_draft.latency_ms,
            input_summary=goal.target_outcome,
            output_summary=llm_draft.plan_summary,
            error_code=error_code,
            resolution=resolution,
            metadata=(
                skill_binding.with_usage_metadata(
                    {
                        "fallback_used": llm_draft.fallback_used,
                        "response_shape_valid": llm_draft.response_shape_valid,
                        "retry_count": llm_draft.retry_count,
                        "provider": llm_draft.provider,
                        "model": llm_draft.model,
                    },
                    skill_name="plan_study_path",
                )
                if skill_binding is not None
                else {
                    "fallback_used": llm_draft.fallback_used,
                    "response_shape_valid": llm_draft.response_shape_valid,
                    "retry_count": llm_draft.retry_count,
                    "provider": llm_draft.provider,
                    "model": llm_draft.model,
                }
            ),
        )

    async def extend_plan_window(
        self,
        *,
        goal: LearnerGoal,
        active_plan: StudyPlan,
        existing_tasks: list[DailyTask],
        stage_id_by_position: dict[int, str],
    ) -> tuple[list[DailyTask], date | None]:
        target_until = min(goal.deadline_date, date.today() + timedelta(days=self._planning_window_days - 1))
        if active_plan.materialized_until_date is not None and active_plan.materialized_until_date >= target_until:
            return [], active_plan.materialized_until_date

        payload_tasks = active_plan.blueprint_payload.get("tasks", [])
        existing_dates = {(task.scheduled_for, task.task_type, task.topic_focus) for task in existing_tasks}
        new_tasks: list[DailyTask] = []
        for item in payload_tasks:
            scheduled_for = self._parse_date(item["scheduled_for"])
            if scheduled_for > target_until:
                continue
            task_key = (scheduled_for, str(item["task_type"]), str(item["topic_focus"]))
            if task_key in existing_dates:
                continue
            new_tasks.append(
                DailyTask.build(
                    learner_goal_id=goal.id,
                    study_plan_id=active_plan.id,
                    plan_stage_id=stage_id_by_position.get(int(item["stage_position"])),
                    task_origin="planner",
                    task_type=str(item["task_type"]),
                    execution_mode=str(item["execution_mode"]),
                    title=str(item["title"]),
                    instructions=str(item["instructions"]),
                    topic_focus=str(item["topic_focus"]),
                    difficulty=str(item["difficulty"]) if item.get("difficulty") is not None else None,
                    question_count=int(item["question_count"]) if item.get("question_count") is not None else None,
                    estimated_minutes=int(item["estimated_minutes"]),
                    scheduled_for=scheduled_for,
                    due_on=self._parse_date(item["due_on"]),
                )
            )
        return new_tasks, target_until

    def _build_stage_blueprint(self, goal: LearnerGoal, *, strategy_summary: dict[str, object] | None) -> list[dict[str, object]]:
        total_days = max((goal.deadline_date - date.today()).days + 1, 7)
        total_weeks = max(ceil(total_days / 7), 1)
        if strategy_summary is not None and strategy_summary.get("primary_instruction_mode") == "guided":
            if total_weeks <= 3:
                stage_specs = [
                    ("Foundation", 0.5),
                    ("Guided Practice", 0.5),
                ]
            else:
                stage_specs = [
                    ("Foundation", 0.4),
                    ("Guided Practice", 0.4),
                    ("Consolidation", 0.2),
                ]
        elif total_weeks <= 3:
            stage_specs = [
                ("Foundation", 0.4),
                ("Consolidation", 0.6),
            ]
        else:
            stage_specs = [
                ("Foundation", 0.3),
                ("Guided Practice", 0.45),
                ("Consolidation", 0.25),
            ]
        cursor = date.today()
        stages: list[dict[str, object]] = []
        days_remaining = total_days
        for index, (title, ratio) in enumerate(stage_specs):
            if index == len(stage_specs) - 1:
                stage_days = days_remaining
            else:
                stage_days = max(2, round(total_days * ratio))
                stage_days = min(stage_days, days_remaining - (len(stage_specs) - index - 1) * 2)
            start_date = cursor
            end_date = start_date + timedelta(days=stage_days - 1)
            stages.append(
                {
                    "position": index + 1,
                    "title": title,
                    "focus_topics": self._focus_topics(goal.subject, index),
                    "start_date": start_date,
                    "end_date": end_date,
                }
            )
            cursor = end_date + timedelta(days=1)
            days_remaining -= stage_days
        return stages

    def _build_task_blueprint(
        self,
        *,
        goal: LearnerGoal,
        stage_blueprint: list[dict[str, object]],
        strategy_summary: dict[str, object] | None,
    ) -> list[dict[str, object]]:
        study_days_per_week = self._study_days_per_week(goal.weekly_study_minutes)
        if strategy_summary is not None:
            if strategy_summary.get("review_bias") == "intensive":
                study_days_per_week = min(study_days_per_week + 1, 5)
            if strategy_summary.get("difficulty_bias") == "supportive":
                study_days_per_week = max(study_days_per_week, 3)
        estimated_minutes = max(20, goal.weekly_study_minutes // study_days_per_week)
        cadence = max(1, round(7 / study_days_per_week))
        all_tasks: list[dict[str, object]] = []
        for stage in stage_blueprint:
            start_date = stage["start_date"]
            end_date = stage["end_date"]
            focus_topics = list(stage["focus_topics"])
            scheduled_dates = self._pick_task_dates(
                start_date=start_date,
                end_date=end_date,
                cadence_days=cadence,
            )
            for index, scheduled_for in enumerate(scheduled_dates):
                task_type = "lesson" if index % 2 == 0 else "practice"
                if strategy_summary is not None and strategy_summary.get("difficulty_bias") == "supportive":
                    task_type = "lesson" if index % 3 != 2 else "practice"
                execution_mode = "chat" if task_type == "lesson" else "quiz"
                topic_focus = focus_topics[min(index % len(focus_topics), len(focus_topics) - 1)]
                difficulty = "medium" if task_type != "lesson" else None
                if strategy_summary is not None and task_type != "lesson":
                    difficulty = "easy" if strategy_summary.get("difficulty_bias") == "supportive" else "medium"
                all_tasks.append(
                    {
                        "stage_position": stage["position"],
                        "scheduled_for": scheduled_for,
                        "due_on": scheduled_for,
                        "task_type": task_type,
                        "execution_mode": execution_mode,
                        "topic_focus": topic_focus,
                        "difficulty": difficulty,
                        "question_count": 3 if task_type != "lesson" else None,
                        "estimated_minutes": estimated_minutes,
                    }
                )
        return all_tasks

    def _build_fallback_draft(
        self,
        *,
        goal: LearnerGoal,
        stage_blueprint: list[dict[str, object]],
        task_blueprint: list[dict[str, object]],
    ) -> StudyPlanDraft:
        return StudyPlanDraft(
            plan_summary=f"Fallback study plan for {goal.subject} toward {goal.target_outcome}.",
            stages=[
                self._fallback_stage(item["title"], item["focus_topics"])
                for item in stage_blueprint
            ],
            tasks=[
                self._fallback_task(item)
                for item in task_blueprint
            ],
            provider=getattr(self._llm_provider, "provider_name", "fallback"),
            model=getattr(self._llm_provider, "model_name", "fallback"),
            latency_ms=0,
            retry_count=0,
            response_shape_valid=False,
            fallback_used=True,
        )

    @staticmethod
    def _merge_rollout_overlay(
        *,
        strategy_summary: dict[str, object] | None,
        rollout_overlay: dict[str, object] | None,
    ) -> dict[str, object] | None:
        if strategy_summary is None and rollout_overlay is None:
            return None
        merged = dict(strategy_summary or {})
        if rollout_overlay is not None:
            merged.update({key: value for key, value in rollout_overlay.items() if value is not None})
        return merged

    @staticmethod
    def _merge_memory_interpretation(
        *,
        strategy_summary: dict[str, object] | None,
        memory_interpretation: MemoryInterpretationResult | None,
    ) -> dict[str, object] | None:
        if memory_interpretation is None:
            return strategy_summary
        merged = {
            "primary_instruction_mode": "mixed",
            "difficulty_bias": "standard",
            "review_bias": "balanced",
            "replan_bias": "conservative",
            "assessment_bias": "standard",
            **dict(strategy_summary or {}),
        }
        if memory_interpretation.contested_items:
            merged["memory_constraint"] = "verify_contested_memory_before_planning"
            merged["review_bias"] = "intensive"
        if any(item.semantic_category == "misconception" for item in memory_interpretation.facts):
            merged["difficulty_bias"] = "supportive"
        if memory_interpretation.recommended_constraints:
            merged["memory_constraints"] = list(memory_interpretation.recommended_constraints)
        return merged

    @staticmethod
    def _serialize_memory_interpretation(
        memory_interpretation: MemoryInterpretationResult | None,
    ) -> dict[str, object] | None:
        if memory_interpretation is None:
            return None
        return {
            "facts": [item.__dict__ for item in memory_interpretation.facts],
            "behavior_patterns": [item.__dict__ for item in memory_interpretation.behavior_patterns],
            "contested_items": [item.__dict__ for item in memory_interpretation.contested_items],
            "recommended_constraints": memory_interpretation.recommended_constraints,
            "conflict_count": memory_interpretation.conflict_count,
        }

    @staticmethod
    def _fallback_stage(title: str, focus_topics: list[str]):
        return StudyPlanStageDraft(
            title=title,
            objective=f"Strengthen understanding through {title.lower()} work.",
            focus_topics=focus_topics,
        )

    @staticmethod
    def _fallback_task(item: dict[str, object]):
        return StudyPlanTaskDraft(
            stage_position=int(item["stage_position"]),
            scheduled_for=item["scheduled_for"],
            due_on=item["due_on"],
            task_type=str(item["task_type"]),
            execution_mode=str(item["execution_mode"]),
            title=f"{str(item['topic_focus'])} {str(item['task_type']).title()}",
            instructions=f"Focus on {item['topic_focus']} using the current study objective.",
            topic_focus=str(item["topic_focus"]),
            difficulty=str(item["difficulty"]) if item.get("difficulty") is not None else None,
            question_count=int(item["question_count"]) if item.get("question_count") is not None else None,
            estimated_minutes=int(item["estimated_minutes"]),
        )

    @staticmethod
    def _study_days_per_week(weekly_study_minutes: int) -> int:
        if weekly_study_minutes < 150:
            return 2
        if weekly_study_minutes < 300:
            return 3
        if weekly_study_minutes < 450:
            return 4
        return 5

    @staticmethod
    def _pick_task_dates(*, start_date: date, end_date: date, cadence_days: int) -> list[date]:
        dates: list[date] = []
        cursor = start_date
        while cursor <= end_date:
            dates.append(cursor)
            cursor += timedelta(days=cadence_days)
        if not dates:
            dates.append(start_date)
        return dates

    @staticmethod
    def _focus_topics(subject: str, stage_index: int) -> list[str]:
        if stage_index == 0:
            return [f"{subject} foundations", f"{subject} core ideas"]
        if stage_index == 1:
            return [f"{subject} worked examples", f"{subject} problem solving"]
        return [f"{subject} consolidation", f"{subject} review"]

    @staticmethod
    def _parse_date(value: object) -> date:
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            return date.fromisoformat(value)
        raise ValidationError("Invalid date value inside study plan blueprint.")
