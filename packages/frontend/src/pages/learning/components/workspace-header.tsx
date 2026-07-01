import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import type { Session } from "@/types/session";

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

interface WorkspaceHeaderProps {
  session: Session;
}

export function WorkspaceHeader({ session }: WorkspaceHeaderProps) {
  return (
    <div className="flex items-center gap-3 border-b border-border-subtle px-5 py-4">
      <Link to="/sessions">
        <Button variant="ghost" size="icon" className="shrink-0">
          <ArrowLeft className="h-4 w-4" />
        </Button>
      </Link>
      <div className="min-w-0 flex-1">
        <p className="text-[11px] font-semibold tracking-widest text-accent-gold uppercase">
          学习工作台
        </p>
        <h1 className="truncate font-serif text-lg font-semibold text-text-primary">
          {session.title || session.subject || "学习会话"}
        </h1>
        <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-text-secondary">
          {session.subject && <span>{session.subject}</span>}
          <Badge variant="outline" className="text-[10px] font-normal">
            {statusLabel(session.status)}
          </Badge>
        </div>
      </div>
    </div>
  );
}
