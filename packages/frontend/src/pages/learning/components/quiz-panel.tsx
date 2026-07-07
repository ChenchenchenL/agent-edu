import { useEffect, useState } from "react";
import {
  ClipboardList,
  Loader2,
  Sparkles,
  CheckCircle2,
  RotateCcw,
  AlertCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import {
  useSessionQuizzes,
  useQuizDetail,
  useGenerateQuiz,
} from "@/hooks/use-quiz";
import { useQuizAttempts } from "@/hooks/use-quiz-attempts";
import { QuestionCard } from "@/pages/learning/components/question-card";
import { difficultyLabel } from "@/pages/learning/lib/labels";
import type { MessageRequest } from "@/types/session";

interface QuizPanelProps {
  sessionId: string;
  defaultTopic: string;
  onRequestHint: (payload: MessageRequest) => void;
  onDiscussAnswer: (content: string) => void;
  isPending: boolean;
}

function formatDateTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function QuizPanel({
  sessionId,
  defaultTopic,
  onRequestHint,
  onDiscussAnswer,
  isPending,
}: QuizPanelProps) {
  const [topic, setTopic] = useState(defaultTopic);
  const [difficulty, setDifficulty] = useState("medium");
  const [questionCount, setQuestionCount] = useState(3);
  const [activeQuizId, setActiveQuizId] = useState<string | null>(null);

  const {
    data: quizList,
    isLoading: listLoading,
    error: listError,
  } = useSessionQuizzes(sessionId);
  const {
    data: activeQuiz,
    isLoading: detailLoading,
    error: detailError,
  } = useQuizDetail(sessionId, activeQuizId);
  const generateQuiz = useGenerateQuiz(sessionId);

  const { state, actions, derived } = useQuizAttempts({
    sessionId,
    activeQuiz: activeQuiz ?? null,
    activeQuizId,
  });

  useEffect(() => {
    if (activeQuizId || !quizList || quizList.length === 0) return;
    setActiveQuizId(quizList[0].quiz_id);
  }, [activeQuizId, quizList]);

  function regenerateQuiz(difficultyOverride?: string) {
    if (!activeQuiz) return;
    setTopic(activeQuiz.topic);
    generateQuiz.mutate({
      topic: activeQuiz.topic,
      difficulty: difficultyOverride ?? activeQuiz.difficulty,
      question_count: activeQuiz.questions.length,
    });
  }

  function handleGenerate(e: React.FormEvent) {
    e.preventDefault();
    const trimmedTopic = topic.trim();
    if (!trimmedTopic) return;
    generateQuiz.mutate(
      { topic: trimmedTopic, difficulty, question_count: questionCount },
      {
        onSuccess: (quiz) => {
          setActiveQuizId(quiz.quiz_id);
          actions.resetAll();
        },
      },
    );
  }

  function handleSelectQuiz(quizId: string) {
    setActiveQuizId(quizId);
    actions.resetAll();
  }

  function handleQuestionCountChange(value: string) {
    const parsed = Number.parseInt(value, 10);
    if (Number.isNaN(parsed)) {
      setQuestionCount(1);
      return;
    }
    setQuestionCount(Math.min(10, Math.max(1, parsed)));
  }

  const quizListItems = quizList ?? [];
  const progressPercent =
    derived.totalQuestions === 0
      ? 0
      : Math.round((derived.checkedCount / derived.totalQuestions) * 100);

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-border-subtle px-4 py-3">
        <div className="flex items-center gap-2">
          <ClipboardList className="h-4 w-4 text-primary" />
          <h2 className="font-medium text-text-primary">练习题</h2>
        </div>
        <p className="mt-1 text-xs text-text-secondary">
          生成题目，作答后可获取提示或讨论
        </p>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-4">
        <form onSubmit={handleGenerate} className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="quiz-topic" className="text-xs">
              主题
            </Label>
            <Input
              id="quiz-topic"
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              placeholder="例如：矩阵乘法"
              className="h-9 text-sm"
              maxLength={255}
              required
            />
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1.5">
              <Label htmlFor="quiz-difficulty" className="text-xs">
                难度
              </Label>
              <select
                id="quiz-difficulty"
                value={difficulty}
                onChange={(e) => setDifficulty(e.target.value)}
                className="flex h-9 w-full rounded-md border border-input bg-surface px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <option value="easy">简单</option>
                <option value="medium">中等</option>
                <option value="hard">困难</option>
              </select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="quiz-count" className="text-xs">
                题数
              </Label>
              <Input
                id="quiz-count"
                type="number"
                min={1}
                max={10}
                value={questionCount}
                onChange={(e) => handleQuestionCountChange(e.target.value)}
                className="h-9 text-sm"
              />
            </div>
          </div>

          <Button
            type="submit"
            className="w-full"
            size="sm"
            disabled={generateQuiz.isPending || !topic.trim()}
          >
            {generateQuiz.isPending ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                生成中...
              </>
            ) : (
              <>
                <Sparkles className="h-3.5 w-3.5" />
                生成练习题
              </>
            )}
          </Button>

          {generateQuiz.isPending && (
            <div className="rounded-lg border border-accent-gold/20 bg-accent-gold-surface/60 px-3 py-3">
              <div className="flex items-center gap-2">
                <Loader2 className="h-4 w-4 animate-spin text-accent-gold" />
                <p className="text-sm font-medium text-text-primary">
                  AI 正在生成练习题...
                </p>
              </div>
              <p className="mt-1.5 text-xs leading-relaxed text-text-secondary">
                {questionCount <= 3
                  ? "通常需要 30 秒左右，请耐心等待。"
                  : `正在生成 ${questionCount} 道题目，最多可能需要几分钟，请耐心等待。`}
              </p>
            </div>
          )}

          {generateQuiz.error && (
            <p className="text-xs text-error">{generateQuiz.error.message}</p>
          )}
        </form>

        {listLoading && (
          <div className="mt-5 flex items-center justify-center gap-2 rounded-lg border border-border-subtle bg-surface px-3 py-4 text-xs text-text-secondary">
            <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
            正在读取练习记录
          </div>
        )}

        {listError && (
          <div className="mt-5 flex items-start gap-2 rounded-lg border border-error/20 bg-error/5 px-3 py-3 text-xs text-error">
            <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>练习记录读取失败：{listError.message}</span>
          </div>
        )}

        {!listLoading && !listError && quizListItems.length === 0 && (
          <div className="mt-5 rounded-lg border border-dashed border-border bg-accent-gold-surface/50 px-3 py-4">
            <p className="text-sm font-medium text-text-primary">
              还没有练习题
            </p>
            <p className="mt-1 text-xs leading-relaxed text-text-secondary">
              生成一组题目后，可以逐题作答、请求提示、对照参考答案，并把有疑问的答案发回对话区讨论。
            </p>
          </div>
        )}

        {!listLoading && !listError && quizListItems.length > 0 && (
          <div className="mt-5 space-y-2">
            <p className="text-[11px] font-medium tracking-wide text-text-secondary uppercase">
              历史练习
            </p>
            <div className="space-y-1.5">
              {quizListItems.map((quiz) => (
                <button
                  key={quiz.quiz_id}
                  type="button"
                  onClick={() => handleSelectQuiz(quiz.quiz_id)}
                  className={`w-full rounded-lg border px-3 py-2 text-left transition-colors ${
                    activeQuizId === quiz.quiz_id
                      ? "border-primary/30 bg-primary-surface"
                      : "border-border-subtle bg-surface hover:border-primary/20"
                  }`}
                >
                  <p className="truncate text-sm font-medium text-text-primary">
                    {quiz.topic}
                  </p>
                  <div className="mt-1 flex items-center gap-2 text-[11px] text-text-secondary">
                    <span>{difficultyLabel(quiz.difficulty)}</span>
                    <span>|</span>
                    <span>{quiz.question_count} 题</span>
                    <span>|</span>
                    <span>{formatDateTime(quiz.created_at)}</span>
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}

        {activeQuizId && (
          <div className="mt-5 space-y-3">
            {detailLoading ? (
              <div className="flex justify-center py-6">
                <Loader2 className="h-4 w-4 animate-spin text-primary" />
              </div>
            ) : activeQuiz ? (
              <>
                <div className="rounded-lg border border-primary/15 bg-primary-surface/60 px-3 py-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-text-primary">
                        {activeQuiz.topic}
                      </p>
                      <p className="mt-1 text-xs text-text-secondary">
                        已作答 {derived.answeredCount}/{derived.totalQuestions}，已核对{" "}
                        {derived.checkedCount}/{derived.totalQuestions}
                      </p>
                    </div>
                    <Badge variant="outline" className="shrink-0 text-[10px]">
                      {difficultyLabel(activeQuiz.difficulty)}
                    </Badge>
                  </div>
                  <div
                    className="mt-3 h-1.5 overflow-hidden rounded-full bg-surface"
                    aria-label="练习完成进度"
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={progressPercent}
                    role="progressbar"
                  >
                    <div
                      className="h-full rounded-full bg-primary transition-all"
                      style={{ width: `${progressPercent}%` }}
                    />
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={!derived.canReset}
                      onClick={actions.resetAll}
                    >
                      <RotateCcw className="h-3.5 w-3.5" />
                      重置本轮
                    </Button>
                    {derived.checkedCount === derived.totalQuestions &&
                      derived.totalQuestions > 0 && (
                        <span className="inline-flex items-center gap-1 rounded-md bg-success/10 px-2.5 py-1.5 text-xs font-medium text-success">
                          <CheckCircle2 className="h-3.5 w-3.5" />
                          本轮已完成
                        </span>
                      )}
                  </div>
                </div>

                {activeQuiz.questions.map((question, index) => (
                  <QuestionCard
                    key={question.id ?? `${question.prompt}-${index}`}
                    index={index}
                    question={question}
                    answer={state.answers[index] ?? ""}
                    onAnswerChange={(value) => actions.setAnswer(index, value)}
                    isRevealed={!!state.revealed[index]}
                    isHinted={!!state.hinted[index]}
                    isDiscussed={!!state.discussed[index]}
                    isSubmitting={!!state.submitting[index]}
                    attempt={
                      question.id ? state.attempts[question.id] : undefined
                    }
                    attemptError={
                      question.id ? state.attemptErrors[question.id] : undefined
                    }
                    isPending={isPending}
                    onToggleReveal={() => actions.toggleReveal(index)}
                    onSubmitAttempt={() => actions.submitAttempt(index)}
                    onRequestHint={() => actions.requestHint(index, onRequestHint)}
                    onDiscuss={() => actions.discuss(index, onDiscussAnswer)}
                    onFollowUp={(action) =>
                      actions.followUp(
                        index,
                        action,
                        regenerateQuiz,
                        onRequestHint,
                      )
                    }
                  />
                ))}
              </>
            ) : detailError ? (
              <div className="flex items-start gap-2 rounded-lg border border-error/20 bg-error/5 px-3 py-3 text-xs text-error">
                <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <span>练习详情读取失败：{detailError.message}</span>
              </div>
            ) : null}
          </div>
        )}
      </div>
    </div>
  );
}
