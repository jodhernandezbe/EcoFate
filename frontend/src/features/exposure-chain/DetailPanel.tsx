import { formatQuantity, type GraphNode } from "./graph";
import { KINDS } from "./kinds";

interface Props {
  node: GraphNode | null;
  laneLabel: string | null;
  digits: number;
  id: string;
  onClose: () => void;
}

/** The chosen step's quantities, facts and warnings exactly as the API sent them. */
export function DetailPanel({ node, laneLabel, digits, id, onClose }: Props) {
  if (!node) {
    return (
      <p id={id} className="m-0 text-xs text-fg2">
        Choose a step to see its values, sources and warnings.
      </p>
    );
  }
  return (
    <section id={id} aria-label={`${node.title} details`} className="@container rounded-xl border border-hairline bg-fg2/5 p-3 text-xs">
      <div className="flex items-center justify-between gap-2">
        <h4 className="m-0 text-sm font-semibold">
          {node.title}
          <span className="ml-2 font-normal text-fg2">{[KINDS[node.kind].badge, laneLabel].filter(Boolean).join(" · ")}</span>
        </h4>
        <button type="button" onClick={onClose} className="spring rounded-lg px-2 py-0.5 text-accent hover:underline">
          Close
        </button>
      </div>
      <dl className="m-0 mt-2 grid grid-cols-1 gap-x-4 gap-y-1.5 @xl:grid-cols-2 @4xl:grid-cols-3">
        {node.quantities.map((q) => (
          <div key={q.key}>
            <dt className="text-fg2">{q.label}</dt>
            <dd className={`m-0 tabular-nums ${q.value === null ? "text-fg2" : "text-fg"}`}>
              {q.value === null && q.reason ? q.reason : formatQuantity(q, digits)}
              {q.source ? <span className="block text-fg2">Source: {q.source}</span> : null}
            </dd>
          </div>
        ))}
        {node.facts.map((f) => (
          <div key={f.key}>
            <dt className="text-fg2">{f.label}</dt>
            <dd className={`m-0 ${f.text === null ? "text-fg2" : "text-fg"}`}>{f.text ?? f.reason ?? "not reported"}</dd>
          </div>
        ))}
      </dl>
      {node.quantities.length + node.facts.length === 0 && <p className="m-0 mt-2 text-fg2">No further values for this step.</p>}
      {node.warnings.length > 0 && (
        <ul className="m-0 mt-2 list-disc pl-4 text-warn">
          {node.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}
    </section>
  );
}
