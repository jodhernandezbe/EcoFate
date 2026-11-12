import "../../index.css";

import { cleanup, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { page, userEvent } from "vitest/browser";

import { facility, workspace } from "../../test/fixtures";
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
    <div data-testid="frame" style={{ width, height: 820, padding: 16, display: "flex", flexDirection: "column", background: "var(--bg)", color: "var(--fg)" }}>
      {children}
    </div>
  );
}

function draw(graph: ExposureGraph = FULL_GRAPH, width = 1280) {
  const f = facility({ name: "Plant F1", exposure_graph: graph });
  render(
    <Frame width={width}>
      <ExposureChainTab facility={f} workspace={workspace({ facilities: [f] })} digits={2} onPick={() => {}} />
    </Frame>,
  );
}

/** Waits for the layout and the fitted view, then freezes the flowing dots at one instant. */
async function settle() {
  await screen.findByRole("button", { name: /Source: Plant F1/ });
  await new Promise((resolve) => setTimeout(resolve, 500));
  for (const svg of document.querySelectorAll("svg")) {
    svg.pauseAnimations();
    svg.setCurrentTime(0.8);
  }
}

const frame = () => page.getByTestId("frame");
/** Light and dark run as two projects; each keeps its own references. */
const shot = (name: string) => `${name}-${realMatchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"}`;

describe("exposure chain, in a real browser", () => {
  it("draws both lanes with every connection flowing", async () => {
    draw();
    await settle();
    expect(document.querySelectorAll(".react-flow__edge")).toHaveLength(FULL_GRAPH.edges.length);
    expect(document.querySelectorAll("[data-testid=flow-particle]").length).toBe(FULL_GRAPH.edges.length * 3);
    await expect.element(frame()).toMatchScreenshot(shot("both-lanes-wide"));
  });

  it("fits a narrow panel without overlapping steps", async () => {
    draw(FULL_GRAPH, 600);
    await settle();
    await expect.element(frame()).toMatchScreenshot(shot("both-lanes-narrow"));
  });

  it("draws a worker lane resting on OSHA monitoring in the high band", async () => {
    draw(MONITORING_GRAPH);
    await settle();
    await expect.element(frame()).toMatchScreenshot(shot("worker-monitoring-high-wide"));
  });

  it("fits the monitoring lane in a narrow panel", async () => {
    draw(MONITORING_GRAPH, 600);
    await settle();
    await expect.element(frame()).toMatchScreenshot(shot("worker-monitoring-high-narrow"));
  });

  it("shows an unavailable lane's reason", async () => {
    draw(COMMUNITY_ONLY_GRAPH);
    await settle();
    await expect.element(frame()).toMatchScreenshot(shot("community-only"));
  });

  it("opens the worker endpoint with its band, both tiers and absent reasons", async () => {
    draw();
    await settle();
    await userEvent.click(page.getByRole("button", { name: /Endpoint: Ratio to the occupational limit/ }));
    await settle();
    await expect.element(frame()).toMatchScreenshot(shot("worker-endpoint-detail"));
  });

  it("isolates one pathway", async () => {
    draw();
    await settle();
    await userEvent.click(page.getByRole("button", { name: "Worker, workplace air", exact: true }));
    await settle();
    await expect.element(frame()).toMatchScreenshot(shot("worker-lane-only"));
  });

  it("stops the flow when the user prefers reduced motion", async () => {
    window.matchMedia = (query: string) =>
      ({ ...realMatchMedia(query), matches: query.includes("reduce"), media: query, addEventListener() {}, removeEventListener() {} }) as MediaQueryList;
    draw();
    await settle();
    expect(document.querySelectorAll("[data-testid=flow-particle]")).toHaveLength(0);
    expect(document.querySelectorAll(".react-flow__edge")).toHaveLength(FULL_GRAPH.edges.length);
  });
});
