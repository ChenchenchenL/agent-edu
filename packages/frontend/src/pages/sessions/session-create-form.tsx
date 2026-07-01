import { useState } from "react";
import { BookOpen, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useCreateSession } from "@/hooks/use-sessions";

interface SessionCreateFormProps {
  onSuccess: (sessionId: string) => void;
  onCancel: () => void;
}

export function SessionCreateForm({
  onSuccess,
  onCancel,
}: SessionCreateFormProps) {
  const [title, setTitle] = useState("");
  const [subject, setSubject] = useState("");
  const createSession = useCreateSession();

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    createSession.mutate(
      {
        title: title.trim() || undefined,
        subject: subject.trim() || undefined,
      },
      {
        onSuccess: (session) => {
          onSuccess(session.id);
        },
      },
    );
  }

  return (
    <Card className="notebook-margin border-primary/15 bg-surface shadow-md">
      <CardHeader className="pb-2">
        <CardTitle className="flex items-center gap-2.5 font-serif text-xl font-semibold">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary-surface">
            <BookOpen className="h-4 w-4 text-primary" />
          </div>
          新建学习会话
        </CardTitle>
        <p className="text-sm text-text-secondary">
          设定学习主题，AI 导师将根据你的水平调整讲解节奏。
        </p>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-5">
          <div className="space-y-2">
            <Label htmlFor="subject" className="text-text-primary">
              学习主题 <span className="text-error">*</span>
            </Label>
            <Input
              id="subject"
              placeholder="例如：线性代数、Python 编程、英语写作..."
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              required
              maxLength={255}
              className="h-11 bg-background/50"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="title" className="text-text-primary">
              会话标题
              <span className="ml-1.5 text-xs font-normal text-text-secondary">
                可选
              </span>
            </Label>
            <Input
              id="title"
              placeholder="给这次学习起个名字"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              maxLength={255}
              className="h-11 bg-background/50"
            />
          </div>
          {createSession.error && (
            <p className="rounded-md bg-error/5 px-3 py-2 text-sm text-error">
              创建失败：{createSession.error.message}
            </p>
          )}
          <div className="flex items-center justify-between border-t border-border-subtle pt-5">
            <p className="hidden items-center gap-1.5 text-xs text-text-secondary sm:flex">
              <Sparkles className="h-3.5 w-3.5 text-accent-gold" />
              支持任意学科主题
            </p>
            <div className="flex w-full justify-end gap-3 sm:w-auto">
              <Button
                type="button"
                variant="outline"
                onClick={onCancel}
                disabled={createSession.isPending}
              >
                取消
              </Button>
              <Button type="submit" disabled={createSession.isPending}>
                {createSession.isPending ? "创建中..." : "开始学习"}
              </Button>
            </div>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
