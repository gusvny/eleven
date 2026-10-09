# t261009-39 — acceptance walkthrough (integration, gen0)

## Verdict: pass

## What was walked

The ticket asked three things: settle (a)/(b)/(c) on evidence, act on the
answer, leave both faces green. Walked from the user side, independently of
the machine gate receipt.

1. **The ruling is evidence-correct.** Re-ran the generator's own check on
   this worktree (HEAD=5a001326, `server/workflows` byte-identical to
   main@ff068ff7 — `git diff ff068ff7 HEAD -- server/workflows` empty):
   `check 绿：yaml 与代码一致且过 workflow.py 校验`, exit 0. The implement
   stage's ruling stands: **(b) is the true mechanism** (yaml is generator
   output from `<Class>.STAGES`), each tree is green against its own code,
   main's regeneration is a **no-op**, and landing the lane's English yaml
   here without the lane's anglicized engine code would turn main's own
   check red — `server/workflows/` untouched is the lawful landing, not an
   under-delivery. The English artefacts reach main as one unit when
   t261008-47 merges (binding merge-gate watch item, recorded in
   `yaml-verdict.md`).
2. **The lane's revert patch** `integration/t261008-47/yaml-revert-to-main.patch`
   is no longer applicable and no longer needed — applying it would re-open
   the settled copy decision and redden the lane's own check (ticket point 4).
3. **The regression pin is real, not a green-light shortcut.** Both new test
   assets assert the public contract only: generator exit codes, named drift
   files, byte equality between a fresh generation and the committed
   snapshots. No internal names, no incidental ordering, no weakening found.

### Test asset change review (mandatory section)

Both assets are new this ticket; no pre-existing test was touched
(`git status --short` on HEAD shows only additions plus the pre-seeded
`integration/run_scenarios.py` registration).

- `server/engine/tests/test_t261009_39_yaml_follows_code.py` (4 tests): check
  green on committed tree; regen-in-temp-copy byte-matches both snapshots
  (the mechanical "content follows code" assertion the ticket's point 5
  requires); drift injection (append / truncate) makes `--check` exit 1 and
  name `dev-lane` — failing for the right reason, not an import crash.
  Subprocess hardened (`cwd=` pinned, timeout, tmp_path teardown).
- `integration/t261009-39/sc_t261009_39_yaml_follows_code.py`: same intent at
  L2, plus the read-only-real-tree check (C) and an explicit three-state
  contract (missing venv / unimportable temporalio = exit 2 ENV_FAIL, never a
  silent green). Declared intent split vs `t23-yaml-chain-truth` is sound:
  that scenario owns the real-tree green + chain order; this owns idempotent
  regeneration + inject/repair — no intent-level duplication.

Verdict: contract precision, no green-light shortcut.

### Scenario conclusions (walkthrough evidence)

- `t26100939-yaml-follows-code` — **pass**. Targeted rerun this session:
  `python3 integration/run_scenarios.py --only t26100939-yaml-follows-code`
  → `ran=1 pass=1 fail=0`, scenario `dur_s: 1.889`, all A/B/C assertions ok
  (report: `out/integration-report-261010-014752.json`).
- New unit test file: `4 passed in 1.70s` (`pytest ...test_t261009_39_yaml_follows_code.py -q`).
- Generator check on worktree: green, exit 0 (verbatim above); worktree
  `server/workflows` unchanged vs main.
- Gate receipt (this round, injected): 511 ran / 491 pass / 4 product red /
  16 env red; main-sync `main@ff068ff already up to date (fast path)`. The 4
  product reds are the ledger's 命中红 line — browser/capture scenarios
  (`t261005-16-capture-fresh-home-journey`, `t261006-02-capture-auth-surface-real-stage`,
  `t261006-03-engine-path-capture-journey`, `t261008-36-panel-settings-faces-merge`) —
  none touches this ticket's face (generated yaml, engine tests). The
  itemized per-scenario list was truncated in the injected context, so the
  gate-side timing for `t26100939-yaml-follows-code` specifically is **not
  verifiable from my context** (缺数据面, stated honestly); the targeted
  rerun above is the authoritative local evidence.

### 对照证据 (gate vs targeted rerun)

| scenario | gate receipt timing | targeted rerun (this session) |
|---|---|---|
| t26100939-yaml-follows-code | not itemized in injected context (receipt truncated) — 移交命令 `python3 integration/run_scenarios.py --only t26100939-yaml-follows-code` | PASS, 1.889s (`out/integration-report-261010-014752.json`) |

### Parallel-period UI presentation

不适用 — this ticket changes no UI; write set is generated yaml, engine tests,
integration entries only.

## Leftovers and risks

- The invariant "engine copy + generated yaml land as one commit" binds the
  t261008-47 → main merge; enforcement belongs to that ticket / merge gate.
- `yaml-revert-to-main.patch` should be discarded by t261008-47 (outside this
  ticket's write set).

## doc_sediment / doc_conflicts

- **doc_sediment**: `want=false` — no docs/ design doc governs
  `gen_workflows_doc.py`; its contract lives in its own module docstring, and
  the settled ruling is recorded in the ticket's own artifacts
  (`yaml-verdict.md`). Nothing here generalizes beyond the ticket.
- **doc_conflicts**: none found — only doc read this ticket is
  `docs/README.md` (catalogue scan, earlier stages); no docs/ claim about the
  workflow yaml or the generator exists to be contradicted.

## References (docs read)

- docs/README.md (catalogue scan, earlier stages; no governing design doc)
- 仓库根 CLAUDE.md（只读）
