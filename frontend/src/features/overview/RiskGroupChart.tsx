import { Bar, BarChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { formatNumber } from "../../lib/format";
import type { BandBoundaries } from "../../types/api";
import { describeBar, type Group, type Pathway, type Quantity } from "./riskGroups";

const BAR_COLOR = "var(--accent)";
const AXIS_TEXT = { fill: "var(--fg-2)", fontSize: 11 };

interface ChartRow {
  label: string;
  group: Group;
  /** Only a positive value can be drawn on the logarithmic axis; others stay in the text. */
  value?: number;
}

export const toRows = (groups: Group[], quantity: Quantity): ChartRow[] =>
  groups.map((group) => {
    const best = group[quantity];
    return { label: group.label, group, value: best !== null && best.value > 0 ? best.value : undefined };
  });

/** An axis tick: plain digits, or a compact 1e-4 where scientific notation would not fit. */
const compactTick = (value: number): string =>
  value !== 0 && (Math.abs(value) < 1e-3 || Math.abs(value) >= 1e5) ? value.toExponential(0) : formatNumber(value, 2);

const shorten = (text: string, max: number): string => (text.length > max ? `${text.slice(0, max - 1)}…` : text);

/** The dashed reference lines of a quantity: the boundaries where it becomes moderate and high. */
export function bandLines(quantity: Quantity, bands: BandBoundaries): { y: number; text: string }[] {
  const [low, high] =
    quantity === "hq"
      ? [bands.hq_lower, bands.hq_upper]
      : quantity === "risk"
        ? [bands.cancer_risk_lower, bands.cancer_risk_upper]
        : [bands.oel_ratio_lower, bands.oel_ratio_upper];
  return [
    { y: low, text: `moderate ${compactTick(low)}` },
    { y: high, text: `high ${compactTick(high)}` },
  ];
}

interface TooltipProps {
  active?: boolean;
  payload?: readonly { payload?: unknown }[];
  quantity: Quantity;
  digits: number;
  pathway?: Pathway;
}

/** The hover card of a bar: its value, the facility and concentration behind it, the counts. */
export function BarTooltip({ active, payload, quantity, digits, pathway = "outdoor" }: TooltipProps) {
  const row = payload?.[0]?.payload as ChartRow | undefined;
  if (!active || !row) return null;
  const detail = describeBar(row.group, quantity, digits, pathway);
  return (
    <div className="max-w-72 rounded-xl border border-hairline bg-solid p-2.5 text-xs shadow-[var(--shadow)]">
      <p className="m-0 font-semibold">{detail.group}</p>
      {detail.lines.map((line) => (
        <div key={line.label} className="mt-1.5">
          <p className="m-0">
            <span className="text-fg2">{line.label}: </span>
            <span className="font-semibold">{line.value}</span>
          </p>
          {line.detail && <p className="m-0 text-[11px] text-fg2">{line.detail}</p>}
        </div>
      ))}
      <p className="m-0 mt-1.5 text-[11px] text-fg2">{detail.counts}</p>
    </div>
  );
}

/** The same bars as text, for screen readers and for values a log axis cannot draw. */
function BarsAsText({ groups, quantity, digits, caption }: { groups: Group[]; quantity: Quantity; digits: number; caption: string }) {
  // The wrapper clips it: a table ignores its own width, so `sr-only` on the table alone left a
  // 1300 px wide box that made the panel scroll sideways.
  return (
    <div className="sr-only">
      <table>
        <caption>{caption}</caption>
        <thead>
          <tr>
            <th scope="col">Group</th>
            <th scope="col">Highest worst-case value</th>
            <th scope="col">Facilities</th>
            <th scope="col">Assessed</th>
          </tr>
        </thead>
        <tbody>
          {groups.map((g) => {
            const best = g[quantity];
            return (
              <tr key={g.key}>
                <th scope="row">{g.label}</th>
                <td>{best ? `${formatNumber(best.value, digits)} (${best.name ?? best.frsId})` : "not reported"}</td>
                <td>{g.facilities}</td>
                <td>{g.assessed}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

interface Props {
  groups: Group[];
  quantity: Quantity;
  /** The chart's heading, also its name for assistive technology. */
  title: string;
  /** Band boundaries from the client settings; the dashed lines of the shown quantity. */
  bands: BandBoundaries | undefined;
  /** The exposure pathway the bars belong to; outdoor air unless said otherwise. */
  pathway?: Pathway;
  digits: number;
  /** Characters of an x-axis label shown before it is cut (the tooltip and text have it all). */
  labelChars: number;
  /** Tailwind classes for the plot area's height. */
  heightClass: string;
  /** Angle the x-axis labels (a narrow chart); wide charts keep them level. */
  angled: boolean;
}

/** One bar per group: the highest worst-case value of one quantity, with its band boundaries dashed. */
export function RiskGroupChart({
  groups,
  quantity,
  title,
  bands,
  pathway = "outdoor",
  digits,
  labelChars,
  heightClass,
  angled,
}: Props) {
  const lines = bands ? bandLines(quantity, bands) : [];
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <h3 className="m-0 text-xs font-medium">{title}</h3>
      {bands && (
        <p className="m-0 text-[11px] text-fg2">
          Dashed lines: {lines.map((l) => l.text).join(", ")}
        </p>
      )}
      <div className={`w-full ${heightClass}`}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={toRows(groups, quantity)} margin={{ top: 8, right: 8, bottom: 4, left: 0 }}>
            <CartesianGrid stroke="var(--hairline)" vertical={false} />
            <XAxis
              dataKey="label"
              interval={0}
              angle={angled ? -25 : 0}
              textAnchor={angled ? "end" : "middle"}
              height={angled ? 58 : 30}
              padding={{ left: 24, right: 0 }}
              tick={AXIS_TEXT}
              tickFormatter={(value: string) => shorten(value, labelChars)}
              stroke="var(--hairline)"
            />
            <YAxis
              scale="log"
              domain={["auto", "auto"]}
              width={46}
              padding={{ top: 10, bottom: 0 }}
              tick={AXIS_TEXT}
              tickFormatter={compactTick}
              stroke="var(--hairline)"
            />
            {lines.map((line) => (
              <ReferenceLine
                key={line.y}
                y={line.y}
                stroke="var(--fg-2)"
                strokeDasharray="4 3"
                ifOverflow="extendDomain"
                label={{ value: line.text, position: "insideTopLeft", fill: "var(--fg-2)", fontSize: 10 }}
              />
            ))}
            <Tooltip
              cursor={{ fill: "var(--hairline)" }}
              content={(props) => <BarTooltip {...props} quantity={quantity} digits={digits} pathway={pathway} />}
            />
            <Bar dataKey="value" name={title} fill={BAR_COLOR} radius={[3, 3, 0, 0]} isAnimationActive={false} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <BarsAsText groups={groups} quantity={quantity} digits={digits} caption={title} />
    </div>
  );
}
