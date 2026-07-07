import { useMemo } from "react";
import {
  AlertTriangle,
  Loader2,
  AlertCircle,
  Inbox,
  TrendingUp,
  Hash,
  Target,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { useMisconceptionTrend } from "@/hooks/use-operator-quiz-observability";
import type { MisconceptionTrendRecord } from "@/types/quiz-observability";

function barColor(rank: number, total: number): string {
  // Top-ranked gets the signature deep teal; others fade to primary blue.
  if (total <= 1) return "bg-primary";
  const ratio = rank / (total - 1);
  if (ratio < 0.15) return "bg-primary";
  if (ratio < 0.5) return "bg-primary/75";
  return "bg-primary/45";
}

function StatTile({
  label,
  value,
  icon,
  hint,
}: {
  label: string;
  value: string | number;
  icon: React.ReactNode;
  hint?: string;
}) {
  return (
    <div className="rounded-md border border-border bg-surface p-4">
      <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-text-secondary">
        {icon}
        {label}
      </div>
      <div className="mt-3 flex items-baseline gap-2">
        <span className="font-mono text-3xl font-semibold tabular-nums text-text-primary">
          {value}
        </span>
        {hint && <span className="text-xs text-text-secondary">{hint}</span>}
      </div>
    </div>
  );
}

function TrendRow({
  record,
  rank,
  maxCount,
  total,
}: {
  record: MisconceptionTrendRecord;
  rank: number;
  maxCount: number;
  total: number;
}) {
  const widthPct =
    maxCount > 0 ? Math.max(2, (record.count / maxCount) * 100) : 0;
  const sharePct =
    total > 0 ? Math.round((record.count / total) * 100) : 0;

  return (
    <div className="group grid grid-cols-[2.5rem_1fr_auto] items-center gap-3 border-b border-border-subtle px-3 py-2.5 last:border-b-0 hover:bg-muted/40 transition-colors">
      <span className="font-mono text-[11px] text-text-secondary tabular-nums">
        {String(rank + 1).padStart(2, "0")}
      </span>
      <div className="min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className="font-mono text-sm font-medium text-text-primary truncate">
            {record.misconception_code}
          </span>
          <Badge variant="outline" className="text-[10px] font-mono shrink-0">
            {sharePct}%
          </Badge>
        </div>
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-border-subtle">
          <div
            className={`h-full rounded-full transition-all ${barColor(rank, total)}`}
            style={{ width: `${widthPct}%` }}
          />
        </div>
      </div>
      <span className="font-mono text-sm font-semibold tabular-nums text-text-primary">
        {record.count}
      </span>
    </div>
  );
}

export function MisconceptionsPage() {
  const { data, isLoading, error } = useMisconceptionTrend(2000);

  const trends = data?.trends ?? [];
  const sorted = useMemo(
    () => [...trends].sort((a, b) => b.count - a.count),
    [trends],
  );
  const totalOccurrences = sorted.reduce((acc, t) => acc + t.count, 0);
  const uniqueCount = sorted.length;
  const maxCount = sorted[0]?.count ?? 0;
  const topCode = sorted[0]?.misconception_code ?? null;

  return (
    <div className="fade-in">
      {/* Header */}
      <div className="flex items-end justify-between border-b border-border pb-4 mb-5">
        <div>
          <div className="flex items-center gap-2 text-xs font-mono uppercase tracking-[0.2em] text-text-secondary mb-2">
            <span>§ 02</span>
            <span className="h-px w-6 bg-border" />
            <span>误解趋势</span>
          </div>
          <h1 className="font-serif text-2xl font-semibold text-text-primary tracking-tight">
            误解代码趋势
          </h1>
          <p className="mt-1 text-sm text-text-secondary">
            批改过程中识别出的误解代码频次分布
          </p>
        </div>
        <div className="flex items-baseline gap-3">
          <span className="font-mono text-3xl font-semibold tabular-nums text-text-primary">
            {totalOccurrences}
          </span>
          <span className="text-xs text-text-secondary uppercase tracking-wider">
            总出现
          </span>
        </div>
      </div>

      {/* Stat tiles */}
      <div className="grid gap-3 md:grid-cols-3 mb-5">
        <StatTile
          label="唯一代码"
          value={uniqueCount}
          icon={<Hash className="h-3.5 w-3.5" />}
          hint="种"
        />
        <StatTile
          label="总出现"
          value={totalOccurrences}
          icon={<TrendingUp className="h-3.5 w-3.5" />}
          hint="次"
        />
        <StatTile
          label="最高频"
          value={topCode ?? "—"}
          icon={<Target className="h-3.5 w-3.5" />}
          hint={topCode ? `${maxCount} 次` : undefined}
        />
      </div>

      {/* Trend chart */}
      <div className="rounded-md border border-border bg-surface">
        <div className="flex items-center justify-between border-b border-border-subtle px-4 py-3">
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-primary" />
            <h2 className="font-serif text-base font-semibold text-text-primary">
              频次排行
            </h2>
          </div>
          <span className="font-mono text-[11px] text-text-secondary tabular-nums">
            {uniqueCount} 个代码
          </span>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center gap-2 py-16 text-sm text-text-secondary">
            <Loader2 className="h-4 w-4 animate-spin text-primary" />
            加载误解趋势...
          </div>
        ) : error ? (
          <div className="flex items-start gap-2 p-6 text-sm text-error">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>加载失败：{error.message}</span>
          </div>
        ) : sorted.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-2 py-16 text-center">
            <Inbox className="h-6 w-6 text-text-secondary" />
            <p className="text-sm text-text-primary">暂无误解数据</p>
            <p className="text-xs text-text-secondary">
              学员答题被识别出误解后，趋势会出现在这里
            </p>
          </div>
        ) : (
          <div className="divide-y divide-border-subtle">
            {sorted.map((record, index) => (
              <TrendRow
                key={record.misconception_code}
                record={record}
                rank={index}
                maxCount={maxCount}
                total={totalOccurrences}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
