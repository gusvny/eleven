# t261030-25 — the fixture that wrote production state (KI-429)

English, developer report. Every number below was measured on 2026-10-30 in this
lane; the commands that produced them are named next to them.

## 1. The writer, named by a content-hash bisect

**Named writer:**
`integration/tests/test_t261011_26_round_face.py::RoundFaceEndToEnd::test_unresolvable_face_dir_degrades_honest`
(and the same test as INHERITED by `class TruthfulTerminalFace(RoundFaceEndToEnd)`,
which is why every invocation left a PAIR of directories, 1-7 s apart).

What it did:

- its `StubTree.env()` pinned the face dir and the run root but NOT the projects
  root, so `SANDBAR_PROJECTS_DIR` was unset for the round it started;
- its `test_unresolvable_face_dir_degrades_honest` leg then CLEARS the face-dir
  override (`FACE_DIR_ENV: ""`), which sends the runner down
  `resolve_face_dir()`'s fallback — "the project whose ledger the run row lands
  in" — that project is the REAL one;
- so the round published a real `run-*` directory into
  `~/.sandbar/projects/sandbar/data/develop/rounds/`, with a revision from the
  fixture's throw-away git repo (not an object in this repo), and persisted its
  run row into the REAL `ledger/scenario-runs.jsonl`;
- the tick-entry reconciliation (`develop_certify.reconcile_unrecorded_rounds`)
  then booked those rows: 50 delivery-ledger rows at one instant (41
  certifications + 9 freeze episodes, seq 751-800, all stamped
  `at=1793332801440` = 12:00:01) and the develop-buffer line was frozen.

Why the earlier hunt missed it (the lesson KI-429 records): the predecessor
measured the rounds directory by COUNT (11 -> 11). The round face keeps a
ROLLING WINDOW, so the leak ADDS its own directory and PRUNES an old one in the
same run: the count does not move, the content does. Measured, same candidate,
count-based vs content-based:

```
$ git cat-file -t 4a994ea9        # the incident revision
fatal: Not a valid object name 4a994ea9

# bisect harness, one candidate, before/after content hashes of the real root:
[attempt 1] test_t261011_26_round_face.py::RoundFaceEndToEnd::test_unresolvable_face_dir_degrades_honest
  before=4a84a4b015057131 after=b57b7b99246460bd DIRTY
  CHANGED added=2 [data/develop/rounds/run-01M65HYBH3PQR4ZWH1081DMN0N,
                   data/develop/rounds/run-01M65HYBVQQNJG88VPDEZGDNNR]
          removed=2 [data/develop/rounds/run-01M65BKP1VX1930HPMJ20W4BCT,
                     data/develop/rounds/run-01M65BKWPQY9J8466G6M76HWZ4]
          changed=1 [ledger/scenario-runs.jsonl]
```

The two new directories reproduce the incident exactly:

```
{"counts": {"env_fail": 0, "fail": 0, "pass": 1, "ran": 1},
 "last_scenario": {"name": "sc_0", "verdict": "PASS"},
 "revision": {"src": "b69221d7077fc8c518625c3684a126be66f0e00e"},
 "state": "done", ...}
PASS [sc_0] (0.1s)
INTEG_SUMMARY {"ran": 1, "run_id": "run-01M65HYBH3PQR4ZWH1081DMN0N"}
```

`{"repo": "src"}` is the fixture repo name and `sc_0` its stub case name — the
same fingerprint as the six directories in the incident.

### The harness (committed)

- `integration/t261030-25/lib_real_root_watch.py` — content snapshot of a
  projects root: sha256 for the rounds tree, the delivery ledger, the
  guard/pointer files and the runs store; directories are markers (an empty
  added directory is still a change); two oversized append-only ledgers
  (`events.jsonl`, `scenario-results.jsonl`) are witnessed by size+mtime_ns
  (declared trade-off, not silent).
- `integration/t261030-25/bisect_real_root_writer.py` — runs candidates
  (`--from-registry`, `--candidates FILE`, `--mode one|sweep|bisect`) and
  reports `before=<hash> after=<hash> CLEAN|DIRTY` with the changed paths.
  Group bisection over `integration/run_scenarios.py`'s own registry, so the
  candidate universe is what a round actually runs.
- The bisect itself ran in a detached git worktree of this repo
  (`/tmp/sb-bisect-wt`), so the hunt could not dirty the checkout under test.

### Correction after the first pass: the harness is DECOY-FIRST

