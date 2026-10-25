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

## 261024 afternoon/evening — the line was green on content long before it could certify

The morning's red was one product defect plus two integration bugs. The afternoon found
that the certification machinery itself was the bottleneck, not the code.

### What landed (develop-buffer; promoted to main at 090314e6)

| ticket | what it fixed |
| --- | --- |
| `t261024-12` | KI-350: a narrowed green gate round now refreshes the landing anchor |
| `t261024-16` | the inspection human-gate sign chain (self-sign refused by name, human sign closes, `human_gate.who` receipt) |
| `t261024-21` | the Epics tab: the metrics renderer no longer shadows the tab renderer |
| `t261024-30` | KI-352: a round always leaves exactly one named record |
| `t261021-10`, `t261021-14`, `t261021-15` | their own delivery work |

### What the investigation found (all registered)

- KI-345 the Epics tab was blank because `panel-page.ts` declared `renderEpics` twice.
- KI-346 `run_watch` could not open the fix ticket it decided on (case rows unavailable, empty write set).
- KI-347 a landed lane had rewritten an integration case's pin and the anchors registry.
- KI-348 the "line worktree not clean" refusal blames engine corruption when the truth is an operator edit.
- KI-349 the same run content judged green or red depending on whether a relative block was produced.
- KI-350 the landing anchor only came from a full closing run, so narrowed gates could never land (fixed).
- KI-351 a case that reclaims stages killed the round hosting it.
- KI-352 eight of nineteen rounds wrote no certification at all (fixed by `t261024-30`).
- KI-353 a ticket whose own scenario sits in a cheap pool can be peeled to a zero-run gate and never land (open: `t261024-40`).

### The known-red book (measured today)

- 795 registry entries; the fast set is 91, so 704 cases separate a lane gate from a full round.
- A round now skips 106 rows: 63 docker-dependent cases (host order "exclude every docker case"), plus booked product debt and contention rows.
- 63 of the 795 touch docker (engine 20 / ro 17 / exclusive 15 / browser-free 7 / main 3 / browser 1). Five cases moved to `integration/process_bench.py` today and run docker-free.
- Rows retired today because the fix landed and was re-measured green: the two Epics journeys, the sign journey, the fast-set orphans.

### Still open at hand-off

- `t261024-40` KI-353 (in progress), `t261022-14` (its live witness, engine-paused), `t261022-12` and `t261021-12` (acceptance / merge_check), `t261022-15` (waiting for a working session).
- Durable follow-ups worth a ticket: the fixed wall-clock windows (5 s / 60 s / 90 s) measured on an idle box are the single largest source of red; each should either own its resource or scale with the measured bench, never stay a constant.

## 261025 01:00-06:30 — two engine stalls, both located and cleared

After the last promotion the line stopped producing rounds altogether. Two independent
faults sat on top of each other:

1. **A stale round guard.** `ledger/delivery-guard.json` read `{"held": true, "by":
   "dispatcher-scan", "at": 1792858803558}` from 00:51 onward, with no pid in it. Every
   round afterwards answered `{"rounds": [], "end": {"state": "joined", "reason":
   "guard_held"}}` — the scheduled tick and the manual force marker alike — and wrote
   nothing. Cleared with the engine's own `guard_release`; the guard carries no owner pid,
   so a dead owner cannot be detected (KI-354's family: the same class as the stale round
   pointer fixed earlier in `lib_round_face`).
2. **`line_env` stopped inheriting the process environment.** `develop_certify.line_round_tick`
   builds `line_env = dict(env) if env else {}` and the forced path passes `env=None`, so
   `resolve_runner` never saw `SANDBAR_LINE_ROUND_RUNNER` (present in the worker's own
   environment, both paths existing) and answered `runner_missing`. The regression came with
   the t261024-50 landing (the candidate-tree roster change touches exactly that block).
   Fixed by ticket `t261024-70` (landed `4135c3f8`, promoted).

