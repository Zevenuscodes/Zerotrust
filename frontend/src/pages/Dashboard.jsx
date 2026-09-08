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

const TELEMETRY_INTERVAL_MS = 12000;
const HISTORY_LENGTH = 20;

const DECISION_ICON = { allow: "✓", stepup: "!", terminate: "✕" };

export default function Dashboard() {
  const [trustScore, setTrustScore] = useState(100);
  const [decision, setDecision] = useState("allow");
  const [reasons, setReasons] = useState([]);
  const [history, setHistory] = useState([100]);
  const [mfaOpen, setMfaOpen] = useState(false);
  const [otp, setOtp] = useState("");
  const [mfaError, setMfaError] = useState("");
  const [terminated, setTerminated] = useState(false);
  const [scratch, setScratch] = useState("");

  const keystrokeTracker = useRef(createKeystrokeTracker());
  const mouseTracker = useRef(createMouseTracker());
  const scratchRef = useRef(null);
  const navigate = useNavigate();
  const { username, logout } = useAuth();

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

        const resp = await api.telemetry({ keystroke, mouse, context });
        setTrustScore(resp.trust_score);
        setDecision(resp.decision);
        setReasons(resp.reasons || []);
        setHistory((h) => [...h, resp.trust_score].slice(-HISTORY_LENGTH));

        if (resp.decision === "terminate") {
          clearInterval(interval);
          setTerminated(true);
        } else if (resp.decision === "stepup") {
          setMfaOpen(true);
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
        setTrustScore(resp.trust_score);
        setDecision("allow");
        setHistory((h) => [...h, resp.trust_score].slice(-HISTORY_LENGTH));
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

        <section className="trust-panel card">
          <TrustGauge score={trustScore} decision={decision} />
          <div className="trust-info">
            <h2>Live trust score</h2>
            <div className={`decision-badge ${decision}`}>
              <span>{DECISION_ICON[decision]}</span> {decision}
            </div>
            <div className="trust-history">
              <Sparkline values={history} />
              <span className="muted">last {history.length} heartbeats</span>
            </div>
            {reasons.length > 0 && (
              <ul className="reasons">
                {reasons.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            )}
          </div>
        </section>

        <section className="scratch-panel card">
          <h2>Keep typing/moving to feed your behavior profile</h2>
          <p className="muted">
            Telemetry is sent every {TELEMETRY_INTERVAL_MS / 1000}s. Try typing
            normally, then try typing very differently (or open this app on
            another device/browser) to see the trust score react.
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
                Your trust score dropped into the medium-risk range. Enter the
                one-time code to continue.
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
