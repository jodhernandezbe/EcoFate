import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { cloneElement, type ReactElement } from "react";
import { describe, expect, it, vi } from "vitest";

import { facility, profile, workspace, worker } from "../../test/fixtures";
import type { Facility } from "../../types/workspace";
import { OverviewPanel } from "./OverviewPanel";

vi.mock("recharts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("recharts")>();
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: ReactElement }) =>
      cloneElement(children, { width: 600, height: 300 } as object),
  };
});

const bands = {
  hq_lower: 0.1,
  hq_upper: 1,
  cancer_risk_lower: 1e-6,
  cancer_risk_upper: 1e-4,
  oel_ratio_lower: 0.1,
  oel_ratio_upper: 1,
};
const extreme = (high: number) => ({ low: high / 2, high, low_stack: 1, high_stack: 2 });
const exposure = (hq: number, risk: number | null) => ({
  stacks_given: 1,
  stacks_evaluated: 1,
  hq_worst: extreme(hq),
  hq_representative: null,
  cancer_risk_worst: risk === null ? null : extreme(risk),
  cancer_risk_representative: null,
  concentration_worst: extreme(10),
  concentration_representative: null,
  dose: null,
  warnings: [],
});
const cond = (stage: string, category: string) => ({
  tri_activity: "a", tri_section: "3.2a", lifecycle_stage: stage, cou_category: category, mapping_strength: "Direct",
});
const plant = (id: string, code: string, hq: number, risk: number | null, over: Partial<Facility> = {}) =>
  facility({
    frs_id: id,
    name: `Plant ${id}`,
    naics_subsector: code,
    naics_subsector_title: `Industry ${code}`,
    exposure: exposure(hq, risk),
    conditions_of_use: [cond("Processing", "Reactant")],
    lifecycle_stages: ["Processing"],
    ...over,
  });

const facilities = ["1", "2", "3", "4", "5", "6"].map((n, i) => plant(`F${n}`, `30${n}`, i + 1, 10 - i));
/** The panel on its risk view (the summary is the default; the sections are hidden until chosen). */
const show = (fs: Facility[] = facilities) => {
  const view = render(
    <OverviewPanel
      workspace={workspace({ facilities: fs })}
      digits={2}
      bands={bands}
    />,
  );
  if (fs.length > 0) fireEvent.click(screen.getByRole("button", { name: "Risk by group" }));
  return view;
};

const section = (name: RegExp) => screen.getByRole("region", { name });
/** The rows of a section's chart (its text table). */
const rowsOf = (name: RegExp) =>
  within(within(section(name)).getByRole("table", { hidden: true })).getAllByRole("row", { hidden: true }).slice(1);

describe("risk-by-group sections", () => {
  it("shows the three sections on the risk view, and nothing below them", () => {
    show();
    expect(section(/Risk by industry/)).toBeInTheDocument();
    expect(section(/Risk by condition of use/)).toBeInTheDocument();
    expect(section(/Risk by life cycle stage/)).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Results" })).toBeNull();
    expect(screen.queryByRole("table", { name: /Results/ })).toBeNull();
  });

  it("shows the sections even with no facilities", () => {
    show([]);
    fireEvent.click(screen.getByRole("button", { name: "Risk by group" }));
    expect(screen.getAllByRole("region", { name: /Risk by/ })).toHaveLength(3);
  });

  it("keeps the top five industries by hazard quotient, highest first", () => {
    show();
    const industry = /Risk by industry/;
    const rows = rowsOf(industry);
    expect(rows).toHaveLength(5);
    expect(rows[0]).toHaveTextContent("306 · Industry 306");
    expect(within(section(industry)).getByText("1 more group not shown.")).toBeInTheDocument();
    expect(within(section(industry)).getByRole("heading", { name: /Hazard quotient/ })).toBeInTheDocument();
  });

  it("switches to the cancer risk, on its own chart and ranking, never both at once", () => {
    show();
    const industry = /Risk by industry/;
    fireEvent.click(within(section(industry)).getByRole("button", { name: "Cancer risk" }));
    expect(within(section(industry)).getByRole("heading", { name: /Lifetime cancer risk/ })).toBeInTheDocument();
    expect(within(section(industry)).queryByRole("heading", { name: /Hazard quotient/ })).toBeNull();
    expect(rowsOf(industry)[0]).toHaveTextContent("301 · Industry 301");
    expect(within(section(industry)).getByRole("button", { name: "Cancer risk" })).toHaveAttribute("aria-pressed", "true");
    expect(within(section(industry)).getByRole("button", { name: "Hazard quotient" })).toHaveAttribute("aria-pressed", "false");
  });

  it("changes all three sections together", () => {
    show();
    fireEvent.click(within(section(/Risk by industry/)).getByRole("button", { name: "Cancer risk" }));
    for (const name of [/condition of use/, /life cycle stage/]) {
      expect(within(section(name)).getByRole("heading", { name: /Lifetime cancer risk/ })).toBeInTheDocument();
    }
  });

  it("explains that a facility with several conditions appears in each", () => {
    show();
    expect(within(section(/condition of use/)).getByText(/appears in each, so bars can overlap/)).toBeInTheDocument();
    expect(within(section(/Risk by industry/)).queryByText(/bars can overlap/)).toBeNull();
  });

  it("says nothing was assessed instead of drawing an empty chart", () => {
    show([facility({ frs_id: "X", naics_subsector: "325", naics_subsector_title: "Chemicals" })]);
    for (const name of [/industry/, /condition of use/, /life cycle stage/]) {
      expect(within(section(name)).getByText(/Nothing assessed yet/)).toBeInTheDocument();
    }
  });

  it("counts facilities that belong to no industry", () => {
    show([...facilities, facility({ frs_id: "N", name: "No code" })]);
    expect(within(section(/Risk by industry/)).getByText("1 facility: industry not reported.")).toBeInTheDocument();
  });
});

