# -*- coding: utf-8 -*-
"""261019: a FLAT sign payload must reach the workflow with its fields intact.

Measured on t261019-32's acceptance walkthrough (worker log, kept with
SANDBAR_QMLE2E_KEEP_TMP=1):

    merge/awaiting-human  Waiting for the human sign-off
    merge/running         human signed off () - merging          <- EMPTY signer
    merge/done            merge booked 40b0e42c (human : ;)

The client's sign op did `raw = args.get("input") or {}`; a caller that sends
`who`/`gate`/`decision` at the TOP level (the documented CLI shape) has no
`input` key, so `None or {}` produced `{}` — a dict — and the `isinstance`
fallback to the flat args never fired. Every field was swallowed, the signal
carried `who=""`, and the no-self-sign handler (which refuses only when
`who == worked_by.session`) let the merge through. The guardrail held only
against a signature that carried an identity.

Coverage: the pure unwrap shape for both documented payload shapes (flat and
nested), an explicit assertion that a missing `input` is NOT read as an empty
payload, and the source anchor that keeps the two sign/authz faces on one rule.
"""
import os
import re

CLIENT_PY = os.path.join(os.path.dirname(__file__), "..", "client.py")
NOTE_PATCH = "server/engine/client.py"


def _unwrap(args):
    """Mirror of the client's sign payload unwrap (the rule under test)."""
    raw = args.get("input")
    if not isinstance(raw, dict):
        raw = args
    return raw


def test_flat_payload_keeps_its_fields():
    flat = {"op": "sign", "who": "host", "gate": "merge", "decision": "approve"}
    assert _unwrap(flat).get("who") == "host"
    assert _unwrap(flat).get("gate") == "merge"


def test_nested_payload_still_works():
    nested = {"op": "sign", "input": {"who": "host", "gate": "merge"}}
    assert _unwrap(nested).get("who") == "host"


def test_missing_input_is_never_an_empty_payload():
    # the incident: `or {}` made a missing key indistinguishable from an empty one
    flat = {"op": "sign", "who": "host"}
    assert flat.get("input") is None, "the fix depends on the key staying absent"
    assert _unwrap(flat).get("who") == "host", \
        "a missing input must fall back to the flat args, never become {}"


def test_non_dict_input_falls_back():
    assert _unwrap({"op": "sign", "input": "nope", "who": "host"}).get("who") == "host"


def test_sign_op_no_longer_reads_input_with_default_empty_dict():
    src = open(CLIENT_PY, encoding="utf-8").read()
    i = src.index('if op == "sign":')
    window = src[i:i + 1200]
    code_lines = [ln.strip() for ln in window.splitlines()
                  if ln.strip() and not ln.strip().startswith("#")]
    assert not any(ln == 'raw = args.get("input") or {}' for ln in code_lines), \
        "the `or {}` shape swallows every top-level field and blanks the signer"
    assert re.search(r'raw = args\.get\("input"\)\s*\n', window), \
        "the key must be read without a default so the fallback can fire"
