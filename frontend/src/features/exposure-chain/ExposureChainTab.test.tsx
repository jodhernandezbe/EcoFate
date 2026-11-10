import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, describe, expect, it, vi } from "vitest";

import { installReactFlowStubs } from "../../test/fakeReactFlow";
import { facility, workspace } from "../../test/fixtures";
import { COMMUNITY_ONLY_GRAPH, FULL_GRAPH } from "../../test/graphs";
import type { ExposureGraph } from "../../types/api";
import { ExposureChainTab } from "./ExposureChainTab";

beforeAll(installReactFlowStubs);

function draw(graph: ExposureGraph | null = FULL_GRAPH, onPick = vi.fn()) {
  const f = facility({ name: "Plant F1", exposure_graph: graph });
  render(<ExposureChainTab facility={f} workspace={workspace({ facilities: [f] })} digits={2} onPick={onPick} />);
  return onPick;
}

const step = (name: RegExp) => screen.findByRole("button", { name });

describe("ExposureChainTab", () => {
  it("says what to do without a facility, and without a graph", () => {
    const { unmount } = render(<ExposureChainTab facility={null} workspace={workspace()} digits={2} onPick={vi.fn()} />);
    expect(screen.getByText(/No facility selected/)).toBeInTheDocument();
    unmount();
    draw(null);
    expect(screen.getByText(/no exposure chain yet/)).toBeInTheDocument();
  });

  it("draws every node the API sent, each stack and each age band", async () => {
    draw();
    expect(await step(/Stack 2/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Residents aged 0-4.*Inhalation dose 0.3 mg\/\(kg·day\)/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Residents aged 18-64/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Worker, indoor air, Endpoint: Ratio to the occupational limit/ })).toBeInTheDocument();
  });

  it("lists every connection with what it carries for screen readers", () => {
    draw();
    const items = within(screen.getByRole("list", { name: "Connections" })).getAllByRole("listitem").map((li) => li.textContent);
    expect(items).toContain("Stack 2 to Outdoor ambient air: Peak concentration 4 µg/m³");
    expect(items).toContain("Shift worker, 8-hour average to Ratio to the occupational limit: Ratio to the limit (worst case) 2");
    expect(items).toHaveLength(FULL_GRAPH.edges.length);
  });

  it("shows each lane's status in words, and an unavailable lane's reason", () => {
    draw(COMMUNITY_ONLY_GRAPH);
    const lanes = screen.getByRole("list", { name: "Pathways" });
    expect(within(lanes).getByText("Above concern")).toBeInTheDocument();
    expect(within(lanes).getByText("(no occupational result yet)")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Pathway" })).toBeNull();
  });

  it("opens a step's detail with sources and absent reasons, and closes it with Escape", async () => {
    draw();
    await userEvent.click(await step(/Endpoint: Ratio to the occupational limit/));
    const panel = screen.getByRole("region", { name: "Ratio to the occupational limit details" });
    expect(within(panel).getByText("Source: synthetic limit")).toBeInTheDocument();
    expect(within(panel).getAllByText("not reported by the tool").length).toBeGreaterThan(0); // the API's reason
    expect(within(panel).queryByText(/not reported \(/)).toBeNull(); // never the phrase and the reason both
    expect(within(panel).getByText("Ratio to the limit (baseline ventilation)")).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("region", { name: /details/ })).toBeNull();
  });

  it("dims the other lane while a step is hovered", async () => {
    draw();
    await userEvent.hover(await step(/Community, outdoor air, Pathway: Outdoor ambient air/));
    const workerAir = screen.getByRole("button", { name: /Worker, indoor air, Pathway/ });
    expect(workerAir.parentElement?.className).toContain("opacity-35");
  });

  it("isolates one pathway", async () => {
    draw();
    await step(/Stack 1/);
    await userEvent.click(screen.getByRole("button", { name: "Worker, indoor air" }));
    expect(await step(/Worker, indoor air, Release/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Stack 1/ })).toBeNull();
  });

  it("draws a lane the frontend has never seen", async () => {
    const extra: ExposureGraph = {
      lanes: [...FULL_GRAPH.lanes, { id: "dermal", label: "Dermal", available: true, reason: null, status: null, status_label: null }],
      nodes: [...FULL_GRAPH.nodes, { ...(FULL_GRAPH.nodes[1] ?? expect.fail("node")), id: "dermal:x", lane: "dermal", title: "Skin contact" }],
      edges: [...FULL_GRAPH.edges, { id: "source->dermal:x", source: "source", target: "dermal:x", lane: "dermal", quantity: null }],
    };
    draw(extra);
    expect(await step(/Dermal, .*Skin contact/)).toBeInTheDocument();
  });

  it("reports the facility the user picks", async () => {
    const onPick = draw();
    await userEvent.selectOptions(screen.getByLabelText("Facility"), "F1");
    expect(onPick).toHaveBeenCalledWith("F1");
  });
});
