import { getStoredProfile } from "@/lib/learner-auth";
import { getStoredOperatorKey } from "@/lib/operator-auth";

const DEFAULT_API_ORIGIN = "http://localhost:8000";
const DEFAULT_TIMEOUT_MS = 60_000;

function resolveApiBase(): string {
  const explicitBase = import.meta.env.VITE_API_BASE_URL?.trim();
  if (explicitBase) {
    return explicitBase.replace(/\/$/, "");
  }

  if (import.meta.env.DEV) {
    return "/api/v1";
  }

  return `${DEFAULT_API_ORIGIN}/api/v1`;
}

const API_BASE = resolveApiBase();

class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

interface RequestOptions extends RequestInit {
  timeoutMs?: number;
}

async function request<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const { timeoutMs, ...init } = options;
  const controller = new AbortController();
  const timeoutId = window.setTimeout(
    () => controller.abort(),
    timeoutMs ?? DEFAULT_TIMEOUT_MS,
  );
  const url = `${API_BASE}${path}`;

  const learnerProfile = getStoredProfile();
  const operatorKey = getStoredOperatorKey();
  try {
    const res = await fetch(url, {
      headers: {
        "Content-Type": "application/json",
        ...(learnerProfile ? { "X-Learner-Key": learnerProfile.access_key } : {}),
        ...(operatorKey ? { "X-Operator-Key": operatorKey } : {}),
        ...init.headers,
      },
      ...init,
      signal: init.signal ?? controller.signal,
    });

    if (!res.ok) {
      const body = await res.text().catch(() => "");
      throw new ApiError(res.status, body || res.statusText);
    }

    return res.json() as Promise<T>;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError(
        504,
        "Request timed out. Check that the API is reachable at " + API_BASE,
      );
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

export function get<T>(path: string): Promise<T> {
  return request<T>(path);
}

export function post<T>(path: string, body: unknown, timeoutMs?: number): Promise<T> {
  return request<T>(path, {
    method: "POST",
    body: JSON.stringify(body),
    ...(timeoutMs != null ? { timeoutMs } : {}),
  });
}

export function patch<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export { ApiError, API_BASE };
