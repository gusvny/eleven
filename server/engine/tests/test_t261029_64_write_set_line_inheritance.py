"""t261029-64: the write-set whitelist must answer "did this ticket write this
file?", and the merge-base pair alone cannot always answer it.

Defect (measured live on ticket t261029-38, 2026-10-29). The whitelist judged "this
ticket's own write" as the intersection of two three-dot diffs, whose baselines are
`merge-base(line, lane)` and `merge-base(main, lane)`. A develop line whose tip is a
merge of main, plus a lane that absorbed an OLDER line tip, makes
`git merge-base --all <line> <lane>` report two candidates. The plain command prints
one of them, and on that topology it is the same commit merge-base(main, lane) gives,
so the two baselines coincided, the code took its documented "the two sides coincide
-> the old one-sided caliber" arm, and the intersection filter was skipped entirely.
Result: the whole `line...lane` diff was charged to the ticket. Three files that are
byte-identical to the line tip (agent_activities.py, dev_lane.py, shared.py) were
reported as out-of-write-set writes, and `git diff --quiet <line-tip> -- <file>` was
empty for each of them.

The rule the fix implements (state it once, here and in the code):
  a file whose content at HEAD is BYTE-IDENTICAL to the other side's TIP is not this
  ticket's write and is never judged — and every skip is NAMED on the record with
  the tip it was compared against. A degenerate basis (both baselines equal) is named
  too: it is never a silent degradation to the single-sided caliber. Fail-closed
  stays: an unresolvable tip or a failed tip diff reds by name and judges nothing,
  and the t261022-08 items (baseline_diff_failed / baseline_diff_empty) are untouched.

Faces under test, on a real temp git repo reproducing that topology (zero network,
zero Temporal, the real `verify_lane.run` entry and the real merge_check):
  A  the topology really is degenerate: two merge bases, and the plain resolution
     equals merge-base(main, lane) (driven through the producer's own
     `agent_activities._merge_base_ref`, so the fixture proves the production shape
     instead of asserting a hand-picked pair);
  B  the OLD reading (no other-side tip passed): the line's own work is charged to
     the ticket (the bug, reproduced on this very fixture);
  C  the fixed reading: those files are skipped and the skip NAMES the rule and the
     tip; this ticket's own write is what remains;
  D  a genuine out-of-write-set write by the ticket still reds — a non-test path and
     a test path that is not this ticket's test face (the t261029-38 anchor shape:
     an arbitrate commit editing test_t260925_04_file_blast_radius.py);
  E  the degenerate basis is named on the record, and the green shape (write set
     covering the ticket's real writes) still carries both names;
  F  fail-closed: an unresolvable other-side tip is a NAMED red that judges nothing;
  G  wiring: the real merge_check resolves the line TIP and passes it down, and the
     whitelist's skip note reaches the merge_check row (a green-looking merge receipt
     still says how the skip was decided).
"""
import asyncio
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
import verify_lane as vl  # noqa: E402

LINE = "develop"
LANE = "lane/t261029-64"
# The line's own work: two files the line changed and this lane merely absorbed.
LINE_ONLY = ("line-side.txt", "server/engine/line_module.py")
# The ticket's genuine out-of-write-set writes: one non-test path and one test path
# that is NOT this ticket's test face (ticket-test-face carve does not admit it).
FOREIGN = ("server/engine/agent_activities.py",
           "server/engine/tests/test_t260925_04_file_blast_radius.py")
OWN = "own/own.txt"


# ---------------- real-git fixture helpers ----------------

def _git(root, *args, env=None):
    p = subprocess.run(["git"] + list(args), cwd=str(root), capture_output=True,
                       text=True, env=env)
    assert p.returncode == 0, "git %s failed: %s" % (" ".join(args), p.stderr)
    return p.stdout


def _stamp(root, *args, date):
    """Run a commit/merge with a pinned date: git's merge-base walk is date-ordered,
    so the fixture must not depend on the wall clock to reproduce the topology."""
    env = dict(os.environ, GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date,
               GIT_COMMITTER_NAME="t261029-64", GIT_COMMITTER_EMAIL="t@t261029-64",
               GIT_AUTHOR_NAME="t261029-64", GIT_AUTHOR_EMAIL="t@t261029-64")
    return _git(root, *args, env=env)


def _commit(root, msg, date):
    _git(root, "add", "-A")
    _stamp(root, "commit", "-qm", msg, date=date)
    return _git(root, "rev-parse", "HEAD").strip()


