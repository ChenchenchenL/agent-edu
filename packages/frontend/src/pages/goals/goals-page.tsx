import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Plus,
  Compass,
  Calendar,
  Clock,
  Target,
  AlertCircle,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { GoalCreateForm } from "./goal-create-form";
import { useLearnerProfile, useGoals } from "@/hooks/use-goals";
import type { LearnerGoal } from "@/types/goal";

function statusVariant(
  status: string,
): "default" | "secondary" | "outline" | "success" {
  switch (status) {
    case "active":
      return "success";
    case "completed":
      return "secondary";
    case "paused":
      return "outline";
    default:
      return "outline";
  }
}

function statusLabel(status: string): string {
  switch (status) {
    case "active":
      return "进行中";
    case "completed":
      return "已完成";
    case "paused":
      return "已暂停";
    default:
      return status;
  }
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return dateStr;
  return d.toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function GoalsSkeleton() {
  return (
    <div className="space-y-3">
      {[1, 2, 3].map((i) => (
        <div
          key={i}
          className="h-[90px] animate-pulse rounded-lg border border-border-subtle bg-surface"
        />
      ))}
    </div>
  );
}

export function GoalsPage() {
  const navigate = useNavigate();
  const {
    data: profile,
    isLoading: profileLoading,
    error: profileError,
  } = useLearnerProfile();
  const {
    data: goals,
    isLoading: goalsLoading,
    error: goalsError,
  } = useGoals(profile?.id ?? null);
  const [showCreateForm, setShowCreateForm] = useState(false);

  if (profileLoading) {
    return (
      <div className="fade-in">
        <div className="mb-10">
          <div className="h-8 w-40 animate-pulse rounded bg-muted" />
          <div className="mt-3 h-4 w-64 animate-pulse rounded bg-muted" />
        </div>
        <GoalsSkeleton />
      </div>
    );
  }

  if (profileError) {
    return (
      <div className="fade-in flex flex-col items-center justify-center gap-4 py-24">
        <div className="flex h-14 w-14 items-center justify-center rounded-full bg-error/10">
          <AlertCircle className="h-6 w-6 text-error" />
        </div>
        <div className="text-center">
          <p className="font-medium text-text-primary">无法初始化学习档案</p>
          <p className="mt-1 text-sm text-text-secondary">
            请确认后端服务已启动，然后重试
          </p>
        </div>
        <Button variant="outline" onClick={() => window.location.reload()}>
          重试
        </Button>
      </div>
    );
  }

  const goalList = goals ?? [];
  const isLoading = goalsLoading;

  return (
    <div className="fade-in">
      <div className="mb-10 flex flex-col gap-6 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="mb-2 text-xs font-semibold tracking-widest text-accent-gold uppercase">
            学习路径
          </p>
          <h1 className="text-3xl font-semibold text-text-primary">
            学习目标
          </h1>
          <p className="mt-2 max-w-md text-[15px] leading-relaxed text-text-secondary">
            设定学习目标，AI 将为你生成个性化学习计划，并安排每日任务和复习。
          </p>
        </div>
        <Button
          onClick={() => setShowCreateForm(true)}
          size="lg"
          className="shrink-0 shadow-sm"
        >
          <Plus className="h-4 w-4" />
          新建目标
        </Button>
      </div>

      {showCreateForm && profile && (
        <div className="mb-8">
          <GoalCreateForm
            profileId={profile.id}
            onSuccess={(goalId) => {
              setShowCreateForm(false);
              navigate(`/goals/${goalId}`);
            }}
            onCancel={() => setShowCreateForm(false)}
          />
        </div>
      )}

      {isLoading ? (
        <GoalsSkeleton />
      ) : goalsError ? (
        <div className="rounded-lg border border-error/20 bg-error/5 px-4 py-3 text-sm text-error">
          加载目标列表失败：{goalsError.message}
        </div>
      ) : goalList.length === 0 ? (
        <Card className="border-dashed border-border bg-surface/60 shadow-none">
          <CardContent className="flex flex-col items-center gap-5 py-20">
            <div className="notebook-margin flex h-14 w-14 items-center justify-center rounded-xl bg-primary-surface">
              <Compass className="h-7 w-7 text-primary" />
            </div>
            <div className="max-w-sm text-center">
              <p className="font-serif text-lg font-semibold text-text-primary">
                开始你的学习之旅
              </p>
              <p className="mt-2 text-sm leading-relaxed text-text-secondary">
                创建一个学习目标，AI
                将根据你的时间和基础，自动生成个性化学习计划。
              </p>
            </div>
            <Button
              variant="outline"
              onClick={() => setShowCreateForm(true)}
              className="mt-1"
            >
              <Plus className="h-4 w-4" />
              创建第一个目标
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2.5">
          {goalList.map((goal: LearnerGoal) => (
            <Card
              key={goal.id}
              className="notebook-margin group cursor-pointer border-border-subtle shadow-none transition-all hover:border-primary/20 hover:shadow-md"
              onClick={() => navigate(`/goals/${goal.id}`)}
            >
              <CardContent className="flex items-center justify-between gap-4 py-4 pl-5">
                <div className="flex min-w-0 items-center gap-4">
                  <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-primary-surface transition-colors group-hover:bg-primary/10">
                    <Target className="h-5 w-5 text-primary" />
                  </div>
                  <div className="min-w-0">
                    <h3 className="truncate font-medium text-text-primary">
                      {goal.title}
                    </h3>
                    <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-text-secondary">
                      <span className="inline-flex items-center gap-1">
                        <Compass className="h-3 w-3 text-accent-gold" />
                        {goal.subject}
                      </span>
                      <span className="inline-flex items-center gap-1">
                        <Calendar className="h-3 w-3" />
                        截止 {formatDate(goal.deadline_date)}
                      </span>
                      <span className="inline-flex items-center gap-1">
                        <Clock className="h-3 w-3" />
                        {goal.weekly_study_minutes} 分钟/周
                      </span>
                    </div>
                  </div>
                </div>
                <Badge
                  variant={statusVariant(goal.status)}
                  className="shrink-0"
                >
                  {statusLabel(goal.status)}
                </Badge>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
