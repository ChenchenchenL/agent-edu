import { useState } from "react";
import {
  ClipboardList,
  Loader2,
  Sparkles,
  Lightbulb,
  CheckCircle2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import {
  useSessionQuizzes,
  useQuizDetail,
  useGenerateQuiz,
} from "@/hooks/use-quiz";
import { difficultyLabel } from "@/pages/learning/lib/labels";
import type { MessageRequest } from "@/types/session";

interface QuizPanelProps {
  sessionId: string;
  defaultTopic: string;
  onRequestHint: (payload: MessageRequest) => void;
  onDiscussAnswer: (content: string) => void;
  isPending: boolean;
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
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const [revealed, setRevealed] = useState<Record<number, boolean>>({});

  const { data: quizList, isLoading: listLoading } =
    useSessionQuizzes(sessionId);
  const { data: activeQuiz, isLoading: detailLoading } = useQuizDetail(
    sessionId,
    activeQuizId,
  );
  const generateQuiz = useGenerateQuiz(sessionId);

  function handleGenerate(e: React.FormEvent) {
    e.preventDefault();
    const trimmedTopic = topic.trim();
    if (!trimmedTopic) return;
    generateQuiz.mutate(
      {
        topic: trimmedTopic,
        difficulty,
        question_count: questionCount,
      },
      {
        onSuccess: (quiz) => {
          setActiveQuizId(quiz.quiz_id);
          setAnswers({});
          setRevealed({});
        },
      },
    );
  }

  function handleSelectQuiz(quizId: string) {
    setActiveQuizId(quizId);
    setAnswers({});
    setRevealed({});
  }

  function handleRequestHint(questionIndex: number) {
    if (!activeQuiz) return;
    const question = activeQuiz.questions[questionIndex];
    if (!question) return;
    const learnerAnswer = answers[questionIndex]?.trim();
    onRequestHint({
      content: learnerAnswer
        ? "请针对我的答案给出提示，不要直接告诉我正确答案"
        : "请给我这道题的提示，不要直接告诉我答案",
      mode: "hint",
      related_quiz_id: activeQuiz.quiz_id,
      question_prompt: question.prompt,
      learner_answer: learnerAnswer || undefined,
    });
  }

  function handleDiscuss(questionIndex: number) {
    const question = activeQuiz?.questions[questionIndex];
    const learnerAnswer = answers[questionIndex]?.trim();
    if (!question || !learnerAnswer) return;
    onDiscussAnswer(
      `关于练习题「${question.prompt}」，我的答案是：${learnerAnswer}。请帮我分析是否正确并讲解。`,
    );
  }

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
                onChange={(e) =>
                  setQuestionCount(Number.parseInt(e.target.value, 10) || 1)
                }
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
                生成中…
              </>
            ) : (
              <>
                <Sparkles className="h-3.5 w-3.5" />
                生成练习题
              </>
            )}
          </Button>

          {generateQuiz.error && (
            <p className="text-xs text-error">{generateQuiz.error.message}</p>
          )}
        </form>

        {!listLoading && quizList && quizList.length > 0 && (
          <div className="mt-5 space-y-2">
            <p className="text-[11px] font-medium tracking-wide text-text-secondary uppercase">
              历史练习
            </p>
            <div className="space-y-1.5">
              {quizList.map((quiz) => (
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
                    <span>·</span>
                    <span>{quiz.question_count} 题</span>
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
                <div className="flex items-center justify-between">
                  <p className="text-sm font-medium text-text-primary">
                    {activeQuiz.topic}
                  </p>
                  <Badge variant="outline" className="text-[10px]">
                    {activeQuiz.questions.length} 题
                  </Badge>
                </div>

                {activeQuiz.questions.map((question, index) => (
                  <div
                    key={question.prompt}
                    className="notebook-margin rounded-lg border border-border-subtle bg-surface p-3"
                  >
                    <p className="text-xs font-medium text-text-secondary">
                      第 {index + 1} 题
                    </p>
                    <p className="mt-1 text-sm leading-relaxed text-text-primary">
                      {question.prompt}
                    </p>

                    <Textarea
                      placeholder="写下你的答案…"
                      value={answers[index] ?? ""}
                      onChange={(e) =>
                        setAnswers((prev) => ({
                          ...prev,
                          [index]: e.target.value,
                        }))
                      }
                      className="mt-3 min-h-[64px] text-sm"
                      disabled={isPending}
                      maxLength={4000}
                    />

                    <div className="mt-2 flex flex-wrap gap-2">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        disabled={isPending}
                        onClick={() => handleRequestHint(index)}
                      >
                        <Lightbulb className="h-3.5 w-3.5" />
                        获取提示
                      </Button>
                      <Button
                        type="button"
                        variant="secondary"
                        size="sm"
                        disabled={isPending || !answers[index]?.trim()}
                        onClick={() => handleDiscuss(index)}
                      >
                        提交讨论
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() =>
                          setRevealed((prev) => ({
                            ...prev,
                            [index]: !prev[index],
                          }))
                        }
                      >
                        {revealed[index] ? "隐藏参考" : "查看参考"}
                      </Button>
                    </div>

                    {revealed[index] && (
                      <div className="mt-2 flex items-start gap-2 rounded-md bg-success/5 px-2.5 py-2 text-xs text-success">
                        <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                        <span>{question.answer}</span>
                      </div>
                    )}
                  </div>
                ))}
              </>
            ) : null}
          </div>
        )}
      </div>
    </div>
  );
}
