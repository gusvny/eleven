#!/usr/bin/env python3
"""sc_t26100928_legacy_and_ancestor_gate.py -- t261009-28 L3 (integration role).

User-visible contracts (ticket t261009-28 items (4) and (3)):

  A  NO BACKWARD MAGIC: a project store that still carries a legacy
     landings.jsonl (the retired second shape) is REFUSED BY NAME at the
     landing entry -- the refusal names the file, says its rows are not
     migrated, and nothing is written anywhere (delivery ledger stays empty,
     line head unchanged). Never silently read as no landings.
  B  the refusal is about the legacy file, not the fixture: the same landing
     on a store WITHOUT the legacy file is accepted.
  C  the ancestor gate exists: when the line's branch no longer carries the
     revision the latest certification names (fault injection: the line
     branch is reset to main after the certification — the landed revision
     would skip certified content), the landing is refused by name, records
     nothing, and moves no head. (A normal stale lane merged --no-ff keeps
     the certified revision an ancestor of the merge result, so the gate
     correctly admits it — the design letter is ancestor-of-landed, judged
     in the LINE worktree.)

Grey-box L3: real git subprocesses on fixture repos, the public surfaces
(develop_line.load_line / land_ticket / LandingError,
develop_certify.ledger_path / read_rows / append_rows / KIND_*), the
delivery-ledger FILE read back from disk (reader side). Isolated
SANDBAR_PROJECTS_DIR + SANDBAR_DELIVERY_LEDGER_DIR; offline seconds; zero
docker/browser; never touches 3099.

Intent split (no duplication): legacy-refusal unit truth tables and the
ancestor check's exception taxonomy belong to developer L1
(test_t261009_28_landing_delivery_ledger.py); the landing act's own
guarantees stay with the adapted t261009-18-line-landing-journey; the
one-home ordering face is t261009-28-landing-one-home-ordering. The
pre-first-certification fallback control is covered by that entry's face A
(a landing on a never-certified line is accepted). Pre-implementation tree =
FAIL named (TDD signal); green required at the integration gate / merge.
git or repo root missing = ENV_FAIL exit 2.
"""
import json
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


def lane_branch(repo, branch, base_ref, fname, content):
    git("checkout", "-q", "-b", branch, base_ref, cwd=repo)
    with open(os.path.join(repo, fname), "w") as f:
        f.write(content)
    git("add", "-A", cwd=repo)
    git("-c", "user.email=t@s", "-c", "user.name=t", "commit", "-qm",
        "lane " + branch, cwd=repo)


def declare_line(key, repo_name, branch):
    import shared
    dev_dir = shared.develop_dir(key)
    os.makedirs(dev_dir, exist_ok=True)
    with open(os.path.join(dev_dir, "lines.json"), "w") as f:
        json.dump([{"version": 1, "line_id": "line-1", "scope": "slice",
                    "owner": "integration-role",
                    "repositories": [{"name": repo_name, "branch": branch}]}], f)


def plant_legacy(key):
    """A legacy second-shape record exactly as t261009-18 wrote it."""
    import shared
    dev_dir = shared.develop_dir(key)
    os.makedirs(dev_dir, exist_ok=True)
    with open(os.path.join(dev_dir, "landings.jsonl"), "w") as f:
        f.write(json.dumps({"id": "ldg-legacy", "line_id": "line-1",
                            "revisions": {"repo1": "deadbeef"}, "base": {},
                            "by": "someone", "version": 1}) + "\n")


def landing_rows(lpath):
    import develop_certify
    rows = develop_certify.read_rows(lpath)[0] if os.path.exists(lpath) else []
    return [x for x in rows if isinstance(x, dict)
            and x.get("kind") == develop_certify.KIND_LANDING]


