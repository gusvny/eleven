#!/usr/bin/env python3
"""t261031-43 (KI-447 follow-up, delivered by t261101-05) L1: the declared develop
line is resolved AT ACTIVITY TIME from the ticket's live meta, with the recorded
activity argument as the fallback.

The defect (measured on t261031-17 right after t261031-34 landed): t261031-34
threaded the line into the merge_check payload from the RECORDED activity argument.
A running workflow's recorded arguments are what its history captured when it
started, so a field added later decodes as an empty string forever. The lane carried
t261031-34 and its own verify_lane.py had the fix, yet its merge_check still redded
with the landed line files named out-of-write-set. The fix was correct and
unreachable.

What this battery pins (one group per deliverable):

  A  precedence: live meta first, the recorded argument as the fallback, and both
     empty = the old caliber; the incident shape resolves to the line and names why;
  B  a malformed or unknown line id is NAMED - an undeclared line, an unreadable
     declaration, a missing project key, a failed live meta read - and is never
     silently read as "no line";
  C  one tree, two calibers: the empty id (today's in-flight behavior) reds on the
     landed line file, the meta-resolved id decides as line content and NAMES the
     skip - the incident, reproduced and closed;
  D  both faces read the SAME id through the real merge_check (the verify_lane
     payload and the foreign-repair population record); a ticket with no declared
     line keeps the empty payload and no resolution row; a faulting resolution keeps
     the recorded argument and never blocks the gate;
  E  replay safety: MergeCheckArgs keeps its shape and its empty default, both face
     sites keep the recorded field as the literal fallback, the resolution runs once
     per call before the per-scope loop, the workflow records the same argument (no
     new command), and outside an activity context there is no live read at all.

Offline, temp dirs only, zero network, zero Temporal, zero docker. The live meta read
is stubbed in every case that needs one, and the projects root is redirected to a temp
directory. Never touches port 3099/7233. Run:
  server/engine/.venv/bin/python -m pytest \
    server/engine/tests/test_t261031_43_develop_line_from_meta.py -q
"""
import asyncio
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent
sys.path.insert(0, str(ENGINE))
sys.path.insert(0, str(ENGINE.parent / "tools"))

import agent_activities as aa  # noqa: E402
import shared  # noqa: E402
import verify_lane as vl  # noqa: E402

TID = "t261031-43"
LINE = "develop"
LINE_ID = "develop-buffer"
PROJECT_KEY = "t26103143-proj"
LANE = "lane/t261031-43"
WRITE_SET = ["own/"]

#: The landed shared engine file (the file t261031-17's receipt named).
LINE_LANDED = "server/engine/dev_lane.py"
#: The ticket's own lawful write.
OWN = "own/own.txt"
LANDING_SUBJECT = ("landing t261029-18 onto line %s (sandbar): rev e59c7122aef4"
                   % LINE_ID)
CONFLICT_SUBJECT = "%s conflict resolution (round 0): worker-settled merge commit" % TID

#: verify_lane's out-of-write-set red line, escaped: the source stays ASCII (the
#: copy-language gate) while the assertion reads the real machine wording.
_OOB = "\u8d8a\u754c\u5199"


# ---------------- real-git fixture helpers ----------------

def _git(root, *args, env=None):
    p = subprocess.run(["git"] + list(args), cwd=str(root), capture_output=True,
                       text=True, env=env)
    assert p.returncode == 0, "git %s failed: %s" % (" ".join(args), p.stderr)
    return p.stdout


def _env(date):
    return dict(os.environ, GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date,
                GIT_COMMITTER_NAME=TID, GIT_COMMITTER_EMAIL="t@%s" % TID,
                GIT_AUTHOR_NAME=TID, GIT_AUTHOR_EMAIL="t@%s" % TID)


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _commit(root, msg, date):
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", msg, env=_env(date))
    return _git(root, "rev-parse", "HEAD").strip()


