import "maplibre-gl/dist/maplibre-gl.css";

import { Earth } from "lucide-react";
import { Map as MapLibreMap, type StyleSpecification } from "maplibre-gl";

import "./maplibreWorker";
import { useEffect, useRef, useState } from "react";

import { PATHWAYS, pathwayInfo, type Pathway } from "../../lib/pathways";
import { DARK_MODE, REDUCED_MOTION, matches, usePrefers } from "../../lib/usePrefers";
import type { ClientConfig, Facility, ScenarioDriver, WorkspaceState } from "../../types/workspace";
import { SOURCES, addOverlays, readPalette, setSourceData } from "./layers";
import { FacilityInspector } from "./FacilityInspector";
import { MapLegend } from "./MapLegend";
import {
  bufferCollection,
  facilityCollection,
  receptorCollection,
  sectorCollection,
  statusKey,
  type StatusKey,
} from "./mapData";

const FIT_PADDING_PX = 64;
const FIT_MAX_ZOOM = 14;
const FIT_RESET_MAX_ZOOM = 6;
// Framing one facility from the results table.
const LEGEND_MAX_SHARE = 0.4;
const FIT_DURATION_MS = 900;
const BLANK_STYLE: StyleSpecification = { version: 8, sources: {}, layers: [] };
export const BLANK_NOTICE = "The basemap could not be loaded; facilities are drawn on a blank canvas.";

interface Props {
  workspace: WorkspaceState;
  config: ClientConfig["map"];
  digits: number;
  /** Rises when the workspace is replaced as a whole, so the camera reframes anyway. */
  viewEpoch?: number;
  /** Told which facility the user pinned on the map. */
  onPin?: (frsId: string) => void;
}

type Box = { west: number; south: number; east: number; north: number };
const corners = (box: Box): [[number, number], [number, number]] => [
  [box.west, box.south],
  [box.east, box.north],
];

function useOverlayData(
  shown: Facility[],
  config: Props["config"],
  drivers: ScenarioDriver[],
  pinnedId: string | null,
  pathway: Pathway,
) {
  const scale = { minPx: config.marker_min_px, maxPx: config.marker_max_px };
  return {
    [SOURCES.facilities]: facilityCollection(shown, scale, drivers, pathway),
    [SOURCES.buffers]: bufferCollection(shown),
    [SOURCES.sectors]: sectorCollection(shown),
    // Receptors are tracts around a stack: only the outdoor pathway has them.
    [SOURCES.receptors]: receptorCollection(shown, pathway === "outdoor" ? drivers : [], pinnedId),
  };
}

/** The pathway dropdown: the same choices and labels as Risk by group. */
function PathwayPicker({ pathway, onPathway }: { pathway: Pathway; onPathway: (pathway: Pathway) => void }) {
  return (
    <select
      aria-label="Map pathway (medium, route, receptor)"
      value={pathway}
      onChange={(event) => onPathway(event.target.value as Pathway)}
      className="max-w-full rounded-lg bg-fg2/10 px-2 py-1 text-[11px] text-fg"
    >
      {PATHWAYS.map(({ key, label }) => (
        <option key={key} value={key}>
          {label}
        </option>
      ))}
    </select>
  );
}

/**
 * Frame ``box``; false (nothing done) when the container is too small to hold it. The legend sits over the bottom-left corner, so what is framed is kept clear of
 * it, but it never takes more than a share of a narrow map (a fit with no room left is refused).
 */
function fitCamera(
  map: MapLibreMap,
  container: HTMLElement,
  legend: HTMLElement | null,
  box: Box,
  maxZoom: number,
  animate: boolean,
): boolean {
  const room = container.clientWidth > 0 ? container.clientWidth * LEGEND_MAX_SHARE : Infinity;
  const padding = {
    top: FIT_PADDING_PX,
    right: FIT_PADDING_PX,
    bottom: FIT_PADDING_PX,
    left: FIT_PADDING_PX + Math.min(legend?.offsetWidth ?? 0, room),
  };
  // A box with no room left inside the padding cannot be framed (MapLibre refuses and keeps a
  // meaningless camera), for example while the panels are still settling.
  const roomy =
    container.clientWidth > padding.left + padding.right &&
    container.clientHeight > padding.top + padding.bottom;
  if (!roomy && container.clientWidth > 0) return false;
  map.fitBounds(corners(box), {
    padding,
    maxZoom,
    duration: animate && !matches(REDUCED_MOTION) ? FIT_DURATION_MS : 0,
  });
  return true;
}

const hasSize = (element: HTMLElement | null): boolean =>
  element !== null && element.clientWidth > 0 && element.clientHeight > 0;