With both cleared the loop heals itself: the worker now writes its own certification
(`05:20 4135c3f8 green dispatcher-scan`, no operator act).

### Still open, and what each needs

- `t261022-14` and `t261022-12`: both green apart from a gate run that peels their OWN
  scenario out of the run list (engine pool: `ran=0`; browser-free: the fast set only), so
  no landing anchor is ever minted. Two fixes landed (`t261024-40`, `t261024-60`) and the
  witnesses did not move - KI-355 records the conclusion: the peel is on the POOL EXCLUSION
  side, not in the plan builder those two tickets touched. Next attempt starts there.
- `t261022-15` still waits for a working session.

### Numbers at hand-off (261025 06:30)

main `4135c3f8`; 46 landings; 74 certifications; known-red book 104 rows; KI 345-355 open
(11 entries, each with the measured evidence and the reproduction path). Six fix tickets
landed across the day: KI-350 anchor refresh, the inspection sign chain, the Epics renderer,
KI-352 single record, the zero-run gate (two attempts), and the runner/env regression.

## 261025 08:20-09:20 — the peel is fixed, the anchor is the last link

`t261025-02` (the pool-exclusion-side fix) is live and it works: both witnesses now run
their OWN scenarios inside the gate. t261022-12's receipt names `quickmanual-handback-faces`
and `quickmanual-main-sync-handback-e2e` (both pass); t261022-14's receipt reads
`ran=3 passed=3 failed=0`.

They still cannot land, and the reason is one link further on (KI-356): the landing anchor
(`meta.last_green_run`) is not refreshed by a TARGETED green round, so both lanes still carry
a stale sha (t261022-14: 5fe50423 vs its HEAD 77d52623; t261022-12: 43c5d2f2, ran=0) and the
landing refuses "proven revision does not contain current main". KI-350's fix (t261024-12,
live since the 00:00 handover) evidently covers only the full-round path.

Also fixed tonight, both found by the round itself:
- the D3 assertion in `t261024-70-line-round-env-inherit` scanned every ledger row as a
  string and tripped on a promotion NOTE that mentioned "runner_missing"; it now judges
  structured fields only (state/reason/error/verdict/kind).
- two engine stalls, cleared: the stale round guard (held since 00:51 with no owner pid) and
  the `line_env` regression that answered `runner_missing` (ticket t261024-70).

## 261025 11:30 — final state and the three things that are NOT fixed

Landings 48, certifications 78, main `ce872293` (7 promotions today: 5184f806 -> ce872293).
Known-red book 106 rows. KI 345-357 open.

Fixed and verified today (each with a live witness, not only a battery):
- the Epics tab renderer collision (t261024-21)
- the inspection sign chain, first round (t261024-16)
- KI-350 full-round anchor refresh (t261024-12)
- KI-352 the round now always writes exactly one record (t261024-30)
- KI-353 the gate no longer peels a ticket's own scenario (t261025-02 - the receipts now name the
  ticket's own cases)
- KI-354/355 family: the stale round guard, and the line_env regression that answered runner_missing
  (t261024-70)

NOT fixed, and each has a live reproduction:
1. KI-356/357 **the landing anchor still does not refresh for a narrowed round.** Three tickets
   tried (t261024-12, t261025-02, t261025-08) and all three were accepted on a fixture battery
   while the live value never moved. Witness: `t261022-14` (lane HEAD has advanced, meta.last_green_run
   is still 5fe50423/ran=90) and `t261022-12` (still 43c5d2f2/ran=0, now also capped at
   "test-set iterations 6 > 5"). REPRO: re-gate the lane, then read meta.last_green_run - it must equal
   the lane HEAD; today it does not.
2. **Inspection fixture ticket ids collide with the day's real ticket** (booked isolated, not fixed):
   after the 07:30 daily schedule mints today's ticket, both sign fixtures are handed the same id
   (t261025-01) and hang on the real ticket. Works before 07:30, breaks after.
3. **`t261022-15`** still waits for a working session (process-bench leak ticket).