def _build(tmp_path):
    """The measured topology on a real repo.

    main:  c0 -> m1        (main advances and also edits the engine file)
    line:  c0 -> L1        (a landing commit of the DECLARED line authored the
                            engine file: line content, not the ticket's write)
    lane:  L1 -> T1        (the ticket's own lawful file)
              -> N         (the worker-settled merge of main: a third blob)
    """
    root = tmp_path / "proj"
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q", "-b", "main", ".")
    _git(root, "config", "user.email", "t@%s" % TID)
    _git(root, "config", "user.name", TID)
    _git(root, "config", "commit.gpgsign", "false")
    _write(root, "verify.yaml",
           "schema: v1\nlanes:\n  code:\n    write_allow:\n      - own/\n")
    _write(root, "base.txt", "b\n")
    c0 = _commit(root, "c0 baseline", "2026-10-31T10:00:00 +0800")

    _git(root, "checkout", "-q", "-b", LINE, c0)
    _write(root, LINE_LANDED, "LINE = 1\n")
    _commit(root, LANDING_SUBJECT, "2026-10-31T10:01:00 +0800")

    _git(root, "checkout", "-q", "main")
    _write(root, LINE_LANDED, "MAIN = 1\n")
    m1 = _commit(root, "m1 main squash close-out", "2026-10-31T10:02:00 +0800")

    _git(root, "checkout", "-q", "-b", LANE, LINE)
    _write(root, OWN, "o\n")
    _commit(root, "%s implement: worker-settled (gen0, 1 file changed)" % TID,
            "2026-10-31T10:03:00 +0800")
    p = subprocess.run(["git", "merge", "-q", "--no-commit", "--no-ff", m1],
                       cwd=str(root), capture_output=True, text=True,
                       env=_env("2026-10-31T10:04:00 +0800"))
    assert p.returncode in (0, 1), p.stderr
    _write(root, LINE_LANDED, "LINE = 1\nMAIN = 1\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", CONFLICT_SUBJECT,
         env=_env("2026-10-31T10:04:00 +0800"))
    return root


def _main_sha(root):
    return _git(root, "rev-parse", "main").strip()


def _baselines(root):
    """The merge gate's own baseline resolution, so the values under test are the
    ones merge_check really passes down."""
    base, err = aa._merge_base_ref(LANE, root, other=LINE)
    assert not err, err
    base_other, err2 = aa._merge_base_ref(LANE, root, other="main")
    assert not err2, err2
    tip, tip_err = aa._tip_ref(LINE, root)
    assert not tip_err and tip, tip_err
    return base, base_other, tip


def _judge(root, develop_line):
    """Run verify_lane's real write-set judge on the fixture with the given line id."""
    base, base_other, tip = _baselines(root)
    payload = {"lane": "code", "path": str(root), "require_base": True,
               "skip_slow": True, "write_set": list(WRITE_SET), "ticket_id": TID,
               "base": base, "base_other": base_other, "base_other_tip": tip,
               "develop_line": develop_line}
    res = vl.run(payload)
    hits = [c for c in res["checks"] if c.get("id") == vl.WS_CHECK_ID]
    assert hits, "the write-set record lost its machine key: %r" % (res["checks"],)
    rec = hits[0]
    details = [str(i.get("detail", "")) for i in (rec.get("items") or [])]
    reds = [d for d in details
            if LINE_LANDED in d and (_OOB in d or "out-of-write-set" in d)]
    return rec, details, reds


def _fixture_lines(monkeypatch, tmp_path, declared=(LINE_ID,)):
    """A temp projects root carrying the declared lines, so no case reads the host."""
    root = tmp_path / "projects"
    d = root / PROJECT_KEY / "data" / "develop"
    d.mkdir(parents=True, exist_ok=True)
    (d / "lines.json").write_text(json.dumps(
        [{"line_id": lid, "scope": "test line", "owner": "host",
          "repositories": [{"name": "sandbar", "branch": LINE}], "version": 1}
         for lid in declared]), encoding="utf-8")
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(root))
    return root


def _meta(line_id=LINE_ID, project=PROJECT_KEY):
    return {"develop_line": line_id, "project": project,
            "lane_version": "develop-buffer-v1", "ticket_id": TID}


def _stub_live_meta(monkeypatch, meta, diag=""):
    async def _reader(_tid):
        return (None if meta is None else dict(meta)), diag
    monkeypatch.setattr(aa, "_read_ticket_live_meta", _reader)


