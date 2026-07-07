import { useQuery } from "@tanstack/react-query";
import { get } from "@/api/client";
import type {
  AdaptivePolicyAuditTrailResponse,
  LearningGainDashboardResponse,
  MisconceptionTrendResponse,
  OperatorAttemptBrowseResponse,
  OperatorGradingQueueResponse,
} from "@/types/quiz-observability";

export interface PaginatedParams {
  limit?: number;
  offset?: number;
}

function buildQuery(params: PaginatedParams): string {
  const search = new URLSearchParams();
  if (params.limit != null) search.set("limit", String(params.limit));
  if (params.offset != null) search.set("offset", String(params.offset));
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

export function useOperatorAttempts(params: PaginatedParams = {}) {
  return useQuery<OperatorAttemptBrowseResponse>({
    queryKey: ["operator", "quiz", "attempts", params.limit, params.offset],
    queryFn: () =>
      get<OperatorAttemptBrowseResponse>(
        `/operator/quizzes/attempts${buildQuery(params)}`,
      ),
  });
}

export function useOperatorGradingQueue(params: PaginatedParams = {}) {
  return useQuery<OperatorGradingQueueResponse>({
    queryKey: ["operator", "quiz", "grading", "needs-review", params.limit, params.offset],
    queryFn: () =>
      get<OperatorGradingQueueResponse>(
        `/operator/quizzes/grading/needs-review${buildQuery(params)}`,
      ),
  });
}

export function useMisconceptionTrend(limit: number = 1000) {
  return useQuery<MisconceptionTrendResponse>({
    queryKey: ["operator", "quiz", "misconceptions", "trend", limit],
    queryFn: () =>
      get<MisconceptionTrendResponse>(
        `/operator/quizzes/misconceptions/trend?limit=${limit}`,
      ),
  });
}

export function useAdaptivePolicyAudit(params: PaginatedParams = {}) {
  return useQuery<AdaptivePolicyAuditTrailResponse>({
    queryKey: ["operator", "quiz", "adaptive-policy", "audit", params.limit, params.offset],
    queryFn: () =>
      get<AdaptivePolicyAuditTrailResponse>(
        `/operator/quizzes/adaptive-policy/audit${buildQuery(params)}`,
      ),
  });
}

export function useLearningGainDashboard(limit: number = 1000) {
  return useQuery<LearningGainDashboardResponse>({
    queryKey: ["operator", "skills", "learning-gain", limit],
    queryFn: () =>
      get<LearningGainDashboardResponse>(
        `/operator/skills/learning-gain?limit=${limit}`,
      ),
  });
}
