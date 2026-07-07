import { BrowserRouter, Routes, Route, Navigate, Outlet } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Layout } from "@/pages/layout";
import { GoalsPage } from "@/pages/goals/goals-page";
import { GoalDetailPage } from "@/pages/goals/goal-detail-page";
import { SessionsPage } from "@/pages/sessions/sessions-page";
import { LearningWorkspacePage } from "@/pages/learning/learning-workspace-page";
import { OperatorDashboardPage } from "@/pages/operator/operator-dashboard-page";
import { OperatorShell } from "@/pages/operator/components/operator-shell";
import { MemoryDetailPage } from "@/pages/operator/memory-detail-page";
import { ReflectionDetailPage } from "@/pages/operator/reflection-detail-page";
import { SkillDetailPage } from "@/pages/operator/skill-detail-page";
import { AuditDetailPage } from "@/pages/operator/audit-detail-page";
import { QuizAttemptsPage } from "@/pages/operator/quiz-attempts-page";
import { MisconceptionsPage } from "@/pages/operator/misconceptions-page";
import { LearningGainsPage } from "@/pages/operator/learning-gains-page";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
    },
  },
});

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Layout>
          <Routes>
            <Route path="/" element={<Navigate to="/goals" replace />} />
            <Route path="/goals" element={<GoalsPage />} />
            <Route path="/goals/:id" element={<GoalDetailPage />} />
            <Route path="/sessions" element={<SessionsPage />} />
            <Route path="/sessions/:id" element={<LearningWorkspacePage />} />
            <Route path="/operator" element={<OperatorShell><Outlet /></OperatorShell>}>
              <Route index element={<OperatorDashboardPage />} />
              <Route path="memory/:type/:id" element={<MemoryDetailPage />} />
              <Route path="reflections/:id" element={<ReflectionDetailPage />} />
              <Route path="skills/artifacts/:id" element={<SkillDetailPage />} />
              <Route path="audit/events/:id" element={<AuditDetailPage />} />
              <Route path="quiz/attempts" element={<QuizAttemptsPage />} />
              <Route path="quiz/misconceptions" element={<MisconceptionsPage />} />
              <Route path="quiz/learning-gains" element={<LearningGainsPage />} />
            </Route>
          </Routes>
        </Layout>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

export default App;
