import { useEffect, useRef, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../context/AuthContext";
import { createKeystrokeTracker } from "../telemetry/keystroke";
import { createMouseTracker } from "../telemetry/mouse";
import { getContextInfo } from "../telemetry/fingerprint";
import Brand from "../components/Brand";

export default function Login() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const passwordRef = useRef(null);
  const keystrokeTracker = useRef(createKeystrokeTracker());
  const mouseTracker = useRef(createMouseTracker());
  const navigate = useNavigate();
  const { login } = useAuth();

  useEffect(() => {
    const detachMouse = mouseTracker.current.attach(document);
    let detachKeys = () => {};
    if (passwordRef.current) {
      detachKeys = keystrokeTracker.current.attach(passwordRef.current);
    }
    return () => {
      detachMouse();
      detachKeys();
    };
  }, []);

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const keystroke = keystrokeTracker.current.snapshot();
      const mouse = mouseTracker.current.snapshot();
      const context = getContextInfo();

      const resp = await api.login({ username, password, keystroke, mouse, context });
      login(resp.access_token, username);
      navigate("/dashboard");
    } catch (err) {
      setError(err.message || "Login failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="page-shell">
      <div className="auth-page card">
        <Brand subtitle="Continuous authentication" />
        <h2>Log in</h2>
        <form onSubmit={handleSubmit}>
          <label>
            Username
            <input value={username} onChange={(e) => setUsername(e.target.value)} required autoFocus />
          </label>
          <label>
            Password
            <input
              ref={passwordRef}
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </label>
          {error && <p className="error">{error}</p>}
          <button type="submit" disabled={submitting}>
            {submitting ? "Logging in..." : "Log in"}
          </button>
        </form>
        <p className="auth-footer">
          Need an account? <Link to="/register">Register</Link>
        </p>
      </div>
    </div>
  );
}
