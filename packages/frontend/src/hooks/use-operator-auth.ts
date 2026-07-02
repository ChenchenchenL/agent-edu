import { useState, useCallback, useEffect } from "react";
import { getStoredOperatorKey, storeOperatorKey, clearOperatorKey } from "@/lib/operator-auth";

export function useOperatorAuth() {
  const [key, setKey] = useState<string | null>(getStoredOperatorKey());

  const login = useCallback((newKey: string, persist: boolean = false) => {
    storeOperatorKey(newKey, persist);
    setKey(newKey);
  }, []);

  const logout = useCallback(() => {
    clearOperatorKey();
    setKey(null);
  }, []);

  // Sync with storage on mount (in case another tab changed it, though this handles simple cases)
  useEffect(() => {
    const handleStorage = () => {
      setKey(getStoredOperatorKey());
    };
    window.addEventListener("storage", handleStorage);
    return () => window.removeEventListener("storage", handleStorage);
  }, []);

  return {
    isAuthenticated: !!key,
    key,
    login,
    logout,
  };
}
