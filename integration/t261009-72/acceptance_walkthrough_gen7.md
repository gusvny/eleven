# Acceptance walkthrough report — t261009-72 (integration, gen7, post-re-sync round)

**Verdict: OK** — after the human-ordered main re-sync (main@12e33d2 merged, lane HEAD
a2748281), this ticket's fix survives the merge intact, its boot face re-verifies green,
and the host ruling on the T2b blocker is confirmed by this round's receipts. The gate
blocker set shrank from three to one, and the one is another ticket's product red.

## What was verified this round (user view)

### The re-sync preserved the fix — PASS

- HEAD a2748281 (`Merge branch 'main' into lane/t261009-72`) contains main@12e33d29
  (t261009-79). This ticket's seam is intact in the merged tree:
  `lib_fix17.mjs` header invariant + `benchEnv` `delete env.SANDBAR_REPO` (:247) +
  exported `benchRepoPatch` (:273); `run_scenarios.py` still registers
  `t261009-72-bench-boot-anchor` (:134).
- Direct node re-run of the ticket scenario on the merged tree: **9/9 PASS, exit 0**
  (boots with hostile foreign `env SANDBAR_REPO`, engine channel on the fixture stub).

### Host ruling on T2b — confirmed from this round's receipts

Per the host ruling I judged from this round's gate, not from memory:

- `t261008-23-lane-map-v5-proportional` worker handover targeted re-run: **PASS, 20.7 s**
  (out/integration-report-261011-023613.json), zero env-red. The probe now reads SVG
  `stroke-dasharray` geometry (`sc_t26100823_lane_map_v5.mjs:105-106`) — assertion
  semantics unchanged ("a dashed window box"), only the observation face re-anchored to
  the SVG scene; this is contract-precise, not a green shortcut. This also retro-validates
  the gen0-gen5 attribution: the red was "green on main, red in the lane" precisely
  because this ticket's anchoring fix is what lets the lane console load the lane tree's
  product at all.
- Gate blocker list shrank 3 → 1: only `t261009-53-lane-map-slim-pipe` remains
  (P7/P9 product reds, owner ticket t261009-53, ledger 基线定点/歧义). t261009-22 cleared
  with the sync. t261009-53 stays a blocker for its owner after this ticket merges.
- env-reds this round (t261003-13, t261006-03, t261006-12 ×2, t261008-02, +1) are all
  named, supply-side, in-registry — not this ticket's face.

## Test-asset change review (t261009-79's probe edits)

The v5 probe re-anchor and the T5 fix (60-char d slice no longer cuts the closing `Z`)
keep every assertion's meaning; the fixture lookup fix repairs the probe, not the
expectation. No weakening found. This ticket's own test assets are unchanged.

## State to hand over (not mine to touch, per write-set rule)

A NEW main-sync merge is **in progress** in the worktree right now: MERGE_HEAD =
9252c23d (main advanced again), with exactly one unmerged path —
`integration/test_anchors.json` (conflict at :4860-4877 between HEAD's entries, which
include this ticket's scenario entry with filled sync_path, and main's newer entries).
Resolution precedent from gen3 applies: keep BOTH sides' entries (union), keep this
ticket's entry nested under `scenarios{}` with its sync_path. The settle is the
worker's; I did not touch the index. If the settle drops this ticket's entry, the
anchor-presence lint will name it (t261004-25 face).

## 对照证据

| scenario | this round's receipts | targeted / direct re-run | agreement |
|---|---|---|---|
| t261009-72-bench-boot-anchor | PASS (every gate round 1–4; round-8 narrowed set per injection) | this round: 9/9 PASS direct node on merged tree | agree |
| t261008-23-lane-map-v5-proportional | PASS 20.7 s handover receipt (261011-023613) | same receipt (worker-executed) | agree — T2b cleared |
| t261009-22-lane-map-mock-chrome | cleared from blockers post-sync | gen0 FAIL T5 pre-sync (identical then) | consistent with ruling |
| t261009-53-lane-map-slim-pipe | FAIL — sole remaining blocker (owner t261009-53) | gen0 direct FAIL P7/P9 identical | agree |
| t261009-68-lane-map-mount-receipt | PASS 21.3 s (round 3 receipt) | 6/6 PASS direct (gen1) | agree |
| t261004-25-anchor-presence-lint | PASS 68.5 s (round 3) | PASS 65.7 s targeted (gen1 handover) | agree |

## UI 呈现检查项

不适用 — this ticket lands no UI of its own.

## 收口两问

**doc_sediment**: want=true (unchanged across all rounds) — target:
`docs/ops/engine-worker-and-lane-operations.md` (or a short new `docs/reference/` entry),
reason: the anchor-seam invariant ("the bench console owns the lane worktree; a foreign
fixture repo is declared via per-plugin `config.repo`, never via `env SANDBAR_REPO`; the
guard refuses env cross-checkout anchors by design") caused a whole-family 16/16 env_fail
blackout and is the exact trap the next harness author will re-dig. The T2b story adds a
second sediment-worthy fact: a probe pinned to CSS borders went deterministically red on
an SVG scene — "green on main, red in the lane" was the anchoring fix working, not a
regression.

**doc_conflicts**: none — the only docs file actually read across all rounds is
`docs/README.md` (catalogue; no claims to contradict). Refs: docs/README.md.
