import {
  AlertCircle,
  CheckCircle2,
  CircleHelp,
  Sparkles,
  XCircle,
  UserCheck,
} from "lucide-react";
import type {
  AnswerAttemptResponse,
  GradingStatus,
  RecommendedNextAction,
} from "@/types/quiz";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

interface AnswerFeedbackCardProps {
  attempt: AnswerAttemptResponse;
  questionPrompt: string;
  onFollowUp?: (action: RecommendedNextAction | string) => void;
}

const STATUS_COPY: Record<GradingStatus, { label: string; tone: string }> = {
  graded: { label: "已批改", tone: "primary" },
  needs_review: { label: "待人工复核", tone: "warning" },
  rejected: { label: "批改失败", tone: "error" },
};

const ACTION_COPY: Record<string, string> = {
  continue: "继续下一题",
  review: "复习该知识点",
  request_review: "等待人工复核",
  request_hint: "请求提示",
  easier_question: "尝试更简单的题",
  assessment_ready: "进入测评",
  generate_quiz: "生成新练习",
  review_scheduling: "安排复习",
};

function toneClasses(tone: string): string {
  switch (tone) {
    case "success":
      return "border-success/30 bg-success/5 text-success";
    case "error":
      return "border-error/30 bg-error/5 text-error";
    case "warning":
      return "border-accent-gold/30 bg-accent-gold-surface text-accent-gold";
    case "primary":
    default:
      return "border-primary/20 bg-primary-surface text-primary";
  }
}

function statusTone(status: GradingStatus, isCorrect: boolean | null): string {
  if (status === "graded") return isCorrect ? "success" : "error";
  if (status === "needs_review") return "warning";
  return "error";
}

function StatusIcon({
  status,
  isCorrect,
}: {
  status: GradingStatus;
  isCorrect: boolean | null;
}) {
  if (status === "graded") {
    return isCorrect ? (
      <CheckCircle2 className="h-4 w-4 text-success" />
    ) : (
      <XCircle className="h-4 w-4 text-error" />
    );
  }
  if (status === "needs_review") {
    return <CircleHelp className="h-4 w-4 text-accent-gold" />;
  }
  return <AlertCircle className="h-4 w-4 text-error" />;
}

function formatPercent(score: number | null): string {
  if (score == null) return "—";
  return `${Math.round(score * 100)} 分`;
}

function formatMastery(score: number): string {
  return `${Math.round(score * 100)}%`;
}

function masteryBarColor(score: number): string {
  if (score >= 0.75) return "bg-success";
  if (score >= 0.5) return "bg-primary";
  if (score >= 0.3) return "bg-accent-gold";
  return "bg-error";
}

export function AnswerFeedbackCard({
  attempt,
  questionPrompt,
  onFollowUp,
}: AnswerFeedbackCardProps) {
  const { grading, mastery_snapshot, recommended_next_action } = attempt;
  const tone = statusTone(grading.grading_status, grading.is_correct);
  const statusCopy = STATUS_COPY[grading.grading_status];
  const actionLabel =
    ACTION_COPY[recommended_next_action] ?? recommended_next_action;

  return (
    <div
      className={`mt-3 rounded-lg border px-3 py-3 ${toneClasses(tone)}`}
      role="status"
      aria-live="polite"
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <StatusIcon
            status={grading.grading_status}
            isCorrect={grading.is_correct}
          />
          <div>
            <p className="text-sm font-medium">
              {grading.is_correct === true
                ? "答案正确"
                : grading.is_correct === false
                  ? "答案有误"
                  : statusCopy.label}
            </p>
            <p className="mt-0.5 text-[11px] opacity-80">{questionPrompt}</p>
          </div>
        </div>
        <Badge variant="outline" className="shrink-0 text-[10px]">
          第 {attempt.attempt_number} 次作答
        </Badge>
      </div>

      {/* Score + source row */}
      {grading.grading_status === "graded" && (
        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          <span className="font-medium">得分：{formatPercent(grading.score)}</span>
          {grading.confidence != null && (
            <span className="opacity-70">
              置信度 {Math.round(grading.confidence * 100)}%
            </span>
          )}
          {grading.grading_source && (
            <span className="opacity-70">
              来源：{grading.grading_source}
            </span>
          )}
        </div>
      )}

      {/* Rubric feedback */}
      {grading.rubric_feedback && (
        <p className="mt-2 text-xs leading-relaxed opacity-90">
          {grading.rubric_feedback}
        </p>
      )}

      {/* Misconceptions */}
      {grading.misconception_codes.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {grading.misconception_codes.map((code) => (
            <Badge key={code} variant="secondary" className="text-[10px]">
              {code}
            </Badge>
          ))}
        </div>
      )}

      {/* Mastery snapshot */}
      {mastery_snapshot && (
        <div className="mt-3 rounded-md border border-border-subtle bg-surface/60 px-2.5 py-2">
          <div className="flex items-center justify-between text-[11px]">
            <span className="font-medium">掌握度</span>
            <span className="opacity-80">
              {formatMastery(mastery_snapshot.mastery_score)} · 置信{" "}
              {Math.round(mastery_snapshot.confidence * 100)}% · 证据{" "}
              {mastery_snapshot.evidence_count}
            </span>
          </div>
          <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-border-subtle">
            <div
              className={`h-full rounded-full transition-all ${masteryBarColor(
                mastery_snapshot.mastery_score,
              )}`}
              style={{
                width: `${Math.round(mastery_snapshot.mastery_score * 100)}%`,
              }}
            />
          </div>
        </div>
      )}

      {/* Needs human review notice */}
      {grading.needs_human_review && (
        <div className="mt-2 flex items-start gap-1.5 rounded-md bg-accent-gold-surface/80 px-2 py-1.5 text-[11px] text-accent-gold">
          <UserCheck className="mt-0.5 h-3 w-3 shrink-0" />
          <span>本题需要人工复核，当前结果暂不计入掌握度。</span>
        </div>
      )}

      {/* Recommended next action */}
      <div className="mt-3 flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 text-xs">
          <Sparkles className="h-3 w-3 opacity-70" />
          <span className="opacity-80">下一步建议：</span>
          <span className="font-medium">{actionLabel}</span>
        </div>
        {onFollowUp && (
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-7 text-[11px]"
            onClick={() => onFollowUp(recommended_next_action)}
          >
            执行
          </Button>
        )}
      </div>
    </div>
  );
}
