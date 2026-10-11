import { useEffect, useRef, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../context/AuthContext";
import { createKeystrokeTracker } from "../telemetry/keystroke";
import { createMouseTracker } from "../telemetry/mouse";
import { createPhraseTracker } from "../telemetry/phrase";
import { getContextInfo } from "../telemetry/fingerprint";
import Brand from "../components/Brand";

const BASELINE_PASSPHRASE = "the quick zero trust fox verifies every packet";
const ENROLLMENTS_REQUIRED = 3;

export default function Register() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [typed, setTyped] = useState("");
  const [enrollments, setEnrollments] = useState([]);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const phraseRef = useRef(null);
  // Completion is signalled from the final keyup (see phrase.js) rather
  // than from onChange, which fires too early to have measured it.
  const phraseTracker = useRef(
    createPhraseTracker(BASELINE_PASSPHRASE, (sample) => {
      setTyped("");
      if (sample) {
        setEnrollments((prev) => [...prev, sample]);
        setError("");
      } else {
        setError("That pass had a correction in it — type it straight through.");
      }
    })
  );
  const keystrokeTracker = useRef(createKeystrokeTracker());
  const mouseTracker = useRef(createMouseTracker());
  const navigate = useNavigate();
  const { login } = useAuth();

  useEffect(() => {
    const detachMouse = mouseTracker.current.attach(document);
    let detachKeys = () => {};
    let detachPhrase = () => {};
    if (phraseRef.current) {
      detachKeys = keystrokeTracker.current.attach(phraseRef.current);
      detachPhrase = phraseTracker.current.attach(phraseRef.current);
    }
    return () => {
      detachMouse();
      detachKeys();
      detachPhrase();
    };
  }, []);

  function handlePhraseChange(e) {
    setTyped(e.target.value);
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");

    if (enrollments.length < ENROLLMENTS_REQUIRED) {
      setError(`Type the phrase ${ENROLLMENTS_REQUIRED - enrollments.length} more time(s).`);
      return;
    }

    setSubmitting(true);
    try {
      const resp = await api.register({
        username,
        password,
        keystroke: keystrokeTracker.current.snapshot(),
        mouse: mouseTracker.current.snapshot(),
        context: getContextInfo(),
        phrase_enrollments: enrollments,
      });
      login(resp.access_token, username);
      navigate("/dashboard");
    } catch (err) {
      setError(err.message || "Registration failed");
      setSubmitting(false);
    }
  }

  const done = enrollments.length;
  const complete = done >= ENROLLMENTS_REQUIRED;

  return (
    <div className="page-shell">
      <div className="auth-page card">
        <Brand subtitle="Continuous authentication" />
        <h2>Register</h2>
        <p className="muted">
          Type the phrase {ENROLLMENTS_REQUIRED} times to enroll your typing rhythm.
        </p>
        <form onSubmit={handleSubmit}>
          <label>
            Username
            <input value={username} onChange={(e) => setUsername(e.target.value)} required autoFocus />
          </label>
          <label>
            Password
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </label>
          <label>
            Passphrase
            <code className="passphrase">{BASELINE_PASSPHRASE}</code>
            <input
              ref={phraseRef}
              value={typed}
              onChange={handlePhraseChange}
              disabled={complete}
              placeholder={complete ? "Enrolled" : "Type the phrase above"}
            />
          </label>
          <div className="enroll-progress">
            {Array.from({ length: ENROLLMENTS_REQUIRED }, (_, i) => (
              <span key={i} className={`enroll-dot ${i < done ? "filled" : ""}`} />
            ))}
            <span className="muted">{done} / {ENROLLMENTS_REQUIRED} captured</span>
          </div>
          {error && <p className="error">{error}</p>}
          <button type="submit" disabled={submitting || !complete}>
            {submitting ? "Registering..." : "Register"}
          </button>
        </form>
        <p className="auth-footer">
          Already have an account? <Link to="/login">Log in</Link>
        </p>
      </div>
    </div>
  );
}