The first pass measured the REAL projects root in place. That was the wrong
instrument placement: some candidates leak run rows while being measured, so the
hunt itself fed the production runs store (82 rows), and the LIVE worker — still
running code that predated the reachability net — healed them at 13:00:02 into
15 fabricated certifications and 3 freezes (seq 803-821; seq 813 is the honest
34f639ac round and is not part of the pollution). The harness now runs every
candidate under a throwaway `HOME` whose projects root is a MIRROR of the real
one and watches THAT; the real root is a read-only guard that reports
`ESCAPE::DIRTY` if a candidate hardcodes a production path. `--no-decoy` needs
`--i-know-this-writes-production`.

Re-confirmed with the corrected harness (pre-fix sources restored in the scratch
worktree, decoy mode):

```
[attempt 1] PRE-FIX test_t261011_26_round_face.py -k unresolvable (decoy mode)
  before=4676f6de2e0c3c08 after=f4ffc0dd38534f1b DIRTY
  CHANGED added=2 [data/develop/rounds/run-01M65K8PX7A0YT0M8VBC2081R7,
                   data/develop/rounds/run-01M65K8Q9FHMHFCGSEWGWAYRCW]
          changed=1 [ledger/scenario-runs.jsonl]      <-- the DECOY root
(NO ESCAPE line: the real root was byte-unchanged)

# fixed sources:
[attempt 1] AFTER-FIX integration/tests/test_t261011_26_round_face.py (whole file)
  before=f5f9011ac118169b after=f5f9011ac118169b CLEAN
```

## 2. Isolation: the fixture owns a projects root and asserts the real one

Changes:

- `integration/tests/test_t261011_26_round_face.py` — `StubTree.env()` now pins
  `SANDBAR_PROJECTS_DIR` to the fixture's own temp root; `setUp` snapshots the
  real root and `tearDown` asserts it is BYTE-UNCHANGED for every test in the
  class (added, removed and changed all empty).
- `integration/scenario_ledger.py` — `ledger_dir()` now honours
  `SANDBAR_PROJECTS_DIR` between the explicit override and the hardcoded
  production path, so "the fixture owns a projects root" holds for the runs
  store too (unset = byte-identical production behaviour).
- `integration/line_round_runner.py` — `_choose_project()` answers from the
  caller's stated seams (`SANDBAR_SCENARIO_LEDGER_DIR`, then the face dir)
  before it ever scans the projects root. This is what makes the WHOLE family
  clean, not just the incident's fixture: seven other line-round fixtures were
  still booking run rows into the production runs store, and all of them now
  write nothing (see the sweep below).

Evidence (real root, before/after content hashes):

```
# after the fix, the incident's battery, all 51 tests:
[attempt 1] AFTER-FIX integration/tests/test_t261011_26_round_face.py (whole file, 51 tests)
  before=b57b7b99246460bd after=b57b7b99246460bd CLEAN
NAMED WRITERS: none

# the eight line-round candidates that used to write the production runs store:
[attempt 1] t261011-21-clone-assets-line-round   ... before=780a1af03f278a0b after=780a1af03f278a0b CLEAN
[attempt 2] t261011-26-round-progress-face       ... CLEAN
[attempt 3] t261011-26-round-evidence-kept       ... CLEAN
[attempt 4] t261012-06-rounds-window             ... CLEAN
[attempt 5] t261012-01-round-face-truth          ... CLEAN
[attempt 6] t261009-77-line-round-runner         ... CLEAN
[attempt 7] t261011-18-line-round-assets         ... CLEAN
[attempt 8] t261009-46-optin-landing-journey     ... CLEAN
NAMED WRITERS: none
```

Mutation proof (the pin removed in a scratch copy of the fixture — the
assertion must bite):

```
# mutation applied to /tmp/sb-bisect-wt: `lrf.PROJECTS_DIR_ENV` pin deleted
[attempt 1] MUTATION (pin removed) ...test_unresolvable_face_dir_degrades_honest
  before=b57b7b99246460bd after=dfeb06418dc7e631 DIRTY
  CHANGED added=2 [data/develop/rounds/run-01M65J3GQWWXHCBRA7DDRYFRV5,
                   data/develop/rounds/run-01M65J3H61RTJKQT5EHJWFVQBY]
          removed=2 [...] changed=1 [ledger/scenario-runs.jsonl]
# and the fixture's own assertion fired:
AssertionError: this fixture wrote the REAL projects root
  (/Users/user/.sandbar/projects/sandbar): CHANGED added=2 [...]; changed=1 [...]
```

Battery: `integration/tests/test_t261030_real_root_isolation.py` — I1 a staged
round writes neither its own root nor the real one; I2 the same round with the
seam removed DOES write (proved against a decoy `$HOME`, so a test never
demonstrates a leak by leaking into production).

