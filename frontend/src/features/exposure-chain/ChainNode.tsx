import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";

import { StatusPill } from "../../components/ui/StatusPill";
import { NODE_H, NODE_W, formatQuantity, headline, type GraphNode } from "./graph";
import { KINDS } from "./kinds";

export interface ChainNodeData extends Record<string, unknown> {
  node: GraphNode;
  laneLabel: string | null;
  digits: number;
  selected: boolean;
  dimmed: boolean;
  detailId: string;
  onSelect: (id: string) => void;
  onHover: (lane: string | null) => void;
}

export type ChainFlowNode = Node<ChainNodeData, "chain">;

const HIDDEN_HANDLE = "!h-1 !w-1 !min-h-0 !min-w-0 !border-0 !bg-transparent";

/** One step: a real button (focus, Enter and ARIA are native) inside the React Flow node. */
export function ChainNode({ data }: NodeProps<ChainFlowNode>) {
  const { node, laneLabel, digits, selected, dimmed } = data;
  const { icon: Icon, badge } = KINDS[node.kind];
  const value = headline(node);
  const shown = value ? formatQuantity(value, digits) : null;
  const name = [laneLabel, `${badge}: ${node.title}`, shown && `${value?.label} ${shown}`].filter(Boolean).join(", ");
  return (
    <div style={{ width: NODE_W, height: NODE_H }} className={dimmed ? "opacity-35 transition-opacity" : "transition-opacity"}>
      <Handle type="target" position={Position.Left} isConnectable={false} className={HIDDEN_HANDLE} />
      <button
        type="button"
        aria-label={name}
        aria-expanded={selected}
        aria-controls={data.detailId}
        onClick={() => data.onSelect(node.id)}
        onMouseEnter={() => data.onHover(node.lane)}
        onMouseLeave={() => data.onHover(null)}
        onFocus={() => data.onHover(node.lane)}
        onBlur={() => data.onHover(null)}
        className={`nopan nodrag spring flex h-full w-full flex-col justify-between rounded-xl border bg-solid p-2.5 text-left shadow-sm transition motion-reduce:transition-none ${
          selected ? "border-accent ring-2 ring-accent/30" : "border-hairline hover:border-accent/60"
        }`}
      >
        <span className="flex items-center justify-between gap-1">
          <Icon aria-hidden="true" size={16} className="shrink-0 text-accent" />
          {node.status !== null ? (
            <StatusPill status={node.status} label={node.status_label ?? undefined} />
          ) : (
            <span className="text-[11px] font-medium text-fg2">{badge}</span>
          )}
        </span>
        <span className="line-clamp-2 text-[12px] font-medium leading-tight text-fg">{node.title}</span>
        <span className="flex min-h-5 items-end justify-between gap-1">
          <span className="min-w-0">
            {value && <span className="line-clamp-2 block text-[11px] leading-tight text-fg2">{value.label}</span>}
            <span className={`block truncate text-[13px] font-semibold tabular-nums ${value?.value === null ? "text-fg2" : "text-fg"}`}>
              {shown ?? "\u00a0"}
            </span>
          </span>
        </span>
      </button>
      <Handle type="source" position={Position.Right} isConnectable={false} className={HIDDEN_HANDLE} />
    </div>
  );
}
