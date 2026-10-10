# Held gate-face edits — server/engine/path_gates.py (t261009-58 debt)

`path_gates.py` is a protected face (host ruling 261010T02:18Z): this ticket may
not write it until the host authorizes per-item (same handling as t261009-38/-45).
The two edits below implement host ruling 261010T02:09Z (KI-01M4HR0ECTNFS4RWSQ8M0GE17J);
they were implemented once (gen2), verified green, then reverted byte-for-byte to
HEAD when the protection was declared. They wait for authorization, then land in a
retry round of this ticket or a follow-up ticket. Design notes stay here so the
re-application is a copy-paste, not a re-derivation.

## Edit 1 — bundle_out_face condition 3 accepts entries UNDER the src prefix

In `bundle_out_face` (and the SAME predicate in `bundle_out_prefixes` — one judge,
no second truth), replace the src-coverage check:

```python
# before
if _within(src, ws):
    return src
# after
if _within(src, ws) or any(_within(e, (src,)) for e in ws):
    return src
```

`bundle_out_prefixes` symmetric change:

```python
# before
if _within(src, ws) and out not in outs:
# after
if (_within(src, ws) or any(_within(e, (src,)) for e in ws)) and out not in outs:
```

Measured motive (t261009-53): a write set naming three concrete `src/client/`
files left the rebuilt `lib/client.{cjs,js}` refused twice
(`unauth-implement-gen0` / `unauth-arbitrate-gen0`). The src side is already
bound by the write-set judge; widening the out side adds nothing the src side
does not guard. Fail-closed shapes unchanged (empty ws / missing declaration →
refused).

Unit test (was green in gen2): `test_bundle_out_admits_entries_under_src_prefix`
in `server/engine/tests/test_t261009_58_write_set_record.py` — ws `["src/client/a.c",
"src/client/b.c"]` admits `lib/client.cjs`/`lib/client.js`; old shape
`["src/client/"]` unchanged; `dist/client.cjs` refused; src-outside-prefix
refused; empty/None declaration fail-closed; `bundle_out_prefixes == ["lib"]`.

## Edit 2 — arbitrate (kind=test_face) gains the _bundle_out_ok() fallback

In `judge_stage_paths`, the `test_face` branch currently ends:

```python
return "" if (receipt and _within(f, (receipt,))) else "unauthorized_path"
```

Change to the same fallback the write_set/join/self_heal kinds carry:

```python
return "" if (_test_face_ok() or _bundle_out_ok()) else "unauthorized_path"
```

(so a rebuilt out-prefix file is a NAMED pass — `BUNDLE_OUT_FACE_NOTE: file (src
prefix)` — instead of showing up wearing an "unauthorized write" face), and
update `_STAGE_FACE_DESC["test_face"]` to append
`∪ declared build-chain outputs (bundle-out-face, named)` plus the
`judge_stage_paths` docstring line ("the test_face kind gains the bundle-out-face
fallback too").

Unit test (was green in gen2): `test_arbitrate_test_face_admits_bundle_out_named`
in the same module, plus moving `("arbitrate", None)` out of
`test_judge_other_kinds_do_not_widen` in
`server/engine/tests/test_t261009_38_bundle_out_face.py` (replaced by the new
named-pass pin) — that legacy pin reversal is the ruling reversing a spec, not a
test fudge.

## Acceptance when authorization lands

1. Both edits applied exactly as above; `path_gates.py` diff contains nothing else.
2. The three test changes re-landed with them.
3. `pytest` on the four touched modules green; `python3 integration/lint_tests.py`
   → `0 error / 1 warn`.
