# Plan — t261009-75: one declared answer-row shape, two agreeing readers

KI-01M4HPGHVWAKB62TXYV4G7ENEB. The request ledger (`<root>/<key>/requests.jsonl`,
append-only) has two readers with different strictness:

- Panel reader `server/plugins/executor-panel/src/host/requests.ts` `isAnswerRow`:
  strict — `type==='answer' && answer_for:string && at:number && answer:string`.
- Engine reader `server/engine/request_thread.py` `head_states`: lenient — any
  dict row with `type==='answer'` and a string `answer_for` clears a head.

Measured 261010: six steward-written answer rows with `at` as a STRING cleared
the engine's account, the panel still showed six waiting.

## Decision (the shape, declared once)

Adopt the panel's predicate as the ONE canonical answer-row shape. Both
sanctioned writers already produce it (`answerRequest` writes `at: nowMs`
number; the engine write path likewise stamps a numeric `at`). Rows written
outside the sanctioned writers (hand-written rows) that fail the shape must be
named, never guessed into clearing a head. The panel's current "shape-off row
stays waiting" stance is the safe direction and is kept.

Consequence: a hand-written `at`-string answer row keeps the head OPEN on BOTH
faces, and both faces say so by name. Divergence of verdicts becomes
impossible for answer rows; for historical lenient tolerance the difference is
declared in code comments on both sides pointing at each other (the write set
does not include `docs/`, so the declaration lives in the two module headers).

## Steps

### Step 1 — engine reader aligns + names malformed rows
File: `server/engine/request_thread.py`
- Add module constants `ANSWER_ROW_REQUIRED` (the canonical shape, comment
  naming `requests.ts isAnswerRow` as the mirror truth source) and a helper
  `is_answer_row(row)` implementing exactly the panel predicate
  (`type/answer_for/at:number/answer:string`).
- `head_states` applies the predicate: a shape-off answer row no longer clears
  a head AND is collected. Extend the read face so the CLI/read output carries
  the named malformed rows (e.g. `head_states_with_report` returning
  `(states, {"malformed_answer_rows": [{"answer_for", "at"}, ...]})` —
  `head_states` keeps its signature for existing callers and delegates).
- Module header comment: declare the shared shape and state that any future
  divergence must be named on both sides.

### Step 2 — engine write path asserted canonical
File: `server/engine/request_thread.py`
- Verify (and where absent, enforce) that the engine-side answer/reply append
  stamps `at` as an int; a non-numeric `at` supplied in argv is refused
  fail-closed rather than landed (the writer can never produce the bad shape).

### Step 3 — panel declares the mirror
File: `server/plugins/executor-panel/src/host/requests.ts`
- Keep `isAnswerRow` unchanged (it is the truth source). Comment names the
  engine mirror (`request_thread.py is_answer_row`) and the KI id. The view
  already counts malformed rows; ensure a shape-off answer row surfaces in the
  existing malformed counter (it already does via `isAnswerRow` failure — add
  the naming comment only).

### Step 4 — tests
- `server/engine/tests/` (extend `test_t261007_02_request_thread.py` or a new
  `test_t261010_75_answer_row_shape.py`):
  - string-`at` answer row over an open head → head stays open, row named in
    the malformed report;
  - canonical answer row (as the writer produces) → head answered;
  - answer row missing `answer` string → stays open, named;
  - malformed-input discipline: non-dict row, bad JSON line → counted not
    dropped;
  - engine append path writes numeric `at`; argv with string `at` refused.
- `server/plugins/executor-panel/tests/` (extend `requests-thread.test.mjs` /
  `requests.test.mjs`):
  - string-`at` answer row → request stays `waiting`, malformed_rows counts it;
  - end-to-end through the sanctioned writer: `answerRequest` append, then the
    panel's own read split shows the item out of `waiting` (acceptance 4 at
    unit level — no integration entry executed);
  - mutation check: a canonical row DOES move the panel state (guards against
    over-tightening).

