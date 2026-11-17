import { useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";

import { statusColor, type ExposureGraph } from "./graph";
import { layoutSankey, MIN_WIDTH } from "./layout";
import { BandLabel, SankeyBand } from "./SankeyBand";
import { SankeyNode } from "./SankeyNode";

interface Props {
  graph: ExposureGraph;
  digits: number;
  selectedId: string | null;
  activeLane: string | null;
  detailId: string;
  onSelect: (id: string) => void;
  onHover: (lane: string | null) => void;
}

/** The width of an element, followed as it resizes (the minimum width until it is measured). */
function useWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(MIN_WIDTH);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const measure = () => setWidth(element.clientWidth || MIN_WIDTH);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return { ref, width };
}

/** Opens a diagram wider than its container scrolled to the end, where the result is. */
function useOpenAtEnd(ref: RefObject<HTMLDivElement | null>, contentWidth: number) {
  const opened = useRef(false);
  useLayoutEffect(() => {
    const box = ref.current;
    if (!box || opened.current || box.scrollWidth <= box.clientWidth) return;
    opened.current = true;
    box.scrollLeft = box.scrollWidth;
  }, [ref, contentWidth]);
}

/**
 * The Sankey diagram: SVG bands under HTML step cards, laid out at the container's width. Below the
 * minimum width it keeps its size and the container scrolls horizontally, so text stays legible.
 */
export function SankeyDiagram({ graph, digits, selectedId, activeLane, detailId, onSelect, onHover }: Props) {
  const { ref, width } = useWidth();
  const layout = layoutSankey(graph, width);
  useOpenAtEnd(ref, layout.width);
  const lanes = new Map(graph.lanes.map((lane) => [lane.id, lane]));
  const dimmed = (lane: string | null) => activeLane !== null && lane !== null && lane !== activeLane;
  return (
    <div ref={ref} className="min-w-0 overflow-x-auto">
      <div role="group" aria-label="Exposure chain diagram" className="relative" style={{ width: layout.width, height: layout.height }}>
        <svg viewBox={`0 0 ${layout.width} ${layout.height}`} width={layout.width} height={layout.height} className="absolute inset-0" aria-hidden="true">
          {layout.bands.map((band) => (
            <SankeyBand key={band.edge.id} band={band} status={lanes.get(band.edge.lane)?.status ?? null} dimmed={dimmed(band.edge.lane)} />
          ))}
        </svg>
        {layout.headers.map((header) => (
          <p
            key={header.lane}
            style={{ left: header.x, top: header.y }}
            className={`absolute m-0 flex items-center gap-1.5 text-xs font-semibold text-fg2 transition-opacity ${dimmed(header.lane) ? "opacity-30" : ""}`}
          >
            <span aria-hidden="true" className="size-2 rounded-full" style={{ background: statusColor(lanes.get(header.lane)?.status ?? null) }} />
            {lanes.get(header.lane)?.label ?? header.lane}
          </p>
        ))}
        {layout.bands.map((band) => (
          <BandLabel key={band.edge.id} band={band} digits={digits} dimmed={dimmed(band.edge.lane)} />
        ))}
        {layout.nodes.map(({ node, x, y }) => (
          <SankeyNode
            key={node.id}
            node={node}
            x={x}
            y={y}
            laneLabel={lanes.get(node.lane ?? "")?.label ?? null}
            digits={digits}
            selected={selectedId === node.id}
            dimmed={dimmed(node.lane)}
            detailId={detailId}
            onSelect={onSelect}
            onHover={onHover}
          />
        ))}
      </div>
    </div>
  );
}