## 3. Ledger-side safety net: no certification and no freeze over an unreachable revision

SCOPE (decided after measuring the blast radius): the net sits on the
RECONCILIATION path — the path that mints a certification from a run ROW the
engine never drove, which is exactly how production state was fabricated. The
settle path needs no second net, structurally: it hands the candidate to the
round's own runner, which CHECKS OUT that revision in a tree of its own, so an
unreachable revision dies there as a named could-not-run (no header, no
certification). Measured why the split matters: a settle-path net refused 37
existing batteries whose records deliberately carry synthetic revision labels
(test_t261016_01, t261026_19, t261024_30, t261009_30/50/59, t261024_70,
t261025_11) — the same batteries that pin the chain, the freeze ladder and the
tick triggers. One test was updated rather than scoped away because its premise
IS the new contract: `test_t261025_11_one_record_reconcile.py::test_t1_...` now
heals a witness run that cites a REAL commit in an injected line worktree.

`server/engine/develop_certify.py`:

- `line_repo_dir(project, repo)` — the tree a line's repository is judged in
  (`<develop_dir>/wt/<repo>`, the same path `line_head_candidate` reads).
- `revision_reachable(repo_dir, revision)` — `git cat-file -e <rev>^{commit}`,
  fail-closed on every failure (absent tree, spawn error, timeout, non-zero).
- `unreachable_candidates(candidate_repos, project)` — named list
  (`revision_not_a_git_object` / `repo_not_resolvable` / `candidate_malformed`),
  every member judged, none skipped.
- `unreachable_refusal(blocked, caller)` — one wording, both call sites:
  `certification_refused:<why>:<repo>@<revision>:caller=<caller>`.
- The RECONCILIATION path refuses by name, mints no certification and no
  freeze, and records ONE `range_growth` row
  (`unrecorded_round_refused:certification_refused:...`) so the next tick does
  not replay the same refusal forever.

Mutation proof (fabricated candidate; live data, copies of the real ledger):

```
# reconcile over today's real runs store, project=sandbar:
entries: 16 Counter({'error': 15, 'reconciled': 1})
  "error": "certification_refused:repo_not_resolvable:src@01035295881554b0dd5085949b54f00f66f7bdbf:caller=reconciled:run-01M65G2R7PQCWEAY71424768B7"
  "error": "certification_refused:repo_not_resolvable:src@58bfa7bd4eca5911acc12d429505053c8706ccc3:caller=reconciled:run-01M65G2X7X03NFXHQZXQB71TN1"
ledger kinds after: 327 certifications  (unchanged: no new certification)
```

Teeth unchanged, measured live: seq 802 of the real delivery ledger is the
certification the dispatcher minted for the real round
(`run-01M65GQ2Y4AF7JTCCVYRKN9C7B`, revision `c3678c32`, 693/693 green) — a real
green round still certifies. A real red still freezes:
`server/engine/tests/test_t261030_ledger_isolation_guard.py::test_r3_a_real_red_round_still_freezes`.

