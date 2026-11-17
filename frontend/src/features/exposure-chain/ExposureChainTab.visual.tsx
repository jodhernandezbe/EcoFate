import "../../index.css";

import { cleanup, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { page, userEvent } from "vitest/browser";

import { COMMUNITY_ONLY_GRAPH, FULL_GRAPH, MONITORING_GRAPH } from "../../test/graphs";
import type { ExposureGraph } from "../../types/api";
import { ExposureChainTab } from "./ExposureChainTab";

const realMatchMedia = window.matchMedia.bind(window);
afterEach(() => {
  cleanup();
  window.matchMedia = realMatchMedia;
});

function Frame({ width, children }: { width: number; children: ReactNode }) {
  return (
    <div data-testid="frame" style={{ width, padding: 16, display: "flex", flexDirection: "column", background: "var(--bg)", color: "var(--fg)" }}>
      {children}
    </div>
  );
}

/** In a panel narrower than the diagram it opens at the end; this scrolls to the start. */
function scrollDiagram(to: "start" | "end") {
  const box = document.querySelector<HTMLElement>(".overflow-x-auto");
  if (box) box.scrollLeft = to === "start" ? 0 : box.scrollWidth;
}

function draw(chain: ExposureGraph = FULL_GRAPH, width = 1280) {
  render(
    <Frame width={width}>
      <ExposureChainTab chain={chain} digits={2} />
    </Frame>,
  );
}

/** Waits for the diagram, then freezes the moving dots at one instant. */
async function settle() {
  await new Promise((resolve) => setTimeout(resolve, 100));
  for (const svg of document.querySelectorAll("svg")) {
    svg.pauseAnimations();
    svg.setCurrentTime(0.8);
  }
}

const frame = () => page.getByTestId("frame");
/** Light and dark run as two projects; each keeps its own references. */
const shot = (name: string) => `${name}-${realMatchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"}`;

/** The same chain with values the tools did not report, as the API would send them. */
const WITHOUT_VALUES: ExposureGraph = {
  ...FULL_GRAPH,
  nodes: FULL_GRAPH.nodes.map((n) =>
    n.id === "community:air" || n.id === "community:endpoint"
      ? { ...n, quantities: n.quantities.map((q) => ({ ...q, value: null, reason: "not reported by the tool" })) }
      : n,
  ),
  edges: FULL_GRAPH.edges.map((e) =>
    e.id === "community:inhale->community:band:0-4" && e.quantity ? { ...e, quantity: { ...e.quantity, value: null, reason: "no dose reported" } } : e,
  ),
};

const EMPTY: ExposureGraph = { lanes: [], nodes: [], edges: [], caption: null };

describe("exposure chain, in a real browser", () => {
  it("draws both lanes with a flowing marker on every band", async () => {
    draw();
    await settle();
    expect(document.querySelectorAll("[data-testid=band]")).toHaveLength(FULL_GRAPH.edges.length);
    expect(document.querySelectorAll("[data-testid=flow-marker]").length).toBe(FULL_GRAPH.edges.length * 2);
    await expect.element(frame()).toMatchScreenshot(shot("both-lanes-wide"));
  });

  it("keeps its legible size in a narrow panel, opens at the result and scrolls back", async () => {
    draw(FULL_GRAPH, 600);
    await settle();
    await expect.element(frame()).toMatchScreenshot(shot("both-lanes-narrow-end"));
    scrollDiagram("start");
    await settle();
    await expect.element(frame()).toMatchScreenshot(shot("both-lanes-narrow-start"));
  });

  it("draws missing values with their reasons", async () => {
    draw(WITHOUT_VALUES);
    await expect.element(frame()).toMatchScreenshot(shot("missing-values"));
  });

  it("draws a worker lane resting on OSHA monitoring in the high band", async () => {
    draw(MONITORING_GRAPH);
    await expect.element(frame()).toMatchScreenshot(shot("worker-monitoring-high"));
  });

  it("shows an unavailable lane's reason with no bands for it", async () => {
    draw(COMMUNITY_ONLY_GRAPH);
    await expect.element(frame()).toMatchScreenshot(shot("community-only"));
  });

  it("says what to do when the chain is empty", async () => {
    draw(EMPTY, 900);
    await expect.element(frame()).toMatchScreenshot(shot("empty"));
  });

  it("opens the community receptor with its most affected residents", async () => {
    draw();
    await settle();
    await userEvent.click(page.getByRole("button", { name: /Residents aged 0-4/ }));
    await settle();
    await expect.element(frame()).toMatchScreenshot(shot("receptor-detail"));
  });

  it("opens the worker endpoint with its band and absent reasons", async () => {
    draw();
    await settle();
    await userEvent.click(page.getByRole("button", { name: /Endpoint: Ratio to the occupational limit/ }));
    await settle();
    await expect.element(frame()).toMatchScreenshot(shot("worker-endpoint-detail"));
  });

  it("highlights one lane and dims the other", async () => {
    draw();
    await settle();
    await userEvent.hover(page.getByRole("button", { name: /Worker, workplace air, Pathway/ }));
    await settle();
    await expect.element(frame()).toMatchScreenshot(shot("worker-lane-highlighted"));
  });

  it("stops the flow when the user prefers reduced motion, keeping the arrowheads", async () => {
    window.matchMedia = (query: string) =>
      ({ ...realMatchMedia(query), matches: query.includes("reduce"), media: query, addEventListener() {}, removeEventListener() {} }) as MediaQueryList;
    draw();
    await screen.findByRole("button", { name: /Source/ });
    expect(document.querySelectorAll("[data-testid=flow-marker]")).toHaveLength(0);
    expect(document.querySelectorAll("[data-testid=band-arrow]")).toHaveLength(FULL_GRAPH.edges.length);
  });
});
