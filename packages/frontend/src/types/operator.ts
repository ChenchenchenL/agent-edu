export interface AuditEvent {
  id: string;
  event_type: string;
  resource_type: string;
  resource_id: string | null;
  actor: string;
  event_data: Record<string, unknown>;
  created_at: string;
}

export interface MemoryGovernanceSummary {
  learner_profile_id: string;
  learner_goal_id: string | null;
  knowledge_total: number;
  behavior_total: number;
  candidate_total: number;
  active_total: number;
  stable_total: number;
  archived_total: number;
  suppressed_total: number;
  contradiction_focus_total: number;
  stale_candidate_total: number;
  high_priority_total: number;
  promotion_candidate_total: number;
  demotion_risk_total: number;
  operator_review_recommended_total: number;
  high_quality_total: number;
  medium_quality_total: number;
  ready_promotion_total: number;
  weak_candidate_total: number;
}

export interface MemoryConflictSet {
  id: string;
  learner_profile_id: string;
  learner_goal_id: string | null;
  topic_key: string;
  conflict_type: string;
  severity_score: number;
  status: string;
  summary: string;
  reason_code: string;
  reason_note: string;
  handling_result: string | null;
  created_at: string;
  updated_at: string;
}

export interface ReflectionReviewQueueItem {
  reflection_id: string;
  learner_goal_id: string;
  learner_profile_id: string;
  status: string;
  scope: string;
  trigger_source: string;
  primary_root_cause: string;
  severity: string;
  confidence_score: number;
  priority_score: number;
  duplicate_count: number;
  summary: string;
  created_at: string;
  last_duplicate_at: string | null;
}

export interface ReflectionReviewQueueResponse {
  items: ReflectionReviewQueueItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface ProposalQueueItem {
  id: string;
  reflection_record_id: string;
  learner_goal_id: string;
  proposal_type: string;
  target_scope: string;
  status: string;
  priority_score: number;
  risk_level: string;
  auto_sandbox_eligible: boolean;
  admission_mode: string;
  rollout_eligible: boolean;
  activation_surface: string;
  evaluation_status: string;
  change_summary: string;
  latest_sandbox_run_id: string | null;
  proposal_bundle_id: string | null;
  created_at: string;
}

export interface ProposalQueueResponse {
  items: ProposalQueueItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface SkillCuratorRecommendation {
  id: string;
  artifact_id: string;
  skill_name: string;
  skill_version: number;
  artifact_status: string;
  scope: string;
  surface: string;
  recommendation_type: string;
  recommended_action: string;
  status: string;
  reason_code: string;
  reason_note: string;
  created_at: string;
  updated_at: string;
}

export interface GuardrailsStatus {
  llm_call_guard: { enabled: boolean } | Record<string, unknown>;
  circuit_breaker: { enabled: boolean } | Record<string, unknown>;
}
