// Shared behavior-capture logic, ported from frontend/src/telemetry/*.js so the
// extension scores behavior with the exact same feature definitions the backend
// risk engine and the web app already agree on. Loaded as a plain content-script
// file (no ES modules), so it attaches everything to a single global namespace.
(function () {
  if (window.__ztTelemetryLib) return; // avoid re-injecting into the same page
  window.__ztTelemetryLib = true;

  function mean(arr) {
    if (!arr.length) return 0;
    return arr.reduce((a, b) => a + b, 0) / arr.length;
  }

  function std(arr, avg) {
    if (arr.length < 2) return 0;
    const variance = arr.reduce((sum, v) => sum + (v - avg) ** 2, 0) / arr.length;
    return Math.sqrt(variance);
  }

  function createKeystrokeTracker() {
    const dwellTimes = [];
    const flightTimes = [];
    const downTimestamps = new Map();
    let lastUpTime = null;

    function onKeyDown(e) {
      if (!downTimestamps.has(e.key)) {
        downTimestamps.set(e.key, performance.now());
      }
    }

    function onKeyUp(e) {
      const downTime = downTimestamps.get(e.key);
      const upTime = performance.now();
      if (downTime !== undefined) {
        dwellTimes.push(upTime - downTime);
        downTimestamps.delete(e.key);
      }
      if (lastUpTime !== null) {
        flightTimes.push(upTime - lastUpTime);
      }
      lastUpTime = upTime;
    }

    function attach(target) {
      target.addEventListener("keydown", onKeyDown, true);
      target.addEventListener("keyup", onKeyUp, true);
      return () => {
        target.removeEventListener("keydown", onKeyDown, true);
        target.removeEventListener("keyup", onKeyUp, true);
      };
    }

    function snapshot(reset = true) {
      const meanDwell = mean(dwellTimes);
      const meanFlight = mean(flightTimes);
      const result = {
        key_count: dwellTimes.length,
        mean_dwell_ms: meanDwell,
        std_dwell_ms: std(dwellTimes, meanDwell),
        mean_flight_ms: meanFlight,
        std_flight_ms: std(flightTimes, meanFlight),
      };
      if (reset) {
        dwellTimes.length = 0;
        flightTimes.length = 0;
      }
      return result;
    }

    function hasEnoughData() {
      return dwellTimes.length >= 5;
    }

    return { attach, snapshot, hasEnoughData };
  }

  function createMouseTracker() {
    let points = [];
    let lastAngle = null;

    function onMouseMove(e) {
      points.push({ x: e.clientX, y: e.clientY, t: performance.now() });
      if (points.length > 500) points.shift();
    }

    function attach(target) {
      target.addEventListener("mousemove", onMouseMove, true);
      return () => target.removeEventListener("mousemove", onMouseMove, true);
    }

    function snapshot(reset = true) {
      const velocities = [];
      const accelerations = [];
      let directionChanges = 0;
      lastAngle = null;
      let lastVelocity = null;

      for (let i = 1; i < points.length; i++) {
        const dx = points[i].x - points[i - 1].x;
        const dy = points[i].y - points[i - 1].y;
        const dt = Math.max(points[i].t - points[i - 1].t, 1);
        const distance = Math.sqrt(dx * dx + dy * dy);
        const velocity = distance / dt;
        velocities.push(velocity);

        if (lastVelocity !== null) {
          accelerations.push((velocity - lastVelocity) / dt);
        }
        lastVelocity = velocity;

        if (distance > 2) {
          const angle = Math.atan2(dy, dx);
          if (lastAngle !== null && Math.abs(angle - lastAngle) > Math.PI / 4) {
            directionChanges += 1;
          }
          lastAngle = angle;
        }
      }

      const meanVelocity = mean(velocities);
      const result = {
        point_count: points.length,
        mean_velocity: meanVelocity,
        std_velocity: std(velocities, meanVelocity),
        mean_acceleration: mean(accelerations),
        direction_changes: directionChanges,
      };

      if (reset) points = [];
      return result;
    }

    function hasEnoughData() {
      return points.length >= 20;
    }

    return { attach, snapshot, hasEnoughData };
  }

  function djb2(str) {
    let hash = 5381;
    for (let i = 0; i < str.length; i++) {
      hash = (hash * 33) ^ str.charCodeAt(i);
    }
    return (hash >>> 0).toString(16);
  }

  function canvasSignature() {
    try {
      const canvas = document.createElement("canvas");
      const ctx = canvas.getContext("2d");
      ctx.textBaseline = "top";
      ctx.font = "14px 'Arial'";
      ctx.fillStyle = "#f60";
      ctx.fillRect(0, 0, 100, 20);
      ctx.fillStyle = "#069";
      ctx.fillText("zero-trust-fp", 2, 2);
      return canvas.toDataURL();
    } catch {
      return "no-canvas";
    }
  }

  function getDeviceFingerprint() {
    const parts = [
      navigator.userAgent,
      navigator.platform,
      navigator.hardwareConcurrency || "unknown",
      navigator.language,
      `${screen.width}x${screen.height}x${screen.colorDepth}`,
      Intl.DateTimeFormat().resolvedOptions().timeZone,
      canvasSignature(),
    ];
    return djb2(parts.join("||"));
  }

  function getContextInfo() {
    return {
      device_fingerprint: getDeviceFingerprint(),
      screen_width: screen.width,
      screen_height: screen.height,
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    };
  }

  window.ZT = { createKeystrokeTracker, createMouseTracker, getContextInfo };
})();
