import { decisionColor } from "./TrustGauge";

const OPERATION_LABELS = { view: "View", edit: "Edit", admin: "Admin" };

export default function TrustVectorPanel({ vector, activeOperation, onSelect }) {
  if (!vector?.length) return null;

  return (
    <section className="vector-panel card">
      <h2>Trust vector T(t)</h2>
      <p className="muted">
        One independently-decaying trust component per operation class, each with
        its own behavioral baseline and thresholds -- not one global score.
        Verifying step-up re-earns trust for that operation only; it does not
        transfer to the others.
      </p>
      <div className="vector-row">
        {vector.map((v) => {
          const color = decisionColor(v.decision);
          const active = v.operation === activeOperation;
          return (
            <button
              key={v.operation}
              className={`vector-cell ${active ? "active" : ""}`}
              onClick={() => onSelect(v.operation)}
              type="button"
            >
              <span className="vector-cell-label">{OPERATION_LABELS[v.operation] || v.operation}</span>
              <span className="vector-cell-score" style={{ color }}>{v.trust_score.toFixed(0)}</span>
              <div className="vector-cell-bar-track">
                <div className="vector-cell-bar-fill" style={{ width: `${v.trust_score}%`, background: color }} />
                <div className="vector-cell-threshold" style={{ left: `${v.stepup_threshold}%` }} title={`step-up @ ${v.stepup_threshold}`} />
                <div className="vector-cell-threshold" style={{ left: `${v.allow_threshold}%` }} title={`allow @ ${v.allow_threshold}`} />
              </div>
              <span className={`vector-cell-decision ${v.decision}`}>{v.decision}</span>
            </button>
          );
        })}
      </div>
    </section>
  );
}
