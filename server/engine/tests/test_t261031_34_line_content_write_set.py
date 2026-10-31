#!/usr/bin/env python3
"""t261031-34 (KI-447) L1: landed line content is not a write-set violation, and
the own-pointed battery's line-vs-main shape decision is a NAMED one.

The defect (measured 261031 on t261031-17, a develop-buffer line ticket whose lane
is based on the line):

  1. the quickmanual merge_check write-set item reported the out-of-write-set
     verdict for server/engine/dev_lane.py while the engine's own foreign face said "mixed
     authorship: merge e7400c7 and lane commit bb6635b both authored this path —
     a human decides", and bb6635b is a LINE LANDING commit ("landing t261029-18
     onto line develop-buffer (sandbar): rev e59c7122aef4"). The content is line
     content, not the ticket's work; the write-set item compares against main, so
     every line-based lane looks foreign;
  2. three battery tests that are green on main were red inside that lane, because
     their "un-patched replay sends the declared scope alone" assertion encodes
     MAIN's code shape (main unions at the call site; the line unions inside the
     single writer `_integ_run_args`, so its un-patched path carries the union).

What this battery pins (one case group per ticket deliverable):

  A  a path authored by a LANDING commit of the ticket's declared line is NOT
     foreign — decided by authorship, named on the record (write-set whitelist on
     a real temp git repo reproducing the measured topology, and the engine's own
     foreign-repair population over the same tree);
  B  a path the TICKET authored outside its write set IS foreign (the landing rule
     is not an amnesty for the ticket's own plain commit);
  C  a genuinely foreign path (main-only content, edited by the ticket) IS foreign;
  D  the ambiguous population is NAMED: a landing of ANOTHER line, no declared
     line, and an unparsable landing-shaped subject still judge, and say why. The
     named escape survives; the landing-authored case does not reach it;
  E  the battery-shape decision: option (ii) — the un-patched "declared scope
     alone" case is declared MAIN-SHAPE-ONLY with a NAMED skip at run time, and the
     behavioural claim stays pinned by a shape-independent case. Both battery files
     must carry the named skip and the pin, and the pre-patch branch of the real
     `_quick_gate_round` must hand the DECLARED list to the writer (that is what a
     recorded history replays);
  F  wiring: the real merge_check passes the declared line to verify_lane and to
     the repair population, an old payload defaults to the pre-fix caliber, and an
     automatic conflict resolution that authored a shared engine file is NAMED on
     the receipt.

Offline, temp dirs only, zero network, zero Temporal, zero docker, never touches
3099/7233. Run:
  server/engine/.venv/bin/python -m pytest \
    server/engine/tests/test_t261031_34_line_content_write_set.py -q
"""
import asyncio
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent
sys.path.insert(0, str(ENGINE))
sys.path.insert(0, str(ENGINE.parent / "tools"))

import agent_activities as aa  # noqa: E402
import dev_lane  # noqa: E402
import shared  # noqa: E402
import verify_lane as vl  # noqa: E402

LINE = "develop"
LINE_ID = "develop-buffer"
OTHER_LINE_ID = "some-other-line"
LANE = "lane/t261031-34"
TID = "t261031-34"

WRITE_SET = ["own/"]

#: The measured shape: a shared engine file the line landed and a main sync then
#: merged (a third blob — neither side's version).
LINE_LANDED = "server/engine/dev_lane.py"
#: The ticket's own out-of-write-set write.
TICKET_WROTE = "server/engine/agent_activities.py"
#: A path only MAIN has, which the ticket then edited (genuinely foreign).
MAIN_ONLY = "server/engine/main_only_tool.py"
#: A path authored by a landing of ANOTHER line: the evidence cannot decide.
OTHER_LINE_PATH = "server/engine/shared.py"
#: The ticket's lawful write (inside its write set).
OWN = "own/own.txt"

LANDING_MAIN = ("landing t261029-18 onto line %s (sandbar): rev "
                "e59c7122aef4" % LINE_ID)
LANDING_OTHER = ("landing t261099-99 onto line %s (sandbar): rev "
                 "0123456789ab" % OTHER_LINE_ID)
