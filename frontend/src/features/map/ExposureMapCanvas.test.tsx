import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { act } from "react";

import { FakeMap } from "../../test/fakeMaplibre";
import { resizeObservers } from "../../test/fakeResizeObserver";
import { facility, scenario, workspace } from "../../test/fixtures";
import type { WorkspaceState } from "../../types/workspace";
import { BLANK_NOTICE, ExposureMapCanvas } from "./ExposureMapCanvas";
import { SECTOR_CAPTION } from "./MapLegend";

const config = {
  light_style: "https://example.test/light.json",
  dark_style: "https://example.test/dark.json",
  marker_min_px: 6,
  marker_max_px: 22,
  initial_view: { west: -125, south: 24.5, east: -66.9, north: 49.5 },
};

const listeners = new Set<() => void>();
const current = { dark: false, reduced: false };

/** Stubs the OS settings; `flipDark` changes the colour scheme the way the OS would. */
function media(options: { dark?: boolean; reduced?: boolean }) {
  current.dark = !!options.dark;
  current.reduced = !!options.reduced;
  vi.stubGlobal("matchMedia", (query: string) => ({
    get matches() {
      return query.includes("dark") ? current.dark : query.includes("reduce") && current.reduced;
    },
    addEventListener: (_: string, listener: () => void) => listeners.add(listener),
    removeEventListener: (_: string, listener: () => void) => listeners.delete(listener),
  }));
}

function flipDark(dark: boolean) {
  current.dark = dark;
  act(() => listeners.forEach((listener) => listener()));
}

const placed = (version: number, over: Partial<WorkspaceState> = {}) =>
  workspace({
    framing_version: version,
    bounds: { west: -20, south: 10, east: -10, north: 20 },
    facilities: [facility()],
    ...over,
  });

function load(): FakeMap {
  const map = FakeMap.last;
  act(() => map.emit("style.load"));
  return map;
}

beforeEach(() => {
  listeners.clear();
  FakeMap.reset();
  media({});
});
afterEach(() => vi.unstubAllGlobals());

describe("basemap", () => {
  it("uses the light style from configuration in light mode", () => {
    render(<ExposureMapCanvas digits={2} workspace={workspace()} config={config} />);
    expect(FakeMap.last.options.style).toBe(config.light_style);
  });

  it("uses the dark style in dark mode", () => {
    media({ dark: true });
    render(<ExposureMapCanvas digits={2} workspace={workspace()} config={config} />);
    expect(FakeMap.last.options.style).toBe(config.dark_style);
  });

  it("starts on the configured view before anything is placed", () => {
    render(<ExposureMapCanvas digits={2} workspace={workspace()} config={config} />);
    expect(FakeMap.last.options.bounds).toEqual([
      [-125, 24.5],
      [-66.9, 49.5],
    ]);
    expect(FakeMap.last.fits).toHaveLength(0);
  });

  it("shows the attribution", () => {
    render(<ExposureMapCanvas digits={2} workspace={workspace()} config={config} />);
    expect(FakeMap.last.options.attributionControl).toBeTruthy();
  });

  it("falls back to a blank canvas with a notice when the basemap fails to load", () => {
    render(<ExposureMapCanvas digits={2} workspace={workspace()} config={config} />);
    const map = FakeMap.last;
    act(() => map.emit("error", { error: new Error("tiles") }));
    expect(screen.getByRole("status")).toHaveTextContent(BLANK_NOTICE);
    expect(map.styles).toHaveLength(2);
    expect(map.styles[1]).toMatchObject({ version: 8, layers: [] });
  });

  it("removes the map when it unmounts", () => {
    const { unmount } = render(<ExposureMapCanvas digits={2} workspace={workspace()} config={config} />);
    const map = FakeMap.last;
    unmount();
    expect(map.removed).toBe(true);
  });
});

