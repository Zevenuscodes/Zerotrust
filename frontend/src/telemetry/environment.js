// Session invariants: properties of the machine and browser that CANNOT
// legitimately change part-way through a single session.
//
// This replaces keystroke/mouse dynamics as the primary signal. Those were
// statistical -- high variance within one person, modest separation between
// people, and useless until dozens of samples existed. These are closer to
// invariants: a screen does not change resolution mid-session, a CPU does
// not change core count, and a canvas does not render differently on the
// same machine. When one of them changes while a session token stays the
// same, the most likely explanation is that the token is being presented
// from somewhere it was not issued.

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
    return hash(canvas.toDataURL());
  } catch {
    return "no-canvas";
  }
}

function webglSignature() {
  try {
    const gl = document.createElement("canvas").getContext("webgl");
    if (!gl) return "no-webgl";
    const dbg = gl.getExtension("WEBGL_debug_renderer_info");
    if (!dbg) return "no-debug-info";
    return hash(
      `${gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL)}|${gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL)}`
    );
  } catch {
    return "webgl-error";
  }
}

function hash(str) {
  let h = 5381;
  for (let i = 0; i < str.length; i++) h = (h * 33) ^ str.charCodeAt(i);
  return (h >>> 0).toString(16);
}

export function getEnvironment() {
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  return {
    device_fingerprint: hash(
      [navigator.userAgent, navigator.platform, screen.width, screen.height, tz, canvasSignature()].join("||")
    ),
    canvas_hash: canvasSignature(),
    webgl_hash: webglSignature(),
    user_agent: navigator.userAgent,
    platform: navigator.platform || "",
    screen_width: screen.width,
    screen_height: screen.height,
    color_depth: screen.colorDepth,
    hardware_concurrency: navigator.hardwareConcurrency || 0,
    device_memory: navigator.deviceMemory || 0,
    timezone: tz,
    // Offset is checked against the IP's location: a mismatch between where
    // the clock says you are and where the network says you are is a
    // standard VPN/proxy indicator.
    timezone_offset_min: -new Date().getTimezoneOffset(),
    languages: (navigator.languages || [navigator.language]).join(","),
    // Client wall clock, compared with server time to detect a tampered or
    // replayed client.
    client_time_ms: Date.now(),
  };
}
