import { StatusPill } from "../../components/ui/StatusPill";
import { formatQuantity, headline, NODE_H, NODE_W, type GraphNode } from "./graph";
import { KINDS } from "./kinds";

interface Props {
  node: GraphNode;
  x: number;
  y: number;
  laneLabel: string | null;
  digits: number;
  selected: boolean;
  dimmed: boolean;
  detailId: string;
  onSelect: (id: string) => void;
  onHover: (lane: string | null) => void;
}

/** What the card reads for its headline value: the value as sent, else the API's reason. */
export function faceValue(node: GraphNode, digits: number): { text: string; absent: boolean } | null {
  const value = headline(node);
  if (!value) return null;
  if (value.value === null) return { text: value.reason ?? formatQuantity(value, digits), absent: true };
  return { text: formatQuantity(value, digits), absent: false };
}

/** One step: a real button (focus, Enter and Space are native) laid over the diagram. */
export function SankeyNode({ node, x, y, laneLabel, digits, selected, dimmed, detailId, onSelect, onHover }: Props) {
  const { icon: Icon, badge } = KINDS[node.kind];
  const value = headline(node);
  const face = faceValue(node, digits);
  const name = [laneLabel, `${badge}: ${node.title}`, face && `${value?.label} ${face.text}`].filter(Boolean).join(", ");
  return (
    <button
      type="button"
      aria-label={name}
      aria-expanded={selected}
      aria-controls={detailId}
      onClick={() => onSelect(node.id)}
      onMouseEnter={() => onHover(node.lane)}
      onMouseLeave={() => onHover(null)}
      onFocus={() => onHover(node.lane)}
      onBlur={() => onHover(null)}
      style={{ left: x, top: y, width: NODE_W, height: NODE_H }}
      className={`spring absolute flex flex-col justify-between rounded-xl border bg-solid p-2.5 text-left shadow-sm transition motion-reduce:transition-none ${
        dimmed ? "opacity-35" : ""
      } ${selected ? "border-accent ring-2 ring-accent/30" : "border-hairline hover:border-accent/60"}`}
    >
      <span className="flex items-center justify-between gap-1">
        <Icon aria-hidden="true" size={16} className="shrink-0 text-accent" />
        {node.status !== null ? (
          <StatusPill status={node.status} label={node.status_label ?? undefined} />
        ) : (
          <span className="text-[11px] font-medium text-fg2">{badge}</span>
        )}
      </span>
      <span className="line-clamp-2 text-xs font-medium leading-tight text-fg">{node.title}</span>
      <span className="block min-h-12 min-w-0">
        {value && <span className="line-clamp-2 block text-[11px] leading-tight text-fg2">{value.label}</span>}
        <span className={`line-clamp-2 block text-xs font-semibold leading-tight tabular-nums ${face?.absent ? "text-fg2" : "text-fg"}`}>
          {face?.text ?? " "}
        </span>
      </span>
    </button>
  );
}