def _resolve(args):
    return asyncio.run(aa._resolve_merge_check_develop_line(args))


class _FakeProc:
    def __init__(self, payload):
        self.pid = 0
        self.returncode = 0
        self._payload = payload

    async def communicate(self):
        return json.dumps(self._payload).encode("utf-8"), b""


def _run_merge_check(monkeypatch, root, seen, results=None, **arg_over):
    """Run the real merge_check with verify_lane stubbed; returns its result."""
    async def _spawn(*args, **kwargs):
        payload = json.loads(args[4])
        seen.append(payload)
        if payload.get("lane") != "code":
            return _FakeProc({"ok": True, "result": {}})
        return _FakeProc({"ok": True, "result": results or {
            "green": True, "exit_code": 0, "red_count": 0, "checks": []}})

    monkeypatch.setattr(aa.asyncio, "create_subprocess_exec", _spawn)
    saved_root = aa.REPO_ROOT
    try:
        aa.REPO_ROOT = root
        kwargs = dict(ticket_id=TID, worktree=str(root), branch=LANE,
                      base_ref=_main_sha(root), write_set=list(WRITE_SET),
                      foreign_repair_split=True)
        kwargs.update(arg_over)
        return asyncio.run(aa.merge_check(aa.MergeCheckArgs(**kwargs)))
    finally:
        aa.REPO_ROOT = saved_root


# ---------------- A. precedence ----------------

def test_a1_precedence_matrix_unit():
    """The precedence, repo-free: live meta first, the recorded argument as the
    fallback, and BOTH empty = the old caliber (no id at all)."""
    p = aa._develop_line_precedence
    # the incident shape: the recorded field is empty, the live meta declares a line
    assert p("", LINE_ID) == (LINE_ID, aa.DEVELOP_LINE_SOURCE_LIVE_META)
    # args and meta equal: today's behavior, the same id
    assert p(LINE_ID, LINE_ID) == (LINE_ID, aa.DEVELOP_LINE_SOURCE_LIVE_META)
    # meta empty + args present: the args value wins
    assert p(LINE_ID, "") == (LINE_ID, aa.DEVELOP_LINE_SOURCE_RECORDED)
    # both empty: the old caliber
    assert p("", "") == ("", "")
    # surrounding whitespace and non-string values never leak into the id
    assert p("  ", None) == ("", "")
    assert p(None, "  " + LINE_ID + "\n") == (LINE_ID, aa.DEVELOP_LINE_SOURCE_LIVE_META)
    # the live meta wins when the two sources disagree
    assert p("other-line", LINE_ID) == (LINE_ID, aa.DEVELOP_LINE_SOURCE_LIVE_META)


def test_a2_the_incident_shape_resolves_to_the_line_and_names_why(monkeypatch, tmp_path):
    """The measured shape: recorded args empty, live meta declares the line. The face
    resolves the line AND names the in-flight reason, so the merge human can read why
    this round decided as line content."""
    _fixture_lines(monkeypatch, tmp_path)
    _stub_live_meta(monkeypatch, _meta())
    face = _resolve(shared.MergeCheckArgs(ticket_id=TID, develop_line=""))
    assert face["line_id"] == LINE_ID, face
    assert face["source"] == aa.DEVELOP_LINE_SOURCE_LIVE_META, face
    assert face["state"] == "declared", face
    note = face["note"]
    assert LINE_ID in note and "live meta" in note, note
    assert "recorded activity args carry no develop line" in note, note
    assert "in-flight" in note, note


def test_a3_equal_sources_are_silent_todays_behavior(monkeypatch, tmp_path):
    """Args and meta carry the same declared line: the same id and NO receipt row, so
    a new line ticket's receipt keeps today's shape."""
    _fixture_lines(monkeypatch, tmp_path)
    _stub_live_meta(monkeypatch, _meta())
    face = _resolve(shared.MergeCheckArgs(ticket_id=TID, develop_line=LINE_ID))
    assert face["line_id"] == LINE_ID, face
    assert face["state"] == "declared", face
    assert face["note"] == "", face


