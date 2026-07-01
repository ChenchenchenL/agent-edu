import type { ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { BookOpen, GraduationCap } from "lucide-react";

interface LayoutProps {
  children: ReactNode;
}

export function Layout({ children }: LayoutProps) {
  const location = useLocation();
  const isSessionDetail = /^\/sessions\/[^/]+$/.test(location.pathname);

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-10 border-b border-border-subtle bg-surface/90 backdrop-blur-md">
        <div className="mx-auto flex h-16 max-w-5xl items-center justify-between px-6">
          <Link
            to="/sessions"
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

          {!isSessionDetail && (
            <div className="hidden items-center gap-1.5 text-xs text-text-secondary sm:flex">
              <GraduationCap className="h-3.5 w-3.5 text-accent-gold" />
              <span>引导式学习 · AI 导师</span>
            </div>
          )}
        </div>
      </header>

      <main
        className={`mx-auto w-full flex-1 px-6 ${
          isSessionDetail ? "max-w-5xl py-5" : "max-w-5xl py-10"
        }`}
      >
        {children}
      </main>

      <footer className="border-t border-border-subtle py-5">
        <div className="mx-auto max-w-5xl px-6 text-center text-xs text-text-secondary">
          Agent Edu · 专注深度理解，而非标准答案
        </div>
      </footer>
    </div>
  );
}
