import type { OccupationalTier } from "../../types/workspace";

const LOOK: Record<OccupationalTier, { label: string; tone: string }> = {
  acceptable: { label: "Acceptable", tone: "bg-ok/15 text-ok" },
  elevated: { label: "Elevated", tone: "bg-warn/15 text-warn" },
  exceedance: { label: "Exceedance", tone: "bg-bad/15 text-bad" },
};

/** Tier of the worker screening as a coloured pill that also says it in words. */
export function TierPill({ tier, prefix }: { tier: OccupationalTier | null; prefix?: string }) {
  const { label, tone } = tier ? LOOK[tier] : { label: "Not computed", tone: "bg-fg2/10 text-fg2" };
  return (
    <span
      className={`inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${tone}`}
      data-tier={tier ?? "none"}
    >
      {prefix ? `${prefix} ` : ""}
      {label}
    </span>
  );
}
