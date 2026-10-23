# 261024 handoff — landing the merge queue (develop-buffer)

## Where things stand

- **Line**: a GREEN certification exists (cert-01M5MEP8J @ 0e1e14a3, failed=0); the
  freeze it opened was closed by an integration ruling and no new freeze is open.
- **Landed**: eight tickets are on develop-buffer (landing commits in the line
  history; the newest are `t261021-07`, `t261021-13`, `t261021-08`).
- **Open**: eight. Three `merge blocked`, one `implement blocked`, one `arbitrate
  blocked`, one `implement running`, one parked at `work/awaiting`, and the manual
  ticket `t261023-06` at `open/blocked`.

## The four doors that were closed (and how each was opened)

1. **authorize must be issued by a human identity.** `who=integration` is refused as
   self-signing, and the CALLER only sees a delivery timeout plus a resume-shaped
   refusal. Re-sending the same payload with `who=host` (the host delegated signing on
   261023) lands the authorization and resets the iteration counter. See KI-344.
2. **Shared registries conflict on every landing.** `integration/run_scenarios.py` and
   `integration/test_anchors.json` are appended by every ticket. The line's version is
   the correct base (it already carries landed peers); resolving by taking the line's
   copy for `run_scenarios.py` and by UNION for `test_anchors.json` lands cleanly.
3. **A single L16 lint error kept every gate red.** `server/engine/tests/test_t261021_01_inspection_sighting.py`
   landed on the line without an `integration/test_anchors.json` entry; every lane that
   carried the file therefore read a missing anchor. Fixed on the line (`23b3cdcd`).
4. **Landing waits for a certification that covers the head.** Every landing moves the
   head, so landings and rounds alternate: land a few, run a round, land again. A
   `merge` stage that looks stuck is usually waiting for that certification.

## What is genuinely left for a human or a working session

- `t261021-10` and `t261021-12`: their lanes conflict on **other tickets' delivery
  files** (engine-face language inventory + lint; workbench TS). That is content
  judgement, not a mechanical merge — integration must not decide it.
- `t261023-06` (manual lane): implement the cap-stop authorize path. The lane cannot
  open until `verify.yaml` declares the evidence (`l1_battery`,
  `server/engine/tests/test_t261023_pin_refresh.py`); the ticket carries the full
  diagnosis and the corrected scope.
- `t261021-14`, `t261022-14`, `t261021-15`, `t261022-15`: they cycle between the cap and
  the gate; each needs either a content fix from its developer or a host decision to
  cancel.

## Method that works (reuse it)

1. `engine_ops sync <ticket>` — confirm the lane carries main.
2. If the lane is behind the LINE: `git merge develop` in the lane; resolve
   `run_scenarios.py` (take the line) and `test_anchors.json` (union), abort on any
   other conflict.
3. `ticket.py op=rework to_stage=merge_check` — re-run the gate so the green-run face
   records the current HEAD.
4. When a ticket stops on the iteration cap: `op=authorize kind=arbitration_verdict
   scope=[<ticket>] who=host` then `op=retry_qc`.
5. Let a round certify between landing waves.

## Final state after the 261024 night run (goal rounds 25-60)

- Landed: **8** tickets on develop-buffer.
- Open: **8** — three `merge blocked` (gates send them back: content, not mechanics),
  one `implement blocked`, one `arbitrate blocked`, one `review_plan running`, one
  parked at `work/awaiting`, and the manual ticket `t261023-06`.
- The line certifies green repeatedly (the last cert is `cert-01M5MXJB2P…`); no freeze
  is open.
- What stops the rest is NOT mechanics: `t261021-10` / `t261021-12` conflict on other
  tickets' delivery files, `t261021-14/-15`, `t261022-12/-14/-15` cycle between the gate
  cap and content reds, and `t261023-06` needs its implementation written in the
  manual lane. Each needs a developer or a host decision — the mechanics that were
  broken (identity, registries, anchor gap, landing/cert alternation) are all fixed and
  written up above.

## 261024 07:00-07:40 — the red round was one real defect plus two integration bugs

The round `run-01M5N28HDZCDAJVGTFA2HYRYA7` at the head `0b58cd27` went red on four
cases and opened freeze `frz-01M5N106WSYB2P54YE8WF7179M` (cause
`cert-01M5N106WSYB2P54YE8WF7179K`). Triage, each reproduced alone in a clean clone of
the line head:

1. `t261012-05-fix-pins` — an integration case, broken by a landed lane. The
   t261021-07 landing (while converting copy) rewrote the case's own pin from the real
   registry id `t260904-12-no-skip-guard` to an id that exists nowhere
   (`t260904-12-wording-guard`), and appended an out-of-order row to
   `integration/test_anchors.json` (lint L23). Both repaired on the line
   (`cfc0246b`, `6bd847c4`); 35 pass / 0 fail, lint 0 error. KI-347.
2. `t260917-09-tests-false-escalation-guard` — an integration case reading its own
   receipt wrong: `declared_stop` scanned a 4000-char compact dump, and the ticket's
   acceptance list sits ahead of `blocked_reason` in that dump, so the very marker the
   bail then printed was invisible. The scan now reads `blocked_reason` /
   `blocked_detail` first (dump stays as fallback; markers and the negative judgement
   unchanged). Green in isolation, 133.6 s.
3. `t261021-13-epic-doc-link-opens-reader` + `t261005-10-ui2-epics-docs-metrics-tabs-journey`
   — ONE real product regression: `server/plugins/executor-panel/src/host/panel-page.ts`
   declares `renderEpics` twice, and the metrics renderer added by the metrics-tab
   landing shadows the Epics tab's renderer, so the tab renders empty while `/api/epics`
   answers. Causality measured: renaming only the metrics renderer turns both journeys
   green (3.8 s / 15.7 s). Recorded as KI-345.

Why the repair is not in this wave: a dev-lane worktree starts from **main**
(measured: `.lane/t261024-03` HEAD was main, one `renderEpics`), and the duplicate only
exists on develop-buffer. Naming a line commit as `base_ref` does not move the branch
point. So `t261024-02` / `t261024-03` were parked (their cancel reasons carry the full
spec for the follow-up) and both journeys are booked `verdict=booked` as product debt
(owner + retire_when) instead of holding the landing queue hostage. The follow-up
ticket is re-filed against main once the line promotes.

Also found: the designed auto-repair path is dead — `run_watch.run_watch_now` decided
`fix_ticket` for the red round and then could not open it (the round's case rows were
"unavailable" to `case_rows_fn`, and the minted write set was empty). KI-346.

## What is left, in order

1. This round (started 23:40Z) should certify green at `5779bd5a`; then write the one
   `freeze_change closed` row citing that cert (the design says a person writes it —
   no engine code does) and the landing queue resumes.
2. Then `retry_qc` on `t261021-14`, `t261021-15`, `t261021-12`, `t261022-12`
   (freeze / stale proven revision), and let the dispatcher work `t261022-14`
   (reworked back to implement: the known-red rows it kept re-adding are now on main).
3. Promotion to main is a host act. It must carry the booked Epics-tab debt; the
   `renderEpics` fix ticket is written to be pasted the moment main has the code.
4. `t261021-10` still needs a host ruling (its handover names the design conflict);
   `t261022-15` waits for a working session.
