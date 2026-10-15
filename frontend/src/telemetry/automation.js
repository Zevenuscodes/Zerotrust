// Automation indicators: is there a human driving this session, or a script?
//
// This targets the threat that actually matters once a session token is
// stolen -- the token being replayed by tooling. Unlike keystroke dynamics
// it doesn't try to identify WHICH person is present, only whether the
// interaction looks human at all, which is a far easier question with much
// sharper answers.

export function createAutomationTracker() {
  const actionTimes = [];     // timestamps of discrete user actions
  let pageReadyAt = performance.now();
  let firstActionAt = null;
  let clicksWithoutPrecursor = 0;
  let pastesIntoSensitive = 0;
  let sawPointerMovement = false;
  let sawScroll = false;

  function note(ts) {
    if (firstActionAt === null) firstActionAt = ts;
    actionTimes.push(ts);
    if (actionTimes.length > 200) actionTimes.shift();
  }

  function onPointerMove() { sawPointerMovement = true; }
  function onScroll() { sawScroll = true; }
  function onKeyDown() { note(performance.now()); }

  function onClick() {
    const ts = performance.now();
    // A real click is preceded by the pointer moving or the page scrolling.
    // A dispatched/synthetic click typically arrives with neither.
    if (!sawPointerMovement && !sawScroll) clicksWithoutPrecursor += 1;
    note(ts);
  }

  function onPaste(e) {
    const t = e.target;
    const sensitive = t && (t.type === "password" || t.dataset?.sensitive === "true");
    if (sensitive) pastesIntoSensitive += 1;
    note(performance.now());
  }

  function attach(target) {
    target.addEventListener("pointermove", onPointerMove, { passive: true });
    target.addEventListener("scroll", onScroll, { passive: true, capture: true });
    target.addEventListener("keydown", onKeyDown, true);
    target.addEventListener("click", onClick, true);
    target.addEventListener("paste", onPaste, true);
    return () => {
      target.removeEventListener("pointermove", onPointerMove);
      target.removeEventListener("scroll", onScroll, true);
      target.removeEventListener("keydown", onKeyDown, true);
      target.removeEventListener("click", onClick, true);
      target.removeEventListener("paste", onPaste, true);
    };
  }

  function headlessHints() {
    const hints = [];
    if (navigator.webdriver) hints.push("webdriver");
    if ((navigator.plugins?.length || 0) === 0) hints.push("no_plugins");
    if (!navigator.languages || navigator.languages.length === 0) hints.push("no_languages");
    if (/HeadlessChrome|PhantomJS|Electron/i.test(navigator.userAgent)) hints.push("headless_ua");
    // A real browser exposes window.chrome on Chromium; its absence there is
    // a common automation tell.
    if (/Chrome/.test(navigator.userAgent) && !window.chrome) hints.push("no_chrome_object");
    if (screen.width === 0 || screen.height === 0) hints.push("zero_screen");
    return hints;
  }

  function snapshot(reset = true) {
    // Humans produce irregular gaps between actions; scripts tend to fire on
    // a timer, so the spread of their intervals is unnaturally small
    // relative to the mean. That ratio travels to the backend rather than
    // raw timings, so no keystroke content or rhythm is reconstructable.
    const gaps = [];
    for (let i = 1; i < actionTimes.length; i++) gaps.push(actionTimes[i] - actionTimes[i - 1]);
    const mean = gaps.length ? gaps.reduce((a, b) => a + b, 0) / gaps.length : 0;
    const variance = gaps.length > 1
      ? gaps.reduce((s, g) => s + (g - mean) ** 2, 0) / gaps.length
      : 0;
    const cv = mean > 0 ? Math.sqrt(variance) / mean : 0;

    const result = {
      action_count: actionTimes.length,
      interval_cv: Number(cv.toFixed(4)),
      mean_interval_ms: Math.round(mean),
      time_to_first_action_ms:
        firstActionAt === null ? null : Math.round(firstActionAt - pageReadyAt),
      clicks_without_precursor: clicksWithoutPrecursor,
      pastes_into_sensitive: pastesIntoSensitive,
      saw_pointer_movement: sawPointerMovement,
      headless_hints: headlessHints(),
    };

    if (reset) {
      actionTimes.length = 0;
      clicksWithoutPrecursor = 0;
      pastesIntoSensitive = 0;
      pageReadyAt = performance.now();
      firstActionAt = null;
    }
    return result;
  }

  return { attach, snapshot };
}