CONFLICT_COMMIT = "%s conflict resolution (round 0): worker-settled merge commit" % TID


# ---------------- real-git fixture helpers ----------------

def _git(root, *args, env=None):
    p = subprocess.run(["git"] + list(args), cwd=str(root), capture_output=True,
                       text=True, env=env)
    assert p.returncode == 0, "git %s failed: %s" % (" ".join(args), p.stderr)
    return p.stdout


def _stamp(root, *args, date):
    env = dict(os.environ, GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date,
               GIT_COMMITTER_NAME=TID, GIT_COMMITTER_EMAIL="t@%s" % TID,
               GIT_AUTHOR_NAME=TID, GIT_AUTHOR_EMAIL="t@%s" % TID)
    return _git(root, *args, env=env)


def _commit(root, msg, date):
    _git(root, "add", "-A")
    _stamp(root, "commit", "-qm", msg, date=date)
    return _git(root, "rev-parse", "HEAD").strip()


def _merge_no_commit(root, ref, date):
    """A real conflict is the point: git exits 1 and leaves the markers, exactly as
    the worker's resolution round finds them."""
    env = dict(os.environ, GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date,
               GIT_COMMITTER_NAME=TID, GIT_COMMITTER_EMAIL="t@%s" % TID,
               GIT_AUTHOR_NAME=TID, GIT_AUTHOR_EMAIL="t@%s" % TID)
    p = subprocess.run(["git", "merge", "-q", "--no-commit", "--no-ff", ref],
                       cwd=str(root), capture_output=True, text=True, env=env)
    assert p.returncode in (0, 1), p.stderr
    return p


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _build(tmp_path: Path):
    """The measured topology, on a real repo.

    main:  c0 -> m1  (main advances; m1 adds a main-only tool and edits the engine
                      file the line also landed)
    line:  c0 -> L0 (a landing of ANOTHER line authored server/engine/shared.py)
              -> L1 (a landing of the DECLARED line authored dev_lane.py = the tip)
    lane:  L1 -> T1 (this ticket's own writes: its lawful file + its out-of-write-set
                      engine write) -> N = merge(m1, conflict on dev_lane.py resolved
                      by a merged blob) -> T2 (the ticket edits the main-only tool)
    """
    root = tmp_path / "proj"
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q", "-b", "main", ".")
    _git(root, "config", "user.email", "t@%s" % TID)
    _git(root, "config", "user.name", TID)
    _git(root, "config", "commit.gpgsign", "false")
    _write(root, "verify.yaml", "schema: v1\nlanes:\n  code:\n    write_allow:\n      - own/\n")
    _write(root, "base.txt", "b\n")
    c0 = _commit(root, "c0 baseline", "2026-10-31T10:00:00 +0800")

    # the line: two landings, the second one on the declared line
    _git(root, "checkout", "-q", "-b", LINE, c0)
    _write(root, OTHER_LINE_PATH, "SHARED = 1\n")
    l0 = _commit(root, LANDING_OTHER, "2026-10-31T10:01:00 +0800")
    _write(root, LINE_LANDED, "LINE = 1\n")
    l1 = _commit(root, LANDING_MAIN, "2026-10-31T10:02:00 +0800")

    # main advances: the same engine file (a real conflict for the lane's merge) +
    # a tool only main has
    _git(root, "checkout", "-q", "main")
    _write(root, LINE_LANDED, "MAIN = 1\n")
    _write(root, OTHER_LINE_PATH, "MAIN_SHARED = 1\n")
    _write(root, MAIN_ONLY, "TOOL = 1\n")
    m1 = _commit(root, "m1 main squash close-out", "2026-10-31T10:03:00 +0800")

    # the lane, based on the line (a develop-buffer ticket)
    _git(root, "checkout", "-q", "-b", LANE, l1)
    _write(root, OWN, "o\n")
    _write(root, TICKET_WROTE, "# written by the ticket\n")
    t1 = _commit(root, "%s implement: worker-settled (gen0, 2 files changed)" % TID,
                 "2026-10-31T10:04:00 +0800")
    # the worker-settled conflict resolution: the merged blob differs from BOTH
    # parents (this is what the engine measured on t261031-17)
    _merge_no_commit(root, m1, "2026-10-31T10:05:00 +0800")
    _write(root, LINE_LANDED, "LINE = 1\nMAIN = 1\n")
    _write(root, OTHER_LINE_PATH, "SHARED = 1\nMAIN_SHARED = 1\n")
    _git(root, "add", "-A")
    _stamp(root, "commit", "-qm", CONFLICT_COMMIT, date="2026-10-31T10:05:00 +0800")
    n = _git(root, "rev-parse", "HEAD").strip()
    _write(root, MAIN_ONLY, "TOOL = 2\n")
    t2 = _commit(root, "%s implement: edit the main-only tool" % TID,
                 "2026-10-31T10:06:00 +0800")
    return root, {"c0": c0, "l0": l0, "l1": l1, "m1": m1, "t1": t1, "n": n, "t2": t2}


