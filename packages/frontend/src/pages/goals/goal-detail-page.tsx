import { useEffect } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import {
  Loader2,
  ArrowLeft,
  Calendar,
  Clock,
  Target,
  Compass,
  Play,
  BookOpen,
  Sparkles,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import {
  useGoal,
  useGoalPlans,
  useGoalTasks,
  useMaterializeToday,
  useGeneratePlan,
} from "@/hooks/use-goals";
import { useExecuteTask } from "@/hooks/use-tasks";
import {
  taskStatusLabel,
  taskTypeLabel,
  difficultyLabel,
} from "@/pages/learning/lib/labels";
import type { DailyTask } from "@/types/task";
import type { StudyPlanSummary } from "@/types/goal";

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

function taskStatusVariant(
  status: string,
): "default" | "secondary" | "outline" | "success" | "destructive" {
  switch (status) {
    case "completed":
      return "success";
    case "in_progress":
      return "default";
    case "failed":
      return "destructive";
    default:
      return "outline";
  }
}

function TaskCard({ task }: { task: DailyTask }) {
  const navigate = useNavigate();
  const executeTask = useExecuteTask();

  function handleExecute() {
    executeTask.mutate(task.id, {
      onSuccess: (result) => {
        navigate(`/sessions/${result.execution_session_id}`);
      },
    });
  }

  const isExecutable = task.status === "pending" || task.status === "due";

  return (
    <div className="notebook-margin rounded-lg border border-border-subtle bg-surface p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium leading-snug text-text-primary">
            {task.title}
          </p>
          <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-text-secondary">
            {task.instructions}
          </p>
        </div>
        <Badge
          variant={taskStatusVariant(task.status)}
          className="shrink-0 text-[10px]"
        >
          {taskStatusLabel(task.status)}
        </Badge>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-text-secondary">
        <span className="inline-flex items-center gap-1">
          <BookOpen className="h-3 w-3" />
          {taskTypeLabel(task.task_type)}
        </span>
        {task.topic_focus && <span className="truncate">{task.topic_focus}</span>}
        {task.difficulty && <span>{difficultyLabel(task.difficulty)}</span>}
        <span className="inline-flex items-center gap-1">
          <Clock className="h-3 w-3" />
          {task.estimated_minutes} 分钟
        </span>
        <span className="inline-flex items-center gap-1">
          <Calendar className="h-3 w-3" />
          {formatDate(task.due_on)}
        </span>
      </div>

      {task.execution_session_id ? (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="mt-3 w-full"
          onClick={() => navigate(`/sessions/${task.execution_session_id}`)}
        >
          <BookOpen className="h-3.5 w-3.5" />
          继续学习
        </Button>
      ) : isExecutable ? (
        <Button
          type="button"
          size="sm"
          className="mt-3 w-full"
          disabled={executeTask.isPending}
          onClick={handleExecute}
        >
          {executeTask.isPending ? (
            <>
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              启动中...
            </>
          ) : (
            <>
              <Play className="h-3.5 w-3.5" />
              开始学习
            </>
          )}
        </Button>
      ) : null}

      {executeTask.error && (
        <p className="mt-2 text-xs text-error">{executeTask.error.message}</p>
      )}
    </div>
  );
}

export function GoalDetailPage() {
  const { id: goalId } = useParams<{ id: string }>();
  const { data: goal, isLoading: goalLoading } = useGoal(goalId ?? "");
  const { data: plans, isLoading: plansLoading } = useGoalPlans(goalId ?? "");
  const { data: tasks, isLoading: tasksLoading, refetch: refetchTasks } = useGoalTasks(goalId ?? "");
  const materializeToday = useMaterializeToday(goalId ?? "");
  const generatePlan = useGeneratePlan();

  useEffect(() => {
    if (!goalId) return;
    materializeToday.mutate();
  }, [goalId]);

  if (goalLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="h-5 w-5 animate-spin text-primary" />
      </div>
    );
  }

  if (!goal) {
    return (
      <div className="fade-in flex flex-col items-center gap-4 py-24">
        <p className="font-medium text-text-primary">目标不存在</p>
        <p className="text-sm text-text-secondary">
          该目标可能已被删除或链接无效
        </p>
        <Link to="/goals">
          <Button variant="outline">返回目标列表</Button>
        </Link>
      </div>
    );
  }

  const activePlan = plans?.[0] ?? null;
  const taskList = tasks ?? [];
  const todayStr = new Date().toISOString().slice(0, 10);

  const todayTasks = taskList.filter(
    (t) =>
      t.due_on === todayStr &&
      (t.status === "pending" || t.status === "in_progress" || t.status === "due"),
  );
  const futureTasks = taskList.filter(
    (t) =>
      t.due_on > todayStr &&
      (t.status === "pending" || t.status === "in_progress" || t.status === "due"),
  );
  const reviewTasks = taskList.filter((t) => t.status === "review");
  const completedTasks = taskList.filter((t) => t.status === "completed");

  const futureTasksByDate = futureTasks.reduce<Record<string, typeof futureTasks>>((acc, task) => {
    const date = task.due_on;
    if (!acc[date]) acc[date] = [];
    acc[date].push(task);
    return acc;
  }, {});
  const futureDates = Object.keys(futureTasksByDate).sort();

  function handleGeneratePlan() {
    if (!goalId) return;
    generatePlan.mutate(goalId, {
      onSuccess: () => {
        refetchTasks();
      },
    });
  }

  return (
    <div className="fade-in">
      <div className="mb-6">
        <Link
          to="/goals"
          className="mb-4 inline-flex items-center gap-1.5 text-sm text-text-secondary no-underline hover:text-text-primary"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          返回目标列表
        </Link>

        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-semibold text-text-primary">
                {goal.title}
              </h1>
              <Badge variant={statusVariant(goal.status)}>
                {statusLabel(goal.status)}
              </Badge>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-text-secondary">
              <span className="inline-flex items-center gap-1.5">
                <Compass className="h-4 w-4 text-accent-gold" />
                {goal.subject}
              </span>
              <span className="inline-flex items-center gap-1.5">
                <Calendar className="h-4 w-4" />
                截止 {formatDate(goal.deadline_date)}
              </span>
              <span className="inline-flex items-center gap-1.5">
                <Clock className="h-4 w-4" />
                {goal.weekly_study_minutes} 分钟/周
              </span>
            </div>
            {goal.target_outcome && (
              <p className="mt-3 text-sm leading-relaxed text-text-secondary">
                <span className="font-medium text-text-primary">期望成果：</span>
                {goal.target_outcome}
              </p>
            )}
          </div>
        </div>
      </div>

      {/* Plan Section */}
      <section className="mb-8">
        <h2 className="mb-3 flex items-center gap-2 text-lg font-semibold text-text-primary">
          <Sparkles className="h-5 w-5 text-accent-gold" />
          学习计划
        </h2>

        {plansLoading ? (
          <div className="flex justify-center py-6">
            <Loader2 className="h-5 w-5 animate-spin text-primary" />
          </div>
        ) : !activePlan ? (
          <Card className="border-dashed border-border bg-surface/60 shadow-none">
            <CardContent className="flex flex-col items-center gap-4 py-10">
              <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary-surface">
                <Sparkles className="h-6 w-6 text-primary" />
              </div>
              <div className="text-center">
                <p className="font-medium text-text-primary">尚未生成学习计划</p>
                <p className="mt-1 text-sm text-text-secondary">
                  AI 将根据你的目标和时间自动生成学习计划
                </p>
              </div>
              <Button
                onClick={handleGeneratePlan}
                disabled={generatePlan.isPending}
              >
                {generatePlan.isPending ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    AI 正在规划中...
                  </>
                ) : (
                  <>
                    <Sparkles className="h-4 w-4" />
                    生成学习计划
                  </>
                )}
              </Button>
              {generatePlan.error && (
                <p className="text-sm text-error">
                  生成失败：{generatePlan.error.message}
                </p>
              )}
            </CardContent>
          </Card>
        ) : (
          <PlanStages plan={activePlan} />
        )}
      </section>

      {/* Tasks Section */}
      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-lg font-semibold text-text-primary">
            <Target className="h-5 w-5 text-primary" />
            任务列表
          </h2>
          {materializeToday.isPending && (
            <span className="flex items-center gap-1.5 text-xs text-text-secondary">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              同步中...
            </span>
          )}
        </div>

        {tasksLoading ? (
          <div className="flex justify-center py-6">
            <Loader2 className="h-5 w-5 animate-spin text-primary" />
          </div>
        ) : taskList.length === 0 ? (
          <div className="py-8 text-center text-sm text-text-secondary">
            暂无任务。生成学习计划后，系统将自动安排每日任务。
          </div>
        ) : (
          <div className="space-y-6">
            {todayTasks.length > 0 && (
              <TaskGroup title="今日任务" tasks={todayTasks} />
            )}
            {futureDates.map((date) => (
              <TaskGroup
                key={date}
                title={formatDate(date)}
                tasks={futureTasksByDate[date]}
              />
            ))}
            {reviewTasks.length > 0 && (
              <TaskGroup title="待复习" tasks={reviewTasks} />
            )}
            {completedTasks.length > 0 && (
              <TaskGroup title="已完成" tasks={completedTasks} />
            )}
          </div>
        )}
      </section>
    </div>
  );
}

