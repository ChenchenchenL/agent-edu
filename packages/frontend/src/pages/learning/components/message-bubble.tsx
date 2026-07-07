import { GraduationCap, User } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { MarkdownContent } from "@/components/markdown-content";
import { ExplanationCard } from "@/pages/learning/components/explanation-card";
import { HintCard } from "@/pages/learning/components/hint-card";
import type { MessageHistoryItem } from "@/types/session";

interface MessageBubbleProps {
  message: MessageHistoryItem;
}

function modeLabel(mode: string | null): string | null {
  if (mode === "hint") return "提示";
  if (mode === "chat") return "讲解";
  return null;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user";
  const label = modeLabel(message.mode);

  return (
    <div className={`flex gap-3 ${isUser ? "flex-row-reverse" : "flex-row"}`}>
      <div
        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${
          isUser
            ? "bg-primary text-white"
            : "bg-accent-gold-surface text-accent-gold"
        }`}
      >
        {isUser ? (
          <User className="h-4 w-4" />
        ) : (
          <GraduationCap className="h-4 w-4" />
        )}
      </div>

      <div
        className={`max-w-[80%] ${isUser ? "items-end" : "items-start"} flex flex-col`}
      >
        {!isUser && label && (
          <Badge variant="outline" className="mb-1.5 text-[10px] font-normal">
            {label}
          </Badge>
        )}

        <div
          className={`rounded-2xl px-4 py-3 ${
            isUser
              ? "rounded-tr-sm bg-primary text-white"
              : "rounded-tl-sm border border-border-subtle bg-surface shadow-sm"
          }`}
        >
          {isUser ? (
            <p className="whitespace-pre-wrap text-[14px] leading-relaxed">
              {message.content}
            </p>
          ) : (
            <MarkdownContent content={message.content} />
          )}

          {message.content_payload?.type === "explanation" && (
            <ExplanationCard payload={message.content_payload} />
          )}
          {message.content_payload?.type === "hint" && (
            <HintCard payload={message.content_payload} />
          )}
        </div>

        <p className="mt-1.5 px-1 text-[11px] text-text-secondary">
          {new Date(message.created_at).toLocaleTimeString("zh-CN", {
            hour: "2-digit",
            minute: "2-digit",
          })}
        </p>
      </div>
    </div>
  );
}
