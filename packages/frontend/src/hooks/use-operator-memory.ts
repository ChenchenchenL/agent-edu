import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { get, post, patch } from "@/api/client";

export function useMemoryDetail(memoryType: "knowledge" | "behavior", memoryId: string) {
  return useQuery({
    queryKey: ["operator", "memory", memoryType, memoryId],
    queryFn: () => get<any>(`/memory/${memoryType}/${memoryId}`),
  });
}

export function useMemoryEvidenceLinks(memoryType: "knowledge" | "behavior", memoryId: string) {
  return useQuery({
    queryKey: ["operator", "memory", memoryType, memoryId, "evidence"],
    queryFn: () => get<any[]>(`/memory/${memoryType}/${memoryId}/evidence-links`),
  });
}

export function useMemoryGovernanceDecisions(memoryType: "knowledge" | "behavior", memoryId: string) {
  return useQuery({
    queryKey: ["operator", "memory", memoryType, memoryId, "decisions"],
    queryFn: () => get<any[]>(`/memory/${memoryType}/${memoryId}/governance-decisions`),
  });
}

export function useMemoryAnnotations(memoryType: "knowledge" | "behavior", memoryId: string) {
  return useQuery({
    queryKey: ["operator", "memory", memoryType, memoryId, "annotations"],
    queryFn: () => get<any[]>(`/memory/${memoryType}/${memoryId}/annotations`),
  });
}

export function useMemoryAction() {
  const queryClient = useQueryClient();

  const suppress = useMutation({
    mutationFn: (args: { memoryType: "knowledge" | "behavior"; memoryId: string; reason_code: string; reason_note?: string }) =>
      post(`/memory/suppress`, {
        memory_type: args.memoryType,
        memory_id: args.memoryId,
        reason_code: args.reason_code,
        reason_note: args.reason_note,
      }),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ["operator", "memory", variables.memoryType, variables.memoryId] });
      queryClient.invalidateQueries({ queryKey: ["operator", "memory", variables.memoryType, variables.memoryId, "decisions"] });
    },
  });

  const restore = useMutation({
    mutationFn: (args: { memoryType: "knowledge" | "behavior"; memoryId: string; reason_code: string; reason_note?: string }) =>
      post(`/memory/restore`, {
        memory_type: args.memoryType,
        memory_id: args.memoryId,
        reason_code: args.reason_code,
        reason_note: args.reason_note,
      }),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ["operator", "memory", variables.memoryType, variables.memoryId] });
      queryClient.invalidateQueries({ queryKey: ["operator", "memory", variables.memoryType, variables.memoryId, "decisions"] });
    },
  });

  const annotate = useMutation({
    mutationFn: (args: { memoryType: "knowledge" | "behavior"; memoryId: string; annotation_key: string; annotation_value: any; reason_code: string; reason_note?: string }) =>
      post(`/memory/annotate`, {
        memory_type: args.memoryType,
        memory_id: args.memoryId,
        annotation_key: args.annotation_key,
        annotation_value: args.annotation_value,
        reason_code: args.reason_code,
        reason_note: args.reason_note,
      }),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ["operator", "memory", variables.memoryType, variables.memoryId, "annotations"] });
    },
  });

  return { suppress, restore, annotate };
}
