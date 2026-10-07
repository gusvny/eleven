# Test design — t261008-04 vacuous skip-branch guard

Deliverable type: repair of an existing registered scenario, not a new journey.
The scenario under repair is `integration/t261006-12/sc_review_ledger_period_chain.py`
(registry entry `t261006-12-review-ledger-period-chain`, ro pool, offline seconds,
zero docker/Temporal/3099). No new scenario file is added: the guard-nonlinearity
intent already lives in that entry, and a separate meta-scenario would duplicate
intent at zero additional fault coverage.

## Fault surfaces and case mapping

| # | Fault surface | Case (high-level) | Pass/fail anchor |
|---|---|---|---|
| F1 | Vacuous capture: lazy `{0,600}?` window captures only the 19-char literal, so the P1 forbidden-word scan reads nothing (the ticket's finding) | Fix extractor to a line-indent branch body; assert captured length > 100 (real body ~12 lines / ~300-600 chars; a regression to the literal-only shape fails loudly) | `len(skip_txt) > 100` on the unmodified tree, PASS |
| F2 | Wrong anchor: first literal occurrence is a comment (activities.py line 1104), not the branch (line 1298) | Anchor regex pins the `if bool(plan.get("skip_when_unchanged"))` statement; assert anchor match count == 1 in the source (t261008-04 review comment 1) | `ok(len(re.findall(SKIP_ANCHOR, ACTIV_SRC)) == 1, ...)` PASS |
| F3 | Over-capture: extractor swallows post-branch code (false pass by scanning clean neighboring code) | Structural pin: the skip branch returns before the Temporal connection, so `Client.connect` must NOT appear in the capture | `ok("Client.connect" not in skip_txt, ...)` PASS |
| F4 | Regression to vacuous extractor goes silently green | Negative control: build a poisoned copy of the source by inserting one forbidden reference (`append_reviewed`) indented inside the extracted branch body, re-run the extractor, assert the capture sees the plant (i.e. the guard's own scan would go red) — the control must assert through the same forbidden-word scan the guard uses (review comment 2) | On poisoned source, scan reports the planted word — RED expected, mechanism proven |
| F5 | Plant fails to land (anchor missing / wrong indent) and the control silently skips | Plant-landing failure is a RED assertion, never a skip; plant line index must sit strictly inside the extracted line range (review comment 3) | PASS on unmodified tree |

## Three-state contract

PASS / FAIL only for this scenario's faces (all offline, no external supply);
engine module `inspection_review_ledger` unimportable = ENV_FAIL exit 2 (existing
header contract, unchanged).

## Acceptance mapping (from the ticket)

1. Scenario still passes on the unmodified tree → gate run of
   `python3 integration/t261006-12/sc_review_ledger_period_chain.py` exit 0.
2. Negative control fails when the planted word is present → F4: the plant is built
   in-scenario from real source, so the red face is exercised mechanically.
3. Handoff states measured capture length before (= 19 chars, t261007-03) and after
   → implement-stage handoff must carry both numbers from the read-only measurement
   snippet.

## Out of scope

`server/engine/activities.py` (source under test) and all other guards in the same
scenario file — untouched by this ticket.