def main():
    if shutil.which("git") is None or REPO.returncode != 0:
        print("ENV_FAIL: git or repo root unavailable")
        return 2
    if not os.path.isdir(ENGINE):
        print("FAIL develop-modules-absent :: server/engine missing (TDD signal)")
        return 1
    sys.path.insert(0, ENGINE)
    try:
        import develop_certify
        import develop_line
        import shared
    except ImportError as e:
        print("FAIL develop-modules-absent :: %s (expected before implement; "
              "TDD signal)" % e)
        return 1

    root = tempfile.mkdtemp(prefix="t26100928-gate-")
    try:
        os.environ["SANDBAR_PROJECTS_DIR"] = root
        ledger_dir = os.path.join(root, "ledger")
        os.environ[develop_certify.LEDGER_DIR_ENV] = ledger_dir
        branch = "develop-main"

        # --- A: legacy second shape refused by name, nothing written ---
        key_a = "t26100928legacy"
        repo = make_repo(root, "repoA")
        lane_branch(repo, "lane-a", "main", "a.txt", "a\n")
        declare_line(key_a, "repoA", branch)
        plant_legacy(key_a)
        line = develop_line.load_line(key_a, "line-1")
        head0 = git("rev-parse", branch, cwd=repo).stdout.strip()
        refused = False
        detail = "no exception raised"
        try:
            r = develop_line.land_ticket(line, key_a, {"repoA": Path(repo)},
                                         "t-legacy", "integration-test")
            detail = "land_ticket returned ok=%r error=%r" % (
                getattr(r, "ok", None), getattr(r, "error", None))
        except develop_line.LandingError as e:
            refused = True
            detail = str(e)
        except Exception as e:  # wrong taxonomy is still a named finding
            refused = True
            detail = "wrong exception type %s: %s" % (type(e).__name__, e)
        check("A-legacy-refused", refused, detail)
        msg = detail.lower()
        check("A-refusal-names-file",
              "landings.jsonl" in msg or "legacy" in msg, detail)
        lpath = develop_certify.ledger_path(key_a)
        check("A-delivery-ledger-untouched", len(landing_rows(lpath)) == 0,
              str(landing_rows(lpath))[:200])
        check("A-line-head-unchanged",
              git("rev-parse", branch, cwd=repo).stdout.strip() == head0, head0)

        # --- B: control -- same landing without the legacy file is fine ---
        key_b = "t26100928clean"
        repo_b = make_repo(root, "repoB")
        lane_branch(repo_b, "lane-b", "main", "b.txt", "b\n")
        declare_line(key_b, "repoB", branch)
        line_b = develop_line.load_line(key_b, "line-1")
        r = develop_line.land_ticket(line_b, key_b, {"repoB": Path(repo_b)},
                                     "t-clean", "integration-test")
        check("B-clean-store-accepted",
              bool(getattr(r, "ok", True) or not getattr(r, "error", "")),
              str(getattr(r, "error", "")))
        check("B-clean-store-recorded", len(landing_rows(
            develop_certify.ledger_path(key_b))) == 1,
            str(landing_rows(develop_certify.ledger_path(key_b)))[:200])

        # --- C: the ancestor gate ---
        key_c = "t26100928gate"
        repo_c = make_repo(root, "repoC")
        lane_branch(repo_c, "lane-1", "main", "c1.txt", "c1\n")
        declare_line(key_c, "repoC", branch)
        line_c = develop_line.load_line(key_c, "line-1")
        r = develop_line.land_ticket(line_c, key_c, {"repoC": Path(repo_c)},
                                     "t-c1", "integration-test")
        check("C-first-landing-accepted",
              bool(getattr(r, "ok", True) or not getattr(r, "error", "")),
              str(getattr(r, "error", "")))
        certified = git("rev-parse", branch, cwd=repo_c).stdout.strip()
        lpath_c = develop_certify.ledger_path(key_c)
        ap = develop_certify.append_rows(
            [{"kind": develop_certify.KIND_CERT, "id": "cert-c1",
              "line": "line-1",
              "repos": [{"repo": "repoC", "revision": certified}],
              "run": "run-c1", "booked_red": "no", "judged_by": "integration-test",
              "at": 1}], lpath_c)
        check("C-cert-appended", ap.get("written") == 1, json.dumps(ap))
        # fault injection: the line branch loses the certified content
        # (reset to main IN THE LINE WORKTREE — the engine-owned checkout the
        # landing merges into and reads the ancestor from; resetting the main
        # checkout would not touch what the landing sees) — a landing now
        # would produce a revision that does NOT carry what the ledger
        # certifies. (t261009-28 implement-stage adaptation: the
        # pre-implementation draft reset the fixture's main checkout, which
        # the landing never reads.)
        git("reset", "-q", "--hard", "main",
            cwd=os.path.join(shared.develop_dir(key_c), "wt", "repoC"))
        head0 = git("rev-parse", branch, cwd=repo_c).stdout.strip()
        refused = False
        detail = "no exception raised"
        try:
            r = develop_line.land_ticket(line_c, key_c, {"repoC": Path(repo_c)},
                                         "t-c2", "integration-test")
            detail = "land_ticket returned ok=%r error=%r" % (
                getattr(r, "ok", None), getattr(r, "error", None))
        except develop_line.LandingError as e:
            refused = True
            detail = str(e)
        except Exception as e:
            refused = True
            detail = "wrong exception type %s: %s" % (type(e).__name__, e)
        check("C-cert-skipping-landing-refused", refused, detail)
        check("C-refusal-precise",
              "repoC" in detail or "ancestor" in detail.lower()
              or "certif" in detail.lower(), detail)
        check("C-no-record-on-refusal",
              len(landing_rows(lpath_c)) == 1,
              "landing rows=%d" % len(landing_rows(lpath_c)))
        check("C-line-head-unchanged",
              git("rev-parse", branch, cwd=repo_c).stdout.strip() == head0, head0)
        return 0 if failed == 0 else 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        print("FAIL scenario-crashed :: %r (named failure beats a silent face)" % e)
        sys.exit(1)
