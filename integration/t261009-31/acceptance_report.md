# Acceptance walkthrough report — t261009-31 (dismiss a dead ticket, engine half)

Role: integration, stage acceptance_walkthrough (gen0). Lane HEAD at verification: `cad82b6f`
(main@770e9e9 already merged in). Verdict: **pass**.

## What was walked through, from the user's seat

The host asked: a failed ticket must be dismissable by a person, and the dismissal must be a
recorded human decision. This ticket owns the engine half (journal + read faces + CLI ops);
the dwell-rule/UI half is explicitly staged behind the lane-map UI ticket and is **not**
judged here.

Verified end to end through the real public faces:

1. **CLI happy path (real user path, zero fixture)** — `python3 server/tools/ticket.py
   '{"op":"dismiss","id":...,"who":"xihu","reason":"probe refusal human"}'` returned
   `{"ok":true,"dismissed":{at,who,reason,ticket_id},"journal":"<abs path>"}` with exit 0,
   and wrote exactly one row `{at,ticket_id,who,reason,action:"dismiss"}` to
   `server/engine/out/ticket-dismiss.jsonl` (read back from the reader side, per the
   reader-side evidence discipline). **Probe row removed afterwards**; tree left as found
   (the file is gitignored, so git status would not have shown it either way — reader-side
   read-back was the proof, not git).
2. **Human-only gate, live** — same CLI with `who:"developer"` refused by name:
   `who is an agent role name (developer) — only a human can sign a dismissal; an agent may
   not dismiss a ticket it failed`, exit 1, **zero writes**.
3. **Existence gate, live** — dismiss of a nonexistent ticket refused by name
   (`unknown ticket: … not in the engine ticket population`), exit 1, zero writes.
4. **Not a workflow signal** — a successful dismissal produced no workflow write; the
   journal file was the only persisted record; `git status` clean apart from the pre-existing
   test-file comment edit.

## Machine verification (targeted re-runs, gate-compliant)

- `python3 integration/run_scenarios.py --only t261009-31-dismiss-journal-contract`
  → ran=1 pass=1 (0.1s).
- `python3 integration/run_scenarios.py --only t261009-31-dismiss-reader-face`
  → ran=1 pass=1 (0.3s).
- Engine unit layer: `server/engine/.venv/bin/python -m pytest
  tests/test_t261009_31_ticket_dismiss.py -q` → **29 passed**.

## 对照证据 (gate receipt vs targeted re-run, same scenario names)

| scenario | gate receipt (out/integration-report-261009-224923.json) | targeted re-run (this walkthrough) |
|---|---|---|
| t261009-31-dismiss-journal-contract | PASS, 0.1s | PASS, 0.1s |
| t261009-31-dismiss-reader-face | PASS, 0.3s | PASS, 0.3s |

No full-suite run was performed this segment (none needed: no red to reproduce).

## Test asset change review (walkthrough-vs-arbitrate window)

One uncommitted edit in the tree: `integration/t261009-31/sc_t26100931_dismiss_reader_face.py`
line 126 — a **comment only** (`# engine-venv-compat（t260907-10 回落链行，摘除票删旧行）`)
on the venv fallback chain line. No behavioral change; judged contract-annotation, not a
green-light shortcut. Approved.

## Spec-carried-over audit (void face → dismissal)

- Append-only JSONL, malformed file stays appendable (write never reads back): confirmed in
  `ticket_dismiss.append_dismiss_journal` and scenario A/D legs.
- Bad lines skipped but COUNTED: `read_dismiss_journal(with_malformed=True)`.
- Bounds (who ≤ 64, reason ≤ 2000) refused structurally, zero side effects: scenario B
  refusal matrix with dir-digest proof.
- Degradation contract (read failure ⇒ key absent + named `dismissed_note`): present at all
  three augmentation sites in `client.py` (list rows, dev-lane detail, inspection detail).
- Deliberately NOT carried: first-signature-wins (last-row-wins + action decides instead);
  no DONE-family reclassification (`dismissed` is its own key; scenario N leg).
- UI/dwell rule untouched: `isDwellOpen` in
  `server/plugins/workbench/src/client/sandbar-dwell.ts` is unchanged (no diff in tree) —
  matches the dispatch spec's out-of-scope clause.

