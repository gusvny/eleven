# Test design — t261009-70 (stage: design_integration_tests, role: integration)

## What changed for the user (behavior surface)

Today a stage-console boot failure is unattributable: the receipt says only
"ready timeout (45s)" and points at a `console.log` the harness itself deleted
on the way out. After this ticket a boot failure must LEAVE evidence a steward
can act on: the rejection message names the timeout, quotes a bounded tail of
the console's own last words, and names a survivor log path outside the
reclaimed temp home. A boot failure stays a failure (env-red); nothing becomes
a pass.

## Scenario (registered, pool `ro`, offline seconds)

`integration/t261009-70/sc_t26100970_boot_evidence.mjs` → registry name
`t261009-70-boot-evidence`. Grey-box L3 over the PUBLIC contract face of
`integration/t260904-17/lib_fix17.mjs` (`waitReady` / failure-capture export,
discovered by contract name), short injected timeouts, dead loopback port,
temp dirs only. Zero docker/Temporal/browser, never touches 3099/7233.

### Sub-cases

- A `boot-timeout-names-reason-and-survivor` — the readiness timeout REJECTS
  (never resolves; boot-red stays red), the message names the timeout, quotes
  the log's last line, and names an existing survivor path outside the temp
  home holding the log content.
- B `boot-timeout-tail-is-bounded` — a 20k-line log still yields a bounded
  message carrying the LAST line (no whole-log dump).
- C `boot-timeout-{missing,empty,binary}-log-named` — malformed evidence honesty
  (settled at the t261009-70 rework, 261010): a MISSING or EMPTY log degrades to
  a NAMED absence inside the rejection (the worst lie is quoting invented
  lines); a PRESENT but non-UTF8 log is evidence, not absence — the survivor
  copy is BYTE-EXACT (raw bytes; the first utf8-reading cut corrupted binary
  logs, 5 bytes → 10 replacement-sequence bytes, proved in walkthrough) while
  the quoted tail names the lossy decode instead of printing replacement
  garbage. No secondary throw; no fabricated lines.
- E `boot-failure-leaves-evidence` — contract discovery: a missing
  `waitReady` export is a named FAIL (pre-implement red = TDD signal).

### Failure surfaces covered

abnormal input (missing/empty log = named absence; non-UTF8 log = byte-exact
survivor + named lossy tail), resource lifecycle (survivor must
live outside the reclaimed tmpHome; temp homes removed in every arm),
error-message precision (named absence, not "no result"), and the
no-weakening invariant (rejection must not turn into resolution).

## Intent-duplication check

No existing registry entry guards boot-failure evidence or the readiness
timeout face (grepped SCENARIOS for waitReady/console.log/ready-timeout —
zero hits besides this ticket's own entries). The lane-map mount journey
(t261009-68 entry) owns crash-free rendering, not boot evidence. The sibling
readiness-timeout site in `integration/t260916-26/lib_t260916_26_bench.mjs:78`
is the same fault family but outside this ticket's write-set — recorded in the
plan review, fix belongs to its own ticket.

## Gate semantics

env_fail stays non-red; the 45 s default is not relaxed; no assertion of any
existing scenario touched. The scenario is red until the implement stage lands
the evidence survival (expected, named TDD signal).