## Verification
- `python3 -m py_compile server/engine/request_thread.py`
- targeted pytest: `pytest server/engine/tests/test_t261007_02_request_thread.py server/engine/tests/test_t261010_75_answer_row_shape.py`
- `python3 integration/lint_tests.py`
- panel: `node --test server/plugins/executor-panel/tests/requests-thread.test.mjs server/plugins/executor-panel/tests/requests.test.mjs` (same runner the suite already uses)
- NO integration entry points run (discipline 260921).

## Alternatives considered (and why not)
1. **Lenient engine + declared divergence** (engine keeps accepting any
   answer row; difference documented): rejected — the whole defect is that the
   two verdicts differ on the same file; documenting a live disagreement does
   not make a steward able to predict the panel from the engine's account.
2. **Coercion/leniency on the panel** (accept `at` as number-or-numeric-string):
   rejected — rewards rows written outside the sanctioned writer, and the
   ticket pins the panel's strict stance as the safe direction.
3. **Rewrite/migrate the six historical rows**: forbidden — append-only ledger,
   explicitly out of scope.

## Files changed
- `server/engine/request_thread.py`
- `server/plugins/executor-panel/src/host/requests.ts`
- `server/engine/tests/test_t261010_75_answer_row_shape.py` (new; maybe touch
  `test_t261007_02_request_thread.py`)
- `server/plugins/executor-panel/tests/requests-thread.test.mjs`
- `integration/t261009-75/plan.md` (this file)

## Acceptance criteria
1. A row produced by either sanctioned writer moves BOTH readers' state for the
   same head (unit-proven both directions).
2. A shape-off answer row (string `at`, missing `answer`, etc.) clears a head
   on NEITHER face and is named on BOTH faces (engine report + panel
   malformed counter).
3. The declared shape and the mirror relationship are stated in both module
   headers; no third shape table exists.
4. Append-only discipline untouched: no row rewriting, dismiss/state/link
   semantics unchanged, panel remains the decider's face.

---

## Addendum (implement stage): review_plan binding conditions applied

1. **Gate-behavior change declared + tested.** The strict `is_answer_row`
   predicate inside `head_states` also moves three internal gates: the
   duplicate scan (`file_thread_op` — a re-file over a head cleared only by a
   shape-off answer row now hits the duplicate gate instead of opening a second
   head), the resolved gate (`state_op`) and the supersedes gate (`link_op` —
   a head cleared only by a shape-off answer row is supersedable). Covered by
   `test_duplicate_scan_links_over_shapeoff_answered_head` and
   `test_supersedes_gate_sees_shapeoff_answered_head_as_open`.
2. **Step 2 rescoped.** The engine CLI never receives an argv-supplied `at`
   (`reply_op` hardcodes `at: now_ms`); the invented string-`at` refusal is
   dropped. Kept: the numeric-`at` regression test on the reply row.
3. **The malformed report reaches a human via the CLI.** New `op="read"` face
   on `request_thread.py` returns `{ok, file, states, malformed_answer_rows,
   malformed_lines}` — the steward checks "is the ledger clear" from the
   engine side alone.
4. **Legacy sentence retired; historical ruling stated.** The header sentence
   "the legacy answer row keeps judging the head answered" is replaced by the
   canonical-shape declaration. Ruling: every answer row the panel ever wrote
   carries a numeric `at` (and the panel also lands an answered state row), so
   panel-written history stays answered — only out-of-writer rows (the KI's
   six) flip to open, on BOTH faces alike.
5. **KI id named in both module headers** (`request_thread.py` and
   `requests.ts`).

Implementation status: all four steps landed; engine 58 UT green
(t261007-02 + t261009-75 files), panel UT green (new
t261010-75-answer-row-shape.test.mjs + requests-thread/requests/dismiss),
`integration/lint_tests.py` 0 error (1 pre-existing L8 warn), anchor declared
in `integration/test_anchors.json`.
