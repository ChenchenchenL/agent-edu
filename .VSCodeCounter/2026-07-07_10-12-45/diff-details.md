# Diff Details

Date : 2026-07-07 10:12:45

Directory /home/cl/agent-edu

Total : 160 files,  18845 codes, 858 comments, 2534 blanks, all 22237 lines

[Summary](results.md) / [Details](details.md) / [Diff Summary](diff.md) / Diff Details

## Files
| filename | language | code | comment | blank | total |
| :--- | :--- | ---: | ---: | ---: | ---: |
| [Makefile](/Makefile) | Makefile | 26 | 23 | 6 | 55 |
| [alembic/versions/0025\_skill\_packages\_and\_installations.py](/alembic/versions/0025_skill_packages_and_installations.py) | Python | 56 | 6 | 9 | 71 |
| [alembic/versions/0026\_quiz\_answer\_attempts.py](/alembic/versions/0026_quiz_answer_attempts.py) | Python | 143 | 6 | 9 | 158 |
| [apps/worker/main.py](/apps/worker/main.py) | Python | 32 | 6 | 4 | 42 |
| [docs/DOCKER\_VALIDATION.md](/docs/DOCKER_VALIDATION.md) | Markdown | 5 | 0 | 1 | 6 |
| [docs/MVP\_VALIDATION\_BASELINE.md](/docs/MVP_VALIDATION_BASELINE.md) | Markdown | 101 | 0 | 35 | 136 |
| [docs/QUIZ\_ATTEMPT\_OBSERVABILITY\_CONTRACT.md](/docs/QUIZ_ATTEMPT_OBSERVABILITY_CONTRACT.md) | Markdown | 154 | 0 | 59 | 213 |
| [packages/agent\_core/src/agent\_core/api/app.py](/packages/agent_core/src/agent_core/api/app.py) | Python | 2 | 0 | 0 | 2 |
| [packages/agent\_core/src/agent\_core/api/dependencies.py](/packages/agent_core/src/agent_core/api/dependencies.py) | Python | 120 | 9 | 11 | 140 |
| [packages/agent\_core/src/agent\_core/api/error\_handlers.py](/packages/agent_core/src/agent_core/api/error_handlers.py) | Python | 1 | 3 | 0 | 4 |
| [packages/agent\_core/src/agent\_core/api/rate\_limit.py](/packages/agent_core/src/agent_core/api/rate_limit.py) | Python | 14 | 11 | 2 | 27 |
| [packages/agent\_core/src/agent\_core/api/routes/health.py](/packages/agent_core/src/agent_core/api/routes/health.py) | Python | 13 | 1 | 0 | 14 |
| [packages/agent\_core/src/agent\_core/api/routes/quiz.py](/packages/agent_core/src/agent_core/api/routes/quiz.py) | Python | 138 | 6 | 31 | 175 |
| [packages/agent\_core/src/agent\_core/api/routes/reflection.py](/packages/agent_core/src/agent_core/api/routes/reflection.py) | Python | 23 | 0 | 2 | 25 |
| [packages/agent\_core/src/agent\_core/api/routes/sessions.py](/packages/agent_core/src/agent_core/api/routes/sessions.py) | Python | 37 | 0 | 2 | 39 |
| [packages/agent\_core/src/agent\_core/api/routes/skill\_packages.py](/packages/agent_core/src/agent_core/api/routes/skill_packages.py) | Python | 263 | 0 | 32 | 295 |
| [packages/agent\_core/src/agent\_core/api/routes/skills.py](/packages/agent_core/src/agent_core/api/routes/skills.py) | Python | 144 | 0 | 10 | 154 |
| [packages/agent\_core/src/agent\_core/application/services/adaptive\_quiz\_policy.py](/packages/agent_core/src/agent_core/application/services/adaptive_quiz_policy.py) | Python | 195 | 38 | 32 | 265 |
| [packages/agent\_core/src/agent\_core/application/services/audit.py](/packages/agent_core/src/agent_core/application/services/audit.py) | Python | 6 | 0 | 1 | 7 |
| [packages/agent\_core/src/agent\_core/application/services/chat.py](/packages/agent_core/src/agent_core/application/services/chat.py) | Python | 3 | 5 | 0 | 8 |
| [packages/agent\_core/src/agent\_core/application/services/dynamic\_runtime\_registry.py](/packages/agent_core/src/agent_core/application/services/dynamic_runtime_registry.py) | Python | 127 | 29 | 10 | 166 |
| [packages/agent\_core/src/agent\_core/application/services/learner\_memory/evidence.py](/packages/agent_core/src/agent_core/application/services/learner_memory/evidence.py) | Python | 43 | 0 | 1 | 44 |
| [packages/agent\_core/src/agent\_core/application/services/long\_term\_memory\_materialization.py](/packages/agent_core/src/agent_core/application/services/long_term_memory_materialization.py) | Python | 144 | 9 | 6 | 159 |
| [packages/agent\_core/src/agent\_core/application/services/long\_term\_memory\_materialization\_replay.py](/packages/agent_core/src/agent_core/application/services/long_term_memory_materialization_replay.py) | Python | 43 | 0 | 2 | 45 |
| [packages/agent\_core/src/agent\_core/application/services/memory.py](/packages/agent_core/src/agent_core/application/services/memory.py) | Python | 13 | 0 | 1 | 14 |
| [packages/agent\_core/src/agent\_core/application/services/memory\_normalization.py](/packages/agent_core/src/agent_core/application/services/memory_normalization.py) | Python | 6 | 0 | 0 | 6 |
| [packages/agent\_core/src/agent\_core/application/services/quiz.py](/packages/agent_core/src/agent_core/application/services/quiz.py) | Python | 91 | 1 | 9 | 101 |
| [packages/agent\_core/src/agent\_core/application/services/quiz\_attempt.py](/packages/agent_core/src/agent_core/application/services/quiz_attempt.py) | Python | 474 | 18 | 34 | 526 |
| [packages/agent\_core/src/agent\_core/application/services/quiz\_grading.py](/packages/agent_core/src/agent_core/application/services/quiz_grading.py) | Python | 260 | 20 | 28 | 308 |
| [packages/agent\_core/src/agent\_core/application/services/quiz\_observability.py](/packages/agent_core/src/agent_core/application/services/quiz_observability.py) | Python | 219 | 40 | 30 | 289 |
| [packages/agent\_core/src/agent\_core/application/services/reflection.py](/packages/agent_core/src/agent_core/application/services/reflection.py) | Python | 371 | 9 | 32 | 412 |
| [packages/agent\_core/src/agent\_core/application/services/reflection\_evidence.py](/packages/agent_core/src/agent_core/application/services/reflection_evidence.py) | Python | 134 | 8 | 11 | 153 |
| [packages/agent\_core/src/agent\_core/application/services/reflection\_evidence\_contracts.py](/packages/agent_core/src/agent_core/application/services/reflection_evidence_contracts.py) | Python | 104 | 14 | 21 | 139 |
| [packages/agent\_core/src/agent\_core/application/services/reflection\_governance.py](/packages/agent_core/src/agent_core/application/services/reflection_governance.py) | Python | 105 | 1 | 9 | 115 |
| [packages/agent\_core/src/agent\_core/application/services/reflection\_proposal\_sandbox.py](/packages/agent_core/src/agent_core/application/services/reflection_proposal_sandbox.py) | Python | 32 | 3 | 2 | 37 |
| [packages/agent\_core/src/agent\_core/application/services/reflection\_proposals.py](/packages/agent_core/src/agent_core/application/services/reflection_proposals.py) | Python | 214 | 2 | 6 | 222 |
| [packages/agent\_core/src/agent\_core/application/services/reflection\_replay.py](/packages/agent_core/src/agent_core/application/services/reflection_replay.py) | Python | 40 | 0 | 8 | 48 |
| [packages/agent\_core/src/agent\_core/application/services/reflection\_sandbox\_admission.py](/packages/agent_core/src/agent_core/application/services/reflection_sandbox_admission.py) | Python | 2 | 0 | 0 | 2 |
| [packages/agent\_core/src/agent\_core/application/services/reflection\_sandbox\_policy.py](/packages/agent_core/src/agent_core/application/services/reflection_sandbox_policy.py) | Python | 10 | 0 | 1 | 11 |
| [packages/agent\_core/src/agent\_core/application/services/reflection\_skill\_evolution\_curator.py](/packages/agent_core/src/agent_core/application/services/reflection_skill_evolution_curator.py) | Python | 6 | 1 | 0 | 7 |
| [packages/agent\_core/src/agent\_core/application/services/reflection\_trigger\_policy.py](/packages/agent_core/src/agent_core/application/services/reflection_trigger_policy.py) | Python | 332 | 17 | 44 | 393 |
| [packages/agent\_core/src/agent\_core/application/services/runtime\_protection/alert\_bridge.py](/packages/agent_core/src/agent_core/application/services/runtime_protection/alert_bridge.py) | Python | 80 | 31 | 20 | 131 |
| [packages/agent\_core/src/agent\_core/application/services/skill/\_\_init\_\_.py](/packages/agent_core/src/agent_core/application/services/skill/__init__.py) | Python | 10 | 0 | 0 | 10 |
| [packages/agent\_core/src/agent\_core/application/services/skill/artifact\_timeline.py](/packages/agent_core/src/agent_core/application/services/skill/artifact_timeline.py) | Python | 126 | 0 | 16 | 142 |
| [packages/agent\_core/src/agent\_core/application/services/skill/candidates.py](/packages/agent_core/src/agent_core/application/services/skill/candidates.py) | Python | -2 | 5 | 0 | 3 |
| [packages/agent\_core/src/agent\_core/application/services/skill/capability.py](/packages/agent_core/src/agent_core/application/services/skill/capability.py) | Python | 1 | 6 | 0 | 7 |
| [packages/agent\_core/src/agent\_core/application/services/skill/curator\_execution\_policy.py](/packages/agent_core/src/agent_core/application/services/skill/curator_execution_policy.py) | Python | 4 | 0 | 0 | 4 |
| [packages/agent\_core/src/agent\_core/application/services/skill/curator\_executor.py](/packages/agent_core/src/agent_core/application/services/skill/curator_executor.py) | Python | 17 | 0 | 2 | 19 |
| [packages/agent\_core/src/agent\_core/application/services/skill/curator\_job.py](/packages/agent_core/src/agent_core/application/services/skill/curator_job.py) | Python | 228 | 15 | 20 | 263 |
| [packages/agent\_core/src/agent\_core/application/services/skill/outcome\_aggregator.py](/packages/agent_core/src/agent_core/application/services/skill/outcome_aggregator.py) | Python | 157 | 8 | 22 | 187 |
| [packages/agent\_core/src/agent\_core/application/services/skill/outcome\_feedback\_job.py](/packages/agent_core/src/agent_core/application/services/skill/outcome_feedback_job.py) | Python | 113 | 0 | 16 | 129 |
| [packages/agent\_core/src/agent\_core/application/services/skill/outcome\_trigger\_strategy.py](/packages/agent_core/src/agent_core/application/services/skill/outcome_trigger_strategy.py) | Python | 155 | 0 | 20 | 175 |
| [packages/agent\_core/src/agent\_core/application/services/skill/package\_import.py](/packages/agent_core/src/agent_core/application/services/skill/package_import.py) | Python | 116 | 0 | 12 | 128 |
| [packages/agent\_core/src/agent\_core/application/services/skill/package\_installation.py](/packages/agent_core/src/agent_core/application/services/skill/package_installation.py) | Python | 211 | 0 | 25 | 236 |
| [packages/agent\_core/src/agent\_core/application/services/skill/package\_manifest.py](/packages/agent_core/src/agent_core/application/services/skill/package_manifest.py) | Python | 102 | 0 | 15 | 117 |
| [packages/agent\_core/src/agent\_core/application/services/skill/package\_verification.py](/packages/agent_core/src/agent_core/application/services/skill/package_verification.py) | Python | 41 | 0 | 9 | 50 |
| [packages/agent\_core/src/agent\_core/application/services/skill/quality\_updater.py](/packages/agent_core/src/agent_core/application/services/skill/quality_updater.py) | Python | 93 | 0 | 18 | 111 |
| [packages/agent\_core/src/agent\_core/application/services/skill/recommendations.py](/packages/agent_core/src/agent_core/application/services/skill/recommendations.py) | Python | 2 | 1 | 1 | 4 |
| [packages/agent\_core/src/agent\_core/application/services/skill/resolution.py](/packages/agent_core/src/agent_core/application/services/skill/resolution.py) | Python | 4 | 0 | 0 | 4 |
| [packages/agent\_core/src/agent\_core/application/services/skill/rollout\_drilldown.py](/packages/agent_core/src/agent_core/application/services/skill/rollout_drilldown.py) | Python | 113 | 0 | 15 | 128 |
| [packages/agent\_core/src/agent\_core/application/services/skill/router.py](/packages/agent_core/src/agent_core/application/services/skill/router.py) | Python | 10 | 0 | 1 | 11 |
| [packages/agent\_core/src/agent\_core/application/services/skill/router\_policy.py](/packages/agent_core/src/agent_core/application/services/skill/router_policy.py) | Python | 16 | 7 | 6 | 29 |
| [packages/agent\_core/src/agent\_core/application/services/skill/router\_sources.py](/packages/agent_core/src/agent_core/application/services/skill/router_sources.py) | Python | 56 | 0 | 8 | 64 |
| [packages/agent\_core/src/agent\_core/application/services/skill/runtime\_explain.py](/packages/agent_core/src/agent_core/application/services/skill/runtime_explain.py) | Python | 118 | 12 | 8 | 138 |
| [packages/agent\_core/src/agent\_core/application/services/skill/usage.py](/packages/agent_core/src/agent_core/application/services/skill/usage.py) | Python | 25 | 8 | 3 | 36 |
| [packages/agent\_core/src/agent\_core/application/services/skills.py](/packages/agent_core/src/agent_core/application/services/skills.py) | Python | 10 | 2 | 0 | 12 |
| [packages/agent\_core/src/agent\_core/application/services/task.py](/packages/agent_core/src/agent_core/application/services/task.py) | Python | 2 | 0 | 0 | 2 |
| [packages/agent\_core/src/agent\_core/application/services/task\_autonomy\_scheduling.py](/packages/agent_core/src/agent_core/application/services/task_autonomy_scheduling.py) | Python | 4 | 0 | 0 | 4 |
| [packages/agent\_core/src/agent\_core/application/services/task\_runtime\_skill.py](/packages/agent_core/src/agent_core/application/services/task_runtime_skill.py) | Python | 2 | 0 | 0 | 2 |
| [packages/agent\_core/src/agent\_core/application/services/task\_status\_update\_support.py](/packages/agent_core/src/agent_core/application/services/task_status_update_support.py) | Python | -41 | 0 | 1 | -40 |
| [packages/agent\_core/src/agent\_core/application/services/tool\_plan\_runtime.py](/packages/agent_core/src/agent_core/application/services/tool_plan_runtime.py) | Python | 25 | 0 | 1 | 26 |
| [packages/agent\_core/src/agent\_core/domain/entities/learner/autonomy.py](/packages/agent_core/src/agent_core/domain/entities/learner/autonomy.py) | Python | 15 | 0 | 3 | 18 |
| [packages/agent\_core/src/agent\_core/domain/entities/memory/governance.py](/packages/agent_core/src/agent_core/domain/entities/memory/governance.py) | Python | 2 | 0 | 0 | 2 |
| [packages/agent\_core/src/agent\_core/domain/entities/quiz.py](/packages/agent_core/src/agent_core/domain/entities/quiz.py) | Python | 10 | 0 | 0 | 10 |
| [packages/agent\_core/src/agent\_core/domain/entities/reflection/evaluation.py](/packages/agent_core/src/agent_core/domain/entities/reflection/evaluation.py) | Python | 5 | 0 | 0 | 5 |
| [packages/agent\_core/src/agent\_core/domain/entities/reflection/proposal.py](/packages/agent_core/src/agent_core/domain/entities/reflection/proposal.py) | Python | 26 | 0 | 0 | 26 |
| [packages/agent\_core/src/agent\_core/domain/entities/reflection/record.py](/packages/agent_core/src/agent_core/domain/entities/reflection/record.py) | Python | 20 | 0 | 0 | 20 |
| [packages/agent\_core/src/agent\_core/domain/entities/session/\_\_init\_\_.py](/packages/agent_core/src/agent_core/domain/entities/session/__init__.py) | Python | 15 | 0 | 0 | 15 |
| [packages/agent\_core/src/agent\_core/domain/entities/session/quiz.py](/packages/agent_core/src/agent_core/domain/entities/session/quiz.py) | Python | 131 | 0 | 7 | 138 |
| [packages/agent\_core/src/agent\_core/domain/entities/skill/\_\_init\_\_.py](/packages/agent_core/src/agent_core/domain/entities/skill/__init__.py) | Python | 14 | 1 | 2 | 17 |
| [packages/agent\_core/src/agent\_core/domain/entities/skill/artifact.py](/packages/agent_core/src/agent_core/domain/entities/skill/artifact.py) | Python | 13 | 0 | 0 | 13 |
| [packages/agent\_core/src/agent\_core/domain/entities/skill/execution.py](/packages/agent_core/src/agent_core/domain/entities/skill/execution.py) | Python | 30 | 0 | 0 | 30 |
| [packages/agent\_core/src/agent\_core/domain/entities/skill/package.py](/packages/agent_core/src/agent_core/domain/entities/skill/package.py) | Python | 245 | 0 | 25 | 270 |
| [packages/agent\_core/src/agent\_core/domain/entities/skill/recommendation.py](/packages/agent_core/src/agent_core/domain/entities/skill/recommendation.py) | Python | 20 | 0 | 0 | 20 |
| [packages/agent\_core/src/agent\_core/domain/entities/skill/usage.py](/packages/agent_core/src/agent_core/domain/entities/skill/usage.py) | Python | 13 | 0 | 0 | 13 |
| [packages/agent\_core/src/agent\_core/domain/errors.py](/packages/agent_core/src/agent_core/domain/errors.py) | Python | 3 | 5 | 1 | 9 |
| [packages/agent\_core/src/agent\_core/domain/schemas/quiz.py](/packages/agent_core/src/agent_core/domain/schemas/quiz.py) | Python | 84 | 3 | 36 | 123 |
| [packages/agent\_core/src/agent\_core/domain/schemas/reflection.py](/packages/agent_core/src/agent_core/domain/schemas/reflection.py) | Python | 3 | 0 | 0 | 3 |
| [packages/agent\_core/src/agent\_core/domain/schemas/reflection\_v2.py](/packages/agent_core/src/agent_core/domain/schemas/reflection_v2.py) | Python | 3 | 0 | 2 | 5 |
| [packages/agent\_core/src/agent\_core/domain/schemas/skill.py](/packages/agent_core/src/agent_core/domain/schemas/skill.py) | Python | 118 | 0 | 28 | 146 |
| [packages/agent\_core/src/agent\_core/infrastructure/config/settings.py](/packages/agent_core/src/agent_core/infrastructure/config/settings.py) | Python | 9 | 0 | 0 | 9 |
| [packages/agent\_core/src/agent\_core/infrastructure/db/models.py](/packages/agent_core/src/agent_core/infrastructure/db/models.py) | Python | 87 | 0 | 9 | 96 |
| [packages/agent\_core/src/agent\_core/infrastructure/db/repositories/\_\_init\_\_.py](/packages/agent_core/src/agent_core/infrastructure/db/repositories/__init__.py) | Python | 7 | 0 | 2 | 9 |
| [packages/agent\_core/src/agent\_core/infrastructure/db/repositories/audit.py](/packages/agent_core/src/agent_core/infrastructure/db/repositories/audit.py) | Python | 55 | 0 | 2 | 57 |
| [packages/agent\_core/src/agent\_core/infrastructure/db/repositories/learner.py](/packages/agent_core/src/agent_core/infrastructure/db/repositories/learner.py) | Python | 19 | 0 | 1 | 20 |
| [packages/agent\_core/src/agent\_core/infrastructure/db/repositories/quiz\_answer\_attempt.py](/packages/agent_core/src/agent_core/infrastructure/db/repositories/quiz_answer_attempt.py) | Python | 199 | 1 | 22 | 222 |
| [packages/agent\_core/src/agent\_core/infrastructure/db/repositories/reflection.py](/packages/agent_core/src/agent_core/infrastructure/db/repositories/reflection.py) | Python | 5 | 0 | 1 | 6 |
| [packages/agent\_core/src/agent\_core/infrastructure/db/repositories/session.py](/packages/agent_core/src/agent_core/infrastructure/db/repositories/session.py) | Python | 22 | 0 | 1 | 23 |
| [packages/agent\_core/src/agent\_core/infrastructure/db/repositories/skill.py](/packages/agent_core/src/agent_core/infrastructure/db/repositories/skill.py) | Python | 6 | 0 | 0 | 6 |
| [packages/agent\_core/src/agent\_core/infrastructure/db/repositories/skill\_package.py](/packages/agent_core/src/agent_core/infrastructure/db/repositories/skill_package.py) | Python | 251 | 0 | 27 | 278 |
| [packages/agent\_core/src/agent\_core/infrastructure/embedding/dashscope\_compatible\_provider.py](/packages/agent_core/src/agent_core/infrastructure/embedding/dashscope_compatible_provider.py) | Python | 18 | 0 | 2 | 20 |
| [packages/agent\_core/src/agent\_core/infrastructure/llm/circuit\_breaker.py](/packages/agent_core/src/agent_core/infrastructure/llm/circuit_breaker.py) | Python | 12 | 2 | 1 | 15 |
| [packages/agent\_core/src/agent\_core/infrastructure/llm/dashscope\_compatible\_provider.py](/packages/agent_core/src/agent_core/infrastructure/llm/dashscope_compatible_provider.py) | Python | 88 | 0 | 5 | 93 |
| [packages/agent\_core/src/agent\_core/infrastructure/llm/mock\_provider.py](/packages/agent_core/src/agent_core/infrastructure/llm/mock_provider.py) | Python | 40 | 0 | 1 | 41 |
| [packages/agent\_core/src/agent\_core/infrastructure/llm/types.py](/packages/agent_core/src/agent_core/infrastructure/llm/types.py) | Python | 23 | 0 | 3 | 26 |
| [packages/agent\_core/src/agent\_core/infrastructure/observability/metrics.py](/packages/agent_core/src/agent_core/infrastructure/observability/metrics.py) | Python | 129 | 8 | 43 | 180 |
| [packages/frontend/package-lock.json](/packages/frontend/package-lock.json) | JSON | 1,715 | 0 | 0 | 1,715 |
| [packages/frontend/package.json](/packages/frontend/package.json) | JSON | 8 | 0 | 0 | 8 |
| [packages/frontend/src/App.tsx](/packages/frontend/src/App.tsx) | TypeScript JSX | 6 | 0 | 0 | 6 |
| [packages/frontend/src/api/client.test.ts](/packages/frontend/src/api/client.test.ts) | TypeScript | 80 | 11 | 20 | 111 |
| [packages/frontend/src/api/client.ts](/packages/frontend/src/api/client.ts) | TypeScript | 32 | 8 | 2 | 42 |
| [packages/frontend/src/hooks/use-operator-quiz-observability.ts](/packages/frontend/src/hooks/use-operator-quiz-observability.ts) | TypeScript | 65 | 0 | 8 | 73 |
| [packages/frontend/src/hooks/use-quiz-attempts.ts](/packages/frontend/src/hooks/use-quiz-attempts.ts) | TypeScript | 206 | 0 | 22 | 228 |
| [packages/frontend/src/hooks/use-quiz.ts](/packages/frontend/src/hooks/use-quiz.ts) | TypeScript | 25 | 0 | 2 | 27 |
| [packages/frontend/src/pages/goals/goals-page.tsx](/packages/frontend/src/pages/goals/goals-page.tsx) | TypeScript JSX | -1 | 0 | 0 | -1 |
| [packages/frontend/src/pages/learning/components/answer-feedback-card.test.tsx](/packages/frontend/src/pages/learning/components/answer-feedback-card.test.tsx) | TypeScript JSX | 104 | 1 | 15 | 120 |
| [packages/frontend/src/pages/learning/components/answer-feedback-card.tsx](/packages/frontend/src/pages/learning/components/answer-feedback-card.tsx) | TypeScript JSX | 200 | 7 | 18 | 225 |
| [packages/frontend/src/pages/learning/components/question-card.test.tsx](/packages/frontend/src/pages/learning/components/question-card.test.tsx) | TypeScript JSX | 86 | 1 | 11 | 98 |
| [packages/frontend/src/pages/learning/components/question-card.tsx](/packages/frontend/src/pages/learning/components/question-card.tsx) | TypeScript JSX | 184 | 8 | 12 | 204 |
| [packages/frontend/src/pages/learning/components/quiz-panel.test.tsx](/packages/frontend/src/pages/learning/components/quiz-panel.test.tsx) | TypeScript JSX | 213 | 4 | 25 | 242 |
| [packages/frontend/src/pages/learning/components/quiz-panel.tsx](/packages/frontend/src/pages/learning/components/quiz-panel.tsx) | TypeScript JSX | -96 | 0 | -6 | -102 |
| [packages/frontend/src/pages/operator/learning-gains-page.tsx](/packages/frontend/src/pages/operator/learning-gains-page.tsx) | TypeScript JSX | 250 | 3 | 17 | 270 |
| [packages/frontend/src/pages/operator/memory-detail-page.tsx](/packages/frontend/src/pages/operator/memory-detail-page.tsx) | TypeScript JSX | -1 | 0 | 0 | -1 |
| [packages/frontend/src/pages/operator/misconceptions-page.tsx](/packages/frontend/src/pages/operator/misconceptions-page.tsx) | TypeScript JSX | 191 | 4 | 11 | 206 |
| [packages/frontend/src/pages/operator/operator-dashboard-page.tsx](/packages/frontend/src/pages/operator/operator-dashboard-page.tsx) | TypeScript JSX | 80 | 0 | 4 | 84 |
| [packages/frontend/src/pages/operator/quiz-attempts-page.tsx](/packages/frontend/src/pages/operator/quiz-attempts-page.tsx) | TypeScript JSX | 333 | 5 | 21 | 359 |
| [packages/frontend/src/test/fixtures.ts](/packages/frontend/src/test/fixtures.ts) | TypeScript | 78 | 0 | 6 | 84 |
| [packages/frontend/src/test/setup.ts](/packages/frontend/src/test/setup.ts) | TypeScript | 6 | 0 | 2 | 8 |
| [packages/frontend/src/types/quiz-observability.ts](/packages/frontend/src/types/quiz-observability.ts) | TypeScript | 43 | 0 | 10 | 53 |
| [packages/frontend/src/types/quiz.ts](/packages/frontend/src/types/quiz.ts) | TypeScript | 52 | 0 | 9 | 61 |
| [packages/frontend/vitest.config.ts](/packages/frontend/vitest.config.ts) | TypeScript | 18 | 0 | 2 | 20 |
| [plan/QUIZ\_ADAPTIVE\_MEMORY\_SKILL\_ENHANCEMENT\_PLAN.md](/plan/QUIZ_ADAPTIVE_MEMORY_SKILL_ENHANCEMENT_PLAN.md) | Markdown | 428 | 0 | 177 | 605 |
| [tests/e2e\_quiz\_contract\_smoke.py](/tests/e2e_quiz_contract_smoke.py) | Python | 117 | 20 | 24 | 161 |
| [tests/test\_adaptive\_quiz\_policy.py](/tests/test_adaptive_quiz_policy.py) | Python | 513 | 4 | 92 | 609 |
| [tests/test\_answer\_attempt\_memory\_bridge.py](/tests/test_answer_attempt_memory_bridge.py) | Python | 703 | 6 | 109 | 818 |
| [tests/test\_answer\_attempt\_reflection.py](/tests/test_answer_attempt_reflection.py) | Python | 482 | 13 | 92 | 587 |
| [tests/test\_answer\_grading\_service.py](/tests/test_answer_grading_service.py) | Python | 264 | 17 | 41 | 322 |
| [tests/test\_api\_integration.py](/tests/test_api_integration.py) | Python | 1 | 0 | 1 | 2 |
| [tests/test\_curator\_executor.py](/tests/test_curator_executor.py) | Python | 36 | 1 | 3 | 40 |
| [tests/test\_embedding\_circuit\_breaker.py](/tests/test_embedding_circuit_breaker.py) | Python | 105 | 11 | 28 | 144 |
| [tests/test\_error\_contract.py](/tests/test_error_contract.py) | Python | 53 | 6 | 22 | 81 |
| [tests/test\_mvp\_acceptance.py](/tests/test_mvp_acceptance.py) | Python | 56 | 4 | 5 | 65 |
| [tests/test\_mvp\_blackbox.py](/tests/test_mvp_blackbox.py) | Python | 143 | 33 | 28 | 204 |
| [tests/test\_phase6\_mastery\_routing.py](/tests/test_phase6_mastery_routing.py) | Python | 361 | 11 | 52 | 424 |
| [tests/test\_phase6\_metrics\_and\_validation.py](/tests/test_phase6_metrics_and_validation.py) | Python | 92 | 2 | 21 | 115 |
| [tests/test\_phase7\_learning\_gain.py](/tests/test_phase7_learning_gain.py) | Python | 386 | 24 | 66 | 476 |
| [tests/test\_phase8\_observability\_api.py](/tests/test_phase8_observability_api.py) | Python | 417 | 37 | 71 | 525 |
| [tests/test\_quiz\_answer\_attempts.py](/tests/test_quiz_answer_attempts.py) | Python | 483 | 29 | 77 | 589 |
| [tests/test\_rate\_limit\_security.py](/tests/test_rate_limit_security.py) | Python | 77 | 8 | 32 | 117 |
| [tests/test\_reflection\_service.py](/tests/test_reflection_service.py) | Python | 581 | 42 | 67 | 690 |
| [tests/test\_reflection\_skill\_evolution\_regression.py](/tests/test_reflection_skill_evolution_regression.py) | Python | 23 | 4 | 4 | 31 |
| [tests/test\_reflection\_trigger\_policy.py](/tests/test_reflection_trigger_policy.py) | Python | 216 | 3 | 26 | 245 |
| [tests/test\_runtime\_protection\_alert\_bridge.py](/tests/test_runtime_protection_alert_bridge.py) | Python | 98 | 10 | 35 | 143 |
| [tests/test\_sandbox\_admission\_and\_governance.py](/tests/test_sandbox_admission_and_governance.py) | Python | 40 | 24 | 9 | 73 |
| [tests/test\_skill\_explainability.py](/tests/test_skill_explainability.py) | Python | 340 | 19 | 69 | 428 |
| [tests/test\_skill\_outcome\_feedback.py](/tests/test_skill_outcome_feedback.py) | Python | 391 | 25 | 73 | 489 |
| [tests/test\_skill\_package\_registry.py](/tests/test_skill_package_registry.py) | Python | 557 | 28 | 108 | 693 |
| [tests/test\_skill\_router.py](/tests/test_skill_router.py) | Python | 111 | 15 | 14 | 140 |
| [tests/test\_skill\_service.py](/tests/test_skill_service.py) | Python | 108 | 9 | 13 | 130 |
| [tests/test\_task\_runtime\_skill.py](/tests/test_task_runtime_skill.py) | Python | 2 | 0 | 0 | 2 |

[Summary](results.md) / [Details](details.md) / [Diff Summary](diff.md) / Diff Details