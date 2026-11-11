import { useCallback, useEffect, useState } from "react";

import { clearKey, getKeysStatus, saveKey } from "../services/apiClient";
import type { KeysStatusResponse } from "../types/workspace";

function message(error: unknown): string {
  return error instanceof Error ? error.message : "Something went wrong. Try again.";
}

/** How the last save or clear of the user's key went; its text never holds any part of a key. */
export interface KeyOutcome {
  kind: "success" | "error";
  message: string;
}

/**
 * Whether the signed-in user has an OpenAI key stored, and which data services this installation
 * provides (never a key), with save and clear actions and the last outcome.
 */
export function useKeyStatus() {
  const [statuses, setStatuses] = useState<KeysStatusResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<KeyOutcome | undefined>(undefined);
  const [loadError, setLoadError] = useState<string | null>(null);

  const run = useCallback(async (done: string, action: () => Promise<unknown>) => {
    setBusy(true);
    setOutcome(undefined);
    try {
      await action();
      setStatuses(await getKeysStatus());
      setOutcome({ kind: "success", message: done });
      return true;
    } catch (failure) {
      setOutcome({ kind: "error", message: message(failure) });
      return false;
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    let live = true;
    getKeysStatus()
      .then((value) => {
        if (live) setStatuses(value);
      })
      .catch((failure: unknown) => {
        if (live) setLoadError(message(failure));
      });
    return () => {
      live = false;
    };
  }, []);

  const save = useCallback((key: string) => run("Key saved.", () => saveKey(key)), [run]);
  const clear = useCallback(() => run("Key cleared.", () => clearKey()), [run]);
  return { statuses, busy, outcome, loadError, save, clear };
}
