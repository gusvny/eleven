# t261002-11 KI-191 Acceptance Walkthrough (integration, gen0)

Verdict: **OK (green after a targeted L3 harness repair — full attribution below)**.
The mechanical gate blocked `t261002-11-ki191-fixture-period-isolation`; targeted
reproduction confirmed a scenario-harness fault (not a product fault), the L3 asset was
repaired in place, and the scenario is now 26/26 green alongside the L1 battery (51 passed).

## 1. Per-acceptance-item walkthrough (user view)

| # | Acceptance | Verdict | Evidence |
|---|---|---|---|
| 1 | After a fixture fast-forward run, the next real schedule fire mints a real ticket (fixture mark is not dedupable) | **PASS** | L3 section A: fixture-marked open mints `t261002-01`; real (unmarked) open on the same (instance, period) returns `deduped=False` with a NEW id `t261002-02 ≠ t261002-01`. Fixture occupier recorded in receipt `skipped_fixture_tickets`. Same-mark fixture fire still dedups normally; fixture fire onto an unmarked real ticket = named fail-closed error (`fixture mark ownership check failed`, names both marks). |
| 2 | Fixture teardown releases the period slot (no leftover squatting) | **PASS** | L3 section B: `release_period_slot` happy path cancels the marked live ticket (status=CANCELED), returns `released=[t261002-01], pointer_cleared=True`, slot face flips to `freed`/empty; double-clean, wrong-mark, and missing-mark all fail with named errors (`double-clean check failed` / `mark ownership mismatch check failed` / `fixture mark missing check failed`) — never bare booleans. |
| 3 | Dedup receipt names the deduped ticket id and slot-taken time | **PASS** | Root cause of `ticket=?` was reading key `ticket` instead of `ticket_id` in `inspection_flow` spawn note — fixed to read `ticket_id` plus `slot_taken_at` (honest `unknown` for stampless legacy tickets, never fabricated) and `fixture=`. Source-lock asserts in L3 section D; runtime receipt face asserted in L1. |
| 4 | "Who occupies the period slot" is queryable, not just a boolean | **PASS** | New public face `describe_period_slot` + CLI `inspection_trigger.py slot`: returns `slot_state / ticket_id / status / fixture_mark / slot_taken_at / all_tickets`. Legacy stampless occupier honestly reports empty mark + `slot_taken_at=unknown` (no fabrication); empty slot explicit `empty`. |
| (spec) | L3 regression scenario green and registered | **PASS after repair** | Registered as `t261002-11-ki191-fixture-period-isolation` in `integration/run_scenarios.py` with intent clause; targeted rerun `RESULT: PASS pass=26 fail=0 env_fail=0`. |

## 2. Test-asset change review (mandated section)

Two uncommitted modifications were present in the working tree when this walkthrough
started (mtime 2026-10-02 23:08, after the implement commit `0a50f0c` at 22:52;
provenance = the design_integration_tests stage handoff, whose report describes exactly
these contract-alignment edits):

1. `integration/run_scenarios.py` — scenario entry cmd switched to the engine-venv
   fallback chain (`open_period_ticket` internally imports `inspection_flow → temporalio`;
   bare python3 = environment red, not scenario red). Intent: environment-robustness,
   **not** a green-light shortcut. Accepted.
2. `integration/t261002-11/sc_ki191_fixture_period_isolation.py` — `release_slot` helper
   gained the `SANDBAR_INSPECTION_DIR` injection chain + `pointer_cleared=True` assertion;
   section-A assertion order adjusted. Intent: contract precision (asserts the exact face
   acceptance item 2 demands). Accepted.

My own change during this walkthrough: my first targeted run crashed in section B
(see §3); I had drafted a parallel fix of the same helper before discovering the
design-stage final version had landed concurrently in the working tree. I removed my
duplicated (shadowed) definition and kept the file's own version — net scenario content
is the design-stage final version; no assertion was weakened anywhere.

## 3. Defect found, attribution, and resolution (integration-layer finding)

- Symptom: first targeted run of the L3 scenario crashed in section B —
  `open_period_ticket` after teardown raised 「去重指针在飞行窗内且票不可见（…/ledgerB/
  inspection-integration-tests-20261002.ticket → t261002-01，年龄 0s≤120.0s）」.
- Attribution: the walkthrough-time scenario helper `release_slot(client, **kw)` did NOT
  set `SANDBAR_INSPECTION_DIR` around the release call (while `open_ticket` did), so
  `release_period_slot` resolved the pointer directory to the engine default
  (`server/engine/out/inspection`), cleared nothing at the real path, and left the real
  flight pointer behind — silently (`pointer_cleared=False` was returned but never
  asserted). The leftover pointer then fail-closed the next same-ledger open. Location:
  `integration/t261002-11/sc_ki191_fixture_period_isolation.py` helper (test harness),
  not `server/engine/inspection_ticketing.py` (product) — production callers resolve the
  same env var at both ends, and the L1 battery locks the same-default invariant
  (inspection_ticketing.py comment 「锁两处逐字一致…同口径由单测锁」).
