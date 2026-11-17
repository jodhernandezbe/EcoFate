import { facility, scenario, worker, workerOnly } from "../../test/fixtures";
import type { ScenarioDriver, ScenarioReceptor } from "../../types/workspace";
import {
  bufferCollection,
  facilityCollection,
  markerRadius,
  receptorCollection,
  sectorCollection,
} from "./mapData";

const scale = { minPx: 6, maxPx: 22 };

describe("markerRadius", () => {
  it("maps the smallest and largest rate to the configured radii", () => {
    const rates = [1, 4, 9];
    expect(markerRadius(1, rates, scale)).toBe(6);
    expect(markerRadius(9, rates, scale)).toBe(22);
  });

  it("scales by the square root, so area follows the rate", () => {
    expect(markerRadius(4, [1, 4, 9], scale)).toBe(14);
  });

  it("uses the middle radius when every rate is equal or there is one facility", () => {
    expect(markerRadius(5, [5], scale)).toBe(14);
    expect(markerRadius(5, [5, 5], scale)).toBe(14);
  });

  it("treats a negative rate as zero", () => {
    expect(markerRadius(-3, [-3, 4], scale)).toBe(6);
  });
});

describe("facilityCollection", () => {
  it("places one point per facility at its longitude and latitude", () => {
    const data = facilityCollection([facility({ longitude: -20, latitude: 10 })], scale);
    expect(data.features).toHaveLength(1);
    expect(data.features[0]?.geometry.coordinates).toEqual([-20, 10]);
  });

  it("colours by status and is neutral while no risk is computed", () => {
    const data = facilityCollection(
      [facility({ frs_id: "A", status: "high" }), facility({ frs_id: "B", status: null })],
      scale,
    );
    expect(data.features.map((f) => f.properties.status)).toEqual(["high", "none"]);
  });

  it("colours by the band of the chosen pathway and has no ring property for the other", () => {
    const f = facility({ status: "low", occupational_exposure: worker({ risk_tier: "high" }) });
    const [outdoor] = facilityCollection([f], scale, [], "outdoor").features;
    const [indoor] = facilityCollection([f], scale, [], "indoor").features;
    expect([outdoor?.properties.status, indoor?.properties.status]).toEqual(["low", "high"]);
    expect(Object.keys(outdoor?.properties ?? {})).not.toContain("worker_tier");
  });

  it("gives a facility with no result on the pathway the neutral none status", () => {
    const only = workerOnly();
    expect(facilityCollection([only], scale, [], "outdoor").features[0]?.properties.status).toBe("none");
    expect(facilityCollection([only], scale, [], "indoor").features[0]?.properties.status).toBe("moderate");
    expect(facilityCollection([facility()], scale, [], "indoor").features[0]?.properties.status).toBe("none");
  });

  it("sizes a worker-only facility by its total, whichever pathway is chosen", () => {
    const facilities = [
      facility({ frs_id: "A", total_air_release_kg_per_year: 100 }),
      workerOnly({ total_air_release_kg_per_year: 400 }),
    ];
    for (const pathway of ["outdoor", "indoor"] as const) {
      const sizes = facilityCollection(facilities, scale, [], pathway).features.map((f) => f.properties.radius_px);
      expect(sizes).toEqual([6, 22]);
    }
  });

  it("marks the facilities that drive a result and no others", () => {
    const drivers: ScenarioDriver[] = [
      { pathway_key: "community_inhalation", quantity: "hq", frs_id: "A", facility_name: "A", stack_number: 1, value: 2 },
    ];
    const data = facilityCollection([facility({ frs_id: "A" }), facility({ frs_id: "B" })], scale, drivers);
    expect(data.features.map((f) => f.properties.driver)).toEqual([true, false]);
    expect(facilityCollection([facility()], scale).features[0]?.properties.driver).toBe(false);
  });

  it("falls back to the FRS ID for an unnamed facility", () => {
    const data = facilityCollection([facility({ name: null })], scale);
    expect(data.features[0]?.properties.name).toBe("FRS F1");
  });

  it("sizes by total annual air release on a square-root scale", () => {
    const data = facilityCollection(
      [
        facility({ frs_id: "A", total_air_release_kg_per_year: 100 }),
        facility({ frs_id: "B", total_air_release_kg_per_year: 400 }),
        facility({ frs_id: "C", total_air_release_kg_per_year: 900 }),
      ],
      scale,
    );
    expect(data.features.map((f) => f.properties.radius_px)).toEqual([6, 14, 22]);
  });

  it("ignores the emission rate", () => {
    const data = facilityCollection(
      [
        facility({ frs_id: "A", emission_rate_g_s: 9, total_air_release_kg_per_year: 100 }),
        facility({ frs_id: "B", emission_rate_g_s: 1, total_air_release_kg_per_year: 400 }),
      ],
      scale,
    );
    expect(data.features.map((f) => f.properties.radius_px)).toEqual([6, 22]);
  });

  it("gives an absent or non-finite total the smallest size, never the middle one", () => {
    const data = facilityCollection(
      [
        facility({ frs_id: "A", total_air_release_kg_per_year: 100 }),
        facility({ frs_id: "B", total_air_release_kg_per_year: 400 }),
        facility({ frs_id: "C", total_air_release_kg_per_year: null }),
        facility({ frs_id: "D", total_air_release_kg_per_year: Number.NaN }),
      ],
      scale,
    );
    expect(data.features.map((f) => f.properties.radius_px)).toEqual([6, 22, 6, 6]);
  });
});

