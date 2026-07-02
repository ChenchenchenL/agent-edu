import { useQuery } from "@tanstack/react-query";
import { get } from "@/api/client";

export function useAuditDetail(eventId: string) {
  return useQuery({
    queryKey: ["operator", "audit", eventId],
    queryFn: () => get<any>(`/audit/events/${eventId}`),
  });
}