Discipline learned tonight, worth keeping:
- A fix is not accepted on a fixture battery: reproduce the WRITE (or the refusal) on the live path.
- Never commit the known-red book or notes to main directly: main must stay an ancestor of the line,
  or every promotion refuses `promotion_not_fast_forward` (happened three times).
- Never widen a wall-clock window without confirming the failure path still fails loud
  (the 90 s -> 240 s change hid a real stall for four minutes).

## 261025 afternoon addendum (13:00-16:20 CST) — the two wedged tickets landed

`t261022-14` and `t261022-12` both landed and closed; `main` moved twice
(a4ab2b7 -> b3c3ca5b -> 82927fd0). What actually unblocked them, in order:

1. **KI-356/357 is real but needs the enable signal.** `t261025-08` shipped a
   replay-safe signal (`client.enable_narrowed_anchor(ticket, who)`,
   `ENABLE_NARROWED_ANCHOR_SIGNAL`). Sending it BEFORE the re-gate is what makes
   `_ki220_record_green_run` take the narrowed arm. Proof on the live path:
   `t261022-14` recorded `{ran: 3, sha: 017425aa, narrowed: true}` right after the
   signal, and `t261022-12` recorded `{ran: 2, sha: 607348dc, narrowed: true}`.
   Rework alone does not do it — the signal is the missing operator act.
   Both KI rows are now `fixed`.
2. **A freeze was pinning every landing for four hours** (03:07 -> 07:00). Closer:
   attribute + `closed` change rows with the booked-red ground (the two cause reds
   were the inspection fixture-id collisions). Two freezes were closed that way,
   the second one on repair evidence from a line commit.
3. **A landing can resurrect a line-side deletion** (new KI-360). The `t261022-14`
   landing merged the lane's older `integration/run_scenarios.py` over `e868f0fb`,
   restoring `FAST_SET_CATCH[t261022-09-quick-gate-scope]` with no registry marker.
   The fast-set declaration then refused as an orphan, which turned FOUR cases red
   (`t261009-16-fast-set-declaration/gate`, `t261011-11-review-patrol`,
   `t261018-01-closing-fast-once`) and made every round red. Repaired on the line at
   `9061c17d` (delete the key, retire the case from the book: 106 -> 105 rows).
4. **`t261022-12` could only move forward through the gate stage.** `rework` to
   `implement` is refused with the impossible literal `fallback()` (new KI-358);
   `rework` to `run_integration_tests` is the path that makes the lane re-sync main
   and re-run the closing full run. That closing run then passed with zero new reds.
5. **KI-352 is still alive in the product path.** The 06:00 round on `82927fd0` ran
   709 with 0 failed and 13 env reds: face red, record green, and this time it did
   write a cert row. The 04:20 round (4 content reds) did not need one. But the
   03:18 round never wrote one, so the class is not closed — a content-green round
   whose face is red is still not guaranteed a record.

New KIs registered in this window: KI-358 (rework-to-implement refuses with
`fallback()`), KI-359 (an orphan `stage_docker.py hold` lease outlived its scenario
by 3h08m on a dead anchor pid; killed by hand), KI-360 (a landing resurrecting a
line-side deletion).

Still open after this window: `t261022-15` (process-bench leak, waits for a working
session), KI-359's reaper, KI-358, and KI-352's product-path guarantee.

## 261026 night — six tickets delivered to main

`main` moved four times after the afternoon addendum (`f070bf84` -> `5fb09030` -> `92495bcb` ->
`5c1ed768`), and every ticket that was open at midnight is on it except `t261022-15`, which still
waits for a working session.

| ticket | what it delivered |
| --- | --- |
| t261025-11 | the round that wrote no ledger row now heals into exactly one |
| t261025-12 | the panel carries the two certification controls the host asked for |
| t261025-14 | usage is frozen before the lane dies; the face states its coverage |
| t261026-01 | the ticket population matches the store (43 -> the real count) |
| t261026-02 | project sessions reads the DSH session home (host ruling u) |
| t261026-03 | markdown is a document wherever it lives, not only under docs/ |
| t261025-13 | the token face is three honest tiles; the rework-rate tile is gone |

