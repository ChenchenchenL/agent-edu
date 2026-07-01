import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { get, post } from "@/api/client";
import type {
  GenerateQuizRequest,
  QuizDraft,
  QuizSummary,
} from "@/types/quiz";

export function useSessionQuizzes(sessionId: string) {
  return useQuery<QuizSummary[]>({
    queryKey: ["sessions", sessionId, "quizzes"],
    queryFn: () => get<QuizSummary[]>(`/sessions/${sessionId}/quizzes`),
    enabled: !!sessionId,
  });
}

export function useQuizDetail(sessionId: string, quizId: string | null) {
  return useQuery<QuizDraft>({
    queryKey: ["sessions", sessionId, "quizzes", quizId],
    queryFn: () =>
      get<QuizDraft>(`/sessions/${sessionId}/quizzes/${quizId}`),
    enabled: !!sessionId && !!quizId,
  });
}

export function useGenerateQuiz(sessionId: string) {
  const queryClient = useQueryClient();
  return useMutation<QuizDraft, Error, GenerateQuizRequest>({
    mutationFn: (data) =>
      post<QuizDraft>(`/sessions/${sessionId}/quizzes/generate`, data),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["sessions", sessionId, "quizzes"],
      });
    },
  });
}
