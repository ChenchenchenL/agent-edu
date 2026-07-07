import { useMemo, useState } from "react";
import {
  Loader2,
  AlertCircle,
  Inbox,
  ChevronLeft,
  ChevronRight,
  Filter,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  useOperatorAttempts,
  useOperatorGradingQueue,
} from "@/hooks/use-operator-quiz-observability";
import type { OperatorAttemptRecord } from "@/types/quiz-observability";

type FilterMode = "all" | "needs_review" | "graded" | "rejected";

const PAGE_SIZE = 25;

function scoreColor(score: number | null): string {
  if (score == null) return "text-text-secondary";
  if (score >= 0.8) return "text-success";
  if (score >= 0.5) return "text-accent-gold";
  return "text-error";
}

function scoreBarColor(score: number | null): string {
  if (score == null) return "bg-border-subtle";
  if (score >= 0.8) return "bg-success";
  if (score >= 0.5) return "bg-accent-gold";
  return "bg-error";
}

function formatTime(value: string): string {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(d);
}

function formatScore(score: number | null): string {
  if (score == null) return "—";
  return `${Math.round(score * 100)}`;
}

function CorrectnessBadge({ isCorrect }: { isCorrect: boolean | null }) {
  if (isCorrect === true) {
    return (
      <Badge variant="outline" className="text-[10px] border-success/30 text-success">
        正确
      </Badge>
    );
  }
  if (isCorrect === false) {
    return (
      <Badge variant="outline" className="text-[10px] border-error/30 text-error">
        错误
      </Badge>
    );
  }
  return (
    <Badge variant="outline" className="text-[10px]">
      未判
    </Badge>
  );
}

function AttemptRow({ attempt }: { attempt: OperatorAttemptRecord }) {
  const hasMisconceptions = attempt.misconception_codes.length > 0;
  return (
    <tr className="border-b border-border-subtle last:border-b-0 hover:bg-muted/40 transition-colors">
      <td className="py-2.5 pr-3 align-top">
        <span className="font-mono text-[11px] text-text-secondary tabular-nums">
          {formatTime(attempt.created_at)}
        </span>
      </td>
      <td className="py-2.5 pr-3 align-top">
        <span className="font-mono text-[11px] text-text-secondary truncate block max-w-[90px]">
          {attempt.session_id.slice(0, 8)}
        </span>
      </td>
      <td className="py-2.5 pr-3 align-top">
        <span className="font-mono text-[11px] text-text-secondary truncate block max-w-[90px]">
          {attempt.question_id.slice(0, 8)}
        </span>
      </td>
      <td className="py-2.5 pr-3 align-top">
        <div className="flex items-center gap-2 min-w-[110px]">
          <span
            className={`font-mono text-sm font-semibold tabular-nums ${scoreColor(
              attempt.score,
            )}`}
          >
            {formatScore(attempt.score)}
          </span>
          <div className="flex-1 h-1 rounded-full bg-border-subtle overflow-hidden">
            <div
              className={`h-full rounded-full ${scoreBarColor(attempt.score)}`}
              style={{
                width:
                  attempt.score != null
                    ? `${Math.max(2, Math.round(attempt.score * 100))}%`
                    : "0%",
              }}
            />
          </div>
        </div>
      </td>
      <td className="py-2.5 pr-3 align-top">
        <CorrectnessBadge isCorrect={attempt.is_correct} />
      </td>
      <td className="py-2.5 align-top">
        {hasMisconceptions ? (
          <div className="flex flex-wrap gap-1">
            {attempt.misconception_codes.map((code) => (
              <Badge
                key={code}
                variant="secondary"
                className="text-[10px] font-mono"
              >
                {code}
              </Badge>
            ))}
          </div>
        ) : (
          <span className="text-[11px] text-text-secondary">—</span>
        )}
      </td>
    </tr>
  );
}

function FilterTabs({
  value,
  onChange,
  counts,
}: {
  value: FilterMode;
  onChange: (mode: FilterMode) => void;
  counts: Record<FilterMode, number>;
}) {
  const tabs: { key: FilterMode; label: string }[] = [
    { key: "all", label: "全部" },
    { key: "needs_review", label: "待复核" },
    { key: "graded", label: "已批改" },
    { key: "rejected", label: "已拒绝" },
  ];
  return (
    <div className="flex items-center gap-1 rounded-md border border-border-subtle bg-surface p-0.5">
      {tabs.map((tab) => {
        const active = value === tab.key;
        return (
          <button
            key={tab.key}
            type="button"
            onClick={() => onChange(tab.key)}
            className={`flex items-center gap-1.5 rounded-[3px] px-2.5 py-1 text-xs font-medium transition-colors ${
              active
                ? "bg-primary text-white"
                : "text-text-secondary hover:text-text-primary hover:bg-muted/60"
            }`}
          >
            {tab.label}
            <span
              className={`font-mono text-[10px] tabular-nums ${
                active ? "text-white/80" : "text-text-secondary"
              }`}
            >
              {counts[tab.key]}
            </span>
          </button>
        );
      })}
    </div>
  );
}

