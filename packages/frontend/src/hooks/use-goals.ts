import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { get, post } from "@/api/client";
import { ensureProfile } from "@/lib/learner-auth";
import type {
  CreateGoalRequest,
  LearnerGoal,
  StudyPlanSummary,
} from "@/types/goal";
import type { DailyTask } from "@/types/task";

const PLAN_GENERATION_TIMEOUT_MS = 120_000;

export function useLearnerProfile() {
  return useQuery<{ id: string; access_key: string }>({
    queryKey: ["learner-profile"],
    queryFn: () => ensureProfile(),
    staleTime: Infinity,
  });
}

export function useGoals(profileId: string | null) {
  return useQuery<LearnerGoal[]>({
    queryKey: ["goals", profileId],
    queryFn: () => get<LearnerGoal[]>(`/learner-profiles/${profileId}/goals`),
    enabled: !!profileId,
  });
}

export function useGoal(goalId: string) {
  return useQuery<LearnerGoal>({
    queryKey: ["goal", goalId],
    queryFn: () => get<LearnerGoal>(`/goals/${goalId}`),
    enabled: !!goalId,
  });
}

export function useCreateGoal(profileId: string) {
  const queryClient = useQueryClient();
  return useMutation<LearnerGoal, Error, CreateGoalRequest>({
    mutationFn: (data) =>
      post<LearnerGoal>(`/learner-profiles/${profileId}/goals`, data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["goals", profileId] });
    },
  });
}

export function useGeneratePlan() {
  const queryClient = useQueryClient();
  return useMutation<StudyPlanSummary, Error, string>({
    mutationFn: (goalId) =>
      post<StudyPlanSummary>(
        `/goals/${goalId}/plans`,
        { trigger_source: "learner_ui" },
        PLAN_GENERATION_TIMEOUT_MS,
      ),
    onSuccess: (_data, goalId) => {
      void queryClient.invalidateQueries({
        queryKey: ["goal-plans", goalId],
      });
      void queryClient.invalidateQueries({
        queryKey: ["goal-tasks", goalId],
      });
    },
  });
}

export function useGoalPlans(goalId: string) {
  return useQuery<StudyPlanSummary[]>({
    queryKey: ["goal-plans", goalId],
    queryFn: () => get<StudyPlanSummary[]>(`/goals/${goalId}/plans`),
    enabled: !!goalId,
  });
}

export function useGoalTasks(goalId: string) {
  return useQuery<DailyTask[]>({
    queryKey: ["goal-tasks", goalId],
    queryFn: () => get<DailyTask[]>(`/goals/${goalId}/tasks`),
    enabled: !!goalId,
  });
}

export function useMaterializeToday(goalId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      post(`/goals/${goalId}/autonomy/materialize-today`, {}),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["goal-tasks", goalId],
      });
    },
  });
}
