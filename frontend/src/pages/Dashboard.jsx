import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../context/AuthContext";
import { createKeystrokeTracker } from "../telemetry/keystroke";
import { createMouseTracker } from "../telemetry/mouse";
import { getContextInfo } from "../telemetry/fingerprint";
import TrustGauge from "../components/TrustGauge";
import Sparkline from "../components/Sparkline";
import Brand from "../components/Brand";
import ParameterBreakdown from "../components/ParameterBreakdown";
import TrustVectorPanel from "../components/TrustVectorPanel";

const TELEMETRY_INTERVAL_MS = 12000;
const HISTORY_LENGTH = 20;
const OPERATIONS = ["view", "edit", "admin"];
const OPERATION_LABELS = { view: "View", edit: "Edit", admin: "Admin" };

const DECISION_ICON = { allow: "✓", stepup: "!", terminate: "✕" };

export default function Dashboard() {
  const [operation, setOperation] = useState("view");
  const [trustVector, setTrustVector] = useState([]);
  const [decision, setDecision] = useState("allow");
  const [reasons, setReasons] = useState([]);
  const [history, setHistory] = useState({ view: [100], edit: [100], admin: [100] });
  const [featureScores, setFeatureScores] = useState([]);
  const [contextChecks, setContextChecks] = useState([]);
  const [bootstrapped, setBootstrapped] = useState(false);
  const [mfaOpen, setMfaOpen] = useState(false);
  const [mfaOperation, setMfaOperation] = useState(null);
  const [otp, setOtp] = useState("");
  const [mfaError, setMfaError] = useState("");
  const [terminated, setTerminated] = useState(false);
  const [scratch, setScratch] = useState("");

  const keystrokeTracker = useRef(createKeystrokeTracker());
  const mouseTracker = useRef(createMouseTracker());
  const scratchRef = useRef(null);
  const operationRef = useRef(operation);
  operationRef.current = operation;
  const navigate = useNavigate();
  const { username, logout } = useAuth();

  useEffect(() => {
    api.status().then((resp) => {
      if (resp.trust_vector?.length) setTrustVector(resp.trust_vector);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    const detachMouse = mouseTracker.current.attach(document);
    let detachKeys = () => {};
    if (scratchRef.current) {
      detachKeys = keystrokeTracker.current.attach(scratchRef.current);
    }

    const interval = setInterval(sendTelemetry, TELEMETRY_INTERVAL_MS);

    async function sendTelemetry() {
      try {
        const keystroke = keystrokeTracker.current.snapshot();
        const mouse = mouseTracker.current.snapshot();
        const context = getContextInfo();
        const activeOperation = operationRef.current;

        const resp = await api.telemetry({ keystroke, mouse, context, operation: activeOperation });
        setDecision(resp.decision);
        setReasons(resp.reasons || []);
        setFeatureScores(resp.feature_scores || []);
        setContextChecks(resp.context_checks || []);
        setBootstrapped(resp.bootstrapped);
        setTrustVector(resp.trust_vector || []);
        setHistory((h) => ({
          ...h,
          [resp.operation]: [...(h[resp.operation] || []), resp.trust_score].slice(-HISTORY_LENGTH),
        }));

        if (resp.decision === "terminate") {
          clearInterval(interval);
          setTerminated(true);
        } else if (resp.decision === "stepup") {
          setMfaOpen(true);
          setMfaOperation(resp.operation);
        }
      } catch (err) {
        if (err.status === 403) {
          clearInterval(interval);
          setTerminated(true);
        }
      }
    }

    return () => {
      detachMouse();
      detachKeys();
      clearInterval(interval);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleMfaSubmit(e) {
    e.preventDefault();
    setMfaError("");
    try {
      const resp = await api.verifyMfa(otp);
      if (resp.verified) {
        setMfaOpen(false);
        setOtp("");
        setDecision("allow");
        setTrustVector((v) => v.map((entry) => (entry.operation === resp.operation ? { ...entry, trust_score: resp.trust_score, decision: "allow" } : entry)));
        setHistory((h) => ({
          ...h,
          [resp.operation]: [...(h[resp.operation] || []), resp.trust_score].slice(-HISTORY_LENGTH),
        }));
      } else {
        setMfaError("Incorrect code. Try again.");
      }
    } catch (err) {
      setMfaError(err.message || "Verification failed");
    }
  }

  async function handleLogout() {
    try {
      await api.logout();
    } catch {
      // ignore -- logging out client-side regardless
    }
    logout();
    navigate("/login");
  }

  function handleSelectOperation(op) {
    setOperation(op);
    setFeatureScores([]);
    setContextChecks([]);
    setReasons([]);
  }

  if (terminated) {
    return (
      <div className="page-shell">
        <div className="terminated-page card">
          <div className="terminated-icon">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
              <path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
            </svg>
          </div>
          <h1>Session terminated</h1>
          <p>
            The risk engine detected a trust score below the safe threshold and
            ended this session. This is the Zero Trust policy in action: never
            trust, always verify — even mid-session.
          </p>
          <button onClick={() => { logout(); navigate("/login"); }}>
            Back to login
          </button>
        </div>
      </div>
    );
  }

  const activeEntry = trustVector.find((v) => v.operation === operation);
  const activeScore = activeEntry ? activeEntry.trust_score : 100;

  return (
    <div className="page-shell">
      <div className="dashboard">
        <header>
          <Brand />
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span className="who">Signed in as <strong>{username}</strong></span>
            <button className="ghost" onClick={handleLogout}>Log out</button>
          </div>
        </header>

        <section className="op-select">
          <span className="muted">Simulating operation:</span>
          <div className="op-tabs">
            {OPERATIONS.map((op) => (
              <button
                key={op}
                className={`op-tab ${operation === op ? "active" : ""}`}
                onClick={() => handleSelectOperation(op)}
                type="button"
              >
                {OPERATION_LABELS[op]}
              </button>
            ))}
          </div>
        </section>

        <section className="trust-panel card">
          <TrustGauge score={activeScore} decision={decision} />
          <div className="trust-info">
            <h2>Trust for "{OPERATION_LABELS[operation]}"</h2>
            <div className={`decision-badge ${decision}`}>
              <span>{DECISION_ICON[decision]}</span> {decision}
            </div>
            <div className="trust-history">
              <Sparkline values={history[operation] || [100]} />
              <span className="muted">last {(history[operation] || []).length} heartbeats for this operation</span>
            </div>
            {bootstrapped && (
              <p className="muted" style={{ marginBottom: 6 }}>
                Not enough "{operation}"-specific history yet — bootstrapping from your overall behavior.
              </p>
            )}
            {reasons.length > 0 && (
              <ul className="reasons">
                {reasons.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            )}
          </div>
        </section>

        <TrustVectorPanel vector={trustVector} activeOperation={operation} onSelect={handleSelectOperation} />

        <ParameterBreakdown featureScores={featureScores} contextChecks={contextChecks} />

        <section className="scratch-panel card">
          <h2>Keep typing/moving to feed your behavior profile</h2>
          <p className="muted">
            Telemetry is sent every {TELEMETRY_INTERVAL_MS / 1000}s, tagged with
            whichever operation is selected above. Each operation learns its own
            baseline — try typing normally on "View", then switch to "Admin" and
            type very differently to see only that component react.
          </p>
          <textarea
            ref={scratchRef}
            value={scratch}
            onChange={(e) => setScratch(e.target.value)}
            rows={6}
            placeholder="Type here..."
          />
        </section>

        {mfaOpen && (
          <div className="modal-backdrop">
            <div className="modal card">
              <h2>Step-up verification required</h2>
              <p className="muted">
                Trust for "{OPERATION_LABELS[mfaOperation] || mfaOperation}" dropped into
                the medium-risk range. Enter the one-time code to re-earn trust for
                this operation. (Other operations are unaffected.)
              </p>
              <p className="muted">(Demo OTP: 123456)</p>
              <form onSubmit={handleMfaSubmit}>
                <input
                  value={otp}
                  onChange={(e) => setOtp(e.target.value)}
                  placeholder="6-digit code"
                  maxLength={6}
                  autoFocus
                />
                {mfaError && <p className="error">{mfaError}</p>}
                <button type="submit">Verify</button>
              </form>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
