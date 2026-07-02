export interface DailyTask {
  id: string;
  learner_goal_id: string;
  study_plan_id: string;
  plan_stage_id: string | null;
  task_origin: string;
  task_type: string;
  execution_mode: string;
  title: string;
  instructions: string;
  topic_focus: string;
  difficulty: string | null;
  question_count: number | null;
  estimated_minutes: number;
  scheduled_for: string;
  due_on: string;
  status: string;
  source_task_id: string | null;
  execution_session_id: string | null;
  last_workflow_run_id: string | null;
  result_note: string | null;
  created_at: string;
  updated_at: string;
}

export interface ExecuteDailyTaskResponse {
  task: DailyTask;
  workflow_run_id: string;
  execution_session_id: string;
  reused_existing_execution: boolean;
}

export interface UpdateDailyTaskStatusRequest {
  status: string;
  result_note?: string;
}

export interface PlanStage {
  id: string;
  study_plan_id: string;
  position: number;
  title: string;
  objective: string;
  focus_topics: string[];
  start_date: string;
  end_date: string;
}

export interface StudyPlan {
  id: string;
  learner_goal_id: string;
  version: number;
  status: string;
  trigger_source: string;
  plan_summary: string;
  blueprint_payload: Record<string, unknown>;
  materialized_until_date: string | null;
  supersedes_plan_id: string | null;
  created_at: string;
  updated_at: string;
  stages: PlanStage[];
}
