# t261009-70 finding — boot-failure evidence and family enumeration

Date: 261010. Stage: implement (developer). Write set respected: `integration/t260904-17/lib_fix17.mjs`,
`integration/tests/`, `integration/t261009-70/`, `integration/` (registry + anchor registration).

## What changed (the fix)

`integration/t260904-17/lib_fix17.mjs`:

- New exported `captureBootFailure(logPath, label)`: reads the console log BEFORE the
  reclamation that deletes it, returns a bounded tail (last 4000 chars) for the error
  message and copies a bounded slice (last 256 KB, review comment 2) to a survivor file
  `$TMPDIR/fix17-console-<label>-<ts>-<pid>.log` that no reclamation path touches. The
  filename carries the label (boot-console projectsRoot basename) so a steward can
  attribute the log without opening it. Missing/empty/unreadable logs degrade to a
  named absence — the helper never throws, never fabricates lines.
- `waitReady` (now exported for the contract face) timeout branch throws an error that
  names the timeout AND quotes the log tail AND names the survivor path. The old
  message `隔离台就绪超时（45s）：log=<tmpHome>/console.log` named a file the caller's
  `clean()` had already deleted.
- `bootConsole` catch attaches the same evidence for every failure path (profile build,
  spawn, anything), then still reclaims tmpHome unchanged — the 260926 disk-leak
  invariant (reclaims-own-temp) is intact; only the copied survivor outlives it.
- Gate semantics untouched: boot failure still rejects → scenario still env_fails
  (exit 2); the 45 s default is not relaxed; no assertion weakened. The message text is
  for humans only — no parser matches on it (grep 261010: nothing matched the old
  string either; language asymmetry recorded here so nobody "fixes" it back, review
  comment 3).

## Family enumeration (review comment 1)

Grep over `integration/` for the readiness-timeout-then-name-a-deleted-log pattern
(`就绪超时` / `waitReady`):

| Site | Classification |
|---|---|
| `integration/t260904-17/lib_fix17.mjs` (waitReady, `bootConsole` 45000 ms) | **Fixed here.** This is the boot face of the whole fix23 console-scenario family (t261008-23 ×4, t261009-22, t261009-53, t261009-68). |
| `integration/t260916-26/lib_t260916_26_bench.mjs:78` (identical `waitReady` throw, `bootLaneConsole`) | **Same bug, OUTSIDE this ticket's write set** (t260916-26 dir). Needs its own ticket; do not fix here. Its scenarios: `sc_plugin_inject_contract`, `sc_console_boot_no_plugin_banner`. |
| `integration/t260904-15/lib_fix15.mjs` bootConsole | Different boot face (docker stage via `stage_docker.mjs`); its readiness check lives in the stage tool, not an inline 45 s wait naming console.log. Not this pattern. |
| `bench_console.mjs`, `lib_stage_console.mjs` | Console boot helpers without the ready-timeout-naming-deleted-log shape. Not this pattern. |

## Root cause naming for the lane-map reproducer (ticket item 2) — state of evidence

Static comparison (same lane, same commit) of boot inputs:

- t261009-53 `sc_t26100953_lane_map_pipe.mjs` boots via `lib_fix23.bootFixture` →
  `lib_fix17.bootConsole` — the **identical skeleton** (profile materialization, env,
  shim PATH, freePort) used by t261008-23 / t261009-22 scenarios.
- The sibling quoted in the ticket as passing in the same runs is NOT on this boot
  face: `t261005-04-ticket-detail-overlay` boots via `lib_fix15` (docker stage), and
  `t261009-64-withdrawal-promotion-guard-live` (0.20 s) is a `.py` scenario with no
  console boot at all. So "sibling console scenarios pass in the same runs" does not
  currently exercise the lib_fix17 boot face — the discriminating comparison is
  against t261008-23/t261009-22 scenarios (same face), whose recent statuses are not
  readable from this worktree (ledger lives outside the repo).
- A deterministic 45 s timeout that also reproduces against the main tree (baseline)
  cannot be caused by lane-only tree changes; combined with the shared skeleton, the
  prime suspects ranked: (a) the local `dsh` spawn itself failing on this host (env
  red — e.g. `dsh` binary/profile loader), (b) scenario-specific fixture registry
  content (`t26100953-lanemap` projectsRoot) crashing the loader before HTTP-up.
  The preserved survivor log + embedded tail now names which, with quoted lines.

**The run that settles it is gate-executed** (review comment 4), not run in this
stage per the 260921 verification discipline:

```
python3 integration/run_scenarios.py --only t261009-70-boot-evidence
node integration/t261009-53/sc_t26100953_lane_map_pipe.mjs   # 45s reproducer, now leaves $TMPDIR/fix17-console-boot-t26100953-lanemap-*.log
```

The receipt text of any future boot failure carries the tail and the survivor path;
this file should be appended with the quoted lines once the first reproduction lands.

## Verification done in this stage (unit tier only)

- `node --check` on both touched `.mjs` files.
- `node integration/tests/test_t261009_70_boot_evidence.mjs` → 9/9 green (bounded
  tail, 256 KB survivor cap, absent/empty/unreadable/binary-malformed honesty,
  hostile-label sanitization, waitReady dead-port rejection naming reason + existing
  survivor, reclamation invariant, no survivor leak).
- `python3 integration/lint_tests.py` → 0 errors (anchor registered for the new
  registered scenario in `integration/test_anchors.json`; registry entry present in
  `integration/run_scenarios.py`).

## Risks / leftovers

- Survivor files are one-per-failure, bounded at 256 KB each, in `$TMPDIR` — a slow
  accumulation is possible over many failing runs; acceptable vs. the evidence win,
  flagged for a future sweep if it ever matters.
- lib_t260916-26 family fix = separate ticket (named above).
- The t261005-04-vs-t261009-53 sibling asymmetry (docker face vs local face) should be
  stated in the eventual acceptance report: "sibling passes" today proves less than
  the ticket assumed.

Docs read: docs/README.md (index; no design doc conflicts — failure-classification
protocol v1 applies to gate semantics, which are untouched).

## Rework round 1 (261010) — binary evidence contract settled

Walkthrough defect: the first cut of `captureBootFailure` read the log as utf8, so a
binary log's survivor copy was corrupt (5 raw bytes → 10 replacement-sequence bytes,
proved) and the tail printed replacement garbage. Settled contract (now identical in
`lib_fix17.mjs` JSDoc, the `run_scenarios.py` registry D text, `test-design.md`, and
the scenario):

- missing/empty log → NAMED ABSENCE, no survivor (unchanged);
- present but non-UTF8 log → evidence, not absence: survivor copy is BYTE-EXACT
  (raw bytes read/written, bounded at 256 KB), quoted tail names the lossy decode
  instead of printing replacement garbage (a clean-text tail slice of a non-UTF8
  log is still quoted verbatim);
- valid UTF-8 log → text tail quoted even past the 4000-char bound (strict full
  decode first, so a large valid log is never misnamed lossy).

Also corrected: the round-0 handover quoted a non-registry scenario name
(`t261008-23-lane-map-v5`); the real registry names are `t261008-23-lane-map-v5-proportional`,
`t261008-23-timeline-reason-collapse`, `t261008-23-changes-english-dedup`,
`t261008-23-agent-log-dir-resolution`, `t261009-22-lane-map-mock-chrome` — the
passing-family quote must use one of those. Stated follow-up (not this ticket):
survivor files in $TMPDIR are unbounded across runs (pruning sweep); the
t260916-26 bench lib shares the deleted-log fault (own ticket).
