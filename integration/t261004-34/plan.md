# t261004-34 plan — Guards that cannot see their own target, round 2

Stage: create_plan (developer, round 1). No code in this stage; this file is the plan
deliverable. Write set honored: `integration/` and `server/engine/` only.

## A. Copy-language gate must count whole-line comments (executor -0002)

Root cause: `lint_diff` in `integration/lint_copy_language.py` fires only when
`_in_scope(path) and not _is_comment_only(text, path) and CJK_RE.search(text)` — a line
that is nothing but a comment never fires, while the module docstring (host order 261004)
promises the opposite.

Change (tighten only):
1. In `lint_diff`, drop the `not _is_comment_only(...)` term: condition becomes
   `_in_scope(path) and CJK_RE.search(text)`. `_strip_comment` / `_is_comment_only`
   stay — the marker-carry logic (`prev_carry`) still uses them, so the exemption
   marker (same line, or line directly above) keeps working for legitimately exempt
   lines.
2. Docstring: already claims comments fire; re-read and adjust wording if the
   implementation notes need it so docstring == code (no behavior text changes).
3. New unit battery `integration/test_copy_language_comments.py` (same importlib
   pattern as `test_copy_language_untracked.py`), cases:
   - whole-line `# 中文注释` under `server/engine/**` fires with file:line named;
   - `x = 1  # 中文` still fires (no regression);
   - whole-line Chinese comment with `# copy-lang-allow:fixture` on itself stays exempt;
   - whole-line Chinese comment with the marker on the line above stays exempt;
   - malformed diff input (truncated hunks, binary-ish bytes as text, lines without
     headers) does not crash and yields no false violation;
   - out-of-scope comment line stays silent.

Verification (this stage + implement stage): `python3 -m pytest
integration/test_copy_language_comments.py integration/test_copy_language_untracked.py -q`;
`python3 integration/lint_tests.py` must stay 0-error on the lane tree.

## B. No shared-tree planting from a concurrently running scenario (executor -0003)