def _baselines(root):
    """The merge gate's own resolution (the producer's helpers), so the numbers
    under test are the ones merge_check really passes down."""
    base, err = aa._merge_base_ref(LANE, root, other=LINE)
    assert not err, err
    base_other, err2 = aa._merge_base_ref(LANE, root, other="main")
    assert not err2, err2
    tip, tip_err = aa._tip_ref(LINE, root)
    assert not tip_err and tip, tip_err
    return base, base_other, tip


def _judge(root, **args):
    payload = {"lane": "code", "path": str(root), "require_base": True,
               "skip_slow": True, "write_set": list(WRITE_SET),
               "ticket_id": TID, "develop_line": LINE_ID}
    payload.update(args)
    res = vl.run(payload)
    hits = [c for c in res["checks"] if c.get("id") == vl.WS_CHECK_ID]
    assert hits, "the write-set record lost its machine key: %r" % (res["checks"],)
    return res, hits[0]


def _details(rec):
    return [str(i.get("detail", "")) for i in (rec.get("items") or [])]


#: verify_lane's out-of-write-set red line, escaped: the source stays ASCII (the
#: copy-language gate) while the assertion still reads the real machine wording.
_OOB = "\u8d8a\u754c\u5199"


def _red_naming(rec, rel):
    return [d for d in _details(rec)
            if rel in d and (_OOB in d or "out-of-write-set" in d)]


def _note(rec):
    return str(rec.get("note") or "")


# ---------------- A. landed line content is NOT this ticket's write -------------

def test_a1_fixture_reproduces_the_measured_shape(tmp_path):
    """The fixture really is the measured shape: the engine file's content at the
    lane HEAD differs from BOTH baselines and from the line tip, and the merge
    commit (not a lane commit) authored the third blob. Without the fix this path
    reds — that is the defect, reproduced."""
    root, shas = _build(tmp_path)
    base, base_other, tip = _baselines(root)
    head = _git(root, "rev-parse", "HEAD").strip()
    blobs = {ref: _git(root, "rev-parse", "%s:%s" % (ref, LINE_LANDED)).strip()
             for ref in (head, base, base_other, tip)}
    assert blobs[head] not in (blobs[base], blobs[base_other], blobs[tip]), blobs
    # the landing commit of the declared line authored it
    landing = _git(root, "log", "--format=%s", "--all", "--", LINE_LANDED).splitlines()
    assert LANDING_MAIN in landing, landing
    # and the plain-commit authors outside both baselines are only the ticket's
    own = _git(root, "log", "--format=%s", "--no-merges", "HEAD", "--not",
               "main", tip, "--", LINE_LANDED).strip()
    assert own == "", ("no non-merge lane commit authored the engine file: %r" % own)


def test_a2_landing_authored_path_is_not_foreign_and_the_skip_is_named(tmp_path):
    root, _shas = _build(tmp_path)
    base, base_other, tip = _baselines(root)
    res, rec = _judge(root, base=base, base_other=base_other, base_other_tip=tip)
    assert not _red_naming(rec, LINE_LANDED), (
        "landed line content must never read as this ticket's write: %s"
        % (_details(rec),))
    note = _note(rec)
    assert "t261031-34" in note and LINE_LANDED in note, note
    assert LINE_ID in note and "landing" in note, note
    assert "the line is not a lane" in note, note


