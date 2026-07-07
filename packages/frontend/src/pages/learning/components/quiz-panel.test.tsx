import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { PropsWithChildren } from "react";

import { QuizPanel } from "@/pages/learning/components/quiz-panel";
import { buildQuizDraft, buildAnswerAttemptResponse } from "@/test/fixtures";
import type {
  AnswerAttemptResponse,
  QuizDraft,
  QuizSummary,
} from "@/types/quiz";

const mockUseSessionQuizzes = vi.fn<
  (sessionId: string) => { data: QuizSummary[] | undefined; isLoading: boolean; error: null }
>();
const mockUseQuizDetail = vi.fn<
  (
    sessionId: string,
    quizId: string | null,
  ) => { data: QuizDraft | undefined; isLoading: boolean; error: null }
>();
const mockUseGenerateQuiz = vi.fn<(sessionId: string) => {
  isPending: boolean;
  error: null;
  mutate: ReturnType<typeof vi.fn>;
}>();
const mockUseSubmitAnswerAttempt = vi.fn<(sessionId: string) => {
  mutate: ReturnType<typeof vi.fn>;
}>();

vi.mock("@/hooks/use-quiz", () => ({
  useSessionQuizzes: (...args: unknown[]) => mockUseSessionQuizzes(...(args as [string])),
  useQuizDetail: (...args: unknown[]) => mockUseQuizDetail(...(args as [string, string | null])),
  useGenerateQuiz: (...args: unknown[]) => mockUseGenerateQuiz(...(args as [string])),
  useSubmitAnswerAttempt: (...args: unknown[]) =>
    mockUseSubmitAnswerAttempt(...(args as [string])),
}));

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: PropsWithChildren) {
    return (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>{children}</MemoryRouter>
      </QueryClientProvider>
    );
  };
}

const QUIZ_DRAFT_A = buildQuizDraft({
  quiz_id: "quiz-a",
  topic: "Algebra",
  questions: [
    { id: "q-a1", prompt: "2+2?", answer: "4", question_type: "short_answer", options: [] },
    { id: "q-a2", prompt: "3*3?", answer: "9", question_type: "short_answer", options: [] },
  ],
});

const QUIZ_DRAFT_B = buildQuizDraft({
  quiz_id: "quiz-b",
  topic: "Geometry",
  questions: [
    { id: "q-b1", prompt: "Sides of triangle?", answer: "3", question_type: "short_answer", options: [] },
  ],
});

function setupBaseHooks() {
  mockUseSessionQuizzes.mockReturnValue({
    data: [
      {
        quiz_id: "quiz-a",
        session_id: "sess-1",
        topic: "Algebra",
        difficulty: "medium",
        question_count: 2,
        skill_trace: [],
        created_at: "2026-01-01T00:00:00Z",
      },
      {
        quiz_id: "quiz-b",
        session_id: "sess-1",
        topic: "Geometry",
        difficulty: "easy",
        question_count: 1,
        skill_trace: [],
        created_at: "2026-01-02T00:00:00Z",
      },
    ],
    isLoading: false,
    error: null,
  });
  mockUseQuizDetail.mockImplementation((_sessionId, quizId) => {
    if (quizId === "quiz-a") return { data: QUIZ_DRAFT_A, isLoading: false, error: null };
    if (quizId === "quiz-b") return { data: QUIZ_DRAFT_B, isLoading: false, error: null };
    return { data: undefined, isLoading: false, error: null };
  });
  mockUseGenerateQuiz.mockReturnValue({
    isPending: false,
    error: null,
    mutate: vi.fn(),
  });
  const submitMutate = vi.fn();
  mockUseSubmitAnswerAttempt.mockReturnValue({ mutate: submitMutate });
  return submitMutate;
}

