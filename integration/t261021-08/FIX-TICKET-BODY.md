# FIX TICKET BODY — ready to open (follow-up to t261021-08)

This file IS the body of the follow-up ticket `t261021-08-fix` (plan gen3,
review gen3 pass, authority option (b)). The host opens the ticket with:

- title: `Executor request layer: one card per condition at the write path (t261021-08 fix)`
- write_set: `server/engine/`, `server/plugins/executor-panel/`, `integration/`
- everything below goes into the ticket body verbatim.

---

## Body

The executor request inbox is half noise (t261021-08 measured: 6 run-silent
cards for one identical condition, elided ticket ids, why-questions, no-op
re-check defaults, null `expires_at` on every row, 18 cross-role notices in
the host ledger, 35 unfoldered correction rows). The detect estate is
gate-green (`integration/t261021-08/`); the enforcement it specifies is NOT
landed yet. This ticket lands it at the write path.

Design authority: `docs/design/executor-operational-envelope-v1.md` §3
(a request carries `audience` and, when the records can settle it,
`resolves_when`). Convergence representation: APPEND-FOLDED — the head row is
never rewritten (`request_thread._locked_append` is an append-only lock with
no read-modify-write recovery). Spec source:
`integration/t261021-08/HANDOFF-request-layer-fix.md`; executable spec:
`integration/t261021-08/lib_request_contract.py` (port verbatim).

### Required behaviour (enforced at the write path, not by prompt discipline)
1. Condition identity: `condition_key` = kind:project:line/ticket:cause,
   normalized, never a round id or per-instance value; a same-key re-file
   while open appends ONE `request-update` row (count/last_seen), never a new
   head; re-raise only after the kind's re-raise age or a host dismissal
   (KI-C).
2. Self-contained question: full ticket id, line, stage, decision (yes/no or
   named options); missing any ⇒ refusal listing every missing item.
3. Default action: concrete `{action, after_ms}` or `{hold: true}`; a no-op
   re-check default is refused by name (`no-op-recheck`).
4. Audience routing: `role:<x>` rows go to `requests-<role>.jsonl`, never the
   host ledger; only host-audience decisions/blockers/authorizations/judgement
   calls reach it.
5. Convergence: `resolves_when` (existing sweep family + new
   `green_row_for_round`) flips the card to resolved without a host dismissal.
6. Expiry: every new card carries `expires_at` (kind TTL when omitted); the
   sweep appends `expired` state rows (`by:"engine:request-sweep"`); expired
   cards leave the open list and are COUNTED in the digest, never dropped.
7. Cap and digest: above `SANDBAR_REQUESTS_OPEN_CAP` (default 20), one digest
   card lists folded cards with ages and which carry a default; folded heads
   are marked `folded_into`.
8. Backward compatibility: legacy rows (no condition key, no expiry) are
   legal history; readers classify them `legacy`, never crash, never rewrite.

### Changed files
1. `server/engine/request_contract.py` (NEW) — verbatim port of the contract
   lib validators + `fold_updates`; stdlib-only, engine-import-light.
2. `server/engine/executor_requests.py` — validators after identity gates,
   before ANY write (named refusals: `condition_key`, `self_contained`,
   `default_action`, `audience`); expiry stamp; same-key update row under
   `request_thread._locked_append`; role-surface routing.
3. `server/engine/shared.py` — role-surface path helper +
   `SANDBAR_REQUESTS_OPEN_CAP` reader (malformed override keeps the default
   and says so).
4. `server/engine/run_watch.py` — dedupe `run-silent:<line>` (round id stays
   in `detail`); self-contained question; concrete default or hold;
   `resolves_when:{"green_row_for_round":<rid>}`; kind-TTL `expires_at`.
5. `server/engine/request_sweep.py` — `green_row_for_round` in the existing
   fail-closed family + the expiry sweep; heads without a declared condition
   untouched (KI-B: the legacy 46 exit only by host dismissal).
6. `server/plugins/executor-panel/src/host/requests.ts` — TS fold port
   closing KI-A: open list minus resolved/expired/folded; update rows and
   duplicate-key head rows fold into their head; legacy visible; role
   surfaces excluded from the host inbox; digest counts; English labels,
   data untranslated (CLAUDE.md rule 6).
7. Tests: `server/engine/tests/test_t261021_08_request_layer.py` (NEW unit
   battery ported from `integration/t261021-08/test_request_contract.py` +
   write-path cases); extend `test_run_watch.py`,
   `test_t261019_44_request_sweep.py`; NEW
   `server/plugins/executor-panel/tests/requests-fold.test.mjs` (golden
   fixture shared by literal copy with the python suite; drift = red).
8. Estate sync — SAME ticket, SAME merge (atomicity, review gen3 R2): flip
   `integration/t261021-08/sc_t26102108_request_layer_gate.py` leg G1 (the
   engine face now REFUSES the defect shapes and converges same-key
   re-files); header note on `lib_request_contract.py` (spec moved to the
   engine port) + a mirror-sync drift test on the public names; L16 anchor
   entries in `integration/test_anchors.json` for the touched scenario/tests.

### Steps
1. Port `request_contract.py` + unit battery → `pytest
   server/engine/tests/test_t261021_08_request_layer.py`, `py_compile`,
   `python3 integration/lint_tests.py`.
2. Wire `executor_requests.py` (+ shared helper) → write-path cases in the
   battery; same trio.
3. `run_watch.py` → extend `test_run_watch.py`, run it.
4. `request_sweep.py` → extend `test_t261019_44_request_sweep.py`, run it.
5. Panel TS fold → `node --test
   server/plugins/executor-panel/tests/requests-fold.test.mjs`, `node --check`.
6. Estate sync (G1 flip, mirror-sync test, anchors) → battery re-run +
   `lint_tests.py`; the gate runs the flipped scenario.

### Acceptance
- In-lane green: all pytest files above, `lint_tests.py` 0 error/0 warn, the
  panel fold test green.
- Gate green on the flipped `t261021-08-request-layer-gate`.
- Live re-measure, reader-side discipline (the requests.jsonl FILE the host
  panel reads, KI-195), counting core `run_all_detectors`: 0 open same-key
  duplicate heads; 0 post-fix rows with null `expires_at`; 0 cross-role rows
  in the host ledger; 0 unfoldered correction rows post-fix. The legacy-46
  residual is reported SEPARATELY (KI-B), never merged into the verdict.

### Known issues this ticket's acceptance must close
- KI-A: until the panel fold lands, folded updates render as extra history
  rows — acceptance NOT green while the inbox shows them as separate cards.
- KI-B: the legacy 46 stay noisy until the expiry sweep lands; reported
  separately.
- KI-C: the re-raise age (a dismissed/aged-out condition may file a fresh
  head) is added by this ticket.

### Alternatives considered (rejected at plan review)
- Validators inside `executor_requests.py` only: two sources of truth for a
  contract whose point is one card per condition.
- Reader-only fold first: the spec demands write-path enforcement; a reader
  mask hides noise instead of stopping it.
