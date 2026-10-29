#!/usr/bin/env python3
"""t261029-18 — a multi-repo lane's ROOT tree is on lane/<id>-root while the gate
hands the placeholder lane/<id>: the file-level blast radius must stop degrading.

intent (what this case verifies; grey-box L2, offline, seconds)

  A INCIDENT SHAPE. On a real multi-repo lane (root-tree worktree on
    lane/<id>-root, one member worktree on lane/<id>-<member>, the on-disk
    repo_worktrees.json the engine writes), the REAL changed_files activity, handed
    the placeholder branch, returns the committed and dirty files of every tree
    (member paths repo-prefixed) with no error, and the real decision faces
    (shared.changed_files_blast_radius + shared.targeted_rerun_plan) narrow instead
    of returning the full-run sentinel.
  B NON-VACUITY. The placeholder really does not resolve on that lane and the
    root-tree twin does (read from git), so A cannot pass by accident; and the
    pre-fix failure input still rides the sentinel.
  C MANIFEST ABSENT ON A MULTI-REPO LANE. A resolved root-tree twin is itself the
    evidence that the lane's root branch is lane/<id>-root, i.e. a multi-repo lane whose
    manifest - the only way to enumerate the member trees - is gone. The root tree alone
    is not the lane's change set, so the receipt must FAIL CLOSED (a named error, no
    partial list, the full-run sentinel): a root-only list would let the round narrow
    while member commits and dirty files stay unseen. A manifest-free SINGLE-repo lane
    keeps returning its own list (control).
  D FAIL-CLOSED. An unresolvable name, a corrupt manifest and a missing member tree
    each give files == [] plus a named error and the full-run sentinel, and never
    raise (accepted plan A4).
  E SHARED-FACE RAIL. A member path whose tail is a shared face (a member-repo
    verify.yaml) reads shared, so a prefixed member path cannot silently narrow the
    round.
  F GREEN-RUN ANCHOR. lane_head_sha on the same real lane resolves the root-tree tip
    (the merge gate's green-run face can be recorded again) and keeps its fail-closed
    shape for an unresolvable name.

Why L1 cannot carry it: the unit tier bans real git (server/engine/tests/conftest.py),
and this property is git ref resolution over the assembled multi-repo lane shape.
Why not L3: the workflow arm needs a real worker and Temporal (engine/exclusive pool,
minutes) and would re-run the same activity; the one link only the assembly holds (the
gate handing meta.branch down) is pinned by the engine unit battery.
Intent split: the candidate truth tables, the failure-message matrix, the wall-clock
leg and the naming lock belong to developer L1
(server/engine/tests/test_t261029_18_lane_branch_root.py); THIS case uniquely owns the
real-git lane shapes and the composed decision.

The ordinary (manifest-present) path emits one scope line per tree, and a leg reads it
back in-process - the ticket's "write the degrade into the gate log" requirement.
The lane shapes come from the shared real-git fixture (integration/t260921-09/
lib_lane_fixture.py, whose build_lane takes repo "" = the project-root tree and
with_manifest=False); this file only drives the real activities and judges.

Three states: exit 0 = all pass, 1 = any FAIL (product red), 2 = ENV_FAIL
(git or the engine venv is missing).
"""
import asyncio
import logging
import re
import shutil
import sys
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "t260921-09"
sys.path.insert(0, str(FIXTURE_DIR))
import lib_lane_fixture as FX  # noqa: E402


class _Capture(logging.Handler):
    """Collect the records the activity logger emits (the gate log face, in-process)."""

    def __init__(self):
        super().__init__(level=logging.INFO)
        self.lines = []

    def emit(self, record):
        try:
            self.lines.append(record.getMessage())
        except Exception:  # noqa: BLE001 — a malformed record is not a test failure
            pass


def drive_changed_files(shared, aa, lane, branch, tid):
    """Drive the REAL activity. Returns (result, raised) so a raise is a named FAIL.

    The accepted plan promises the activity never raises on a bad lane shape (A4); a
    raise must therefore be visible as a failed leg, not as a crashed scenario.
    """
    try:
        res = asyncio.run(aa.changed_files(
            shared.ChangedFilesArgs(ticket_id=tid, worktree=str(lane), branch=branch)))
        return res, ""
    except Exception as e:  # noqa: BLE001
        return None, "%s: %s" % (type(e).__name__, str(e)[:240])


