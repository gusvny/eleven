"""t261022-08 unit tests (L1): the write-set whitelist's fail-open hole around the
two-sided intersection basis.

The defect (measured on this host while repairing t260915-05): a lane branch
carrying a committed file OUTSIDE the ticket's write set reached the merge stage
with merge_check GREEN. The whitelist judges "this ticket's own write" as the
INTERSECTION of two three-dot diffs (base...HEAD and base_other...HEAD); a file
absent from the second diff used to be skipped one by one, silently. When the
second diff yielded NO file at all (base_other already contains HEAD: a line that
absorbed the lane, or a caller passing the lane head), every file was skipped and
the check came out GREEN with zero items - a whole diff escaping judgement.

Faces under test, all on real tmp git repos (zero network, zero Temporal):
  A  control: an intact basis still judges the probe red (no regression, and the
     other side's work is still not charged to this ticket);
  B  THE HOLE: an empty intersection over a non-empty judged diff is RED, names
     the reason code and the file (never a silent green);
  C  fail-closed: an uncomputable basis (bad ref) is RED with a named reason and
     judges nothing;
  D  lawful admission 1 stays green and named (ticket test face, t261004-25);
  E  lawful admission 2 stays green and named (declared build-chain out prefix
     whose paired src the write set covers, t261009-38/-46);
  F  the residual visibility face: an empty judged diff is a NAMED green, never a
     silent one;
  G  the old one-sided caliber (no base_other) is unchanged.
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent
sys.path.insert(0, str(ENGINE))
sys.path.insert(0, str(ENGINE.parent / "tools"))

import path_gates as pg  # noqa: E402
import verify_lane as vl  # noqa: E402

PROBE = "server/zz_t26102208_probe.py"


# ---------------- fixture helpers ----------------

def _git(root, *args, **kw):
    p = subprocess.run(["git"] + list(args), cwd=str(root),
                       capture_output=True, text=True)
    if kw.get("check", True) and p.returncode != 0:
        raise AssertionError("git %s failed: %s" % (" ".join(args), p.stderr))
    return p


def _commit(root, msg):
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", msg)
    return _git(root, "rev-parse", "HEAD").stdout.strip()


def _mb(root, a, b):
    return _git(root, "merge-base", a, b).stdout.strip()


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _build(tmp_path, lane_files, merge_main=True, name="lane"):
    """Diverged topology (t260901-18 shape): main carries its own commit, a line
    branch (`lane-line`) carries its own, the ticket branch forks from the line
    tip and commits `lane_files`, then optionally syncs main."""
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q", ".")
    _git(root, "config", "user.email", "t@t261022-08")
    _git(root, "config", "user.name", "t261022-08")
    _write(root, "verify.yaml",
           "schema: v1\nlanes:\n  code:\n    write_allow:\n      - allow-fallback.txt\n")
    _write(root, "base.txt", "b\n")
    c0 = _commit(root, "c0 baseline")
    _git(root, "branch", "-M", "main")
    _write(root, "main-side.txt", "m\n")
    _commit(root, "c1 main-side (main's own work)")
    _git(root, "branch", "lane-line", c0)
    _git(root, "checkout", "-q", "lane-line")
    _write(root, "line-side.txt", "l\n")
    _commit(root, "c2 line-side (the line's own work)")
    _git(root, "checkout", "-q", "-b", "lane/t261022-08")
    for rel, text in lane_files.items():
        _write(root, rel, text)
    _commit(root, "c3 this ticket's write")
    if merge_main:
        _git(root, "merge", "-q", "--no-edit", "main")
    return root


def _whitelist(root, **args):
    payload = {"lane": "code", "path": str(root), "require_base": True,
               "skip_slow": True}
    payload.update(args)
    res = vl.run(payload)
    hits = [c for c in res["checks"] if c.get("id") == vl.WS_CHECK_ID]
    assert hits, "write-set record lost its machine key: %r" % (res["checks"],)
    return res, hits[0]


def _details(rec):
    return [str(i.get("detail", "")) for i in (rec.get("items") or [])]


def _reason_codes(rec):
    return [str(i.get("reason_code", "")) for i in (rec.get("items") or [])]


LANE = {"own/own.txt": "o\n", PROBE: "probe = 1\n"}


# ---------------- A. control: an intact basis still judges ----------------

def test_a_intact_basis_judges_the_probe_red_and_charges_no_side(tmp_path):
    root = _build(tmp_path, LANE)
    base, base_other = _mb(root, "lane-line", "HEAD"), _mb(root, "main", "HEAD")
    assert base and base_other and base != base_other, "topology must be two-sided"
    res, rec = _whitelist(root, base=base, base_other=base_other, write_set=["own/"])
    assert res["green"] is False and rec["level"] == "red"
    assert len(_details(rec)) == 1 and PROBE in _details(rec)[0], _details(rec)
    # the other side's work is still NOT charged to this ticket ...
    assert not any("main-side.txt" in d for d in _details(rec))
    # ... and the per-file skip that produces that calm is NAMED on the record:
    # main-side.txt (main's own commit, carried in by the lane's main sync) is the
    # one file the intersection attributes to the other baseline.
    assert "main-side.txt" in (rec.get("note") or ""), \
        "a per-file skip must be named on the record: %r" % (rec.get("note"),)


def test_a2_old_one_sided_caliber_unchanged(tmp_path):
    # No base_other = the legacy caliber, byte for byte: everything in base...HEAD
    # is judged, so the probe is red (this door never failed open).
    root = _build(tmp_path, LANE)
    res, rec = _whitelist(root, base=_mb(root, "main", "HEAD"), write_set=["own/"])
    assert res["green"] is False and rec["level"] == "red"
    assert len(_details(rec)) == 2 and any(PROBE in d for d in _details(rec)), _details(rec)


# ---------------- B. THE HOLE: empty intersection is red ----------------

def test_b_empty_intersection_is_red_and_names_the_file(tmp_path):
    """The measured fail-open: base_other is a ref that already contains HEAD, so
    the second diff lists nothing. Every file used to be skipped => GREEN over an
    out-of-write-set lane commit. Now: red, named reason, file named."""
    root = _build(tmp_path, LANE)
    head = _git(root, "rev-parse", "HEAD").stdout.strip()
    res, rec = _whitelist(root, base=_mb(root, "lane-line", "HEAD"),
                          base_other=head, write_set=["own/"])
    assert res["green"] is False, "empty intersection must never be green"
    assert rec["level"] == "red"
    assert "baseline_diff_empty" in _reason_codes(rec), _reason_codes(rec)
    assert any(PROBE in d for d in _details(rec)), \
        "the unjudged file must be named by filename (merge receipt is findable): %s" % (_details(rec),)


def test_b2_line_that_absorbed_the_lane_is_red_not_green(tmp_path):
    """The production shape of the same hole: base_other (or base) resolves to a
    ref that already contains the lane head (a develop line that took the lane's
    commits). Nothing can be attributed => red, never a silent pass."""
    root = _build(tmp_path, LANE)
    _git(root, "branch", "line/absorbed", "HEAD")
    res, rec = _whitelist(root, base=_mb(root, "lane-line", "HEAD"),
                          base_other="refs/heads/line/absorbed", write_set=["own/"])
    assert res["green"] is False and rec["level"] == "red"
    assert "baseline_diff_empty" in _reason_codes(rec), _reason_codes(rec)


# ---------------- C. uncomputable basis is red with a named reason ----------------

def test_c_uncomputable_basis_is_red_named_and_judges_nothing(tmp_path):
    root = _build(tmp_path, LANE)
    res, rec = _whitelist(root, base=_mb(root, "lane-line", "HEAD"),
                          base_other="no-such-ref-t261022-08", write_set=["own/"])
    assert res["green"] is False and rec["level"] == "red"
    assert "baseline_diff_failed" in _reason_codes(rec), _reason_codes(rec)
    assert any("no-such-ref-t261022-08" in d for d in _details(rec))
    # fail-closed = no partial judgement: no per-file verdict is invented
    assert not any(PROBE in d for d in _details(rec)), _details(rec)
    assert len(_details(rec)) == 1, _details(rec)


# ---------------- D. lawful admission 1: ticket test face ----------------

def test_d_ticket_test_face_still_green_and_named(tmp_path):
    face = "server/engine/tests/test_t261022_08_face.py"
    assert pg.is_ticket_test_face(face, "t261022-08")
    root = _build(tmp_path, {"own/own.txt": "o\n", face: "def test_x():\n    pass\n"})
    res, rec = _whitelist(root, base=_mb(root, "lane-line", "HEAD"),
                          base_other=_mb(root, "main", "HEAD"),
                          write_set=["own/"], ticket_id="t261022-08")
    assert res["green"] is True and rec["level"] == "green", _details(rec)
    note = rec.get("note") or ""
    assert pg.TICKET_TEST_FACE_NOTE in note and face in note, note


def test_d2_out_of_set_non_test_file_is_not_admitted(tmp_path):
    # Opposite control of D: the same topology with a non-test-face out-of-set file
    # stays red (the admission is narrow, not a general widening).
    root = _build(tmp_path, LANE)
    res, rec = _whitelist(root, base=_mb(root, "lane-line", "HEAD"),
                          base_other=_mb(root, "main", "HEAD"),
                          write_set=["own/"], ticket_id="t261022-08")
    assert rec["level"] == "red" and any(PROBE in d for d in _details(rec))


# ---------------- E. lawful admission 2: declared build-chain out prefix ----------------

def test_e_bundle_out_admission_still_green_and_named(tmp_path):
    """The out prefix is outside the ticket write set but its paired src is inside:
    merge_check widens the set before calling verify_lane (t261009-38), and the
    widening carries a named note. The widened set must still pass here."""
    import agent_activities as aa  # reachable where the engine venv has temporalio

    root = _build(tmp_path, {"ui/src/a.tsx": "export const A = 1;\n",
                             "ui/lib/bundle.js": "var A=1;\n"})
    _write(root, "server/merge-checks.yaml",
           "bundle_pairs:\n"
           "  - src: ui/src/\n"
           "    out: ui/lib/\n")
    eff, note = aa._bundle_widened_write_set(root, ["ui/src/"])
    assert "ui/lib" in eff and pg.BUNDLE_OUT_FACE_NOTE in note and "ui/lib" in note, (eff, note)

    base, base_other = _mb(root, "lane-line", "HEAD"), _mb(root, "main", "HEAD")
    # Without the widening the declared output is an out-of-set write (red).
    res0, rec0 = _whitelist(root, base=base, base_other=base_other, write_set=["ui/src/"])
    assert rec0["level"] == "red" and any("ui/lib/bundle.js" in d for d in _details(rec0))
    # With the widening (the production call shape) it is admitted: green.
    res, rec = _whitelist(root, base=base, base_other=base_other, write_set=eff)
    assert res["green"] is True and rec["level"] == "green", _details(rec)


# ---------------- F. residual visibility: empty judged diff is named ----------------

def test_f_empty_judged_diff_is_a_named_green(tmp_path):
    """A judged diff with no file has nothing to judge (the branch has no commit
    since its own baseline). It stays green - blocking that is the commit item's
    job - but the record must SAY so, never be silently empty."""
    root = _build(tmp_path, LANE)
    head = _git(root, "rev-parse", "HEAD").stdout.strip()
    res, rec = _whitelist(root, base=head, base_other=_mb(root, "main", "HEAD"),
                          write_set=["own/"])
    assert rec["level"] == "green" and not _details(rec)
    assert "nothing to judge" in (rec.get("note") or ""), rec.get("note")


def test_f2_clean_lane_stays_green_without_noise(tmp_path):
    # No regression on the ordinary green: a lane whose judged diff holds only
    # in-write-set writes is green with no note at all (the skip note only appears
    # when the intersection really does attribute a file to the other baseline).
    root = _build(tmp_path, {"own/own.txt": "o\n", "own/more.txt": "m\n"},
                  merge_main=False)
    res, rec = _whitelist(root, base=_mb(root, "lane-line", "HEAD"),
                          base_other=_mb(root, "main", "HEAD"), write_set=["own/"])
    assert res["green"] is True and rec["level"] == "green"
    assert "note" not in rec, rec.get("note")
