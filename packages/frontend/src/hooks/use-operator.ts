import { useQuery } from "@tanstack/react-query";
import { get } from "@/api/client";
import type {
  AuditEvent,
  GuardrailsStatus,
  ProposalQueueResponse,
  ReflectionReviewQueueResponse,
  SkillCuratorRecommendation,
} from "@/types/operator";

export function useAuditEvents(params?: {
  eventType?: string;
  resourceType?: string;
  limit?: number;
}) {
  const searchParams = new URLSearchParams();
  if (params?.eventType) searchParams.set("event_type", params.eventType);
  if (params?.resourceType) searchParams.set("resource_type", params.resourceType);
  if (params?.limit) searchParams.set("limit", String(params.limit));
  const qs = searchParams.toString();
  return useQuery<AuditEvent[]>({
    queryKey: ["audit", "events", params],
    queryFn: () => get<AuditEvent[]>(`/audit/events${qs ? `?${qs}` : ""}`),
  });
}

export function useGuardrailsStatus() {
  return useQuery<GuardrailsStatus>({
    queryKey: ["guardrails", "status"],
    queryFn: () => get<GuardrailsStatus>("/guardrails/status"),
    refetchInterval: 30_000,
  });
}

export function useReflectionReviewQueue(limit = 10) {
  return useQuery<ReflectionReviewQueueResponse>({
    queryKey: ["reflections", "review-queue", limit],
    queryFn: () =>
      get<ReflectionReviewQueueResponse>(
        `/reflections/review-queue?limit=${limit}`,
      ),
  });
}

export function useProposalReviewQueue(limit = 10) {
  return useQuery<ProposalQueueResponse>({
    queryKey: ["proposals", "review-queue", limit],
    queryFn: () =>
      get<ProposalQueueResponse>(`/proposals/review-queue?limit=${limit}`),
  });
}

export function useCuratorRecommendations(limit = 10) {
  return useQuery<SkillCuratorRecommendation[]>({
    queryKey: ["skill-curator-recommendations", limit],
    queryFn: () =>
      get<SkillCuratorRecommendation[]>(
        `/skill-curator-recommendations?limit=${limit}`,
      ),
  });
}
