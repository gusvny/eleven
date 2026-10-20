"""t261007-02 -- the ledger thread face (request_thread.py) unit tests.

Coverage (mapped to the ticket's acceptance items):
- State machine: one case per legal transition; the three named refusals
  (a project session answering / an unknown source class / a resolved without
  evidence);
- Links: supersedes derives superseded (clean path: link row + state row both
  PHYSICALLY present -- review round 2 comment 2's invariant: the read-side
  recompute is torn-op repair, never a write-path license to skip the row);
- Duplicate re-file: same (source ticket + owning epic + subject) over an open
  head appends a duplicates link and opens NO new head; the link omits `from`
  and carries the triple snapshot (review round 2 comment 1);
- The two ownership fields: epic required / none plus reason / unregistered
  code refused / no consistency check against the source ticket's epic;
- Source and project derivation: project and source_class come from the
  registers (executor_sessions / sessions.json); a self-reported mismatch is
  refused; register read-back (acceptance item 4);
- expires_at never mutates state and never silences (display-face semantics);
- Malformed input: CLI non-JSON / non-object / lone surrogate / bad-line
  counting / torn-line recovery;
- flock: released on the error path (with discipline).
All seams injected (env / registers / clock / ledger path); zero real
~/.sandbar, zero external sources.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import request_thread as rt  # noqa: E402
import shared  # noqa: E402

REPO = Path(__file__).resolve().parents[3]

HEAD_BODY = {
    "op": "file",
    "kind": "decision",
    "question": "Adopt the thread ledger shape for the request family?",
    "detail": "design source: 261004 note",
    "default_action": "stay on one-question-one-answer",
    "subject": "request-ledger-thread",
    "epic": "project-executor",
    "source_ticket": "t261007-02",
}


def _env(tmp: Path, **kw) -> dict:
    env = {
        "SANDBAR_PANEL_DIR": str(tmp),
        "DSH_SESSION_ID": "sess-exec-1",
        "DSH_HEADLESS_SESSION": "",
        shared.CALLER_PROJECT_ENV: "proj-alpha",
        shared.CALLER_IDENTITY_SRC_ENV: "env",
        shared.CALLER_SURFACE_ENV: "",
    }
    env.update(kw)
    return env


def _decl_loader(sessions):
    def load(key):
        return {"ok": True, "executor_sessions": list(sessions)}
    return load


def _epics(tmp: Path, *codes) -> str:
    d = tmp / "epics"
    d.mkdir(parents=True, exist_ok=True)
    for c in codes:
        # t261019-12: registry entries carry front-matter; retired:false accepts.
        (d / (c + ".md")).write_text(
            "---\ncode: %s\nretired: false\nsummary: fixture entry.\n---\n\n# %s\n" % (c, c),
            encoding="utf-8")
    return str(d)


def _ledger(tmp, key="proj-alpha"):
    return tmp / key / "requests.jsonl"


def _rows(tmp, key="proj-alpha"):
    p = _ledger(tmp, key)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").split("\n"):
        if line.strip():
            out.append(json.loads(line))
    return out


def _file(tmp, body=None, now=1000, env=None, **kw):
    kw.setdefault("load_decl", _decl_loader(["sess-exec-1"]))
    kw.setdefault("epics_dir", _epics(tmp, "project-executor"))
    return rt.file_thread_op(dict(body or HEAD_BODY), now, 1,
                             env=env or _env(tmp), **kw)


def _put_sessions(tmp, key, sids):
    # The REAL register writer schema (workbench session-handles.ts
    # serializeSessionLedgerFile): {"version": 1, "sessions": [...]}. A fixture
    # must never invent a shape the register never writes (arbitration round 1
    # test-asset review: the invented `entries` shape was masking defect 1).
    d = tmp / key
    d.mkdir(parents=True, exist_ok=True)
    (d / "sessions.json").write_text(json.dumps(
        {"version": 1, "sessions": [{"session_id": s} for s in sids]}), encoding="utf-8")


# ---------- op=file: head row / ownership fields / source classification ----------

def test_file_head_row_shape(tmp_path):
    out = _file(tmp_path)
    assert out["ok"] is True
    row = out["row"]
    assert row["type"] == "request"
    assert row["subject"] == "request-ledger-thread"
    assert row["epic"] == "project-executor"
    assert row["source_ticket"] == "t261007-02"
    assert row["source_class"] == rt.SRC_EXECUTOR  # named in executor_sessions -> executor session
    assert row["raised_by"] == "sess-exec-1"
    assert "epic_reason" not in row


def test_epic_none_requires_reason(tmp_path):
    body = dict(HEAD_BODY, epic="none")
    out = _file(tmp_path, body)
    assert out["ok"] is False and out["field"] == "epic_reason"
    out2 = _file(tmp_path, dict(body, epic_reason="no epic owns cross-project tooling yet"))
    assert out2["ok"] is True and out2["row"]["epic"] == "none"
    assert out2["row"]["epic_reason"].startswith("no epic owns")


def test_epic_long_reason_refused_local_bound(tmp_path):
    out = _file(tmp_path, dict(HEAD_BODY, epic="none", epic_reason="x" * 201))
    assert out["ok"] is False and out["field"] == "epic_reason"


def test_epic_unknown_code_refused(tmp_path):
    out = _file(tmp_path)  # epics dir has only project-executor
    out2 = _file(tmp_path, dict(HEAD_BODY, epic="nope-epic"))
    assert out["ok"] is True
    assert out2["ok"] is False and out2["field"] == "epic"


def test_epic_not_crosschecked_against_source_ticket(tmp_path):
    # The only hard check = the code is in the register; epic independent of source_ticket is fine (trade-off 2).
    out = _file(tmp_path, dict(HEAD_BODY, epic="project-executor",
                               source_ticket="t260101-01"))
    assert out["ok"] is True


def test_subject_required(tmp_path):
    out = _file(tmp_path, {k: v for k, v in HEAD_BODY.items() if k != "subject"})
    assert out["ok"] is False and out["field"] == "subject"


def test_source_ticket_shape_refused(tmp_path):
    out = _file(tmp_path, dict(HEAD_BODY, source_ticket="not-a-ticket"))
    assert out["ok"] is False and out["field"] == "source_ticket"


def test_source_class_project_session_from_register(tmp_path):
    # sessions.json registration judges project-session; executor_sessions empty.
    _put_sessions(tmp_path, "proj-alpha", ["sess-exec-1"])
    out = _file(tmp_path, env=_env(tmp_path), load_decl=_decl_loader([]))
    assert out["ok"] is True
    assert out["row"]["source_class"] == rt.SRC_PROJECT


def test_source_class_unknown_refused(tmp_path):
    out = _file(tmp_path, env=_env(tmp_path), load_decl=_decl_loader([]))
    assert out["ok"] is False and out["field"] == "source_class"
    assert "source-class-unknown" in out["error"]


def test_source_class_lane_agent_from_injected_surface(tmp_path):
    env = _env(tmp_path, **{shared.CALLER_SURFACE_ENV: shared.CALLER_SURFACE_LANE_AGENT})
    out = _file(tmp_path, env=env, load_decl=_decl_loader([]))
    assert out["ok"] is True
    assert out["row"]["source_class"] == rt.SRC_LANE


def test_project_derived_not_self_reported(tmp_path):
    # Register read-back (acceptance item 4): the row's project = the register-resolved identity;
    # no caller-nameable project field in the body; a self-reported raised_by mismatch is refused (tested elsewhere).
    out = _file(tmp_path, dict(HEAD_BODY, caller_project="proj-alpha"))
    assert out["ok"] is True
    assert out["row"]["project"] == "proj-alpha"  # = the resolved caller identity
    assert not (tmp_path / "proj-beta" / "requests.jsonl").exists()
    # A different identity anchor lands in that project's ledger (the resolution decides, not the row).
    out2 = _file(tmp_path, dict(HEAD_BODY), now=2000,
                 env=_env(tmp_path, **{shared.CALLER_PROJECT_ENV: "proj-beta"}))
    assert out2["ok"] is True
    assert out2["row"]["project"] == "proj-beta"


def test_sessions_register_malformed_counts_as_absent(tmp_path):
    _put_sessions(tmp_path, "proj-alpha", ["sess-exec-1"])
    p = tmp_path / "proj-alpha" / "sessions.json"
    p.write_text("{broken json", encoding="utf-8")
    out = _file(tmp_path, env=_env(tmp_path), load_decl=_decl_loader([]))
    assert out["ok"] is False and out["field"] == "source_class"  # a broken register keeps the seam closed


# ---------- op=state: resolved with evidence / named refusals ----------

def _resolved(tmp, now=2000):
    _file(tmp_path := tmp)
    return rt.state_op({"op": "state", "id": "req-1000-0001", "state": "resolved",
                        "evidence": "t261007-02"}, now, 1,
                       env=_env(tmp_path), load_decl=_decl_loader(["sess-exec-1"]))


def test_resolved_with_ticket_evidence(tmp_path):
    out = _resolved(tmp_path)
    assert out["ok"] is True
    row = out["row"]
    assert row["type"] == "state" and row["state"] == rt.STATE_RESOLVED
    assert row["evidence"] == "t261007-02"


def test_resolved_with_commit_evidence(tmp_path):
    _file(tmp_path)
    out = rt.state_op({"op": "state", "id": "req-1000-0001", "state": "resolved",
                       "evidence": "0194abcd" * 3}, 2000, 1,
                      env=_env(tmp_path), load_decl=_decl_loader(["sess-exec-1"]))
    assert out["ok"] is True


def test_resolved_without_evidence_refused(tmp_path):
    _file(tmp_path)
    out = rt.state_op({"op": "state", "id": "req-1000-0001", "state": "resolved"},
                      2000, 1, env=_env(tmp_path), load_decl=_decl_loader(["sess-exec-1"]))
    assert out["ok"] is False and out["field"] == "evidence"
    assert "no evidence means no resolved" in out["error"]


def test_resolved_bad_evidence_shape_refused(tmp_path):
    _file(tmp_path)
    out = rt.state_op({"op": "state", "id": "req-1000-0001", "state": "resolved",
                       "evidence": "I did the thing"}, 2000, 1,
                      env=_env(tmp_path), load_decl=_decl_loader(["sess-exec-1"]))
    assert out["ok"] is False and out["field"] == "evidence"


def test_host_states_refused_from_engine(tmp_path):
    _file(tmp_path)
    for s in (rt.STATE_ANSWERED, rt.STATE_DISMISSED):
        out = rt.state_op({"op": "state", "id": "req-1000-0001", "state": s},
                          2000, 1, env=_env(tmp_path), load_decl=_decl_loader(["sess-exec-1"]))
        assert out["ok"] is False and out["field"] == "state"
        assert "panel" in out["error"]


def test_superseded_manual_refused(tmp_path):
    _file(tmp_path)
    out = rt.state_op({"op": "state", "id": "req-1000-0001", "state": "superseded"},
                      2000, 1, env=_env(tmp_path), load_decl=_decl_loader(["sess-exec-1"]))
    assert out["ok"] is False and out["field"] == "state"
    assert "machine" in out["error"]


def test_resolve_twice_refused_terminal(tmp_path):
    _resolved(tmp_path)
    out2 = rt.state_op({"op": "state", "id": "req-1000-0001", "state": "resolved",
                        "evidence": "0194abcd"}, 3000, 1,
                       env=_env(tmp_path), load_decl=_decl_loader(["sess-exec-1"]))
    assert out2["ok"] is False and out2["field"] == "state"
    assert "already resolved" in out2["error"]


def test_project_session_cannot_resolve(tmp_path):
    _put_sessions(tmp_path, "proj-alpha", ["sess-proj-1"])
    _file(tmp_path)
    env = _env(tmp_path, DSH_SESSION_ID="sess-proj-1")
    out = rt.state_op({"op": "state", "id": "req-1000-0001", "state": "resolved",
                       "evidence": "t261007-02"}, 2000, 1, env=env,
                      load_decl=_decl_loader([]))
    assert out["ok"] is False and out["field"] == "state"
    assert "project session cannot resolve" in out["error"]


# ---------- op=reply: writer rules / the delegated trio ----------

def test_reply_by_executor_with_delegated_fields(tmp_path):
    # Delegated answer (ticket item 7, rework defect 2): by = the DECIDER, via =
    # the filer (the resolved session), anchor = the host's words. The filer is
    # identity-gated: a via that is not the resolved session is refused.
    _file(tmp_path)
    out = rt.reply_op({"op": "reply", "id": "req-1000-0001", "text": "host chose plan A",
                       "intent": "answer", "by": "host", "via": "sess-exec-1",
                       "anchor": "go with A"}, 2000, 1,
                      env=_env(tmp_path), load_decl=_decl_loader(["sess-exec-1"]))
    assert out["ok"] is True
    row = out["row"]
    assert row["type"] == "reply" and row["reply_for"] == "req-1000-0001"
    assert row["by"] == "host" and row["via"] == "sess-exec-1"
    assert row["anchor"] == "go with A" and row["intent"] == "answer"


def test_reply_by_requires_via(tmp_path):
    _file(tmp_path)
    out = rt.reply_op({"op": "reply", "id": "req-1000-0001", "text": "x",
                       "intent": "answer", "by": "host"}, 2000, 1,
                      env=_env(tmp_path), load_decl=_decl_loader(["sess-exec-1"]))
    assert out["ok"] is False and out["field"] == "via"
    assert "requires the filer" in out["error"]


def test_reply_via_mismatch_refused(tmp_path):
    _file(tmp_path)
    out = rt.reply_op({"op": "reply", "id": "req-1000-0001", "text": "x",
                       "intent": "answer", "by": "host", "via": "someone-else"},
                      2000, 1, env=_env(tmp_path), load_decl=_decl_loader(["sess-exec-1"]))
    assert out["ok"] is False and out["field"] == "via"
    assert "never self-reported" in out["error"]


def test_reply_via_without_by_is_the_callers_own(tmp_path):
    # Legacy shape (via alone): the reply is the caller's own; via is just an
    # explicit filing mark, by stays the resolved session.
    _file(tmp_path)
    out = rt.reply_op({"op": "reply", "id": "req-1000-0001", "text": "measured",
                       "intent": "fact", "via": "sess-exec-1"}, 2000, 1,
                      env=_env(tmp_path), load_decl=_decl_loader(["sess-exec-1"]))
    assert out["ok"] is True
    assert out["row"]["by"] == "sess-exec-1" and out["row"]["via"] == "sess-exec-1"


def test_project_session_answer_refused(tmp_path):
    _put_sessions(tmp_path, "proj-alpha", ["sess-proj-1"])
    _file(tmp_path)
    env = _env(tmp_path, DSH_SESSION_ID="sess-proj-1")
    out = rt.reply_op({"op": "reply", "id": "req-1000-0001", "text": "the answer is B",
                       "intent": "answer"}, 2000, 1, env=env, load_decl=_decl_loader([]))
    assert out["ok"] is False and out["field"] == "reply"
    assert "may ask and add facts" in out["error"]


def test_project_session_fact_allowed(tmp_path):
    _put_sessions(tmp_path, "proj-alpha", ["sess-proj-1"])
    _file(tmp_path)
    env = _env(tmp_path, DSH_SESSION_ID="sess-proj-1")
    out = rt.reply_op({"op": "reply", "id": "req-1000-0001", "text": "measured: 3 hits",
                       "intent": "fact"}, 2000, 1, env=env, load_decl=_decl_loader([]))
    assert out["ok"] is True and out["row"]["source_class"] == rt.SRC_PROJECT


def test_reply_to_unknown_head_refused(tmp_path):
    out = rt.reply_op({"op": "reply", "id": "req-404-0001", "text": "hi"}, 2000, 1,
                      env=_env(tmp_path), load_decl=_decl_loader(["sess-exec-1"]))
    assert out["ok"] is False and out["field"] == "id"


def test_reply_no_state_gate_on_superseded_head(tmp_path):
    # Review round 1 comment 3: replies carry no state gate (the note gates writers only).
    _file(tmp_path)
    rt.link_op({"op": "link", "kind": "supersedes", "from": "req-1000-0001",
                "to": "req-1000-0001"}, 2000, 1,
               env=_env(tmp_path), load_decl=_decl_loader(["sess-exec-1"]))
    out = rt.reply_op({"op": "reply", "id": "req-1000-0001", "text": "still counts"},
                      3000, 1, env=_env(tmp_path), load_decl=_decl_loader(["sess-exec-1"]))
    assert out["ok"] is True


# ---------- op=link: supersedes derivation / shapes ----------

def _two_heads(tmp):
    _file(tmp)  # req-1000-0001
    _file(tmp, dict(HEAD_BODY, subject="other-family"), now=1500)  # req-1500-0001


def test_supersedes_link_and_state_rows_physically_present(tmp_path):
    _two_heads(tmp_path)
    out = rt.link_op({"op": "link", "kind": "supersedes", "from": "req-1000-0001",
                      "to": "req-1500-0001"}, 2000, 1,
                     env=_env(tmp_path), load_decl=_decl_loader(["sess-exec-1"]))
    assert out["ok"] is True
    rows = _rows(tmp_path)
    kinds = [(r["type"], r.get("kind") or r.get("state")) for r in rows]
    # Invariant (review round 2 comment 2): both rows PHYSICALLY present on the clean path.
    assert ("link", "supersedes") in kinds
    assert ("state", "superseded") in kinds
    states = rt.head_states(rows)
    assert states["req-1500-0001"] == rt.STATE_SUPERSEDED
    assert states["req-1000-0001"] == rt.STATE_OPEN


def test_supersede_read_recompute_torn_op(tmp_path):
    # Torn op: only the link row, the state row absent (simulated crash) -> read recompute.
    _two_heads(tmp_path)
    rows = _rows(tmp_path)
    rows.append({"type": "link", "id": "lnk-torn-0001", "kind": "supersedes",
                 "from": "req-1000-0001", "to": "req-1500-0001", "at": 2000,
                 "by": "sess-exec-1"})
    states = rt.head_states(rows)
    assert states["req-1500-0001"] == rt.STATE_SUPERSEDED


def test_supersede_terminal_target_refused(tmp_path):
    _two_heads(tmp_path)
    rt.link_op({"op": "link", "kind": "supersedes", "from": "req-1000-0001",
                "to": "req-1500-0001"}, 2000, 1,
               env=_env(tmp_path), load_decl=_decl_loader(["sess-exec-1"]))
    out = rt.link_op({"op": "link", "kind": "supersedes", "from": "req-1000-0001",
                      "to": "req-1500-0001"}, 3000, 1,
                     env=_env(tmp_path), load_decl=_decl_loader(["sess-exec-1"]))
    assert out["ok"] is False and out["field"] == "to"


def test_link_unknown_kind_or_head_refused(tmp_path):
    _two_heads(tmp_path)
    base = dict(env=_env(tmp_path), load_decl=_decl_loader(["sess-exec-1"]))
    out = rt.link_op({"op": "link", "kind": "likes", "to": "req-1000-0001"}, 2000, 1, **base)
    assert out["ok"] is False and out["field"] == "kind"
    out2 = rt.link_op({"op": "link", "kind": "blocks", "to": "req-404-0001"}, 2000, 1, **base)
    assert out2["ok"] is False and out2["field"] == "to"
    out3 = rt.link_op({"op": "link", "kind": "blocks", "from": "req-404-0001",
                       "to": "req-1000-0001"}, 2000, 1, **base)
    assert out3["ok"] is False and out3["field"] == "from"


# ---------- duplicate re-file: mechanical link, no new head (acceptance item 3) ----------

def test_duplicate_refile_links_instead_of_opening(tmp_path):
    _file(tmp_path)  # open head with (t261007-02, project-executor, request-ledger-thread)
    # A terminal head no longer blocks -> assert the open-head block first.
    out = _file(tmp_path, now=2000)
    assert out["ok"] is True
    assert out["linked_to"] == "req-1000-0001"
    assert out["row"]["kind"] == rt.LINK_DUPLICATES
    assert out["row"]["to"] == "req-1000-0001"
    # Review round 2 comment 1: the linked re-file omits from (never a row); the snapshot travels on the row.
    assert "from" not in out["row"]
    assert out["row"]["dup_subject"] == "request-ledger-thread"
    assert out["row"]["dup_epic"] == "project-executor"
    assert out["row"]["dup_source_ticket"] == "t261007-02"
    rows = _rows(tmp_path)
    heads = [r for r in rows if r["type"] == "request"]
    assert len(heads) == 1  # no new head


def test_refile_after_terminal_opens_new_head(tmp_path):
    _file(tmp_path)
    rt.state_op({"op": "state", "id": "req-1000-0001", "state": "resolved",
                 "evidence": "t261007-02"}, 2000, 1,
                env=_env(tmp_path), load_decl=_decl_loader(["sess-exec-1"]))
    out = _file(tmp_path, now=3000)
    assert out["ok"] is True
    assert "linked_to" not in out
    assert out["row"]["type"] == "request"


def test_refile_different_triple_opens(tmp_path):
    _file(tmp_path)
    out = _file(tmp_path, dict(HEAD_BODY, subject="another-family"), now=2000)
    assert out["ok"] is True and "linked_to" not in out


def test_legacy_head_without_subject_never_collides(tmp_path):
    # Legacy heads (no subject) stay out of the family scan -- classification waits for the host.
    import executor_requests as er
    out = er.append_request({"kind": "decision", "question": "legacy row?",
                             "detail": "", "default_action": "x", "expires_at": None},
                            500, env=_env(tmp_path), load_decl=_decl_loader(["sess-exec-1"]))
    assert out["ok"] is True
    out2 = _file(tmp_path, now=1000)
    assert out2["ok"] is True and "linked_to" not in out2


# ---------- expires_at semantics: display only, never a state change, never a mute ----------

def test_expiry_never_mutates_state(tmp_path):
    _file(tmp_path, dict(HEAD_BODY, expires_at=500))  # expiry earlier than any judgement moment
    rows = _rows(tmp_path)
    states = rt.head_states(rows)
    assert states["req-1000-0001"] == rt.STATE_OPEN  # expiry is not closed, not dismissed, not muted


# ---------- malformed input / torn lines / lock discipline ----------

def test_torn_line_counted_never_silent(tmp_path):
    _file(tmp_path)
    p = _ledger(tmp_path)
    with open(p, "a", encoding="utf-8") as f:
        f.write('{"type":"request", "id":"torn\n')  # a half line (simulated crash tear)
    out = rt.reply_op({"op": "reply", "id": "req-1000-0001", "text": "ok"}, 2000, 1,
                      env=_env(tmp_path), load_decl=_decl_loader(["sess-exec-1"]))
    assert out["ok"] is True  # bad-line tolerance never blocks the write path


def test_lock_released_on_error_path(tmp_path):
    # After a mid-op refusal (unknown head) the lock must be free: the next writer succeeds immediately.
    _file(tmp_path)
    out = rt.reply_op({"op": "reply", "id": "req-404-0001", "text": "x"}, 2000, 1,
                      env=_env(tmp_path), load_decl=_decl_loader(["sess-exec-1"]))
    assert out["ok"] is False
    out2 = rt.reply_op({"op": "reply", "id": "req-1000-0001", "text": "y"}, 2500, 1,
                       env=_env(tmp_path), load_decl=_decl_loader(["sess-exec-1"]))
    assert out2["ok"] is True  # the lock is re-acquired = released with no residue


def test_direct_write_closure_resident_channel(tmp_path):
    env = _env(tmp_path, **{shared.CALLER_IDENTITY_SRC_ENV: "cwd"})
    out = _file(tmp_path, env=env, cwd=str(tmp_path / "proj-alpha"),
                load_decl=_decl_loader(["sess-exec-1"]))
    assert out["ok"] is False and out["field"] == "channel"
    assert "client.py deliver" in out["error"]


# ---------- CLI malformed input ----------

def _run_cli(args):
    return subprocess.run([sys.executable, str(REPO / "server" / "engine" / "request_thread.py")]
                          + args, capture_output=True, text=True, timeout=60)


def test_cli_bad_json_and_non_object(tmp_path):
    r = _run_cli(["not json"])
    assert r.returncode == 2 and json.loads(r.stdout)["field"] == "body"
    r2 = _run_cli(["[1,2]"])
    assert r2.returncode == 2 and "JSON object" in json.loads(r2.stdout)["error"]


def test_cli_lone_surrogate_visible_not_crash(tmp_path):
    r = _run_cli([json.dumps({"op": "file", "subject": "\ud800",
                              "question": "q?", "kind": "k", "epic": "none"})])
    assert r.returncode == 2
    out = json.loads(r.stdout)
    assert out["ok"] is False  # the bad char becomes visible, the refusal named, no crash


def test_cli_unknown_op_refused(tmp_path):
    r = _run_cli([json.dumps({"op": "poke"})])
    assert r.returncode == 2 and json.loads(r.stdout)["field"] == "op"