describe("container", () => {
  it("fills its box with an inline position that MapLibre's stylesheet cannot override", () => {
    render(<ExposureMapCanvas digits={2} workspace={workspace()} config={config} />);
    const box = screen.getByRole("region", { name: "Facility map" });
    expect(box.style.position).toBe("absolute");
    expect(box.style.inset).toBe("0px");
  });
});

describe("overlays", () => {
  it("adds the marker, circle and sector layers once the style loads", () => {
    render(<ExposureMapCanvas digits={2} workspace={placed(1)} config={config} />);
    const map = load();
    expect([...map.sources.keys()].sort()).toEqual(["buffers", "facilities", "receptors", "sectors"]);
    expect(map.layers).toContain("facility-markers");
    expect(map.layers).toContain("sector-fill");
    expect(map.layers).toContain("facility-driver-rings");
    expect(map.layers).toContain("scenario-receptors");
  });

  it("puts every facility on the map", () => {
    const { rerender } = render(<ExposureMapCanvas digits={2} workspace={placed(1)} config={config} />);
    const map = load();
    const count = () => (map.getSource("facilities")?.data as { features: unknown[] }).features.length;
    expect(count()).toBe(1);
    rerender(
      <ExposureMapCanvas
        digits={2}
        workspace={placed(2, { facilities: [facility(), facility({ frs_id: "F2", latitude: 12 })] })}
        config={config}
      />,
    );
    expect(count()).toBe(2);
  });

  it("switches to the dark style when the OS does, and draws the overlays again", () => {
    render(<ExposureMapCanvas digits={2} workspace={placed(1)} config={config} />);
    const map = load();
    flipDark(true);
    expect(map.styles).toEqual([config.light_style, config.dark_style]);
    expect(map.layers.size).toBe(0); // a new style drops the overlays
    act(() => map.emit("style.load"));
    expect(map.layers).toContain("facility-markers");
    expect((map.getSource("facilities")?.data as { features: unknown[] }).features).toHaveLength(1);
    expect(FakeMap.instances).toHaveLength(1); // the same map, not a new one
  });
});

describe("camera", () => {
  it("fits the bounds of the placed facilities when the framing version changes", () => {
    const { rerender } = render(<ExposureMapCanvas digits={2} workspace={placed(1)} config={config} />);
    const map = FakeMap.last;
    expect(map.fits).toHaveLength(1);
    expect(map.fits[0]?.bounds).toEqual([[-20, 10], [-10, 20]]);
    rerender(<ExposureMapCanvas digits={2} workspace={placed(2)} config={config} />);
    expect(map.fits).toHaveLength(2);
  });

  it("does not move for an update that leaves the framing version alone", () => {
    const { rerender } = render(<ExposureMapCanvas digits={2} workspace={placed(1)} config={config} />);
    const map = FakeMap.last;
    rerender(<ExposureMapCanvas digits={2} workspace={placed(1, { warnings: ["something"] })} config={config} />);
    expect(map.fits).toHaveLength(1);
  });

  it("does not move before anything is placed", () => {
    render(<ExposureMapCanvas digits={2} workspace={workspace()} config={config} />);
    expect(FakeMap.last.fits).toHaveLength(0);
  });

  it("animates the move normally", () => {
    render(<ExposureMapCanvas digits={2} workspace={placed(1)} config={config} />);
    expect(FakeMap.last.fits[0]?.options.duration).toBeGreaterThan(0);
  });

  it("moves instantly when the user prefers reduced motion", () => {
    media({ reduced: true });
    render(<ExposureMapCanvas digits={2} workspace={placed(1)} config={config} />);
    expect(FakeMap.last.fits[0]?.options.duration).toBe(0);
  });
});

