import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { get, post } from "@/api/client";

export function useSkillDetail(artifactId: string) {
  return useQuery({
    queryKey: ["operator", "skill", artifactId],
    queryFn: () => get<any>(`/skills/artifacts/${artifactId}`),
  });
}

export function useSkillUsage(artifactId: string) {
  return useQuery({
    queryKey: ["operator", "skill", artifactId, "usage"],
    queryFn: () => get<any>(`/skills/artifacts/${artifactId}/usage`),
  });
}

export function useSkillAction() {
  const queryClient = useQueryClient();

  const suppress = useMutation({
    mutationFn: (args: { artifactId: string; reason_code: string }) =>
      post(`/skills/artifacts/${args.artifactId}/deactivate`, {
        reason_code: args.reason_code,
      }),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ["operator", "skill", variables.artifactId] });
    },
  });

  return { suppress };
}
