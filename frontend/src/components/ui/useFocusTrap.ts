import { useEffect, useRef, type RefObject } from "react";

const FOCUSABLE =
  'button:not([disabled]), input:not([disabled]), [href], [tabindex]:not([tabindex="-1"])';

/** The first focusable element of `start`: itself when it is focusable, else its first descendant. */
function firstIn(start: HTMLElement | null): HTMLElement | undefined {
  if (!start) return undefined;
  return start.matches(FOCUSABLE) ? start : (start.querySelector<HTMLElement>(FOCUSABLE) ?? undefined);
}

/**
 * While `active`, keeps Tab inside `container`, closes on Escape (marking the event handled so
 * layers below ignore it) and returns focus to the element that had it on close.
 *
 * On opening, focus goes to the first focusable element of the first of `starts` that has one
 * (for example the content, then the close button); without `starts`, to the first in `container`.
 */
export function useFocusTrap(
  active: boolean,
  container: RefObject<HTMLElement | null>,
  onClose: () => void,
  starts: readonly RefObject<HTMLElement | null>[] = [],
): void {
  const close = useRef(onClose);
  useEffect(() => {
    close.current = onClose;
  });

  useEffect(() => {
    if (!active) return;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const items = () => Array.from(container.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []);
    const preferred = starts.map((start) => firstIn(start.current)).find(Boolean);
    (preferred ?? items()[0])?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        close.current();
        return;
      }
      if (event.key !== "Tab") return;
      const list = items();
      const first = list[0];
      const last = list[list.length - 1];
      if (!first || !last) return;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      previous?.focus();
    };
    // `starts` are refs: stable across renders, read only when the trap opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, container]);
}
