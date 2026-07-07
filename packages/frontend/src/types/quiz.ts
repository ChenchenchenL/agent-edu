export type QuestionType = "short_answer" | "open_ended" | "mcq";

export type GradingStrategy = "deterministic" | "llm" | "hybrid";

export type GradingStatus = "graded" | "needs_review" | "rejected";

export type GradingSource = "deterministic" | "llm" | "hybrid" | null;

export type RecommendedNextAction =
  | "continue"
  | "review"
  | "request_review"
  | "request_hint"
  | "easier_question"
  | "assessment_ready"
  | "generate_quiz"
  | "review_scheduling";

export interface QuizQuestion {
  id: string | null;
  prompt: string;
  answer: string;
  question_type?: QuestionType;
  options?: string[];
}

export interface QuizDraft {
  quiz_id: string;
  session_id: string;
  topic: string;
  difficulty: string;
  question_count: number;
  questions: QuizQuestion[];
  skill_trace: string[];
  created_at: string;
}

export interface QuizSummary {
  quiz_id: string;
  session_id: string;
  topic: string;
  difficulty: string;
  question_count: number;
  skill_trace: string[];
  created_at: string;
}

export interface GenerateQuizRequest {
  topic: string;
  difficulty: string;
  question_count: number;
}

export interface SubmitAnswerAttemptRequest {
  learner_answer: string;
  hint_used?: boolean;
  hint_count?: number;
  client_context?: Record<string, unknown> | null;
  grading_strategy?: GradingStrategy;
}

export interface GradingFeedback {
  grading_status: GradingStatus;
  grading_source: GradingSource;
  score: number | null;
  is_correct: boolean | null;
  confidence: number | null;
  rubric_feedback: string | null;
  misconception_codes: string[];
  needs_human_review: boolean;
}

export interface MasterySnapshot {
  topic_key: string;
  mastery_score: number;
  confidence: number;
  evidence_count: number;
  last_attempt_status: string | null;
  last_assessed_at: string | null;
}

export interface AnswerAttemptResponse {
  attempt_id: string;
  session_id: string;
  quiz_id: string;
  question_id: string;
  attempt_number: number;
  grading: GradingFeedback;
  mastery_snapshot: MasterySnapshot | null;
  recommended_next_action: RecommendedNextAction | string;
  created_at: string;
}