def _merge(root, ref, date):
    _stamp(root, "merge", "-q", "--no-edit", ref, date=date)
    return _git(root, "rev-parse", "HEAD").strip()


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _build(tmp_path: Path):
    """The measured topology.

    main:   c0 -> m1 (main's own work)
    line:   c0 -> L1 (the line's own work) -> M = merge(L1, m1)   [the line tip]
    lane:   m1 -> T1 (this ticket's write) -> T2 (foreign writes) -> N = merge(T2, L1)

    `git merge-base --all develop lane` then has two candidates (L1 and m1): L1 is
    reachable from the lane through N and from the line through M, and m1 likewise,
    and neither is an ancestor of the other. The plain command prints m1 (the newer
    side), which is exactly merge-base(main, lane) -> the degenerate basis.
    """
    root = tmp_path / "proj"
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q", "-b", "main", ".")
    _git(root, "config", "user.email", "t@t261029-64")
    _git(root, "config", "user.name", "t261029-64")
    _git(root, "config", "commit.gpgsign", "false")
    _write(root, "verify.yaml",
           "schema: v1\nlanes:\n  code:\n    write_allow:\n      - own/\n")
    _write(root, "base.txt", "b\n")
    c0 = _commit(root, "c0 baseline", "2026-10-29T10:00:00 +0800")
    # The line forks first and does its own work, then absorbs main (line tip = M).
    _git(root, "checkout", "-q", "-b", LINE, c0)
    _write(root, "server/engine/line_module.py", "LINE = 1\n")
    _write(root, "line-side.txt", "l\n")
    l1 = _commit(root, "L1 the line's own work", "2026-10-29T10:01:00 +0800")
    _git(root, "checkout", "-q", "main")
    _write(root, "main-side.txt", "m\n")
    m1 = _commit(root, "m1 main-side (main's own work)", "2026-10-29T10:02:00 +0800")
    _git(root, "checkout", "-q", LINE)
    line_tip = _merge(root, "main", "2026-10-29T10:03:00 +0800")
    # The lane forks from main's tip, writes its own file, writes two foreign files,
    # then merges the OLD line tip (the lane therefore carries the line's content
    # without ever absorbing the line's merge commit).
    _git(root, "checkout", "-q", "-b", LANE, m1)
    _write(root, OWN, "o\n")
    _commit(root, "T1 this ticket's own write", "2026-10-29T10:04:00 +0800")
    for rel in FOREIGN:
        _write(root, rel, "# foreign write by this ticket\n")
    t2 = _commit(root, "T2 foreign writes by this ticket", "2026-10-29T10:05:00 +0800")
    head = _merge(root, l1, "2026-10-29T10:06:00 +0800")
    return root, {"c0": c0, "l1": l1, "m1": m1, "line_tip": line_tip,
                  "t2": t2, "head": head}


def _baselines(root):
    """The producer's own resolution (agent_activities._merge_base_ref), so the
    numbers under test are the ones the merge gate really passes down."""
    base, _ = aa._merge_base_ref(LANE, root, other=LINE)
    base_other, _ = aa._merge_base_ref(LANE, root, other="main")
    return base, base_other


def _whitelist(root, **args):
    payload = {"lane": "code", "path": str(root), "require_base": True,
               "skip_slow": True, "write_set": ["own/"]}
    payload.update(args)
    res = vl.run(payload)
    hits = [c for c in res["checks"] if c.get("id") == vl.WS_CHECK_ID]
    assert hits, "write-set record lost its machine key: %r" % (res["checks"],)
    return res, hits[0]


def _details(rec):
    return [str(i.get("detail", "")) for i in (rec.get("items") or [])]


def _reason_codes(rec):
    return [str(i.get("reason_code", "")) for i in (rec.get("items") or [])]


def _named(rec, rel):
    """Is the path named anywhere on the record (red detail or green note)?"""
    blob = " ".join(_details(rec) + [str(rec.get("note") or "")])
    return rel in blob


# ---------------- A: the fixture really is the production shape ----------------

def test_a_topology_has_two_merge_bases_and_a_degenerate_basis(tmp_path):
    root, shas = _build(tmp_path)
    bases = _git(root, "merge-base", "--all", LINE, LANE).split()
    assert len(bases) == 2, \
        "the fixture must reproduce the two-candidate merge-base topology: %r" % (bases,)
    assert set(bases) == {shas["l1"], shas["m1"]}, bases
    base, base_other = _baselines(root)
    assert base and base_other and base == base_other, \
        ("the two baselines must coincide (the measured defect shape): %r vs %r"
         % (base, base_other))
    assert base == shas["m1"], (base, shas["m1"])
    # The producer resolves the other side's TIP too (a sha, not the branch name).
    tip, err = aa._tip_ref(LINE, root)
    assert (tip, err) == (shas["line_tip"], ""), (tip, err)


# ---------------- B: the bug, reproduced on this fixture ----------------

