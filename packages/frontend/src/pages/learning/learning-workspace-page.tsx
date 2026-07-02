import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { Loader2, MessageSquare, ClipboardList, Lightbulb, BookCheck } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  useSession,
  useSessionMessages,
  useSendMessage,
} from "@/hooks/use-sessions";
import { WorkspaceHeader } from "@/pages/learning/components/workspace-header";
import { MessageThread } from "@/pages/learning/components/message-thread";
import { ChatComposer } from "@/pages/learning/components/chat-composer";
import { QuizPanel } from "@/pages/learning/components/quiz-panel";
import { HintPanel } from "@/pages/learning/components/hint-panel";
import { TaskPanel } from "@/pages/learning/components/task-panel";
import type { MessageRequest } from "@/types/session";

type SidePanel = "quiz" | "hint" | "tasks";

export function LearningWorkspacePage() {
  const { id: sessionId } = useParams<{ id: string }>();
  const [chatInput, setChatInput] = useState("");
  const [sidePanel, setSidePanel] = useState<SidePanel>("quiz");

  const { data: session, isLoading: sessionLoading } = useSession(
    sessionId ?? "",
  );
  const { data: messageData, isLoading: messagesLoading } = useSessionMessages(
    sessionId ?? "",
  );
  const sendMessage = useSendMessage(sessionId ?? "");

  const messages = messageData?.items ?? [];

  function sendChat(content: string, extra?: Partial<MessageRequest>) {
    const trimmed = content.trim();
    if (!trimmed) return;
    sendMessage.mutate({ content: trimmed, mode: "chat", ...extra });
  }

  function sendHint(payload: MessageRequest) {
    sendMessage.mutate(payload);
  }

  function handleChatSubmit() {
    sendChat(chatInput, { mode: "chat" });
    setChatInput("");
  }

  function handleHintRequest(content: string) {
    sendHint({ content, mode: "hint" });
  }

  if (sessionLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="h-5 w-5 animate-spin text-primary" />
      </div>
    );
  }

  if (!session) {
    return (
      <div className="fade-in flex flex-col items-center gap-4 py-24">
        <p className="font-medium text-text-primary">会话不存在</p>
        <p className="text-sm text-text-secondary">
          该会话可能已被删除或链接无效
        </p>
        <Link to="/sessions">
          <Button variant="outline">返回会话列表</Button>
        </Link>
      </div>
    );
  }

  return (
    <div className="fade-in -mx-6 -mt-5 flex h-[calc(100vh-7rem)] flex-col">
      <div className="overflow-hidden rounded-xl border border-border-subtle bg-surface shadow-sm">
        <WorkspaceHeader session={session} />

        <div className="flex h-[calc(100vh-7rem-5.5rem)] flex-col lg:flex-row">
          {/* 对话区 */}
          <section className="flex min-h-0 flex-1 flex-col border-b border-border-subtle lg:border-r lg:border-b-0">
            <div className="flex items-center gap-2 border-b border-border-subtle px-5 py-2.5">
              <MessageSquare className="h-3.5 w-3.5 text-primary" />
              <span className="text-xs font-medium text-text-primary">
                对话与讲解
              </span>
            </div>

            <MessageThread
              messages={messages}
              isLoading={messagesLoading}
              isSending={sendMessage.isPending}
            />

            <ChatComposer
              value={chatInput}
              onChange={setChatInput}
              onSubmit={handleChatSubmit}
              isPending={sendMessage.isPending}
            />
          </section>

          {/* 工具面板 */}
          <aside className="flex w-full shrink-0 flex-col lg:w-[380px]">
            <div className="flex border-b border-border-subtle">
              <button
                type="button"
                onClick={() => setSidePanel("quiz")}
                className={`flex flex-1 items-center justify-center gap-1.5 px-4 py-2.5 text-xs font-medium transition-colors ${
                  sidePanel === "quiz"
                    ? "border-b-2 border-primary text-primary"
                    : "text-text-secondary hover:text-text-primary"
                }`}
              >
                <ClipboardList className="h-3.5 w-3.5" />
                练习题
              </button>
              <button
                type="button"
                onClick={() => setSidePanel("hint")}
                className={`flex flex-1 items-center justify-center gap-1.5 px-4 py-2.5 text-xs font-medium transition-colors ${
                  sidePanel === "hint"
                    ? "border-b-2 border-primary text-primary"
                    : "text-text-secondary hover:text-text-primary"
                }`}
              >
                <Lightbulb className="h-3.5 w-3.5" />
                提示
              </button>
              <button
                type="button"
                onClick={() => setSidePanel("tasks")}
                className={`flex flex-1 items-center justify-center gap-1.5 px-4 py-2.5 text-xs font-medium transition-colors ${
                  sidePanel === "tasks"
                    ? "border-b-2 border-primary text-primary"
                    : "text-text-secondary hover:text-text-primary"
                }`}
              >
                <BookCheck className="h-3.5 w-3.5" />
                任务
              </button>
            </div>

            <div className="min-h-0 flex-1 overflow-hidden">
              {sidePanel === "quiz" ? (
                <QuizPanel
                  sessionId={session.id}
                  defaultTopic={session.subject ?? ""}
                  onRequestHint={sendHint}
                  onDiscussAnswer={(content) => sendChat(content)}
                  isPending={sendMessage.isPending}
                />
              ) : sidePanel === "hint" ? (
                <HintPanel
                  onRequestHint={handleHintRequest}
                  isPending={sendMessage.isPending}
                />
              ) : (
                <TaskPanel sessionId={session.id} goalId={session.learner_goal_id} />
              )}
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}
