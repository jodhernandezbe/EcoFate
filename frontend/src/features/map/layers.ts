import type { FeatureCollection } from "geojson";
import type { Map as MapLibreMap } from "maplibre-gl";

/** Source and layer ids of the workspace overlays. */
export const SOURCES = {
  facilities: "facilities",
  buffers: "buffers",
  sectors: "sectors",
  receptors: "receptors",
} as const;
export const MARKER_LAYER = "facility-markers";
export const WORKER_RING_LAYER = "facility-worker-rings";
export const DRIVER_RING_LAYER = "facility-driver-rings";
export const RECEPTOR_LAYER = "scenario-receptors";

export interface Palette {
  ok: string;
  warn: string;
  bad: string;
  neutral: string;
  accent: string;
  halo: string;
}

const EMPTY: FeatureCollection = { type: "FeatureCollection", features: [] };

/** Colours from the CSS design tokens, so the map follows the light and dark themes. */
export function readPalette(root: Element = document.documentElement): Palette {
  const style = getComputedStyle(root);
  const token = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback;
  return {
    ok: token("--ok", "#1b7a34"),
    warn: token("--warn", "#a35200"),
    bad: token("--bad", "#c4001a"),
    neutral: token("--fg-2", "#6e6e73"),
    accent: token("--accent", "#0066cc"),
    halo: token("--surface-solid", "#ffffff"),
  };
}

function addSources(map: MapLibreMap): void {
  for (const id of Object.values(SOURCES)) {
    if (!map.getSource(id)) map.addSource(id, { type: "geojson", data: EMPTY });
  }
}

function addPlumeLayers(map: MapLibreMap, palette: Palette): void {
  map.addLayer({
    id: "buffer-fill",
    type: "fill",
    source: SOURCES.buffers,
    paint: { "fill-color": palette.accent, "fill-opacity": 0.07 },
  });
  map.addLayer({
    id: "buffer-line",
    type: "line",
    source: SOURCES.buffers,
    paint: { "line-color": palette.accent, "line-width": 1.5, "line-opacity": 0.7 },
  });
  map.addLayer({
    id: "sector-fill",
    type: "fill",
    source: SOURCES.sectors,
    paint: { "fill-color": palette.warn, "fill-opacity": 0.22 },
  });
  map.addLayer({
    id: "sector-line",
    type: "line",
    source: SOURCES.sectors,
    paint: { "line-color": palette.warn, "line-width": 1.5, "line-dasharray": [2, 2] },
  });
}

function addMarkerLayer(map: MapLibreMap, palette: Palette): void {
  map.addLayer({
    id: MARKER_LAYER,
    type: "circle",
    source: SOURCES.facilities,
    paint: {
      "circle-radius": ["get", "radius_px"],
      "circle-color": [
        "match",
        ["get", "status"],
        "low",
        palette.ok,
        "moderate",
        palette.warn,
        "high",
        palette.bad,
        palette.neutral,
      ],
      // A worker-only facility has no community result: outlined, never filled.
      "circle-opacity": ["case", ["get", "worker_only"], 0, 0.85],
      "circle-stroke-color": ["case", ["get", "worker_only"], palette.neutral, palette.halo],
      "circle-stroke-width": ["case", ["get", "worker_only"], 2, 1.5],
    },
  });
}

/** A ring just outside each marker, coloured by the worker tier (no ring while it is not computed). */
function addWorkerRingLayer(map: MapLibreMap, palette: Palette): void {
  map.addLayer({
    id: WORKER_RING_LAYER,
    type: "circle",
    source: SOURCES.facilities,
    paint: {
      "circle-radius": ["+", ["get", "radius_px"], 3],
      "circle-opacity": 0,
      "circle-stroke-width": ["match", ["get", "worker_tier"], "none", 0, 2.5],
      "circle-stroke-color": [
        "match",
        ["get", "worker_tier"],
        "low",
        palette.ok,
        "moderate",
        palette.warn,
        "high",
        palette.bad,
        palette.neutral,
      ],
    },
  });
}

/** An outer ring on the facilities that have the highest value of some result. */
function addDriverRingLayer(map: MapLibreMap, palette: Palette): void {
  map.addLayer({
    id: DRIVER_RING_LAYER,
    type: "circle",
    source: SOURCES.facilities,
    filter: ["==", ["get", "driver"], true],
    paint: {
      "circle-radius": ["+", ["get", "radius_px"], 8],
      "circle-opacity": 0,
      "circle-stroke-width": 2,
      "circle-stroke-color": palette.accent,
    },
  });
}

/** The most affected tracts of the pinned driving facility; stronger where more of the maximum. */
function addReceptorLayer(map: MapLibreMap, palette: Palette): void {
  map.addLayer({
    id: RECEPTOR_LAYER,
    type: "circle",
    source: SOURCES.receptors,
    paint: {
      "circle-radius": 6,
      "circle-color": palette.accent,
      "circle-opacity": ["interpolate", ["linear"], ["get", "fraction"], 0, 0.35, 1, 1],
      "circle-stroke-color": palette.halo,
      "circle-stroke-width": 1.5,
    },
  });
}

/** Adds the overlay sources and layers (again after a style change, which drops them). */
export function addOverlays(map: MapLibreMap, palette: Palette): void {
  addSources(map);
  if (map.getLayer(MARKER_LAYER)) return;
  addPlumeLayers(map, palette);
  addMarkerLayer(map, palette);
  addWorkerRingLayer(map, palette);
  addDriverRingLayer(map, palette);
  addReceptorLayer(map, palette);
}

/** Replaces the data of an overlay source. */
export function setSourceData(map: MapLibreMap, id: string, data: object): void {
  const source = map.getSource(id);
  if (source && "setData" in source) (source as { setData: (d: object) => void }).setData(data);
}
