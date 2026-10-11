// Captures keystroke dynamics (dwell time = keydown->keyup, flight time =
// keyup->next keydown) from whatever element it's attached to, and reduces
// the rolling buffer to a small feature vector the backend risk engine scores.

// A gap this long between keys is the user stopping to think, read, or walk
// away -- not part of their typing rhythm. Including pauses made flight time
// wildly noisy (real sessions produced means from 170ms to 866ms), which
// inflated the baseline's spread so far that no typing speed looked unusual
// any more. Same idea for a key held down far longer than any normal press.
const MAX_FLIGHT_MS = 750;
const MAX_DWELL_MS = 400;

export function createKeystrokeTracker() {
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
      const dwell = upTime - downTime;
      if (dwell <= MAX_DWELL_MS) dwellTimes.push(dwell);
      downTimestamps.delete(e.key);
    }
    if (lastUpTime !== null) {
      const flight = upTime - lastUpTime;
      if (flight <= MAX_FLIGHT_MS) flightTimes.push(flight);
    }
    lastUpTime = upTime;
  }

  function attach(target) {
    target.addEventListener("keydown", onKeyDown);
    target.addEventListener("keyup", onKeyUp);
    return () => {
      target.removeEventListener("keydown", onKeyDown);
      target.removeEventListener("keyup", onKeyUp);
    };
  }

  function mean(arr) {
    if (!arr.length) return 0;
    return arr.reduce((a, b) => a + b, 0) / arr.length;
  }

  function std(arr, avg) {
    if (arr.length < 2) return 0;
    const variance = arr.reduce((sum, v) => sum + (v - avg) ** 2, 0) / arr.length;
    return Math.sqrt(variance);
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
