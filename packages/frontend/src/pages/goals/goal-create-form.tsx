import { useState } from "react";
import { Calendar, Clock, Target, BookOpen, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useCreateGoal, useGeneratePlan } from "@/hooks/use-goals";
import type { CreateGoalRequest } from "@/types/goal";

interface GoalCreateFormProps {
  profileId: string;
  onSuccess: (goalId: string) => void;
  onCancel: () => void;
}

function defaultDeadlineDate(): string {
  const d = new Date();
  d.setDate(d.getDate() + 30);
  return d.toISOString().slice(0, 10);
}

export function GoalCreateForm({
  profileId,
  onSuccess,
  onCancel,
}: GoalCreateFormProps) {
  const [subject, setSubject] = useState("");
  const [title, setTitle] = useState("");
  const [targetOutcome, setTargetOutcome] = useState("");
  const [deadlineDate, setDeadlineDate] = useState(defaultDeadlineDate());
  const [weeklyMinutes, setWeeklyMinutes] = useState(300);
  const [baselineNote, setBaselineNote] = useState("");
  const [planGenerating, setPlanGenerating] = useState(false);
  const [planError, setPlanError] = useState<string | null>(null);

  const createGoal = useCreateGoal(profileId);
  const generatePlan = useGeneratePlan();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setPlanError(null);

    const payload: CreateGoalRequest = {
      subject: subject.trim(),
      title: title.trim(),
      target_outcome: targetOutcome.trim(),
      deadline_date: deadlineDate,
      weekly_study_minutes: weeklyMinutes,
      baseline_note: baselineNote.trim() || null,
    };

    try {
      const goal = await createGoal.mutateAsync(payload);
      setPlanGenerating(true);
      try {
        await generatePlan.mutateAsync(goal.id);
      } catch {
        // plan generation failed but goal was created; still navigate
      }
      setPlanGenerating(false);
      onSuccess(goal.id);
    } catch (err) {
      setPlanError(err instanceof Error ? err.message : "创建失败");
      setPlanGenerating(false);
    }
  }

  const isPending = createGoal.isPending || planGenerating;

  return (
    <Card className="notebook-margin border-primary/15 bg-surface shadow-md">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2.5 font-serif text-xl font-semibold">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary-surface">
            <Target className="h-4 w-4 text-primary" />
          </div>
          新建学习目标
        </CardTitle>
        <p className="text-sm text-text-secondary">
          设定目标和时间规划，AI 将为你生成个性化学习计划。
        </p>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-5">
          <div className="space-y-1.5">
            <Label htmlFor="goal-subject" className="text-text-primary">
              学科主题 <span className="text-error">*</span>
            </Label>
            <Input
              id="goal-subject"
              placeholder="例如：线性代数、Python 编程、英语写作..."
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              required
              maxLength={255}
              className="h-11 bg-background/50"
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="goal-title" className="text-text-primary">
              目标名称 <span className="text-error">*</span>
            </Label>
            <Input
              id="goal-title"
              placeholder="例如：掌握矩阵运算基础"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
              maxLength={255}
              className="h-11 bg-background/50"
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="goal-outcome" className="text-text-primary">
              期望成果 <span className="text-error">*</span>
            </Label>
            <Textarea
              id="goal-outcome"
              placeholder="描述你希望达到的学习成果..."
              value={targetOutcome}
              onChange={(e) => setTargetOutcome(e.target.value)}
              required
              maxLength={1000}
              className="min-h-[80px] bg-background/50"
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label htmlFor="goal-deadline" className="text-text-primary">
                <Calendar className="mr-1 inline h-3.5 w-3.5" />
                目标日期 <span className="text-error">*</span>
              </Label>
              <Input
                id="goal-deadline"
                type="date"
                value={deadlineDate}
                onChange={(e) => setDeadlineDate(e.target.value)}
                required
                className="h-11 bg-background/50"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="goal-weekly" className="text-text-primary">
                <Clock className="mr-1 inline h-3.5 w-3.5" />
                每周学习时长(分钟) <span className="text-error">*</span>
              </Label>
              <Input
                id="goal-weekly"
                type="number"
                min={60}
                max={1200}
                step={30}
                value={weeklyMinutes}
                onChange={(e) =>
                  setWeeklyMinutes(Number.parseInt(e.target.value, 10) || 60)
                }
                required
                className="h-11 bg-background/50"
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="goal-baseline" className="text-text-primary">
              <BookOpen className="mr-1 inline h-3.5 w-3.5" />
              当前基础
              <span className="ml-1.5 text-xs font-normal text-text-secondary">
                可选
              </span>
            </Label>
            <Textarea
              id="goal-baseline"
              placeholder="描述你目前的基础水平，帮助 AI 更好地规划..."
              value={baselineNote}
              onChange={(e) => setBaselineNote(e.target.value)}
              maxLength={2000}
              className="min-h-[64px] bg-background/50"
            />
          </div>

          {(planError || createGoal.error) && (
            <p className="rounded-md bg-error/5 px-3 py-2 text-sm text-error">
              {planError || createGoal.error?.message}
            </p>
          )}

          <div className="flex items-center justify-between border-t border-border-subtle pt-5">
            {planGenerating ? (
              <p className="flex items-center gap-2 text-sm text-accent-gold">
                <Loader2 className="h-4 w-4 animate-spin" />
                AI 正在为你规划学习路径...
              </p>
            ) : (
              <p className="hidden items-center gap-1.5 text-xs text-text-secondary sm:flex">
                系统将自动生成个性化学习计划
              </p>
            )}
            <div className="flex w-full justify-end gap-3 sm:w-auto">
              <Button
                type="button"
                variant="outline"
                onClick={onCancel}
                disabled={isPending}
              >
                取消
              </Button>
              <Button type="submit" disabled={isPending}>
                {planGenerating ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    规划中...
                  </>
                ) : createGoal.isPending ? (
                  "创建中..."
                ) : (
                  "创建目标并生成计划"
                )}
              </Button>
            </div>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
