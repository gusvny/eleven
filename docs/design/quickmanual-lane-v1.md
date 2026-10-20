# Quickmanual lane v1 — a recorded lane where a session works directly

Status: design (host-ruled 261019). Implementation is a separate ticket.

## Why

Small repairs happen many times a day. Today they take one of two bad shapes:

* a full dev-lane ticket (plan, review, developer agent, integration agent, acceptance walk-through)
  for a change of three lines — the ceremony costs more than the fix; or
* a direct commit on main by whoever noticed the problem, with **no ticket, no lane and no gate**
  (measured 261019: six such fixes in one day — the probe sentinel, the verdict caliber, a test
  fixture, the executor-panel envelope, the sandbox ledger read, a file-name sweep).

The second shape is what this lane removes. The host's requirement is exact: **it still opens a
ticket and creates a lane, but the work is done by one session working in that lane** — recorded,
gated, and landable, without pretending a second and third agent reviewed it.

## Stage chain

```
open → work → run_integration_tests → merge_check → merge
```

* **open** — the ticket face states what is being fixed and what acceptance looks like. No plan
  stage: a quick repair's plan is its ticket description.
* **work** — the lane is created and held; **a session works in it** (the host's own session, or a
  project session the host points at the ticket). The stage does not spawn an agent. It ends when
  the session signals done, and the ordinary settle/disposal path records the work: the same
  disposition rules, the same write-set gate, the same settle commit.
* **run_integration_tests** — the existing gate, unchanged: scoped to the changed files.
* **merge_check** — the existing gate, unchanged.
* **merge** — the existing landing path: `engine:land` onto the declared line, then the line's
  certification and the signed promotion. Never a direct squash into main.

No `create_plan`, `review_plan`, `design_integration_tests` or `acceptance_walkthrough`: those
stages exist to make a second and third role check the first. In a quick lane there is no second
role, so keeping them would be a role playing both sides — the failure mode this design avoids.

## What still has to hold (the guardrails)

1. **The write set still binds.** The path gate is unchanged: a quick lane may not write outside its
   declared paths, and `notes/` stays main-side.
2. **The line rules still bind.** Landing, freeze, certification and promotion are the existing
   ones. A frozen line refuses a quick lane exactly as it refuses any other ticket.
3. **Evidence is mandatory.** The ticket must carry a regression: an L1 battery, a scenario, or (for
   a document-only change) the check that was run. A quick fix without evidence is a defect of the
   delivery, not a shortcut: the record is what distinguishes this lane from a direct commit.
4. **No self-signed gate.** The session that did the work does not sign the merge. The executor
   signs per the own-project merge rule, or the host signs.

## Identity

The lane records **who worked**: the session id and its role on the ticket face, never a borrowed
role name. A reader of the record must be able to say "a session fixed this, the executor signed it,
the suite passed" without guessing.

## What this lane is not

* Not a bypass: it has the same gates minus the roles that only make sense with more than one actor.
* Not the default: a change that needs a plan, a design or a walk-through belongs in a dev-lane
  ticket, and converting upward is normal.
* Not a place for design documents: `docs/design` and `notes/` stay main-side.

## Open questions deliberately not decided here

A change-size or time ceiling, and an integration audit pass over quick-lane landings: the host
ruled both out for now (261019). They stay recorded as candidates, not as commitments.
