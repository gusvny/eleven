# t261009-51 Plan — Canonical serialization + a lint that bites (anchor registries)

> Implementation note (review_plan gen0 conditions applied): the new lint check is
> **L23**, not L22 — L22 is the stale-pin check (t261009-02). The style's failure-mode
> tradeoffs are declared in `lib_registry.py`'s docstring; canonicalization is
> documented root-agnostic (batch_stage_exceptions.json is a list root in good
> standing). This file was re-authored at implement after the original was
> quarantined; content matches the approved plan plus those corrections.

## Problem
Every ticket that appends an anchor entry re-serializes `integration/test_anchors.json`
with whatever `json.dumps` defaults its script uses. The 1-space vs 2-space indent flip
made t261009-48/49 produce ~9k-line diffs with zero semantic change, and turns parallel
anchor appends into guaranteed conflicts.

## Canonical form (declared once, in code)
UTF-8, `ensure_ascii=False`, `indent=2`, insertion key order (no sort_keys), exactly
one trailing newline — the style `integration/known-red-baseline.json` already uses.
Declared in `integration/lib_registry.py` (`CANONICAL_JSON_KWARGS`).

## Declared registry set (normalization scope)
`integration/test_anchors.json`, `integration/known-red-baseline.json`,
`integration/batch_stage_exceptions.json`.
Deliberately excluded: the L8 tmpdir baseline (lint-generated output of
`--write-tmpdir-baseline`, not a hand-edited registry).

## Changed files (landed)
1. `integration/lib_registry.py` (new) — canonical bytes, `write_registry` single
   entry point, `first_diff_line`; failure-mode tradeoffs declared (lone-surrogate
   raises loudly, never a silent ensure_ascii=True downgrade; family precedent
   `lib_emit_anchor.py`); root-agnostic canonicalization.
2. `integration/lint_tests.py` — new check **L23 registry serialization** (docstring
   paragraph + `lint_registry_serialization(err, repo=None)` + call after L22 in
   `main()`). Byte-compares canonical re-serialization vs disk; red names the file
   and the first differing line; unreadable declared registry = fail-closed red;
   malformed JSON stays with the existing faces (L16/L4); never rewrites.
3. Registry normalization — `batch_stage_exceptions.json` re-serialized (the one
   real byte change; the other two were already canonical). Content-freeness proven
   by `git show HEAD:<path>` parsed == on-disk parsed (unit test C6).
4. `integration/t261009-51/test_lib_registry.py` — 17-case unit battery (canonical
   shape, root-agnostic array root, round trip, first_diff_line faces, malformed
   inputs incl. unserializable no-partial-write, HEAD-vs-disk content-freeness, L23
   lint faces over a tmp repo incl. planted style drift).
5. `integration/README.md` — new section "JSON registries: the canonical write path"
   pointing anchor append work at `lib_registry.write_registry`.
6. Scenario registration (design stage, same lane): `integration/run_scenarios.py`
   two t261009-51 entries + their anchor manifest entries; scripts
   `sc_registry_style_drift_bite.py` / `sc_registry_writer_canonical.py` live in
   `integration/t261009-51/`.

## Verification (run, evidence in the stage result)
- `pytest integration/t261009-51/test_lib_registry.py` → 17 passed
- `python3 -m py_compile` on all new/changed py files → OK
- `python3 integration/lint_tests.py` → exit 0 (0 error / 1 pre-existing L8 warn on
  grandfathered files); `L23 ... 3 declared registries on the canonical form`
- Live bite proof: `git diff --stat integration/test_anchors.json` after appending
  the two anchor entries via the canonical writer = **+10 lines** (the incident's
  same-kind change was 9082 lines).
- Discipline: no integration entry executed in-lane (scenario runs left to the gate);
  no git operations.

## Alternatives considered (rejected)
- Canonical writer inside `lint_tests.py`: consumers would import the heavy lint
  module (atexit side effects) to write a file.
- Self-healing gate: violates fail-loud rule — no gate silently reformats a shared
  source of truth.

## Non-goals (rule 6)
No anchor meaning changes, no entries added/removed beyond this ticket's own two
scenario registrations, no engine tests/scenarios touched, no source formatter,
TMPDIR_BASELINE left as-is.
