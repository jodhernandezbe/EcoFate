import type { Map as MapLibreMap } from "maplibre-gl";
import { useEffect, useId, useReducer, useRef, useState } from "react";

import type { Facility } from "../../types/workspace";
import { FacilityHoverCard } from "./FacilityHoverCard";
import { type MarkerScale, facilityCollection } from "./mapData";

// Room the card needs beside and above a marker; it flips to the other side without it (px).
const CARD_WIDTH_PX = 336;
const CARD_HEIGHT_PX = 420;
const GAP_PX = 12;

interface Active {
  frsId: string;
  flipX: boolean;
  flipY: boolean;
  /** Opened by a click: it stays while the pointer leaves, takes the pointer, and folds. */
  pinned: boolean;
  /** Tallest the card may be: the overlay less the gaps (px). */
  maxHeight: number;
}

function useMapMoves(map: MapLibreMap): void {
  const [, redraw] = useReducer((n: number) => n + 1, 0);
  useEffect(() => {
    map.on("move", redraw);
    map.on("resize", redraw);
    return () => {
      map.off("move", redraw);
      map.off("resize", redraw);
    };
  }, [map]);
}

/**
 * One keyboard-focusable button over every marker (a canvas marker cannot take focus), and the
 * glass card of the facility that is hovered or focused; a click pins it so its sections can be
 * folded and it can be read at leisure. Escape closes it; leaving or blurring closes an
 * unpinned one; a click on the map closes a pinned one.
 */
/** Name, community status and, when computed, the worker tier: what a marker announces. */
function markerLabel(facility: Facility): string {
  const name = facility.name ?? `FRS ${facility.frs_id}`;
  const tier = facility.occupational_exposure?.risk_tier;
  const community = facility.worker_only ? "reports no stack release" : (facility.status ?? "risk not computed");
  return `${name}, ${community}${tier ? `, worker ${tier}` : ""}`;
}

export function FacilityInspector({
  map,
  facilities,
  scale,
  digits,
  onPin,
  onPinned,
}: {
  map: MapLibreMap;
  facilities: Facility[];
  scale: MarkerScale;
  digits: number;
  /** Told which facility a click pinned (not when it is unpinned, hovered or focused). */
  onPin?: (frsId: string) => void;
  /** Told which facility is pinned right now, or null when none is (also after it is closed). */
  onPinned?: (frsId: string | null) => void;
}) {
  const overlay = useRef<HTMLDivElement>(null);
  const cardId = useId();
  const [active, setActive] = useState<Active | null>(null);
  useMapMoves(map);
  const pinnedId = active?.pinned ? active.frsId : null;
  useEffect(() => onPinned?.(pinnedId), [onPinned, pinnedId]);

  useEffect(() => {
    if (!active?.pinned) return;
    const unpin = () => setActive(null);
    map.on("click", unpin);
    return () => {
      map.off("click", unpin);
    };
  }, [map, active?.pinned]);

  useEffect(() => {
    if (!active) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      // Handled here: a layer below (leaving fullscreen) must not also act on this key.
      event.preventDefault();
      event.stopPropagation();
      setActive(null);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [active]);

  const radii = facilityCollection(facilities, scale).features;
  const placed = (facility: Facility, x: number, y: number, pinned: boolean): Active => {
    const box = overlay.current?.getBoundingClientRect();
    if (!box) {
      return { frsId: facility.frs_id, flipX: false, flipY: false, pinned, maxHeight: CARD_HEIGHT_PX };
    }
    // The card grows from the marker, up by default and down when there is little room above,
    // so it may be no taller than the room on that side: the overlay clips what sticks out, and
    // a clipped part cannot be scrolled to.
    const above = Math.max(y - GAP_PX, 0);
    const below = Math.max(box.height - y - GAP_PX, 0);
    const flipY = above < CARD_HEIGHT_PX && below > above;
    return {
      frsId: facility.frs_id,
      flipX: box.width - x < CARD_WIDTH_PX + GAP_PX,
      flipY,
      pinned,
      maxHeight: flipY ? below : above,
    };
  };
  // Hovering or focusing shows a facility unless another one is pinned.
  const open = (facility: Facility, x: number, y: number) =>
    setActive((now) => (now?.pinned && now.frsId !== facility.frs_id ? now : placed(facility, x, y, now?.pinned ?? false)));
  const pin = (facility: Facility, x: number, y: number) => {
    if (!(active?.pinned && active.frsId === facility.frs_id)) onPin?.(facility.frs_id);
    setActive((now) =>
      now?.pinned && now.frsId === facility.frs_id ? null : placed(facility, x, y, true),
    );
  };
  const close = (frsId: string) =>
    setActive((now) => (now?.frsId === frsId && !now.pinned ? null : now));

  return (
    <div ref={overlay} className="pointer-events-none absolute inset-0 z-10 overflow-hidden">
      {facilities.map((facility, index) => {
        const { x, y } = map.project([facility.longitude, facility.latitude]);
        const radius = radii[index]?.properties.radius_px ?? scale.minPx;
        const isActive = active?.frsId === facility.frs_id;
        return (
          <div key={facility.frs_id}>
            <button
              type="button"
              aria-label={markerLabel(facility)}
              aria-describedby={isActive ? cardId : undefined}
              className="pointer-events-auto absolute -translate-x-1/2 -translate-y-1/2 cursor-pointer rounded-full bg-transparent"
              style={{ left: x, top: y, width: radius * 2, height: radius * 2 }}
              aria-pressed={isActive && active?.pinned ? true : undefined}
              onMouseEnter={() => open(facility, x, y)}
              onMouseLeave={() => close(facility.frs_id)}
              onFocus={() => open(facility, x, y)}
              onBlur={() => close(facility.frs_id)}
              onClick={() => pin(facility, x, y)}
            />
            {isActive && active && (
              <div
                className="absolute"
                style={{
                  left: x + (active.flipX ? -(radius + GAP_PX) : radius + GAP_PX),
                  top: y,
                  transform: `translate(${active.flipX ? "-100%" : "0"}, ${active.flipY ? "0" : "-100%"})`,
                }}
              >
                <FacilityHoverCard
                  facility={facility}
                  digits={digits}
                  id={cardId}
                  pinned={active.pinned}
                  maxHeight={active.maxHeight}
                  onClose={() => setActive(null)}
                />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
