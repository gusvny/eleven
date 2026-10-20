# -*- coding: utf-8 -*-
"""t261019-25 — run watch over the delivery ledger (unit tier).

Covers the decision table of docs/design/executor-operational-envelope-v1 §1
against fixture records only (no real ledgers, no Temporal, no integration
entries): green/no-op, content red, the MIXED red (review C1), the env-only
red in all three shapes (open freeze + releasing green -> closure; open freeze
without one -> fix ticket; no freeze without a later green -> fix ticket; no
freeze with a later green -> nothing), run-stalled, the silent round (retry
once, then run-silent), and the mandatory malformed-input set (torn ledger
line, corrupt state file, unreadable case rows, missing run header, request
without a declared executor session). Every write is read BACK through the
real writers (review C3): the receipt is not evidence.
"""
import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

ENGINE = str(Path(__file__).resolve().parents[1])
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

import run_watch  # noqa: E402
import develop_certify  # noqa: E402


# ---------- fixture builders (records only, no engine globals) ----------


def _ledger(project, d):
    return Path(d) / ("%s.jsonl" % project)


def _append(path, rows):
    res = develop_certify.append_rows(rows, path)
    assert res["written"] == len(rows), res
    return res


def _landing(line, ticket, at, seq_hint=None):
    return {"kind": "landing", "id": "ldg-%s-%s" % (line, ticket),
            "ticket": ticket, "line": line,
            "repos": [{"repo": "r", "revision": "a" * 12}],
            "at": at, "actor": "test"}


def _cert(line, run, booked="baseline@x"):
    return {"kind": develop_certify.KIND_CERT, "id": "cert-%s" % run, "line": line,
            "repos": [{"repo": "r", "revision": "a" * 12}], "run": run,
            "booked_red": booked, "judged_by": "test", "at": 1}


def _freeze(line, cert_id):
    return {"kind": "freeze", "id": "frz-%s" % cert_id, "line": line,
            "cause": cert_id, "at": 1}


def _header(run, verdict, failed=0, env_failed=0, ran=2):
    passed = ran - failed - env_failed
    return {"v": "run-ledger-v1", "id": run,
            "repos": [{"repo": "r", "revision": "a" * 12}], "suite": "full",
            "source": "scheduled", "env_fp": "0" * 64, "conc_width": 1,
            "pool": "p", "started_at": 1, "duration_s": 1.0,
            "cases": {"ran": ran, "passed": passed, "failed": failed,
                      "env_failed": env_failed},
            "verdict": verdict}


def _case(run, scenario, verdict):
    return {"run": run, "scenario": scenario, "verdict": verdict}


def _face(run, state="done", verdict=None, reason=""):
    d = {"run_id": run, "line": "default", "state": state,
         "started_at": "2026-10-19T00:00:00Z",
         "updated_at": "2026-10-19T01:00:00Z"}
    if state in ("done", "failed"):
        d["outcome"] = {"verdict": verdict, "reason": reason}
    return d


def _write_face(rounds_dir, run, face):
    d = rounds_dir / run
    d.mkdir(parents=True, exist_ok=True)
    (d / "face.json").write_text(json.dumps(face), encoding="utf-8")