describe("overview views", () => {
  const render0 = (fs: Facility[]) =>
    render(<OverviewPanel workspace={workspace({ facilities: fs })} digits={2} bands={bands} />);

  it("opens on the summary, with the charts one click away", () => {
    render0(facilities);
    expect(screen.getByRole("group", { name: "Executive summary" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /Risk by/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Summary" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Risk by group" }));
    expect(screen.getAllByRole("region", { name: /Risk by/ })).toHaveLength(3);
    expect(screen.queryByRole("group", { name: "Executive summary" })).toBeNull();
  });

  it("goes back to the summary and returns to the charts, keeping the quantity chosen", () => {
    render0(facilities);
    fireEvent.click(screen.getByRole("button", { name: "Risk by group" }));
    fireEvent.click(within(section(/Risk by industry/)).getByRole("button", { name: "Cancer risk" }));
    fireEvent.click(screen.getByRole("button", { name: "Summary" }));
    expect(screen.getByRole("group", { name: "Executive summary" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Risk by group" }));
    expect(screen.getAllByRole("region", { name: /Risk by/ })).toHaveLength(3);
    expect(within(section(/Risk by industry/)).getByRole("button", { name: "Cancer risk" })).toHaveAttribute("aria-pressed", "true");
  });

  it("shows the three empty sections before anything has run, so they are discoverable", () => {
    render0([]);
    expect(screen.getByRole("group", { name: "Overview view" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Risk by group" }));
    expect(screen.getByText("No facilities assessed yet.")).toBeInTheDocument();
    expect(screen.queryByText(/0 facilities/)).toBeNull(); // no count before there is something to count
    expect(screen.getAllByRole("region", { name: /Risk by/ })).toHaveLength(3);
    expect(screen.getAllByText(/Nothing to show yet/)).toHaveLength(3);
  });

  it("counts the facilities and how many have a worst-case result", () => {
    render0(facilities);
    fireEvent.click(screen.getByRole("button", { name: "Risk by group" }));
    expect(screen.getByText("6 facilities in this run, 6 with a worst-case result.")).toBeInTheDocument();
  });
});

describe("expanding a section", () => {
  it("fills the panel, hides the rest without unmounting it, and restores", async () => {
    const { container } = show();
    const industry = section(/Risk by industry/);
    await userEvent.click(within(industry).getByRole("button", { name: "Expand section" }));
    expect(within(industry).getByRole("button", { name: "Restore section" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByRole("region", { name: /condition of use/ })).toBeNull();
    expect(container.querySelector('[aria-label="Executive summary"]')).not.toBeNull();
    await userEvent.click(within(industry).getByRole("button", { name: "Restore section" }));
    expect(screen.getByRole("region", { name: /condition of use/ })).toBeInTheDocument();
  });

  it("restores on Escape and keeps the key from leaving the panel", async () => {
    const reached = vi.fn();
    window.addEventListener("keydown", reached);
    show();
    const industry = section(/Risk by industry/);
    await userEvent.click(within(industry).getByRole("button", { name: "Expand section" }));
    await userEvent.keyboard("{Escape}");
    expect(screen.getByRole("region", { name: /condition of use/ })).toBeInTheDocument();
    expect(reached.mock.calls.filter(([e]) => e.key === "Escape")).toHaveLength(0);
    await userEvent.keyboard("{Escape}");
    expect(reached.mock.calls.filter(([e]) => e.key === "Escape")).toHaveLength(1); // nothing expanded: not ours
    window.removeEventListener("keydown", reached);
  });
});

describe("exposure pathway dropdown", () => {
  const indoor = (id: string, code: string, ratio: number | null, hq: number | null) =>
    plant(id, code, 1, null, {
      occupational_exposure: worker({
        baseline: { ...worker().baseline, oel_ratio: ratio, hq, cancer_risk: null },
      }),
      operational_profile: profile(),
    });
  const mixed = [indoor("W1", "301", 3, 0.2), indoor("W2", "302", 0.5, 0.9), indoor("W3", "303", null, null)];
  const picker = () => screen.getByRole("combobox", { name: /Exposure pathway/ });

  it("offers one dropdown for the whole view, outdoor air to the general population first", () => {
    show(mixed);
    expect(screen.getAllByRole("combobox", { name: /Exposure pathway/ })).toHaveLength(1);
    const options = within(picker()).getAllByRole("option").map((o) => o.textContent);
    expect(options).toEqual(["Outdoor Air → Inhalation → General Population", "Indoor Air → Inhalation → Worker"]);
    expect(picker()).toHaveValue("outdoor");
  });

  it("ranks the workers on the indoor pathway, with their quantities and boundaries", () => {
    show(mixed);
    const industry = /Risk by industry/;
    fireEvent.change(picker(), { target: { value: "indoor" } });
    expect(within(section(industry)).getByRole("heading", { name: /Worker hazard quotient/ })).toBeInTheDocument();
    expect(rowsOf(industry)[0]).toHaveTextContent("0.9");
    expect(within(section(industry)).getByRole("button", { name: "Limit ratio" })).toBeInTheDocument();
    fireEvent.click(within(section(industry)).getByRole("button", { name: "Limit ratio" }));
    expect(within(section(industry)).getByRole("heading", { name: /occupational limit/ })).toBeInTheDocument();
    expect(rowsOf(industry)[0]).toHaveTextContent("301 · Industry 301");
    expect(within(section(industry)).getByText(/Dashed lines: moderate 0\.1, high 1/)).toBeInTheDocument();
  });

  it("changes all three sections together", () => {
    show(mixed);
    fireEvent.change(picker(), { target: { value: "indoor" } });
    for (const name of [/Risk by industry/, /condition of use/, /life cycle stage/]) {
      expect(within(section(name)).getByRole("button", { name: "Limit ratio" })).toBeInTheDocument();
    }
  });

  it("offers no limit ratio outdoors, and falls back to the hazard quotient when leaving workers", () => {
    show(mixed);
    const industry = /Risk by industry/;
    expect(within(section(industry)).queryByRole("button", { name: "Limit ratio" })).toBeNull();
    fireEvent.change(picker(), { target: { value: "indoor" } });
    fireEvent.click(within(section(industry)).getByRole("button", { name: "Limit ratio" }));
    fireEvent.change(picker(), { target: { value: "outdoor" } });
    expect(within(section(industry)).queryByRole("button", { name: "Limit ratio" })).toBeNull();
    expect(within(section(industry)).getByRole("button", { name: "Hazard quotient" })).toHaveAttribute("aria-pressed", "true");
  });

  it("says why nothing is ranked when no facility has a worker value", () => {
    show([plant("P1", "301", 1, null)]);
    fireEvent.change(picker(), { target: { value: "indoor" } });
    expect(within(section(/Risk by industry/)).getByText(/No group has a worker hazard quotient to rank/)).toBeInTheDocument();
  });
});

describe("OverviewPanel exposure chain tab", () => {
  it("offers a third tab and keeps the slot mounted across tabs", async () => {
    render(<OverviewPanel workspace={workspace()} digits={2} chain={<p>chain slot</p>} />);
    expect(screen.getByRole("button", { name: "Exposure chain" })).toBeInTheDocument();
    expect(screen.getByText("chain slot")).not.toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Exposure chain" }));
    expect(screen.getByText("chain slot")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Summary" }));
    expect(screen.getByText("chain slot")).not.toBeVisible();
    expect(screen.getByRole("group", { name: "Executive summary" })).toBeVisible();
  });
});
