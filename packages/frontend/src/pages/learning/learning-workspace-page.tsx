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
      <div className="flex h-[80vh] items-center justify-center bg-background">
        <Loader2 className="h-6 w-6 animate-spin text-primary" />
      </div>
    );
  }

  if (!session) {
    return (
      <div className="fade-in flex flex-col items-center justify-center gap-4 py-24 min-h-[80vh] bg-background">
        <p className="font-serif text-lg font-semibold text-text-primary">会话不存在</p>
        <p className="text-sm text-text-secondary">
          该会话可能已被删除或链接无效
        </p>
        <Link to="/sessions">
          <Button variant="outline" className="rounded-none">返回会话列表</Button>
        </Link>
      </div>
    );
  }

  return (
    <div className="fade-in flex h-[calc(100vh-4rem)] flex-col bg-surface overflow-hidden">
      {/* Header section */}
      <div className="shrink-0">
        <WorkspaceHeader session={session} />
      </div>

      {/* Main split workspace */}
      <div className="flex flex-1 min-h-0 flex-col lg:flex-row">
        {/* Left Column: Chat / Explanation Workspace (takes remaining space) */}
        <section className="flex min-h-0 flex-1 flex-col bg-[#fcfbfa] border-b border-border lg:border-r lg:border-b-0">
          <div className="flex items-center gap-2 border-b border-border px-6 py-3 bg-[#FAF9F6]">
            <MessageSquare className="h-4 w-4 text-primary" strokeWidth={1.5} />
            <span className="text-xs font-serif font-semibold tracking-wider text-text-primary uppercase">
              对话与讲解
            </span>
          </div>

          <div className="flex-1 min-h-0 flex flex-col overflow-hidden">
            <MessageThread
              messages={messages}
              isLoading={messagesLoading}
              isSending={sendMessage.isPending}
            />
          </div>

          <div className="shrink-0 bg-white">
            <ChatComposer
              value={chatInput}
              onChange={setChatInput}
              onSubmit={handleChatSubmit}
              isPending={sendMessage.isPending}
            />
          </div>
        </section>

        {/* Right Column: Dynamic Tool Workspace (Quiz / Hints / Study Tasks) */}
        <aside className="flex w-full lg:w-[480px] xl:w-[560px] shrink-0 flex-col bg-white min-h-0 overflow-hidden">
          {/* Tab Navigation */}
          <div className="flex border-b border-border bg-[#FAF9F6] shrink-0">
            <button
              type="button"
              onClick={() => setSidePanel("quiz")}
              className={`flex flex-1 items-center justify-center gap-2 px-5 py-3 text-xs font-serif font-semibold tracking-wider transition-colors relative uppercase ${
                sidePanel === "quiz"
                  ? "text-primary"
                  : "text-text-secondary hover:text-text-primary"
              }`}
            >
              <ClipboardList className="h-4 w-4" strokeWidth={1.5} />
              练习题
              {sidePanel === "quiz" && (
                <div className="absolute bottom-[-1px] left-0 right-0 h-0.5 bg-primary" />
              )}
            </button>
            <button
              type="button"
              onClick={() => setSidePanel("hint")}
              className={`flex flex-1 items-center justify-center gap-2 px-5 py-3 text-xs font-serif font-semibold tracking-wider transition-colors relative uppercase ${
                sidePanel === "hint"
                  ? "text-primary"
                  : "text-text-secondary hover:text-text-primary"
              }`}
            >
              <Lightbulb className="h-4 w-4" strokeWidth={1.5} />
              提示
              {sidePanel === "hint" && (
                <div className="absolute bottom-[-1px] left-0 right-0 h-0.5 bg-primary" />
              )}
            </button>
            <button
              type="button"
              onClick={() => setSidePanel("tasks")}
              className={`flex flex-1 items-center justify-center gap-2 px-5 py-3 text-xs font-serif font-semibold tracking-wider transition-colors relative uppercase ${
                sidePanel === "tasks"
                  ? "text-primary"
                  : "text-text-secondary hover:text-text-primary"
              }`}
            >
              <BookCheck className="h-4 w-4" strokeWidth={1.5} />
              任务
              {sidePanel === "tasks" && (
                <div className="absolute bottom-[-1px] left-0 right-0 h-0.5 bg-primary" />
              )}
            </button>
          </div>

          {/* Panel Content Panel */}
          <div className="flex-1 min-h-0 overflow-y-auto">
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
  );
}
