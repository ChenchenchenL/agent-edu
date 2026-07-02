const OPERATOR_CREDENTIAL_KEY = "agent-edu:operator-key";

export function getStoredOperatorKey(): string | null {
  try {
    return localStorage.getItem(OPERATOR_CREDENTIAL_KEY) || sessionStorage.getItem(OPERATOR_CREDENTIAL_KEY);
  } catch {
    return null;
  }
}

export function storeOperatorKey(key: string, persist: boolean = false): void {
  if (persist) {
    localStorage.setItem(OPERATOR_CREDENTIAL_KEY, key);
    sessionStorage.removeItem(OPERATOR_CREDENTIAL_KEY);
  } else {
    sessionStorage.setItem(OPERATOR_CREDENTIAL_KEY, key);
    localStorage.removeItem(OPERATOR_CREDENTIAL_KEY);
  }
}

export function clearOperatorKey(): void {
  localStorage.removeItem(OPERATOR_CREDENTIAL_KEY);
  sessionStorage.removeItem(OPERATOR_CREDENTIAL_KEY);
}
