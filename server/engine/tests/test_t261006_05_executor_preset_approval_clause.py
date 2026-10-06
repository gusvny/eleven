# -*- coding: utf-8 -*-
"""t261006-05 — source lock for the executor preset's approval/escalation clause
(KI-208 persona face).

The preset does not own the sandbox/approval stack (host-plane), but the persona
must carry the discipline: an executor session has no approval answerer, so it
must never depend on an approval prompt after a sandbox denial. This test is a
static source assertion only (reads the preset file; zero runtime, zero host).
It pins three things:
  1. the "no answerer" statement on record (the approval sibling of the
     ask_user_question clause);
  2. the sandbox-inside preference (evidence into the repo + a named report in
     the final message);
  3. the engine-side delivery face (client.py deliver), and no recommendation of
     the direct ledger append anywhere in the preset.
"""
import re
from pathlib import Path

PRESET = Path(__file__).resolve().parents[2] / "profile" / "agent-presets" / "sandbar-executor" / "agent.cordis.yml"


def _text() -> str:
    return PRESET.read_text(encoding="utf-8")


def test_approval_no_answerer_statement_present():
    t = _text()
    assert re.search(r"NO approval answerer", t), "preset must state the executor session has no approval answerer (KI-208)"
    assert re.search(r"Never depend on an approval prompt", t), "preset must forbid depending on an approval prompt"
    # The escalation-retry trap (the 03:29 event shape) is named as forbidden.
    assert re.search(r"Never retry a denied\s+action as an escalation request", t)


def test_sandbox_inside_preference_present():
    t = _text()
    assert re.search(r"prefer an action that stays inside your workspace", t)
    assert re.search(r"write the evidence into the repo", t)
    assert re.search(r"name it\s+in your final message", t)


def test_engine_side_delivery_face_present():
    t = _text()
    assert re.search(r"client\.py deliver", t), "preset must name the engine-side delivery face"
    assert re.search(r"never\s+a direct ledger append", t)


def test_preset_does_not_recommend_the_direct_cli_entry():
    # The direct-write entry (executor_requests.py CLI) must not be recommended as a
    # delivery channel anywhere in the preset — it is the closed door (t261006-05).
    t = _text()
    assert "executor_requests.py" not in t, "preset must not point at the direct ledger-append CLI"