def receipt(res):
    """(files, error, resolved) of a changed_files receipt, as plain values."""
    if res is None:
        return [], "<no receipt>", []
    files = [str(x) for x in (getattr(res, "files", None) or [])]
    err = str(getattr(res, "error", "") or "")
    resolved = [str(x) for x in (getattr(res, "resolved", None) or [])]
    return files, err, resolved


def root_lane(project, tid, root_spec, member_specs, write_set, with_manifest=True):
    """The engine's multi-repo lane shape: repo "" first = the project-root tree.

    build_lane creates the root tree's worktree first (it IS the lane container) and
    writes the manifest members-first, root entry last, through the engine's own
    naming source.
    """
    specs = {"": dict(root_spec or {})}
    specs.update(member_specs)
    return project.build_lane(tid, specs, write_set, with_manifest=with_manifest)


def main():
    FX.ensure_engine_runtime()  # no temporalio -> re-exec the engine venv; missing = exit 2
    shared, aa = FX.load_engine()
    L = FX.Legs("lane-branch-root")
    projects = []

    def project(single=False):
        p = FX.TempProject(single=single)
        projects.append(p)
        return p

    try:
        # ---------------- A/B: the incident shape and its non-vacuity -------------
        p = project()
        tid = "t26102918a"
        p.init_repo("", {".gitignore": "/repo_a/\n", "docs/root.md": "base\n"})
        p.init_repo("repo_a", {"src/a.py": "base\n"})
        lane = root_lane(
            p, tid,
            root_spec={"commit": ("docs/root.md", "lane work\n"),
                       "out_dirty": "docs/notes.md"},
            member_specs={"repo_a": {"commit": ("src/a.py", "lane work\n"),
                                     "out_dirty": "src/scratch.py"}},
            write_set=["docs/root.md", "repo_a/src/a.py"])
        ph = "lane/%s" % tid
        root_branch = "lane/%s-root" % tid
        member_branch = "lane/%s-repo_a" % tid

        bad = FX.git("rev-parse", "--verify", ph, cwd=lane)
        good = FX.git("rev-parse", "--verify", root_branch, cwd=lane)
        L.check("A1 non-vacuity: the placeholder does not resolve on the lane, "
                "the root-tree twin does",
                bad.returncode != 0 and good.returncode == 0,
                "placeholder rc=%s twin rc=%s" % (bad.returncode, good.returncode))
        st = FX.git("status", "--porcelain", "--untracked-files=all", cwd=lane).stdout
        L.check("A2 layout parity: the root tree's status carries no member-tree "
                "entry (the real multi-repo layout ignores members at the root)",
                "repo_a" not in st, st[:200].replace("\n", " | "))

        logger = logging.getLogger("temporalio.activity")
        level_before = logger.level
        cap = _Capture()
        logger.setLevel(logging.INFO)
        logger.addHandler(cap)
        try:
            res, raised = drive_changed_files(shared, aa, lane, ph, tid)
        finally:
            logger.removeHandler(cap)
            logger.setLevel(level_before)
        files, err, resolved = receipt(res)
        L.check("A3 a raise never reaches the caller (the activity reports, it does "
                "not throw)", raised == "", raised)
        L.check("A4 the committed ROOT file is in the list", "docs/root.md" in files,
                str(files[:8]))
        L.check("A5 the dirty ROOT file is in the list", "docs/notes.md" in files,
                str(files[:8]))
        L.check("A6 the member commit AND the member dirty file are listed, "
                "repo-prefixed",
                "repo_a/src/a.py" in files and "repo_a/src/scratch.py" in files,
                str(files[:8]))
        L.check("A7 no error (the incident shape produced one and forced a full run)",
                err == "", err[:240])
        L.check("A8 no directory-folded entry can reach the radius",
                not any(f.endswith("/") for f in files), str(files[:8]))
        L.check("A9 the receipt names the branch each scope was measured on",
                any(root_branch in r for r in resolved)
                and any(member_branch in r for r in resolved), str(resolved))
        L.check("A9b the gate log line names scope and resolved branch "
                "(the ticket's log requirement on the ordinary path)",
                any("changed_files: scope=" in ln and root_branch in ln
                    for ln in cap.lines), str(cap.lines[-3:]))
        radius = shared.changed_files_blast_radius(files, err)
        plan = shared.targeted_rerun_plan(["docs/root.md", "repo_a/src/a.py"],
                                          ["sc_fixture_red"],
                                          changed_files=files, diff_error=err)
        L.check("A10 the decision narrows instead of the full-run sentinel",
                radius == "localized" and plan == ["sc_fixture_red"],
                "radius=%s plan=%r" % (radius, plan))
        L.check("A11 non-vacuity control: the pre-fix failure input rides the "
                "sentinel",
                shared.targeted_rerun_plan(["docs/root.md"], ["sc_fixture_red"],
                                           changed_files=[],
                                           diff_error="merge-base failed") == [])

        # ---------------- F: the green-run anchor on the same real lane -----------
        tip = FX.git_ok("rev-parse", root_branch, cwd=lane)
        gs = asyncio.run(aa.lane_head_sha(
            aa.LaneHeadShaArgs(ticket_id=tid, worktree=str(lane), branch=ph)))
        L.check("F1 the green-run anchor resolves the root-tree tip instead of "
                "failing every round",
                getattr(gs, "ok", False) is True and str(getattr(gs, "sha", "")) == tip,
                "ok=%r sha=%r tip=%r" % (getattr(gs, "ok", None),
                                         str(getattr(gs, "sha", ""))[:12],
                                         tip[:12]))
        gb = asyncio.run(aa.lane_head_sha(
            aa.LaneHeadShaArgs(ticket_id=tid, worktree=str(lane),
                               branch="lane/ghost-%s" % tid)))
        L.check("F2 an unresolvable name keeps the fail-closed shape "
                "(ok=False + a named error)",
                getattr(gb, "ok", None) is False
                and str(getattr(gb, "error", "") or "").strip() != "",
                str(getattr(gb, "error", ""))[:200])

        # ---------------- C: manifest ABSENT on a multi-repo lane ----------------
        # The members carry a committed change and a dirty file; the root ignores them.
        # With no manifest the root tree alone is NOT the lane's change set: resolving
        # the twin and returning the root list would narrow the round while the member
        # work stays unseen (the pre-fix code failed closed here).
        p = project()
        tid = "t26102918b"
        p.init_repo("", {".gitignore": "/repo_a/\n", "docs/root.md": "base\n"})
        p.init_repo("repo_a", {"src/a.py": "base\n"})
        lane = root_lane(p, tid,
                         root_spec={"commit": ("docs/root.md", "lane work\n")},
                         member_specs={"repo_a": {"commit": ("src/a.py", "work\n"),
                                                  "out_dirty": "src/scratch.py"}},
                         write_set=["docs/root.md", "repo_a/src/a.py"],
                         with_manifest=False)
        ph = "lane/%s" % tid
        root_branch = "lane/%s-root" % tid
        res, raised = drive_changed_files(shared, aa, lane, ph, tid)
        files, err, resolved = receipt(res)
        L.check("C1 the manifest-absent multi-repo shape fails closed "
                "(named error, no partial list, no raise)",
                raised == "" and files == [] and err.strip() != "",
                "%s | %s | %s" % (raised, err[:200], str(files[:6])))
        L.check("C2 the diagnostic names what failed (the manifest / the member "
                "enumeration)",
                any(w in err.lower() for w in ("manifest", "member", "multi-repo")),
                err[:240])
        L.check("C3 that error rides the full-run sentinel (the round cannot narrow)",
                shared.targeted_rerun_plan(["docs/root.md", "repo_a/src/a.py"],
                                           ["sc_prev_red"], changed_files=files,
                                           diff_error=err) == [],
                "files=%s err=%s" % (str(files[:4]), err[:120]))
        # control: a manifest-free SINGLE-repo lane still returns its own list, so the
        # guard cannot be a blanket refusal of every manifest-free lane.
        p = project(single=True)
        tid = "t26102918b2"
        p.init_repo("", {"docs/x.md": "base\n"})
        lane = p.build_single_lane(tid, {"commit": ("docs/x.md", "work\n"),
                                         "out_dirty": "docs/notes.md"},
                                   write_set=["docs/x.md"])
        res, raised = drive_changed_files(shared, aa, lane, "lane/%s-single" % tid, tid)
        files, err, _ = receipt(res)
        L.check("C4 control: a manifest-free single-repo lane still returns its own list",
                raised == "" and err == "" and "docs/x.md" in files,
                "%s | %s | %s" % (raised, err[:160], str(files[:6])))

        # ---------------- D: fail-closed matrix ----------------------------------
        p = project(single=True)
        tid = "t26102918d"
        p.init_repo("", {"docs/x.md": "base\n"})
        lane = p.build_single_lane(tid, {"commit": ("docs/x.md", "work\n")},
                                   write_set=["docs/x.md"])
        ghost = "lane/ghost-%s" % tid
        res, raised = drive_changed_files(shared, aa, lane, ghost, tid)
        files, err, _ = receipt(res)
        L.check("D1 an unresolvable name is a named fail-closed error, never a raise",
                raised == "" and files == [] and ghost in err,
                "%s | %s" % (raised, err[:200]))
        L.check("D2 that error rides the full-run sentinel",
                shared.targeted_rerun_plan(["docs/x.md"], ["sc_fixture_red"],
                                           changed_files=[], diff_error=err) == [])

        p = project()
        tid = "t26102918d2"
        p.init_repo("", {".gitignore": "/repo_a/\n", "docs/root.md": "base\n"})
        p.init_repo("repo_a", {"src/a.py": "base\n"})
        lane = root_lane(p, tid,
                         root_spec={"commit": ("docs/root.md", "lane work\n")},
                         member_specs={"repo_a": {}},
                         write_set=["docs/root.md"])
        (Path(lane) / aa.MULTI_MANIFEST_REL).write_text("{not json", encoding="utf-8")
        res, raised = drive_changed_files(shared, aa, lane, "lane/%s" % tid, tid)
        files, err, _ = receipt(res)
        L.check("D3 a corrupt manifest is a named error (the manifest is named), "
                "never a raise and never a partial list",
                raised == "" and files == [] and "manifest" in err.lower(),
                "%s | %s" % (raised, err[:220]))

        p = project()
        tid = "t26102918d3"
        p.init_repo("", {".gitignore": "/repo_a/\n", "docs/root.md": "base\n"})
        p.init_repo("repo_a", {"src/a.py": "base\n"})
        lane = root_lane(p, tid,
                         root_spec={"commit": ("docs/root.md", "lane work\n")},
                         member_specs={"repo_a": {"commit": ("src/a.py", "work\n")}},
                         write_set=["docs/root.md", "repo_a/src/a.py"])
        shutil.rmtree(lane / "repo_a")
        res, raised = drive_changed_files(shared, aa, lane, "lane/%s" % tid, tid)
        files, err, _ = receipt(res)
        L.check("D4 a missing member tree is a named error and no partial list, "
                "never a raise (accepted plan A4)",
                raised == "" and files == [] and err.strip() != "",
                "%s | %s" % (raised, err[:220]))

        # ---------------- E: shared-face rail over a prefixed member path ---------
        p = project()
        tid = "t26102918e"
        p.init_repo("", {".gitignore": "/repo_a/\n", "docs/root.md": "base\n"})
        p.init_repo("repo_a", {"verify.yaml": "checks: []\n", "src/a.py": "base\n"})
        lane = root_lane(
            p, tid, root_spec={},
            member_specs={"repo_a": {"commit": ("verify.yaml", "checks: [x]\n")}},
            write_set=["repo_a/verify.yaml"])
        res, raised = drive_changed_files(shared, aa, lane, "lane/%s" % tid, tid)
        files, err, _ = receipt(res)
        L.check("E1 the member verify.yaml is in the list (prefixed)",
                raised == "" and "repo_a/verify.yaml" in files,
                "%s | %s" % (raised, str(files[:6])))
        L.check("E2 a member path whose tail is a shared face reads shared "
                "(the round cannot narrow)",
                bool(files) and shared.changed_files_blast_radius(files, err)
                == "shared",
                "%s / %s" % (shared.changed_files_blast_radius(files, err),
                             str(files[:6])))
        L.check("E3 control: a member path with no shared tail stays localized",
                shared.changed_files_blast_radius(["repo_a/src/a.py"], "")
                == "localized")
    finally:
        for p in projects:
            p.cleanup()
    L.finish()


if __name__ == "__main__":
    main()
