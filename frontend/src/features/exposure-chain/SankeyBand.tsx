import { REDUCED_MOTION, usePrefers } from "../../lib/usePrefers";
import { formatQuantity, statusColor, type GraphLane } from "./graph";
import type { LaidBand } from "./layout";

/** Dots that travel along a band, evenly spaced (presentation only). */
const DOTS = 2;
const PERIOD_S = 2.4;
const ARROW = 7;

/** The band's centre line: leaves the source card and enters the target card level. */
export function bandPath({ from, to }: LaidBand): string {
  const mid = (from.x + to.x) / 2;
  return `M ${from.x} ${from.y} C ${mid} ${from.y}, ${mid} ${to.y}, ${to.x} ${to.y}`;
}

interface Props {
  band: LaidBand;
  status: GraphLane["status"];
  dimmed: boolean;
}

/**
 * A band between two steps: a curve of one fixed width in the lane's status colour, an arrowhead
 * showing the direction, and dots that move along it (still when the user prefers reduced motion).
 */
export function SankeyBand({ band, status, dimmed }: Props) {
  const reduced = usePrefers(REDUCED_MOTION);
  const color = statusColor(status);
  const path = bandPath(band);
  const { to } = band;
  return (
    <g data-lane={band.edge.lane} opacity={dimmed ? 0.2 : 1} aria-hidden="true">
      <path d={path} fill="none" stroke={color} strokeWidth={band.width} strokeOpacity={0.3} data-testid="band" />
      {band.label && <path d={`M ${band.label.x} ${(band.from.y + band.to.y) / 2} V ${band.label.top}`} stroke={color} strokeWidth={1.5} strokeDasharray="3 3" fill="none" data-testid="band-leader" />}
      <path d={`M ${to.x - ARROW} ${to.y - ARROW} L ${to.x} ${to.y} L ${to.x - ARROW} ${to.y + ARROW} Z`} fill={color} data-testid="band-arrow" />
      {!reduced &&
        !dimmed &&
        Array.from({ length: DOTS }, (_, index) => (
          <circle key={index} r={3} fill={color} data-testid="flow-marker">
            <animateMotion dur={`${PERIOD_S}s`} begin={`${(-index * PERIOD_S) / DOTS}s`} repeatCount="indefinite" path={path} />
          </circle>
        ))}
    </g>
  );
}

interface LabelProps {
  band: LaidBand;
  dimmed: boolean;
  digits: number;
}

/** What the band carries, as the API sent it (the reason when it sent no value), hung under its lane. */
export function BandLabel({ band, dimmed, digits }: LabelProps) {
  const quantity = band.edge.quantity;
  const box = band.label;
  if (!quantity || !box) return null;
  const absent = quantity.value === null;
  return (
    <div
      aria-hidden="true"
      style={{ left: box.x, top: box.top, maxWidth: box.maxWidth, transform: "translateX(-50%)" }}
      className={`pointer-events-none absolute w-max rounded-lg border border-hairline bg-solid px-1.5 py-0.5 text-center leading-tight shadow-sm transition-opacity ${dimmed ? "opacity-30" : ""}`}
    >
      <span className="block text-[11px] text-fg2">{quantity.label}</span>
      <span className={`block text-xs font-medium tabular-nums ${absent ? "text-fg2" : "text-fg"}`}>
        {absent ? (quantity.reason ?? formatQuantity(quantity, digits)) : formatQuantity(quantity, digits)}
      </span>
    </div>
  );
}
