---
title: "Failure Classification Protocol v1 and Mechanical Attribution"
category: design
tags:
  - failure classification
  - attribution
  - integration gate
  - protocol
  - result ledger
status: active
updated: 2026-09-28
related:
  - mode: dependency
    target: sandbar-project-onboarding-contract-v1.md
    note: verify.yaml contract clause ②a / integration lane
  - mode: practice reference
    target: ../testing-guide.md
    note: three-state execution contract (t260904-12)
---

# Failure Classification Protocol v1 and Mechanical Attribution

## Problem

Three misjudgments in a single day on 260910 (t260910-05 / t260910-10 / t260910-08):

1. **A transient concurrent-environment failure taken as a genuine red** — arbitration could only take "text lines + exit code" and guess by reading them; the classifier was patched six times, hit the round limit, and was escalated to a human;
2. **A genuine red released as environment noise** — four sub-cases of the documentation-view contrast check, seven violations each, were a genuine product red; arbitration had no main baseline to compare against and let it through under the "environment noise" narrative;
3. **Noise inferred from duration characteristics** — five reds were judged "noise" by integration on duration characteristics alone; after the host challenged it, actual measurement showed two were green on main (genuine regressions pending isolated re-runs to qualify), one was also red on main (pre-existing debt), and one refused to run because its pre-check found stale artifacts (it was never actually exercised, yet reported FAIL).

Two root causes: **failure information is not structured** (text + exit code, readable only by guessing); and **ENV_FAIL is a natural exemption label** (nothing blocks it even without evidence).

## Requirement (the contract surface)

**One uniform format: one line of JSON per test case** (the single canonical form, the single authority). Minimum required fields:

| Field | Semantics |
|---|---|
| name | case name (the gate aligns baselines by this; the gate does not know scenario semantics) |
| suite | owning suite |
| status | `pass` / `fail` / `not-checked` (closed vocabulary; failing before reaching an assertion = not-checked) |
| cause | `self` / `external` / `unknown` (responsibility lead) |
| reason | reason code: assert_mismatch / connect_refused / timeout / lock_busy / missing_asset / self_precheck / … (open vocabulary; the gate does not seal the enumeration, it only classifies) |
| dur_s | case duration (the data source for the duration trend on the B face of inspection; the 260910 measurement "777s vs 176s for a solo run" is the case for this field) |
| attempt | which attempt this is (producer = emitter, default 1; the rework generation is explicitly stamped by the gate/engine side, never written twice) |
| started | start time |
| git_sha | fingerprint of the tree under test |
| evidence | one line of verbatim text (newlines mechanically flattened; an environment red must name what is missing) |
| artifacts[] | evidence artifact paths |

**Tightened three-state semantics**: the ENV_FAIL state = not-checked and must carry reason + evidence; **a not-checked without evidence is always treated as FAIL** (fail-closed, both ends: the emitting side refuses to emit, the gate side reclassifies).
`fail × prepare-type reason` (self_precheck/connect_refused/lock_busy/missing_asset)
= **protocol violation**: the gate reclassifies it as not-checked + violation flag + independent interception (not released just because main is also red).

**Mechanical attribution (host decision table)**: the gate automatically runs the same command on main to obtain a baseline, and decides by set difference against the lane cases:

| Lane case | main baseline | Verdict |
|---|---|---|
| not-checked × self | green | **intercept** (caused by this ticket) |
| not-checked × external | green | record + push for remediation, do not block |
| fail (assertion does not hold) | green | **intercept** (genuine regression) |
| any | red (checked fail) | pre-existing debt, record and do not block |
| any | not-checked (baseline never checked it) | **unknown**, record without verdict |
| protocol violation | any | reclassify + **intercept** |

Baseline criteria (the key point, nailed down): **the baseline red list admits only checked fails (assertion level)** — the baseline answers only "whose fault it is", never "whether this is the environment"; a baseline-side not-checked = not checked = cannot answer whose fault, and never enters the red list (otherwise the t260910-10 type of "genuine red whitewashed by a baseline environment red" recurs verbatim from the baseline side).

