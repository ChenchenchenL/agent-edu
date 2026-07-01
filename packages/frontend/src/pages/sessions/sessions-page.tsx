import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Plus, BookOpen, MessageSquare, Clock, Hash } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { SessionCreateForm } from "./session-create-form";
import { useSessions } from "@/hooks/use-sessions";

function formatRelativeTime(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return "刚刚";
  if (diffMin < 60) return `${diffMin} 分钟前`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr} 小时前`;
  const diffDay = Math.floor(diffHr / 24);
  if (diffDay < 7) return `${diffDay} 天前`;
  return date.toLocaleDateString("zh-CN");
}

function statusVariant(
  status: string,
): "default" | "secondary" | "outline" | "success" {
  switch (status) {
    case "active":
      return "success";
    case "completed":
      return "secondary";
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
    case "archived":
      return "已归档";
    default:
      return status;
  }
}

function SessionsSkeleton() {
  return (
    <div className="space-y-3">
      {[1, 2, 3].map((i) => (
        <div
          key={i}
          className="h-[76px] animate-pulse rounded-lg border border-border-subtle bg-surface"
        />
      ))}
    </div>
  );
}

export function SessionsPage() {
  const navigate = useNavigate();
  const { data: sessions, isLoading, error } = useSessions();
  const [showCreateForm, setShowCreateForm] = useState(false);

  if (isLoading) {
    return (
      <div className="fade-in">
        <div className="mb-10">
          <div className="h-8 w-40 animate-pulse rounded bg-muted" />
          <div className="mt-3 h-4 w-64 animate-pulse rounded bg-muted" />
        </div>
        <SessionsSkeleton />
      </div>
    );
  }

  if (error) {
    return (
      <div className="fade-in flex flex-col items-center justify-center gap-4 py-24">
        <div className="flex h-14 w-14 items-center justify-center rounded-full bg-error/10">
          <BookOpen className="h-6 w-6 text-error" />
        </div>
        <div className="text-center">
          <p className="font-medium text-text-primary">无法加载会话列表</p>
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

  const sessionList = sessions ?? [];

  return (
    <div className="fade-in">
      <div className="mb-10 flex flex-col gap-6 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="mb-2 text-xs font-semibold tracking-widest text-accent-gold uppercase">
            学习中心
          </p>
          <h1 className="text-3xl font-semibold text-text-primary">学习会话</h1>
          <p className="mt-2 max-w-md text-[15px] leading-relaxed text-text-secondary">
            创建新会话，与 AI 导师展开引导式对话，逐步建立对知识的深度理解。
          </p>
        </div>
        <Button
          onClick={() => setShowCreateForm(true)}
          size="lg"
          className="shrink-0 shadow-sm"
        >
          <Plus className="h-4 w-4" />
          新建会话
        </Button>
      </div>

      {showCreateForm && (
        <div className="mb-8">
          <SessionCreateForm
            onSuccess={(sessionId) => {
              setShowCreateForm(false);
              navigate(`/sessions/${sessionId}`);
            }}
            onCancel={() => setShowCreateForm(false)}
          />
        </div>
      )}

      {sessionList.length === 0 ? (
        <Card className="border-dashed border-border bg-surface/60 shadow-none">
          <CardContent className="flex flex-col items-center gap-5 py-20">
            <div className="notebook-margin flex h-14 w-14 items-center justify-center rounded-xl bg-primary-surface">
              <BookOpen className="h-7 w-7 text-primary" />
            </div>
            <div className="max-w-sm text-center">
              <p className="font-serif text-lg font-semibold text-text-primary">
                开启你的第一次学习
              </p>
              <p className="mt-2 text-sm leading-relaxed text-text-secondary">
                选择一个感兴趣的主题，AI 导师将以提问和讲解的方式，陪你一步步探索。
              </p>
            </div>
            <Button
              variant="outline"
              onClick={() => setShowCreateForm(true)}
              className="mt-1"
            >
              <Plus className="h-4 w-4" />
              创建第一个会话
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2.5">
          {sessionList.map((session) => (
            <Card
              key={session.id}
              className="notebook-margin group cursor-pointer border-border-subtle shadow-none transition-all hover:border-primary/20 hover:shadow-md"
              onClick={() => navigate(`/sessions/${session.id}`)}
            >
              <CardContent className="flex items-center justify-between gap-4 py-4 pl-5">
                <div className="flex min-w-0 items-center gap-4">
                  <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-primary-surface transition-colors group-hover:bg-primary/10">
                    <MessageSquare className="h-5 w-5 text-primary" />
                  </div>
                  <div className="min-w-0">
                    <h3 className="truncate font-medium text-text-primary">
                      {session.title || session.subject || "未命名会话"}
                    </h3>
                    <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-text-secondary">
                      {session.subject && (
                        <span className="inline-flex items-center gap-1">
                          <Hash className="h-3 w-3 text-accent-gold" />
                          {session.subject}
                        </span>
                      )}
                      <span className="inline-flex items-center gap-1">
                        <MessageSquare className="h-3 w-3" />
                        {session.message_count} 条消息
                      </span>
                      <span className="inline-flex items-center gap-1">
                        <Clock className="h-3 w-3" />
                        {formatRelativeTime(session.last_activity_at)}
                      </span>
                    </div>
                  </div>
                </div>
                <Badge
                  variant={statusVariant(session.status)}
                  className="shrink-0"
                >
                  {statusLabel(session.status)}
                </Badge>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
