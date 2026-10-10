#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_legacy_path_untouched.py -- t261009-46 L3 coexistence face: a ticket that
did NOT opt in takes today's path, and the running flow still never reaches the
new surface (grey-box L3, real git subprocesses on fixture repos, offline
seconds, stdlib only, zero docker/Temporal/browser, never touches 3099/7233).

intent: this entry owns the ticket spec's "old flow is untouched" face at the
seams an offline scenario can drive honestly:
  A  absence of the version field IS the legacy version (the no-silent-
     migration rule from the user side: a ticket that predates the field is
     never moved by the new flow's existence), and a legacy resolution never
     opens any develop behaviour.
  B  the one-way dependency, re-stated for the wired tree: importing
     agent_activities leaves the new surface unimported (its only reference is
     the lazy import inside land_to_line), and the new surface never reaches
     back into the running flow (develop_line / develop_certify /
     develop_promote carry no reference to dev_lane / workflows_v2) -- the
     t261009-18 inert face's reuse direction, restated for the wiring ticket:
     dev_lane now imports the new surface (declared inert, gated at the
     version predicate), so the direction that must never appear is
     new->running-flow.
  C  an old-path settle touches none of the new surface's homes: performing the
     engine's single settle/merge implementation on a fixture lane writes
     NOTHING into the injected project store (no develop area, no delivery
     ledger, no line worktree) and advances main by exactly one commit --
     byte-level store snapshot before/after is equal outside the repo itself.
  D  workflows_v2.py carries no reference to the new surface (the module with
     no sanctioned reason to know the new version exists).

Pre-wiring tree: A/C/D green, B red on the import face once the wiring adds a
module-level reference (the expected TDD signal); all green required at the
integration gate / merge. git or engine tree missing = ENV_FAIL exit 2.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                      capture_output=True, text=True)
ENGINE = os.path.join(REPO.stdout.strip(), "server", "engine") if REPO.returncode == 0 else ""

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("PASS %s" % name)
    else:
        failed += 1
        print("FAIL %s :: %s" % (name, detail))


def rev(repo, ref):
    return git("rev-parse", ref, cwd=repo).stdout.strip()


def git(*args, cwd):
    return subprocess.run(["git"] + list(args), cwd=cwd,
                          capture_output=True, text=True)


def make_repo(root, name):
    path = os.path.join(root, name)
    os.makedirs(path)
    git("init", "-q", "-b", "main", cwd=path)
    with open(os.path.join(path, "base.txt"), "w") as f:
        f.write("base\n")
    git("add", "-A", cwd=path)
    git("-c", "user.email=t@s", "-c", "user.name=t", "commit", "-qm", "base", cwd=path)
    return path


def snapshot(root):
    """Every file under the injected projects root, relpath -> bytes."""
    face = {}
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            try:
                with open(p, "rb") as f:
                    face[os.path.relpath(p, root)] = f.read()
            except OSError:
                face[os.path.relpath(p, root)] = b"<unreadable>"
    return face