def test_b_old_caliber_charges_the_line_to_this_ticket(tmp_path):
    """With no other-side tip (the pre-fix caliber on a degenerate basis), every
    file of the judged diff is judged: the line's own work reds as an
    out-of-write-set write. This is the false red t261029-64 exists to remove."""
    root, _ = _build(tmp_path)
    base, base_other = _baselines(root)
    res, rec = _whitelist(root, base=base, base_other=base_other)
    assert res["green"] is False and rec["level"] == "red"
    for rel in LINE_ONLY:
        assert any(rel in d for d in _details(rec)), \
            "the old caliber must charge the line's file %s (bug reproduced): %s" % (
                rel, _details(rec))
    # ... and the degrade itself is already visible on the record (named, not silent)
    assert "degenerate basis" in (rec.get("note") or ""), rec.get("note")


# ---------------- C: the fix — content rule, named skip ----------------

def test_c_line_files_identical_to_the_tip_are_skipped_and_named(tmp_path):
    root, shas = _build(tmp_path)
    base, base_other = _baselines(root)
    res, rec = _whitelist(root, base=base, base_other=base_other,
                          base_other_tip=LINE)
    note = rec.get("note") or ""
    for rel in LINE_ONLY:
        assert _named(rec, rel), "the skip must NAME the file %s: %r" % (rel, rec)
        assert not any(("out-of-write-set" in d or "\u8d8a\u754c\u5199" in d)
                       and rel in d for d in _details(rec)), \
            "%s is byte-identical to the other side's tip and must never be judged " \
            "as this ticket's write: %s" % (rel, _details(rec))
    assert shas["line_tip"][:12] in note, \
        "the record must say which tip decided the skip: %r" % note
    assert "byte-identical to the other side's tip" in note, note
    # the ticket's own write stays inside its write set: no red for it
    assert not any(OWN in d for d in _details(rec)), _details(rec)


def test_c2_content_rule_is_a_content_question_not_a_name_question(tmp_path):
    """The line's file is byte-identical to the tip; the ticket's foreign write is
    not. Same topology, same rule, opposite verdicts — the rule really compares
    content instead of trusting where the file came from."""
    root, _ = _build(tmp_path)
    base, base_other = _baselines(root)
    res, rec = _whitelist(root, base=base, base_other=base_other,
                          base_other_tip=LINE)
    assert res["green"] is False, "the ticket's foreign writes must still red"
    for rel in FOREIGN:
        assert any(rel in d for d in _details(rec)), \
            "a genuine out-of-write-set write must still red: %s missing from %s" % (
                rel, _details(rec))
    assert not any(rel in d for rel in LINE_ONLY for d in _details(rec)), _details(rec)


# ---------------- D: the ticket's own foreign write still reds ----------------

def test_d_foreign_non_test_path_reds(tmp_path):
    root, _ = _build(tmp_path)
    base, base_other = _baselines(root)
    res, rec = _whitelist(root, base=base, base_other=base_other,
                          base_other_tip=LINE,
                          write_set=["own/", FOREIGN[1]],
                          ticket_id="t261029-64")
    assert rec["level"] == "red", _details(rec)
    assert any(FOREIGN[0] in d for d in _details(rec)), _details(rec)


def test_d2_foreign_test_path_outside_the_ticket_face_reds(tmp_path):
    """The t261029-38 anchor: its own arbitrate commit b69b32a edited
    test_t260925_04_file_blast_radius.py, outside its write set. The test file is not
    named after this ticket, so the ticket-test-face carve does not admit it and the
    red must survive — with the content rule on."""
    root, _ = _build(tmp_path)
    base, base_other = _baselines(root)
    res, rec = _whitelist(root, base=base, base_other=base_other,
                          base_other_tip=LINE,
                          write_set=["own/", FOREIGN[0]],
                          ticket_id="t261029-64")
    assert rec["level"] == "red", _details(rec)
    assert any(FOREIGN[1] in d for d in _details(rec)), _details(rec)


# ---------------- E: the green shape still names both facts ----------------

def test_e_green_receipt_names_the_skip_and_the_degenerate_basis(tmp_path):
    root, shas = _build(tmp_path)
    base, base_other = _baselines(root)
    res, rec = _whitelist(root, base=base, base_other=base_other,
                          base_other_tip=LINE, write_set=["own/"] + list(FOREIGN))
    assert res["green"] is True and rec["level"] == "green", _details(rec)
    note = rec.get("note") or ""
    assert "degenerate basis" in note, note
    assert base[:12] in note and shas["line_tip"][:12] in note, note
    assert "content comparison against the other side's tip" in note, note
    for rel in LINE_ONLY:
        assert rel in note, "every skipped file is listed: %r" % note


