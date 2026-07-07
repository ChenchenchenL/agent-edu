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

/**
 * Machine-readable error codes returned by the backend.
 *
 * The frontend uses these to decide how to surface the error to the user
 * (retry, back off, show a specific message). Unknown codes are preserved
 * as-is so new backend codes do not require a frontend release.
 */
export type ApiErrorCode =
  | "rate_limit_exceeded"
  | "provider_budget_exhausted"
  | "provider_timeout"
  | "provider_unavailable"
  | "circuit_open"
  | "background_job_overloaded"
  | "validation_error"
  | "not_found"
  | "service_unavailable"
  | (string & {});

class ApiError extends Error {
  status: number;
  code: ApiErrorCode;
  constructor(status: number, message: string, code: ApiErrorCode = "service_unavailable") {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

interface RequestOptions extends RequestInit {
  timeoutMs?: number;
}

async function parseErrorBody(res: Response): Promise<{ message: string; code: ApiErrorCode }> {
  try {
    const body = await res.json();
    if (body && typeof body === "object") {
      const err = (body as { error?: { code?: unknown; message?: unknown } }).error;
      if (err && typeof err === "object") {
        const code = typeof err.code === "string" ? err.code : "service_unavailable";
        const message = typeof err.message === "string" && err.message
          ? err.message
          : res.statusText;
        return { message, code };
      }
    }
  } catch {
    /* fall through to text fallback */
  }
  const text = await res.text().catch(() => "");
  return { message: text || res.statusText, code: "service_unavailable" };
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
      const { message, code } = await parseErrorBody(res);
      throw new ApiError(res.status, message, code);
    }

    return res.json() as Promise<T>;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError(
        504,
        "Request timed out. Check that the API is reachable at " + API_BASE,
        "provider_timeout",
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
