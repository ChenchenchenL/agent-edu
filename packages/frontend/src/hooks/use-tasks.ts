import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { get, post } from "@/api/client";
import type { DailyTask, ExecuteDailyTaskResponse } from "@/types/task";

export function useGoalTasks(goalId: string | null) {
  return useQuery<DailyTask[]>({
    queryKey: ["goals", goalId, "tasks"],
    queryFn: () => get<DailyTask[]>(`/goals/${goalId}/tasks`),
    enabled: !!goalId,
  });
}

export function useTask(taskId: string | null) {
  return useQuery<DailyTask>({
    queryKey: ["tasks", taskId],
    queryFn: () => get<DailyTask>(`/tasks/${taskId}`),
    enabled: !!taskId,
  });
}

export function useExecuteTask() {
  const queryClient = useQueryClient();
  return useMutation<ExecuteDailyTaskResponse, Error, string>({
    mutationFn: (taskId) => post<ExecuteDailyTaskResponse>(`/tasks/${taskId}/execute`, {}),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["goals"] });
    },
  });
}
