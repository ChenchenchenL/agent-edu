import { useNavigate, Link } from "react-router-dom";
import {
  ClipboardList,
  Loader2,
  Play,
  Calendar,
  Clock,
  BookOpen,
  Target,
  LinkIcon,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useGoalTasks, useExecuteTask } from "@/hooks/use-tasks";
import { useBindGoal, useGoalsForSelect } from "@/hooks/use-sessions";
import { useLearnerProfile } from "@/hooks/use-goals";
import {
  taskStatusLabel,
  taskTypeLabel,
  difficultyLabel,
} from "@/pages/learning/lib/labels";
import type { DailyTask } from "@/types/task";

interface TaskPanelProps {
  sessionId: string;
  goalId: string | null;
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
    case "review":
    case "due":
      return "secondary";
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
        <Badge variant={taskStatusVariant(task.status)} className="shrink-0 text-[10px]">
          {taskStatusLabel(task.status)}
        </Badge>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-text-secondary">
        <span className="inline-flex items-center gap-1">
          <BookOpen className="h-3 w-3" />
          {taskTypeLabel(task.task_type)}
        </span>
        {task.topic_focus && (
          <span className="truncate">{task.topic_focus}</span>
        )}
        {task.difficulty && (
          <span>{difficultyLabel(task.difficulty)}</span>
        )}
        <span className="inline-flex items-center gap-1">
          <Clock className="h-3 w-3" />
          {task.estimated_minutes} 分钟
        </span>
        <span className="inline-flex items-center gap-1">
          <Calendar className="h-3 w-3" />
          {new Date(task.due_on).toLocaleDateString("zh-CN", {
            month: "short",
            day: "numeric",
          })}
        </span>
      </div>

      {isExecutable && (
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
              启动中…
            </>
          ) : (
            <>
              <Play className="h-3.5 w-3.5" />
              开始学习
            </>
          )}
        </Button>
      )}

      {executeTask.error && (
        <p className="mt-2 text-xs text-error">{executeTask.error.message}</p>
      )}
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

export function TaskPanel({ sessionId, goalId }: TaskPanelProps) {
  const { data: tasks, isLoading, error } = useGoalTasks(goalId);
  const bindGoal = useBindGoal(sessionId);
  const { data: profile } = useLearnerProfile();
  const { data: goals } = useGoalsForSelect(profile?.id ?? null);

  function handleBindGoal(newGoalId: string) {
    bindGoal.mutate(newGoalId);
  }

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-border-subtle px-4 py-3">
        <div className="flex items-center gap-2">
          <ClipboardList className="h-4 w-4 text-primary" />
          <h2 className="font-medium text-text-primary">学习任务</h2>
        </div>
        <p className="mt-1 text-xs text-text-secondary">
          查看今日任务、复习计划，开始学习
        </p>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-4">
        {isLoading ? (
          <div className="flex justify-center py-8">
            <Loader2 className="h-4 w-4 animate-spin text-primary" />
          </div>
        ) : error ? (
          <div className="rounded-lg bg-error/5 px-3 py-2.5 text-xs text-error">
            加载任务失败：{error.message}
          </div>
        ) : !goalId ? (
          <div className="space-y-4 py-4">
            <div className="rounded-lg border border-dashed border-border bg-surface/60 px-3 py-4 text-center">
              <Target className="mx-auto h-5 w-5 text-text-secondary" />
              <p className="mt-2 text-sm font-medium text-text-primary">
                未关联学习目标
              </p>
              <p className="mt-1 text-xs text-text-secondary">
                关联目标后可查看学习任务和复习计划
              </p>
            </div>

            {goals && goals.length > 0 ? (
              <div className="space-y-2">
                <p className="text-[11px] font-medium tracking-wide text-text-secondary uppercase">
                  选择要关联的目标
                </p>
                {goals.map((goal) => (
                  <button
                    key={goal.id}
                    type="button"
                    onClick={() => handleBindGoal(goal.id)}
                    disabled={bindGoal.isPending}
                    className="w-full rounded-lg border border-border-subtle bg-surface px-3 py-2.5 text-left transition-colors hover:border-primary/20 disabled:opacity-50"
                  >
                    <p className="truncate text-sm font-medium text-text-primary">
                      {goal.title}
                    </p>
                    <p className="mt-0.5 text-xs text-text-secondary">
                      {goal.subject} · {goal.weekly_study_minutes} 分钟/周
                    </p>
                  </button>
                ))}
              </div>
            ) : (
              <div className="text-center">
                <p className="text-xs text-text-secondary">
                  还没有学习目标
                </p>
                <Link
                  to="/goals"
                  className="mt-2 inline-flex items-center gap-1 text-xs text-primary hover:underline"
                >
                  <LinkIcon className="h-3 w-3" />
                  去创建目标
                </Link>
              </div>
            )}

            {bindGoal.error && (
              <p className="text-xs text-error">{bindGoal.error.message}</p>
            )}
          </div>
        ) : !tasks || tasks.length === 0 ? (
          <div className="py-8 text-center text-xs text-text-secondary">
            暂无任务
          </div>
        ) : (
          <div className="space-y-5">
            <TaskGroup
              title="今日任务"
              tasks={tasks.filter(
                (t) =>
                  t.status === "pending" ||
                  t.status === "in_progress" ||
                  t.status === "due",
              )}
            />
            <TaskGroup
              title="待复习"
              tasks={tasks.filter((t) => t.status === "review")}
            />
            <TaskGroup
              title="已完成"
              tasks={tasks.filter((t) => t.status === "completed")}
            />
            <TaskGroup
              title="其他"
              tasks={tasks.filter(
                (t) =>
                  !["pending", "in_progress", "due", "review", "completed"].includes(t.status),
              )}
            />
          </div>
        )}
      </div>
    </div>
  );
}
