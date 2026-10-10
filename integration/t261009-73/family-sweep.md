# Family sweep receipt — t261009-73

Ticket item 3: the family sweep is closed with THIS receipt, not with t261009-70's
finding. The finding's enumeration was the starting list; everything below comes
from a fresh grep over `integration/` at this worktree (base `dbca4bda` + this
ticket's changes):

```
grep -rn "waitReady|就绪超时|not ready" integration/ --include="*.mjs" --include="*.py"
grep -n "超时" integration/*.mjs integration/*.py   # readiness-path follow-ups
grep -rn "ready|超时|console.log" <each candidate lib>   # per-file classification pass
```

Pattern under test: a readiness/boot timeout that throws a message naming a local
console log which the SAME caller's teardown then deletes (unattributable env-red).

## Classifications

| Site | Classification |
|---|---|
| `integration/t260904-17/lib_fix17.mjs` (`waitReady` + `captureBootFailure` + `bootConsole` catch) | **Fixed by t261009-70** (dbca4bda). Evidence contract face; regression test `integration/tests/test_t261009_70_boot_evidence.mjs` re-run green this ticket. |
| `integration/t260916-26/lib_t260916_26_bench.mjs` (local `waitReady` throw + `bootLaneConsole` catch) | **Fixed here.** `waitReady` now throws with the fix17 template (bounded tail + `$TMPDIR` survivor); `attachBootEvidence` runs before `clean()` on every failure path. Unit tier: `integration/tests/test_t26100916_26_boot_evidence.mjs`, 8 cases green. |
| `integration/t260905-07/lib_t260905.mjs:57` (`waitReady`, 90 s) | **Not this pattern** (review comment 2 confirmed): it reads the log at throw time (`readFileSync(...).slice(-2000)`) and embeds the tail in the message, with `(无日志)` as named absence — degraded-but-attributable at throw time. No survivor copy (observation only; no ticket forced). Its boot faces `start()`/`teardown()` reclaim tmpHome after the throw, but the evidence already lives in the message. |
| `integration/t260904-06/bench-shot.mjs:116` (`waitReady`) | **Not this pattern** (same degraded shape): tail embedded at throw time, `(无日志)` absence. No survivor copy — observation only. |
| `integration/stage_docker.py` (`_wait_diag`, ~3061) | **Not this pattern**: readiness failure attaches the log tail from `docker compose logs` at failure time; the log source is container-side, not a locally reclaimed file. Already precise-by-design (gen2 companion 1). |
| `integration/t260916-25/lib_stage_fixture.mjs` | **Not this pattern**: its `超时` hits are the stepper's timeout-kill guard (`超时兜底 SIGKILL`); no throw names a console log. |
| `integration/t260905-08/lib_t260905_08.mjs` | **Not this pattern**: single `超时` hit is a header comment about inherited teardown/timeout semantics (from fix17); no readiness throw naming a log. |
| `integration/stage_client_boot.mjs` | **Not this pattern**: `超时` hits are its own lifecycle timeouts (unauthorized/deps/shutdown); it is a client-session channel, no console-log-naming boot throw. |
| `integration/t260904-10/lib_fix10.mjs`, `integration/t260904-05/lib_browser.mjs` | **Not this pattern**: `console.log` hits are result-printing calls (`[FAIL]/[PASS]/SUMMARY`), not log-file references; no readiness-timeout throw naming a file. |
| `integration/t260904-15/lib_fix15.mjs` | **Not this pattern** (re-verified from the finding, not copied): boot face is the docker stage via `stage_docker.mjs`; readiness lives in the stage tool (see `stage_docker.py` row). |
| `integration/bench_console.mjs`, `integration/lib_stage_console.mjs`, `integration/lib_stage_ui_surface.mjs` | **Not this pattern**: console boot/management helpers without the ready-timeout-naming-deleted-log shape; their timeouts (daemon probe, ensure budget) throw naming the cause, not a log they then delete. |
| `integration/t260916-26/sc_console_boot_no_plugin_banner.mjs`, `integration/t260916-26/sc_t26091626_boot_evidence.mjs`, `integration/t261009-70/sc_t26100970_boot_evidence.mjs`, `integration/tests/test_t261009_70_boot_evidence.mjs`, `integration/run_scenarios.py`, `integration/baselines/sc_capture_board_assert.mjs` | **Grep hits only** (word matches: scenario comments, the contract registry text, test/scenario files exercising the helper faces — including this ticket's own gate scenario `sc_t26091626_boot_evidence.mjs` and its `run_scenarios.py` / `test_anchors.json` registry entries). No harness code throwing the pattern. |

Sweep verdict: **closed** — exactly one site carried the pattern (fixed here),
one was already fixed (t261009-70), and every other hit is classified
not-this-pattern with the reason above.

## Borrowed-pattern fault-mode checklist (review comment 1 — explicit, not implicit)

Reference pattern: `lib_fix17.captureBootFailure` / `bootFailureError` /
`bootConsole` catch (t261009-70, dbca4bda). Trade-off per fault mode:

| Fault mode (reference) | Carried / Not carried — how |
|---|---|
| (a) missing / empty / unreadable log → named absence, never fabricated lines | **Carried** via direct reuse of `captureBootFailure` (same function object, zero divergence). Unit cases: missing / empty / chmod-000. |
| (b) non-UTF-8 log → named lossy decode + byte-exact survivor | **Carried** via reuse. Unit case: 6-byte binary log, survivor byte-compared. |
| (c) survivor write failure → bounded tail in message remains the fallback | **Carried** via reuse (captureBootFailure sets `survivor = null`, template prints `(copy failed or log empty)`). |
| (d) evidence attachment masking the original error | **Carried**: `attachBootEvidence` wraps its whole body in try/catch and returns the original error untouched on any internal failure. |
| (e) double attachment on already-annotated errors | **Carried**: dedupe marker `log preserved at` (same phrase as the fix17 template), unit-asserted. |
| (f) hostile label chars (label derives from consumer input `basename(projectsRoot)`) | **Carried** via reuse of captureBootFailure's sanitization; unit case with `../../evil name;rm`. |
| Survivor written INSIDE the reclaimed tmpHome (defeating the whole fix) | **Carried-not**: survivor path is `$TMPDIR/...` from captureBootFailure; unit case asserts the survivor survives a simulated `rmSync(tmpHome)`. |

Deviations from the reference: none functional. The only local code is the
`attachBootEvidence` seam (approved by review, comment 4: pure append-and-annotate,
no state) and the verbatim-template throw in the local `waitReady` (comment 5:
strings copied character-for-character from `lib_fix17.bootFailureError` /
`bootConsole` catch, dedupe marker included; template source noted in the module
header).