describe("QuizPanel integration", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders quiz list and first quiz's questions on mount", async () => {
    setupBaseHooks();
    render(
      <QuizPanel
        sessionId="sess-1"
        defaultTopic="Math"
        onRequestHint={() => {}}
        onDiscussAnswer={() => {}}
        isPending={false}
      />,
      { wrapper: createWrapper() },
    );

    await waitFor(() => {
      expect(screen.getAllByText("Algebra").length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText("Geometry")).toBeInTheDocument();
    });
    expect(screen.getByText("2+2?")).toBeInTheDocument();
    expect(screen.getByText("3*3?")).toBeInTheDocument();
  });

  it("calls submitAttempt mutation when user submits an answer", async () => {
    const submitMutate = setupBaseHooks();
    render(
      <QuizPanel
        sessionId="sess-1"
        defaultTopic="Math"
        onRequestHint={() => {}}
        onDiscussAnswer={() => {}}
        isPending={false}
      />,
      { wrapper: createWrapper() },
    );

    await waitFor(() => screen.getByText("2+2?"));

    const answerInputs = screen.getAllByPlaceholderText("写下你的答案...");
    await userEvent.type(answerInputs[0], "4");

    const submitButtons = screen.getAllByRole("button", { name: /提交批改/ });
    fireEvent.click(submitButtons[0]);

    expect(submitMutate).toHaveBeenCalledTimes(1);
    const call = submitMutate.mock.calls[0];
    expect(call[0]).toEqual({
      quizId: "quiz-a",
      questionId: "q-a1",
      payload: {
        learner_answer: "4",
        hint_used: false,
        hint_count: 0,
        grading_strategy: "hybrid",
      },
    });
  });

  it("clears local answer state when user switches to a different quiz", async () => {
    setupBaseHooks();
    render(
      <QuizPanel
        sessionId="sess-1"
        defaultTopic="Math"
        onRequestHint={() => {}}
        onDiscussAnswer={() => {}}
        isPending={false}
      />,
      { wrapper: createWrapper() },
    );

    await waitFor(() => screen.getByText("2+2?"));

    // Type into the first answer box
    const answerInputs = screen.getAllByPlaceholderText("写下你的答案...");
    await userEvent.type(answerInputs[0], "some answer");
    expect((answerInputs[0] as HTMLTextAreaElement).value).toBe("some answer");

    // Click the "Geometry" quiz button in the history list
    fireEvent.click(screen.getByText("Geometry"));

    await waitFor(() => {
      expect(screen.getByText("Sides of triangle?")).toBeInTheDocument();
    });
    // The new quiz's answer textarea should be empty (state cleared)
    const newInputs = screen.getAllByPlaceholderText("写下你的答案...");
    expect((newInputs[0] as HTMLTextAreaElement).value).toBe("");
  });

  it("shows feedback card after successful submission", async () => {
    const submitMutate = vi.fn(
      (_params: unknown, options?: { onSuccess?: (r: AnswerAttemptResponse) => void }) => {
        options?.onSuccess?.(
          buildAnswerAttemptResponse({
            attempt_id: "att-1",
            question_id: "q-a1",
            recommended_next_action: "continue",
          }),
        );
      },
    );
    setupBaseHooks();
    mockUseSubmitAnswerAttempt.mockReturnValue({ mutate: submitMutate });

    render(
      <QuizPanel
        sessionId="sess-1"
        defaultTopic="Math"
        onRequestHint={() => {}}
        onDiscussAnswer={() => {}}
        isPending={false}
      />,
      { wrapper: createWrapper() },
    );

    await waitFor(() => screen.getByText("2+2?"));
    const answerInputs = screen.getAllByPlaceholderText("写下你的答案...");
    await userEvent.type(answerInputs[0], "4");
    const submitButtons = screen.getAllByRole("button", { name: /提交批改/ });
    fireEvent.click(submitButtons[0]);

    // After successful submission, the AnswerFeedbackCard renders "答案正确"
    await waitFor(() => {
      expect(screen.getByText("答案正确")).toBeInTheDocument();
    });
  });
});
