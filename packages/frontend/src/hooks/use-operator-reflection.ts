import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { get, post } from "@/api/client";

export function useReflectionDetail(reflectionId: string) {
  return useQuery({
    queryKey: ["operator", "reflection", reflectionId],
    queryFn: () => get<any>(`/reflections/${reflectionId}`),
  });
}

export function useReflectionOutcomeEvaluation(reflectionId: string) {
  return useQuery({
    queryKey: ["operator", "reflection", reflectionId, "outcome-evaluation"],
    queryFn: () => get<any>(`/reflections/${reflectionId}/outcome-evaluation`),
    retry: 0,
  });
}

export function useReflectionReviewHistory(reflectionId: string) {
  return useQuery({
    queryKey: ["operator", "reflection", reflectionId, "reviews"],
    queryFn: () => get<any[]>(`/reflections/${reflectionId}/reviews`),
  });
}

export function useReflectionRelatedProposals(reflectionId: string) {
  return useQuery({
    queryKey: ["operator", "reflection", reflectionId, "proposals"],
    queryFn: () => get<any[]>(`/reflections/${reflectionId}/proposals`),
  });
}

export function useReflectionAction() {
  const queryClient = useQueryClient();

  const resolve = useMutation({
    mutationFn: (args: { reflectionId: string; resolution: string }) =>
      post(`/reflections/${args.reflectionId}/resolve`, {
        resolution_status: args.resolution,
      }),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ["operator", "reflection", variables.reflectionId] });
    },
  });

  return { resolve };
}