Battery: `server/engine/tests/test_t261030_ledger_isolation_guard.py` (16 tests,
the ticket's declared evidence). Full engine battery:
`6449 passed, 4 warnings in 570.96s` (`python -m pytest server/engine/tests -q`)
— the four warnings are the pre-existing `production_snapshot` mark notices.

## 4. Disposition of the fabricated artifacts

**Run directories: DELETED from the live face, evidence committed.**
`integration/t261030-25/fabricated-rounds-261030-25.json` holds every removed
directory's `run_id`, revision set, full `face.json` and `suite.log`; the tool
that produced it (`rounds_disposition.py`) classifies by reachability and only
ever deletes directories whose every cited revision is not a commit object in
this repo. Reasons: the rounds face is the operator's live view ("how is the
line doing") and a fabricated green round there is a readable lie; the face's
own rolling retention prunes by age anyway, so deleting is what retention would
have done — now with the evidence kept in the repo and the reason recorded.
Eight directories existed at disposition time (four of the incident's original
eight had already been pruned by the reproduction runs themselves; the tool's
manifest plus this report name them):

| run id | revision (not an object here) |
| --- | --- |
| run-01M65CXM3HH9QV2VF0BFBBF96T | src@55401dee |
| run-01M65CXTPHMG7KD0KPE2BS5VG0 | src@4a994ea9 |
| run-01M65G2X7X03NFXHQZXQB71TN1 | src@58bfa7bd |
| run-01M65G33NS9379PSFM28EBAJED | src@6f3b43d0 |
| run-01M65HYBH3PQR4ZWH1081DMN0N | src@b69221d7 (reproduced by this hunt) |
| run-01M65HYBVQQNJG88VPDEZGDNNR | src@c683e538 (reproduced by this hunt) |
| run-01M65J3GQWWXHCBRA7DDRYFRV5 | src@382cd8eb (mutation proof) |
| run-01M65J3H61RTJKQT5EHJWFVQBY | src@f58ac57d (mutation proof) |

Pruned before disposition by the reproduction runs (recorded from their
`face.json` before deletion): `run-01M65BKP1VX1930HPMJ20W4BCT` (src@56b4b853),
`run-01M65BKWPQY9J8466G6M76HWZ4` (src@b7d3030a),
`run-01M65C4BD9MP2M6KHJ02JEZYPV` (src@362f598d),
`run-01M65C4HSPKXPRY9MMQM7HPZ63` (src@c99d3815).

**Delivery-ledger rows: KEPT (append-only) — decided by integration, and the
13:00:02 burst is disposed of the same way.** The burst is 50 rows at
`at=1793332801440` — 41 `certification` rows and 9 `freeze` rows, seq 751-800.
The ledger is immutable by design (a fact is never edited; a correction is
another row), and the false freeze was already released with a named
`freeze_change` row at seq 801. Deleting those rows would be rewriting
history, and it would also throw away the record of what the reconciliation did
— the reachability net is what prevents a repeat, not a silent edit. A
disposition note is carried in this report and in the handoff note for the KI.

**13:00:02 burst (seq 803-821): recorded, not rewritten.** 16 certifications +
3 freezes were healed by the live worker's then-stale code from run rows this
hunt had left behind. Disposition (integration's decision, append-only): the
two still-open false freezes were closed and one note row records the burst,
with seq 813 explicitly excepted as the honest `34f639ac` 690/690 round:

| seq | row | what it says |
| --- | --- | --- |
| 823 | `freeze_change` closed `frz-...Q9T` | cause cites `src@0103529588`, not a git object here |
| 824 | `freeze_change` closed `frz-...Q9Y` | cause cites `src@aaad61c8`, same fixture pollution |
| 825 | `range_growth` note | the whole 803-821 burst is fixture pollution, seq 813 excepted |

**Runs-store rows: my 82 rows REMOVED, with a backup and a manifest.**
`scenario-runs.jsonl.bak-t261030-25` is the unedited backup;
`integration/t261030-25/removed-runs-store-rows-261030-25.json` lists every
removed row (id, source, timestamps, repos, cases, verdict). Every removed row
was created by this hunt between 04:45 and 05:00Z, and every removed row's
revisions are not git objects here. Nothing cited them, and the reference set
was re-checked afterwards: zero uncited `lane:line-round` rows remain, so the
reconciliation has nothing left to heal. Rows the FIXTURES wrote earlier
(the incident's own 19 uncited rows) were consumed by the 13:00 heal and are
therefore now cited by the recorded burst — they were left in place.

## 5. Verification runs (decoy mode unless stated)

| run | result |
| --- | --- |
| full engine battery | `6449 passed, 4 warnings in 570.96s` |
| `pytest integration/tests/test_t261011_26_round_face.py test_t261009_77_line_round_runner.py test_t261030_real_root_isolation.py` under the decoy harness | `69 passed`, DECOY CLEAN, no ESCAPE |
| every integration battery touching the changed modules (16 files) under the decoy harness | `320 passed`, no ESCAPE (one decoy-only `project.yaml` write, i.e. the decoy absorbed it) |
| `integration/lint_tests.py` | `0 error / 0 warn` |
| `integration/lint_copy_language.py` | `0 violation(s)` |
| `integration/ki_ledger.py --check` | `ki ledger clean: 426 records` |
| delivery / runs ledgers | `delivery.jsonl parses, 825 rows`; `scenario-runs.jsonl parses, 7128 rows` |

## 6. What is NOT determined

- Whether the OTHER half of the incident's pair (the two directories at
  12:11, `src@58bfa7bd` / `src@6f3b43d0`) came from the same test file in a
  second battery invocation or from a second fixture: no byte-level writer id
  is recorded in `face.json` beyond `writer_pid`. Both were removed and the
  class is closed at the seam (all eight line-round candidates now measure
  clean), so this is a bookkeeping gap, not an open leak.
- The pre-existing `events.jsonl` write by
  `t261009-46-optin-landing-journey` seen in the first sweep did not reproduce
  in the two later sweeps; it is named here rather than claimed either way.