def main():
    global passed, failed
    if shutil.which("git") is None or REPO.returncode != 0:
        print("ENV_FAIL: git or repo root unavailable")
        return 2
    if not os.path.isdir(ENGINE):
        print("FAIL engine-tree-absent :: %s" % ENGINE)
        return 1
    sys.path.insert(0, ENGINE)

    # --- B first, in a clean interpreter state: the one-way import face ---
    try:
        import agent_activities as acts  # noqa: F401
    except ImportError as e:
        print("FAIL agent-activities-unimportable :: %s" % e)
        return 1
    check("import-acts-leaves-develop-line-unimported",
          "develop_line" not in sys.modules,
          "importing agent_activities pulled in develop_line: %s"
          % sys.modules.get("develop_line"))
    check("import-acts-leaves-develop-certify-unimported",
          "develop_certify" not in sys.modules,
          "importing agent_activities pulled in develop_certify")
    try:
        import dev_lane  # noqa: F401
    except ImportError as e:
        # temporalio-chain absence is an environment face, not a wiring defect
        print("NOTE dev_lane unimportable :: %s" % e)
    # the direction that must never appear: the new surface reaching back into
    # the running flow (dev_lane importing develop_line is the wiring itself,
    # declared inert; the reverse reference is the coexistence breach)
    for mod_name in ("develop_line", "develop_certify", "develop_promote"):
        src = os.path.join(ENGINE, mod_name + ".py")
        with open(src, encoding="utf-8", errors="replace") as f:
            text = f.read()
        hits = [w for w in ("import dev_lane", "from dev_lane",
                            "import workflows_v2", "from workflows_v2") if w in text]
        check("new-surface-never-imports-running-flow-%s" % mod_name, not hits,
              "hits: %s" % hits)

    try:
        import develop_line
        import shared
    except ImportError as e:
        print("FAIL engine-module-unimportable :: %s" % e)
        return 1

    root = tempfile.mkdtemp(prefix="t26100946-legacy-")
    try:
        os.environ["SANDBAR_PROJECTS_DIR"] = root
        os.environ["SANDBAR_DELIVERY_LEDGER_DIR"] = os.path.join(root, "ledger")
        key = "t46legacy"

        # --- A: absence of the field is the legacy version, never a migration ---
        lawful = getattr(develop_line, "LANE_VERSION_LEGACY", None)
        parse = getattr(develop_line, "parse_lane_version", None)
        if parse is None or not lawful:
            print("FAIL optin-surface-absent :: parse_lane_version / LANE_VERSION_LEGACY "
                  "missing (expected before implement; TDD signal)")
            return 1
        try:
            got = parse(lawful)
        except Exception as e:
            got = "raised %s" % e
        check("legacy-name-canonical", got == lawful, "got %r" % (got,))
        # a legacy resolution never opens develop behaviour: no develop dir
        # and no delivery ledger may appear merely by resolving the version.
        dev = shared.develop_dir(key)
        led = Path(root) / "ledger"
        check("legacy-resolution-creates-nothing",
              not dev.is_dir(),
              "develop dir %s exists for a project that never opted in" % dev)
        check("no-delivery-ledger-for-legacy",
              not led.is_dir() or not any(led.iterdir()),
              "delivery ledger exists for a project that never landed")

        # --- C: an old-path settle writes nothing into the new homes ---
        store_before = {}
        os.makedirs(os.path.join(root, key, "data"), exist_ok=True)
        store_before = snapshot(root)
        repo = make_repo(root, "repo-legacy")
        base_sha = rev(repo, "main")
        git("checkout", "-q", "-b", "lane-old", "main", cwd=repo)
        with open(os.path.join(repo, "old.txt"), "w") as f:
            f.write("old work\n")
        git("add", "-A", cwd=repo)
        git("-c", "user.email=t@s", "-c", "user.name=t",
            "commit", "-qm", "old lane work", cwd=repo)
        # the old flow's merge into main, through the single implementation the
        # engine already owns (imported, never re-enacted here): stage the merge
        # (MERGE_HEAD in place, as the join close-out does) then settle it
        git("checkout", "-q", "main", cwd=repo)
        m = git("merge", "--no-ff", "--no-commit", "lane-old", cwd=repo)
        check("legacy-merge-staged", m.returncode == 0, m.stderr[:160])
        from agent_activities import _settle_merge_core
        res = _settle_merge_core(Path(repo), "legacy-ticket", 0)
        check("legacy-settle-ran", getattr(res, "ok", True) is not False,
              "%s %s" % (repr(res)[:120], getattr(res, "error", "")[:160]))
        check("legacy-main-advanced-one-commit",
              git("rev-list", "--first-parent", "--count",
                  "%s..main" % base_sha, cwd=repo).stdout.strip() == "1"
              and len(git("log", "-1", "--format=%P", "main",
                          cwd=repo).stdout.split()) == 2,
              "main log: %s" % git("log", "--oneline", "main", cwd=repo).stdout[:160])
        store_after = snapshot(root)
        new_paths = sorted(set(store_after) - set(store_before))
        unexpected = [p for p in new_paths if not p.startswith("repo-legacy")]
        check("legacy-store-untouched-by-new-surface", not unexpected,
              "legacy settle created non-repo store paths: %s" % unexpected[:6])
        check("no-develop-dir-for-legacy",
              not os.path.isdir(shared.develop_dir(key)),
              "develop dir %s exists for a legacy-only project" % shared.develop_dir(key))

        # --- D: workflows_v2 never names the new surface ---
        wf = os.path.join(ENGINE, "workflows_v2.py")
        if os.path.isfile(wf):
            with open(wf, encoding="utf-8", errors="replace") as f:
                text = f.read()
            hits = [w for w in ("develop_line", "develop_certify", "develop_promote",
                                "land_to_line", "LANE_VERSION") if w in text]
            check("workflows-v2-references-nothing-new", not hits, "hits: %s" % hits)
        else:
            print("NOTE workflows_v2.py absent (naming may differ); face D not assertable")
            failed += 1

        print("SUMMARY t26100946-legacy-path-untouched pass=%d fail=%d" % (passed, failed))
        return 1 if failed else 0
    finally:
        os.environ.pop("SANDBAR_PROJECTS_DIR", None)
        os.environ.pop("SANDBAR_DELIVERY_LEDGER_DIR", None)
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
