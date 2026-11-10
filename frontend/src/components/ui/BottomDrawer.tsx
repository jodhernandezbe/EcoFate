import { Maximize2, Minimize2, X } from "lucide-react";
import { useId, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";

import { useFocusTrap } from "./useFocusTrap";

interface BottomDrawerProps {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  /** Starting height as a share (0-1) of the window height. */
  initialShare?: number;
  /** Smallest height, px. */
  minPx?: number;
  /** Open at the height of the content (up to the window) until the user resizes it. */
  fitContent?: boolean;
}

const KEY_STEP_PX = 24;
// The card floats inside the window: this far from its edges, and this share of its width
// (never narrower than the floor, never wider than the window).
const INSET_PX = 20;
const WIDTH_SHARE = 0.85;
const MIN_WIDTH_PX = 480;

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

/**
 * A modal card docked to the bottom of the window over a scrim: resizable by its top edge,
 * maximizable to the whole window, closed with Escape, the scrim or its close control. The
 * workspace behind it stays mounted, so nothing is lost while it is open.
 */
export function BottomDrawer({
  open,
  title,
  onClose,
  children,
  initialShare = 0.6,
  minPx = 360,
  fitContent = false,
}: BottomDrawerProps) {
  const titleId = useId();
  const panel = useRef<HTMLElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const [height, setHeight] = useState<number | null>(null);
  const [maximized, setMaximized] = useState(false);
  // Open on the content's first control (else Close), never on the window controls.
  useFocusTrap(open, panel, onClose, [content, closeButton]);
  if (!open) return null;

  const ceiling = () => window.innerHeight - 2 * INSET_PX;
  const fitting = fitContent && height === null && !maximized;
  const current = () => height ?? Math.round(window.innerHeight * initialShare);
  // Event handlers only: the auto-sized height is read from the DOM, which render must not do.
  const measured = () => (fitting && panel.current ? panel.current.offsetHeight : current());
  const resizeTo = (next: number) => setHeight(clamp(next, minPx, ceiling()));
  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (!event.currentTarget.hasPointerCapture(event.pointerId)) return;
    resizeTo(window.innerHeight - INSET_PX - event.clientY);
  };
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
    event.preventDefault();
    resizeTo(measured() + (event.key === "ArrowUp" ? KEY_STEP_PX : -KEY_STEP_PX));
  };
  // While auto-sized there is no height to read in render (the ref is only read in handlers).
  const shown = maximized ? window.innerHeight : fitting ? null : clamp(current(), minPx, ceiling());
  const width = `min(100%, max(${MIN_WIDTH_PX}px, ${WIDTH_SHARE * 100}%))`;
  const surface = `${title} panel`; // in every control's name, so a screen reader knows which drawer
  const frame = shown === null ? { width } : { height: shown, width: maximized ? "100%" : width };

  return (
    <div
      className={`fixed inset-0 z-50 flex flex-col items-center justify-end bg-black/30 ${maximized ? "" : "p-5"}`}
      onPointerDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        style={frame}
        className={`sheet-in relative flex max-h-full flex-col border border-hairline bg-solid shadow-[var(--shadow)] ${
          maximized ? "" : "rounded-2xl"
        }`}
      >
        <header className="flex shrink-0 items-center gap-2 px-5 pb-2 pt-4">
          <h2 id={titleId} className="flex-1 text-lg font-semibold tracking-tight">
            {title}
          </h2>
          <button
            type="button"
            aria-label={maximized ? `Restore ${surface} size` : `Maximize ${surface}`}
            onClick={() => setMaximized((value) => !value)}
            className="spring grid size-8 place-items-center rounded-full text-fg2 transition hover:bg-hairline hover:text-fg"
          >
            {maximized ? <Minimize2 size={16} aria-hidden="true" /> : <Maximize2 size={16} aria-hidden="true" />}
          </button>
          <button
            type="button"
            ref={closeButton}
            aria-label={`Close ${surface}`}
            onClick={onClose}
            className="spring grid size-8 place-items-center rounded-full text-fg2 transition hover:bg-hairline hover:text-fg"
          >
            <X size={16} aria-hidden="true" />
          </button>
        </header>
        {/* After the header in the DOM so Tab order runs title controls, handle, then content. */}
        {maximized ? null : (
          <div
            role="separator"
            aria-orientation="horizontal"
            aria-label={`Resize ${surface}`}
            aria-valuenow={shown ?? undefined}
            aria-valuemin={minPx}
            aria-valuemax={ceiling()}
            tabIndex={0}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onKeyDown={onKeyDown}
            className="group absolute inset-x-4 -top-1 z-10 h-2 cursor-row-resize touch-none"
          >
            <span className="mt-[3px] block h-[3px] w-full rounded-full bg-transparent transition-colors group-hover:bg-accent group-focus-visible:bg-accent" />
          </div>
        )}
        <div ref={content} className="min-h-0 flex-1 overflow-y-auto px-5 pb-5">
          {children}
        </div>
      </section>
    </div>
  );
}