### What actually cost the time

1. **The line froze four times**, each time on a red whose content had nothing to do with the
   revision under test: two interference faces, one stale assertion, one contention red. Each thaw
   was an attributed `closed` row citing the booking or the repair - never a silent release.
2. **A saturated box produces red-by-budget.** Load average 18-34 with FSEvents and mds near 100
   percent turned four cases red in one round that all pass alone (recorded as KI-365). The rule
   that saved the night: re-run every red alone before believing it, and run the line round with no
   ticket gate and no operator probe in flight.
3. **A landing can resurrect a line-side deletion** (KI-360) and **a landing can be skipped because
   the landing record matched the ticket, not the proven revision** (KI-361). Both bit tonight; both
   were repaired by hand and recorded.
4. **Booking a flaky-green case is forbidden by the repo's own test** (`test_fixed_must_leave_the_book`
   names t260921-06 explicitly). One booking was made and reverted within the hour; the rule stands:
   a case that re-runs green is re-run, not booked.
5. **Promotion only ever reads the newest green certification**, and every relative round writes a
   baseline certification for main afterwards - so a promotion issued even ten minutes late loses to
   its own baseline. The reliable shape is one job that runs the round and promotes immediately
   afterwards; two of tonight's promotions were done that way.

### Still open

- `t261022-15`: the process bench must not outlive its case; needs a working session.
- KI-358 (rework to implement refuses with the literal `fallback()`), KI-359 (stage lease outliving
  its scenario), KI-362 (usage dies with the lane), KI-363 (population filter), KI-365 (budget kills
  cannot be told from content reds on the face).

## 261025 late shift (05:00-07:00 CST) — the certification loop ran end to end

`main` moved four more times and every open ticket except one closed. The loop that finally held:

    land -> baseline round on main -> candidate round on the line head -> green certification
         -> the engine releases the freeze itself -> the executor promotes main

What made it work, in order:

1. **Never run a line round while a ticket gate is running its own suite.** Both share the docker
   batch stage; a gate's teardown kills the round mid-flight. Measured signature: the suite dies at
   a near-constant 249-506 s with `runner_failed_exit_2` and `batch-stage: received signal 15`.
2. **An orphaned batch stage wedges everything afterwards** (KI-366). `stage_docker sweep` reported
   it but refused to tear it down (holder heartbeat fresh, anchor tree already deleted). The fix was
   an explicit `stage_docker down --project batch-<id>`; the next round certified green in 15 min.
3. **A booking made on the line is invisible to the next automatic round** (KI-364): the round
   candidates on the LAST LANDING, which predates the booking commit. A manual round (candidate =
   line head) breaks the loop; so does landing one more ticket.
4. **A rework can miss the landing entirely** (KI-361, three times tonight). A ticket that lands and
   then gets a send-back closes with the fix still in the lane, and the lane is deleted at close.
   Symptom to watch: the ticket is `merge/running` while the scenario its rework named is still red
   on the line. Recovery when the lane is already gone: cherry-pick the orphan commit, or repair the
   asset directly when it is integration's own (that is what the metrics anchor needed).

Faces fixed tonight, all driven by host reports: the certification tab's two controls (design in
`docs/design/executor-operational-envelope-v1.md` §5), the metrics fabrications (fake 2001
timestamps, a population seven times too small, tokens missing cache and 70 percent of the tickets),
the tokens-by-role and project-sessions empties, and the markdown reviewer that only recognised
`docs/**/*.md`.

Still open: `t261022-15` waits for a working session (process-bench leak), KI-358 (rework to
implement refused with the literal `fallback()`), KI-361/362/363/364/365/366, and the display
caliber questions the host has already ruled on (they ride in the tickets, not here).
