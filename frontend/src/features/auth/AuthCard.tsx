import type { FormEvent, ReactNode } from "react";

import { Banner } from "../../components/ui/Banner";
import { BrandLogo } from "../../components/ui/BrandLogo";
import { GlassCard } from "../../components/ui/GlassCard";

interface AuthCardProps {
  title: string;
  /** One sentence under the title. */
  lead?: string;
  children: ReactNode;
  /** Links to the other screens, under the form. */
  footer?: ReactNode;
}

/** The page every account screen sits on: the brand, a title and one glass card. */
export function AuthCard({ title, lead, children, footer }: AuthCardProps) {
  return (
    <main className="grid min-h-dvh place-items-center bg-bg p-4">
      <GlassCard className="flex w-full max-w-sm flex-col gap-4 p-6">
        <BrandLogo size={36} label="Exposure & Risk Studio" />
        <div className="flex flex-col gap-1">
          <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
          {lead ? <p className="text-sm text-fg2">{lead}</p> : null}
        </div>
        {children}
        {footer ? <div className="flex flex-col gap-1 text-sm text-fg2">{footer}</div> : null}
      </GlassCard>
    </main>
  );
}

/** A text-styled button that moves to another screen. */
export function LinkButton({ onClick, children }: { onClick: () => void; children: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="spring w-fit rounded-lg text-accent underline-offset-2 hover:underline"
    >
      {children}
    </button>
  );
}

interface FormProps {
  onSubmit: () => void;
  busy: boolean;
  /** What the status line says while the request runs. */
  progress: string;
  error: string | null;
  submitLabel: string;
  children: ReactNode;
}

/** A form with its progress line, error banner and one accent submit button. */
export function AuthForm({ onSubmit, busy, progress, error, submitLabel, children }: FormProps) {
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!busy) onSubmit();
  };
  return (
    <form onSubmit={submit} aria-busy={busy} className="flex flex-col gap-3">
      {children}
      {error ? <Banner kind="error">{error}</Banner> : null}
      {busy ? (
        <p role="status" className="text-xs text-fg2">
          {progress}
        </p>
      ) : null}
      <button
        type="submit"
        disabled={busy}
        className="spring rounded-xl bg-accent px-4 py-2 text-sm font-semibold text-accent-fg transition disabled:opacity-40"
      >
        {submitLabel}
      </button>
    </form>
  );
}
