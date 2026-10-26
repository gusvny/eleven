# -*- coding: utf-8 -*-
"""t261026-07 -- the request class -> condition table, the residue close, and
the sweep's place in the watch cycle. Unit tests over request_sweep.py,
executor_requests.py and run_watch.py's filing face.

Coverage (mapped to the ticket's A/B/C/D and the plan-review conditions):
- A (table): run-stalled / run-silent file with the round_after condition on
  their own line (run_watch decision bodies carry it; append_request_row
  forwards it; executor_requests stamps it); a blocker derives ticket_closed
  from a well-formed subject_ticket; a malformed subject_ticket / condition is
  a named refusal, never a stored guess;
- A (not auto-closable): finding / question file with auto_closable=false and
  a face note naming the human answer as the only closer;
- B (watch cycle): run_watch_tick_engine runs the sweep BEFORE the decisions
  and carries its receipt on the result; a sweep that throws is a named
  entry and the decisions still run;
- C (residue): legacy open heads with no condition close ONLY on a cited
  subject row (run-silent / run-stalled: a certification row on the line
  after the head; blocker: its ticket closed or a landing naming it);
- D (bound): finding / question are NEVER closed (bucket human_word); a
  blocker whose ticket reads not-listed stays open (bucket not_listed); an
  unparsable head stays open (bucket uncited);
- round_after as a new closed-set kind: validation, evaluation (strictly
  after the head's `at`, both sides must carry a readable `at`), and
  end-to-end close through sweep_project with idempotence.
All fixtures are local (tmp ledgers / stubs); zero real ~/.sandbar, zero
external sources, no real ticket channel.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import request_sweep as rs  # noqa: E402
import executor_requests as er  # noqa: E402
import shared  # noqa: E402

NOW = 1730000000000
SEQ = 3


# ---------- fixtures ---------------------------------------------------------

@pytest.fixture
def ledger_env(tmp_path):
    env = {"SANDBAR_PANEL_DIR": str(tmp_path)}
    return env, tmp_path


def write_ledger(tmp_path, key, rows):
    path = tmp_path / key / "requests.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return path


def head(hid, kind, at=NOW, detail="", question="", cond=None):
    row = {"type": "request", "id": hid, "at": at, "kind": kind,
           "question": question or ("%s head %s" % (kind, hid)),
           "detail": detail, "default_action": "wait",
           "raised_by": "sess-x", "surface": "engine"}
    if cond is not None:
        row["resolves_when"] = cond
    return row


def cert(cid, line, at, seq=1, run="run-x"):
    return {"kind": "certification", "id": cid, "line": line, "seq": seq,
            "run": run, "repos": [], "booked_red": "false", "judged_by": "t",
            "at": at}


def landing(lid, ticket, at=NOW):
    return {"kind": "landing", "id": lid, "ticket": ticket, "line": "main",
            "at": at}


def ticket_closed_fn(status="closed"):
    def fn(t):
        return (status, "ticket-list-projection")
    return fn


def sweep(tmp_path, key, rows, ledger_rows, env, ticket_status=None):
    def ledger_rows_fn():
        return ledger_rows, 0, ""
    return rs.sweep_project(key, NOW + 5, SEQ, env=env,
                            ledger_rows_fn=ledger_rows_fn,
                            is_green=lambda rid: True,
                            ticket_status_fn=ticket_status
                            or ticket_closed_fn())


def read_ledger(path):
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                out.append(json.loads(line))
    return out


def residue_bucket(receipt, hid):
    for e in receipt.get("residue") or []:
        if e.get("id") == hid:
            return e
    return None


# ---------- round_after: the new closed-set kind -----------------------------

def test_round_after_validation_accepts_line_shape():
    out = rs.validate_resolves_when({"kind": "round_after",
                                     "line": "develop-buffer"})
    assert out["ok"] is True
    assert out["condition"] == {"kind": "round_after", "line": "develop-buffer"}


def test_round_after_validation_refuses_bad_line_and_extra_keys():
    bad_line = rs.validate_resolves_when({"kind": "round_after", "line": ""})
    assert bad_line["ok"] is False and bad_line["field"] == "resolves_when"
    bad_shape = rs.validate_resolves_when({"kind": "round_after",
                                           "line": "a b!"})
    assert bad_shape["ok"] is False
    extra = rs.validate_resolves_when({"kind": "round_after",
                                       "line": "l", "cert": "cert-x"})
    assert extra["ok"] is False and "unknown key" in extra["error"]
    unknown = rs.validate_resolves_when({"kind": "round_but_later",
                                         "line": "l"})
    assert unknown["ok"] is False and "closed" in unknown["error"]


def test_eval_round_after_true_false_skip():
    rows = [cert("c1", "develop-buffer", NOW + 10),
            {"kind": "landing", "id": "ldg-1", "ticket": "t1", "at": NOW + 10}]
    v, ev, note = rs.eval_round_after("develop-buffer", rows, NOW)
    assert v is rs.VERDICT_TRUE and ev == "c1"
    assert "round_after" in note and "c1" in note
    # a cert BEFORE the head never closes it
    v2, _, _ = rs.eval_round_after("develop-buffer", rows, NOW + 20)
    assert v2 is rs.VERDICT_FALSE
    # an unreadable head `at` is a named skip, never a guess
    v3, _, note3 = rs.eval_round_after("develop-buffer", rows, None)
    assert v3 is rs.VERDICT_SKIP and "head_at_unreadable" in note3
    # a cert whose own `at` is unreadable does not count
    rows2 = [cert("c2", "develop-buffer", None)]
    v4, _, _ = rs.eval_round_after("develop-buffer", rows2, NOW)
    assert v4 is rs.VERDICT_FALSE


def test_class_table_declares_the_vocabulary():
    assert set(rs.CLASS_CONDITION_TABLE) == {"run-silent", "run-stalled",
                                             "blocker"}
    for spec in rs.CLASS_CONDITION_TABLE.values():
        assert spec["kind"] in rs.CONDITION_KINDS
    assert set(rs.NOT_AUTO_CLOSABLE) == {"finding", "question"}


# ---------- A: the filing face stamps the table -----------------------------

ER_BODY = {"question": "Is the line stalled?", "default_action": "wait"}


def _er_env(tmp, **kw):
    env = {"SANDBAR_PANEL_DIR": str(tmp),
           "DSH_SESSION_ID": "sess-exec-1",
           "DSH_HEADLESS_SESSION": "",
           shared.CALLER_PROJECT_ENV: "proj-alpha",
           shared.CALLER_IDENTITY_SRC_ENV: "env",
           shared.CALLER_SURFACE_ENV: ""}
    env.update(kw)
    return env


def _decl_loader(sessions):
    def load(key):
        return {"ok": True, "executor_sessions": list(sessions)}
    return load


def _file(tmp, key="proj-alpha"):
    return tmp / key / "requests.jsonl"


def test_blocker_with_subject_ticket_derives_ticket_closed(tmp_path):
    body = dict(ER_BODY, kind="blocker", subject_ticket="t261026-07",
                question="Fix ticket t261026-07 blocks the line")
    out = er.append_request(body, NOW, env=_er_env(tmp_path),
                            load_decl=_decl_loader(["sess-exec-1"]))
    assert out["ok"] is True
    row = out["row"]
    assert row["resolves_when"] == {"kind": "ticket_closed",
                                    "ticket": "t261026-07"}
    assert row["subject_ticket"] == "t261026-07"


def test_malformed_subject_ticket_refused(tmp_path):
    body = dict(ER_BODY, kind="blocker", subject_ticket="not-a-ticket")
    out = er.append_request(body, NOW, env=_er_env(tmp_path),
                            load_decl=_decl_loader(["sess-exec-1"]))
    assert out["ok"] is False and out["field"] == "subject_ticket"
    assert not _file(tmp_path).exists()


def test_explicit_resolves_when_stamped_malformed_refused(tmp_path):
    body = dict(ER_BODY, kind="run-stalled",
                resolves_when={"kind": "round_after",
                               "line": "develop-buffer"})
    out = er.append_request(body, NOW, env=_er_env(tmp_path),
                            load_decl=_decl_loader(["sess-exec-1"]))
    assert out["ok"] is True
    assert out["row"]["resolves_when"] == {"kind": "round_after",
                                           "line": "develop-buffer"}
    bad = dict(ER_BODY, kind="run-stalled",
               resolves_when={"kind": "round_after", "line": "b d"})
    out2 = er.append_request(bad, NOW + 1, env=_er_env(tmp_path),
                             load_decl=_decl_loader(["sess-exec-1"]))
    assert out2["ok"] is False and out2["field"] == "resolves_when"


def test_finding_and_question_stamped_not_auto_closable(tmp_path):
    for kind in ("finding", "question"):
        body = dict(ER_BODY, kind=kind)
        out = er.append_request(body, NOW, env=_er_env(tmp_path),
                                load_decl=_decl_loader(["sess-exec-1"]))
        assert out["ok"] is True
        row = out["row"]
        assert row.get("auto_closable") is False
        assert "human" in row["auto_closable_note"]
        assert "resolves_when" not in row
        _file(tmp_path).unlink()


def test_append_request_row_forwards_resolves_when(tmp_path, monkeypatch):
    # run_watch.append_request_row is the watch's only filing face; the table
    # condition must reach the row (the declared executor session comes from
    # the injected declaration loader).
    import run_watch as rw
    import executor_grants
    monkeypatch.setattr(executor_grants, "load_declaration",
                        lambda key: {"ok": True,
                                     "executor_sessions": ["sess-exec-1"]})
    out = rw.append_request_row("proj-alpha", "run-stalled",
                                "run-stalled on line develop-buffer",
                                {"line": "develop-buffer"}, NOW,
                                env=_er_env(tmp_path),
                                resolves_when={"kind": "round_after",
                                               "line": "develop-buffer"})
    assert out.get("ok") is True, out
    row = out["row"]
    assert row["resolves_when"] == {"kind": "round_after",
                                    "line": "develop-buffer"}
    assert row.get("delivered_via") == "engine-process"


# ---------- B: the sweep runs in the watch cycle ----------------------------

def test_tick_engine_runs_sweep_before_decisions(tmp_path, monkeypatch):
    import run_watch as rw
    import develop_certify
    seen = []

    def fake_tick(project_key, now_ms=None):
        seen.append(("tick", project_key))
        return {"lines": [], "summary": "tick"}

    monkeypatch.setattr(rw, "run_watch_tick", fake_tick)
    monkeypatch.setattr(develop_certify, "declared_line_projects",
                        lambda: ["proj-alpha"])
    seen = []

    def fake_sweep(project_key, now_ms, seq, **kw):
        seen.append(("sweep", project_key))
        return {"ok": True, "project": project_key, "resolved": [],
                "residue": [], "skipped": [], "unchanged": 0,
                "malformed_lines": 0}
    monkeypatch.setattr(rs, "sweep_project", fake_sweep)
    out = rw.run_watch_tick_engine(now_ms=NOW)
    assert ("sweep", "proj-alpha") in seen
    assert seen.index(("sweep", "proj-alpha")) < seen.index(("tick", "proj-alpha"))
    assert out["request_sweep"]["proj-alpha"]["ok"] is True
    assert out["request_sweep_closed_total"] == 0
    assert "sweep closed" in out["summary"]


def test_tick_engine_sweep_crash_is_named_entry_decisions_still_run(tmp_path,
                                                                    monkeypatch):
    import run_watch as rw
    import develop_certify

    def boom(*a, **kw):
        raise RuntimeError("sweep exploded")

    monkeypatch.setattr(rs, "sweep_project", boom)
    monkeypatch.setattr(rw, "run_watch_tick",
                        lambda project_key, now_ms=None:
                        {"lines": [], "summary": "tick"})
    monkeypatch.setattr(develop_certify, "declared_line_projects",
                        lambda: ["proj-alpha"])
    out = rw.run_watch_tick_engine(now_ms=NOW)
    entry = out["request_sweep"]["proj-alpha"]
    assert entry["ok"] is False and "request_sweep_failed" in entry["error"]
    assert out["projects"]["proj-alpha"]["summary"] == "tick"


def test_tick_engine_sweep_receipt_counts_closes(tmp_path, monkeypatch):
    import run_watch as rw
    import develop_certify
    monkeypatch.setattr(rw, "run_watch_tick",
                        lambda project_key, now_ms=None:
                        {"lines": [], "summary": "tick"})
    monkeypatch.setattr(develop_certify, "declared_line_projects",
                        lambda: ["proj-alpha"])

    def fake_sweep(project_key, now_ms, seq, **kw):
        return {"ok": True, "project": project_key,
                "resolved": [{"id": "r1", "evidence": "c1", "note": "",
                              "row_id": "st-1"}],
                "residue": [{"id": "r2", "bucket": "closed",
                             "evidence": "c2", "row_id": "st-2"}],
                "skipped": [], "unchanged": 0, "malformed_lines": 0}
    monkeypatch.setattr(rs, "sweep_project", fake_sweep)
    out = rw.run_watch_tick_engine(now_ms=NOW)
    assert out["request_sweep_closed_total"] == 2


# ---------- C+D: the residue close and its bound -----------------------------

def test_residue_closes_run_silent_on_later_cert(tmp_path, ledger_env):
    env, tmp = ledger_env
    detail = json.dumps({"line": "develop-buffer", "round": "run-1"})
    rows = [head("h1", "run-silent", at=NOW, detail=detail,
                 question="run-silent on line develop-buffer: no run row")]
    path = write_ledger(tmp, "proj-alpha", rows)
    ledger = [cert("c-later", "develop-buffer", NOW + 100)]
    receipt = sweep(tmp, "proj-alpha", rows, ledger, env)
    entry = residue_bucket(receipt, "h1")
    assert entry and entry["bucket"] == "closed"
    assert entry["evidence"] == "c-later"
    assert "round_after" in entry["note"]
    states = read_ledger(path)
    closed = [r for r in states if r.get("state_for") == "h1"]
    assert len(closed) == 1 and closed[0]["state"] == "resolved"
    assert closed[0]["by"] == rs.RESIDUE_BY


def test_residue_closes_run_stalled_via_question_line(tmp_path, ledger_env):
    env, tmp = ledger_env
    rows = [head("h2", "run-stalled", at=NOW,
                 question="run-stalled on line main: 2 pending landing(s)")]
    write_ledger(tmp, "proj-alpha", rows)
    ledger = [cert("c-r", "main", NOW + 1)]
    receipt = sweep(tmp, "proj-alpha", rows, ledger, env)
    entry = residue_bucket(receipt, "h2")
    assert entry and entry["bucket"] == "closed"
    assert entry["evidence"] == "c-r"


def test_residue_closes_blocker_on_closed_ticket_or_landing(tmp_path, ledger_env):
    env, tmp = ledger_env
    rows = [head("h3", "blocker", at=NOW,
                 question="fix ticket t261026-99 blocks the landing")]
    write_ledger(tmp, "proj-alpha", rows)
    receipt = sweep(tmp, "proj-alpha", rows, [], env)
    entry = residue_bucket(receipt, "h3")
    assert entry and entry["bucket"] == "closed"
    assert entry["evidence"].startswith("t261026-99 status=closed via")
    # a landing naming the ticket closes it too (ticket reader says open)
    write_ledger(tmp, "proj-alpha", rows)
    ledger2 = [landing("ldg-9", "t261026-99")]
    receipt2 = sweep(tmp, "proj-alpha", rows, ledger2, env,
                     ticket_status=ticket_closed_fn("open"))
    assert residue_bucket(receipt2, "h3")["bucket"] == "closed"
    assert residue_bucket(receipt2, "h3")["evidence"] == "ldg-9"


def test_residue_bound_finding_question_never_closed(tmp_path, ledger_env):
    env, tmp = ledger_env
    rows = [head("h4", "finding", at=NOW), head("h5", "question", at=NOW)]
    path = write_ledger(tmp, "proj-alpha", rows)
    ledger = [cert("c-any", "develop-buffer", NOW + 100)]
    receipt = sweep(tmp, "proj-alpha", rows, ledger, env)
    for hid in ("h4", "h5"):
        entry = residue_bucket(receipt, hid)
        assert entry and entry["bucket"] == "human_word"
    states = read_ledger(path)
    assert not [r for r in states if r.get("type") == "state"]


def test_residue_bound_not_listed_ticket_stays_open(tmp_path, ledger_env):
    env, tmp = ledger_env
    rows = [head("h6", "blocker", at=NOW, question="ticket t260901-01 stuck")]
    path = write_ledger(tmp, "proj-alpha", rows)
    receipt = sweep(tmp, "proj-alpha", rows, [], env,
                    ticket_status=ticket_closed_fn("not-listed"))
    entry = residue_bucket(receipt, "h6")
    assert entry and entry["bucket"] == "not_listed"
    assert not [r for r in read_ledger(path) if r.get("type") == "state"]


def test_residue_unparsable_and_unhandled_stay_open(tmp_path, ledger_env):
    env, tmp = ledger_env
    rows = [head("h7", "run-silent", at=NOW, detail="prose only, no line"),
            head("h8", "blocker", at=NOW, question="no ticket id here"),
            head("h9", "request", at=NOW)]
    path = write_ledger(tmp, "proj-alpha", rows)
    receipt = sweep(tmp, "proj-alpha", rows, [], env)
    assert residue_bucket(receipt, "h7")["bucket"] == "uncited"
    assert residue_bucket(receipt, "h7")["reason"] == "residue_line_unparsable"
    assert residue_bucket(receipt, "h8")["bucket"] == "uncited"
    assert residue_bucket(receipt, "h8")["reason"] == "residue_subject_unparsable"
    assert residue_bucket(receipt, "h9")["bucket"] == "uncited"
    assert "residue_class_unhandled" in residue_bucket(receipt, "h9")["reason"]
    assert not [r for r in read_ledger(path) if r.get("type") == "state"]


def test_residue_conditioned_heads_are_not_double_owned(tmp_path, ledger_env):
    # a head WITH a condition goes through the condition pass only; the
    # residue pass never touches it
    env, tmp = ledger_env
    cond = {"kind": "round_after", "line": "develop-buffer"}
    rows = [head("h10", "run-silent", at=NOW,
                 detail=json.dumps({"line": "develop-buffer"}), cond=cond)]
    path = write_ledger(tmp, "proj-alpha", rows)
    ledger = [cert("c-z", "develop-buffer", NOW + 1)]
    receipt = sweep(tmp, "proj-alpha", rows, ledger, env)
    assert len(receipt["resolved"]) == 1
    assert receipt["resolved"][0]["id"] == "h10"
    assert receipt["resolved"][0]["note"].startswith("round_after:")
    assert residue_bucket(receipt, "h10") is None
    assert len([r for r in read_ledger(path) if r.get("type") == "state"]) == 1


def test_residue_idempotent_second_sweep_closes_nothing(tmp_path, ledger_env):
    env, tmp = ledger_env
    detail = json.dumps({"line": "develop-buffer"})
    rows = [head("h11", "run-silent", at=NOW, detail=detail)]
    path = write_ledger(tmp, "proj-alpha", rows)
    ledger = [cert("c-1", "develop-buffer", NOW + 1)]
    first = sweep(tmp, "proj-alpha", rows, ledger, env)
    assert residue_bucket(first, "h11")["bucket"] == "closed"
    # replay the same sweep over the NOW-terminal head: no second row
    second = sweep(tmp, "proj-alpha", rows + [
        {"type": "state", "id": "st-x", "state_for": "h11",
         "state": "resolved", "at": NOW + 5}], ledger, env)
    assert residue_bucket(second, "h11") is None
    # exactly ONE closure row total: the terminal head is never re-closed
    assert len([r for r in read_ledger(path)
                if r.get("state_for") == "h11"]) == 1


def test_residue_with_malformed_ledger_rows_counted_not_fatal(tmp_path,
                                                              ledger_env):
    env, tmp = ledger_env
    rows = [head("h12", "run-silent", at=NOW,
                 detail=json.dumps({"line": "l"}))]
    write_ledger(tmp, "proj-alpha", rows)

    def ledger_rows_fn():
        return [cert("c-m", "l", NOW + 1), "not-a-dict"], 1, ""
    receipt = rs.sweep_project("proj-alpha", NOW + 5, SEQ, env=env,
                               ledger_rows_fn=ledger_rows_fn,
                               is_green=lambda rid: True,
                               ticket_status_fn=ticket_closed_fn())
    assert receipt["malformed_lines"] == 1
    assert residue_bucket(receipt, "h12")["bucket"] == "closed"


def test_round_after_condition_head_closes_through_sweep(tmp_path, ledger_env):
    # end-to-end shape of a NEW run-stalled head: filed with round_after, the
    # condition pass closes it when a round row lands after the head
    env, tmp = ledger_env
    cond = {"kind": "round_after", "line": "main"}
    rows = [head("h13", "run-stalled", at=NOW, cond=cond)]
    path = write_ledger(tmp, "proj-alpha", rows)
    receipt = sweep(tmp, "proj-alpha", rows, [], env)
    assert receipt["resolved"] == []  # no round row yet: stays open
    receipt2 = sweep(tmp, "proj-alpha", rows, [cert("c-new", "main", NOW + 1)],
                     env)
    assert len(receipt2["resolved"]) == 1
    assert receipt2["resolved"][0]["evidence"] == "c-new"


def test_both_passes_closing_in_one_sweep_mint_distinct_row_ids(tmp_path,
                                                                ledger_env):
    # acceptance gen7 finding: the residue pass and the condition pass both
    # closing heads in the SAME sweep must thread the seq counter — two
    # resolved rows with the same id in one ledger is a record-hygiene defect
    env, tmp = ledger_env
    cond = {"kind": "round_after", "line": "l-cond"}
    rows = [head("h-cond", "run-silent", at=NOW, cond=cond,
                 detail=json.dumps({"line": "l-cond"})),
            head("h-res", "run-silent", at=NOW,
                 detail=json.dumps({"line": "l-res"}))]
    path = write_ledger(tmp, "proj-alpha", rows)
    ledger = [cert("c-1", "l-cond", NOW + 1), cert("c-2", "l-res", NOW + 1)]
    receipt = sweep(tmp, "proj-alpha", rows, ledger, env)
    assert len(receipt["resolved"]) == 1        # h-cond via the condition pass
    closed = [e for e in receipt["residue"] if e.get("bucket") == "closed"]
    assert [e["id"] for e in closed] == ["h-res"]  # h-res via the residue pass
    ids = [r["id"] for r in read_ledger(path)
           if r.get("type") == "state"]
    assert len(ids) == 2 and len(set(ids)) == 2  # DISTINCT ids, read back