- Note for the record (not a defect): `release_period_slot` resolving the ledger dir from
  ambient env at call time means a caller whose env snapshot differs from the claim-time
  snapshot half-cleans (clears the wrong directory) and only a `pointer_cleared=False`
  receipt betrays it. The L3 scenario now asserts `pointer_cleared=True` explicitly, which
  is the right gray-box guard. If a future caller passes an explicit dir to open but not
  to release, this resurfaces — flagged as an observation only.

## 4. Input-checks sweep (dispatch spec)

Every new surface fails with a named check, never a bare boolean: malformed period →
`period shape check` (`ticket_prefix_from_period` closed check) in slot/release;
missing fixture mark on release → `fixture mark missing check`; double clean →
`double-clean check failed…已释放` (does not fake a second success); ownership →
`mark ownership mismatch check failed` / `fixture mark ownership check failed` (both SA
layer and pointer layer, and pointer-vs-SA contradiction fail-closed with both facts
named). Transient describe indeterminacy stays fail-closed (不猜) at every new consumer.

## 5. Borrowed-implementation discipline (dispatch spec)

The dedup inherits SA-path semantics (`dedup_source sa_query|pointer|already_started`).
Carried over unchanged: SA-hit → describe verification before verdict; terminated-ticket
auto-reopen; live/served dedup; pointer three-state (claimed/exists/malformed/stale);
indeterminate describe = fail-closed transient, never guessed; `already_started`
concurrency window still clears its self-built pointer and yields. Not carried (KI-191
change): fixture-marked tickets are filtered out of every verdict set BEFORE the slot
verdict, so a real fire can never dedup onto them; the pointer layer gains a matching
ownership check (fixture flight lock is not a real fire's lock — cleared with an audit
line, re-mint). Both layers preserve the existing receipt shapes for unmarked callers
(空 mark = byte-identical semantics plus the new additive keys).

## 6. Contrast evidence (t260924-09 discipline)

- Scope: targeted reruns only; no full-suite run was performed in this segment (0/1
  budget used). Gate same-caliber rerun not needed since the only gate-named blocker was
  this scenario.
- Gate receipt: `t261002-11-ki191-fixture-period-isolation` = gate-blocked (exit≠0;
  per-scenario wall time not exposed in the injected gate evidence — honestly annotated,
  no cross-scenario number substituted).
- Targeted reruns (this segment, same scenario name): pre-repair run = crashed at 0.212s
  wall (exit 1, section B); post-repair run = `RESULT: PASS pass=26 fail=0 env_fail=0`,
  ~0.2s wall. L1: `pytest server/engine/tests/test_t261002_11_ki191_fixture_dedup.py
  test_t260916_02*` → 51 passed in 0.46s.
- Handover command for merge executor re-gate (lane root):
  `python3 integration/run_scenarios.py --only t261002-11-ki191-fixture-period-isolation`

## 7. Residual risks / for the merge executor

1. The mechanical gate blocked exactly this scenario (闸拦 receipt, 归属置信=ok); it is
   now green locally. The injected mechanical report also counted 「2 败」 without naming
   them; only this scenario is attributable from the evidence at hand. Recommend the
   merge gate re-run the same-caliber suite (`--exclude-pools engine,exclusive`) after
   the worker lands these working-tree changes as a commit.
2. Working-tree-only changes exist beyond the implement commit (§2 items 1–2). The worker
   will deterministically commit them; merge must review that commit contains exactly
   those two files.
3. Fixtures that historically ran the real flow WITHOUT a mark (the t260926 batch that
   caused the incident) are not visible in this repo's current integration assets — the
   discipline (always pass `--fixture-mark`, always release) is enforced by mechanism +
   this L3 scenario, but fixture-author hygiene is a standing convention, not a static
   guarantee. Registered as sediment candidate (§8).

## 8. Closing questions (留痕, non-blocking)

- doc_sediment: want=true — candidate target: `docs/design/` inspection design doc (or a
  short fixture-discipline note in `docs/testing-guide.md`); reason: the mechanism now
  requires every real-flow fixture to (a) pass a fixture mark and (b) release its period
  slot in teardown — that is an authoring contract for future fixture writers, currently
  documented only in code docstrings and the KI entry; one paragraph in the testing guide
  would prevent the next squatter.
- doc_conflicts: 1 item — doc=`docs/design/inspection-produce-face-extension.md` (line 52)
  and `docs/design/sandbar-project-onboarding-contract-v1.md` (v2.5 row): claim = "one
  ticket per period … deduplicated by (instance, period number)"; actual = dedup is now
  mark-aware (fixture-marked tickets are non-dedupable occupants for real fires; release
  face exists). Not a contradiction of intent (fixtures are not the real schedule), but
  the unconditional "(instance, period)" wording should gain the fixture-mark carve-out.
- UI/泳道图 rendering: 不适用 — this ticket touches no UI/lane-map rendering surface.

## 9. Docs read (结算 note 参考)

notes/debts/known-issues.md (KI-191 entry); docs/design/inspection-produce-face-extension.md
(dedup claims, grep-level); docs/design/sandbar-project-onboarding-contract-v1.md (v2.5
inspection row, grep-level); docs/README.md (directory).
