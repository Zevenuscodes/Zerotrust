import { trustColor } from "./TrustGauge";

const FAMILY_LABELS = {
  integrity: "Session integrity",
  impossible: "Impossible conditions",
  automation: "Human vs automated",
  patterns: "Access habits",
};

const FAMILY_BLURB = {
  integrity: "Is the session still bound to the machine it was issued to",
  impossible: "Travel, concurrent networks, clock agreement",
  automation: "Browser authenticity and interaction rhythm",
  patterns: "Time of day, operation mix, activity rate",
};

function Row({ label, score, detail, weight }) {
  if (score === null || score === undefined) {
    return (
      <div className="param-row">
        <div className="param-row-top">
          <span className="param-name">{label}</span>
          <span className="param-score param-unmeasured">not used</span>
        </div>
        <div className="param-bar-track" />
      </div>
    );
  }

  const color = trustColor(score);
  return (
    <div className="param-row">
      <div className="param-row-top">
        <span className="param-name">
          {label}
          {weight !== undefined && <span className="param-weight">×{weight.toFixed(2)}</span>}
        </span>
        <span className="param-score" style={{ color }}>{score.toFixed(0)}</span>
      </div>
      <div className="param-bar-track">
        <div
          className="param-bar-fill"
          style={{ width: `${Math.max(0, Math.min(100, score))}%`, background: color }}
        />
      </div>
      {detail && <div className="param-detail">{detail}</div>}
    </div>
  );
}

export default function ParameterBreakdown({ familyScores, contextChecks }) {
  if (!familyScores?.length && !contextChecks?.length) return null;

  return (
    <section className="breakdown-panel card">
      <h2>Signal families</h2>

      {familyScores?.length > 0 && (
        <div className="param-group">
          <h3>Weighted for this operation</h3>
          {familyScores.map((f) => (
            <Row
              key={f.name}
              label={FAMILY_LABELS[f.name] || f.name}
              score={f.score}
              weight={f.weight}
              detail={FAMILY_BLURB[f.name]}
            />
          ))}
        </div>
      )}

      {contextChecks?.length > 0 && (
        <div className="param-group">
          <h3>Individual checks</h3>
          {contextChecks.map((c) => (
            <Row key={c.name} label={c.name} score={c.score} detail={c.detail} />
          ))}
        </div>
      )}
    </section>
  );
}
