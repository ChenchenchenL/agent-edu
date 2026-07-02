const LEARNER_PROFILE_KEY = "agent-edu:learner-profile";

export interface LearnerProfileCredentials {
  id: string;
  access_key: string;
}

export function getStoredProfile(): LearnerProfileCredentials | null {
  try {
    const raw = localStorage.getItem(LEARNER_PROFILE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<LearnerProfileCredentials>;
    if (parsed.id && parsed.access_key) {
      return { id: parsed.id, access_key: parsed.access_key };
    }
    return null;
  } catch {
    return null;
  }
}

export function storeProfile(id: string, access_key: string): void {
  localStorage.setItem(
    LEARNER_PROFILE_KEY,
    JSON.stringify({ id, access_key } satisfies LearnerProfileCredentials),
  );
}

export function clearProfile(): void {
  localStorage.removeItem(LEARNER_PROFILE_KEY);
}

export async function ensureProfile(): Promise<LearnerProfileCredentials> {
  const stored = getStoredProfile();
  if (stored) return stored;

  const res = await fetch("/api/v1/learner-profiles", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  if (!res.ok) {
    throw new Error(`Failed to create learner profile: ${res.status}`);
  }
  const data = (await res.json()) as { id: string; access_key: string };
  storeProfile(data.id, data.access_key);
  return { id: data.id, access_key: data.access_key };
}