def test_a3_the_engine_own_foreign_population_decides_the_same(tmp_path):
    """One judgment, two faces: the foreign-repair population reads the same
    authorship and answers the SAME verdict — landed line content, never foreign,
    never repaired, named on the record."""
    root, _shas = _build(tmp_path)
    base, base_err = aa._merge_base_ref(LANE, root)   # the repair face's own base
    assert base and not base_err, base_err
    rec = aa._foreign_population(root, base, LINE_LANDED, line_id=LINE_ID)
    assert rec["population"] == aa.FOREIGN_POPULATION_LINE, rec
    assert "line is not a lane" in rec["evidence"], rec
    assert LINE_ID in rec["evidence"], rec
    # the pre-fix caliber keeps its named escape (no line id = ambiguous)
    rec_no_line = aa._foreign_population(root, base, LINE_LANDED, line_id="")
    assert rec_no_line["population"] == aa.FOREIGN_POPULATION_AMBIGUOUS, rec_no_line
    assert "a human decides" in rec_no_line["evidence"], rec_no_line


def test_a4_split_face_names_line_content_green_and_repairs_nothing(tmp_path):
    """The repair face does not silently repair landed line content either: it is
    left in place, and a GREEN item names the decision on the receipt."""
    root, _shas = _build(tmp_path)
    head_before = _git(root, "rev-parse", "HEAD").strip()
    out = aa._foreign_repair_check_item(
        root, LANE, list(WRITE_SET), TID, split=True, line_id=LINE_ID)
    item = out.get("item")
    assert item is not None and item["green"] is True, item
    assert LINE_LANDED in " ".join(item.get("files") or []), item
    assert LINE_ID in item["detail"] and "not foreign" in item["detail"], item
    rec = out["record"]
    assert rec["files"][LINE_LANDED]["population"] == aa.FOREIGN_POPULATION_LINE
    assert rec["repaired"] == [] and rec["repair_commit"] == ""
    assert _git(root, "rev-parse", "HEAD").strip() == head_before
    assert (root / LINE_LANDED).read_text("utf-8") == "LINE = 1\nMAIN = 1\n"


# ---------------- B. the ticket's own write is still foreign --------------------

def test_b_ticket_authored_path_is_still_foreign(tmp_path):
    root, _shas = _build(tmp_path)
    base, base_other, tip = _baselines(root)
    res, rec = _judge(root, base=base, base_other=base_other, base_other_tip=tip)
    assert res["green"] is False and rec["level"] == "red", _details(rec)
    assert _red_naming(rec, TICKET_WROTE), (
        "an out-of-write-set write by the ticket must still red: %s" % (_details(rec),))
    # the ticket's lawful write stays green
    assert not _red_naming(rec, OWN), _details(rec)


def test_b2_the_repair_population_calls_it_the_tickets_own_commit(tmp_path):
    root, _shas = _build(tmp_path)
    base, base_err = aa._merge_base_ref(LANE, root)
    assert base and not base_err, base_err
    rec = aa._foreign_population(root, base, TICKET_WROTE, line_id=LINE_ID)
    assert rec["population"] == aa.FOREIGN_POPULATION_OWN, rec


# ---------------- C. genuinely foreign (main-only) still reds ------------------

def test_c_main_only_path_edited_by_the_ticket_is_foreign(tmp_path):
    root, _shas = _build(tmp_path)
    base, base_other, tip = _baselines(root)
    res, rec = _judge(root, base=base, base_other=base_other, base_other_tip=tip)
    assert _red_naming(rec, MAIN_ONLY), (
        "a main-only path the ticket edited differs from both sides: %s"
        % (_details(rec),))
    assert MAIN_ONLY not in _note(rec), (
        "it is judged, so it must not also be reported as landed line content")


# ---------------- D. the ambiguous population keeps its NAME -------------------