**Fingerprint closure**: the set difference is trusted only when `env_fingerprint` (lane) == `env_fingerprint` (baseline); the key set = the invariant surface of the runtime context (toolchain versions + hash of protocol library contents), excluding ticket-context keys (SANDBAR_TASK_QUEUE and the like) and transient paths — choosing a key set that always differs means attribution is permanently unknown. Not equal →
attribution for the **not-checked class** degrades to unknown (an incomparable set difference cannot assign fault) + the per-key difference surface is explicitly declared; fail is still intercepted, violation is still intercepted (the conservative direction is not loosened — "a genuine red must be intercepted" is not relaxed because the baseline is incomparable). This is the literal correction to "all attribution degrades": degradation falls only on the not-checked face, which cannot assign fault. For all three degraded states (baseline absent / timed out / fingerprints unequal), attribution explicitly reports `affiliation_confidence=unknown(reason)`, and all-green cases are never implicated.

**The summary line is generated by the gate** (not written by the tests): `{ran, pass, fail, not_checked, wall_s,
concurrency, pool_config, env_fingerprint, baseline_ref}`. Division of labor: the executor produces counts/durations/
concurrency/fingerprint; the gate supplies baseline_ref and **recomputes and cross-checks** against the canonical-line details (the authority for the cross-check = the gate's recomputation; a false report = red).

**Generality**: the gate does not know scenario names and the protocol is project-independent — the mechanism lives in the engine (the failure_protocol pure functions +
the single parsing implementation in verify_lane), and the face lives in the project (verify.yaml declares cmd; any test framework that emits canonical lines is onboarded by that alone).

## Nongoal

- No junit adapter, no intermediate format of any kind (host decision on 260910: the protocol = one line of JSON, the single canonical form);
- No scenario whitelist and no business-semantics recognition (the gate looks only at status/cause/reason and decides mechanically);
- Baseline-tree dependency bootstrapping covers exactly one case, "shared dependencies already present in the main repo → read-only symlink into the baseline tree" (revised on 260922:
  the original "not doing it" entry contradicts the shipped implementation, see the maintenance note; the trade-off list is in Proposal, and the list of names and switches
  is in the implementation). Installing/building/copying dependencies is still out of scope — an absence outside the list still follows the baseline's honest
  not-checked criteria; if every symlink fails, the baseline stays bare, with zero relaxation of the criteria;
- How to repay the baseline red is not handled inside this protocol (it is only recorded; repayment goes through the debt governance process).

## Proposal (what it is / why, names and switches in the implementation)

- The pure-function core lives in the engine (parsing / three-state tightening / fingerprints / decision table / summary recomputation); gate execution and parsing exist in exactly one place
  in the whole system (the verify_lane lane=integ thin shell is not broken; host instruction t260902 layering). The engine activity only places orders and
  translates receipts, and mechanically counts the gate's interception list into failed ("interception" is a mechanical counting surface, not a textual recommendation).
- Dual-parsing compatibility period: canonical lines (JSON lines starting with `{`) are authoritative; legacy PASS[/FAIL[/ENV_FAIL[ text lines are retained for
  counting and the legacy green criterion (compatibility-face regression continues to be guarded by the existing scenarios of t260904-12 sections A/B). **The compatibility text-line path
  has no cause/reason, so the violation class is mechanically invisible** — the blind spot is stated plainly, with no suggestion that it is covered; the red face of purely legacy
  output is fail-closed red with no attribution.
- Baseline execution: a temporary detached worktree + the same command + reduced-load serialization (not the same-criteria wide pool of the lane) +
  a wall-clock ceiling + finally-state collection across every terminal state (worktree remove --force deletes only self-created paths, respecting the KI-065
  radius bound). Scheduling = lane first, baseline second: an all-green lane skips the baseline (zero extra cost); the baseline runs only when there are reds. It is governed by an environment switch
  (on by default, can be turned off, can be time-limited; names in the implementation); an absent baseline = an explicitly declared degradation.
- Baseline-tree dependency bootstrapping (reinstated into scope on 260922): after the baseline tree is created, shared dependencies already present in the main repo are mounted into the
  baseline tree per a list and used read-only — same-repo guard (the baseline tree and the lane root must not be different git repos, no external linking), additive only, never overwriting
  (skip when the target already exists), skip when the source is absent, and a single failure is loud but not fatal. If every symlink fails, the baseline stays bare and the
  not-checked criteria remain as they are (no fake green, zero relaxation of the criteria); the switch is on by default and can be explicitly turned off (names in the implementation);
  collection follows the baseline tree's finally block, taking tree and links together through every terminal state (KI-065 radius bound).
- pytest production side: the native hook pytest_runtest_logreport, with phase merging (setup ERROR →
  not-checked, call FAILED → fail, PASSED → pass, teardown ERROR does not flip an already-decided case,
  same-name one-line invariant), and mechanically single-line evidence. Assembly is introduced explicitly through a thin conftest (not relying on
  the version-sensitive behavior of pytest_plugins).
- The executor synthesizes canonical lines for legacy scenarios (reverse-engineered from the three-state contract: exit1 = assertion-level fail, exit2 = not-checked with tail evidence,
  timeout = a timeout label that does not masquerade as an assertion error); before the protocol is fully switched over, legacy text lines keep being emitted (the observability face), and
  retirement follows a dedicated ticket. When a scenario emits canonical lines itself, they pass through verbatim (zero synthesis in the executor, summary counted by detail) — both production
  seams (executor synthesis / scenario self-emission) are valid, and scenarios that do not self-emit need no change.
- **Abnormal exit ≠ green** (settled in the 260910 walkthrough): an executor crash / being killed / a missing summary line / an exit code inconsistent with
  the case set = the case set may be incomplete, so the gate goes fail-closed red and calls out "incomplete" — protocol mode never
  concludes green for an incomplete case set merely because "the cases that were parsed happen to be all green".
- **ran == the registered count is the only mechanical invariant** (settled in 260911 arbitration: a self-consistent summary ≠ a complete list — when a pool-level
  exception swallows entries, the summary stays self-consistent and silently dropped entries still produce green): the executor self-checks ran against the registered count,
  a pool-level exception keeps the futures handles and surfaces each one = a loud product red, and a spawn failure is classified red per the protocol
  (not-checked×external, with verbatim evidence) and never raises away an entry; the summary line carries expected
  (the registered count) for the gate to cross-check ran==expected.
- Coverage criteria (to prevent misreading): the gate's baseline actually runs only when the lane has reds; "the full-gate run is all green" does not trigger a real full
  main-baseline run — real baseline coverage = the gate scenario's genuine git baseline sub-cases + the gate's real run when the lane has reds.

### Result ledger (the bookkeeping face for red-side attribution)

Addresses "the gate is forever red / full runs repeat": the gate's every scenario verdict is booked per commit, and the red face is checked against the ledger before a real run is made — a hit
exempts the case from a re-run, and only entries that cannot be accounted for are re-run in place.

- **Single source of truth**: a **single out-of-repo** file of JSONL on the host side (the absolute path and the global coverage switch are in the implementation) —
  it does not enter the lane workspace (which would collide with the "merge check = workspace clean" criterion), does not go into the repo (concurrent writes = conflicts = rework),
  and is not copied by fixtures (the multiplication behind the 408GB incident).
- **Format**: append-only JSONL, one line = one scenario verdict, a ten-field closed schema: ts (ISO8601
  with timezone) / commit (40hex) / env_fp (64hex) / conc_width (≥1) / pool / scenario /
  verdict (pass|fail|env_fail|skip) / wall_s / source (lane:<ticket>|inspection|baseline) /
  ticket. Key = (commit, env_fp, conc_width, scenario); any missing/malformed/extra field or
  over-wide line → the write is rejected (a dirty record is worse than no record), and if a whole batch is rejected nothing lands on disk (no file is created).
- **Single writer on the write face**: the only appending writer = the gate (the lane / inspection / baseline paths all converge through it); the library and the query
  CLI themselves have no second-writer entry point, and retention-window maintenance rewrites are not a second writer (same key keeps the newest, atomic replacement, serialized by a
  file lock throughout). A dirty lane tree / a missing source / a missing concurrency width all mean no write plus a named callout — better a missing row than a dirty row.
- **Trust boundary** (pure functions in the engine, the gate only consumes): precondition zero = **only a "checked" face can be
  trusted** (an environment red and a reserved slot = not checked, and do not enter the red/green evidence); under that precondition it further requires env_fp equality
  + commit being an ancestor of the current base or identical + age ≤7 days + consistent conc_width; any one missing falls back to a real run.
  On the read face, malformed lines are named one by one, never silently.
- **Width division of labor (to prevent misreading)**: a baseline row always has the serial width 1 (a baseline run = reduced-load serial), so for a red in a lane at the default
  width the "consistent width" boundary is **not** satisfied; main-side coverage relies on **the same-width rows of the daily inspection** (the full
  face) and on the **live baseline authority** — the value of baseline rows lies in queries and in same-width trust — not in "it was booked but never hits, so the
  ledger is broken".
- **fail-closed consumption discipline**: not found = an explicit "no record" → fall back to a real run, **never "not found means green"**;
  a trusted ledger green does not reclassify or loosen anything (interception still comes from the conservative original verdict; a ledger green is only corroboration); when the baseline
  cannot assign fault, a trusted ledger red may fill in and record "pre-existing debt"; an absent or broken ledger face = a loud degradation, with attribution falling back to
  a real run (= the behavior without a ledger).
- **Retention and query**: older than 90 days is rotated out into monthly volumes; queries hit only the main ledger's 90-day window, and the "no record" wording states this
  explicitly (it does not pretend "never run"; querying monthly volumes goes through the maintenance face).

Maintenance note: this document is the finalized landing for t260910-13; KI registration for the three 260910 misjudgments belongs to the integration role
(the discipline of at least one regression case per fixed fault is carried by the t260910-13 scenario family).

260922 revision registration (clearing the two pending-doc-sync items of the doc gate after t260922-12 was merged): ① the Nongoal
entry "no baseline-tree dependency bootstrapping" is revised to shipped (trade-off list in Proposal); ② the "result ledger" section is added.
Landing path: the original dev-lane ticket t260922-17 hit the protected-path gate (`docs/design` may not be modified by any lane),
and per the gate's named way out ② (back to the main side) the landing was instead managed directly on the main side, and that ticket was voided (full history in the ticket and admin.log).
Evidence criteria: after the merge, evidence capture A′ is **absent**; the reason is that the **command face was constructively unrunnable** — that capture command used
an entry point that only accepts a scenario list, and that entry point is precisely this mechanism's own unmerged feature, which did not exist on main at the time, so
actual measurement gave exit=-9 (drained after a >900s timeout); main now contains that entry point, so the capture can be re-run in a quiet window with no concurrent lanes
(to do, not yet produced). A reviewable substitute evidence = the host-side ledger source of truth (a single out-of-repo
file, not committed) and its existing records: **546 rows / 0 bad rows / a single commit (t260922-06 merged at da942b8) /
a single environment fingerprint / two rounds of 273 scenarios each (2026-09-22 15:33 and 16:16)**, so the mechanism's real seam is in place and mechanically
reviewable. This registration records only the absence and the substitute evidence, and **does not present inference as actual measurement**.

260922 erratum (self-review by the substitute signer, same day): the first version of this registration attributed the absent capture to "docker returning nothing and high
ports being exhausted" — **that judgment was wrong**: the probe command itself failed at the time (this machine has no `timeout` command, and `timeout
docker info` reported command not found), which was misread as a docker fault; actual measurement showed docker healthy (`docker
info` returned rc=0 in an instant, OrbStack 29.4.0, the test-bench containers in place). The real reason is as stated above. This erratum is kept to record the lesson:
**a missing probe tool ≠ a faulty subject**; before judging that "some capability is broken", first confirm that the probe itself can run.
