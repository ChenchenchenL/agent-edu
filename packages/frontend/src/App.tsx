import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Layout } from "@/pages/layout";
import { GoalsPage } from "@/pages/goals/goals-page";
import { GoalDetailPage } from "@/pages/goals/goal-detail-page";
import { SessionsPage } from "@/pages/sessions/sessions-page";
import { LearningWorkspacePage } from "@/pages/learning/learning-workspace-page";
import { OperatorDashboardPage } from "@/pages/operator/operator-dashboard-page";

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
            <Route path="/operator" element={<OperatorDashboardPage />} />
          </Routes>
        </Layout>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

export default App;
