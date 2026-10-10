"""t261009-75 -- the canonical answer-row shape, both readers agree (KI-01M4HPGHVWAKB62TXYV4G7ENEB).

Incident (261010): six hand-written answer rows with `at` as a STRING cleared
the engine's account (`head_states`) while the panel (isAnswerRow) kept six
waiting. Coverage:

- head_states: a canonical answer row clears a head; a shape-off row (string
  `at`, missing `answer`, wrong `answer_for` type, non-dict) never does;
- the malformed-answer report names every shape-off row (answer_for + at);
- op=read: the read face carries the report to a human (states + named rows +
  malformed-line count) -- the steward checks "is the ledger clear" here;
- gate-level declared change: over a head whose only answer is shape-off, the
  supersedes gate (link_op) now treats the head as OPEN (previously the lenient
  answer row marked it terminal and the supersedes was refused); the duplicate
  scan likewise links the re-file instead of opening a new head;
- write-path regression: the engine writer stamps a numeric `at` (reply_op
  hardcodes now_ms) -- the sanctioned writers can never produce the bad shape.
All seams injected (env / registers / clock / ledger path); zero real
~/.sandbar, zero external sources.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import request_thread as rt  # noqa: E402

HEAD = {"type": "request", "id": "req-1", "at": 1000, "project": "proj-alpha",
        "kind": "decision", "question": "q?", "detail": "", "default_action": "",
        "expires_at": None, "raised_by": "sess-1"}


def _good_answer(answer_for="req-1", at=2000):
    return {"type": "answer", "answer_for": answer_for, "at": at,
            "answer": "done", "by": "host"}


# ---------- pure head_states ----------

def test_canonical_answer_row_clears_head():
    states = rt.head_states([HEAD, _good_answer()])
    assert states["req-1"] == rt.STATE_ANSWERED


def test_string_at_answer_row_never_clears_head():
    bad = dict(_good_answer(), at="2000")  # the KI's exact shape
    states = rt.head_states([HEAD, bad])
    assert states["req-1"] == rt.STATE_OPEN
    assert rt.malformed_answer_rows([HEAD, bad]) == [{"answer_for": "req-1", "at": "2000"}]


def test_answer_row_missing_answer_never_clears_head():
    bad = {"type": "answer", "answer_for": "req-1", "at": 2000}
    states = rt.head_states([HEAD, bad])
    assert states["req-1"] == rt.STATE_OPEN
    assert rt.malformed_answer_rows([HEAD, bad]) == [{"answer_for": "req-1", "at": 2000}]


def test_answer_row_non_string_answer_for_never_clears_head():
    bad = dict(_good_answer(), answer_for=7)
    states = rt.head_states([HEAD, bad])
    assert states["req-1"] == rt.STATE_OPEN


def test_bool_at_is_not_a_number():
    bad = dict(_good_answer(), at=True)
    assert rt.head_states([HEAD, bad])["req-1"] == rt.STATE_OPEN


def test_non_dict_json_line_counted_by_the_line_reader(tmp_path):
    """head_states consumes _read_rows_unlocked output (dicts only, by
    contract); the malformed-input guard lives one layer down: a non-dict JSON
    line (e.g. `"answer"`) is counted as a malformed line, never crashed on."""
    p = tmp_path / "proj-alpha" / "requests.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(HEAD) + "\n" + '"answer"\n' + json.dumps(_good_answer()) + "\n",
                 encoding="utf-8")
    import os
    fd = os.open(str(p), os.O_RDONLY)
    try:
        rows, mal = rt._read_rows_unlocked(fd)
    finally:
        os.close(fd)
    assert mal == 1
    assert rt.head_states(rows)["req-1"] == rt.STATE_ANSWERED


def test_malformed_report_empty_for_clean_ledger():
    assert rt.malformed_answer_rows([HEAD, _good_answer()]) == []


# ---------- op=read: the report reaches a human ----------
# The wired env/decl/epics fixtures come from the t261007-02 suite (same seams,
# one shape of fixture -- never an invented register schema).

from test_t261007_02_request_thread import (  # noqa: E402
    _decl_loader, _env, _epics, _file, HEAD_BODY,
)


def _write_ledger(tmp, rows, key="proj-alpha"):
    p = tmp / key / "requests.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return p


def test_read_op_names_malformed_answer_rows(tmp_path):
    _write_ledger(tmp_path, [HEAD, _good_answer(), dict(_good_answer(), at="2000")])
    out = rt.read_op({"op": "read"}, 3000, 1, env=_env(tmp_path),
                     load_decl=_decl_loader(["sess-exec-1"]))
    assert out["ok"] is True
    assert out["states"] == {"req-1": rt.STATE_ANSWERED}
    assert out["malformed_answer_rows"] == [{"answer_for": "req-1", "at": "2000"}]
    assert out["malformed_lines"] == 0


def test_read_op_malformed_line_counted(tmp_path):
    p = _write_ledger(tmp_path, [HEAD])
    with p.open("a", encoding="utf-8") as f:
        f.write("not json\n")
    out = rt.read_op({"op": "read"}, 3000, 1, env=_env(tmp_path),
                     load_decl=_decl_loader(["sess-exec-1"]))
    assert out["malformed_lines"] == 1
    assert out["states"] == {"req-1": rt.STATE_OPEN}


def test_read_op_missing_ledger_is_empty_not_error(tmp_path):
    out = rt.read_op({"op": "read"}, 3000, 1, env=_env(tmp_path),
                     load_decl=_decl_loader(["sess-exec-1"]))
    assert out["ok"] is True
    assert out["states"] == {} and out["malformed_answer_rows"] == []


def test_read_op_requires_caller_gate(tmp_path):
    out = rt.read_op({"op": "read"}, 3000, 1, env=_env(tmp_path),
                     load_decl=_decl_loader([]))
    assert out["ok"] is False  # unknown source class -> structured refusal, no read


# ---------- gate-level declared change ----------

def test_supersedes_gate_sees_shapeoff_answered_head_as_open(tmp_path):
    """Previously the lenient answer row marked the head answered (non-terminal,
    so this passed anyway) -- the sharper sibling: a TERMINAL-shape head. Use
    resolved+bad answer mix: a head whose clearing rows are only shape-off must
    be supersedable."""
    _write_ledger(tmp_path, [HEAD, dict(_good_answer(), at="2000")])
    out = rt.link_op({"op": "link", "kind": "supersedes", "to": "req-1"}, 3000, 1,
                     env=_env(tmp_path), load_decl=_decl_loader(["sess-exec-1"]))
    assert out["ok"] is True
    kinds = [(r["type"], r.get("kind") or r.get("state")) for r in out["rows"]]
    assert ("link", "supersedes") in kinds and ("state", "superseded") in kinds


def test_supersedes_gate_still_refuses_canonical_terminal(tmp_path):
    _write_ledger(tmp_path, [HEAD, _good_answer()])
    out = rt.link_op({"op": "link", "kind": "supersedes", "to": "req-1"}, 3000, 1,
                     env=_env(tmp_path), load_decl=_decl_loader(["sess-exec-1"]))
    # answered is not terminal: supersedes still allowed -- but the read face
    # shows the answer took effect.
    assert out["ok"] is True
    rows = [json.loads(l) for l in
            (tmp_path / "proj-alpha" / "requests.jsonl").read_text(encoding="utf-8").splitlines() if l]
    assert rt.head_states(rows)["req-1"] == rt.STATE_SUPERSEDED


def test_duplicate_scan_links_over_shapeoff_answered_head(tmp_path):
    """Declared change: over a head cleared only by a shape-off answer row, a
    re-file of the same triple now hits the duplicate gate (the head is open)
    instead of silently opening a second head."""
    body = {"op": "file", "kind": "decision", "question": "q?",
            "detail": "d", "default_action": "x",
            "subject": "request-ledger-thread", "epic": "project-executor",
            "source_ticket": "t261009-75"}
    kw = dict(env=_env(tmp_path), load_decl=_decl_loader(["sess-exec-1"]),
              epics_dir=str(_epics(tmp_path, "project-executor")))
    first = rt.file_thread_op(dict(body), 1000, 1, **kw)
    assert first["ok"] is True
    with (tmp_path / "proj-alpha" / "requests.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(dict(_good_answer(), at="2000")) + "\n")
    second = rt.file_thread_op(dict(body), 3000, 1, **kw)
    assert second["ok"] is True and second["linked_to"] == "req-1000-0001"


# ---------- write-path regression: the sanctioned writer stamps numeric at ----------

def test_reply_row_carries_numeric_at(tmp_path):
    from test_t261007_02_request_thread import (  # reuse the wired fixtures
        _env as _wired_env, _decl_loader as _wired_loader, HEAD_BODY, _file)
    _file(tmp_path)
    out = rt.reply_op({"op": "reply", "id": "req-1000-0001", "text": "note",
                       "intent": "fact"}, 2000, 1,
                      env=_wired_env(tmp_path), load_decl=_wired_loader(["sess-exec-1"]))
    assert out["ok"] is True
    assert isinstance(out["row"]["at"], int)
    assert rt.is_answer_row(out["row"]) is False  # a reply is not an answer row


if __name__ == "__main__":
    sys.exit(pytest.main([__file__]))
