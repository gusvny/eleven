# t261009-02 — Integration test design (design_integration_tests stage)

Scope: re-point stale refusal-string anchors left behind by the copy translation in
commit f5c6b9ad (changes.ts), and pin the "wording change carries its anchors" rule
mechanically. No new user-visible behavior is introduced by this ticket, so **zero new
scenario entries** are registered: coverage rides on three existing registered
scenarios (registry `integration/run_scenarios.py`), whose assertions move with the
copy, plus a new static lint (L19) and its unit tests.

## Basis (three-source exhaustion)

1. **user_request / acceptance**: two `越出` anchors must assert the English refusal;
   sweep the scenario family for other stale pins of since-translated messages; the
   rule must be pinned mechanically; assertions must keep testing the refusal
   (provably able to fail); an untranslated-message pin must stay untouched.
2. **KI**: KI-057 (cross-project anchor family, open incident record at
   `notes/debts/known-issues.md` line ~596 quotes the pre-translation Chinese refusal
   `worktree 越出仓库根`) is the family this ticket's red sits in. New failure mode
   discovered by this ticket: **stale-anchor rot** — a copy change in a shared host
   face leaves scenario pins red and blocks unrelated tickets (t261008-29). Reported
   for KI registration by integration role; candidate id suggestion: KI-0xx
   "scenario anchor rot on shared-face copy change".
3. **Contract**: changes.ts diff-face public behavior — an out-of-root worktree
   produces `changed === false` with `emptyReason` naming the path-containment
   invariant; a missing member repo produces a per-repo `emptyReason` naming the repo
   and the non-materialized invariant. Anchors bind to these contract substrings, not
   to full sentences.

## Test set

### T1 — cross-project diff-face refusal anchors (re-point, existing scenario
`t260907-11-wb-anchor-faces`, file `integration/t260907-11/sc_wb_anchor_cross_project_faces.mjs`)
- **Intent**: the anti-crossing gate still refuses an out-of-root worktree with a
  path-containment reason, under both project anchors — i.e. the pin moves with the
  translation without weakening the gate assertion.
- **Legs**:
  - L1a (`dCross`): same worktree, sandbar anchor → refused, `emptyReason` includes
    `outside the repository root`.
  - L1b (`dEsc`): `../`-escape path under fpv root → refused, same substring.
- **Pinned substring**: `outside the repository root` — it names the invariant
  (path containment under the repository root), excludes subject ("worktree"), the
  interpolated path, and colon formatting, and cannot match an unrelated refusal.
- **Fail-proof (L1 failure-mode evidence)**: predicate
  `changed === false && emptyReason.includes('outside the repository root')` is fed
  (a) the real refusal → green; (b) `{changed:false, emptyReason:undefined}` → red;
  (c) `{changed:false, emptyReason:'some other reason'}` → red. The conjunction keeps
  the refusal itself under test (dropping only the substring check would violate the
  ticket's no-widening rule — not done).

### T2 — member-repo non-materialized anchor (re-point, existing scenario
`t260911-01` diff-faces, file `integration/t260911-01/sc_t260911_01_multirepo_diff_faces.mjs:186`)
- **Intent**: an absent member repo is named, not silently dropped — the `未物化`
  pin moves to the translated `not materialized` substring; `includes('ghost')`
  (repo naming) is kept unchanged and still passes.
- **Fail-proof**: same shape as T1 — absence of `not materialized` in `emptyReason`
  must make the assertion red while `repo === 'ghost'` present alone must not pass it.

### T3 — negative anchor (re-point, existing scenario
`t260907-11-wb-anchor-keys`, file `integration/t260907-11/sc_wb_anchor_key_resolution.mjs:52`)
- **Intent**: error-message precision — an unknown-key 400 error must not masquerade
  as a crossing refusal. The old pin `!(error).includes('越出')` is trivially true
  after translation (no longer discriminates); re-pointed to
  `!(error).includes('outside the repository root')`, keeping the negative semantics
  against the current true source.
- **Fail-proof**: an error string containing the crossing wording must make this leg
  red.

### T4 — negative case (no change, stays green)
`t260910-10/sc_docs_project_anchor.mjs:213` pins `未知项目` — that message has NOT
been translated (KI-070 family, changes.ts untouched by f5c6b9ad on this string), so
it stays as-is. Proves the sweep is targeted, not a blanket CJK replace. Also
untouched: `t260920-03:85` and `run_scenarios.py` intent strings (message builders /
descriptions, not changes.ts-face assertions); comments at key_resolution lines 9/47.

### T5 — mechanical guard L19 (new static check in `integration/lint_tests.py`,
unit tests in `integration/test_lint_stale_pin.py`)
- **Intent**: pin the rule "a user-visible string change on a shared face carries its
  scenario anchors in the same change" as a machine check, not discipline.
- **Design**: extract CJK string literals used in assertion positions
  (`X.includes('…')` in `*.mjs`; `'…' in X` / `X in '…'` and `.check()/ok()/j.ok()`
  messages in `*.py`) across `integration/**` scenario files; each literal must occur
  verbatim in (a) a non-integration source tree (`server/`, `app/`), or (b) the same
  file outside assertion literals (fixture-writer side), or (c) an explicit
  per-file:line exemption entry with a reason. Otherwise the lint names the stale pin.
- **Guard test cases**: ①current tree → lint green (proves no false positive on
  `t260920-03:85` f-string builder); ②planted stale CJK pin in a scratch scenario →
  lint red naming it, then reverted (proves the guard can fail); ③literal present in
  `server/` → green; ④exemption entry → green; ⑤malformed inputs (empty index, line
  without literals, non-UTF8-safe content) → no crash, fail-closed behavior.
- **Honest limits** (stated, not promised): L19 catches the observed class (pin whose
  literal no longer exists anywhere it could come from). It cannot prove a pin matches
  the *right* host message, and cannot catch a wording change whose old literal
  survives elsewhere in the tree. A deeper host-template↔pin correlation guard is not
  cheap and is not built.

## Failure faces covered

| Face | Where |
|---|---|
| Boundary (out-of-root path, `../` escape) | T1 L1a/L1b |
| Missing member / degraded multi-repo face | T2 |
| Error precision (no masquerade between error classes) | T3 |
| Regression-catch ability (assertions provably able to fail) | T1/T2/T3 fail-proofs |
| Guard false-positive / false-negative / malformed input | T5 ①–⑤ |
| Over-sweep protection (untranslated pin untouched) | T4 |

## Out of scope

Further copy translation (t261008-47), refusal semantics, re-Chinese-ing the English
wording, fixture semantics, blocked tickets (t261008-29 unblocks itself).

## Registration

No new registry entries. `t260907-11-wb-anchor-faces`, `t260907-11-wb-anchor-keys`,
`t260911-01` diff-faces already registered (`integration/run_scenarios.py:1476,1479,1547`);
their intent strings mention 「越出」 as a description of the refusal semantics — the
implement stage should update the two intent strings' 「越出」 wording references to
the English refusal so registry descriptions do not drift from the pinned literals.