def test_d_landing_of_another_line_is_named_ambiguous(tmp_path):
    root, _shas = _build(tmp_path)
    base, base_other, tip = _baselines(root)
    res, rec = _judge(root, base=base, base_other=base_other, base_other_tip=tip)
    reds = _red_naming(rec, OTHER_LINE_PATH)
    assert reds, ("an undecidable landing authorship must judge, and red: %s"
                  % (_details(rec),))
    item = [i for i in rec["items"] if OTHER_LINE_PATH in str(i.get("detail"))][0]
    assert item.get("reason_code") == "landing_authorship_ambiguous", item
    assert "AMBIGUOUS" in item["detail"] and OTHER_LINE_ID in item["detail"], item
    assert "a human decides" in item["detail"], item
    assert OTHER_LINE_PATH in _note(rec), _note(rec)


def test_d2_verdict_truth_table_unit():
    """The judgment itself, repo-free: decided only for the DECLARED line; every
    shape the evidence cannot name is AMBIGUOUS (named), never a silent skip."""
    fw = _load_foreign_write()
    assert fw.landing_subject_parts(LANDING_MAIN)["line"] == LINE_ID
    assert fw.landing_subject_parts("t1 implement: worker-settled") is None
    assert fw.landing_subject_parts(None) is None
    assert fw.landing_subject_parts("landing broken subject") is None

    v, ev = fw.line_landing_verdict([LANDING_MAIN, CONFLICT_COMMIT], LINE_ID)
    assert v == fw.LINE_LANDING and LINE_ID in ev, (v, ev)
    v, ev = fw.line_landing_verdict([LANDING_MAIN], "")
    assert v == fw.LINE_LANDING_AMBIGUOUS and "no develop line" in ev, (v, ev)
    v, ev = fw.line_landing_verdict([LANDING_OTHER], LINE_ID)
    assert v == fw.LINE_LANDING_AMBIGUOUS and OTHER_LINE_ID in ev, (v, ev)
    v, ev = fw.line_landing_verdict(["landing broken subject"], LINE_ID)
    assert v == fw.LINE_LANDING_AMBIGUOUS and "did not parse" in ev, (v, ev)
    v, _ev = fw.line_landing_verdict([CONFLICT_COMMIT], LINE_ID)
    assert v == fw.LINE_LANDING_NONE, v
    v, _ev = fw.line_landing_verdict([], LINE_ID)
    assert v == fw.LINE_LANDING_NONE, v


def test_d3_ticket_own_commit_wins_over_an_older_landing(tmp_path):
    """The landing rule is never an amnesty: when the ticket's own plain commit
    ALSO authored the path, the path is judged (out of write set = red)."""
    root, _shas = _build(tmp_path)
    base, _bo, _tip = _baselines(root)
    _write(root, LINE_LANDED, "LINE = 1\nMAIN = 1\nTICKET = 1\n")
    _commit(root, "%s implement: edit the landed engine file" % TID,
            "2026-10-31T10:07:00 +0800")
    res, rec = _judge(root, base=base, base_other=_bo, base_other_tip=_tip)
    assert _red_naming(rec, LINE_LANDED), (
        "the ticket's own commit authored it, so the landing rule must not exempt "
        "it: %s" % (_details(rec),))
    assert LINE_LANDED not in _note(rec), _note(rec)


# ---------------- E. the battery-shape decision and its behavioural pin --------

