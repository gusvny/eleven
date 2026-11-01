#!/usr/bin/env python3
"""Per-scope changed-file baseline on a multi-repo lane (ticket t261031-17).

Intent (grey-box L2, `ro` pool, real git fixture, seconds, zero docker, zero browser,
zero console): on a lane that carries a repo-worktree manifest, the engine's changed-file
collector must resolve ONE baseline PER REPO and return a project-root-relative list, so
the blast-radius decision stops forcing a full run.

The reported defect (project-vision, cross-project report): the collector used the
suffix-less lane branch (`lane/<id>`). A multi-repo lane names one branch per repo
(`lane/<id>-<repo>`, plus `lane/<id>-root`), so the suffix-less name exists nowhere, every
scope failed, the list was empty and every gate round ran the whole suite (40 to 60
minutes per round).

Legs (all on real git; every fixture builds its own branch context):

  A  the reported shape (root repo plus IGNORED member mounts): a member-only committed
     change reaches the list with its project-root prefix, and the decision narrows to
     the previous red names while the coarse-prefix rule would still run everything.
  B  safety track: a shared-base face in the root repo (`verify.yaml`) still plans a full
     run.
  C  the sibling mounts are reported by neither face (status `member/`, diff gitlink
     `member`), an ordinary untracked directory in the root tree is still reported, and
     the lane's own coordination artifact does not force a full run.
  D  fail-closed: one member repo has no `main` -> empty list, the error names that scope
     and keeps the merge-base marker, the decision is full.
  E  single-repo lane: the same list a manual git diff gives (committed plus dirty, the
     dirty half read from the LANE TREE, not the owning repo root).
  F  an uncommitted member change is counted, with its prefix.
  G  agent-written external input: a corrupt manifest and an absolute `repo` entry each
     answer an empty list, a named error and a full run, and never raise.

ENV_FAIL (exit 2) covers only context the FIXTURE builds: git absent, engine modules
unimportable, a fixture step failing, or a fixture premise that does not hold (a per-repo
branch or its merge-base unresolvable, or the suffix-less name unexpectedly resolving).
An ENGINE answer that reports the baseline unavailable is NOT an environment red here:
the fixture supplies the per-repo context, so that answer is the product defect under
test. The single-repo sibling case's KI-413 guard does not apply: it exists because its
fixture depended on the ambient checkout's branch, and borrowing it here would hide this
ticket's defect as "environment".

Three-state: PASS / FAIL / ENV_FAIL, no SKIP. A pre-implementation red is the named TDD
signal; green is required at the integration gate and merge.
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

TICKET_ID = "t261031-17"
BASE_BRANCH = "main"
#: Two one-level members: the repo set is one level by design (`shared.repos_under`
#: scans the project root plus its direct children only), so a deeper member is not a
#: shape the engine can derive. Two members still exercise the union, the prefixing and
#: the sibling filter.
MEMBERS = ("member-trainer", "fpv-core")
#: An engine-shaped ticket write set: one shared-base prefix (the coarse rule's trigger)
#: plus the member face.
WRITE_SET = ["server/engine/", "integration/", "member-trainer/src/", "fpv-core/src/"]
REDS = ["sc_red_a", "sc_red_b"]

_SEQ = [0]


# --------------------------------------------------------------------------------------
# fixture helpers (a failing fixture step is an environment fault, never a content red)
# --------------------------------------------------------------------------------------

#: Commit identity for the fixture repositories. Passed as environment variables so a
#: fixture needs no `git config` call per repo (the identity is the same for all).
_GIT_ENV = dict(os.environ)
_GIT_ENV.update({"GIT_AUTHOR_NAME": "integ", "GIT_AUTHOR_EMAIL": "integ@example.test",
                 "GIT_COMMITTER_NAME": "integ",
                 "GIT_COMMITTER_EMAIL": "integ@example.test"})


def _git(cwd, *args, what=""):
    """Run one real git command. `what` names the fixture context this step builds; a
    failure there is ENV_FAIL (`ENV_FAIL: <what> missing (probed ...)`, exit 2)."""
    try:
        p = subprocess.run(["git", "-C", str(cwd)] + [str(a) for a in args],
                           capture_output=True, text=True, timeout=60, env=_GIT_ENV)
    except (OSError, subprocess.SubprocessError) as e:
        env_fail("%s missing (probed `git -C %s %s`: %s: %s)"
                 % (what or "fixture git step", cwd, " ".join(str(a) for a in args),
                    type(e).__name__, str(e)[:200]))
    if what and p.returncode != 0:
        env_fail("%s missing (probed `git -C %s %s` rc=%s: %s)"
                 % (what, cwd, " ".join(str(a) for a in args), p.returncode,
                    ((p.stderr or p.stdout or "").strip() or "no output")[-300:]))
    return p.returncode, (p.stdout or ""), (p.stderr or "")


def _init_repo(path, what):
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-b", BASE_BRANCH, what=what + " (git init -b main)")


def _commit_all(repo, message, what):
    _git(repo, "add", "-A", what=what + " (git add -A)")
    _git(repo, "commit", "-m", message, what=what + " (git commit)")


def _head(repo, what):
    _rc, out, _err = _git(repo, "rev-parse", "HEAD", what=what + " (git rev-parse HEAD)")
    return out.strip()


def _write_manifest(lane, entries):
    d = pathlib.Path(lane) / ".sandbar"
    try:
        d.mkdir(parents=True, exist_ok=True)
        (d / "repo_worktrees.json").write_text(json.dumps(entries, indent=1), encoding="utf-8")
    except OSError as e:
        env_fail("lane manifest path missing (probed %s: %s)" % (d, e))


def _lane_commit(tree, relpath, content="change\n"):
    """Commit one change on the tree's own lane branch."""
    f = pathlib.Path(tree) / relpath
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")
    _git(tree, "add", "-A", what="fixture lane change staged (%s)" % relpath)
    _git(tree, "commit", "-m", "touch %s" % relpath, what="fixture lane commit (%s)" % relpath)


