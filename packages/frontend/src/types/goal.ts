export interface LearnerGoal {
  id: string;
  learner_profile_id: string;
  title: string;
  subject: string;
  target_outcome: string;
  baseline_note: string | null;
  deadline_date: string;
  weekly_study_minutes: number;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface CreateGoalRequest {
  title: string;
  subject: string;
  target_outcome: string;
  baseline_note?: string | null;
  deadline_date: string;
  weekly_study_minutes: number;
}

export interface StudyPlanSummary {
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
  stages: PlanStageSummary[];
}

export interface PlanStageSummary {
  id: string;
  study_plan_id: string;
  position: number;
  title: string;
  objective: string;
  focus_topics: string[];
  start_date: string;
  end_date: string;
}