def test_a4_meta_empty_keeps_the_recorded_value_named(monkeypatch, tmp_path):
    """Meta empty + args present: the recorded value wins, and the row says so."""
    _fixture_lines(monkeypatch, tmp_path)
    _stub_live_meta(monkeypatch, {"project": PROJECT_KEY})
    face = _resolve(shared.MergeCheckArgs(ticket_id=TID, develop_line=LINE_ID))
    assert face["line_id"] == LINE_ID, face
    assert face["source"] == aa.DEVELOP_LINE_SOURCE_RECORDED, face
    assert face["note"], "the fallback must be named, not silent"
    assert "live meta declares no develop line" in face["note"], face["note"]


def test_a5_both_empty_is_the_old_caliber_with_no_row(monkeypatch, tmp_path):
    """A ticket with no declared line anywhere: empty id, empty note, no state. That
    is the pre-t261031-34 caliber byte for byte (no git work, no receipt row)."""
    _fixture_lines(monkeypatch, tmp_path)
    _stub_live_meta(monkeypatch, {"project": PROJECT_KEY, "develop_line": ""})
    face = _resolve(shared.MergeCheckArgs(ticket_id=TID))
    assert face["line_id"] == "" and face["note"] == "" and face["state"] == "", face


# ---------------- B. a malformed / unknown line id is NAMED ----------------

def test_b1_an_undeclared_line_is_named_and_never_read_as_no_line(monkeypatch, tmp_path):
    """The id reaches the judgment as given (never silently dropped to "no line"), and
    the row names the id, the declared set, and the consequence."""
    _fixture_lines(monkeypatch, tmp_path)
    _stub_live_meta(monkeypatch, _meta(line_id="no-such-line"))
    face = _resolve(shared.MergeCheckArgs(ticket_id=TID, develop_line=""))
    assert face["line_id"] == "no-such-line", face
    assert face["state"] == "undeclared", face
    note = face["note"]
    assert "no-such-line" in note, note
    assert "not declared for project %s" % PROJECT_KEY in note, note
    assert LINE_ID in note, "the declared set must be listed: %s" % note
    assert "cannot run" in note and "judged as this ticket's write" in note, note


def test_b2_an_unreadable_declaration_is_named(monkeypatch, tmp_path):
    """A project whose line declaration cannot be read is a NAMED state, not a silent
    "no line"."""
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(tmp_path / "empty-projects"))
    _stub_live_meta(monkeypatch, _meta())
    face = _resolve(shared.MergeCheckArgs(ticket_id=TID, develop_line=""))
    assert face["state"] == "unreadable", face
    assert "could not be read" in face["note"] and LINE_ID in face["note"], face["note"]


def test_b3_a_missing_project_key_is_named_not_guessed(monkeypatch, tmp_path):
    _fixture_lines(monkeypatch, tmp_path)
    _stub_live_meta(monkeypatch, {"develop_line": LINE_ID})
    face = _resolve(shared.MergeCheckArgs(ticket_id=TID, develop_line=""))
    assert face["state"] == "unchecked", face
    assert "project key is not readable" in face["note"], face["note"]


def test_b4_a_failed_live_meta_read_is_named_with_its_consequence(monkeypatch, tmp_path):
    """A failed live meta read must not read as "the ticket declares no line": the row
    says the judgment cannot run this round and names the fault."""
    _fixture_lines(monkeypatch, tmp_path)
    diag = "the live meta query failed (TimeoutError: 8s)"
    _stub_live_meta(monkeypatch, {}, diag=diag)
    face = _resolve(shared.MergeCheckArgs(ticket_id=TID, develop_line=""))
    assert face["line_id"] == "", face
    assert diag in face["note"], face["note"]
    assert "cannot run this round" in face["note"], face["note"]
    # with a recorded value the same fault is named while the fallback stands
    face2 = _resolve(shared.MergeCheckArgs(ticket_id=TID, develop_line=LINE_ID))
    assert face2["line_id"] == LINE_ID, face2
    assert diag in face2["note"], face2["note"]
    assert "recorded activity argument is used" in face2["note"], face2["note"]