export function QuizAttemptsPage() {
  const [filter, setFilter] = useState<FilterMode>("all");
  const [page, setPage] = useState(0);

  const {
    data: attemptsData,
    isLoading,
    error,
  } = useOperatorAttempts({ limit: 200, offset: 0 });

  const { data: gradingData } = useOperatorGradingQueue({ limit: 200 });

  const allAttempts = attemptsData?.attempts ?? [];
  const totalCount = attemptsData?.total_count ?? 0;
  const reviewCount = gradingData?.queue.length ?? 0;

  const filtered = useMemo(() => {
    if (filter === "all") return allAttempts;
    if (filter === "needs_review") {
      return allAttempts.filter((a) => a.misconception_codes.length > 0 || a.is_correct === false);
    }
    // We don't have grading_status in the record; approximate by is_correct presence
    if (filter === "graded") {
      return allAttempts.filter((a) => a.score != null);
    }
    if (filter === "rejected") {
      return allAttempts.filter((a) => a.score == null && a.is_correct == null);
    }
    return allAttempts;
  }, [allAttempts, filter]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const pageItems = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  const counts: Record<FilterMode, number> = {
    all: allAttempts.length,
    needs_review: reviewCount,
    graded: allAttempts.filter((a) => a.score != null).length,
    rejected: allAttempts.filter((a) => a.score == null && a.is_correct == null).length,
  };

  return (
    <div className="fade-in">
      {/* Header */}
      <div className="flex items-end justify-between border-b border-border pb-4 mb-5">
        <div>
          <div className="flex items-center gap-2 text-xs font-mono uppercase tracking-[0.2em] text-text-secondary mb-2">
            <span>§ 01</span>
            <span className="h-px w-6 bg-border" />
            <span>答题记录</span>
          </div>
          <h1 className="font-serif text-2xl font-semibold text-text-primary tracking-tight">
            答题批改记录
          </h1>
          <p className="mt-1 text-sm text-text-secondary">
            全部答题提交、批改结果与误解代码
          </p>
        </div>
        <div className="flex items-baseline gap-3">
          <span className="font-mono text-3xl font-semibold tabular-nums text-text-primary">
            {totalCount}
          </span>
          <span className="text-xs text-text-secondary uppercase tracking-wider">
            总提交
          </span>
        </div>
      </div>

      {/* Toolbar */}
      <div className="flex items-center justify-between gap-3 mb-4">
        <div className="flex items-center gap-2">
          <Filter className="h-3.5 w-3.5 text-text-secondary" />
          <FilterTabs
            value={filter}
            onChange={(mode) => {
              setFilter(mode);
              setPage(0);
            }}
            counts={counts}
          />
        </div>
        <div className="font-mono text-[11px] text-text-secondary tabular-nums">
          显示 {pageItems.length} / {filtered.length}
        </div>
      </div>

      {/* Table */}
      <div className="rounded-md border border-border bg-surface">
        {isLoading ? (
          <div className="flex items-center justify-center gap-2 py-16 text-sm text-text-secondary">
            <Loader2 className="h-4 w-4 animate-spin text-primary" />
            加载答题记录...
          </div>
        ) : error ? (
          <div className="flex items-start gap-2 p-6 text-sm text-error">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>加载失败：{error.message}</span>
          </div>
        ) : allAttempts.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-2 py-16 text-center">
            <Inbox className="h-6 w-6 text-text-secondary" />
            <p className="text-sm text-text-primary">暂无答题记录</p>
            <p className="text-xs text-text-secondary">
              学员提交答题后，批改结果会出现在这里
            </p>
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-border bg-muted/40">
                    <th className="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wider text-text-secondary">
                      时间
                    </th>
                    <th className="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wider text-text-secondary">
                      会话
                    </th>
                    <th className="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wider text-text-secondary">
                      题目
                    </th>
                    <th className="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wider text-text-secondary">
                      得分
                    </th>
                    <th className="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wider text-text-secondary">
                      判定
                    </th>
                    <th className="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wider text-text-secondary">
                      误解代码
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {pageItems.map((attempt) => (
                    <AttemptRow key={attempt.id} attempt={attempt} />
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            {pageCount > 1 && (
              <div className="flex items-center justify-between border-t border-border-subtle px-3 py-2">
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={page === 0}
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                  className="text-xs"
                >
                  <ChevronLeft className="h-3.5 w-3.5 mr-1" />
                  上一页
                </Button>
                <span className="font-mono text-[11px] text-text-secondary tabular-nums">
                  第 {page + 1} / {pageCount} 页
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={page >= pageCount - 1}
                  onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
                  className="text-xs"
                >
                  下一页
                  <ChevronRight className="h-3.5 w-3.5 ml-1" />
                </Button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
