import { useId, useState, type KeyboardEvent } from "react";

import { GlassCard } from "../../components/ui/GlassCard";
import { StatusPill } from "../../components/ui/StatusPill";
import { DetailPanel } from "./DetailPanel";
import { EMPTY_CHAIN, formatQuantity, type ExposureGraph } from "./graph";
import { SankeyDiagram } from "./SankeyDiagram";

interface Props {
  /** The run's worst-case chain; absent (an older server) reads as empty. */
  chain?: ExposureGraph | null;
  digits: number;
}

function LaneStatus({ graph }: { graph: ExposureGraph }) {
  return (
    <ul className="m-0 flex list-none flex-wrap gap-x-4 gap-y-1 p-0 text-xs text-fg2" aria-label="Pathways">
      {graph.lanes.map((lane) => (
        <li key={lane.id} className="flex items-center gap-1.5">
          <span className="text-fg">{lane.label}</span>
          {lane.available ? <StatusPill status={lane.status} label={lane.status_label ?? undefined} /> : <span>({lane.reason})</span>}
        </li>
      ))}
    </ul>
  );
}

/** What a screen reader gets instead of the picture: every connection with what it carries. */
function Connections({ graph, digits }: { graph: ExposureGraph; digits: number }) {
  const title = new Map(graph.nodes.map((n) => [n.id, n.title]));
  return (
    <ol className="sr-only" aria-label="Connections">
      {graph.edges.map((e) => (
        <li key={e.id}>
          {`${title.get(e.source) ?? e.source} to ${title.get(e.target) ?? e.target}`}
          {e.quantity ? `: ${e.quantity.label} ${e.quantity.value === null ? (e.quantity.reason ?? "not reported") : formatQuantity(e.quantity, digits)}` : ""}
        </li>
      ))}
    </ol>
  );
}

function Empty() {
  return (
    <GlassCard className="p-4 text-sm text-fg2">
      No worst-case chain yet. Run an assessment to see how the worst exposure of each route arises, from the release to the value compared with a benchmark.
    </GlassCard>
  );
}

/**
 * The Exposure chain tab: the run's worst-case chain as the API built it, drawn as a Sankey diagram
 * (source, release, pathway, route, receptor, endpoint) with one lane per pathway and no facility named.
 */
export function ExposureChainTab({ chain, digits }: Props) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [hoveredLane, setHoveredLane] = useState<string | null>(null);
  const detailId = useId();
  const graph = chain ?? EMPTY_CHAIN;
  const selected = graph.nodes.find((n) => n.id === selectedId) ?? null;
  const activeLane = hoveredLane ?? selected?.lane ?? null;
  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key !== "Escape" || !selected) return;
    event.preventDefault();
    event.stopPropagation();
    setSelectedId(null);
  };
  return (
    <section aria-label="Exposure chain" className="flex min-h-0 flex-1 flex-col gap-3" onKeyDown={onKeyDown}>
      {graph.lanes.length > 0 && <LaneStatus graph={graph} />}
      {graph.nodes.length === 0 ? (
        <Empty />
      ) : (
        <div className="rounded-xl border border-hairline bg-fg2/5 p-3">
          <SankeyDiagram
            graph={graph}
            digits={digits}
            selectedId={selected?.id ?? null}
            activeLane={activeLane}
            detailId={detailId}
            onSelect={(id) => setSelectedId((now) => (now === id ? null : id))}
            onHover={setHoveredLane}
          />
          {graph.caption && <p className="m-0 mt-3 text-xs text-fg2">{graph.caption}</p>}
        </div>
      )}
      {graph.nodes.length > 0 && (
        <DetailPanel
          node={selected}
          laneLabel={graph.lanes.find((l) => l.id === selected?.lane)?.label ?? null}
          digits={digits}
          id={detailId}
          onClose={() => setSelectedId(null)}
        />
      )}
      <Connections graph={graph} digits={digits} />
    </section>
  );
}
