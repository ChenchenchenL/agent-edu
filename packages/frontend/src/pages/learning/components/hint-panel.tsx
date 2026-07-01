import { useState } from "react";
import { Lightbulb, Loader2, Info } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";

interface HintPanelProps {
  onRequestHint: (content: string) => void;
  isPending: boolean;
}

const HINT_SUGGESTIONS = [
  "我对这个概念还不太理解，请给我一点提示",
  "我卡在这一步了，能引导我思考方向吗？",
  "请帮我梳理一下解题思路，不要直接给答案",
];

export function HintPanel({ onRequestHint, isPending }: HintPanelProps) {
  const [content, setContent] = useState("");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = content.trim();
    if (!trimmed) return;
    onRequestHint(trimmed);
    setContent("");
  }

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-border-subtle px-4 py-3">
        <div className="flex items-center gap-2">
          <Lightbulb className="h-4 w-4 text-accent-gold" />
          <h2 className="font-medium text-text-primary">学习提示</h2>
        </div>
        <p className="mt-1 text-xs text-text-secondary">
          请求引导式提示，系统不会直接给出答案
        </p>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-4">
        <div className="flex items-start gap-2 rounded-lg bg-primary-surface/50 px-3 py-2.5">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
          <p className="text-xs leading-relaxed text-text-secondary">
            提示分为三个级别：概念提示 → 步骤引导 → 针对性提示。你在练习题中提交答案后，系统会根据你的作答给出更精准的提示。
          </p>
        </div>

        <form onSubmit={handleSubmit} className="mt-4 space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="hint-content" className="text-xs">
              描述你的困惑
            </Label>
            <Textarea
              id="hint-content"
              placeholder="例如：我不理解为什么矩阵乘法不满足交换律…"
              value={content}
              onChange={(e) => setContent(e.target.value)}
              className="min-h-[100px] text-sm"
              disabled={isPending}
              maxLength={4000}
            />
          </div>

          <Button
            type="submit"
            className="w-full"
            size="sm"
            disabled={!content.trim() || isPending}
          >
            {isPending ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                获取中…
              </>
            ) : (
              <>
                <Lightbulb className="h-3.5 w-3.5" />
                获取提示
              </>
            )}
          </Button>
        </form>

        <div className="mt-5 space-y-2">
          <p className="text-[11px] font-medium tracking-wide text-text-secondary uppercase">
            快速提问
          </p>
          <div className="space-y-1.5">
            {HINT_SUGGESTIONS.map((suggestion) => (
              <button
                key={suggestion}
                type="button"
                disabled={isPending}
                onClick={() => onRequestHint(suggestion)}
                className="w-full rounded-lg border border-border-subtle bg-surface px-3 py-2 text-left text-xs leading-relaxed text-text-secondary transition-colors hover:border-primary/20 hover:text-text-primary disabled:opacity-50"
              >
                {suggestion}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
