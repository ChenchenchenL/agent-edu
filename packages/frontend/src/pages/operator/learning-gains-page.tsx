import { useMemo } from "react";
import {
  Sparkles,
  Loader2,
  AlertCircle,
  Inbox,
  TrendingUp,
  TrendingDown,
  Minus,
  Users,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { useLearningGainDashboard } from "@/hooks/use-operator-quiz-observability";
import type { LearningGainRecord } from "@/types/quiz-observability";

function gainColor(gain: number): string {
  if (gain >= 0.15) return "text-success";
  if (gain >= 0.05) return "text-primary";
  if (gain >= -0.05) return "text-accent-gold";
  return "text-error";
}

function gainBarColor(gain: number): string {
  if (gain >= 0.15) return "bg-success";
  if (gain >= 0.05) return "bg-primary";
  if (gain >= -0.05) return "bg-accent-gold";
  return "bg-error";
}

function gainLabel(gain: number): string {
  const signed = gain >= 0 ? `+${(gain * 100).toFixed(1)}` : `${(gain * 100).toFixed(1)}`;
  return `${signed}%`;
}

function GainIcon({ gain }: { gain: number }) {
  if (gain >= 0.05) {
    return <TrendingUp className="h-3.5 w-3.5 text-success" />;
  }
  if (gain <= -0.05) {
    return <TrendingDown className="h-3.5 w-3.5 text-error" />;
  }
  return <Minus className="h-3.5 w-3.5 text-accent-gold" />;
}

function SkillCard({ record }: { record: LearningGainRecord }) {
  return (
    <div className="group relative rounded-md border border-border bg-surface p-4 hover:border-primary/30 transition-colors">
      <div
        className={`absolute left-0 top-0 bottom-0 w-1 rounded-l-md ${gainBarColor(
          record.average_learning_gain,
        )}`}
      />
      <div className="pl-2">
        <div className="flex items-start justify-between gap-2">
          <h3 className="font-mono text-sm font-medium text-text-primary truncate">
            {record.skill_name}
          </h3>
          <GainIcon gain={record.average_learning_gain} />
        </div>

        <div className="mt-3 flex items-baseline gap-2">
          <span
            className={`font-mono text-3xl font-semibold tabular-nums ${gainColor(
              record.average_learning_gain,
            )}`}
          >
            {gainLabel(record.average_learning_gain)}
          </span>
          <span className="text-[11px] text-text-secondary uppercase tracking-wider">
            平均增益
          </span>
        </div>

        <div className="mt-3 flex items-center justify-between border-t border-border-subtle pt-2">
          <div className="flex items-center gap-1.5 text-[11px] text-text-secondary">
            <Users className="h-3 w-3" />
            <span className="font-mono tabular-nums">{record.sample_size}</span>
            <span>样本</span>
          </div>
          <Badge
            variant="outline"
            className="text-[10px] font-mono"
          >
            n={record.sample_size}
          </Badge>
        </div>
      </div>
    </div>
  );
}

function SummaryStrip({
  positiveCount,
  neutralCount,
  negativeCount,
  overallGain,
}: {
  positiveCount: number;
  neutralCount: number;
  negativeCount: number;
  overallGain: number;
}) {
  return (
    <div className="grid gap-3 md:grid-cols-4 mb-5">
      <div className="rounded-md border border-border bg-surface p-4">
        <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-text-secondary">
          <TrendingUp className="h-3.5 w-3.5 text-success" />
          正向增益
        </div>
        <div className="mt-3 flex items-baseline gap-2">
          <span className="font-mono text-3xl font-semibold tabular-nums text-success">
            {positiveCount}
          </span>
          <span className="text-xs text-text-secondary">技能</span>
        </div>
      </div>
      <div className="rounded-md border border-border bg-surface p-4">
        <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-text-secondary">
          <Minus className="h-3.5 w-3.5 text-accent-gold" />
          平稳
        </div>
        <div className="mt-3 flex items-baseline gap-2">
          <span className="font-mono text-3xl font-semibold tabular-nums text-accent-gold">
            {neutralCount}
          </span>
          <span className="text-xs text-text-secondary">技能</span>
        </div>
      </div>
      <div className="rounded-md border border-border bg-surface p-4">
        <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-text-secondary">
          <TrendingDown className="h-3.5 w-3.5 text-error" />
          负向增益
        </div>
        <div className="mt-3 flex items-baseline gap-2">
          <span className="font-mono text-3xl font-semibold tabular-nums text-error">
            {negativeCount}
          </span>
          <span className="text-xs text-text-secondary">技能</span>
        </div>
      </div>
      <div className="rounded-md border border-border bg-surface p-4">
        <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-text-secondary">
          <Sparkles className="h-3.5 w-3.5 text-primary" />
          综合增益
        </div>
        <div className="mt-3 flex items-baseline gap-2">
          <span
            className={`font-mono text-3xl font-semibold tabular-nums ${gainColor(
              overallGain,
            )}`}
          >
            {gainLabel(overallGain)}
          </span>
        </div>
      </div>
    </div>
  );
}

export function LearningGainsPage() {
  const { data, isLoading, error } = useLearningGainDashboard(2000);

  const records = data?.learning_gains ?? [];

  const { positiveCount, neutralCount, negativeCount, overallGain } =
    useMemo(() => {
      let positive = 0;
      let neutral = 0;
      let negative = 0;
      let totalGain = 0;
      let totalSamples = 0;
      for (const r of records) {
        if (r.average_learning_gain >= 0.05) positive++;
        else if (r.average_learning_gain <= -0.05) negative++;
        else neutral++;
        totalGain += r.average_learning_gain * r.sample_size;
        totalSamples += r.sample_size;
      }
      return {
        positiveCount: positive,
        neutralCount: neutral,
        negativeCount: negative,
        overallGain: totalSamples > 0 ? totalGain / totalSamples : 0,
      };
    }, [records]);

  const sorted = useMemo(
    () => [...records].sort((a, b) => b.average_learning_gain - a.average_learning_gain),
    [records],
  );

  return (
    <div className="fade-in">
      {/* Header */}
      <div className="flex items-end justify-between border-b border-border pb-4 mb-5">
        <div>
          <div className="flex items-center gap-2 text-xs font-mono uppercase tracking-[0.2em] text-text-secondary mb-2">
            <span>§ 03</span>
            <span className="h-px w-6 bg-border" />
            <span>学习增益</span>
          </div>
          <h1 className="font-serif text-2xl font-semibold text-text-primary tracking-tight">
            技能学习增益看板
          </h1>
          <p className="mt-1 text-sm text-text-secondary">
            每个技能带来的平均掌握度变化
          </p>
        </div>
        <div className="flex items-baseline gap-3">
          <span className="font-mono text-3xl font-semibold tabular-nums text-text-primary">
            {records.length}
          </span>
          <span className="text-xs text-text-secondary uppercase tracking-wider">
            技能
          </span>
        </div>
      </div>

      {/* Summary strip */}
      <SummaryStrip
        positiveCount={positiveCount}
        neutralCount={neutralCount}
        negativeCount={negativeCount}
        overallGain={overallGain}
      />

      {/* Skill grid */}
      <div className="rounded-md border border-border bg-surface">
        <div className="flex items-center justify-between border-b border-border-subtle px-4 py-3">
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-primary" />
            <h2 className="font-serif text-base font-semibold text-text-primary">
              技能明细
            </h2>
          </div>
          <span className="font-mono text-[11px] text-text-secondary tabular-nums">
            按增益降序
          </span>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center gap-2 py-16 text-sm text-text-secondary">
            <Loader2 className="h-4 w-4 animate-spin text-primary" />
            加载学习增益...
          </div>
        ) : error ? (
          <div className="flex items-start gap-2 p-6 text-sm text-error">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>加载失败：{error.message}</span>
          </div>
        ) : sorted.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-2 py-16 text-center">
            <Inbox className="h-6 w-6 text-text-secondary" />
            <p className="text-sm text-text-primary">暂无学习增益数据</p>
            <p className="text-xs text-text-secondary">
              技能被使用并产生掌握度变化后，会出现在这里
            </p>
          </div>
        ) : (
          <div className="grid gap-3 p-4 md:grid-cols-2 lg:grid-cols-3">
            {sorted.map((record) => (
              <SkillCard key={record.skill_name} record={record} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
