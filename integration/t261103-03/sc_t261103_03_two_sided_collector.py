#!/usr/bin/env python3
"""Two-sided change set inside the per-scope collector (ticket t261103-03).

Intent (grey-box L3, `ro` pool, real git fixtures, seconds, zero docker, zero browser,
zero console, never touches 3099/7233): a develop-buffer lane sits on its line and has
also synced main. Its change set must count only what the ticket itself wrote, per
scope: the intersection of the diff against main and the diff against the line. The
receipt must name the basis, keep the per-scope resolution face, and fail closed by name
when the line side is unreadable.

Why this case exists (KI-459, KI-458): main and the line each carried one changed-file
collector, and the two disagree only where the two sides meet. Measured on t261102-09, an
integration-only buffer ticket was charged the whole line: 21 integration paths, a full
784-entry round pinned to the 900 s budget. This case drives the REAL activity
(`agent_activities.changed_files`) and the REAL decision writer
(`shared.targeted_rerun_plan`) over self-built real-git buffer lanes. It judges the
receipt and the decision, never an internal helper name and never source text: the
structure locks belong to the developer family, and a contract-preserving refactor must
not red this case.

Legs:

  A  two-sided caliber on a buffer lane: the line's carried file is NOT the ticket's
     write, the ticket's own file IS, and the receipt names the basis.
  B  per scope: the member scope drops its own line-carried file, keeps its own write
     with the project-root prefix, and `resolved` names every scope.
  C  control, no other side named: the historical caliber is intact - the line's files
     ARE in the list and the basis says main. The two-sided caliber is opt-in.
  D  control, other side named as main: the same list as C and basis main (a second
     baseline is never charged twice, and main is never read twice).
  E  unreadable other side: files=[], a named error that carries the side and the
     merge-base marker, and the decision face does NOT narrow.
  F  unreadable other side in ONE member scope: the whole call fails closed with that
     scope's tag - never a partial list.
  G  the status face is not intersected: an untracked own file still counts under the
     two-sided caliber, in both scopes.
  H  the sibling mount is not resurrected by the two-sided caliber.
  I  a single-repo lane keeps the two-sided caliber (shape control, no repo prefix).

ENV_FAIL (exit 2) covers only context the fixture builds: git absent, engine modules
unimportable, a fixture git step failing. An engine answer that reports the other side
unreadable is NOT an environment red here - the fixture resolves that ref, so the answer
is the product behaviour under test (legs E/F). A pre-implementation red is the named TDD
signal; green is required at the integration gate and merge.

intent split (checked against the SCENARIOS list): t261031-17-multirepo-changed-files owns
the per-scope baseline, the branch naming and the mount drop; t260925-04-file-blast-radius
owns the real-git blast-radius chain; t260925-04-full-run-invariants owns the
malformed-input truth tables; t261029-18-lane-branch-root owns the root-twin naming;
t260930-02-surface-plan-query owns the selector state machine. THIS case owns one thing:
which files a buffer ticket pays for (the two-sided caliber inside the per-scope
collector) and the fail-closed direction when that second baseline is unreadable. The
fixture technique is shared with the sibling cases; shared steps are not shared intent.
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from lib_env import env_fail  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
ENGINE_SRC = REPO / "server" / "engine"
sys.path.insert(0, str(ENGINE_SRC))

TICKET_ID = "t261103-03"
#: The two sides a buffer lane is measured against.
BASE_BRANCH = "main"
LINE_BRANCH = "line/develop-buffer"
#: The branch name the gate hands down (`meta.branch`). A multi-repo lane's real root
#: branch is the `-root` twin; the manifest names each scope's real branch, so this
#: placeholder only has to be carried, never to resolve on its own.
TICKET_BRANCH = "lane/" + TICKET_ID
MEMBER = "member"

#: The line's carried work: files the LINE landed and main never had (the measured
#: shape of the KI-458 charge).
ROOT_LINE_FILE = "integration/t261030-35/line_only.mjs"
MEMBER_LINE_FILE = "parts/line_only.json"
#: The ticket's own work: one committed file per scope plus one untracked file.
ROOT_OWN_FILE = "integration/t261103-03/sc_own.py"
MEMBER_OWN_FILE = "parts/own.txt"
ROOT_DRIFT_FILE = "integration/t261103-03/sc_dirty.py"
MEMBER_DRIFT_FILE = "parts/dirty.txt"
#: A main-side file no ticket wrote: it must never enter the change set through the
#: second baseline alone (it is in the line diff but not in the main diff).
ROOT_MAIN_FILE = "main_only.txt"
MEMBER_MAIN_FILE = "member_main_only.txt"

#: An engine-shaped write set (the real shape of this ticket's own declaration): the
#: coarse rule runs everything, so only the file-level list can narrow a round.
WRITE_SET = ["server/engine/", "integration/"]
REDS = ["sc_red_a"]

_GIT_ENV = dict(os.environ)
_GIT_ENV.update({"GIT_AUTHOR_NAME": "integ", "GIT_AUTHOR_EMAIL": "integ@example.test",
                 "GIT_COMMITTER_NAME": "integ",
                 "GIT_COMMITTER_EMAIL": "integ@example.test"})

_SEQ = [0]


# --------------------------------------------------------------------------------------
# fixture helpers (a failing fixture step is an environment fault, never a content red)
# --------------------------------------------------------------------------------------

def _git(cwd, *args, what=""):
    """Run one real git command. `what` names the fixture context this step builds; a
    failure there is ENV_FAIL (`ENV_FAIL: <what> missing (...)`, exit 2)."""
    try:
        p = subprocess.run(["git", "-C", str(cwd)] + [str(a) for a in args],
                           capture_output=True, text=True, timeout=60, env=_GIT_ENV)
    except (OSError, subprocess.SubprocessError) as e:
        env_fail("%s missing (probed `git -C %s %s`: %s: %s)"
                 % (what or "fixture git step", cwd,
                    " ".join(str(a) for a in args), type(e).__name__, str(e)[:200]))
    if what and p.returncode != 0:
        env_fail("%s missing (probed `git -C %s %s` rc=%s: %s)"
                 % (what, cwd, " ".join(str(a) for a in args), p.returncode,
                    ((p.stderr or p.stdout or "").strip() or "no output")[-300:]))
    return p.returncode, (p.stdout or ""), (p.stderr or "")


def _write(path, text):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _commit_all(repo, message, what):
    _git(repo, "add", "-A", what=what + " (git add -A)")
    _git(repo, "commit", "-m", message, what=what + " (git commit)")


def _head(repo, what):
    _rc, out, _err = _git(repo, "rev-parse", "HEAD", what=what + " (git rev-parse HEAD)")
    return out.strip()


def _build_side(repo, *, line_file, main_file, what, ignore_lines=()):
    """Give one repo the two-sided history shape this ticket is about: a base commit, a
    line branch that lands one file main never had, and a `main` commit the line does
    not carry. `ignore_lines` is committed with the base commit, so every lane worktree
    inherits it (a lane's own coordination directory must never read as a change)."""
    pathlib.Path(repo).mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-b", BASE_BRANCH, what=what + " (git init -b main)")
    if ignore_lines:
        _write(repo / ".gitignore", "\n".join(ignore_lines) + "\n")
    _write(repo / "base.txt", "base\n")
    _commit_all(repo, "base", what + " base commit")
    _git(repo, "checkout", "-b", LINE_BRANCH, what=what + " line branch (git checkout -b)")
    _write(repo / line_file, "line\n")
    _commit_all(repo, "line: carry %s" % line_file, what + " line commit")
    _git(repo, "checkout", BASE_BRANCH, what=what + " back to main")
    _write(repo / main_file, "main\n")
    _commit_all(repo, "main: %s" % main_file, what + " main commit")


def _add_synced_lane(repo, branch, tree, what):
    """Cut the ticket's lane worktree from the LINE head, then sync main into it - the
    buffer-lane shape: the tree carries the line's content AND main's."""
    tree = pathlib.Path(tree)
    _git(repo, "worktree", "add", "-b", branch, str(tree), LINE_BRANCH,
         what="%s lane worktree on branch %r" % (what, branch))
    _git(tree, "merge", "--no-edit", BASE_BRANCH, what=what + " main sync into the lane")


def _lane_commit(tree, relpath, content="change\n"):
    """Commit one change on the tree's own lane branch (the ticket's own write)."""
    _write(pathlib.Path(tree) / relpath, content)
    _git(tree, "add", "-A", what="fixture lane change staged (%s)" % relpath)
    _git(tree, "commit", "-m", "touch %s" % relpath, what="fixture lane commit (%s)" % relpath)


def _write_manifest(lane, entries):
    d = pathlib.Path(lane) / ".sandbar"
    try:
        d.mkdir(parents=True, exist_ok=True)
        (d / "repo_worktrees.json").write_text(json.dumps(entries, indent=1),
                                               encoding="utf-8")
    except OSError as e:
        env_fail("lane manifest path missing (probed %s: %s)" % (d, e))


def make_buffer_lane(tmp, *, ignore_member=True):
    """A buffer-shaped multi-repo lane in the shape `prepare_workspace` writes: a project
    root repo plus one member repo, one worktree per scope, a manifest, the line's
    carried file and a synced main on both sides, plus the ticket's own commit.

    ignore_member=True mirrors the reporting project (the member mount is ignored in the
    root repo); False exposes the mount to the root tree's status, which is the shape the
    sibling filter exists for (leg H)."""
    _SEQ[0] += 1
    seq = _SEQ[0]
    root = tmp / ("proj%d" % seq)
    ignores = [".lane/", ".sandbar/"]
    if ignore_member:
        ignores.append("/%s/" % MEMBER)
    _build_side(root, line_file=ROOT_LINE_FILE, main_file=ROOT_MAIN_FILE,
                what="fixture project repo", ignore_lines=ignores)

    lane = root / ".lane" / ("lane%d" % seq)
    root_branch = "%s-root" % TICKET_BRANCH
    member_branch = "%s-%s" % (TICKET_BRANCH, MEMBER)
    _add_synced_lane(root, root_branch, lane, "fixture project repo")
    _lane_commit(lane, ROOT_OWN_FILE)

    member_repo = root / MEMBER
    _build_side(member_repo, line_file=MEMBER_LINE_FILE, main_file=MEMBER_MAIN_FILE,
                what="fixture member repo %r" % MEMBER)
    _add_synced_lane(member_repo, member_branch, lane / MEMBER,
                     "fixture member repo %r" % MEMBER)
    _lane_commit(lane / MEMBER, MEMBER_OWN_FILE)

    manifest = [
        {"repo": "", "name": "root", "branch": root_branch,
         "base_ref": _head(root, "fixture project base commit")},
        {"repo": MEMBER, "name": MEMBER, "branch": member_branch,
         "base_ref": _head(member_repo, "fixture member base commit")},
    ]
    _write_manifest(lane, manifest)
    return {"root": root, "lane": lane, "member_repo": member_repo,
            "root_branch": root_branch, "member_branch": member_branch}


def make_single_lane(tmp):
    """A single-repo buffer lane: no manifest, and the suffix-less name IS the lane
    branch (the shape leg I guards)."""
    _SEQ[0] += 1
    seq = _SEQ[0]
    root = tmp / ("single%d" % seq)
    _build_side(root, line_file=ROOT_LINE_FILE, main_file=ROOT_MAIN_FILE,
                what="fixture single-repo project",
                ignore_lines=[".lane/", ".sandbar/"])
    lane = root / ".lane" / ("lane%d" % seq)
    _add_synced_lane(root, TICKET_BRANCH, lane, "fixture single-repo project")
    _lane_commit(lane, ROOT_OWN_FILE)
    return {"root": root, "lane": lane}


# --------------------------------------------------------------------------------------
# the measured face: the real activity x the real decision writer
# --------------------------------------------------------------------------------------

def _field(raw, name, default=None):
    if isinstance(raw, dict):
        return raw.get(name, default)
    return getattr(raw, name, default)


def collect(lane, branch, other=None):
    """Call the real `changed_files` activity. Returns (files, error, raw).

    `files is None` means the activity raised, which is itself a contract break (it must
    return a receipt)."""
    import asyncio
    import shared
    import agent_activities as aa
    kwargs = {} if other is None else {"base_other_ref": other}
    try:
        raw = asyncio.run(aa.changed_files(shared.ChangedFilesArgs(
            ticket_id=TICKET_ID, worktree=str(lane), branch=branch, **kwargs)))
    except Exception as e:  # noqa: BLE001 - a raise is a finding, reported as such
        return None, "raised %s: %s" % (type(e).__name__, str(e)[:300]), None
    files = _field(raw, "files", None)
    return [str(f) for f in (files or [])], str(_field(raw, "error", "") or ""), raw


def plan(changed=None, diff_error=""):
    """The engine's one decision writer: no list = the old coarse-prefix caliber."""
    import shared
    kwargs = {}
    if changed is not None:
        kwargs["changed_files"] = changed
    if diff_error:
        kwargs["diff_error"] = diff_error
    return shared.targeted_rerun_plan(WRITE_SET, REDS, **kwargs)


def probe_engine():
    try:
        import shared            # noqa: F401
        import agent_activities  # noqa: F401
    except Exception as e:  # noqa: BLE001 - a missing engine is an environment red
        env_fail("engine modules unimportable (probed `import shared` and `import "
                 "agent_activities` from %s: %s: %s)"
                 % (ENGINE_SRC, type(e).__name__, str(e)[:200]))


def _brief(files, err, width=10):
    shown = files if files is None or len(files) <= width else list(files[:width]) + ["..."]
    return "files=%r err=%r" % (shown, err[:220])


def main():
    if shutil.which("git") is None:
        env_fail("git executable missing (this case drives worktree/diff/status/"
                 "merge-base through real git subprocesses)")
    probe_engine()
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="t26110303-"))
    legs = []

    def check(name, ok, detail=""):
        legs.append(bool(ok))
        print("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                             (" - %s" % detail) if detail else ""))

    try:
        # ---- A/B/C/D: one buffer lane, all four calibers -------------------------
        fx = make_buffer_lane(tmp)
        lane = fx["lane"]

        files_two, err_two, raw_two = collect(lane, TICKET_BRANCH, other=LINE_BRANCH)
        basis_two = str(_field(raw_two, "basis", "") or "")

        check("A1 the two-sided caliber reports the ticket's own file and no error",
              files_two is not None and err_two == ""
              and ROOT_OWN_FILE in files_two, _brief(files_two, err_two))
        check("A2 the line's carried file is NOT charged to the buffer ticket",
              files_two is not None and ROOT_LINE_FILE not in files_two
              and MEMBER_LINE_FILE not in files_two
              and ("%s/%s" % (MEMBER, MEMBER_LINE_FILE)) not in files_two,
              _brief(files_two, err_two))
        check("A3 a main-side file the ticket did not write is not charged either",
              files_two is not None and ROOT_MAIN_FILE not in files_two
              and MEMBER_MAIN_FILE not in files_two, _brief(files_two, err_two))
        check("A4 the receipt names the basis (the other side it was measured against)",
              basis_two == LINE_BRANCH, "basis=%r" % (basis_two,))

        check("B1 the member scope keeps its own write, project-root-relative",
              files_two is not None
              and ("%s/%s" % (MEMBER, MEMBER_OWN_FILE)) in files_two
              and MEMBER_OWN_FILE not in files_two, _brief(files_two, err_two))
        resolved = [str(x) for x in (_field(raw_two, "resolved", None) or [])]
        check("B2 the per-scope resolution face survives the two-sided caliber",
              len(resolved) == 2 and all(":" in x for x in resolved)
              and any(x.startswith("root:") for x in resolved)
              and any(x.startswith("%s:" % MEMBER) for x in resolved),
              "resolved=%r" % (resolved,))

        files_default, err_default, raw_default = collect(lane, TICKET_BRANCH)
        basis_default = str(_field(raw_default, "basis", "") or "")
        check("C1 control: with no other side named the historical caliber is intact - "
              "the line's files ARE in the list (the caliber is opt-in)",
              files_default is not None and err_default == ""
              and ROOT_LINE_FILE in files_default
              and ("%s/%s" % (MEMBER, MEMBER_LINE_FILE)) in files_default,
              _brief(files_default, err_default))
        check("C2 control: the receipt says the basis is main",
              basis_default == "main", "basis=%r" % (basis_default,))

        files_as_main, err_as_main, raw_as_main = collect(
            lane, TICKET_BRANCH, other=BASE_BRANCH)
        check("D1 naming main as the other side is byte-identical to naming nothing "
              "(the main side is never charged twice)",
              files_as_main is not None and err_as_main == ""
              and files_as_main == files_default,
              "as_main=%r default=%r" % (files_as_main, files_default))
        check("D2 the basis still says main when the other side is main",
              str(_field(raw_as_main, "basis", "") or "") == "main",
              "basis=%r" % (_field(raw_as_main, "basis", ""),))

        # ---- G: the status face is not intersected -------------------------------
        _write(lane / ROOT_DRIFT_FILE, "dirty\n")
        _write(lane / MEMBER / MEMBER_DRIFT_FILE, "dirty\n")
        files_g, err_g, _raw_g = collect(lane, TICKET_BRANCH, other=LINE_BRANCH)
        check("G1 an untracked own file still counts under the two-sided caliber "
              "(root scope and member scope)",
              files_g is not None and err_g == ""
              and ROOT_DRIFT_FILE in files_g
              and ("%s/%s" % (MEMBER, MEMBER_DRIFT_FILE)) in files_g,
              _brief(files_g, err_g))
        check("G2 the line's files stay out of the same list",
              files_g is not None and ROOT_LINE_FILE not in files_g
              and ("%s/%s" % (MEMBER, MEMBER_LINE_FILE)) not in files_g,
              _brief(files_g, err_g))

        # ---- E: an unreadable other side fails closed by name ---------------------
        fx_e = make_buffer_lane(tmp)
        files_e, err_e, _raw_e = collect(fx_e["lane"], TICKET_BRANCH,
                                         other="no-such-line-xyz")
        check("E1 an unresolvable other side answers files=[] and names the side",
              files_e == [] and "no-such-line-xyz" in err_e, _brief(files_e, err_e))
        check("E2 the named error keeps the merge-base marker",
              "merge-base" in err_e or "baseline" in err_e, "err=%r" % (err_e[:220],))
        check("E3 the decision face does NOT narrow on that error (fail-closed)",
              plan(changed=files_e, diff_error=err_e) == [],
              "plan=%r" % (plan(changed=files_e, diff_error=err_e),))

        # ---- F: one unreadable member scope fails the whole call ------------------
        fx_f = make_buffer_lane(tmp)
        _git(fx_f["member_repo"], "branch", "-D", LINE_BRANCH,
             what="removal of the member's line branch (leg F premise)")
        files_f, err_f, _raw_f = collect(fx_f["lane"], TICKET_BRANCH, other=LINE_BRANCH)
        check("F1 one unreadable scope fails the WHOLE call: no partial list",
              files_f == [], _brief(files_f, err_f))
        check("F2 the error carries that scope's tag and the side name",
              ("[%s]" % MEMBER) in err_f and LINE_BRANCH in err_f,
              "err=%r" % (err_f[:220],))

        # ---- H: the sibling mount is not resurrected by the two-sided caliber ----
        fx_h = make_buffer_lane(tmp, ignore_member=False)
        files_h, err_h, _raw_h = collect(fx_h["lane"], TICKET_BRANCH, other=LINE_BRANCH)
        mounts = [p for p in (files_h or []) if p.rstrip("/") == MEMBER]
        check("H1 the sibling mount is reported by neither face (no `member` entry)",
              files_h is not None and err_h == "" and mounts == [],
              _brief(files_h, err_h))
        check("H2 the member's own write keeps its prefix in the same list",
              files_h is not None
              and ("%s/%s" % (MEMBER, MEMBER_OWN_FILE)) in files_h,
              _brief(files_h, err_h))

        # ---- I: the single-repo lane keeps the two-sided caliber ----------------
        fx_i = make_single_lane(tmp)
        files_i, err_i, raw_i = collect(fx_i["lane"], TICKET_BRANCH, other=LINE_BRANCH)
        check("I1 a single-repo lane excludes its line-carried file and keeps its own",
              files_i is not None and err_i == ""
              and ROOT_OWN_FILE in files_i and ROOT_LINE_FILE not in files_i,
              _brief(files_i, err_i))
        check("I2 that list carries no repo prefix and the basis is named",
              files_i is not None
              and all(not p.startswith("%s/" % MEMBER) for p in files_i)
              and str(_field(raw_i, "basis", "") or "") == LINE_BRANCH,
              _brief(files_i, err_i))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    n_fail = legs.count(False)
    print("SUMMARY pass=%d fail=%d env_fail=0 na=0"
          % (len(legs) - n_fail, n_fail))
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