## 遗留与风险 (leftovers and risks)

- The journal's default home is `server/engine/out/` (gitignored). Per the boundary
  discipline, an ignored write-face needs its own probe: any acceptance of the UI ticket must
  read the journal through `ticket_dismiss.dismiss_journal_path()` / the `journal` field of
  the receipt, never through `git status`.
- The KI-01M4GGFXPAHDGSQ9767VMB5NGM (failed inspection tickets dwell on the left column
  forever) stays OPEN until the staged UI ticket lands the dwell-rule change; this ticket
  only supplies the dismissal mechanism. Consistent with the KI entry as registered.

## Parallel-period UI presentation (并行期 UI 呈现)

**不适用** — this ticket deliberately changes no UI and no dwell rule (dispatch spec: both
belong to the staged UI ticket); there is nothing to screenshot.

## doc_sediment (沉淀一问)

want=false — the mechanism is fully documented in the module docstring of
`server/engine/ticket_dismiss.py` (contract keys, refusal order, why last-row-wins differs
from the void face). No fact here graduates to docs/ until the UI half lands; at that point
the board-face design doc (if any) is the right home, proposed by the UI ticket.

## doc_conflicts (反向同步闸)

No conflicts. Docs actually read this segment: `docs/README.md` (index only — no doc makes
claims about ticket dismissal or the dwell rule that this implementation touches);
`notes/debts/known-issues.md` KI-01M4GGFXPAHDGSQ9767VMB5NGM read and found consistent
(this ticket does not claim to close it).

## Conclusion

Verdict **pass**. Machine gate green on this ticket's own scenarios (gate + targeted
re-run agree), engine unit layer 29/29 green, user-path CLI probes behave as specified
including both named refusals, no workflow writes, UI untouched per spec. Remaining reds in
the gate receipt are the declared environment-red list (17 named, not this ticket's).

---

# Addendum — gen1 walkthrough (lane HEAD 6d39dff9, main@0b09ec7 merged)

Verdict: **pass** (re-affirmed after the gen1 main sync and the arbitrate-stage change).

## What changed since the gen0 walkthrough

Only two deltas touch this ticket's scope, both audited:

1. `integration/t261009-31/sc_t26100931_dismiss_reader_face.py` line 126 — the arbitrate
   stage amended the venv-fallback comment (`t260907-10 回落链行，摘除票移除旧路径`).
   Comment-only, no behavior change: judged contract-annotation, not a green-light shortcut.
2. main@0b09ec7 merge brought unrelated work (t261009-27 outcome faces, executor Overview
   mock notes, one new t261009-27 integration scenario) — nothing in this ticket's write set
   except co-located lines in `run_scenarios.py` (a new t261009-27 entry only; the two
   t261009-31 entries are byte-identical to gen0).

## Re-verification at HEAD 6d39dff9

- Targeted: `--only t261009-31-dismiss-journal-contract` PASS; `--only t261009-31-dismiss-reader-face` PASS.
- Engine UT: `tests/test_t261009_31_ticket_dismiss.py` → 29 passed.
- CLI probes re-run (real path): agent-role who refused by name (exit 1, zero write);
  unknown ticket refused by name (exit 1, zero write); no journal file created by refusal
  paths. No happy-path write performed this round (gen0 already proved it; no state littered).

## 对照证据 (gate receipt vs targeted re-run, gen1)

Gate full-suite receipt: `out/integration-report-261009-231830.json` (507 ran / 487 pass).

| scenario | gate receipt | targeted re-run (gen1) |
|---|---|---|
| t261009-31-dismiss-journal-contract | PASS, 0.1s | PASS, 0.1s |
| t261009-31-dismiss-reader-face | PASS, 0.3s | PASS, 0.3s |

No full-suite run was performed this segment beyond the gate itself.

## Notes

- Remaining gate reds are the declared environment-red list (18 named, none this ticket's);
  no new product red introduced by this ticket.
- doc_sediment / doc_conflicts unchanged from gen0: want=false; no conflicts (docs read:
  docs/README.md; notes/debts/known-issues.md KI-01M4GGFXPAHDGSQ9767VMB5NGM stays open for
  the staged UI ticket). 并行期 UI 呈现: 不适用 (no UI in this ticket by spec).
