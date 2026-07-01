export interface Session {
  id: string;
  learner_profile_id: string;
  learner_goal_id: string | null;
  daily_task_id: string | null;
  title: string | null;
  subject: string | null;
  status: string;
  message_count: number;
  last_activity_at: string;
  summary: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreateSessionRequest {
  learner_profile_id?: string;
  learner_goal_id?: string;
  title?: string;
  subject?: string;
}

export interface UpdateSessionStatusRequest {
  status: string;
}

export interface ExplanationPayload {
  type: "explanation";
  definition: string;
  core_principles: string[];
  worked_example: string;
  common_mistake: string;
  next_step: string;
}

export interface HintPayload {
  type: "hint";
  hint_level: "conceptual" | "scaffolded" | "targeted";
  next_step_hint: string;
  key_principle: string;
  pitfall: string;
  encouragement: string;
  direct_answer_given: boolean;
}

export type AssistantPayload = ExplanationPayload | HintPayload;

export interface MessageTurnMetrics {
  history_count: number;
  memory_context_count: number;
  cross_session_context_count: number;
  hint_level: "conceptual" | "scaffolded" | "targeted" | null;
  hint_history_count: number;
  used_quiz_context: boolean;
  used_error_analysis: boolean;
  retrieval_latency_ms: number;
  llm_latency_ms: number;
  llm_retry_count: number;
  response_shape_valid: boolean;
}

export interface MessageResponse {
  session_id: string;
  user_message_id: string;
  assistant_message_id: string;
  assistant_message: string;
  assistant_payload: AssistantPayload;
  skill_trace: string[];
  turn_metrics: MessageTurnMetrics;
}

export interface MessageRequest {
  content: string;
  mode?: "chat" | "hint";
  related_quiz_id?: string;
  question_prompt?: string;
  learner_answer?: string;
}

export interface MessageHistoryItem {
  id: string;
  session_id: string;
  role: string;
  content: string;
  mode: string | null;
  skill_trace: string[];
  content_payload: AssistantPayload | null;
  created_at: string;
}

export interface MessageHistoryResponse {
  items: MessageHistoryItem[];
  total: number;
  next_before_id: string | null;
}
