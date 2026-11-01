import type { SessionSummary } from "../../types/workspace";
import { NOT_REPORTED, formatCost, formatCount, formatDuration, formatStarted, formatTokens } from "./format";
import { OutcomePill } from "./OutcomePill";

/** Which container width shows a column: always, from a medium pane, or only on a wide one. */
type Tier = "always" | "medium" | "wide";

const SHOWN_FROM: Record<Tier, string> = {
  always: "",
  medium: "hidden @3xl:table-cell",
  wide: "hidden @7xl:table-cell",
};

/** Fixed widths (the question takes what is left), so the table can never outgrow its pane. */
const COLUMNS: readonly { name: string; tier: Tier; width?: string }[] = [
  { name: "Started", tier: "always", width: "w-48" },
  { name: "Question", tier: "always" },
  { name: "Model", tier: "medium", width: "w-26" },
  { name: "Turns", tier: "medium", width: "w-18" },
  { name: "Model calls", tier: "wide", width: "w-24" },
  { name: "Tool calls", tier: "wide", width: "w-24" },
  { name: "Tokens", tier: "wide", width: "w-36" },
  { name: "Estimated cost", tier: "always", width: "w-28" },
  { name: "Duration", tier: "wide", width: "w-24" },
  { name: "Status", tier: "always", width: "w-30" },
];

/** The summary carries no reason for a failure; the timeline marks the step that failed. */
const FAILED_HINT = "Reason not reported here. Open this session to see which step failed.";

const cell = (tier: Tier) => `truncate px-3 py-2 ${SHOWN_FROM[tier]}`.trim();

interface SessionsTableProps {
  sessions: SessionSummary[];
  selectedId: string | null;
  onSelect: (sessionId: string) => void;
}

/**
 * The recorded sessions, newest first; selecting one opens its timeline. The table fits its pane:
 * columns have fixed widths, the question truncates (whole in its tooltip), and the less used
 * columns appear only when the container is wide enough for them.
 */
export function SessionsTable({ sessions, selectedId, onSelect }: SessionsTableProps) {
  return (
    <div className="@container">
      <div className="overflow-hidden rounded-2xl border border-hairline">
        <table className="w-full table-fixed text-left text-sm">
          <caption className="sr-only">Recorded sessions, newest first</caption>
          <thead className="text-xs text-fg2">
            <tr>
              {COLUMNS.map((column) => (
                <th
                  key={column.name}
                  scope="col"
                  className={`px-3 py-2 align-bottom font-semibold ${column.width ?? ""} ${SHOWN_FROM[column.tier]}`}
                >
                  {column.name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sessions.map((session) => {
              const selected = session.session_id === selectedId;
              return (
                <tr
                  key={session.session_id}
                  className={`border-t border-hairline ${selected ? "bg-hairline" : ""}`}
                >
                  <th scope="row" className="truncate px-3 py-2 text-left font-medium">
                    <button
                      type="button"
                      aria-pressed={selected}
                      onClick={() => onSelect(session.session_id)}
                      className="spring rounded-lg text-accent underline-offset-2 hover:underline"
                    >
                      {formatStarted(session.started_at)}
                    </button>
                  </th>
                  <td className={cell("always")} title={session.question ?? undefined}>
                    {session.question ?? NOT_REPORTED}
                  </td>
                  <td className={cell("medium")}>{session.model ?? NOT_REPORTED}</td>
                  <td className={cell("medium")}>{formatCount(session.turns)}</td>
                  <td className={cell("wide")}>{formatCount(session.model_calls)}</td>
                  <td className={cell("wide")}>{formatCount(session.tool_calls)}</td>
                  <td className={cell("wide")}>{formatTokens(session.input_tokens, session.output_tokens)}</td>
                  <td className={cell("always")}>{formatCost(session)}</td>
                  <td className={cell("wide")}>{formatDuration(session.duration_ms)}</td>
                  <td
                    className="px-3 py-2"
                    title={session.outcome === "error" ? FAILED_HINT : undefined}
                  >
                    <OutcomePill outcome={session.outcome} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