describe("overlay collections", () => {
  const ring = { type: "Polygon" as const, coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] };

  it("includes only facilities that have the shape", () => {
    const facilities = [
      facility({ frs_id: "A", buffer: ring, sector: ring }),
      facility({ frs_id: "B", buffer: ring }),
      facility({ frs_id: "C" }),
    ];
    expect(bufferCollection(facilities).features.map((f) => f.properties.frs_id)).toEqual(["A", "B"]);
    expect(sectorCollection(facilities).features.map((f) => f.properties.frs_id)).toEqual(["A"]);
  });
});


describe("receptorCollection", () => {
  const tract = (label: string, fraction: number, over: Partial<ScenarioReceptor> = {}): ScenarioReceptor => ({
    kind: "tract",
    label,
    residents: 100,
    age_distribution: {},
    distance_m: 500,
    bearing_deg: 90,
    latitude: 10.1,
    longitude: -20.1,
    concentration: 1,
    fraction_of_maximum: fraction,
    note: null,
    ...over,
  });
  const driver = (frs_id: string, quantity = "hq"): ScenarioDriver => ({
    pathway_key: "community_inhalation",
    quantity,
    frs_id,
    facility_name: null,
    stack_number: 1,
    value: 2,
  });
  const facilities = [
    facility({ frs_id: "A", scenarios: [scenario({ receptors: [tract("T1", 1), tract("T2", 0.6)] })] }),
    facility({ frs_id: "B", scenarios: [scenario({ receptors: [tract("T3", 1)] })] }),
  ];

  it("draws the tracts of the pinned driving facility where the tool put them", () => {
    const data = receptorCollection(facilities, [driver("A")], "A");
    expect(data.features.map((f) => f.properties.label)).toEqual(["T1", "T2"]);
    expect(data.features[0]?.geometry.coordinates).toEqual([-20.1, 10.1]);
    expect(data.features[1]?.properties.fraction).toBe(0.6);
  });

  it("draws nothing while no facility is pinned", () => {
    expect(receptorCollection(facilities, [driver("A")], null).features).toEqual([]);
  });

  it("draws nothing for a pinned facility that drives no result", () => {
    expect(receptorCollection(facilities, [driver("A")], "B").features).toEqual([]);
  });

  it("draws only the receptors of the result the facility drives", () => {
    const both = facility({
      frs_id: "A",
      scenarios: [
        scenario({ receptors: [tract("T1", 1)] }),
        scenario({ quantity: "cancer_risk", receptors: [tract("T9", 1)] }),
      ],
    });
    expect(receptorCollection([both], [driver("A", "hq")], "A").features.map((f) => f.properties.label)).toEqual(["T1"]);
  });

  it("draws a tract once, at its highest fraction, when several results name it", () => {
    const both = facility({
      frs_id: "A",
      scenarios: [
        scenario({ receptors: [tract("T1", 0.7)] }),
        scenario({ quantity: "cancer_risk", receptors: [tract("T1", 0.9)] }),
      ],
    });
    const data = receptorCollection([both], [driver("A", "hq"), driver("A", "cancer_risk")], "A");
    expect(data.features).toHaveLength(1);
    expect(data.features[0]?.properties.fraction).toBe(0.9);
  });

  it("skips workers and tracts with no coordinates", () => {
    const mixed = facility({
      frs_id: "A",
      scenarios: [
        scenario({
          receptors: [tract("W", 1, { kind: "workers" }), tract("N", 1, { latitude: null, longitude: null }), tract("T", 1)],
        }),
      ],
    });
    expect(receptorCollection([mixed], [driver("A")], "A").features.map((f) => f.properties.label)).toEqual(["T"]);
  });
});