/** The basemap with the facility markers, receptor circles and schematic downwind sectors. */
export function ExposureMapCanvas({ workspace, config, digits, viewEpoch = 0, onPin }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<MapLibreMap | null>(null);
  const ready = useRef(false);
  const legend = useRef<HTMLElement>(null);
  const [instance, setInstance] = useState<MapLibreMap | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const dark = usePrefers(DARK_MODE);
  const styleUrl = dark ? config.dark_style : config.light_style;
  // Statuses the user switched off in the legend; their markers and shapes leave the map.
  const [hidden, setHidden] = useState<ReadonlySet<StatusKey>>(new Set<StatusKey>());
  // The pathway whose band colours the markers; local to the map, outdoor until the user chooses.
  const [pathway, setPathway] = useState<Pathway>("outdoor");
  const shown = workspace.facilities.filter((f) => !hidden.has(statusKey(f, pathway)));
  const [pinnedId, setPinnedId] = useState<string | null>(null);
  const drivers = workspace.scenario_drivers.filter((d) => d.pathway_key === pathwayInfo(pathway).pathwayKey);
  const data = useOverlayData(shown, config, drivers, pinnedId, pathway);
  // A status hidden on one pathway must not silently hide markers on the other.
  const choosePathway = (next: Pathway) => {
    setPathway(next);
    setHidden(new Set<StatusKey>());
  };
  const latest = useRef({ data, styleUrl, start: config.initial_view, bounds: workspace.bounds });
  useEffect(() => {
    latest.current = { data, styleUrl, start: config.initial_view, bounds: workspace.bounds };
  });

  const draw = () => {
    if (!map.current || !ready.current) return;
    for (const [id, collection] of Object.entries(latest.current.data)) {
      setSourceData(map.current, id, collection);
    }
  };

  useEffect(() => {
    const { start } = latest.current;
    const instance = new MapLibreMap({
      container: container.current as HTMLElement,
      style: latest.current.styleUrl,
      // The configured starting view (the United States) until facilities are placed.
      bounds: [
        [start.west, start.south],
        [start.east, start.north],
      ],
      fitBoundsOptions: { padding: FIT_PADDING_PX },
      // One world only: a wide panel zoomed out would otherwise repeat the continents.
      renderWorldCopies: false,
      attributionControl: { compact: true },
    });
    map.current = instance;
    setInstance(instance);
    instance.on("style.load", () => {
      addOverlays(instance, readPalette());
      ready.current = true;
      draw();
    });
    instance.on("error", (event) => {
      console.warn("Map error:", event.error);
      setNotice(BLANK_NOTICE);
      if (!ready.current) instance.setStyle(BLANK_STYLE);
    });
    // Any change of the container's size (a splitter, a collapse, fullscreen) redraws the map
    // at once; frames are coalesced so a drag does not queue one resize per pixel.
    let frame = 0;
    // A map built into a container that had no usable size yet (panels are measured after
    // mounting) has framed nothing; it frames as soon as the container can hold the view.
    let framed = false;
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        instance.resize();
        if (framed || !hasSize(container.current)) return;
        const { bounds: placed, start } = latest.current;
        const zoom = placed ? FIT_MAX_ZOOM : FIT_RESET_MAX_ZOOM;
        framed = fitCamera(instance, container.current as HTMLElement, legend.current, placed ?? start, zoom, false);
      });
    });
    observer.observe(container.current as HTMLElement);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      ready.current = false;
      instance.remove();
      map.current = null;
      setInstance(null);
    };
    // The map is created once; later changes are applied by the effects below.
  }, []);

  const applied = useRef(styleUrl);
  useEffect(() => {
    if (applied.current === styleUrl || !map.current) return;
    applied.current = styleUrl;
    ready.current = false;
    map.current.setStyle(styleUrl);
  }, [styleUrl]);

  useEffect(draw, [data]);

  const fit = (box: Box, maxZoom: number) => {
    if (map.current && container.current) {
      fitCamera(map.current, container.current, legend.current, box, maxZoom, true);
    }
  };

  const { bounds, framing_version: version } = workspace;
  useEffect(() => {
    if (!map.current || (version === 0 && viewEpoch === 0)) return;
    // Placed facilities are framed; a workspace emptied or replaced by an empty one shows the
    // starting view again.
    if (bounds) fit(bounds, FIT_MAX_ZOOM);
    else fit(latest.current.start, FIT_RESET_MAX_ZOOM);
    // Only a new framing version or epoch moves the camera, never other updates of the same bounds.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version, viewEpoch]);

  return (
    // `isolate`: the map's overlays (basemap button, legend, inspector) stack inside the map only,
    // never above a layer that covers the analysis area (Monitoring, drawers, fullscreen).
    <div className="relative isolate h-full w-full overflow-hidden rounded-2xl border border-hairline">
      {/* Inline, not a utility class: MapLibre's own stylesheet is unlayered, so its
          `position: relative` would beat Tailwind's layered `absolute` and collapse the map. */}
      <div
        ref={container}
        role="region"
        aria-label="Facility map"
        style={{ position: "absolute", inset: 0 }}
      />
      {instance && (
        <FacilityInspector
          map={instance}
          facilities={shown}
          scale={{ minPx: config.marker_min_px, maxPx: config.marker_max_px }}
          pathway={pathway}
          digits={digits}
          onPin={onPin}
          onPinned={setPinnedId}
        />
      )}
      <button
        type="button"
        aria-label="Reset to USA view"
        title="Reset to USA view"
        onClick={() => fit(latest.current.start, FIT_RESET_MAX_ZOOM)}
        className="glass spring absolute right-3 top-3 z-20 flex h-8 items-center gap-1.5 rounded-full px-3 text-xs text-fg2 transition hover:text-fg"
      >
        <Earth size={14} aria-hidden="true" />
        USA
      </button>
      <MapLegend
        ref={legend}
        facilities={workspace.facilities}
        pathway={pathway}
        picker={<PathwayPicker pathway={pathway} onPathway={choosePathway} />}
        drivers={drivers}
        hidden={hidden}
        onToggle={(key) =>
          setHidden((now) => {
            const next = new Set(now);
            if (!next.delete(key)) next.add(key);
            return next;
          })
        }
      />
      {notice && (
        <p role="status" className="glass absolute left-3 top-3 m-0 rounded-xl px-3 py-1.5 text-xs text-fg2">
          {notice}
        </p>
      )}
    </div>
  );
}