def _assert_context(fx):
    """The fixture's premise: every per-repo branch and its merge-base resolve, and the
    suffix-less lane branch resolves NOWHERE (the reported lane shape)."""
    for rel, branch in fx["branches"].items():
        repo = fx["root"] / rel if rel else fx["root"]
        rc, out, err = _git(repo, "rev-parse", "--verify", "--quiet", "%s^{commit}" % branch)
        if rc != 0 or not out.strip():
            env_fail("per-repo lane branch missing (probed `git -C %s rev-parse --verify "
                     "--quiet %r^{commit}` rc=%s: %s)"
                     % (repo, branch, rc, (err or out).strip()[-200:]))
        rc, out, err = _git(repo, "merge-base", BASE_BRANCH, branch)
        if rc != 0 or not out.strip():
            env_fail("merge-base baseline missing (probed `git -C %s merge-base %s %r` "
                     "rc=%s: %s)" % (repo, BASE_BRANCH, branch, rc,
                                     (err or out).strip()[-200:]))
    for rel in [""] + list(fx["members"]):
        repo = fx["root"] / rel if rel else fx["root"]
        rc, out, _err = _git(repo, "rev-parse", "--verify", "--quiet",
                            "%s^{commit}" % fx["ticket_branch"])
        if rc == 0 and out.strip():
            env_fail("fixture premise broken: the suffix-less branch %r unexpectedly "
                     "resolves in %s (the reported lane shape names one branch per repo)"
                     % (fx["ticket_branch"], repo))


