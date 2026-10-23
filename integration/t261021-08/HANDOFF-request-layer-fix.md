# HANDOFF — request-layer fix ticket (t261021-08 follow-up)

Audience: the developer of the follow-up ticket that lands the enforcement in
`server/engine/` + `server/plugins/ui/` (this ticket's write set was
`integration/` only, so nothing here is implemented yet — this file is the
verbatim spec, and `integration/t261021-08/lib_request_contract.py` is the
executable form of every validator named below; port it, do not redesign it).

Design authority: `docs/design/executor-operational-envelope-v1.md` §3 — a
request carries `audience` (`host` | `executor` | `any`) and, when the
records can settle it, `resolves_when`. Convergence representation:
APPEND-FOLDED (the head row is never rewritten; see §2 below for why).

## 1. Enforcement points, per file

### `server/engine/executor_requests.py` (the write path — all of items 1–4, 6, 7)
At the top of `append_request`, after identity gates and BEFORE any write,
run these validators (names verbatim from `lib_request_contract.py`):

| Validator | Refusal on fail |
| --- | --- |
| `normalize_condition_key(row)` | `field=condition_key`, reason `per-instance-value` / `missing kind` / `missing project` / `needs line or ticket` / `cause normalizes to empty` |
| `check_self_contained(row)` | `field=self_contained`, reason lists every missing item of `full_ticket_id, line, stage, decision_yes_no_or_named_options` |
| `check_default_action(row)` | `field=default_action`, reason `no-op-recheck` (banned: re-check / next tick / watch / monitor) or `missing` / bad shape |
| `route_audience(row)` | `field=audience` on bad shape; on `role:<x>` the row goes to `<ledger_root>/<key>/requests-<role>.jsonl`, NEVER `requests.jsonl` |

Plus:
- `expires_at`: required non-null. When the caller omits it, stamp
  `expiry_for(kind, now)` (KIND_TTL_MS: blocker/authorization/run-* 7d,
  notice 48h, question/decision 72h, unknown kind falls back to 72h — no
  card is born immortal). Legacy rows with null expiry are history, never
  rewritten.
- On append, under `request_thread._locked_append`: scan open heads for the
  same `condition_key`. Found and NOT (older than the kind re-raise age or
  host-dismissed) ⇒ append ONE `{type:"request-update", condition_key, count,
  last_seen}` row and return a receipt naming the existing head — no new head
  row. Otherwise append a fresh head carrying `condition_key`.
- Cap/digest: after append, if the open-card count exceeds
  `SANDBAR_REQUESTS_OPEN_CAP` (default 20), file ONE digest card
  (`type:"request-digest"`, listing folded ids with `age_ms` and
  `has_default`) and stamp the folded heads `folded_into` in the fold view
  (the stamp is computed by the reader, see §2 — the producer only files the
  digest row).

### `server/engine/run_watch.py` (the noisy producer)
- Dedupe key drops the round id: `run-silent:<line>` (was
  `run-silent:<line>:<round>`, the measured 6-cards disease). The round id
  stays in `detail`.
- Its questions become self-contained (full round id in the text, line,
  stage, yes/no decision).
- `default_action`: concrete (`{"action": "retry the round", "after_ms":
  1800000}`) or `{"hold": true}` — never "re-checks the records next tick".
- Stamp `resolves_when: {"green_row_for_round": <rid>}` so the existing
  request_sweep closes the card when the run row lands (item 5 convergence).
- Stamp `expires_at` from the kind TTL.

### `server/engine/request_sweep.py` (convergence + expiry consumer)
- One new condition kind `green_row_for_round {run}` in the existing
  fail-closed family (same SKIP-with-named-note rules as
  green_cert_after/landing_on_line/ticket_closed/freeze_closed).
- An expiry sweep: for every open head with `expires_at < now`, append one
  `expired` state row `by: "engine:request-sweep"`, `surface: engine` — the
  card leaves the open list, stays in history, and is COUNTED as expired in
  the digest. Never a silent drop.
- Known reach limit (do not "fix" silently): the sweep skips heads WITHOUT a
  declared condition — the 46 legacy rows are out of its reach; they exit
  only by host dismissal (see §3 residual).

### `server/plugins/ui/` host inbox reader (the fold — items 1/5/6/7 consumer half)
Port `fold_updates(rows, now, cap)` verbatim from
`lib_request_contract.py`: open list = heads minus resolved minus expired
minus folded; update rows and duplicate-key head rows fold into their head
(count/last_seen); legacy rows (no condition key, no expiry) are classified
`legacy`, always visible, counted in the digest; role-surface files
(`requests-<role>.jsonl`) are NEVER read into the host inbox; UI labels in
English (CLAUDE.md rule 6), data not translated.

## 2. Contract decision: append-folded, never in-place
The head row is never edited. Reasons, binding: (a) the ledger's existing
discipline is append-only under `request_thread._locked_append`, a lock with
no read-modify-write recovery path — a torn rewrite has no precedent and no
recovery; (b) `docs/design/executor-operational-envelope-v1.md` does not rule
on the requests-ledger write discipline, so the conservative reading wins;
(c) the measured "35 correction rows" disease is a READER problem (rows no
one folds), and folding fixes it without a new write shape.

## 3. Known issues the follow-up ticket's acceptance MUST close (review gen2 item 3)
- KI-A (reader-gated fold): until the UI half lands, folded update rows show
  as extra history rows, not as one card. The fix ticket's acceptance is NOT
  green while the host inbox still renders folded updates as separate cards.
- KI-B (legacy residual): the 46 open rows stay noisy until the expiry sweep
  lands; they render as legacy in the digest only. The acceptance counts
  them separately from post-fix rows.
- KI-C (producer re-raise): the write path currently has no re-raise age;
  the fix ticket adds the kind re-raise age named in item 1 (a dismissed or
  aged-out condition may file a fresh head).

## 4. Acceptance (re-measure command, for the fix ticket)
Read-only count over the live ledger, post-fix, judged per §3:
`python3 - <<'EOF'` style one-pass counter reporting: open heads with null
`expires_at` (post-fix rows only), open heads sharing one `condition_key`,
cross-role audience rows in `requests.jsonl`, unfoldered correction rows.
All four must be 0 post-fix; legacy rows counted, not merged into the
verdict. The detectors in `lib_request_contract.run_all_detectors` are the
reusable counting core.
