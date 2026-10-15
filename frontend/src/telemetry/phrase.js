// Per-digraph keystroke capture for a FIXED phrase.
//
// The free-text collectors averaged dwell/flight over whatever the user
// happened to type, so their numbers tracked the *text* at least as much as
// the *typist*. Typing a known phrase removes that: everyone types the same
// characters in the same order, so timings can be compared like-for-like --
// your flight time on "th" against your own past flight times on "th".
//
// Capture is reconciled against the input's actual value on every change,
// not driven by the key stream alone. An earlier version latched a single
// "aborted" flag on the first wrong keypress and never cleared it, so one
// typo silently killed capture for the rest of the page -- the progress
// never advanced and nothing explained why.

export function createPhraseTracker(phrase, onComplete) {
  let downAt = null;    // timestamp of the key currently held
  let lastUpAt = null;  // timestamp of the previous key release
  let index = 0;        // how many characters have been captured
  const dwell = [];     // dwell[i]  = hold time of phrase character i
  const flight = [];    // flight[i] = gap from char i-1's release to char i's press
  let diverged = false; // the field no longer matches the phrase at all

  function isContentKey(e) {
    return e.key.length === 1; // ignore Shift/Backspace/arrows etc.
  }

  function onKeyDown(e) {
    if (!isContentKey(e) || diverged) return;
    const now = performance.now();
    if (e.key !== phrase[index]) {
      // Wrong character: don't record it. sync() will see the value diverge
      // and the user can backspace to recover.
      return;
    }
    downAt = now;
    flight[index] = lastUpAt === null ? null : now - lastUpAt;
  }

  function onKeyUp(e) {
    if (!isContentKey(e) || diverged || downAt === null) return;
    const now = performance.now();
    dwell[index] = now - downAt;
    lastUpAt = now;
    downAt = null;
    index += 1;

    // Completion is signalled from the final keyup, NOT from a value change:
    // React's onChange runs on `input`, during keydown, at which point the
    // last character's dwell time has not been measured yet.
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
    diverged = false;
  }

  // Reconcile with what is actually in the field. The input's value is the
  // authority -- it accounts for backspaces, selections, paste and autofill,
  // none of which the key stream alone describes correctly.
  // Returns "ok" | "diverged" | "empty".
  function sync(value) {
    if (value === "") {
      reset();
      return "empty";
    }
    if (!phrase.startsWith(value)) {
      diverged = true;
      return "diverged";
    }
    diverged = false;
    if (value.length < index) {
      // characters were deleted -- drop their timings and carry on
      index = value.length;
      dwell.length = index;
      flight.length = index;
      lastUpAt = null; // the next flight time would span the correction
      downAt = null;
    }
    return "ok";
  }

  function sample() {
    if (diverged || index !== phrase.length) return null;
    return {
      phrase,
      // index i of each array corresponds to phrase[i]
      dwell_ms: dwell.map((v) => (v === null ? null : Math.round(v * 10) / 10)),
      flight_ms: flight.map((v) => (v === null ? null : Math.round(v * 10) / 10)),
    };
  }

  return { attach, reset, sync, sample, captured: () => index };
}