def test_b5_disagreeing_sources_name_the_disagreement(monkeypatch, tmp_path):
    _fixture_lines(monkeypatch, tmp_path)
    _stub_live_meta(monkeypatch, _meta())
    face = _resolve(shared.MergeCheckArgs(ticket_id=TID, develop_line="other-line"))
    assert face["line_id"] == LINE_ID, face
    assert "other-line" in face["note"] and "live meta wins" in face["note"], face["note"]


# ---------------- C. one tree, two calibers (the incident, closed) --------------

def test_c1_the_fixture_reproduces_the_measured_shape(tmp_path):
    """The engine file's content at the lane HEAD differs from BOTH baselines, and the
    commit that authored the landed blob is the landing of the declared line (a merge
    commit never votes). Without a line id this path reds - that is the defect."""
    root = _build(tmp_path)
    base, base_other, tip = _baselines(root)
    head = _git(root, "rev-parse", "HEAD").strip()
    blobs = {ref: _git(root, "rev-parse", "%s:%s" % (ref, LINE_LANDED)).strip()
             for ref in (head, base, base_other, tip)}
    assert blobs[head] not in (blobs[base], blobs[base_other], blobs[tip]), blobs
    authors = _git(root, "log", "--format=%s", "--no-merges", "HEAD", "--not",
                   "main", tip, "--", LINE_LANDED).strip()
    assert authors == "", "no non-merge lane commit may author the landed file: %r" % authors
    landed_by = _git(root, "log", "--format=%s", "--all", "--", LINE_LANDED).splitlines()
    assert LANDING_SUBJECT in landed_by, landed_by


def test_c2_with_the_resolved_line_the_write_set_item_stops_naming_the_file(tmp_path):
    """Two calibers, one tree. The empty id (today's in-flight behavior) is the red
    that was measured; the meta-resolved id decides as landed line content, and the
    skip is NAMED on the record."""
    root = _build(tmp_path)
    _rec_old, details_old, reds_old = _judge(root, "")
    assert reds_old, ("the empty-id caliber must red on the landed line file, "
                      "otherwise this battery proves nothing: %s" % (details_old,))

    rec, details, reds = _judge(root, LINE_ID)
    assert not reds, ("landed line content must not read as this ticket's write: %s"
                      % (details,))
    note = str(rec.get("note") or "")
    assert LINE_LANDED in note and LINE_ID in note, note
    assert "the line is not a lane" in note, note
    # the ticket's own lawful write stays green in both calibers
    assert not [d for d in details if OWN in d and (_OOB in d or "out-of-write-set" in d)]


# ---------------- D. both faces read ONE id through the real merge_check ---------

def test_d1_both_faces_get_the_meta_resolved_id(monkeypatch, tmp_path):
    """End to end through the real activity: the recorded args carry NO line, the live
    meta declares one, and both faces - the verify_lane payload and the foreign-repair
    population record - carry that one id. The receipt names the resolution."""
    root = _build(tmp_path)
    _fixture_lines(monkeypatch, tmp_path)
    _stub_live_meta(monkeypatch, _meta())
    seen = []
    core = _run_merge_check(monkeypatch, root, seen, base_other_ref=LINE,
                            develop_line="")

    payloads = [p for p in seen if p.get("lane") == "code"]
    assert payloads, "merge_check never called verify_lane code: %r" % (seen,)
    assert payloads[-1].get("develop_line") == LINE_ID, payloads[-1]

    repairs = [c for c in core.checks if c.get("id") == aa.FOREIGN_REPAIR_ID]
    records = [c.get("foreign_repair") for c in repairs
               if isinstance(c.get("foreign_repair"), dict)]
    assert records, "the repair face classified nothing: %r" % (repairs,)
    assert any(r.get("line_id") == LINE_ID for r in records), (
        "the repair record must carry the same line id the write-set item got: %r"
        % (records,))

    row = [c for c in core.checks if c.get("id") == aa.DEVELOP_LINE_RESOLUTION_ID]
    assert row, "the resolution must be a NAMED receipt row: %r" % (
        sorted({str(c.get("id")) for c in core.checks}),)
    assert row[0]["green"] is True, row[0]
    assert LINE_ID in row[0]["detail"] and "in-flight" in row[0]["detail"], row[0]
    # the merge rehearsal keeps the last slot (the conflict-classification contract)
    assert core.checks[-1].get("id") != aa.DEVELOP_LINE_RESOLUTION_ID


