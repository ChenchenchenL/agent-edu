import type { ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { BookOpen, Compass, GraduationCap, MessageSquare, Shield } from "lucide-react";

interface LayoutProps {
  children: ReactNode;
}

export function Layout({ children }: LayoutProps) {
  const location = useLocation();
  const isSessionDetail = /^\/sessions\/[^/]+$/.test(location.pathname);
  const isGoalDetail = /^\/goals\/[^/]+$/.test(location.pathname);
  const isDetailPage = isSessionDetail || isGoalDetail;

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-10 border-b border-border-subtle bg-surface/90 backdrop-blur-md">
        <div className="mx-auto flex h-16 max-w-5xl items-center justify-between px-6">
          <Link
            to="/goals"
            className="group flex items-center gap-3 no-underline"
          >
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary-surface transition-colors group-hover:bg-primary/10">
              <BookOpen className="h-[18px] w-[18px] text-primary" />
            </div>
            <div className="flex flex-col">
              <span className="font-serif text-[17px] font-semibold leading-tight text-text-primary">
                Agent Edu
              </span>
              <span className="text-[11px] font-medium tracking-wide text-text-secondary uppercase">
                智能学习助手
              </span>
            </div>
          </Link>

          <nav className="flex items-center gap-4">
            <Link
              to="/goals"
              className={`flex items-center gap-1.5 text-xs transition-colors no-underline ${
                location.pathname.startsWith("/goals")
                  ? "text-primary"
                  : "text-text-secondary hover:text-text-primary"
              }`}
            >
              <Compass className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">学习目标</span>
            </Link>
            <Link
              to="/sessions"
              className={`flex items-center gap-1.5 text-xs transition-colors no-underline ${
                location.pathname.startsWith("/sessions")
                  ? "text-primary"
                  : "text-text-secondary hover:text-text-primary"
              }`}
            >
              <MessageSquare className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">学习会话</span>
            </Link>
            <Link
              to="/operator"
              className={`flex items-center gap-1.5 text-xs transition-colors no-underline ${
                location.pathname === "/operator"
                  ? "text-primary"
                  : "text-text-secondary hover:text-text-primary"
              }`}
            >
              <Shield className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">运营控制台</span>
            </Link>
            {!isDetailPage && (
              <div className="hidden items-center gap-1.5 text-xs text-text-secondary sm:flex">
                <GraduationCap className="h-3.5 w-3.5 text-accent-gold" />
                <span>引导式学习 · AI 导师</span>
              </div>
            )}
          </nav>
        </div>
      </header>

      <main
        className={`w-full flex-1 ${
          isSessionDetail
            ? "max-w-none px-0 py-0"
            : isGoalDetail
              ? "mx-auto max-w-6xl px-6 py-5"
              : "mx-auto max-w-5xl px-6 py-10"
        }`}
      >
        {children}
      </main>

      {!isSessionDetail && (
        <footer className="border-t border-border-subtle py-5">
          <div className="mx-auto max-w-5xl px-6 text-center text-xs text-text-secondary">
            Agent Edu · 专注深度理解，而非标准答案
          </div>
        </footer>
      )}
    </div>
  );
}
