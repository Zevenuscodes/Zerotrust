const DECISION_LABEL = {
  allow: "Trusted",
  stepup: "Verify needed",
  terminate: "Terminated",
};

// Fallback for contexts with no decision to key off (e.g. the sparkline
// trend line, which only has raw historical scores). Wherever a decision
// IS available, use decisionColor instead -- per-operation thresholds mean
// a given score number no longer maps to the same color for every operation.
export function trustColor(score) {
  if (score >= 70) return "var(--success)";
  if (score >= 40) return "var(--warning)";
  return "var(--danger)";
}

export function decisionColor(decision) {
  if (decision === "allow") return "var(--success)";
  if (decision === "stepup") return "var(--warning)";
  return "var(--danger)";
}

export default function TrustGauge({ score, decision, size = 172 }) {
  const strokeWidth = size * 0.09;
  const r = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * r;
  const clamped = Math.max(0, Math.min(100, score));
  const offset = circumference * (1 - clamped / 100);
  const color = decisionColor(decision);

  return (
    <div className="trust-gauge" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="var(--surface-2)"
          strokeWidth={strokeWidth}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{ transition: "stroke-dashoffset 0.5s ease, stroke 0.4s ease" }}
        />
      </svg>
      <div className="trust-gauge-center">
        <span className="trust-gauge-score" style={{ color }}>
          {clamped.toFixed(0)}
        </span>
        <span className="trust-gauge-label">{DECISION_LABEL[decision] || decision}</span>
      </div>
    </div>
  );
}
