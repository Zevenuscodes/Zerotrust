// Regression tests for the phrase tracker's reconciliation.
//
// The bug these guard against: an earlier version latched a single
// "aborted" flag on the first wrong keypress and never cleared it, so one
// typo silently killed enrollment for the rest of the page -- the progress
// never advanced and nothing explained why.
//
//   node frontend/src/telemetry/phrase.test.mjs

import { createPhraseTracker } from "./phrase.js";

const PHRASE = "the quick zero trust fox verifies every packet";
let passed = 0;
const failed = [];

function check(name, cond, detail = "") {
  if (cond) {
    passed++;
    console.log(`  PASS  ${name}`);
  } else {
    failed.push(name);
    console.log(`  FAIL  ${name}  ${detail}`);
  }
}

// Drives the tracker the way a browser does: keydown, keyup, then the
// change event React would fire.
function type(tracker, text, { from = "" } = {}) {
  let value = from;
  for (const ch of text) {
    tracker._keydown({ key: ch });
    tracker._keyup({ key: ch });
    value += ch;
    tracker.sync(value);
  }
  return value;
}

function makeTracker(onComplete) {
  const t = createPhraseTracker(PHRASE, onComplete);
  // attach() wires real DOM listeners; expose them directly for this test
  const handlers = {};
  t.attach({
    addEventListener: (ev, fn) => { handlers[ev] = fn; },
    removeEventListener: () => {},
  });
  t._keydown = handlers.keydown;
  t._keyup = handlers.keyup;
  return t;
}

console.log("\nphrase tracker reconciliation\n");

// --- a clean pass completes -------------------------------------------
let completed = [];
let t = makeTracker((s) => completed.push(s));
type(t, PHRASE);
check("a clean pass produces a sample", completed.length === 1);
check("the sample covers every character",
  completed[0]?.dwell_ms.length === PHRASE.length,
  `${completed[0]?.dwell_ms.length} of ${PHRASE.length}`);
check("first flight time is null (no preceding key)", completed[0]?.flight_ms[0] === null);

// --- a typo does not permanently kill capture --------------------------
completed = [];
t = makeTracker((s) => completed.push(s));
let v = type(t, "the qu");
t._keydown({ key: "z" });           // wrong character
t._keyup({ key: "z" });
v += "z";
check("a wrong character is reported as diverged", t.sync(v) === "diverged");
v = v.slice(0, -1);                  // user backspaces
check("backspacing back to a valid prefix recovers", t.sync(v) === "ok");
type(t, PHRASE.slice(6), { from: v });
check("the corrected pass still completes", completed.length === 1,
  "one typo must not kill the attempt");

// --- a later clean pass works after an earlier bad one ------------------
completed = [];
t = makeTracker((s) => completed.push(s));
t._keydown({ key: "z" });
t._keyup({ key: "z" });
t.sync("z");
t.sync("");                          // user clears the field
type(t, PHRASE);
check("a clean pass after a cleared bad one completes", completed.length === 1);

// --- backspacing discards the deleted characters' timings ---------------
t = makeTracker(() => {});
v = type(t, "the");
check("three characters captured", t.captured() === 3, `${t.captured()}`);
t.sync("th");
check("deleting one character drops its timing", t.captured() === 2, `${t.captured()}`);
t.sync("");
check("clearing the field resets capture", t.captured() === 0, `${t.captured()}`);

// --- an incomplete attempt yields nothing -------------------------------
t = makeTracker(() => {});
type(t, "the quick");
check("an incomplete attempt produces no sample", t.sample() === null);

console.log(`\n${"=".repeat(46)}`);
console.log(`${passed}/${passed + failed.length} checks passed`);
if (failed.length) {
  console.log("\nFAILED:");
  failed.forEach((f) => console.log(`  - ${f}`));
  process.exit(1);
}
console.log("all green");