describe("legend", () => {
  it("keeps the framed facilities clear of the legend", () => {
    Object.defineProperty(HTMLElement.prototype, "offsetWidth", { configurable: true, get: () => 250 });
    try {
      render(<ExposureMapCanvas digits={2} workspace={placed(1)} config={config} />);
      const padding = FakeMap.last.fits[0]?.options.padding;
      expect(padding).toMatchObject({ left: 64 + 250, right: 64, top: 64, bottom: 64 });
    } finally {
      Reflect.deleteProperty(HTMLElement.prototype, "offsetWidth");
    }
  });

  it("explains the colours and sizes", () => {
    render(<ExposureMapCanvas digits={2} workspace={placed(1)} config={config} />);
    const legend = screen.getByRole("complementary", { name: "Map legend" });
    expect(legend).toHaveTextContent("High");
    expect(legend).toHaveTextContent("Marker size follows the emission rate");
  });

  it("has no em dash in its caption", () => {
    const ring = { type: "Polygon" as const, coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] };
    render(
      <ExposureMapCanvas
        digits={2}
        workspace={placed(1, { facilities: [facility({ buffer: ring, sector: ring })] })}
        config={config}
      />,
    );
    expect(screen.getByRole("complementary", { name: "Map legend" }).textContent).not.toContain("\u2014");
  });

  describe("hiding markers", () => {
    const shown = () => {
      const data = FakeMap.last.sources.get("facilities")?.data as { features: unknown[] } | undefined;
      return data?.features.length ?? 0;
    };
    const entry = (name: RegExp) => within(screen.getByRole("complementary", { name: "Map legend" })).getByRole("button", { name });
    const two = () =>
      placed(1, {
        facilities: [
          facility({ frs_id: "A", name: "Plant A", status: "high" }),
          facility({ frs_id: "B", name: "Plant B", status: "low", latitude: 11 }),
          facility({ frs_id: "C", name: "Plant C", status: null, latitude: 12 }),
        ],
      });

    it("says no facility is mapped yet, without counts, while the workspace is empty", () => {
      render(<ExposureMapCanvas digits={2} workspace={workspace()} config={config} />);
      const legend = screen.getByRole("complementary", { name: "Map legend" });
      expect(legend).toHaveTextContent("No facilities mapped yet.");
      expect(entry(/High/).textContent).not.toMatch(/\d/);
      expect(entry(/Not computed/).textContent).not.toMatch(/\d/);
    });

    it("keeps its overlays inside the map's own stacking context", () => {
      const { container } = render(<ExposureMapCanvas digits={2} workspace={two()} config={config} />);
      expect(container.firstElementChild).toHaveClass("isolate");
    });

    it("counts the facilities of each status in the legend", () => {
      render(<ExposureMapCanvas digits={2} workspace={two()} config={config} />);
      expect(entry(/High/)).toHaveTextContent("1");
      expect(entry(/Low/)).toHaveTextContent("1");
      expect(entry(/Moderate/)).toHaveTextContent("0");
      expect(entry(/Not computed/)).toHaveTextContent("1");
    });

    it("hides a status's markers when its entry is pressed, and shows them again when pressed again", async () => {
      render(<ExposureMapCanvas digits={2} workspace={two()} config={config} />);
      load();
      expect(shown()).toBe(3);
      await userEvent.click(entry(/High/));
      expect(entry(/High/)).toHaveAttribute("aria-pressed", "false");
      expect(shown()).toBe(2);
      await userEvent.click(entry(/High/));
      expect(entry(/High/)).toHaveAttribute("aria-pressed", "true");
      expect(shown()).toBe(3);
    });

    it("hides several statuses independently and keeps their counts", async () => {
      render(<ExposureMapCanvas digits={2} workspace={two()} config={config} />);
      load();
      await userEvent.click(entry(/High/));
      await userEvent.click(entry(/Not computed/));
      expect(shown()).toBe(1);
      expect(entry(/High/)).toHaveTextContent("1");
    });

    it("takes a hidden facility's card away with its marker", async () => {
      render(<ExposureMapCanvas digits={2} workspace={two()} config={config} />);
      load();
      expect(screen.getByRole("button", { name: /Plant A/ })).toBeInTheDocument();
      await userEvent.click(entry(/High/));
      expect(screen.queryByRole("button", { name: /Plant A/ })).toBeNull();
      expect(screen.getByRole("button", { name: /Plant B/ })).toBeInTheDocument();
    });
  });

  it("labels the downwind sector as schematic only when one is drawn", () => {
    const ring = { type: "Polygon" as const, coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] };
    const { rerender } = render(<ExposureMapCanvas digits={2} workspace={placed(1)} config={config} />);
    expect(screen.queryByText(new RegExp(SECTOR_CAPTION))).toBeNull();
    rerender(
      <ExposureMapCanvas
        digits={2}
        workspace={placed(1, { facilities: [facility({ buffer: ring, sector: ring })] })}
        config={config}
      />,
    );
    expect(screen.getByText(new RegExp(SECTOR_CAPTION))).toBeInTheDocument();
  });
});

