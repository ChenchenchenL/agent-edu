export type GradingStatus = "graded" | "needs_review" | "rejected";

export interface OperatorAttemptRecord {
  id: string;
  session_id: string;
  quiz_id: string;
  question_id: string;
  score: number | null;
  is_correct: boolean | null;
  misconception_codes: string[];
  created_at: string;
}

export interface OperatorAttemptBrowseResponse {
  attempts: OperatorAttemptRecord[];
  total_count: number;
}

export interface OperatorGradingQueueResponse {
  queue: OperatorAttemptRecord[];
}

export interface MisconceptionTrendRecord {
  misconception_code: string;
  count: number;
}

export interface MisconceptionTrendResponse {
  trends: MisconceptionTrendRecord[];
}

export interface AdaptivePolicyAuditRecord {
  id: string;
  event_type: string;
  resource_id: string | null;
  event_data: Record<string, unknown>;
  created_at: string;
}

export interface AdaptivePolicyAuditTrailResponse {
  audit_trail: AdaptivePolicyAuditRecord[];
}

export interface LearningGainRecord {
  skill_name: string;
  average_learning_gain: number;
  sample_size: number;
}

export interface LearningGainDashboardResponse {
  learning_gains: LearningGainRecord[];
}
