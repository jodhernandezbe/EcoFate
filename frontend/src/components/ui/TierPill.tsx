import { BAND_LOOK, isBand, NEUTRAL_PILL } from "../../lib/band";
import type { OccupationalTier } from "../../types/workspace";

/** Screening band of the worker result as a coloured pill that also says it in words. */
export function TierPill({ tier, prefix }: { tier: OccupationalTier | null; prefix?: string }) {
  const known = isBand(tier);
  const label = tier === null ? "Not computed" : known ? BAND_LOOK[tier].label : "not reported";
  const tone = known ? BAND_LOOK[tier].pill : NEUTRAL_PILL;
  return (
    <span
      className={`inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${tone}`}
      data-tier={known ? tier : "none"}
    >
      {prefix ? `${prefix} ` : ""}
      {label}
    </span>
  );
}
