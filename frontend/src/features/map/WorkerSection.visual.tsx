import "../../index.css";

import { cleanup, render } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { page } from "vitest/browser";

import {
  activity,
  facility,
  monitoredWorker,
  worker,
  workerOnly,
} from "../../test/fixtures";
import { MapLegend } from "./MapLegend";
import { WorkerSection } from "./WorkerSection";

afterEach(cleanup);

/** The inspector card's width; synthetic fixtures only, never real measurements. */
function Frame({
  children,
  width = 380,
}: {
  children: ReactNode;
  width?: number;
}) {
  return (
    <div
      data-testid="frame"
      style={{
        width,
        padding: 16,
        background: "var(--surface)",
        color: "var(--fg)",
      }}
    >
      {children}
    </div>
  );
}

const frame = () => page.getByTestId("frame");
/** Light and dark run as two projects; each keeps its own references. */
const shot = (name: string) =>
  `${name}-${window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"}`;

describe("inspector worker section and map legend, in a real browser", () => {
  it("shows a modelled worker result with its activities, bands in words and context", async () => {
    render(
      <Frame>
        <WorkerSection
          facility={facility({ occupational_exposure: worker() })}
          digits={2}
        />
      </Frame>,
    );
    await expect
      .element(frame())
      .toMatchScreenshot(shot("worker-section-model"));
  });

  it("shows a result resting on OSHA monitoring, with the modelled activities still listed", async () => {
    render(
      <Frame>
        {/* One activity keeps the state inside the 900 px screenshot viewport. */}
        <WorkerSection
          facility={facility({
            occupational_exposure: monitoredWorker({
              activities: [activity()],
            }),
          })}
          digits={2}
        />
      </Frame>,
    );
    await expect
      .element(frame())
      .toMatchScreenshot(shot("worker-section-monitoring"));
  });

  it("says the worker result is not reported when the API sent none", async () => {
    render(
      <Frame>
        <WorkerSection
          facility={facility({ occupational_exposure: null })}
          digits={2}
        />
      </Frame>,
    );
    await expect
      .element(frame())
      .toMatchScreenshot(shot("worker-section-absent"));
  });

  it("shows a worker-only facility", async () => {
    render(
      <Frame>
        <WorkerSection facility={workerOnly()} digits={2} />
      </Frame>,
    );
    await expect
      .element(frame())
      .toMatchScreenshot(shot("worker-section-worker-only"));
  });

  it("explains the fill, the worker ring and the outlined worker-only marker in the legend", async () => {
    render(
      <Frame width={300}>
        {/* The legend is absolutely placed over the map; this box stands in for the map. */}
        <div style={{ position: "relative", height: 440 }}>
          <MapLegend
            facilities={[
              facility({ occupational_exposure: worker() }),
              workerOnly(),
            ]}
            hidden={new Set()}
            onToggle={() => {}}
          />
        </div>
      </Frame>,
    );
    await expect.element(frame()).toMatchScreenshot(shot("map-legend-bands"));
  });
});
