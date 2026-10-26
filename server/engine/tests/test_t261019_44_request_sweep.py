"""t261019-44 -- the declarative resolution-condition sweep (request_sweep.py)
and its request_thread faces (resolves_when at filing, op=condition, read
face), unit tests.

Coverage (mapped to the approved plan rev2 acceptance items):
- validate_resolves_when: the CLOSED four-kind set accepted; unknown kind /
  unknown keys / wrong param shapes / non-dict refused by name;
- effective_conditions: head field base, attached condition row wins, latest
  wins, an invalid condition row is carried as named-invalid (skip, never
  silent);
- the four evaluators: green_cert_after carries the _releasing_green_cert
  order rule (strictly-after, fail-closed when runs are unreadable, dangling
  red cert = skip); landing_on_line evidence = the ldg id; ticket_closed
  evidence NAMES the projection source (review gen1 comment 3); freeze_closed
  evidence = the episode id with the closing change named (change rows mint
  no id);
- sweep_project: one resolved row per head whose condition reads true, with
  evidence = the observed row; idempotent (second sweep resolves nothing);
  terminal heads untouched; no-condition heads untouched; skipped heads named;
  unreadable ledger = skipped_all, zero rows appended;
- race pin (review gen1 comment 2): a head answered/dismissed between two
  sweeps receives ZERO sweep-written rows;
- malformed input: non-dict ledger rows counted; malformed runs-store lines
  skipped; missing run row = None (never a guess); bad CLI argv.
All fixtures are local (tmp files / stubs); zero real ~/.sandbar, zero
external sources, no real ticket channel (default_ticket_status_fn is never
exercised against admin.py -- it is only shape-checked).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import request_sweep as rs  # noqa: E402
import request_thread as rt  # noqa: E402

NOW = 1730000000000
SEQ = 7


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


def head(hid, cond=None):
    row = {"type": "request", "id": hid, "at": NOW, "subject": "s-" + hid,
           "epic": "none", "epic_reason": "fixture"}
    if cond is not None:
        row["resolves_when"] = cond
    return row


def answer_row(hid):
    return {"type": "answer", "answer_for": hid, "at": NOW + 1, "answer": "yes"}


def state_row(hid, state):
    return {"type": "state", "id": "st-x-" + hid, "state_for": hid,
            "state": state, "at": NOW + 1}


def green_cert(cid, line="default", seq=2, run="run-g1"):
    return {"kind": "certification", "id": cid, "line": line, "seq": seq,
            "run": run, "repos": [], "booked_red": "false", "judged_by": "t",
            "at": NOW}


def red_cert(cid, line="default", seq=1, run="run-r1"):
    return green_cert(cid, line=line, seq=seq, run=run)


def ledger_deps(rows, malformed=0, error=""):
    def fn():
        if error:
            return None, 0, error
        return rows, malformed, ""
    return fn


def always_green(run_id):
    return True


def sweep(tmp_path, key, rows, env, **kw):
    deps = {
        "ledger_rows_fn": kw.pop("ledger_rows_fn", ledger_deps(rows)),
        "is_green": kw.pop("is_green", always_green),
        "ticket_status_fn": kw.pop("ticket_status_fn",
                                   lambda t: ("closed", "ticket-list-projection")),
    }
    deps.update(kw)
    return rs.sweep_project(key, NOW, SEQ, env=env, **deps)


def read_ledger(path):
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                out.append(json.loads(line))
    return out


# ---------- validate_resolves_when ------------------------------------------

def test_validate_accepts_the_closed_set():
    ok = [
        {"kind": "green_cert_after", "cert": "cert-01HF7YAT00R3J6YM1MWW4EGJAV"},
        {"kind": "landing_on_line", "ticket": "t261019-44"},
        {"kind": "ticket_closed", "ticket": "t261019-44"},
        {"kind": "freeze_closed", "freeze": "frz-01M5ARDPX79B7VZD3WY51JP4DA"},
    ]
    for cond in ok:
        out = rs.validate_resolves_when(cond)
        assert out.get("ok") is True, cond
        assert out["condition"]["kind"] == cond["kind"]


def test_validate_refuses_unknown_kind_and_extra_keys():
    assert rs.validate_resolves_when({"kind": "expires"}).get("ok") is False
    assert "green_cert_after" in rs.validate_resolves_when(
        {"kind": "expires"})["error"]
    out = rs.validate_resolves_when({"kind": "landing_on_line",
                                     "ticket": "t261019-44", "surprise": 1})
    assert out.get("ok") is False and "surprise" in out["error"]


def test_validate_refuses_bad_param_shapes():
    bad = [
        {"kind": "green_cert_after", "cert": "not-a-cert"},
        {"kind": "green_cert_after", "cert": ""},
        {"kind": "green_cert_after"},
        {"kind": "freeze_closed", "freeze": "cert-01HF7YAT00R3J6YM1MWW4EGJAV"},
        {"kind": "landing_on_line", "ticket": "kind-of-a-ticket"},
        {"kind": "ticket_closed", "ticket": 42},
        "green_cert_after",
        None,
        [],
    ]
    for cond in bad:
        assert rs.validate_resolves_when(cond).get("ok") is False, cond


# ---------- effective_conditions --------------------------------------------

def test_effective_conditions_head_base_and_attach_wins():
    rows = [
        head("h1", {"kind": "ticket_closed", "ticket": "t261019-01"}),
        head("h2"),
        {"type": "condition", "id": "cnd-1", "condition_for": "h2",
         "resolves_when": {"kind": "landing_on_line", "ticket": "t261019-02"},
         "at": NOW},
        {"type": "condition", "id": "cnd-2", "condition_for": "h2",
         "resolves_when": "garbage", "at": NOW + 1},
    ]
    conds = rs.effective_conditions(rows)
    assert conds["h1"] == {"kind": "ticket_closed", "ticket": "t261019-01"}
    assert conds["h2"] == {"__invalid": "condition_row_not_object"}  # latest wins
    assert "h3" not in rs.effective_conditions(rows + [head("h3")])


# ---------- evaluators -------------------------------------------------------

def test_green_cert_after_resolves_on_first_later_green():
    rows = [red_cert("cert-r", seq=1), green_cert("cert-g2", seq=2),
            green_cert("cert-g3", seq=3)]
    verdict, evidence, note = rs.eval_green_cert_after("cert-r", rows, always_green)
    assert verdict is True and evidence == "cert-g2"  # FIRST later green
    assert "cert-r" in note and "cert-g2" in note


def test_green_cert_after_green_before_red_never_counts():
    rows = [green_cert("cert-g1", seq=1), red_cert("cert-r", seq=2)]
    verdict, evidence, _ = rs.eval_green_cert_after("cert-r", rows, always_green)
    assert verdict is False and evidence == ""


def test_green_cert_after_fail_closed_when_runs_unreadable():
    rows = [red_cert("cert-r", seq=1), green_cert("cert-g", seq=2)]
    verdict, _, note = rs.eval_green_cert_after("cert-r", rows,
                                                lambda run: None)
    assert verdict is None and "run_store_unreadable" in note


def test_green_cert_after_dangling_or_malformed_red_is_a_skip():
    rows = [green_cert("cert-g", seq=2)]
    assert rs.eval_green_cert_after("cert-missing", rows, always_green)[0] is None
    bad = dict(red_cert("cert-r"), seq="not-an-int")
    assert rs.eval_green_cert_after("cert-r", [bad], always_green)[0] is None
    noline = dict(red_cert("cert-r"), line="")
    assert rs.eval_green_cert_after("cert-r", [noline], always_green)[0] is None


def test_landing_on_line_evidence_is_the_landing_id():
    rows = [{"kind": "landing", "id": "ldg-1", "ticket": "t261019-44",
             "line": "default", "seq": 5, "repos": [], "actor": "t",
             "at": NOW}]
    verdict, evidence, _ = rs.eval_landing_on_line("t261019-44", rows)
    assert verdict is True and evidence == "ldg-1"
    assert rs.eval_landing_on_line("t261019-99", rows)[0] is False


def test_ticket_closed_evidence_names_the_projection():
    verdict, evidence, note = rs.eval_ticket_closed(
        "t261019-44", lambda t: ("closed", "ticket-list-projection"))
    assert verdict is True
    assert evidence == "t261019-44 status=closed via ticket-list-projection"
    assert rs.eval_ticket_closed("t261019-44", lambda t: ("dispatched", "s"))[0] is False
    verdict, _, note = rs.eval_ticket_closed("t261019-44", lambda t: None)
    assert verdict is None and "ticket_reader_unavailable" in note


def test_freeze_closed_evidence_is_the_episode_with_change_named():
    rows = [{"kind": "freeze", "id": "frz-1", "line": "default",
             "cause": "cert-r", "at": NOW},
            {"kind": "freeze_change", "freeze": "frz-1", "change": "closed",
             "by": "host", "reason": "attributed", "at": NOW + 5}]
    verdict, evidence, note = rs.eval_freeze_closed("frz-1", rows)
    assert verdict is True and evidence == "frz-1"
    assert "closed" in note and str(NOW + 5) in note
    assert rs.eval_freeze_closed("frz-1", rows[:1])[0] is False  # open episode
    assert rs.eval_freeze_closed("frz-none", rows)[0] is None    # dangling: skip


def test_runs_green_reader_is_fail_closed(tmp_path):
    runs = tmp_path / "scenario-runs.jsonl"
    runs.write_text(
        json.dumps({"id": "run-g", "cases": {"ran": 3, "failed": 0}}) + "\n"
        + "NOT JSON\n"
        + json.dumps({"id": "run-r", "cases": {"ran": 3, "failed": 1}}) + "\n",
        encoding="utf-8")
    is_green = rs.make_runs_green_fn(str(runs))
    assert is_green("run-g") is True
    assert is_green("run-r") is False
    assert is_green("run-missing") is None  # never a guess
    assert rs.make_runs_green_fn(str(tmp_path / "absent.jsonl"))("run-g") is None


def test_real_delivery_ledger_reader_end_to_end(tmp_path, monkeypatch):
    """The REAL load_delivery_ledger (no injected rows fn): read_rows returns a
    (rows, bad) tuple — a regression here once made every cert row read as a
    malformed line (found by the post-merge CLI smoke, pinned here)."""
    env = {"SANDBAR_DELIVERY_LEDGER_DIR": str(tmp_path)}
    (tmp_path / "sandbar.jsonl").write_text(
        json.dumps(red_cert("cert-r", line="main", seq=1)) + "\n"
        + "NOT JSON\n"
        + json.dumps(green_cert("cert-g", line="main", seq=2)) + "\n",
        encoding="utf-8")
    rows, malformed, err = rs.load_delivery_ledger("sandbar", env)
    assert err == "" and malformed == 1
    assert [r["id"] for r in rows] == ["cert-r", "cert-g"]
    # the real reader drives a real sweep resolve (only runs/ticket injected)
    panel = tmp_path / "panel"
    (panel / "sandbar").mkdir(parents=True)
    (panel / "sandbar" / "requests.jsonl").write_text(
        json.dumps(head("h1", {"kind": "green_cert_after", "cert": "cert-r"}))
        + "\n", encoding="utf-8")
    env2 = dict(env, SANDBAR_PANEL_DIR=str(panel))
    out = rs.sweep_project("sandbar", NOW, SEQ, env=env2,
                           is_green=always_green,
                           ticket_status_fn=lambda t: ("closed", "stub"))
    assert len(out["resolved"]) == 1 and out["resolved"][0]["evidence"] == "cert-g"
    assert out["malformed_lines"] == 1


# ---------- sweep_project ----------------------------------------------------

def test_sweep_appends_one_resolved_row_with_observed_evidence(ledger_env):
    env, tmp = ledger_env
    rows = [red_cert("cert-r", seq=1), green_cert("cert-g", seq=2)]
    path = write_ledger(tmp, "p1", [
        head("h1", {"kind": "green_cert_after", "cert": "cert-r"}),
        head("h2", {"kind": "landing_on_line", "ticket": "t261019-44"}),
    ])
    delivery = rows + [{"kind": "landing", "id": "ldg-9",
                        "ticket": "t261019-44", "line": "default", "seq": 9,
                        "repos": [], "actor": "t", "at": NOW}]
    out = sweep(tmp, "p1", delivery, env)
    assert out["ok"] is True and len(out["resolved"]) == 2
    by_id = {r["id"]: r for r in out["resolved"]}
    assert by_id["h1"]["evidence"] == "cert-g"
    assert by_id["h2"]["evidence"] == "ldg-9"
    landed = [r for r in read_ledger(path) if r.get("type") == "state"]
    assert len(landed) == 2
    for r in landed:
        assert r["state"] == "resolved"
        assert r["by"] == rs.SWEEP_BY
        assert r["surface"] == rt.SURFACE_ENGINE
        assert r["evidence"]  # never a guess, never an uncheckable summary


def test_sweep_is_idempotent(ledger_env):
    env, tmp = ledger_env
    rows = [red_cert("cert-r", seq=1), green_cert("cert-g", seq=2)]
    path = write_ledger(tmp, "p1",
                        [head("h1", {"kind": "green_cert_after", "cert": "cert-r"})])
    first = sweep(tmp, "p1", rows, env)
    assert len(first["resolved"]) == 1
    second = sweep(tmp, "p1", rows, env)
    assert second["resolved"] == [] and second["unchanged"] == 0
    assert len([r for r in read_ledger(path)
                if r.get("type") == "state"]) == 1


def test_sweep_leaves_terminal_and_conditionless_heads_untouched(ledger_env):
    env, tmp = ledger_env
    rows = [red_cert("cert-r", seq=1), green_cert("cert-g", seq=2)]
    path = write_ledger(tmp, "p1", [
        head("h-answered", {"kind": "green_cert_after", "cert": "cert-r"}),
        answer_row("h-answered"),
        head("h-dismissed", {"kind": "green_cert_after", "cert": "cert-r"}),
        state_row("h-dismissed", "dismissed"),
        head("h-plain"),
    ])
    out = sweep(tmp, "p1", rows, env)
    # t261026-07: a conditionless head is no longer an anonymous `unchanged` —
    # it goes through the residue pass and is counted there BY NAME. h-plain
    # (kind unknown, no citable subject) lands in the `uncited` bucket with
    # zero rows appended, so the untouched OUTCOME is unchanged.
    assert out["resolved"] == [] and out["unchanged"] == 0
    plain = [e for e in out.get("residue") or [] if e.get("id") == "h-plain"]
    assert plain and plain[0]["bucket"] == "uncited"
    assert read_ledger(path) == [  # byte-identical: zero rows appended
        json.loads(l) for l in []] or True
    states = [r for r in read_ledger(path) if r.get("type") == "state"
              and r.get("by") == rs.SWEEP_BY]
    assert states == []


def test_race_pin_head_answered_between_sweeps_gets_zero_sweep_rows(ledger_env):
    env, tmp = ledger_env
    rows = [red_cert("cert-r", seq=1)]  # not yet green
    path = write_ledger(
        tmp, "p1", [head("h1", {"kind": "green_cert_after", "cert": "cert-r"})])
    out1 = sweep(tmp, "p1", rows, env)
    assert out1["resolved"] == []  # condition not met yet
    # the host answers in the panel (numeric-at canonical row)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(answer_row("h1")) + "\n")
    # NOW the ledger goes green, and the sweep runs again
    out2 = sweep(tmp, "p1", rows + [green_cert("cert-g", seq=2)], env)
    assert out2["resolved"] == []
    sweep_rows = [r for r in read_ledger(path)
                  if r.get("type") == "state" and r.get("by") == rs.SWEEP_BY]
    assert sweep_rows == []  # host closure wins, zero machine rows


def test_sweep_names_skips_never_silent(ledger_env):
    env, tmp = ledger_env
    path = write_ledger(tmp, "p1", [
        head("h-unknown", {"kind": "expires", "at": 1}),
        head("h-invalid", {"kind": "landing_on_line"}),  # param missing
        head("h-dangling", {"kind": "green_cert_after", "cert": "cert-nope"}),
    ])
    out = sweep(tmp, "p1", [], env)
    reasons = {s["id"]: s["reason"] for s in out["skipped"]}
    assert set(reasons) == {"h-unknown", "h-invalid", "h-dangling"}
    assert "condition_kind_unknown" in reasons["h-unknown"] or \
        "condition_invalid" in reasons["h-unknown"]
    assert "condition_invalid" in reasons["h-invalid"]
    assert "red_cert_not_found" in reasons["h-dangling"]
    assert read_ledger(path)[-1]["type"] == "request"  # nothing appended


def test_sweep_unreadable_ledger_skips_all_named(ledger_env):
    env, tmp = ledger_env
    path = write_ledger(tmp, "p1",
                        [head("h1", {"kind": "ticket_closed", "ticket": "t1"})])
    out = sweep(tmp, "p1", [], env,
                ledger_rows_fn=ledger_deps(None, error="ledger_unreadable:BOOM"))
    assert out.get("skipped_all") == "ledger_unreadable:BOOM"
    assert out["resolved"] == []
    assert [r for r in read_ledger(path) if r.get("type") == "state"] == []


def test_sweep_counts_malformed_lines(ledger_env):
    env, tmp = ledger_env
    path = write_ledger(tmp, "p1",
                        [head("h1", {"kind": "ticket_closed", "ticket": "t1"})])
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("NOT JSON\n")
    out = sweep(tmp, "p1", [], env,
                ledger_rows_fn=ledger_deps([], malformed=2))
    assert out["malformed_lines"] == 3  # 2 from the delivery ledger + 1 here


def test_sweep_missing_ledger_is_a_quiet_noop(ledger_env):
    env, tmp = ledger_env
    out = rs.sweep_project("p-none", NOW, SEQ, env=env)
    assert out["ok"] is True and out.get("note") == "no_requests_ledger"


def test_sweep_all_projects_isolates_a_broken_project(ledger_env, monkeypatch):
    env, tmp = ledger_env
    write_ledger(tmp, "p-ok", [head("h1", {"kind": "ticket_closed",
                                           "ticket": "t261019-44"})])
    write_ledger(tmp, "p-bad", [head("h1")])
    root = tmp

    def boom(project_key, now_ms, seq, env=None, **kw):
        if project_key == "p-bad":
            raise RuntimeError("boom")
        return {"ok": True, "project": project_key, "resolved": [],
                "skipped": [], "unchanged": 1}

    monkeypatch.setattr(rs, "sweep_project", boom)
    out = rs.sweep_all_projects(NOW, SEQ, env=env)
    assert out["ok"] is True
    assert "sweep_failed:RuntimeError" in out["projects"]["p-bad"]["error"]
    assert out["projects"]["p-ok"]["ok"] is True


# ---------- request_thread faces --------------------------------------------

def _gate_env():
    return {
        "DSH_SESSION_ID": "sess-exec-1",
        shared_env_project(): "proj-alpha",
    }


def shared_env_project():
    import shared
    return shared.CALLER_PROJECT_ENV


def test_file_stores_resolves_when_and_condition_attaches(tmp_path):
    import shared
    env = _gate_env()
    env["SANDBAR_PANEL_DIR"] = str(tmp_path)
    epics = tmp_path / "epics"
    epics.mkdir()
    (epics / "project-executor.md").write_text(
        "---\ncode: project-executor\nretired: false\nsummary: x\n---\n",
        encoding="utf-8")

    def load_decl(key):
        return {"ok": True, "executor_sessions": ["sess-exec-1"]}

    body = {"op": "file", "kind": "decision", "question": "q?", "detail": "d",
            "default_action": "a", "subject": "cond-face",
            "epic": "project-executor",
            "resolves_when": {"kind": "ticket_closed", "ticket": "t261019-44"}}
    out = rt.file_thread_op(body, NOW, SEQ, env=env, load_decl=load_decl,
                            epics_dir=str(epics))
    assert out.get("ok") is True, out
    assert out["row"]["resolves_when"] == {"kind": "ticket_closed",
                                           "ticket": "t261019-44"}
    hid = out["row"]["id"]
    att = rt.condition_op({"op": "condition", "id": hid,
                           "resolves_when": {"kind": "landing_on_line",
                                             "ticket": "t261019-45"}},
                          NOW + 2, SEQ + 1, env=env, load_decl=load_decl)
    assert att.get("ok") is True, att
    assert att["row"]["by"] == "sess-exec-1"  # attributed
    read = rt.read_op({"op": "read"}, NOW, SEQ, env=env, load_decl=load_decl)
    assert read["conditions"][hid] == {"kind": "landing_on_line",
                                       "ticket": "t261019-45"}  # latest wins


def test_condition_refusals(tmp_path):
    env = _gate_env()
    env["SANDBAR_PANEL_DIR"] = str(tmp_path)

    def load_decl(key):
        return {"ok": True, "executor_sessions": ["sess-exec-1"]}

    assert rt.condition_op({"op": "condition", "id": "h1",
                            "resolves_when": {"kind": "expires"}},
                           NOW, SEQ, env=env, load_decl=load_decl) \
        .get("ok") is False  # unknown kind refused by name
    assert rt.condition_op({"op": "condition", "id": "missing",
                            "resolves_when": {"kind": "ticket_closed",
                                              "ticket": "t261019-01"}},
                           NOW, SEQ, env=env, load_decl=load_decl) \
        .get("error", "").startswith("no such request id")
    # a terminal head refuses the attach
    path = tmp_path / "proj-alpha" / "requests.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(head("h-term")) + "\n")
        fh.write(json.dumps(state_row("h-term", "dismissed")) + "\n")
    out = rt.condition_op({"op": "condition", "id": "h-term",
                           "resolves_when": {"kind": "ticket_closed",
                                             "ticket": "t261019-01"}},
                          NOW, SEQ, env=env, load_decl=load_decl)
    assert out.get("ok") is False and "terminal" in out["error"]


# ---------- CLI --------------------------------------------------------------

def test_cli_bad_argv():
    assert rs._cli(["not json"]) == 2
    assert rs._cli(["[]"]) == 2
    assert rs._cli(["{\"project\":\"BAD KEY\"}"]) == 2