def test_e2_non_degenerate_basis_keeps_the_intersection_and_adds_no_basis_note(tmp_path):
    """No degenerate basis = no basis note (the t261022-08 record shape is untouched
    for the two-sided topology that already worked)."""
    root, shas = _build(tmp_path)
    res, rec = _whitelist(root, base=shas["l1"], base_other=shas["m1"],
                          base_other_tip=LINE, write_set=["own/"] + list(FOREIGN))
    assert res["green"] is True and rec["level"] == "green", _details(rec)
    note = rec.get("note") or ""
    assert "degenerate basis" not in note, note
    # the intersection (base=l1) sees only the ticket's own work, so nothing is
    # skipped by the content rule here — the record stays quiet about the line.
    assert "line-side.txt" not in note, note


# ---------------- F: fail-closed on an unusable tip ----------------

def test_f_unresolvable_other_tip_is_red_and_judges_nothing(tmp_path):
    root, _ = _build(tmp_path)
    base, base_other = _baselines(root)
    res, rec = _whitelist(root, base=base, base_other=base_other,
                          base_other_tip="no-such-ref-t261029-64")
    assert res["green"] is False and rec["level"] == "red"
    assert "other_tip_unresolved" in _reason_codes(rec), _reason_codes(rec)
    assert len(_details(rec)) == 1, \
        "an unusable tip judges nothing (no partial verdict): %s" % (_details(rec),)
    assert not any(rel in d for d in _details(rec) for rel in LINE_ONLY + FOREIGN), \
        _details(rec)


def test_f2_t261022_items_keep_their_red_behaviour_with_a_tip_present(tmp_path):
    """Requirement 4: the fail-closed items stay red even with the content rule on."""
    root, _ = _build(tmp_path)
    base, _ = _baselines(root)
    head = _git(root, "rev-parse", "HEAD").strip()
    # an empty second diff (base_other already contains HEAD) is a named red
    res, rec = _whitelist(root, base=base, base_other=head,
                          base_other_tip=LINE)
    assert res["green"] is False and "baseline_diff_empty" in _reason_codes(rec), \
        _reason_codes(rec)
    # a failed second diff stays a named red too
    res2, rec2 = _whitelist(root, base=base, base_other="no-such-ref-t261022-08",
                            base_other_tip=LINE)
    assert res2["green"] is False and "baseline_diff_failed" in _reason_codes(rec2), \
        _reason_codes(rec2)


# ---------------- G: wiring through the real merge_check ----------------

class _FakeProc:
    def __init__(self, payload):
        self.pid = 0
        self.returncode = 0
        self._payload = payload

    async def communicate(self):
        return json.dumps(self._payload).encode("utf-8"), b""


def test_g_merge_check_resolves_and_passes_the_other_side_tip(tmp_path, monkeypatch):
    """The real merge_check must pass the line TIP down, and the whitelist's skip note
    must reach the merge_check row: a user reading a green merge receipt can still see
    which rule decided the skip (requirement 1: no silent skip at the gate face)."""
    root, shas = _build(tmp_path)
    seen = {}

    async def _spawn(*args, **kwargs):
        payload = json.loads(args[4])
        seen.setdefault("payloads", []).append(payload)
        note = ("t261029-64: 2 file(s) byte-identical to the other side's tip %s "
                "(no resulting change, not this ticket's write) and not judged: %s"
                % (str(payload.get("base_other_tip", ""))[:12], ", ".join(LINE_ONLY)))
        if payload.get("lane") != "code":
            return _FakeProc({"ok": True, "result": {}})
        return _FakeProc({"ok": True, "result": {
            "green": True, "exit_code": 0, "red_count": 0,
            "checks": [{"check": "write set", "level": "green", "items": [],
                        "id": "write_set_whitelist", "note": note}]}})

    monkeypatch.setattr(aa.asyncio, "create_subprocess_exec", _spawn)
    saved = aa.REPO_ROOT
    try:
        aa.REPO_ROOT = root
        core = asyncio.run(aa.merge_check(aa.MergeCheckArgs(
            ticket_id="t261029-64", worktree=str(root), branch=LANE,
            base_ref=shas["c0"], write_set=["own/"], base_other_ref=LINE)))
    finally:
        aa.REPO_ROOT = saved

    payloads = [p for p in seen.get("payloads", []) if p.get("lane") == "code"]
    assert payloads, "merge_check never called verify_lane code: %r" % (seen,)
    pay = payloads[-1]
    assert pay.get("base_other_tip") == shas["line_tip"], pay
    row = [c for c in core.checks if c.get("id") == "verify_lane_code"][0]
    assert "byte-identical to the other side's tip" in (row.get("note") or ""), row
