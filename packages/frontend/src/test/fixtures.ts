import type {
  AnswerAttemptResponse,
  GradingFeedback,
  MasterySnapshot,
  QuizDraft,
  QuizQuestion,
} from "@/types/quiz";

export function buildGradingFeedback(
  overrides: Partial<GradingFeedback> = {},
): GradingFeedback {
  return {
    grading_status: "graded",
    grading_source: "hybrid",
    score: 1.0,
    is_correct: true,
    confidence: 0.9,
    rubric_feedback: null,
    misconception_codes: [],
    needs_human_review: false,
    ...overrides,
  };
}

export function buildMasterySnapshot(
  overrides: Partial<MasterySnapshot> = {},
): MasterySnapshot {
  return {
    topic_key: "LinearAlgebra",
    mastery_score: 0.65,
    confidence: 0.7,
    evidence_count: 5,
    last_attempt_status: "completed",
    last_assessed_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

export function buildAnswerAttemptResponse(
  overrides: Partial<AnswerAttemptResponse> = {},
): AnswerAttemptResponse {
  return {
    attempt_id: "att-1",
    session_id: "sess-1",
    quiz_id: "quiz-1",
    question_id: "qq-1",
    attempt_number: 1,
    grading: buildGradingFeedback(),
    mastery_snapshot: buildMasterySnapshot(),
    recommended_next_action: "continue",
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

export function buildQuizQuestion(
  overrides: Partial<QuizQuestion> = {},
): QuizQuestion {
  return {
    id: "qq-1",
    prompt: "What is 2+2?",
    answer: "4",
    question_type: "short_answer",
    options: [],
    ...overrides,
  };
}

export function buildQuizDraft(
  overrides: Partial<QuizDraft> = {},
): QuizDraft {
  return {
    quiz_id: "quiz-1",
    session_id: "sess-1",
    topic: "LinearAlgebra",
    difficulty: "medium",
    question_count: 2,
    questions: [buildQuizQuestion(), buildQuizQuestion({ id: "qq-2", prompt: "3*3?" })],
    skill_trace: [],
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}
