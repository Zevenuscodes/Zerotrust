import { trustColor } from "./TrustGauge";

const FEATURE_LABELS = {
  mean_dwell_ms: "Mean key dwell time",
  std_dwell_ms: "Dwell time variability",
  mean_flight_ms: "Mean flight time (between keys)",
  std_flight_ms: "Flight time variability",
  mean_velocity: "Mean mouse velocity",
  std_velocity: "Mouse velocity variability",
  mean_acceleration: "Mean mouse acceleration",
  direction_changes: "Mouse direction changes",
};

function ParamRow({ label, score, detail }) {
  const color = trustColor(score);
  return (
    <div className="param-row">
      <div className="param-row-top">
        <span className="param-name">{label}</span>
        <span className="param-score" style={{ color }}>{score.toFixed(0)}</span>
      </div>
      <div className="param-bar-track">
        <div className="param-bar-fill" style={{ width: `${Math.max(0, Math.min(100, score))}%`, background: color }} />
      </div>
      {detail && <div className="param-detail">{detail}</div>}
    </div>
  );
}

export default function ParameterBreakdown({ featureScores, contextChecks }) {
  if (!featureScores?.length && !contextChecks?.length) return null;

  return (
    <section className="breakdown-panel card">
      <h2>Individual parameter scores</h2>
      <p className="muted">
        Every parameter below is scored 0-100 against your own historical
        baseline, then combined into behavior score (60%) and context score
        (40%).
      </p>

      {featureScores?.length > 0 && (
        <div className="param-group">
          <h3>Behavior (typing + mouse)</h3>
          {featureScores.map((f) => (
            <ParamRow
              key={f.name}
              label={FEATURE_LABELS[f.name] || f.name}
              score={f.score}
              detail={
                f.baseline_mean !== null && f.baseline_mean !== undefined
                  ? `value ${f.value} vs baseline ${f.baseline_mean} (z=${f.z_score})`
                  : "no baseline yet"
              }
            />
          ))}
        </div>
      )}

      {contextChecks?.length > 0 && (
        <div className="param-group">
          <h3>Context</h3>
          {contextChecks.map((c) => (
            <ParamRow key={c.name} label={c.name} score={c.score} detail={c.detail} />
          ))}
        </div>
      )}
    </section>
  );
}
