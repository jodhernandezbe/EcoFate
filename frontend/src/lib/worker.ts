/** The evidence a worker value rests on, in words: what the API said, never inferred. */
export const MONITORING_EVIDENCE = "OSHA monitoring";

/** The pieces of a worker result that name its evidence (the API's `WorkerExtremum` and result both fit). */
export interface EvidenceSource {
  evidence: "monitoring" | "activity_model" | null;
  /** The label of the driving activity, when the value rests on the activity model. */
  drivingLabel: string | null;
}

/** "OSHA monitoring", the driving activity's label, or null while the API named no evidence. */
export function evidenceText({ evidence, drivingLabel }: EvidenceSource): string | null {
  if (evidence === "monitoring") return MONITORING_EVIDENCE;
  if (evidence === "activity_model") return drivingLabel ?? "Activity model";
  return null;
}

/** The estimator the API named, in words (an estimator this build does not know is shown as sent). */
const ESTIMATORS: Readonly<Record<string, string>> = {
  mass_balance: "Mass balance",
  two_zone: "Two-zone model",
  ecetoc_tra: "ECETOC TRA",
  monitoring: "OSHA monitoring",
};

export const estimatorText = (estimator: string | null): string | null =>
  estimator === null ? null : Object.hasOwn(ESTIMATORS, estimator) ? (ESTIMATORS[estimator] ?? estimator) : estimator;

/** The chemical's vapor pressure against the range the vapor models cover, in words. */
const VOLATILITY: Readonly<Record<string, string>> = {
  below: "below the vapor-model range",
  within: "within the vapor-model range",
  above: "above the vapor-model range",
};

export const volatilityText = (volatility: string | null): string | null =>
  volatility === null || !Object.hasOwn(VOLATILITY, volatility) ? null : (VOLATILITY[volatility] ?? null);
