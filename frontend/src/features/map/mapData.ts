import type { Feature, FeatureCollection, Point, Polygon } from "geojson";

import type { Band } from "../../lib/band";
import { pathwayInfo, type Pathway } from "../../lib/pathways";
import type { Facility, ScenarioDriver } from "../../types/workspace";

export interface MarkerScale {
  minPx: number;
  maxPx: number;
}

/** A marker's status on the chosen pathway: its band, or "none" when it has no result there. */
export type StatusKey = Band | "none";

export interface MarkerProperties {
  frs_id: string;
  name: string;
  status: StatusKey;
  /** Whether the facility drives a worst case of the chosen pathway (drawn as an outer ring). */
  driver: boolean;
  radius_px: number;
}

/** The facility's status key on a pathway (the band the API sent, else "none"). */
export const statusKey = (facility: Facility, pathway: Pathway): StatusKey =>
  pathwayInfo(pathway).band(facility) ?? "none";

/** The total annual air release (kg/yr) when the API sent a finite one. */
export const totalOf = (facility: Facility): number | null => {
  const total = facility.total_air_release_kg_per_year;
  return typeof total === "number" && Number.isFinite(total) ? total : null;
};

/** Marker radius (px) from the total annual air release, on a square-root scale across the facilities shown. */
export function markerRadius(total: number, totals: number[], scale: MarkerScale): number {
  const roots = totals.map((t) => Math.sqrt(Math.max(t, 0)));
  const low = Math.min(...roots);
  const high = Math.max(...roots);
  if (!(high > low)) return (scale.minPx + scale.maxPx) / 2;
  const share = (Math.sqrt(Math.max(total, 0)) - low) / (high - low);
  return scale.minPx + (scale.maxPx - scale.minPx) * share;
}

/**
 * One point per facility: filled by its band on the chosen pathway ("none" when it has no result
 * there), sized by its total annual air release (the smallest size when the API sent none). The
 * `drivers` are those of the chosen pathway.
 */
export function facilityCollection(
  facilities: Facility[],
  scale: MarkerScale,
  drivers: readonly ScenarioDriver[] = [],
  pathway: Pathway = "outdoor",
): FeatureCollection<Point, MarkerProperties> {
  const driving = new Set(drivers.map((d) => d.frs_id));
  const totals = facilities.flatMap((f) => totalOf(f) ?? []);
  return {
    type: "FeatureCollection",
    features: facilities.map((f) => {
      const total = totalOf(f);
      return {
        type: "Feature",
        geometry: { type: "Point", coordinates: [f.longitude, f.latitude] },
        properties: {
          frs_id: f.frs_id,
          name: f.name ?? `FRS ${f.frs_id}`,
          status: statusKey(f, pathway),
          driver: driving.has(f.frs_id),
          radius_px: total === null ? scale.minPx : markerRadius(total, totals, scale),
        },
      };
    }),
  };
}

function polygons(
  facilities: Facility[],
  pick: (facility: Facility) => Polygon | null,
): FeatureCollection<Polygon, { frs_id: string }> {
  const features: Feature<Polygon, { frs_id: string }>[] = [];
  for (const facility of facilities) {
    const shape = pick(facility);
    if (shape) features.push({ type: "Feature", geometry: shape, properties: { frs_id: facility.frs_id } });
  }
  return { type: "FeatureCollection", features };
}

/** The receptor radius circles of the facilities that have receptors. */
export const bufferCollection = (facilities: Facility[]) => polygons(facilities, (f) => f.buffer);

/** The schematic downwind sectors of the facilities that have receptors and weather. */
export const sectorCollection = (facilities: Facility[]) => polygons(facilities, (f) => f.sector);

export interface ReceptorProperties {
  label: string;
  residents: number | null;
  /** The receptor's concentration over the scenario's maximum, as the API sent it. */
  fraction: number;
}

/**
 * The most affected tracts of the scenarios a facility drives, drawn where the tool put them. Only
 * the pinned facility's receptors are drawn, and only for results it drives; a tract several
 * results name is drawn once, at its highest fraction of the maximum.
 */
export function receptorCollection(
  facilities: Facility[],
  drivers: readonly ScenarioDriver[],
  pinnedId: string | null,
): FeatureCollection<Point, ReceptorProperties> {
  const facility = facilities.find((f) => f.frs_id === pinnedId);
  const best = new Map<string, Feature<Point, ReceptorProperties>>();
  for (const scenario of facility?.scenarios ?? []) {
    const drives = drivers.some(
      (d) => d.frs_id === pinnedId && d.pathway_key === scenario.pathway_key && d.quantity === scenario.quantity,
    );
    if (!drives) continue;
    for (const r of scenario.receptors) {
      if (r.kind !== "tract" || r.latitude === null || r.longitude === null) continue;
      const fraction = r.fraction_of_maximum ?? 0;
      if ((best.get(r.label)?.properties.fraction ?? -1) >= fraction) continue;
      best.set(r.label, {
        type: "Feature",
        geometry: { type: "Point", coordinates: [r.longitude, r.latitude] },
        properties: { label: r.label, residents: r.residents, fraction },
      });
    }
  }
  return { type: "FeatureCollection", features: [...best.values()] };
}