def test_d2_no_declared_line_keeps_todays_payload_and_no_row(monkeypatch, tmp_path):
    """A ticket with no line anywhere: the payload's develop_line stays the empty
    string, the repair record carries no line_id key, and no resolution row appears.
    Byte for byte today's caliber."""
    root = _build(tmp_path)
    _fixture_lines(monkeypatch, tmp_path)
    _stub_live_meta(monkeypatch, {"project": PROJECT_KEY, "develop_line": ""})
    seen = []
    core = _run_merge_check(monkeypatch, root, seen)

    payloads = [p for p in seen if p.get("lane") == "code"]
    assert payloads, "merge_check never called verify_lane code"
    assert payloads[-1].get("develop_line") == "", payloads[-1]
    for c in core.checks:
        rec = c.get("foreign_repair")
        if isinstance(rec, dict):
            assert "line_id" not in rec, rec
    assert not [c for c in core.checks
                if c.get("id") == aa.DEVELOP_LINE_RESOLUTION_ID]


def test_d3_a_faulting_resolution_keeps_the_recorded_argument(monkeypatch, tmp_path):
    """A fault in the resolution never blocks the chain and never loses the recorded
    value: the gate runs and the recorded argument reaches the write-set judge."""
    root = _build(tmp_path)

    async def _boom(_tid):
        raise RuntimeError("temporal client exploded")

    monkeypatch.setattr(aa, "_read_ticket_live_meta", _boom)
    seen = []
    _run_merge_check(monkeypatch, root, seen, develop_line=LINE_ID)
    payloads = [p for p in seen if p.get("lane") == "code"]
    assert payloads and payloads[-1].get("develop_line") == LINE_ID, payloads[-1:]


# ---------------- E. replay safety and context bounds ----------------

def test_e1_the_recorded_argument_keeps_its_shape_and_empty_default():
    assert shared.MergeCheckArgs(ticket_id=TID).develop_line == ""
    # a payload recorded by a history that predates the field decodes unchanged
    old = {"ticket_id": TID, "worktree": "/w", "branch": LANE, "write_set": ["own/"]}
    assert shared.MergeCheckArgs(**old).develop_line == ""


def test_e2_both_face_sites_keep_the_recorded_field_as_the_literal_fallback():
    """The two faces still read the recorded field itself; the resolution runs once
    before them, so they cannot disagree."""
    src = (ENGINE / "agent_activities.py").read_text("utf-8")
    assert src.count('line_id=str(getattr(args, "develop_line", "") or "")') == 1
    assert src.count('"develop_line": str(getattr(args, "develop_line", "") or "")') == 1
    start = src.index("async def merge_check(")
    body = src[start:]
    first = body.index("_resolve_merge_check_develop_line")
    scope_loop = body.index("for sc in scopes:\n        core = await _merge_check_one_scope")
    assert first < scope_loop, "the resolution must run once, before the per-scope loop"


def test_e3_the_workflow_still_records_the_same_argument():
    """No new command for any recorded history: the workflow keeps passing the meta
    value inside its own patched() gate, and the activity signature is unchanged."""
    src = (ENGINE / "dev_lane.py").read_text("utf-8")
    assert 'develop_line=(str(self.meta.get("develop_line") or "")' in src
    assert list(inspect.signature(aa.merge_check).parameters) == ["args"]


def test_e4_no_live_meta_read_outside_an_activity_context():
    """A direct call (a unit test, a CLI replay) has no live meta by definition: the
    read answers (None, "") and the recorded payload is the only face. That is why no
    existing merge_check case moves."""
    assert not aa.activity.in_activity()
    meta, diag = asyncio.run(aa._read_ticket_live_meta(TID))
    assert meta is None and diag == ""


def test_e5_the_live_read_is_bounded_and_named():
    src = (ENGINE / "agent_activities.py").read_text("utf-8")
    start = src.index("async def _read_ticket_live_meta")
    body = src[start:start + 2400]
    assert "DEVELOP_LINE_LIVE_META_TIMEOUT_SEC" in body
    assert 'query("snapshot")' in body
    assert "return {}, diag" in body, "a failed read must be named, never silent"
