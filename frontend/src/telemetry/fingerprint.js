// Lightweight device fingerprint: hashes a handful of stable browser/device
// properties plus a canvas-rendering hash. No external library needed --
// good enough to distinguish "same browser/device" from "a different one",
// which is all the context risk check needs.

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

export function getDeviceFingerprint() {
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

export function getContextInfo() {
  return {
    device_fingerprint: getDeviceFingerprint(),
    screen_width: screen.width,
    screen_height: screen.height,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
  };
}
