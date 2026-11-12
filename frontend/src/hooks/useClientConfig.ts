import { useEffect, useState } from "react";

import { getClientConfig } from "../services/apiClient";
import type { ClientConfig } from "../types/workspace";

/** Display settings from the server (band boundaries, model name, chips); null until loaded. */
export function useClientConfig(): ClientConfig | null {
  const [config, setConfig] = useState<ClientConfig | null>(null);
  useEffect(() => {
    let live = true;
    getClientConfig()
      .then((value) => {
        if (live) setConfig(value);
      })
      .catch(() => undefined); // the interface works without them; chips and labels stay hidden
    return () => {
      live = false;
    };
  }, []);
  return config;
}
