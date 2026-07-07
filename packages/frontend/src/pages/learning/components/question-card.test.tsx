import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QuestionCard } from "@/pages/learning/components/question-card";
import {
  buildAnswerAttemptResponse,
  buildQuizQuestion,
} from "@/test/fixtures";
import type { RecommendedNextAction } from "@/types/quiz";

function renderCard(overrides: Partial<Parameters<typeof QuestionCard>[0]> = {}) {
  const defaults = {
    index: 0,
    question: buildQuizQuestion(),
    answer: "4",
    onAnswerChange: vi.fn(),
    isRevealed: false,
    isHinted: false,
    isDiscussed: false,
    isSubmitting: false,
    attempt: undefined,
    attemptError: undefined,
    isPending: false,
    onToggleReveal: vi.fn(),
    onSubmitAttempt: vi.fn(),
    onRequestHint: vi.fn(),
    onDiscuss: vi.fn(),
    onFollowUp: vi.fn<(a: RecommendedNextAction | string) => void>(),
  };
  const props = { ...defaults, ...overrides };
  return { ...render(<QuestionCard {...props} />), props };
}

describe("QuestionCard", () => {
  it("disables submit when answer is empty", () => {
    renderCard({ answer: "" });
    const submit = screen.getByRole("button", { name: /提交批改/ });
    expect(submit).toBeDisabled();
  });

  it("disables submit when question has no id (legacy quiz)", () => {
    renderCard({ question: buildQuizQuestion({ id: null }) });
    const submit = screen.getByRole("button", { name: /提交批改/ });
    expect(submit).toBeDisabled();
    expect(
      screen.getByText(/该题缺少标识，无法提交自动批改/),
    ).toBeInTheDocument();
  });

  it("calls onSubmitAttempt when submit button is clicked", () => {
    const onSubmitAttempt = vi.fn();
    renderCard({ onSubmitAttempt });
    fireEvent.click(screen.getByRole("button", { name: /提交批改/ }));
    expect(onSubmitAttempt).toHaveBeenCalledTimes(1);
  });

  it("shows re-submit label when an attempt already exists", () => {
    renderCard({ attempt: buildAnswerAttemptResponse() });
    expect(screen.getByRole("button", { name: /重新提交/ })).toBeInTheDocument();
  });

  it("renders submission error when attemptError is set", () => {
    renderCard({ attemptError: "timeout" });
    expect(screen.getByText(/提交失败：timeout/)).toBeInTheDocument();
  });

  it("calls onRequestHint on hint button click", () => {
    const onRequestHint = vi.fn();
    renderCard({ onRequestHint });
    fireEvent.click(screen.getByRole("button", { name: /获取提示/ }));
    expect(onRequestHint).toHaveBeenCalledTimes(1);
  });

  it("disables discuss button when answer is empty", () => {
    renderCard({ answer: "" });
    const discuss = screen.getByRole("button", { name: /提交讨论/ });
    expect(discuss).toBeDisabled();
  });

  it("forwards follow-up action from feedback card", () => {
    const onFollowUp = vi.fn<(a: RecommendedNextAction | string) => void>();
    renderCard({
      attempt: buildAnswerAttemptResponse({
        recommended_next_action: "request_hint",
      }),
      onFollowUp,
    });
    // AnswerFeedbackCard renders the "执行" button for follow-up
    fireEvent.click(screen.getByRole("button", { name: /执行/ }));
    expect(onFollowUp).toHaveBeenCalledWith("request_hint");
  });

  it("renders hinted/discussed badges when flags are set", () => {
    renderCard({ isHinted: true, isDiscussed: true });
    expect(screen.getByText("已要提示")).toBeInTheDocument();
    expect(screen.getByText("已讨论")).toBeInTheDocument();
  });
});
