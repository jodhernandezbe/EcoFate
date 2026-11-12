import type { Feature, FeatureCollection, Point, Polygon } from "geojson";

import type { Facility, OccupationalTier, ScenarioDriver, Status } from "../../types/workspace";

export interface MarkerScale {
  minPx: number;
  maxPx: number;
}

export interface MarkerProperties {
  frs_id: string;
  name: string;
  status: Status | "none";
  /** Tier of the worker screening (drawn as a ring), or "none" while it is not computed. */
  worker_tier: OccupationalTier | "none";
  /** A facility with a worker result and no stack release: outlined, no community fill. */
  worker_only: boolean;
  /** Whether the facility has the highest value of some result (drawn as an outer ring). */
  driver: boolean;
  radius_px: number;
}

/** Marker radius (px) from the emission rate, on a square-root scale across the facilities shown. */
export function markerRadius(rate: number, rates: number[], scale: MarkerScale): number {
  const roots = rates.map((r) => Math.sqrt(Math.max(r, 0)));
  const low = Math.min(...roots);
  const high = Math.max(...roots);
  if (!(high > low)) return (scale.minPx + scale.maxPx) / 2;
  const share = (Math.sqrt(Math.max(rate, 0)) - low) / (high - low);
  return scale.minPx + (scale.maxPx - scale.minPx) * share;
}

/**
 * One point per facility: filled by the community status (none while not computed), ringed by the
 * worker tier, sized by emission rate. A worker-only facility has no emission rate: it keeps one
 * fixed size (the smallest) and its marker is outlined instead of filled.
 */
export function facilityCollection(
  facilities: Facility[],
  scale: MarkerScale,
  drivers: readonly ScenarioDriver[] = [],
): FeatureCollection<Point, MarkerProperties> {
  const driving = new Set(drivers.map((d) => d.frs_id));
  const rates = facilities.flatMap((f) => (f.emission_rate_g_s === null ? [] : [f.emission_rate_g_s]));
  return {
    type: "FeatureCollection",
    features: facilities.map((f) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [f.longitude, f.latitude] },
      properties: {
        frs_id: f.frs_id,
        name: f.name ?? `FRS ${f.frs_id}`,
        status: f.status ?? "none",
        worker_tier: f.occupational_exposure?.risk_tier ?? "none",
        worker_only: f.worker_only,
        driver: driving.has(f.frs_id),
        radius_px: f.emission_rate_g_s === null ? scale.minPx : markerRadius(f.emission_rate_g_s, rates, scale),
      },
    })),
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