def make_multi_lane(tmp, *, ignore_members=True, members=MEMBERS):
    """A multi-repo lane in the shape `prepare_workspace` writes: project root repo,
    one-level member repos, one worktree per scope, and the manifest.

    ignore_members=True mirrors the reporting project (members ignored in the root
    repo); False exposes the mount to the root tree's status, which is the defence
    shape the sibling filter exists for."""
    _SEQ[0] += 1
    seq = _SEQ[0]
    root = tmp / ("proj%d" % seq)
    _init_repo(root, "fixture project repo")
    ignores = [".lane/"]
    if ignore_members:
        ignores += ["/%s/" % m for m in members]
    (root / ".gitignore").write_text("\n".join(ignores) + "\n", encoding="utf-8")
    (root / "verify.yaml").write_text("code:\n  cmd: \"true\"\n", encoding="utf-8")
    (root / "base.txt").write_text("base\n", encoding="utf-8")
    _commit_all(root, "base", "fixture project base commit")
    lane_name = "lane%d" % seq
    ticket_branch = "lane/" + lane_name
    lane = root / ".lane" / lane_name
    branches = {"": "%s-root" % ticket_branch}
    _git(root, "worktree", "add", "-b", branches[""], str(lane),
         what="lane root worktree on branch %r" % branches[""])
    for m in members:
        mroot = root / m
        _init_repo(mroot, "fixture member repo %r" % m)
        (mroot / "README.md").write_text("%s base\n" % m, encoding="utf-8")
        _commit_all(mroot, "base", "fixture member base commit %r" % m)
        branches[m] = "%s-%s" % (ticket_branch, m)
        _git(mroot, "worktree", "add", "-b", branches[m], str(lane / m),
             what="lane member worktree on branch %r" % branches[m])
    manifest = [{"repo": "", "name": "root", "branch": branches[""],
                 "base_ref": _head(root, "fixture project base commit")}]
    manifest += [{"repo": m, "name": m, "branch": branches[m],
                  "base_ref": _head(root / m, "fixture member base commit %r" % m)}
                 for m in members]
    _write_manifest(lane, manifest)
    fx = {"root": root, "lane": lane, "lane_name": lane_name,
          "ticket_branch": ticket_branch, "members": tuple(members),
          "branches": branches, "manifest": manifest}
    _assert_context(fx)
    return fx


def make_single_lane(tmp):
    """A single-repo lane: no manifest, and the suffix-less name IS the lane branch."""
    _SEQ[0] += 1
    seq = _SEQ[0]
    root = tmp / ("single%d" % seq)
    _init_repo(root, "fixture single-repo project")
    (root / ".gitignore").write_text(".lane/\n", encoding="utf-8")
    (root / "base.txt").write_text("base\n", encoding="utf-8")
    _commit_all(root, "base", "fixture base commit")
    branch = "lane/lane%d" % seq
    lane = root / ".lane" / ("lane%d" % seq)
    _git(root, "worktree", "add", "-b", branch, str(lane),
         what="single-repo lane worktree on branch %r" % branch)
    return {"root": root, "lane": lane, "branch": branch}


# --------------------------------------------------------------------------------------
# the measured face: the real activity x the real decision writer
# --------------------------------------------------------------------------------------

def collect(lane, branch):
    """Call the real `changed_files` activity. Returns (files, error); files is None when
    the activity raised, which is itself a contract break (it must return a receipt)."""
    import asyncio
    import shared
    import agent_activities as aa
    try:
        raw = asyncio.run(aa.changed_files(shared.ChangedFilesArgs(
            ticket_id=TICKET_ID, worktree=str(lane), branch=branch)))
    except Exception as e:  # noqa: BLE001 — a raise is a finding, reported as such
        return None, "raised %s: %s" % (type(e).__name__, str(e)[:300])
    files = raw.get("files") if isinstance(raw, dict) else getattr(raw, "files", None)
    error = raw.get("error") if isinstance(raw, dict) else getattr(raw, "error", "")
    return [str(f) for f in (files or [])], str(error or "")


def plan(changed=None):
    """The engine's decision writer, old signature (no list) versus the file-level one."""
    import shared
    kwargs = {} if changed is None else {"changed_files": changed}
    return shared.targeted_rerun_plan(WRITE_SET, REDS, **kwargs)


