import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { AnswerFeedbackCard } from "@/pages/learning/components/answer-feedback-card";
import {
  buildAnswerAttemptResponse,
  buildGradingFeedback,
  buildMasterySnapshot,
} from "@/test/fixtures";
import type { RecommendedNextAction } from "@/types/quiz";

describe("AnswerFeedbackCard", () => {
  it("renders correct answer state with score and mastery", () => {
    const attempt = buildAnswerAttemptResponse({
      grading: buildGradingFeedback({
        score: 1.0,
        is_correct: true,
        grading_status: "graded",
        confidence: 0.95,
      }),
      mastery_snapshot: buildMasterySnapshot({ mastery_score: 0.8 }),
      recommended_next_action: "continue",
    });

    render(
      <AnswerFeedbackCard attempt={attempt} questionPrompt="What is 2+2?" />,
    );

    expect(screen.getByText("答案正确")).toBeInTheDocument();
    expect(screen.getByText("得分：100 分")).toBeInTheDocument();
    expect(screen.getByText(/置信度 95%/)).toBeInTheDocument();
    expect(screen.getByText(/掌握度/)).toBeInTheDocument();
    expect(screen.getByText(/80%/)).toBeInTheDocument();
    expect(screen.getByText("继续下一题")).toBeInTheDocument();
  });

  it("renders wrong answer state", () => {
    const attempt = buildAnswerAttemptResponse({
      grading: buildGradingFeedback({
        score: 0,
        is_correct: false,
        rubric_feedback: "Sign error on the diagonal.",
        misconception_codes: ["mis-1", "mis-2"],
      }),
      recommended_next_action: "review",
    });

    render(
      <AnswerFeedbackCard attempt={attempt} questionPrompt="Compute det(A)" />,
    );

    expect(screen.getByText("答案有误")).toBeInTheDocument();
    expect(screen.getByText("得分：0 分")).toBeInTheDocument();
    expect(screen.getByText("Sign error on the diagonal.")).toBeInTheDocument();
    expect(screen.getByText("mis-1")).toBeInTheDocument();
    expect(screen.getByText("mis-2")).toBeInTheDocument();
    expect(screen.getByText("复习该知识点")).toBeInTheDocument();
  });

  it("renders needs_review state with notice", () => {
    const attempt = buildAnswerAttemptResponse({
      grading: buildGradingFeedback({
        grading_status: "needs_review",
        score: null,
        is_correct: null,
        confidence: null,
        needs_human_review: true,
        grading_source: null,
      }),
      mastery_snapshot: null,
      recommended_next_action: "request_review",
    });

    render(
      <AnswerFeedbackCard attempt={attempt} questionPrompt="Explain X" />,
    );

    expect(screen.getByText("待人工复核")).toBeInTheDocument();
    expect(
      screen.getByText(/本题需要人工复核，当前结果暂不计入掌握度/),
    ).toBeInTheDocument();
    // Mastery snapshot section is absent (no "证据 N" counter)
    expect(screen.queryByText(/证据/)).not.toBeInTheDocument();
  });

  it("calls onFollowUp with action when execute button is clicked", () => {
    const onFollowUp = vi.fn<(action: RecommendedNextAction | string) => void>();
    const attempt = buildAnswerAttemptResponse({
      recommended_next_action: "request_hint",
    });

    render(
      <AnswerFeedbackCard
        attempt={attempt}
        questionPrompt="Q"
        onFollowUp={onFollowUp}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /执行/ }));
    expect(onFollowUp).toHaveBeenCalledWith("request_hint");
    expect(onFollowUp).toHaveBeenCalledTimes(1);
  });

  it("hides follow-up execute button when onFollowUp not provided", () => {
    const attempt = buildAnswerAttemptResponse();
    render(
      <AnswerFeedbackCard attempt={attempt} questionPrompt="Q" />,
    );
    expect(screen.queryByRole("button", { name: /执行/ })).not.toBeInTheDocument();
  });

  it("renders attempt number badge", () => {
    const attempt = buildAnswerAttemptResponse({ attempt_number: 3 });
    render(
      <AnswerFeedbackCard attempt={attempt} questionPrompt="Q" />,
    );
    expect(screen.getByText(/第 3 次作答/)).toBeInTheDocument();
  });
});
