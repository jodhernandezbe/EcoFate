import { BAND_LOOK, isBand, NEUTRAL_PILL } from "../../lib/band";
import { formatCount, formatNumber } from "../../lib/format";
import { factorValue, groupFactors } from "../../lib/scenarios";
import type { ScenarioReceptor, WorstCaseScenario } from "../../types/workspace";

function Tier({ tier }: { tier: string | null }) {
  const known = isBand(tier);
  const words = tier === null ? "no level reported" : known ? BAND_LOOK[tier].label : "not reported";
  return (
    <span
      className={`inline-flex whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${known ? BAND_LOOK[tier].pill : NEUTRAL_PILL}`}
    >
      {words}
    </span>
  );
}

function bands(receptor: ScenarioReceptor, digits: number): string {
  return Object.entries(receptor.age_distribution)
    .map(([band, share]) => `${band} ${formatNumber(share, digits)}%`)
    .join(" · ");
}

function ReceptorRow({ receptor, digits }: { receptor: ScenarioReceptor; digits: number }) {
  if (receptor.kind === "workers") {
    return (
      <li className="rounded-lg bg-fg2/5 p-2 text-xs">
        <span className="font-medium">Workers</span>
        {receptor.note && <span className="text-fg2"> · {receptor.note}</span>}
      </li>
    );
  }
  return (
    <li className="rounded-lg bg-fg2/5 p-2 text-xs">
      <p className="m-0">
        <span className="font-medium">Tract {receptor.label}</span>
        <span className="text-fg2"> · {formatCount(receptor.residents)} residents</span>
      </p>
      <p className="m-0 text-fg2">
        {formatNumber(receptor.distance_m, digits)} m at {formatNumber(receptor.bearing_deg, digits)}° from the
        facility · {formatNumber(receptor.concentration, digits)} µg/m³ ({formatNumber(receptor.fraction_of_maximum, digits)} of
        the maximum)
      </p>
      <p className="m-0 text-fg2">{bands(receptor, digits)}</p>
    </li>
  );
}

function Receptors({ scenario, digits }: { scenario: WorstCaseScenario; digits: number }) {
  return (
    <section aria-label="Most affected receptors">
      <h4 className="m-0 mb-1 text-xs font-semibold text-fg2">Most affected receptors</h4>
      {scenario.receptors.length > 0 && (
        <ul className="m-0 grid list-none gap-1 p-0">
          {scenario.receptors.map((receptor) => (
            <ReceptorRow key={receptor.label} receptor={receptor} digits={digits} />
          ))}
        </ul>
      )}
      {scenario.receptors_note && <p className="m-0 mt-1 text-xs text-fg2">{scenario.receptors_note}</p>}
    </section>
  );
}

/**
 * One worst-case scenario in the same layout for every pathway: the value and the level the
 * assessment gave it, then the factors behind it by group, then the receptors. It only shows what
 * the API sent; an absent factor says "not reported" with its reason.
 */
export function ScenarioView({ scenario, digits }: { scenario: WorstCaseScenario; digits: number }) {
  return (
    <article aria-label={`${scenario.quantity_label}, ${scenario.pathway}`} className="grid gap-2">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="m-0 text-xs text-fg2">{scenario.pathway}</p>
        <Tier tier={scenario.tier} />
      </header>
      <p className="m-0 text-sm">
        <span className="text-fg2">{scenario.quantity_label}: </span>
        <span className="text-xl font-semibold tabular-nums">{formatNumber(scenario.value, digits)}</span>
        {scenario.benchmark !== null && (
          <span className="text-xs text-fg2"> (screening benchmark {formatNumber(scenario.benchmark, digits)})</span>
        )}
      </p>
      {groupFactors(scenario.factors).map((group) => (
        <section key={group.key} aria-label={group.title}>
          <h4 className="m-0 mb-1 text-xs font-semibold text-fg2">{group.title}</h4>
          <dl className="m-0 grid grid-cols-2 gap-x-3 gap-y-1">
            {group.factors.map((factor) => (
              <div key={factor.key} className="min-w-0">
                <dt className="text-xs text-fg2">{factor.label}</dt>
                <dd className="m-0 text-sm font-medium tabular-nums">
                  {factorValue(factor, digits)}
                  {factor.value === null && factor.reason && (
                    <span className="block text-[11px] font-normal text-fg2">{factor.reason}</span>
                  )}
                  {factor.value !== null && factor.source && (
                    <span className="block text-[11px] font-normal text-fg2">{factor.source}</span>
                  )}
                </dd>
              </div>
            ))}
          </dl>
        </section>
      ))}
      <Receptors scenario={scenario} digits={digits} />
      {scenario.notes.length > 0 && (
        <ul className="m-0 list-disc pl-4 text-[11px] text-fg2">
          {scenario.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      )}
    </article>
  );
}