describe("starting view and resizing", () => {
  it("is visible on the United States with no facilities", () => {
    render(<ExposureMapCanvas digits={2} workspace={workspace()} config={config} />);
    expect(screen.getByRole("region", { name: "Facility map" })).toBeInTheDocument();
    expect(FakeMap.last.options.bounds).toEqual([
      [-125, 24.5],
      [-66.9, 49.5],
    ]);
    expect(screen.queryByRole("button", { name: /^Facility/ })).toBeNull();
  });

  it("resizes the map when its container changes size, once per frame, and stops on unmount", async () => {
    const { unmount } = render(<ExposureMapCanvas digits={2} workspace={workspace()} config={config} />);
    const map = FakeMap.last;
    const mine = [...resizeObservers].filter((observer) => observer.targets.size > 0);
    expect(mine).toHaveLength(1);
    act(() => {
      mine[0]?.fire();
      mine[0]?.fire();
    });
    await vi.waitFor(() => expect(map.resizes).toBe(1));
    unmount();
    expect(mine[0]?.targets.size).toBe(0);
    expect(map.removed).toBe(true);
  });
});

describe("Reset to USA view", () => {
  it("returns the camera to the configured view and leaves the markers placed", async () => {
    const user = userEvent.setup();
    render(<ExposureMapCanvas digits={2} workspace={placed(1)} config={config} />);
    const map = load();
    expect(map.fits).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: "Reset to USA view" }));
    expect(map.fits).toHaveLength(2);
    expect(map.fits[1]?.bounds).toEqual([
      [-125, 24.5],
      [-66.9, 49.5],
    ]);
    expect(screen.getByRole("button", { name: /Plant F1/ })).toBeInTheDocument();
  });

  it("jumps instead of flying when the user prefers reduced motion", async () => {
    media({ reduced: true });
    const user = userEvent.setup();
    render(<ExposureMapCanvas digits={2} workspace={workspace()} config={config} />);
    await user.click(screen.getByRole("button", { name: "Reset to USA view" }));
    expect(FakeMap.last.fits[0]?.options.duration).toBe(0);
  });
});

describe("reframing a replaced workspace", () => {
  it("shows the United States again when a workspace with facilities is replaced by an empty one", () => {
    const { rerender } = render(<ExposureMapCanvas digits={2} workspace={placed(1)} config={config} viewEpoch={0} />);
    const map = load();
    expect(map.fits).toHaveLength(1);
    rerender(<ExposureMapCanvas digits={2} workspace={workspace()} config={config} viewEpoch={1} />);
    expect(map.fits).toHaveLength(2);
    expect(map.fits[1]?.bounds).toEqual([
      [-125, 24.5],
      [-66.9, 49.5],
    ]);
  });

  it("does not move the camera for the very first, empty workspace", () => {
    render(<ExposureMapCanvas digits={2} workspace={workspace()} config={config} viewEpoch={0} />);
    expect(FakeMap.last.fits).toHaveLength(0);
  });

  it("flies to the facilities when they arrive", () => {
    const { rerender } = render(<ExposureMapCanvas digits={2} workspace={workspace()} config={config} />);
    const map = load();
    rerender(<ExposureMapCanvas digits={2} workspace={placed(1)} config={config} />);
    expect(map.fits.at(-1)?.bounds).toEqual([
      [-20, 10],
      [-10, 20],
    ]);
  });
});

