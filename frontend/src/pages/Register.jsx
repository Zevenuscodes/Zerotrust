import { useEffect, useRef, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../context/AuthContext";
import { createKeystrokeTracker } from "../telemetry/keystroke";
import { createMouseTracker } from "../telemetry/mouse";
import { getContextInfo } from "../telemetry/fingerprint";
import Brand from "../components/Brand";

const BASELINE_PASSPHRASE = "the quick zero trust fox verifies every packet";

export default function Register() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [typedPassphrase, setTypedPassphrase] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const passphraseRef = useRef(null);
  const keystrokeTracker = useRef(createKeystrokeTracker());
  const mouseTracker = useRef(createMouseTracker());
  const navigate = useNavigate();
  const { login } = useAuth();

  useEffect(() => {
    const detachMouse = mouseTracker.current.attach(document);
    let detachKeys = () => {};
    if (passphraseRef.current) {
      detachKeys = keystrokeTracker.current.attach(passphraseRef.current);
    }
    return () => {
      detachMouse();
      detachKeys();
    };
  }, []);

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");

    if (typedPassphrase.trim() !== BASELINE_PASSPHRASE) {
      setError("Please type the baseline passphrase exactly as shown.");
      return;
    }

    setSubmitting(true);
    try {
      const keystroke = keystrokeTracker.current.snapshot();
      const mouse = mouseTracker.current.snapshot();
      const context = getContextInfo();

      const resp = await api.register({
        username,
        password,
        keystroke,
        mouse,
        context,
      });
      login(resp.access_token, username);
      navigate("/dashboard");
    } catch (err) {
      setError(err.message || "Registration failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="page-shell">
      <div className="auth-page card">
        <Brand subtitle="Continuous authentication" />
        <h2>Register</h2>
        <p className="muted">
          This baseline sample (typing rhythm + mouse movement) trains your
          personal behavior profile for continuous authentication.
        </p>
        <form onSubmit={handleSubmit}>
          <label>
            Username
            <input value={username} onChange={(e) => setUsername(e.target.value)} required autoFocus />
          </label>
          <label>
            Password
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </label>
          <label>
            Type this passphrase exactly:
            <code className="passphrase">{BASELINE_PASSPHRASE}</code>
            <input
              ref={passphraseRef}
              value={typedPassphrase}
              onChange={(e) => setTypedPassphrase(e.target.value)}
              required
            />
          </label>
          {error && <p className="error">{error}</p>}
          <button type="submit" disabled={submitting}>
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
