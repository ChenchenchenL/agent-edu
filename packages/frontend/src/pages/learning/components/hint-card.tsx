import { Lightbulb, ShieldCheck, AlertCircle } from "lucide-react";
import type { HintPayload } from "@/types/session";
import { hintLevelLabel } from "@/pages/learning/lib/labels";

interface HintCardProps {
  payload: HintPayload;
}

export function HintCard({ payload }: HintCardProps) {
  return (
    <div className="notebook-margin mt-3 space-y-2.5 rounded-md bg-primary-surface/40 px-3 py-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 text-xs font-medium text-text-primary">
          <Lightbulb className="h-3.5 w-3.5 text-primary" />
          学习提示
        </div>
        <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary">
          {hintLevelLabel(payload.hint_level)}
        </span>
      </div>

      {payload.direct_answer_given && (
        <div className="flex items-start gap-2 rounded-md bg-error/5 px-2.5 py-2 text-xs text-error">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          此回复可能包含直接答案，建议先尝试独立思考
        </div>
      )}

      {!payload.direct_answer_given && (
        <div className="flex items-center gap-1.5 text-[11px] text-success">
          <ShieldCheck className="h-3 w-3" />
          引导式提示，未直接给出答案
        </div>
      )}

      <p className="text-xs leading-relaxed text-text-primary">
        <span className="font-medium">下一步：</span>
        {payload.next_step_hint}
      </p>

      {payload.key_principle && (
        <p className="text-xs leading-relaxed text-text-secondary">
          <span className="font-medium text-text-primary">关键原理：</span>
          {payload.key_principle}
        </p>
      )}

      {payload.pitfall && (
        <p className="text-xs leading-relaxed text-text-secondary">
          <span className="font-medium text-text-primary">注意：</span>
          {payload.pitfall}
        </p>
      )}

      {payload.encouragement && (
        <p className="border-t border-border-subtle pt-2 text-xs italic text-text-secondary">
          {payload.encouragement}
        </p>
      )}
    </div>
  );
}
