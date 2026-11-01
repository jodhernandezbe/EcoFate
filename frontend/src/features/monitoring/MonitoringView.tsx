import { Info, RefreshCw } from "lucide-react";

import { Banner } from "../../components/ui/Banner";
import { useMonitoring, type Loadable } from "../../hooks/useMonitoring";
import type { SessionDetailResponse, SessionsResponse } from "../../types/workspace";
import { SessionsTable } from "./SessionsTable";
import { TurnTimeline } from "./SessionTimeline";

const NO_SESSIONS =
  "No sessions were recorded in the monitoring window yet. Ask the copilot a question, then refresh.";

function Progress({ children }: { children: string }) {
  return (
    <p role="status" className="text-sm text-fg2">
      {children}
    </p>
  );
}

function Retry({ onRetry }: { onRetry: () => void }) {
  return (
    <button
      type="button"
      onClick={onRetry}
      className="spring mt-2 rounded-lg bg-accent px-3 py-1.5 text-sm font-medium text-accent-fg"
    >
      Retry
    </button>
  );
}

/** Why there is nothing to show: monitoring not set up (information) or Logfire failing (retry). */
function Unavailable({
  response,
  onRetry,
}: {
  response: SessionsResponse | SessionDetailResponse;
  onRetry: () => void;
}) {
  const message = response.message ?? "Monitoring is not available.";
  if (response.state === "not_configured") {
    return (
      <p role="status" className="flex items-start gap-2 rounded-xl border border-hairline px-3 py-2 text-sm">
        <Info size={16} aria-hidden="true" className="mt-0.5 shrink-0 text-fg2" />
        <span>{message}</span>
      </p>
    );
  }
  return (
    <div>
      <Banner kind="error">{message}</Banner>
      <Retry onRetry={onRetry} />
    </div>
  );
}

function Failed({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div>
      <Banner kind="error">{message}</Banner>
      <Retry onRetry={onRetry} />
    </div>
  );
}

function Detail({ detail, onRetry }: { detail: Loadable<SessionDetailResponse>; onRetry: () => void }) {
  if (detail.status === "loading") return <Progress>Loading session…</Progress>;
  if (detail.status === "failed") return <Failed message={detail.message} onRetry={onRetry} />;
  if (detail.value.state !== "ok") return <Unavailable response={detail.value} onRetry={onRetry} />;
  return (
    <div className="flex flex-col gap-3">
      {detail.value.turns.map((turn, index) => (
        <TurnTimeline key={turn.trace_id} turn={turn} index={index} />
      ))}
    </div>
  );
}

/**
 * The Monitoring view: the sessions recorded in Logfire and, for the selected one, its turns with
 * their model and tool calls in order. It shows only what the server read back from Logfire.
 */
export function MonitoringView() {
  const { sessions, selected, detail, refresh, select } = useMonitoring();
  const reload = () => void refresh();
  return (
    <section aria-label="Monitoring" className="h-full overflow-y-auto p-4">
      <header className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-lg font-semibold">Monitoring</h2>
        <button
          type="button"
          onClick={reload}
          disabled={sessions.status === "loading"}
          className="spring inline-flex items-center gap-1.5 rounded-lg border border-hairline px-3 py-1.5 text-sm text-fg2 hover:text-fg disabled:opacity-40"
        >
          <RefreshCw size={14} aria-hidden="true" />
          Refresh
        </button>
      </header>
      {sessions.status === "loading" ? <Progress>Loading sessions…</Progress> : null}
      {sessions.status === "failed" ? <Failed message={sessions.message} onRetry={reload} /> : null}
      {sessions.status === "loaded" && sessions.value.state !== "ok" ? (
        <Unavailable response={sessions.value} onRetry={reload} />
      ) : null}
      {sessions.status === "loaded" && sessions.value.state === "ok" ? (
        sessions.value.sessions.length === 0 ? (
          <p className="text-sm text-fg2">{NO_SESSIONS}</p>
        ) : (
          <div className="flex flex-col gap-4">
            <SessionsTable
              sessions={sessions.value.sessions}
              selectedId={selected}
              onSelect={(id) => void select(id)}
            />
            {selected ? (
              <section aria-label="Session timeline" className="flex flex-col gap-2">
                <h3 className="text-sm font-semibold text-fg2">Session timeline</h3>
                <Detail detail={detail} onRetry={() => void select(selected)} />
              </section>
            ) : null}
          </div>
        )
      ) : null}
    </section>
  );
}