function PlanStages({ plan }: { plan: StudyPlanSummary }) {
  return (
    <div className="space-y-3">
      {plan.plan_summary && (
        <p className="rounded-lg border border-border-subtle bg-surface px-4 py-3 text-sm leading-relaxed text-text-secondary">
          {plan.plan_summary}
        </p>
      )}
      <div className="space-y-2">
        {plan.stages
          .sort((a, b) => a.position - b.position)
          .map((stage) => (
            <div
              key={stage.id}
              className="notebook-margin rounded-lg border border-border-subtle bg-surface p-4"
            >
              <div className="flex items-start gap-3">
                <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary-surface text-xs font-bold text-primary">
                  {stage.position}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="font-medium text-text-primary">{stage.title}</p>
                  <p className="mt-1 text-sm text-text-secondary">
                    {stage.objective}
                  </p>
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    {stage.focus_topics.map((topic) => (
                      <Badge key={topic} variant="outline" className="text-[10px]">
                        {topic}
                      </Badge>
                    ))}
                    <span className="ml-auto text-[11px] text-text-secondary">
                      {formatDate(stage.start_date)} — {formatDate(stage.end_date)}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          ))}
      </div>
    </div>
  );
}

function TaskGroup({ title, tasks }: { title: string; tasks: DailyTask[] }) {
  if (tasks.length === 0) return null;

  return (
    <div className="space-y-2">
      <p className="text-[11px] font-medium tracking-wide text-text-secondary uppercase">
        {title}
      </p>
      <div className="space-y-2">
        {tasks.map((task) => (
          <TaskCard key={task.id} task={task} />
        ))}
      </div>
    </div>
  );
}