describe("a container that has no size yet", () => {
  function sizeOf(element: Element, width: number, height: number) {
    Object.defineProperty(element, "clientWidth", { value: width, configurable: true });
    Object.defineProperty(element, "clientHeight", { value: height, configurable: true });
  }

  it("frames the starting view when the container first gets a size", async () => {
    render(<ExposureMapCanvas digits={2} workspace={workspace()} config={config} />);
    const map = FakeMap.last;
    const container = screen.getByRole("region", { name: "Facility map" });
    expect(map.fits).toHaveLength(0);
    sizeOf(container, 700, 500);
    act(() => [...resizeObservers].forEach((observer) => observer.fire()));
    await vi.waitFor(() => expect(map.fits).toHaveLength(1));
    expect(map.fits[0]?.bounds).toEqual([
      [-125, 24.5],
      [-66.9, 49.5],
    ]);
    expect(map.fits[0]?.options.duration).toBe(0);
    act(() => [...resizeObservers].forEach((observer) => observer.fire()));
    await vi.waitFor(() => expect(map.resizes).toBe(2));
    expect(map.fits).toHaveLength(1); // framed once, later resizes only resize
  });

  it("limits what the legend may take of a narrow map", () => {
    const { rerender } = render(<ExposureMapCanvas digits={2} workspace={workspace()} config={config} />);
    const map = load();
    const container = screen.getByRole("region", { name: "Facility map" });
    sizeOf(container, 300, 500);
    const legend = screen.getByRole("complementary", { name: "Map legend" });
    Object.defineProperty(legend, "offsetWidth", { value: 260, configurable: true });
    rerender(<ExposureMapCanvas digits={2} workspace={placed(1)} config={config} />);
    const padding = map.fits.at(-1)?.options.padding as { left: number; right: number };
    expect(padding.left + padding.right).toBeLessThan(300);
  });
});


describe("worst-case scenarios on the map", () => {
  const tract = {
    kind: "tract" as const,
    label: "T1",
    residents: 100,
    age_distribution: {},
    distance_m: 500,
    bearing_deg: 90,
    latitude: 10.1,
    longitude: -20.1,
    concentration: 1,
    fraction_of_maximum: 1,
    note: null,
  };
  const driving = () =>
    placed(1, {
      facilities: [facility({ name: "Plant F1", scenarios: [scenario({ receptors: [tract] })] })],
      scenario_drivers: [
        { pathway_key: "community_inhalation", quantity: "hq", frs_id: "F1", facility_name: "Plant F1", stack_number: 1, value: 2 },
      ],
    });
  const receptors = (map: FakeMap) => (map.getSource("receptors")?.data as { features: unknown[] }).features;

  it("rings the driving facility and explains the ring in the legend", () => {
    render(<ExposureMapCanvas digits={2} workspace={driving()} config={config} />);
    const map = load();
    const marker = (map.getSource("facilities")?.data as { features: { properties: { driver: boolean } }[] }).features[0];
    expect(marker?.properties.driver).toBe(true);
    expect(screen.getByText(/Outer ring: the facility that drives a worst case/)).toBeInTheDocument();
  });

  it("draws the receptors of the pinned driving facility, and removes them when it is closed", async () => {
    const user = userEvent.setup();
    render(<ExposureMapCanvas digits={2} workspace={driving()} config={config} />);
    const map = load();
    expect(receptors(map)).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: /Plant F1/ }));
    expect(receptors(map)).toHaveLength(1);
    await user.keyboard("{Escape}");
    expect(receptors(map)).toHaveLength(0);
  });

  it("shows no ring note and no receptors without scenarios", () => {
    render(<ExposureMapCanvas digits={2} workspace={placed(1)} config={config} />);
    const map = load();
    expect(receptors(map)).toHaveLength(0);
    expect(screen.queryByText(/drives a worst case/)).toBeNull();
  });
});