Root cause: `integration/t261004-20/sc_test_anchor_brakes.py` writes
`server/engine/tests/test_zz_t26100420_planted_anchor_case.py` into the shared lane tree
and is registered in the `serial` pool → runs concurrently with other pools; any scenario
running lint in that window sees the probe (and B7 can see other scenarios' probes).

Chosen fix (the spec's sanctioned fallback, one line): move the registry entry for
`t261004-20-test-anchor-brakes` in `integration/run_scenarios.py` from pool `"serial"` to
`"exclusive"` (runs alone, before the pools barrier). This removes both failure faces
(other scenarios seeing the probe; B7 seeing foreign probes) with zero blast radius.

Why not the preferred temp-tree option: the lint battery (`lint_tests.py`) is repo-root
bound in many checks (L1 scans `integration/**`, L2 uses the engine venv, L8 reads
repo-root baselines, L16 reads `integration/test_anchors.json`); a target-root seam
would touch the whole battery for one scenario's benefit. If review insists on the
temp-tree shape, the seam is a `SANDBAR_LINT_REPO_ROOT`-style override and this plan's
step 1 becomes "add seam + point scenario at a tmp copy" — flagged as the review-open
alternative.

Verification: `python3 integration/lint_tests.py` (L4 registry + L5 orphans still clean);
registry diff reviewed by eye. Scenario itself is NOT run in this stage (integration
entries banned in dev stage; the engine integration gate owns it).

## C. Quarantine recovery idempotence (executor -0004)

Root cause: `_recover_quarantined_test_face` (`server/engine/agent_activities.py`) marks
only the manifest item of the batch it consumed. A path quarantined N times has N batches;
each settle restores it from the next unmarked batch, so a deliberate removal is
impossible and a cleaned face re-reds (observed restore→delete→restore loop on
t261004-18).

Change in `server/engine/agent_activities.py`:
1. Processed-path ledger: `<cwd>/.sandbar/quarantine/recovered-paths.json`
   (`{"paths": {<relpath>: {"ticket": ..., "recovered_ts": ms}}}`), written on every
   successful restore. Malformed/unreadable ledger → recovery skipped entirely with a
   named note (fail toward "do not restore" — that respects removals; never a silent
   no-op).
2. Mark across all historical batches: when a path is restored, mark
   `recovered=true/recovered_ts` on **every** manifest item with the same path in every
   `unauth-*/manifest.json` (not just the consumed batch) — the batch-level blindness
   dies even if the ledger is later lost.
3. Ledger check first: a path already in the ledger is never auto-restored again
   (named note per skip). A later quarantine of the same path is a new human face, not
   an automatic restore — this is the "intentional removal is a distinct, explicit
   intent" half.
4. Existing skip faces (unreadable manifest, action != moved, archive missing/dir, path
   occupied) are unchanged and stay named.

Unit battery `server/engine/tests/test_t261004_34_recovery_idempotent.py`, reusing the
`t260916-19` mk_lane / tmp-git fixture pattern of `test_t261004_25_test_face_gate.py`:
- two batches carrying the same quarantined test-face path → one `settle` restores once,
  BOTH manifests end marked, ledger holds the path;
- a second settle performs no restore (no recovery notes appended, archives untouched);
- the lane deliberately deletes the restored file → next settle does not resurrect it;
- malformed manifest keeps its named-skip behavior; malformed ledger skips recovery with
  a named note;
- malformed input discipline: quarantine manifest with junk item shapes (path non-str,
  archive missing, action unknown) → skipped, no crash, no restore.
Verification: `python3 -m pytest server/engine/tests/test_t261004_34_recovery_idempotent.py
server/engine/tests/test_t261004_25_test_face_gate.py -q` (the -25 suite guards against
regression of the original recovery contract); `python3 -m py_compile server/engine/agent_activities.py`;
`python3 integration/lint_tests.py`.

## D. Wiring guard: L1–L18 battery stays wired into the code lane (host order)

New scenario `integration/t261004-34/sc_lint_battery_wired_into_code_lane.py`
(offline, seconds, pool `ro`+`serial`): load `verify.yaml`, assert
`lanes.code.checks` contains an active entry with `id: lint` whose `cmd` invokes
`integration/lint_tests.py`; assert the cmd's script path exists on disk. Missing or
silently commented-out wiring = FAIL naming the lane and the missing id. YAML is parsed
with a real parser (commented-out lines must not pass as "wired"). Register in
`SCENARIOS` + add its anchor entry to `integration/test_anchors.json` (L16), plus an
`engine_tests` entry for the new C battery (L16 covers every engine test file).

Verification: `python3 -m py_compile` the scenario; `python3 integration/lint_tests.py`
(L4/L5/L16 all clean). Scenario execution belongs to the engine integration gate.

## Step order (implement stage)

1. A (lint module + battery) — smallest, unblocks the L15 face other tickets bleed on.
2. C (recovery idempotence + unit battery) — the defect biting -18/-28 today.
3. B (one-line registry move).
4. D (new scenario + registrations + manifest entries).
5. Full affected-face pass: `python3 integration/lint_tests.py`, targeted pytest files
   above; then report.

## Alternatives considered (for review_plan)

- B via temp tree + lint root seam: rejected here — battery-wide seam for one scenario;
  `exclusive` pool is the spec's sanctioned fallback and is behavior-equivalent for the
  failure face. Reversible if review prefers the seam.
- C via batch-marking only (no ledger): rejected — it fixes the observed five-batch loop
  but not "intentional removal" after a future re-quarantine; the ledger is the explicit
  intent record the spec asks for.
- C via content-hash matching instead of path set: rejected — hashes go stale on edits
  and the spec names the processed-path set as acceptable.

## Risks / handover notes

- Ledger skip-on-corruption means a corrupted ledger silently (well: with a named note)
  stops future recoveries — deliberate fail-toward-no-restore; flag for review.
- After B, `t261004-20-test-anchor-brakes` delays the exclusive phase slightly
  (it spawns lint subprocesses several times); acceptable, it already did as `serial`.
- New engine test file and new scenario both need `test_anchors.json` entries or L16
  goes red — included in step 4.
