// Per-digraph keystroke capture for a FIXED phrase.
//
// The free-text collector (keystroke.js) averages dwell/flight across
// whatever the user happened to type, so its numbers track the *text* at
// least as much as the *typist*: "hello" and a long paragraph produce very
// different averages for the same person. That content variance swamps the
// identity signal.
//
// Typing a known phrase removes it. Everyone types the same characters in
// the same order, so timings can be compared like-for-like: your flight
// time on "th" against your own past flight times on "th". That per-digraph
// comparison is where keystroke dynamics actually carries identity.

// onComplete fires from the final keyup, NOT from a value change. React's
// onChange runs on `input`, which happens during keydown -- at that moment
// the last character's dwell time has not been measured yet and the sample
// would be one character short.
export function createPhraseTracker(phrase, onComplete) {
  let downAt = null;        // timestamp of the key currently held
  let lastUpAt = null;      // timestamp of the previous key release
  let index = 0;            // position within the phrase
  const dwell = [];         // dwell[i]  = hold time of phrase character i
  const flight = [];        // flight[i] = gap between char i-1 release and char i press
  let aborted = false;      // typed something that doesn't match the phrase

  function isContentKey(e) {
    return e.key.length === 1; // ignore Shift/Backspace/arrows etc.
  }

  function onKeyDown(e) {
    if (!isContentKey(e)) return;
    const now = performance.now();
    if (e.key !== phrase[index]) {
      aborted = true; // a typo invalidates positional alignment
      return;
    }
    downAt = now;
    flight[index] = lastUpAt === null ? null : now - lastUpAt;
  }

  function onKeyUp(e) {
    if (!isContentKey(e) || aborted || downAt === null) return;
    const now = performance.now();
    dwell[index] = now - downAt;
    lastUpAt = now;
    downAt = null;
    index += 1;

    if (index === phrase.length && typeof onComplete === "function") {
      const captured = sample();
      reset();
      onComplete(captured);
    }
  }

  function attach(target) {
    target.addEventListener("keydown", onKeyDown);
    target.addEventListener("keyup", onKeyUp);
    return () => {
      target.removeEventListener("keydown", onKeyDown);
      target.removeEventListener("keyup", onKeyUp);
    };
  }

  function reset() {
    downAt = null;
    lastUpAt = null;
    index = 0;
    dwell.length = 0;
    flight.length = 0;
    aborted = false;
  }

  // Complete only when every character was typed in order with no typos --
  // a partial or corrected attempt can't be aligned position-by-position.
  function isComplete() {
    return !aborted && index === phrase.length;
  }

  function sample() {
    if (!isComplete()) return null;
    return {
      phrase,
      // index i of each array corresponds to phrase[i]
      dwell_ms: dwell.map((v) => Math.round(v * 10) / 10),
      flight_ms: flight.map((v) => (v === null ? null : Math.round(v * 10) / 10)),
    };
  }

  return { attach, reset, isComplete, sample };
}
