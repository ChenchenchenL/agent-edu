import {
  BookOpen,
  Lightbulb,
  AlertTriangle,
  ArrowRight,
  PenLine,
} from "lucide-react";
import type { ExplanationPayload } from "@/types/session";

interface ExplanationCardProps {
  payload: ExplanationPayload;
}

export function ExplanationCard({ payload }: ExplanationCardProps) {
  return (
    <div className="notebook-margin mt-3 space-y-3 rounded-md bg-accent-gold-surface/60 px-3 py-3">
      <div className="flex items-center gap-1.5 text-xs font-medium text-text-primary">
        <Lightbulb className="h-3.5 w-3.5 text-accent-gold" />
        知识讲解
      </div>

      <section className="space-y-1">
        <p className="flex items-center gap-1 text-[11px] font-medium tracking-wide text-text-secondary uppercase">
          <BookOpen className="h-3 w-3" />
          定义
        </p>
        <p className="text-xs leading-relaxed text-text-primary">
          {payload.definition}
        </p>
      </section>

      {payload.core_principles.length > 0 && (
        <section className="space-y-1">
          <p className="text-[11px] font-medium tracking-wide text-text-secondary uppercase">
            核心原理
          </p>
          <ul className="space-y-1">
            {payload.core_principles.map((principle) => (
              <li
                key={principle}
                className="flex gap-2 text-xs leading-relaxed text-text-primary"
              >
                <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-accent-gold" />
                {principle}
              </li>
            ))}
          </ul>
        </section>
      )}

      {payload.worked_example && (
        <section className="space-y-1">
          <p className="flex items-center gap-1 text-[11px] font-medium tracking-wide text-text-secondary uppercase">
            <PenLine className="h-3 w-3" />
            例题
          </p>
          <p className="text-xs leading-relaxed text-text-primary">
            {payload.worked_example}
          </p>
        </section>
      )}

      {payload.common_mistake && (
        <section className="space-y-1">
          <p className="flex items-center gap-1 text-[11px] font-medium tracking-wide text-text-secondary uppercase">
            <AlertTriangle className="h-3 w-3 text-error" />
            常见误区
          </p>
          <p className="text-xs leading-relaxed text-text-secondary">
            {payload.common_mistake}
          </p>
        </section>
      )}

      {payload.next_step && (
        <section className="flex items-start gap-2 rounded-md bg-primary-surface/50 px-2.5 py-2">
          <ArrowRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
          <p className="text-xs leading-relaxed text-text-primary">
            <span className="font-medium">下一步：</span>
            {payload.next_step}
          </p>
        </section>
      )}
    </div>
  );
}
