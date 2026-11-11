import { Gauge } from "lucide-react";

import type { QuotaStatus } from "../../types/workspace";
import { turnsLeftText } from "./quotaText";

/** The turns left today, in the header beside the usage meter; nothing when no quota applies. */
export function QuotaMeter({ quota }: { quota: QuotaStatus | null }) {
  const text = turnsLeftText(quota);
  if (!text) return null;
  return (
    <p className="flex items-center gap-1.5 px-2.5 py-1 text-xs text-fg2">
      <Gauge size={14} aria-hidden="true" />
      <span>{text}</span>
    </p>
  );
}
