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
import { createPhraseTracker } from "../telemetry/phrase";

const CHALLENGE_PHRASE = "the quick zero trust fox verifies every packet";

const TELEMETRY_INTERVAL_MS = 12000;
const HISTORY_LENGTH = 20;
const OPERATIONS = ["view", "edit", "admin"];
const OPERATION_LABELS = { view: "View", edit: "Edit", admin: "Admin" };

// Demo control: the backend only honours these when DEMO_LOCATION_ENABLED is
// set (off by default). Lets the impossible-travel check be shown live --
// pick Mumbai, wait for a heartbeat, then switch to New York.
const LOCATIONS = [
  { value: "", label: "Real IP" },
  { value: "mumbai", label: "Mumbai" },
  { value: "london", label: "London" },
  { value: "new_york", label: "New York" },
];

const DECISION_ICON = { allow: "✓", stepup: "!", terminate: "✕" };

export default function Dashboard() {
  const [operation, setOperation] = useState("view");
  const [location, setLocation] = useState("");
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
  const [challengeTyped, setChallengeTyped] = useState("");
  const [phraseScore, setPhraseScore] = useState(null);
  const [useOtpFallback, setUseOtpFallback] = useState(false);
  const [terminated, setTerminated] = useState(false);
  const [scratch, setScratch] = useState("");

  const keystrokeTracker = useRef(createKeystrokeTracker());
  const mouseTracker = useRef(createMouseTracker());
  const scratchRef = useRef(null);
  const challengeRef = useRef(null);
  const submitPhraseRef = useRef(null);
  const challengeTracker = useRef(
    createPhraseTracker(CHALLENGE_PHRASE, (sample) => submitPhraseRef.current?.(sample))
  );
  const operationRef = useRef(operation);
  operationRef.current = operation;
  const locationRef = useRef(location);
  locationRef.current = location;
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

        const resp = await api.telemetry({
          keystroke,
          mouse,
          context,
          operation: activeOperation,
          simulated_location: locationRef.current || null,
        });
        setDecision(resp.decision);
        setTrustVector(resp.trust_vector || []);

        // An idle heartbeat (no typing/mouse movement since the last one)
        // isn't scored at all -- keep showing the last real evaluation's
        // breakdown instead of blanking it out every 12s while you're just
        // reading the screen.
        if (!resp.idle) {
          setReasons(resp.reasons || []);
          setFeatureScores(resp.feature_scores || []);
          setContextChecks(resp.context_checks || []);
          setBootstrapped(resp.bootstrapped);
          setHistory((h) => ({
            ...h,
            [resp.operation]: [...(h[resp.operation] || []), resp.trust_score].slice(-HISTORY_LENGTH),
          }));
        }

        if (resp.decision === "terminate") {
          clearInterval(interval);
          setTerminated(true);
        } else if (resp.mfa_pending) {
          // Keyed off the session's pending flag, not this beat's decision:
          // a challenge raised on one operation stays pending while the user
          // works on another, and would otherwise be invisible (and
          // impossible to clear) after switching tabs.
          setMfaOpen(true);
          setMfaOperation(resp.mfa_pending_operation || resp.operation);
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

  // Step-up by re-typing the enrolled phrase: scored against the user's own
  // per-character rhythm, so it tests who is at the keyboard rather than
  // just whether they know a code. Driven from the tracker's completion
  // callback (final keyup), not onChange -- see phrase.js.
  async function submitPhraseAttempt(sample) {
    setChallengeTyped("");
    if (!sample) {
      setMfaError("Type it straight through, without corrections.");
      return;
    }
    setMfaError("");
    try {
      const resp = await api.verifyPhrase(sample);
      if (resp.verified) {
        setMfaOpen(false);
        setDecision("allow");
        setPhraseScore(null);
        setTrustVector((v) =>
          v.map((entry) =>
            entry.operation === resp.operation
              ? { ...entry, trust_score: resp.trust_score, decision: "allow" }
              : entry
          )
        );
      } else {
        setPhraseScore(resp.phrase_score);
        setMfaError(
          `Typing rhythm didn't match (${resp.phrase_score.toFixed(0)} vs ${resp.threshold} needed).`
        );
      }
    } catch (err) {
      setMfaError(err.message || "Verification failed");
    }
  }

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

  // Kept in a ref so the tracker's completion callback, created once, always
  // calls the current closure rather than a stale one.
  submitPhraseRef.current = submitPhraseAttempt;

  // The challenge input only exists while the modal is open, so the tracker
  // has to be attached when it mounts rather than once on page load.
  useEffect(() => {
    if (!mfaOpen || useOtpFallback || !challengeRef.current) return undefined;
    challengeTracker.current.reset();
    return challengeTracker.current.attach(challengeRef.current);
  }, [mfaOpen, useOtpFallback]);

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
          <p>Trust score fell below the safe threshold, so this session was ended.</p>
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

          <span className="muted loc-label">Location:</span>
          <select
            className="loc-select"
            value={location}
            onChange={(e) => setLocation(e.target.value)}
          >
            {LOCATIONS.map((l) => (
              <option key={l.value} value={l.value}>{l.label}</option>
            ))}
          </select>
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
                Using overall baseline — not enough "{operation}" history yet.
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
          <h2>Type here to feed your behavior profile</h2>
          <p className="muted">Sampled every {TELEMETRY_INTERVAL_MS / 1000}s.</p>
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
              <h2>Verify to continue</h2>
              <p className="muted">
                Trust for "{OPERATION_LABELS[mfaOperation] || mfaOperation}" dropped into the
                medium-risk range.
              </p>

              {!useOtpFallback ? (
                <>
                  <p className="muted">Re-type your enrolled phrase:</p>
                  <code className="passphrase">{CHALLENGE_PHRASE}</code>
                  <input
                    ref={challengeRef}
                    value={challengeTyped}
                    onChange={(e) => setChallengeTyped(e.target.value)}
                    placeholder="Type the phrase above"
                    autoFocus
                  />
                  {phraseScore !== null && (
                    <p className="muted">Match score: {phraseScore.toFixed(0)}</p>
                  )}
                  {mfaError && <p className="error">{mfaError}</p>}
                  <p className="auth-footer">
                    <a onClick={() => { setUseOtpFallback(true); setMfaError(""); }}>Use a code instead</a>
                  </p>
                </>
              ) : (
                <form onSubmit={handleMfaSubmit}>
                  <p className="muted">Demo OTP: 123456</p>
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
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
