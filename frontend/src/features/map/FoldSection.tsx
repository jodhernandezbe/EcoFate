import { ChevronRight } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

interface FoldProps {
  title: string;
  /** Shown beside the title: a count, or the status pill. */
  aside?: ReactNode;
  initiallyOpen: boolean;
  children: ReactNode;
}

/** A titled part of the inspector card that folds; its heading is the toggle (usable once pinned). */
export function FoldSection({ title, aside, initiallyOpen, children }: FoldProps) {
  const [open, setOpen] = useState(initiallyOpen);
  const bodyId = useId();
  return (
    <section className="mt-2">
      <div className="flex items-center justify-between gap-2">
        <h4 className="m-0 text-xs font-semibold text-fg2">
          <button
            type="button"
            aria-expanded={open}
            aria-controls={bodyId}
            onClick={() => setOpen((value) => !value)}
            className="flex items-center gap-1 rounded-lg hover:text-fg"
          >
            <ChevronRight
              size={12}
              aria-hidden="true"
              className={`transition-transform duration-200 ${open ? "rotate-90" : ""}`}
            />
            {title}
          </button>
        </h4>
        {aside}
      </div>
      <div id={bodyId} hidden={!open} className="mt-1">
        {children}
      </div>
    </section>
  );
}
