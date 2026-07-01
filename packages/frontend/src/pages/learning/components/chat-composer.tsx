import { Send, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

interface ChatComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  isPending: boolean;
  placeholder?: string;
}

export function ChatComposer({
  value,
  onChange,
  onSubmit,
  isPending,
  placeholder = "输入你的问题…（Enter 发送，Shift+Enter 换行）",
}: ChatComposerProps) {
  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      onSubmit();
    }
  }

  return (
    <div className="flex gap-3 border-t border-border-subtle bg-surface p-3">
      <Textarea
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        className="min-h-[48px] flex-1 resize-none border-0 bg-transparent shadow-none focus-visible:ring-0"
        disabled={isPending}
        maxLength={4000}
      />
      <Button
        type="button"
        size="icon"
        className="h-[48px] w-[48px] shrink-0 rounded-lg"
        disabled={!value.trim() || isPending}
        onClick={onSubmit}
      >
        {isPending ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <Send className="h-4 w-4" />
        )}
      </Button>
    </div>
  );
}
