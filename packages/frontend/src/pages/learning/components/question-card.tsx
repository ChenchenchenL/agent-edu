import {
  AlertCircle,
  CheckCircle2,
  Circle,
  Eye,
  Lightbulb,
  Loader2,
  MessageSquareText,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { AnswerFeedbackCard } from "@/pages/learning/components/answer-feedback-card";
import type {
  AnswerAttemptResponse,
  QuizQuestion,
  RecommendedNextAction,
} from "@/types/quiz";

interface QuestionCardProps {
  index: number;
  question: QuizQuestion;
  answer: string;
  onAnswerChange: (value: string) => void;
  isRevealed: boolean;
  isHinted: boolean;
  isDiscussed: boolean;
  isSubmitting: boolean;
  attempt: AnswerAttemptResponse | undefined;
  attemptError: string | undefined;
  isPending: boolean;
  onToggleReveal: () => void;
  onSubmitAttempt: () => void;
  onRequestHint: () => void;
  onDiscuss: () => void;
  onFollowUp: (action: RecommendedNextAction | string) => void;
}

function StatusDot({
  isRevealed,
  hasAnswer,
}: {
  isRevealed: boolean;
  hasAnswer: boolean;
}) {
  if (isRevealed) {
    return <CheckCircle2 className="h-3.5 w-3.5 text-success" />;
  }
  if (hasAnswer) {
    return <Circle className="h-3.5 w-3.5 fill-accent-gold text-accent-gold" />;
  }
  return <Circle className="h-3.5 w-3.5 text-text-secondary" />;
}

export function QuestionCard({
  index,
  question,
  answer,
  onAnswerChange,
  isRevealed,
  isHinted,
  isDiscussed,
  isSubmitting,
  attempt,
  attemptError,
  isPending,
  onToggleReveal,
  onSubmitAttempt,
  onRequestHint,
  onDiscuss,
  onFollowUp,
}: QuestionCardProps) {
  const hasAnswer = !!answer.trim();
  const canSubmit = hasAnswer && !!question.id && !isSubmitting && !isPending;
  const submitLabel = isSubmitting
    ? "批改中..."
    : attempt
      ? "重新提交"
      : "提交批改";

  return (
    <div className="notebook-margin rounded-lg border border-border-subtle bg-surface p-3">
      {/* Header row: question index + status badges */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-1.5 text-xs font-medium text-text-secondary">
          <StatusDot isRevealed={isRevealed} hasAnswer={hasAnswer} />
          第 {index + 1} 题
        </div>
        <div className="flex shrink-0 gap-1">
          {isHinted && (
            <Badge variant="secondary" className="text-[10px]">
              已要提示
            </Badge>
          )}
          {isDiscussed && (
            <Badge variant="secondary" className="text-[10px]">
              已讨论
            </Badge>
          )}
        </div>
      </div>

      {/* Prompt */}
      <p className="mt-1 text-sm leading-relaxed text-text-primary">
        {question.prompt}
      </p>

      {/* Answer textarea */}
      <Textarea
        placeholder="写下你的答案..."
        value={answer}
        onChange={(e) => onAnswerChange(e.target.value)}
        className="mt-3 min-h-[64px] text-sm"
        disabled={isPending}
        maxLength={4000}
      />

      {/* Action buttons */}
      <div className="mt-2 flex flex-wrap gap-2">
        <Button
          type="button"
          size="sm"
          disabled={!canSubmit}
          onClick={onSubmitAttempt}
        >
          {isSubmitting ? (
            <>
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              {submitLabel}
            </>
          ) : (
            <>
              <CheckCircle2 className="h-3.5 w-3.5" />
              {submitLabel}
            </>
          )}
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={isPending}
          onClick={onRequestHint}
        >
          <Lightbulb className="h-3.5 w-3.5" />
          获取提示
        </Button>
        <Button
          type="button"
          variant="secondary"
          size="sm"
          disabled={isPending || !hasAnswer}
          onClick={onDiscuss}
        >
          <MessageSquareText className="h-3.5 w-3.5" />
          提交讨论
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={!hasAnswer}
          onClick={onToggleReveal}
        >
          <Eye className="h-3.5 w-3.5" />
          {isRevealed ? "隐藏参考" : "查看参考"}
        </Button>
      </div>

      {/* Submission error */}
      {question.id && attemptError && (
        <div className="mt-2 flex items-start gap-2 rounded-md border border-error/20 bg-error/5 px-2.5 py-2 text-xs text-error">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>提交失败：{attemptError}</span>
        </div>
      )}

      {/* Legacy quiz warning */}
      {!question.id && hasAnswer && (
        <p className="mt-2 text-[11px] text-text-secondary">
          该题缺少标识，无法提交自动批改；可使用"提交讨论"或"获取提示"。
        </p>
      )}

      {/* Reference answer */}
      {isRevealed && (
        <div className="mt-2 flex items-start gap-2 rounded-md bg-success/5 px-2.5 py-2 text-xs text-success">
          <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{question.answer}</span>
        </div>
      )}

      {/* Attempt feedback */}
      {question.id && attempt && (
        <AnswerFeedbackCard
          attempt={attempt}
          questionPrompt={question.prompt}
          onFollowUp={onFollowUp}
        />
      )}
    </div>
  );
}
