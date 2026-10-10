# Test design — t261009-73 (integration stage)

Scenario: `integration/t260916-26/sc_t26091626_boot_evidence.mjs`, registered as
`t260916-26-boot-evidence` in `integration/run_scenarios.py`, anchored
(`contract`) in `integration/test_anchors.json`.

## Intent

The user-perceivable contract this entry owns: a boot failure of the
t260916-26 lane bench is ATTRIBUTABLE — the rejection carries the console's
own last words and a survivor copy the harness's own reclamation does not
delete, so "never ran" is never indistinguishable from "environment red"
(host report 261010, the incident that cost two UI tickets their
verification). The generic contract is already owned by
`t261009-70-boot-evidence` on the fix17 face; this entry owns the SAME
contract on the named family member (`lib_t260916_26_bench.mjs`) — different
face, not an intent duplicate.

## Failure surfaces (from the reviewed plan + defect site)

- Resource lifecycle: `bootLaneConsole`'s `clean()` deletes the log the
  error message names — evidence must be captured BEFORE reclamation.
- Malformed input (the console log is external input): missing / empty /
  unreadable / non-UTF-8 logs must degrade to a NAMED absence or a named
  lossy decode, never fabricated lines, never replacement garbage, never a
  secondary masking error.
- Error-handling path: evidence attachment itself must never throw and must
  not double-annotate an error that already carries its snapshot (dedupe
  marker `log preserved at`).
- Gate honesty: a pre-log boot failure still rejects named and fabricates
  zero survivor files; no pass conversion anywhere.

## Cases (A-F)

| Case | Asserts |
|---|---|
| A | capability discovery: `attachBootEvidence` export exists (named FAIL pre-implement = TDD signal) |
| B | annotation carries failure context + tail (shared phrases) + survivor outside the temp home, content intact AFTER `rmSync(tmpHome)` |
| C | tail bounded: 20000-line log → bounded message carrying the LAST line |
| D | missing/empty → named absence, no quoted lines, no secondary throw; binary → byte-exact survivor, named lossy decode, no U+FFFD |
| E | dedupe marker blocks double annotation |
| F | pre-log boot failure (`FIX17_MAIN_ROOT` → nonexistent tree, throws in `buildLaneProfile` before `console.log` exists) rejects named, quotes no evidence, creates zero `fix17-console-*` survivors |

## Three-state semantics

PASS / FAIL / ENV_FAIL only (bench lib unimportable = exit 2). No SKIP.
Pre-implement tree red on A-F is the expected TDD signal; green required at
the integration gate / merge.

## Non-goals

The real 45 s spawn path (browser family), the family-sweep receipt
(document deliverable of this ticket, not a scenario — snapshot docs get no
regression pin), the fix17 face (owned by t261009-70), the ANCHOR root cause
(t261009-72).

## Self-check (any reader, cwd = repo root)

```
python3 integration/lint_tests.py
node integration/t260916-26/sc_t26091626_boot_evidence.mjs   # red pre-implement (TDD), green at gate
grep -n "t260916-26-boot-evidence" integration/run_scenarios.py
```
