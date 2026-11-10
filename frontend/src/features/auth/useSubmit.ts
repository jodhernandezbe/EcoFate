import { useCallback, useState } from "react";

import { ApiError } from "../../services/apiClient";

const GENERIC = "Something went wrong. Try again.";

/** The message to show for a failed request: the server's user-safe text, plus any wait asked. */
export function describe(error: unknown): string {
  if (!(error instanceof ApiError)) return GENERIC;
  if (error.status === 429 && error.retryAfter !== null) {
    return `${error.message} Try again in ${error.retryAfter} seconds.`;
  }
  return error.message;
}

/** Run one request at a time, keeping whether it is running and why it failed. */
export function useSubmit() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async <T,>(action: () => Promise<T>): Promise<T | undefined> => {
    setBusy(true);
    setError(null);
    try {
      return await action();
    } catch (failure) {
      setError(describe(failure));
      return undefined;
    } finally {
      setBusy(false);
    }
  }, []);
  return { busy, error, run, clearError: () => setError(null) };
}
