import type { ReactNode } from "react";

import { PanelHeader } from "./PanelHeader";

export type Fullscreen = "overview" | "map" | null;

interface PanelFrameProps {
  id: "overview" | "map";
  title: string;
  fullscreen: Fullscreen;
  onToggle: (id: "overview" | "map") => void;
  /** Whether the content scrolls (the overview) or fills the panel itself (the map). */
  scroll: boolean;
  /** Extra controls in the title bar, after the fullscreen toggle. */
  actions?: ReactNode;
  children: ReactNode;
}

/**
 * A titled panel of the analysis area. In fullscreen it covers the whole workspace by CSS alone,
 * so nothing is unmounted (the map keeps its camera and the chat its stream); while another
 * panel is fullscreen it is inert.
 */
export function PanelFrame({ id, title, fullscreen, onToggle, scroll, actions, children }: PanelFrameProps) {
  const mine = fullscreen === id;
  return (
    <section
      aria-label={title}
      inert={fullscreen !== null && !mine}
      className={`flex h-full min-h-0 min-w-0 flex-col bg-bg ${mine ? "fixed inset-0 z-30" : ""}`}
    >
      <PanelHeader title={title} fullscreen={mine} onToggleFullscreen={() => onToggle(id)}>
        {actions}
      </PanelHeader>
      <div className={`min-h-0 flex-1 ${scroll ? "scroll-edges overflow-y-auto" : "overflow-hidden"}`}>{children}</div>
    </section>
  );
}
