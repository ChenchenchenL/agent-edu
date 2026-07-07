import {
  Shield,
  AlertTriangle,
  ClipboardList,
  GitPullRequest,
  Sparkles,
  ScrollText,
  Loader2,
  CheckCircle2,
  XCircle,
  Clock,
  BarChart3,
  Target,
  TrendingUp,
} from "lucide-react";
import { useNavigate } from "react-router-dom";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  useGuardrailsStatus,
  useReflectionReviewQueue,
  useProposalReviewQueue,
  useCuratorRecommendations,
  useAuditEvents,
} from "@/hooks/use-operator";
import {
  useOperatorAttempts,
  useMisconceptionTrend,
  useLearningGainDashboard,
} from "@/hooks/use-operator-quiz-observability";
import type { AuditEvent } from "@/types/operator";

function StatusDot({ status }: { status: "ok" | "warn" | "error" }) {
  const colors = {
    ok: "bg-success",
    warn: "bg-accent-gold",
    error: "bg-error",
  };
  return (
    <span className={`inline-block h-2 w-2 rounded-full ${colors[status]}`} />
  );
}

function GuardrailsCard() {
  const { data, isLoading, error } = useGuardrailsStatus();

  const llmGuardEnabled = data?.llm_call_guard && "enabled" in data.llm_call_guard
    ? data.llm_call_guard.enabled
    : false;
  const circuitBreakerEnabled = data?.circuit_breaker && "enabled" in data.circuit_breaker
    ? data.circuit_breaker.enabled
    : false;

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Shield className="h-4 w-4 text-primary" />
          系统防护
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {isLoading ? (
          <Loader2 className="h-4 w-4 animate-spin text-primary" />
        ) : error ? (
          <p className="text-xs text-error">无法加载防护状态</p>
        ) : (
          <>
            <div className="flex items-center justify-between">
              <span className="text-sm text-text-primary">LLM 调用限制</span>
              <div className="flex items-center gap-2">
                <StatusDot status={llmGuardEnabled ? "ok" : "warn"} />
                <span className="text-xs text-text-secondary">
                  {llmGuardEnabled ? "已启用" : "未启用"}
                </span>
              </div>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-text-primary">熔断器</span>
              <div className="flex items-center gap-2">
                <StatusDot status={circuitBreakerEnabled ? "ok" : "warn"} />
                <span className="text-xs text-text-secondary">
                  {circuitBreakerEnabled ? "已启用" : "未启用"}
                </span>
              </div>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function ReviewQueuesCard() {
  const { data: reflections, isLoading: refLoading } = useReflectionReviewQueue(5);
  const { data: proposals, isLoading: propLoading } = useProposalReviewQueue(5);

  const reflectionCount = reflections?.total ?? 0;
  const proposalCount = proposals?.total ?? 0;
  const totalPending = reflectionCount + proposalCount;

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <AlertTriangle className="h-4 w-4 text-accent-gold" />
          待审核
          {totalPending > 0 && (
            <Badge variant="secondary" className="ml-auto text-[10px]">
              {totalPending}
            </Badge>
          )}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div>
          <div className="mb-2 flex items-center justify-between">
            <span className="flex items-center gap-1.5 text-sm text-text-primary">
              <ClipboardList className="h-3.5 w-3.5" />
              反思审核
            </span>
            {refLoading ? (
              <Loader2 className="h-3 w-3 animate-spin text-text-secondary" />
            ) : (
              <Badge variant={reflectionCount > 0 ? "default" : "outline"} className="text-[10px]">
                {reflectionCount}
              </Badge>
            )}
          </div>
          {reflections?.items && reflections.items.length > 0 && (
            <div className="space-y-1.5">
              {reflections.items.slice(0, 3).map((item) => (
                <div
                  key={item.reflection_id}
                  className="rounded-md bg-muted/50 px-2.5 py-1.5 text-xs"
                >
                  <p className="truncate text-text-primary">{item.summary}</p>
                  <div className="mt-0.5 flex items-center gap-2 text-[10px] text-text-secondary">
                    <span>{item.severity}</span>
                    <span>·</span>
                    <span>优先级 {item.priority_score.toFixed(2)}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="border-t border-border-subtle pt-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="flex items-center gap-1.5 text-sm text-text-primary">
              <GitPullRequest className="h-3.5 w-3.5" />
              提案审核
            </span>
            {propLoading ? (
              <Loader2 className="h-3 w-3 animate-spin text-text-secondary" />
            ) : (
              <Badge variant={proposalCount > 0 ? "default" : "outline"} className="text-[10px]">
                {proposalCount}
              </Badge>
            )}
          </div>
          {proposals?.items && proposals.items.length > 0 && (
            <div className="space-y-1.5">
              {proposals.items.slice(0, 3).map((item) => (
                <div
                  key={item.id}
                  className="rounded-md bg-muted/50 px-2.5 py-1.5 text-xs"
                >
                  <p className="truncate text-text-primary">{item.change_summary}</p>
                  <div className="mt-0.5 flex items-center gap-2 text-[10px] text-text-secondary">
                    <span>{item.risk_level}</span>
                    <span>·</span>
                    <span>{item.proposal_type}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function CuratorRecommendationsCard() {
  const { data: recommendations, isLoading, error } = useCuratorRecommendations(5);

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Sparkles className="h-4 w-4 text-primary" />
          Curator 建议
        </CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Loader2 className="h-4 w-4 animate-spin text-primary" />
        ) : error ? (
          <p className="text-xs text-error">加载失败</p>
        ) : !recommendations || recommendations.length === 0 ? (
          <p className="text-xs text-text-secondary">暂无待处理建议</p>
        ) : (
          <div className="space-y-2">
            {recommendations.slice(0, 5).map((rec) => (
              <div
                key={rec.id}
                className="rounded-md border border-border-subtle px-3 py-2"
              >
                <div className="flex items-center justify-between">
                  <p className="text-sm font-medium text-text-primary">
                    {rec.skill_name}
                  </p>
                  <Badge variant="outline" className="text-[10px]">
                    {rec.recommended_action}
                  </Badge>
                </div>
                <p className="mt-1 text-xs text-text-secondary">
                  {rec.reason_note}
                </p>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function auditEventIcon(eventType: string) {
  if (eventType.includes("success") || eventType.includes("completed")) {
    return <CheckCircle2 className="h-3.5 w-3.5 text-success" />;
  }
  if (eventType.includes("fail") || eventType.includes("error")) {
    return <XCircle className="h-3.5 w-3.5 text-error" />;
  }
  return <Clock className="h-3.5 w-3.5 text-text-secondary" />;
}

function AuditEventsCard() {
  const { data: events, isLoading, error } = useAuditEvents({ limit: 15 });

  return (
    <Card className="lg:col-span-2">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <ScrollText className="h-4 w-4 text-primary" />
          最近审计事件
        </CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <Loader2 className="h-4 w-4 animate-spin text-primary" />
        ) : error ? (
          <p className="text-xs text-error">加载审计事件失败</p>
        ) : !events || events.length === 0 ? (
          <p className="text-xs text-text-secondary">暂无审计事件</p>
        ) : (
          <div className="space-y-1">
            {events.slice(0, 10).map((event: AuditEvent) => (
              <div
                key={event.id}
                className="flex items-start gap-2 rounded-md px-2 py-1.5 text-xs hover:bg-muted/50"
              >
                {auditEventIcon(event.event_type)}
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium text-text-primary">
                    {event.event_type}
                  </p>
                  <div className="flex items-center gap-2 text-[10px] text-text-secondary">
                    <span>{event.resource_type}</span>
                    {event.resource_id && (
                      <>
                        <span>·</span>
                        <span className="truncate">{event.resource_id}</span>
                      </>
                    )}
                    <span>·</span>
                    <span>{event.actor}</span>
                  </div>
                </div>
                <span className="shrink-0 text-[10px] text-text-secondary">
                  {new Date(event.created_at).toLocaleTimeString("zh-CN", {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function QuizObservabilityCard() {
  const navigate = useNavigate();
  const { data: attemptsData } = useOperatorAttempts({ limit: 1 });
  const { data: misconceptionsData } = useMisconceptionTrend(1);
  const { data: gainsData } = useLearningGainDashboard(1);

  const attemptCount = attemptsData?.total_count ?? 0;
  const misconceptionCount = misconceptionsData?.trends.length ?? 0;
  const skillCount = gainsData?.learning_gains.length ?? 0;

  const tiles = [
    {
      label: "答题记录",
      value: attemptCount,
      hint: "总提交",
      icon: <ClipboardList className="h-4 w-4" />,
      to: "/operator/quiz/attempts",
      accent: "text-primary",
    },
    {
      label: "误解趋势",
      value: misconceptionCount,
      hint: "唯一代码",
      icon: <Target className="h-4 w-4" />,
      to: "/operator/quiz/misconceptions",
      accent: "text-accent-gold",
    },
    {
      label: "学习增益",
      value: skillCount,
      hint: "技能",
      icon: <TrendingUp className="h-4 w-4" />,
      to: "/operator/quiz/learning-gains",
      accent: "text-success",
    },
  ];

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <BarChart3 className="h-4 w-4 text-primary" />
          答题观测
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-3 gap-2">
          {tiles.map((tile) => (
            <button
              key={tile.label}
              type="button"
              onClick={() => navigate(tile.to)}
              className="group rounded-md border border-border-subtle bg-background p-3 text-left transition-colors hover:border-primary/30 hover:bg-primary-surface/40"
            >
              <div className={`mb-2 ${tile.accent}`}>{tile.icon}</div>
              <div className="font-mono text-xl font-semibold tabular-nums text-text-primary">
                {tile.value}
              </div>
              <div className="mt-0.5 text-[10px] uppercase tracking-wider text-text-secondary">
                {tile.label}
              </div>
              <div className="mt-1 text-[10px] text-text-secondary">
                {tile.hint}
              </div>
            </button>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

export function OperatorDashboardPage() {
  return (
    <div className="fade-in">
      <div className="mb-6">
        <h1 className="font-serif text-2xl font-bold text-text-primary">
          运营控制台
        </h1>
        <p className="mt-1 text-sm text-text-secondary">
          系统治理状态、审核队列与审计日志
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="lg:col-span-2">
          <QuizObservabilityCard />
        </div>
        <GuardrailsCard />
        <ReviewQueuesCard />
        <CuratorRecommendationsCard />
        <AuditEventsCard />
      </div>
    </div>
  );
}