def probe_engine():
    try:
        import shared            # noqa: F401
        import agent_activities  # noqa: F401
    except Exception as e:  # noqa: BLE001
        env_fail("engine modules unimportable (probed `import shared` and `import "
                 "agent_activities` from %s: %s: %s)"
                 % (ENGINE_SRC, type(e).__name__, str(e)[:200]))


def _brief(files, err, width=8):
    shown = files if files is None or len(files) <= width else list(files[:width]) + ["..."]
    return "files=%r err=%r" % (shown, err[:200])


def main():
    if shutil.which("git") is None:
        env_fail("git executable missing (this case drives worktree/diff/status/"
                 "merge-base through real git subprocesses)")
    probe_engine()
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="t26103117-"))
    legs = []

    def check(name, ok, detail=""):
        legs.append(bool(ok))
        print("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                             ("：%s" % detail) if detail else ""))

    try:
        # ---- A: the reported shape — root repo, members ignored (project-vision) ----
        fx = make_multi_lane(tmp, ignore_members=True)
        _lane_commit(fx["lane"] / "member-trainer", "src/a.py", "a\n")
        files, err = collect(fx["lane"], fx["ticket_branch"])
        check("A1 a member-only committed change is listed, project-root-relative, "
              "with no error (the ticket's premise)",
              files is not None and err == "" and "member-trainer/src/a.py" in files,
              _brief(files, err))
        check("A2 the member path carries its repo prefix (no bare repo-relative entry)",
              files is not None and "member-trainer/src/a.py" in files
              and "src/a.py" not in files, _brief(files, err))
        check("A3 the coarse-prefix rule would run everything and the file-level list "
              "narrows to the previous red names (the economic claim)",
              plan() == [] and plan(changed=files or []) == REDS,
              "old=%r new=%r %s" % (plan(), plan(changed=files or []), _brief(files, err)))

        # ---- F (same fixture): an uncommitted member change is counted, with its prefix ----
        (fx["lane"] / "member-trainer" / "src" / "dirty.py").write_text("d\n", encoding="utf-8")
        files_f, err_f = collect(fx["lane"], fx["ticket_branch"])
        check("F1 an uncommitted member change is counted, project-root-relative",
              files_f is not None and err_f == ""
              and "member-trainer/src/dirty.py" in files_f
              and "src/dirty.py" not in files_f, _brief(files_f, err_f))

        # ---- B: safety track — a shared-base face still runs everything ----
        fxb = make_multi_lane(tmp, ignore_members=True)
        _lane_commit(fxb["lane"], "verify.yaml", "code:\n  cmd: \"true\"\n  extra: 1\n")
        files, err = collect(fxb["lane"], fxb["ticket_branch"])
        check("B1 a root-repo shared-base change is listed with no error",
              files is not None and err == "" and "verify.yaml" in files,
              _brief(files, err))
        check("B2 the shared-base face still plans a full run",
              plan(changed=files or []) == [], _brief(files, err))

        # ---- C: the sibling mounts are not reported, on either face ----
        fxc = make_multi_lane(tmp, ignore_members=False)
        (fxc["lane"] / "notes" / "new").mkdir(parents=True)
        (fxc["lane"] / "notes" / "new" / "keep.md").write_text("k\n", encoding="utf-8")
        files, err = collect(fxc["lane"], fxc["ticket_branch"])
        mounts = [p for p in (files or [])
                  if p.rstrip("/") in fxc["members"]]
        check("C1 the status face does not report a sibling mount (`member/`)",
              files is not None and err == "" and not mounts,
              "mount_entries=%r %s" % (mounts, _brief(files, err)))
        check("C2 an ordinary untracked directory in the root tree is still reported",
              files is not None and "notes/new/keep.md" in files, _brief(files, err))
        check("C3 the lane's own coordination artifact (the manifest) does not force a "
              "full run",
              plan(changed=files or []) == REDS, _brief(files, err))

        # ---- C4: the other measured shape — a lane-root add records a gitlink ----
        fxd = make_multi_lane(tmp, ignore_members=False)
        _commit_all(fxd["lane"], "lane root add", "fixture lane-root add (measured gitlink shape)")
        files, err = collect(fxd["lane"], fxd["ticket_branch"])
        diff_mounts = [p for p in (files or [])
                       if p.rstrip("/") in fxd["members"]]
        check("C4 the diff face does not report the sibling mount gitlink (`member`)",
              files is not None and err == "" and not diff_mounts,
              "mount_entries=%r %s" % (diff_mounts, _brief(files, err)))

        # ---- D: fail-closed — one member loses its baseline branch ----
        fxe = make_multi_lane(tmp, ignore_members=True)
        _lane_commit(fxe["lane"] / "member-trainer", "src/a.py", "a\n")
        _git(fxe["root"] / "fpv-core", "branch", "-m", BASE_BRANCH, "main-renamed-away",
             what="removal of one member's baseline branch (D sub-case)")
        files, err = collect(fxe["lane"], fxe["ticket_branch"])
        check("D1 one scope's baseline failure answers an empty list and names the scope",
              files is not None and files == [] and err != "" and "fpv-core" in err,
              _brief(files, err))
        check("D2 the error keeps the merge-base marker the caller reads",
              "merge-base" in err, _brief(files, err))
        check("D3 the decision is a full run (a partial list must never narrow the gate)",
              plan(changed=files or []) == [], _brief(files, err))

        # ---- E: single-repo lane unchanged (regression witness) ----
        fxs = make_single_lane(tmp)
        _lane_commit(fxs["lane"], "app/feature.py", "f\n")
        (fxs["lane"] / "app" / "dirty.py").write_text("d\n", encoding="utf-8")
        files, err = collect(fxs["lane"], fxs["branch"])
        expected = {"app/feature.py", "app/dirty.py"}
        check("E1 single-repo lane: the same list a manual diff gives, committed plus "
              "the dirty file read from the LANE TREE",
              files is not None and err == "" and set(files) == expected,
              "files=%r expected=%r err=%r" % (files, sorted(expected), err[:200]))
        check("E2 single-repo lane still narrows to the previous red names",
              plan(changed=files or []) == REDS, _brief(files, err))

        # ---- G: agent-written external input — a corrupt manifest ----
        fxg = make_multi_lane(tmp, ignore_members=True)
        (fxg["lane"] / ".sandbar" / "repo_worktrees.json").write_text("{not json",
                                                                     encoding="utf-8")
        files, err = collect(fxg["lane"], fxg["ticket_branch"])
        check("G1 a corrupt manifest answers an empty list and a named error, never a raise",
              files is not None and files == [] and err != ""
              and ("manifest" in err.lower() or "repo_worktrees" in err),
              _brief(files, err))
        check("G2 the corrupt-manifest receipt plans a full run",
              plan(changed=files or []) == [], _brief(files, err))

        # ---- G3 (same fixture): a manifest entry that leaves the project root ----
        escaping = tmp / "outside-repo"
        bad = [dict(e) for e in fxg["manifest"]]
        bad.append({"repo": str(escaping), "name": "escape", "branch": "lane/escape",
                    "base_ref": ""})
        _write_manifest(fxg["lane"], bad)
        files, err = collect(fxg["lane"], fxg["ticket_branch"])
        check("G3 an absolute repo entry is refused by name (empty list, error, full run)",
              files is not None and files == [] and err != ""
              and (str(escaping) in err or "absolute" in err.lower()),
              _brief(files, err))
        check("G4 the escaping-entry receipt plans a full run",
              plan(changed=files or []) == [], _brief(files, err))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    n_fail = legs.count(False)
    print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (len(legs) - n_fail, n_fail))
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
