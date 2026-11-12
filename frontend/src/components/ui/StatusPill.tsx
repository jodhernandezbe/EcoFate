import { BAND_LOOK, isBand, NEUTRAL_PILL } from "../../lib/band";
import type { Status } from "../../types/workspace";

/** Screening band as a coloured pill that also says it in words (colour is never the only cue); `label` replaces the default words. */
export function StatusPill({ status, label }: { status: Status | null; label?: string }) {
  const known = isBand(status);
  const words = label ?? (status === null ? "Not computed" : known ? BAND_LOOK[status].label : "not reported");
  return (
    <span
      className={`inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${known ? BAND_LOOK[status].pill : NEUTRAL_PILL}`}
      data-status={known ? status : "none"}
    >
      {words}
    </span>
  );
}