class World:
    """One isolated instance: delivery ledger dir, projects root (line
    declaration), rounds dir, scenario-ledger dir — all env-pinned."""

    def __init__(self, tmp_path, monkeypatch):
        self.tmp = tmp_path
        self.projects = tmp_path / "projects"
        self.ledger_dir = tmp_path / "delivery"
        self.rounds = tmp_path / "rounds"
        self.scen = tmp_path / "scenario"
        for p in (self.projects, self.ledger_dir, self.rounds, self.scen):
            p.mkdir(parents=True)
        decl = self.projects / "p1" / "data" / "develop"
        decl.mkdir(parents=True)
        (decl / "lines.json").write_text(json.dumps([
            {"line_id": "default", "scope": "test", "owner": "test",
             "repositories": [{"name": "r", "branch": "main"}]}]),
            encoding="utf-8")
        # a declared executor session, so the watch may file requests
        (self.projects / "p1" / "executor-grants.json").write_text(
            json.dumps({"version": 1, "grants": {},
                        "executor_sessions": ["sess-exec-1"]}),
            encoding="utf-8")
        self.ledger = _ledger("p1", self.ledger_dir)
        for key, val in (("DSH_HOME", str(tmp_path / "dsh-home")),
                         ("SANDBAR_PROJECTS_DIR", str(self.projects)),
                         ("SANDBAR_DELIVERY_LEDGER_DIR", str(self.ledger_dir)),
                         ("SANDBAR_LINE_ROUND_FACE_DIR", str(self.rounds)),
                         ("SANDBAR_SCENARIO_LEDGER_DIR", str(self.scen))):
            monkeypatch.setenv(key, val)

    # -- record writes ------------------------------------------------
    def land(self, ticket, at):
        _append(self.ledger, [_landing("default", ticket, at)])

    def certify(self, run, verdict, failed=0, env_failed=0):
        _append(self.ledger, [_cert("default", run)])
        self.header(run, verdict, failed, env_failed)

    def header(self, run, verdict, failed=0, env_failed=0, ran=2):
        with open(self.ledger.parent / run_watch.RUNS_NAME, "a",
                  encoding="utf-8") as fh:
            fh.write(json.dumps(_header(run, verdict, failed, env_failed, ran))
                     + "\n")

    def open_freeze(self, cert_id):
        _append(self.ledger, [_freeze("default", cert_id)])

    def green_cert(self, run):
        # a green certification AFTER the red, same line
        _append(self.ledger, [_cert("default", run)])
        self.header(run, "green")

    def case_rows(self, rows):
        with open(self.scen / "scenario-results.jsonl", "a",
                  encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")

    def face(self, run, **kw):
        _write_face(self.rounds, run, _face(run, **kw))

    # -- reads --------------------------------------------------------
    def rows(self):
        rows, _bad = develop_certify.read_rows(self.ledger)
        return rows

    def request_rows(self):
        # the instance root the watch itself resolves (executor_requests.ledger_root,
        # honoured through the same env the tick ran with)
        import executor_requests
        f = executor_requests.ledger_root() / "p1" / "requests.jsonl"
        if not f.exists():
            return []
        return [json.loads(l) for l in
                f.read_text(encoding="utf-8").splitlines() if l.strip()]

    def digest(self, path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def watch(self, now_ms, **kw):
        return run_watch.run_watch_tick("p1", now_ms=now_ms, **kw)

    def decisions(self, result):
        return {l["line"]: {**l.get("decision", {}), "result": l.get("result")}
                for l in result["lines"]}


# ---------- decision-table tests ----------


def test_green_cert_means_nothing_and_writes_nothing(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.land("t1", 1000)
    w.certify("run-g1", "green")
    before = w.digest(w.ledger)
    res = w.watch(now_ms=2000)
    d = w.decisions(res)["default"]
    assert d["action"] == "none"
    assert w.digest(w.ledger) == before  # read-only proof: nothing written
    assert not (w.ledger_dir / run_watch.STATE_NAME).exists()


def test_content_red_opens_fix_ticket_and_reuses(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.certify("run-r1", "red", failed=2)
    w.case_rows([_case("run-r1", "sc-a", "fail"), _case("run-r1", "sc-b", "fail")])
    started = []

    def seam(project, action, at_ms):
        started.append(action["run_id"])
        return {"ok": True, "ticket_id": "tX-1"}

    res = w.watch(now_ms=2000, start_fix_ticket=seam,
                  retry_round=lambda p: {"ok": True})
    d = w.decisions(res)["default"]
    assert d["action"] == "fix_ticket"
    assert d["kind"] == "content"
    assert sorted(d["names"]) == ["sc-a", "sc-b"]
    assert d["evidence"]["run"] == "run-r1"
    assert d["evidence"]["red_cert"] == "cert-run-r1"
    assert started == ["run-r1"]
    # second tick: the state memory reuses; the seam is NOT called again
    res2 = w.watch(now_ms=3000, start_fix_ticket=seam,
                   retry_round=lambda p: {"ok": True})
    d2 = w.decisions(res2)["default"]
    assert started == ["run-r1"]
    assert d2["result"]["reused"] is True


def test_mixed_red_is_content_never_closure(tmp_path, monkeypatch):
    """Review C1: a red with BOTH kinds is a content red (env-only gate needs
    failed == 0) — it opens a fix ticket even with a releasing green around."""
    w = World(tmp_path, monkeypatch)
    w.certify("run-m1", "red", failed=1, env_failed=1)
    w.case_rows([_case("run-m1", "sc-content", "fail"),
                 _case("run-m1", "sc-bench", "env_fail")])
    w.open_freeze("cert-run-m1")

    def seam(project, action, at_ms):
        return {"ok": True, "ticket_id": "tX-2"}

    res = w.watch(now_ms=2000, start_fix_ticket=seam,
                  retry_round=lambda p: {"ok": True})
    d = w.decisions(res)["default"]
    assert d["action"] == "fix_ticket"
    assert d["kind"] == "content"
    assert "sc-content" in d["names"]
    assert d["result"]["ok"] is True


def test_env_only_red_with_freeze_and_releasing_green_closes(tmp_path, monkeypatch):
    """The closure goes through the engine's own releasing rule and is read
    BACK from the ledger (review C3): the closed change row must cite the
    releasing green certification by id."""
    w = World(tmp_path, monkeypatch)
    w.certify("run-e1", "red", failed=0, env_failed=1)
    w.case_rows([_case("run-e1", "capture-bench", "env_fail")])
    w.open_freeze("cert-run-e1")
    w.green_cert("run-g2")
    res = w.watch(now_ms=2000, retry_round=lambda p: {"ok": True},
                  start_fix_ticket=lambda *a: {"ok": False, "error": "must-not-open"})
    d = w.decisions(res)["default"]
    assert d["action"] == "close_freeze"
    assert d["evidence"]["releasing_cert"] == "cert-run-g2"
    assert d["env_faces"] == ["capture-bench"]
    assert d["result"]["ok"] is True
    # read-back: the row exists and cites the releasing cert
    changes = [r for r in w.rows() if r.get("kind") == develop_certify.KIND_FREEZE_CHANGE
               and r.get("change") == "closed"]
    assert len(changes) == 1
    assert changes[0]["freeze"] == "frz-cert-run-e1"
    assert changes[0]["value"] == "cert-run-g2"
    assert changes[0]["by"] == "run-watch"
    # and the state machine agrees the freeze is now closed
    assert develop_certify.freeze_state(w.rows(), "default")["frozen"] is False


def test_env_only_red_freeze_without_releasing_green_opens_ticket(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.certify("run-e2", "red", failed=0, env_failed=1)
    w.case_rows([_case("run-e2", "bench-x", "env_fail")])
    w.open_freeze("cert-run-e2")
    res = w.watch(now_ms=2000, start_fix_ticket=lambda p, a, t: {"ok": True,
                                                                 "ticket_id": "tX-3"},
                  retry_round=lambda p: {"ok": True})
    d = w.decisions(res)["default"]
    assert d["action"] == "fix_ticket"
    assert d["kind"] == "environment"
    assert d["names"] == ["bench-x"]


def test_env_only_red_no_freeze_with_later_green_is_released(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.certify("run-e3", "red", failed=0, env_failed=1)
    w.case_rows([_case("run-e3", "bench-y", "env_fail")])
    w.green_cert("run-g3")
    before = w.digest(w.ledger)
    res = w.watch(now_ms=2000, start_fix_ticket=lambda *a: pytest.fail("must not open"),
                  retry_round=lambda p: pytest.fail("must not retry"))
    d = w.decisions(res)["default"]
    assert d["action"] == "none"
    assert w.digest(w.ledger) == before


def test_env_only_red_no_freeze_no_later_green_opens_ticket(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.certify("run-e4", "red", failed=0, env_failed=2)
    w.case_rows([_case("run-e4", "bench-z", "env_fail")])
    res = w.watch(now_ms=2000, start_fix_ticket=lambda p, a, t: {"ok": True,
                                                                 "ticket_id": "tX-4"},
                  retry_round=lambda p: {"ok": True})
    d = w.decisions(res)["default"]
    assert d["action"] == "fix_ticket"
    assert d["kind"] == "environment"


def test_stalled_landings_file_run_stalled_request_once(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.certify("run-s1", "green")
    old = 1000  # far older than any sane N-hours threshold
    w.land("t9", old)
    res = w.watch(now_ms=old + 7 * 3600 * 1000)
    d = w.decisions(res)["default"]
    assert d["action"] == "request"
    assert d["request_kind"] == "run-stalled"
    assert d["evidence"]["last_round"] == "run-s1"
    assert d["evidence"]["pending_landings"] == ["ldg-default-t9"]
    rows = w.request_rows()
    assert len(rows) == 1
    assert rows[0]["kind"] == "run-stalled"
    # second tick with the same evidence: deduped, no second row
    res2 = w.watch(now_ms=old + 8 * 3600 * 1000)
    assert w.decisions(res2)["default"]["result"]["reused"] is True
    assert len(w.request_rows()) == 1


def test_fresh_landing_within_n_hours_is_not_stalled(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.certify("run-s2", "green")
    now = 10_000_000_000
    w.land("t8", now - 1000)
    res = w.watch(now_ms=now)
    assert w.decisions(res)["default"]["action"] == "none"


def test_silent_round_retries_once_then_requests(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.face("run-silent1", state="failed", verdict=None, reason="runner died")
    retries = []

    def retry(project):
        retries.append(project)
        return {"ok": True}

    res = w.watch(now_ms=2000, retry_round=retry)
    d = w.decisions(res)["default"]
    assert d["action"] == "retry_round"
    assert retries == ["p1"]
    # second tick: still no row -> run-silent request
    res2 = w.watch(now_ms=3000, retry_round=retry)
    d2 = w.decisions(res2)["default"]
    assert d2["action"] == "request"
    assert d2["request_kind"] == "run-silent"
    assert d2["evidence"]["round"] == "run-silent1"
    assert len(retries) == 1
    assert len(w.request_rows()) == 1


def test_silent_then_row_appears_is_no_request(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.face("run-ok1", state="done", verdict="red")
    w.watch(now_ms=2000, retry_round=lambda p: {"ok": True})  # retry #1
    w.header("run-ok1", "red", failed=1)  # the row lands between ticks
    res = w.watch(now_ms=3000, retry_round=lambda p: {"ok": True},
                  start_fix_ticket=lambda p, a, t: {"ok": True, "ticket_id": "tX-5"})
    d = w.decisions(res)["default"]
    assert d["action"] != "request"  # the round answered; never a silent accept


def test_red_action_wins_over_stalled(tmp_path, monkeypatch):
    """Exactly-one-action: a red face AND a stale pending landing both hold —
    the red wins (precedence in spec order)."""
    w = World(tmp_path, monkeypatch)
    w.certify("run-r9", "red", failed=1)
    w.case_rows([_case("run-r9", "sc-x", "fail")])
    w.land("t7", 1000)
    res = w.watch(now_ms=1000 + 99 * 3600 * 1000,
                  start_fix_ticket=lambda p, a, t: {"ok": True, "ticket_id": "tX-6"},
                  retry_round=lambda p: {"ok": True})
    d = w.decisions(res)["default"]
    assert d["action"] == "fix_ticket"


# ---------- malformed-input set (mandatory) ----------


def test_torn_ledger_line_is_named_not_swallowed(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.certify("run-g9", "green")
    with open(w.ledger, "a", encoding="utf-8") as fh:
        fh.write("{not json\n")
    res = w.watch(now_ms=2000)
    assert res.get("ledger_malformed_lines")
    assert w.decisions(res)["default"]["action"] in ("none", "request",
                                                     "retry_round")


def test_corrupt_state_file_treated_empty_and_named(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.certify("run-r2", "red", failed=1)
    w.case_rows([_case("run-r2", "sc-c", "fail")])
    (w.ledger_dir / run_watch.STATE_NAME).write_text("{broken", encoding="utf-8")
    res = w.watch(now_ms=2000, start_fix_ticket=lambda p, a, t: {"ok": True,
                                                                 "ticket_id": "tX-7"},
                  retry_round=lambda p: {"ok": True})
    assert "state_note" in res
    assert w.decisions(res)["default"]["action"] == "fix_ticket"  # fail toward re-action


def test_missing_case_rows_fail_toward_fix_ticket(tmp_path, monkeypatch):
    """Review R4: env-only can only be classified on present evidence — with
    the case rows rolled away, an open freeze with a releasing green is NOT
    closed; the watch opens the fix ticket instead."""
    w = World(tmp_path, monkeypatch)
    w.certify("run-e9", "red", failed=0, env_failed=1)
    w.open_freeze("cert-run-e9")
    w.green_cert("run-g9b")
    res = w.watch(now_ms=2000, start_fix_ticket=lambda p, a, t: {"ok": True,
                                                                 "ticket_id": "tX-8"},
                  retry_round=lambda p: {"ok": True})
    d = w.decisions(res)["default"]
    assert d["action"] == "fix_ticket"  # never a records-only closure


def test_red_cert_with_missing_run_header_is_named_anomaly(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    _append(w.ledger, [_cert("default", "run-ghost")])  # no header anywhere
    res = w.watch(now_ms=2000, start_fix_ticket=lambda *a: pytest.fail("no"),
                  retry_round=lambda p: {"ok": True})
    d = w.decisions(res)["default"]
    assert d["action"] in ("none", "request", "retry_round")
    assert any(a.startswith("latest_cert_run_header_missing") for a in d.get("anomalies", []))


def test_request_without_declared_executor_session_refuses_named(tmp_path, monkeypatch):
    """The watch files requests under the project's DECLARED executor session;
    with none declared it refuses by name and writes nothing (fail-closed)."""
    w = World(tmp_path, monkeypatch)
    (w.projects / "p1" / "executor-grants.json").unlink()  # no session named
    w.certify("run-s5", "green")
    w.land("t5", 1000)
    res = w.watch(now_ms=1000 + 99 * 3600 * 1000)
    d = w.decisions(res)["default"]
    assert d["action"] == "request"
    assert d["result"]["ok"] is False
    assert "no_declared_executor_session" in (d["result"].get("error") or "")
    assert w.request_rows() == []


def test_close_freeze_row_refuses_a_content_red(tmp_path, monkeypatch):
    """Defence in depth: the closure write itself re-checks the header counts
    and refuses a content red, whatever the caller asks for."""
    w = World(tmp_path, monkeypatch)
    w.certify("run-c1", "red", failed=1)
    w.open_freeze("cert-run-c1")
    w.green_cert("run-c2")
    res = run_watch.close_freeze_row(
        "p1", {"freeze": "frz-cert-run-c1", "red_cert": "cert-run-c1",
               "run": "run-c1", "line": "default"}, 2000)
    assert res["ok"] is False
    assert "content_regression_present" in res["error"]
    assert develop_certify.freeze_state(w.rows(), "default")["frozen"] is True


def test_close_freeze_row_refuses_without_releasing_green(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.certify("run-c3", "red", failed=0, env_failed=1)
    w.open_freeze("cert-run-c3")
    res = run_watch.close_freeze_row(
        "p1", {"freeze": "frz-cert-run-c3", "red_cert": "cert-run-c3",
               "run": "run-c3", "line": "default"}, 2000)
    assert res["ok"] is False
    assert "no_releasing_green_cert" in res["error"]


def test_stalled_hours_env_malformed_falls_back_named(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    monkeypatch.setenv("SANDBAR_RUN_WATCH_STALLED_HOURS", "banana")
    ms, note = run_watch.stalled_ms_from_env()
    assert note.startswith("stalled_hours_override_malformed")
    assert ms == run_watch.STALLED_HOURS_DEFAULT * 3600.0 * 1000.0


def test_runs_store_malformed_line_is_named(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    w.certify("run-g4", "green")
    with open(w.ledger_dir / run_watch.RUNS_NAME, "a", encoding="utf-8") as fh:
        fh.write("]\n")
    res = w.watch(now_ms=2000)
    assert res.get("runs_store_malformed_lines")


def test_engine_level_tick_survives_a_broken_project(tmp_path, monkeypatch):
    """One project's failure is an entry, never the pass's death (the tick
    contract the watch takes over)."""
    w = World(tmp_path, monkeypatch)
    w.certify("run-g5", "green")
    # a second project dir with a BROKEN line declaration
    bad = w.projects / "pbad" / "data" / "develop"
    bad.mkdir(parents=True)
    (bad / "lines.json").write_text("{nope", encoding="utf-8")
    res = run_watch.run_watch_tick_engine(now_ms=2000)
    assert "pbad" in res["projects"]
    assert "unreadable" in res["projects"]["pbad"]["summary"]
    assert res["projects"]["p1"]["lines"][0]["decision"]["action"] == "none"
