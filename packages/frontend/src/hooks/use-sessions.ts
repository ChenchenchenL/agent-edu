import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { get, post } from "@/api/client";
import type {
  Session,
  CreateSessionRequest,
  MessageHistoryResponse,
  MessageRequest,
  MessageResponse,
} from "@/types/session";

export function useSessions() {
  return useQuery<Session[]>({
    queryKey: ["sessions"],
    queryFn: () => get<Session[]>("/sessions"),
  });
}

export function useSession(sessionId: string) {
  return useQuery<Session>({
    queryKey: ["sessions", sessionId],
    queryFn: () => get<Session>(`/sessions/${sessionId}`),
    enabled: !!sessionId,
  });
}

export function useCreateSession() {
  const queryClient = useQueryClient();
  return useMutation<Session, Error, CreateSessionRequest>({
    mutationFn: (data) => post<Session>("/sessions", data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["sessions"] });
    },
  });
}

export function useSessionMessages(sessionId: string) {
  return useQuery<MessageHistoryResponse>({
    queryKey: ["sessions", sessionId, "messages"],
    queryFn: () =>
      get<MessageHistoryResponse>(`/sessions/${sessionId}/messages?limit=50`),
    enabled: !!sessionId,
  });
}

export function useSendMessage(sessionId: string) {
  const queryClient = useQueryClient();
  return useMutation<MessageResponse, Error, MessageRequest>({
    mutationFn: (data) =>
      post<MessageResponse>(`/sessions/${sessionId}/messages`, data),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["sessions", sessionId, "messages"],
      });
      void queryClient.invalidateQueries({
        queryKey: ["sessions", sessionId],
      });
    },
  });
}
