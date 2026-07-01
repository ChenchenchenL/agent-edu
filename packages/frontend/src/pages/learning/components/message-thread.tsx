import { useRef, useEffect } from "react";
import { Loader2, MessageSquare } from "lucide-react";
import { MessageBubble } from "@/pages/learning/components/message-bubble";
import type { MessageHistoryItem } from "@/types/session";

interface MessageThreadProps {
  messages: MessageHistoryItem[];
  isLoading: boolean;
  isSending: boolean;
}

export function MessageThread({
  messages,
  isLoading,
  isSending,
}: MessageThreadProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, isSending]);

  if (isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-primary" />
      </div>
    );
  }

  if (messages.length === 0 && !isSending) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-4 px-6 text-center">
        <div className="notebook-margin flex h-14 w-14 items-center justify-center rounded-xl bg-primary-surface">
          <MessageSquare className="h-7 w-7 text-primary" />
        </div>
        <div className="max-w-sm">
          <p className="font-serif text-lg font-semibold text-text-primary">
            开始你的学习对话
          </p>
          <p className="mt-2 text-sm leading-relaxed text-text-secondary">
            提问获取讲解，在右侧面板生成练习题或请求提示
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 space-y-6 overflow-y-auto px-5 py-5">
      {messages.map((msg) => (
        <MessageBubble key={msg.id} message={msg} />
      ))}
      {isSending && (
        <div className="flex items-center gap-2 text-sm text-text-secondary">
          <Loader2 className="h-4 w-4 animate-spin text-primary" />
          AI 导师正在思考…
        </div>
      )}
      <div ref={messagesEndRef} />
    </div>
  );
}