def _load_foreign_write():
    spec = importlib.util.spec_from_file_location(
        "foreign_write_ut_34", str(ENGINE / "foreign_write.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_e1_battery_decision_is_the_named_skip_and_keeps_the_pin():
    """Option (ii), declared in the code the gate runs: the un-patched
    "declared scope alone" payload is a MAIN-SHAPED history claim, so the case is
    skipped with a NAMED reason, and a shape-independent case keeps pinning the
    behavioural claim (the un-patched branch hands the DECLARED list through)."""
    pairs = [
        (HERE / "test_t261031_23_own_pointed_gate.py", "pytest.skip(_why)"),
        (HERE / "test_t261024_40_own_scenario_face.py", "self.skipTest(_why)"),
    ]
    for path, skip_call in pairs:
        src = path.read_text("utf-8")
        assert skip_call in src, "%s must skip by name: %s" % (path.name, skip_call)
        assert "main-shape-only (t261031-34, KI-447)" in src, path.name
        assert "def main_shape_only_reason" in src or "_main_shape_only_reason" in src, \
            path.name
        # the behavioural pin lives in the same file, so a skipped case never
        # leaves the claim unasserted
        assert "payload_is_what_the_pre_patch" in src, path.name


def test_e2_the_unpatched_branch_hands_the_declared_list_to_the_writer():
    """The behavioural claim on the real `_quick_gate_round`: an un-patched history
    replays the call it recorded — the DECLARED list reaches the single writer (what
    the writer then does with it is that tree's own rule, covered by the batteries)."""
    wf = object.__new__(dev_lane.QuickmanualLaneWorkflow)
    wf.ticket_id = TID
    wf.meta = {"worktree": "/tmp/t261031-34", "stage": "run_integration_tests",
               "workspace": {}, "base_ref": "deadbeef", "log": [],
               "write_set": list(WRITE_SET)}
    wf.gate_runs, wf.results, wf._gens = [], {}, {}
    wf._detail_face_on = False
    sent = []
    real = wf._integ_run_args
    wf._integ_run_args = lambda only_names=(), own_names=(): (
        sent.append(list(only_names)) or real(only_names, own_names=own_names))
    declared, own = "declared-scope", "own-scenario"

    class _Stub:
        def patched(self, pid, *a, **k):
            return pid != dev_lane.QUICK_OWN_POINTED_PATCH_ID

        def now(self):
            return __import__("datetime").datetime(2026, 10, 31, 12, 0, 0)

        async def execute_activity(self, _fn, args, **kw):
            return shared.IntegrationRunResult(
                ran=1, passed=1, failed=0, env_fail=0, error="",
                details=[{"name": declared, "cmd": "", "exit": 0,
                          "output_tail": ""}])

    saved = dev_lane.workflow
    dev_lane.workflow = _Stub()
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(wf._quick_gate_round(
            {"mode": "scenario", "names": [declared], "only_names": [declared],
             "own_names": [own]}))
        recorded = real([declared], own_names=[own])
    finally:
        loop.close()
        dev_lane.workflow = saved
    assert sent == [[declared]], (
        "the un-patched branch must hand the DECLARED list to the writer: %r" % (sent,))
    assert list(recorded.only_names) == [declared], (
        "on a main-shaped tree the recorded payload is the declared scope alone")


def test_e3_the_source_keeps_the_pre_patch_branch_reachable():
    """Source lock: the pre-patch list is `_declared` before the patched() gate, so
    an un-patched history replays the recorded call instead of the new union."""
    src = (ENGINE / "dev_lane.py").read_text("utf-8")
    start = src.index("async def _quick_gate_round")
    body = src[start:start + 4000]
    i_default = body.index("_pointed = _declared")
    i_gate = body.index("workflow.patched(QUICK_OWN_POINTED_PATCH_ID)")
    assert i_default < i_gate, body[:600]


# ---------------- F. wiring: the merge receipt carries both facts --------------

class _FakeProc:
    def __init__(self, payload):
        self.pid = 0
        self.returncode = 0
        self._payload = payload

    async def communicate(self):
        return json.dumps(self._payload).encode("utf-8"), b""


def test_f1_the_activity_argument_defaults_to_the_pre_fix_caliber():
    assert shared.MergeCheckArgs(ticket_id=TID).develop_line == ""


def test_f2_merge_check_passes_the_line_and_names_the_conflict_resolution(
        tmp_path, monkeypatch):
    """End to end through the real activity: the declared line reaches the write-set
    judge, the write-set item is green while NAMING the landed content, and the
    worker's conflict resolution over a shared engine file is a NAMED receipt line
    (a review point the merge human can read, never silent)."""
    root, shas = _build(tmp_path)
    base, base_other, tip = _baselines(root)
    seen = []

    async def _spawn(*args, **kwargs):
        payload = json.loads(args[4])
        seen.append(payload)
        if payload.get("lane") != "code":
            return _FakeProc({"ok": True, "result": {}})
        note = ("t261031-34: 1 file(s) read as LANDED content of the declared line "
                "%s ... and not judged: %s" % (LINE_ID, LINE_LANDED))
        return _FakeProc({"ok": True, "result": {
            "green": True, "exit_code": 0, "red_count": 0,
            "checks": [{"check": "write set", "level": "green", "items": [],
                        "id": "write_set_whitelist", "note": note}]}})

    monkeypatch.setattr(aa.asyncio, "create_subprocess_exec", _spawn)
    saved_root = aa.REPO_ROOT
    try:
        aa.REPO_ROOT = root
        core = asyncio.run(aa.merge_check(aa.MergeCheckArgs(
            ticket_id=TID, worktree=str(root), branch=LANE,
            base_ref=shas["c0"], write_set=list(WRITE_SET),
            base_other_ref=LINE, develop_line=LINE_ID,
            foreign_repair_split=True)))
    finally:
        aa.REPO_ROOT = saved_root

    payloads = [p for p in seen if p.get("lane") == "code"]
    assert payloads, "merge_check never called verify_lane code: %r" % (seen,)
    assert payloads[-1].get("develop_line") == LINE_ID, payloads[-1]
    assert payloads[-1].get("base_other_tip") == tip, payloads[-1]
    assert base and base_other  # the fixture resolves both baselines

    rows = {c.get("id"): c for c in core.checks}
    ws_row = rows.get("verify_lane_code") or {}
    assert LINE_LANDED in str(ws_row.get("note") or ""), ws_row
    repair_rows = [c for c in core.checks if c.get("id") == aa.FOREIGN_REPAIR_ID]
    line_rows = [c for c in repair_rows if c.get("green") is True
                 and LINE_LANDED in " ".join(c.get("files") or [])]
    assert line_rows, (
        "landed line content must be a NAMED green receipt row: %r" % (repair_rows,))
    assert LINE_ID in line_rows[0]["detail"], line_rows[0]
    cr_item = rows.get(aa.CONFLICT_RESOLUTION_AUTHORED_ID) or {}
    assert cr_item.get("green") is True, (
        "the worker's conflict resolution over a shared engine file must be NAMED "
        "on the receipt: %r" % (list(rows),))
    assert shas["n"][:7] in cr_item["detail"], cr_item
    assert LINE_LANDED in cr_item["detail"], cr_item


def test_f3_conflict_resolution_probe_is_silent_when_nothing_was_authored(tmp_path):
    """Two silent shapes, so the item is a review point and not permanent noise:
    a lane with no worker-settled resolution at all, and a resolution whose files
    are inside the ticket's own write set (that is the ticket's work)."""
    plain = tmp_path / "plain"
    plain.mkdir(parents=True, exist_ok=True)
    _git(plain, "init", "-q", "-b", "main", ".")
    _git(plain, "config", "user.email", "t@%s" % TID)
    _git(plain, "config", "user.name", TID)
    _git(plain, "config", "commit.gpgsign", "false")
    _write(plain, "base.txt", "b\n")
    c0 = _commit(plain, "c0", "2026-10-31T09:00:00 +0800")
    _git(plain, "checkout", "-q", "-b", LANE, c0)
    _write(plain, "own/a.txt", "a\n")
    _commit(plain, "%s implement: worker-settled" % TID, "2026-10-31T09:01:00 +0800")
    _stamp(plain, "merge", "-q", "--no-edit", "main", date="2026-10-31T09:02:00 +0800")
    assert aa._conflict_resolution_authored_item(plain, c0, LANE, ["own/"]) is None

    root, _shas = _build(tmp_path)
    assert aa._conflict_resolution_authored_item(
        root, "main", LANE,
        [LINE_LANDED, OTHER_LINE_PATH, MAIN_ONLY, TICKET_WROTE]) is None


def test_f4_conflict_resolution_query_fault_is_named_red(tmp_path):
    root, _shas = _build(tmp_path)
    item = aa._conflict_resolution_authored_item(root, "no-such-base-ref", LANE,
                                                list(WRITE_SET))
    assert item is not None and item["green"] is False, item
    assert item.get("reason_code") == "conflict_resolution_query_failed", item
