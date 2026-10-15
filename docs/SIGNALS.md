# Signal families

The engine scores four independent families and blends them with
per-operation weights. This replaced keystroke/mouse dynamics, which
measurement showed could not carry the signal: within one real session a
user's mean flight time ranged from 170ms to 866ms, because the features
tracked the *text being typed* at least as much as the person typing it. A
baseline that wide makes everything look normal, and no threshold fixes a
feature that carries no information.

| Family | Asks | Why it is stronger |
|---|---|---|
| **Session integrity** | Did the machine change under a live session? | CPU core count, GPU renderer, screen size and canvas output cannot change mid-session. A change is near-proof the token moved machines. No training data, near-zero false positives. |
| **Impossible conditions** | Is something physically impossible happening? | Same session from two networks at once, impossible travel, client clock far from the server's. Binary, so nothing to tune. |
| **Human vs automated** | Is a person driving this, or a script? | The realistic abuse of a stolen token is automation. "Is this human" is a far easier question than "which human is this", with much sharper answers. |
| **Access habits** | Is this when and what this account normally does? | The one statistical family, but on quantities stable week to week (working hours, operation mix) rather than minute to minute. |

## How they combine

```
weighted = sum over families of  weight(family, operation) * score(family)
gate     = min(integrity, impossible, automation)
evidence = min(weighted, gate) - navigation_penalty
```

The **gate** matters. A plain weighted mean lets a catastrophic failure in
one family be averaged away by healthy ones -- a session with a changed GPU
*and* a `navigator.webdriver` flag still cleared "view" because its travel
and habits looked normal. Trust cannot exceed the weakest decisive signal.
`patterns` is deliberately excluded from the gate: an odd working hour
should colour the score, never cap it.

## Per-operation weighting

This is where the operation-conditioned model now lives. Operations differ
in *what evidence they care about*, not merely where their thresholds sit:

| | integrity | impossible | automation | patterns |
|---|---|---|---|---|
| view | 0.35 | 0.25 | 0.20 | 0.20 |
| edit | 0.40 | 0.25 | 0.25 | 0.10 |
| admin | 0.45 | 0.25 | 0.25 | 0.05 |

Reading a page tolerates an odd hour. An admin action leans almost entirely
on whether the session is still bound to the machine it was issued to and
whether a human is driving it.

## Where keystroke timing still appears

Only in the **step-up challenge** (`phrase_auth.py`), where the user re-types
a known phrase. That is a fixed-text comparison -- same characters, same
order, compared position by position -- which is a different and far more
tractable problem than scoring free text. It is not used for continuous
monitoring.

## What is still not established

`test_phrase_separation.py` shows the phrase scorer separates *simulated*
typists. Nothing here has been validated against real impostors. Run
`eval_accuracy.py` with two real people before treating any of it as an
accuracy result.
