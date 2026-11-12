/** The one screening band the API sends for both pathways: its words and colours live here only. */
export type Band = "high" | "moderate" | "low";

interface BandLook {
  /** The words shown next to the colour. */
  label: string;
  /** Tinted pill classes (design tokens at 15 %). */
  pill: string;
  /** Solid fill of a legend swatch. */
  fill: string;
  /** Ring border of a legend swatch. */
  ring: string;
  /** CSS colour of the band (design token). */
  color: string;
}

/** Band to words and tone; the order is the legend order. */
export const BAND_LOOK: Readonly<Record<Band, BandLook>> = {
  low: { label: "Low", pill: "bg-ok/15 text-ok", fill: "bg-ok", ring: "border-ok", color: "var(--ok)" },
  moderate: { label: "Moderate", pill: "bg-warn/15 text-warn", fill: "bg-warn", ring: "border-warn", color: "var(--warn)" },
  high: { label: "High", pill: "bg-bad/15 text-bad", fill: "bg-bad", ring: "border-bad", color: "var(--bad)" },
};

export const BANDS: readonly Band[] = ["low", "moderate", "high"];

/** True for a band this build knows; an old saved value ("above", "exceedance") is not one. */
export const isBand = (value: unknown): value is Band =>
  typeof value === "string" && Object.prototype.hasOwnProperty.call(BAND_LOOK, value);

/** Neutral look for a value that is absent or not understood. */
export const NEUTRAL_PILL = "bg-fg2/10 text-fg2";
