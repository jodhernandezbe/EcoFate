import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { COMMUNITY_ONLY_GRAPH, FULL_GRAPH, MONITORING_GRAPH } from "../../test/graphs";
import type { ExposureGraph } from "../../types/api";
import { ExposureChainTab } from "./ExposureChainTab";

const draw = (chain: ExposureGraph | null | undefined = FULL_GRAPH) => render(<ExposureChainTab chain={chain} digits={2} />);
const step = (name: RegExp) => screen.getByRole("button", { name });

describe("ExposureChainTab", () => {
  it("says what to do when there is no chain, or the server sends none", () => {
    const { unmount } = draw({ lanes: [], nodes: [], edges: [], caption: null });
    expect(screen.getByText(/No worst-case chain yet/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
    unmount();
    render(<ExposureChainTab digits={2} />);
    expect(screen.getByText(/No worst-case chain yet/)).toBeInTheDocument();
  });

  it("names no facility and offers no picker", () => {
    // FULL_GRAPH was built from a facility named "Plant F1" (FRS ID F1, with an address).
    const { container } = draw();
    expect(container.textContent).not.toContain("Plant F1");
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByLabelText("Facility")).toBeNull();
    expect(screen.getByRole("button", { name: /Source: Reported release of Benzene/ })).toBeInTheDocument();
  });

  it("draws one step per node the API sent, one stack and one age band, with its value", () => {
    draw();
    expect(screen.getAllByRole("button")).toHaveLength(FULL_GRAPH.nodes.length);
    expect(step(/Stack 2/)).toBeInTheDocument();
    expect(step(/Residents aged 0-4.*Inhalation dose 0.3 mg\/\(kg·day\)/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Stack 1/ })).toBeNull();
    expect(step(/Worker, workplace air, Endpoint: Ratio to the occupational limit/)).toBeInTheDocument();
  });

  it("shows the caption under the diagram", () => {
    draw();
    expect(screen.getByText(/Bands have a fixed width/)).toBeInTheDocument();
  });

  it("lists every connection with what it carries for screen readers", () => {
    draw();
    const items = within(screen.getByRole("list", { name: "Connections" })).getAllByRole("listitem").map((li) => li.textContent);
    expect(items).toContain("Stack 2 to Outdoor ambient air: Peak concentration 4 µg/m³");
    expect(items).toContain("Shift worker, 8-hour average to Ratio to the occupational limit: Ratio to the limit (worst case, upper bound) 2");
    expect(items).toHaveLength(FULL_GRAPH.edges.length);
  });

  it("shows each lane's status in words, and an unavailable lane's reason with no bands for it", () => {
    draw(COMMUNITY_ONLY_GRAPH);
    const lanes = screen.getByRole("list", { name: "Pathways" });
    expect(within(lanes).getByText("High")).toBeInTheDocument();
    expect(within(lanes).getByText("(no occupational result yet)")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Worker/ })).toBeNull();
  });

  it("reads an absent value as the API's reason, never 0", () => {
    const air = FULL_GRAPH.nodes.map((n) => (n.id === "community:air" ? { ...n, quantities: n.quantities.map((q) => ({ ...q, value: null, reason: "no wind data" })) } : n));
    draw({ ...FULL_GRAPH, nodes: air });
    expect(step(/Outdoor ambient air.*no wind data/)).toBeInTheDocument();
  });

  it("reads an absent band value from its reason in the connection list", () => {
    const edges = FULL_GRAPH.edges.map((e) =>
      e.id === "community:inhale->community:band:0-4" && e.quantity ? { ...e, quantity: { ...e.quantity, value: null, reason: "no dose reported" } } : e,
    );
    draw({ ...FULL_GRAPH, edges });
    expect(screen.getAllByText("no dose reported").length).toBeGreaterThan(0);
    expect(screen.queryByText("0 mg/(kg·day)")).toBeNull();
  });

  it("takes focus node by node in lane order, and Enter opens the detail", async () => {
    draw();
    const names = screen.getAllByRole("button").map((b) => b.getAttribute("aria-label") ?? "");
    expect(names[0]).toMatch(/Source/);
    expect(names.findIndex((n) => /^Community.*Endpoint/.test(n))).toBeLessThan(names.findIndex((n) => /^Worker.*Release/.test(n)));
    await userEvent.tab();
    expect(step(/Source/)).toHaveFocus();
    await userEvent.tab();
    expect(step(/Community, outdoor air, Release/)).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(screen.getByRole("region", { name: "Stack 2 details" })).toBeInTheDocument();
  });

  it("opens the community receptor's detail: age band, share, dose, residents, radius and the tracts without a location", async () => {
    draw();
    await userEvent.click(step(/Residents aged 0-4/));
    const panel = screen.getByRole("region", { name: "Residents aged 0-4 details" });
    expect(within(panel).getByText("Inhalation dose")).toBeInTheDocument();
    expect(within(panel).getByText("Residents")).toBeInTheDocument();
    expect(within(panel).getByText("Radius")).toBeInTheDocument();
    expect(within(panel).queryByText(/T1|T2/)).toBeNull();
  });

  it("opens a step's detail with sources and absent reasons, and closes it with Escape", async () => {
    draw();
    await userEvent.click(step(/Endpoint: Ratio to the occupational limit/));
    const panel = screen.getByRole("region", { name: "Ratio to the occupational limit details" });
    expect(within(panel).getByText("Source: OSHA PEL-TWA (PubChem)")).toBeInTheDocument();
    expect(within(panel).queryByText(/baseline|typical case/i)).toBeNull();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("region", { name: /details/ })).toBeNull();
  });

  it("stops Escape from reaching a layer above while a detail is open", async () => {
    const seen: boolean[] = [];
    render(
      <div onKeyDown={(e) => seen.push(e.defaultPrevented)}>
        <ExposureChainTab chain={FULL_GRAPH} digits={2} />
      </div>,
    );
    await userEvent.click(step(/Stack 2/));
    await userEvent.keyboard("{Escape}");
    expect(seen).toEqual([]);
  });

  it("keeps its open detail while the chain updates, and closes it when the node is gone", async () => {
    const { rerender } = draw();
    await userEvent.click(step(/Stack 2/));
    rerender(<ExposureChainTab chain={{ ...FULL_GRAPH }} digits={2} />);
    expect(screen.getByRole("region", { name: "Stack 2 details" })).toBeInTheDocument();
    rerender(<ExposureChainTab chain={null} digits={2} />);
    expect(screen.queryByRole("region", { name: /details/ })).toBeNull();
  });

  it("dims the other lane while a step is hovered or focused, and the source is never dimmed", async () => {
    draw();
    await userEvent.hover(step(/Community, outdoor air, Pathway: Outdoor ambient air/));
    expect(step(/Worker, workplace air, Pathway/).className).toContain("opacity-35");
    expect(step(/Community, outdoor air, Pathway/).className).not.toContain("opacity-35");
    expect(step(/Source/).className).not.toContain("opacity-35");
    await userEvent.unhover(step(/Community, outdoor air, Pathway/));
    expect(step(/Worker, workplace air, Pathway/).className).not.toContain("opacity-35");
    act(() => step(/Worker, workplace air, Release/).focus());
    expect(step(/Community, outdoor air, Pathway/).className).toContain("opacity-35");
  });

  it("draws a lane the frontend has never seen", () => {
    const extra: ExposureGraph = {
      ...FULL_GRAPH,
      lanes: [...FULL_GRAPH.lanes, { id: "dermal", label: "Dermal", available: true, reason: null, status: null, status_label: null }],
      nodes: [...FULL_GRAPH.nodes, { ...(FULL_GRAPH.nodes[1] ?? expect.fail("node")), id: "dermal:x", lane: "dermal", title: "Skin contact" }],
      edges: [...FULL_GRAPH.edges, { id: "source->dermal:x", source: "source", target: "dermal:x", lane: "dermal", quantity: null }],
    };
    draw(extra);
    expect(step(/Dermal, .*Skin contact/)).toBeInTheDocument();
  });

  it("draws a worker lane resting on monitoring data with its evidence node", async () => {
    draw(MONITORING_GRAPH);
    await userEvent.click(step(/Worker, workplace air, .*OSHA monitoring evidence/));
    const panel = screen.getByRole("region", { name: "OSHA monitoring evidence details" });
    expect(within(panel).getByText("OSHA CEHD (synthetic)")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Driving worker activity/ })).toBeNull();
  });
});
