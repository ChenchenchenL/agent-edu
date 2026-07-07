import { useState } from "react";
import { useSubmitAnswerAttempt } from "@/hooks/use-quiz";
import type {
  AnswerAttemptResponse,
  QuizDraft,
  RecommendedNextAction,
} from "@/types/quiz";
import type { MessageRequest } from "@/types/session";

type IndexFlags = Record<number, boolean>;
type AttemptMap = Record<string, AnswerAttemptResponse>;
type AttemptErrorMap = Record<string, string>;

export interface UseQuizAttemptsInput {
  sessionId: string;
  activeQuiz: QuizDraft | null;
  activeQuizId: string | null;
}

export interface QuizAttemptActions {
  setAnswer: (index: number, value: string) => void;
  toggleReveal: (index: number) => void;
  submitAttempt: (index: number) => void;
  resetAll: () => void;
  requestHint: (index: number, onRequestHint: (p: MessageRequest) => void) => void;
  discuss: (index: number, onDiscussAnswer: (content: string) => void) => void;
  followUp: (
    index: number,
    action: RecommendedNextAction | string,
    regenerateQuiz: (difficultyOverride?: string) => void,
    onRequestHint: (payload: MessageRequest) => void,
  ) => void;
}

export interface QuizAttemptState {
  answers: Record<number, string>;
  revealed: IndexFlags;
  hinted: IndexFlags;
  discussed: IndexFlags;
  attempts: AttemptMap;
  attemptErrors: AttemptErrorMap;
  submitting: IndexFlags;
}

export interface QuizAttemptDerived {
  totalQuestions: number;
  answeredCount: number;
  checkedCount: number;
  canReset: boolean;
}

export function useQuizAttempts({
  sessionId,
  activeQuiz,
  activeQuizId,
}: UseQuizAttemptsInput) {
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const [revealed, setRevealed] = useState<IndexFlags>({});
  const [hinted, setHinted] = useState<IndexFlags>({});
  const [discussed, setDiscussed] = useState<IndexFlags>({});
  const [attempts, setAttempts] = useState<AttemptMap>({});
  const [attemptErrors, setAttemptErrors] = useState<AttemptErrorMap>({});
  const [submitting, setSubmitting] = useState<IndexFlags>({});

  const submitAttemptMutation = useSubmitAnswerAttempt(sessionId);

  const totalQuestions = activeQuiz?.questions.length ?? 0;
  const answeredCount =
    activeQuiz?.questions.filter((_, index) => answers[index]?.trim()).length ?? 0;
  const checkedCount =
    activeQuiz?.questions.filter((_, index) => revealed[index]).length ?? 0;
  const canReset =
    Object.keys(answers).length > 0 ||
    Object.keys(revealed).length > 0 ||
    Object.keys(hinted).length > 0 ||
    Object.keys(discussed).length > 0 ||
    Object.keys(attempts).length > 0;

  function resetAll() {
    setAnswers({});
    setRevealed({});
    setHinted({});
    setDiscussed({});
    setAttempts({});
    setAttemptErrors({});
    setSubmitting({});
  }

  function setAnswer(index: number, value: string) {
    setAnswers((prev) => ({ ...prev, [index]: value }));
  }

  function toggleReveal(index: number) {
    setRevealed((prev) => ({ ...prev, [index]: !prev[index] }));
  }

  function submitAttempt(index: number) {
    if (!activeQuiz || !activeQuizId) return;
    const question = activeQuiz.questions[index];
    const questionId = question?.id;
    const learnerAnswer = answers[index]?.trim();
    if (!questionId || !learnerAnswer) return;

    setSubmitting((prev) => ({ ...prev, [index]: true }));
    setAttemptErrors((prev) => {
      const next = { ...prev };
      delete next[questionId];
      return next;
    });

    submitAttemptMutation.mutate(
      {
        quizId: activeQuizId,
        questionId,
        payload: {
          learner_answer: learnerAnswer,
          hint_used: !!hinted[index],
          hint_count: hinted[index] ? 1 : 0,
          grading_strategy: "hybrid",
        },
      },
      {
        onSuccess: (response) => {
          setAttempts((prev) => ({ ...prev, [questionId]: response }));
        },
        onError: (err) => {
          setAttemptErrors((prev) => ({
            ...prev,
            [questionId]: err instanceof Error ? err.message : "提交失败",
          }));
        },
        onSettled: () => {
          setSubmitting((prev) => ({ ...prev, [index]: false }));
        },
      },
    );
  }

  function requestHint(
    index: number,
    onRequestHint: (payload: MessageRequest) => void,
  ) {
    if (!activeQuiz) return;
    const question = activeQuiz.questions[index];
    if (!question) return;
    const learnerAnswer = answers[index]?.trim();
    onRequestHint({
      content: learnerAnswer
        ? "请针对我的答案给出提示，不要直接告诉我正确答案"
        : "请给我这道题的提示，不要直接告诉我答案",
      mode: "hint",
      related_quiz_id: activeQuiz.quiz_id,
      question_prompt: question.prompt,
      learner_answer: learnerAnswer || undefined,
    });
    setHinted((prev) => ({ ...prev, [index]: true }));
  }

  function discuss(
    index: number,
    onDiscussAnswer: (content: string) => void,
  ) {
    const question = activeQuiz?.questions[index];
    const learnerAnswer = answers[index]?.trim();
    if (!question || !learnerAnswer) return;
    onDiscussAnswer(
      `关于练习题「${question.prompt}」，我的答案是：${learnerAnswer}。请帮我分析是否正确并讲解。`,
    );
    setDiscussed((prev) => ({ ...prev, [index]: true }));
  }

  function followUp(
    index: number,
    action: RecommendedNextAction | string,
    regenerateQuiz: (difficultyOverride?: string) => void,
    onRequestHint: (payload: MessageRequest) => void,
  ) {
    if (!activeQuiz) return;
    switch (action) {
      case "request_hint":
        requestHint(index, onRequestHint);
        return;
      case "generate_quiz":
      case "review_scheduling":
        regenerateQuiz();
        return;
      case "easier_question":
        regenerateQuiz("easy");
        return;
      case "request_review":
      case "assessment_ready":
      case "continue":
      case "review":
      default:
        return;
    }
  }

  const state: QuizAttemptState = {
    answers,
    revealed,
    hinted,
    discussed,
    attempts,
    attemptErrors,
    submitting,
  };

  const actions: QuizAttemptActions = {
    setAnswer,
    toggleReveal,
    submitAttempt,
    resetAll,
    requestHint,
    discuss,
    followUp,
  };

  const derived: QuizAttemptDerived = {
    totalQuestions,
    answeredCount,
    checkedCount,
    canReset,
  };

  return { state, actions, derived };
}
