# -*- coding: utf-8 -*-
"""261020: the human gate needs a NAMED signature, not just a signal.

Measured on t261019-32's acceptance walkthrough (worker log, kept with
SANDBAR_QMLE2E_KEEP_TMP=1):

    merge/awaiting-human  Waiting for the human sign-off
    merge/running         human signed off () - merging          <- EMPTY signer
    merge/done            merge booked 40b0e42c (human : ; ...)

A signature that arrived with `who=""` was accepted and the merge booked with an
empty signer. Two consequences: the design's "one human signature per act" became
unaccountable, and any no-self-sign check that compares against the working
session is vacuous when the identity is blank (a blank matches nothing).

The gate now refuses a blank identity BY NAME and stays awaiting-human; the
signal is consumed, so a real signature can follow. Patch-guarded: a history
that already booked with a blank signer replays unchanged.
"""
import os

import dev_lane as dl

DEV_LANE_PY = os.path.join(os.path.dirname(__file__), "..", "dev_lane.py")


def _src():
    return open(DEV_LANE_PY, encoding="utf-8").read()


def _branch():
    s = _src()
    i = s.index("workflow.patched(SIGN_IDENTITY_PATCH_ID)")
    return s[i:i + 1400]


def test_blank_identity_is_refused_by_name():
    b = _branch()
    assert 'not str(getattr(sig, "who", "") or "").strip()' in b
    assert '"want": "sign(merge)"' in b and "carries no identity" in b


def test_the_refusal_keeps_the_ticket_waiting():
    b = _branch()
    assert 'self._mark("merge", "awaiting-human"' in b, \
        "a refused signature must leave the gate open for a real one"
    assert "continue" in b, "it must not fall through into the merge"


def test_the_signature_is_still_recorded_when_named():
    s = _src()
    i = s.index("workflow.patched(SIGN_IDENTITY_PATCH_ID)")
    after = s[i:i + 2000]
    assert 'self.signatures["merge"] = {"who": sig.who' in after, \
        "a named signature takes the existing path unchanged"


def test_it_is_patch_guarded():
    assert 'SIGN_IDENTITY_PATCH_ID = "dev-lane-sign-identity-v1"' in _src(), \
        "a history that already booked with a blank signer must replay unchanged"
