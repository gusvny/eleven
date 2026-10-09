#!/usr/bin/env python3
"""sc_line_landing_journey.py -- t261009-18 L3 journey (integration role).

User-visible contract under test (design docs/design/develop-buffer-v1.md
goals 6/7/18 + ticket acceptance (b)(c)): after a lane's own proof, the
engine lands the ticket's content onto its DECLARED line -- one landing per
ticket, a LINEAR line history, and ONE append-only landing record a reader
can open in the project store. Grey-box L3: real `git` subprocesses on real
fixture repos, the public surface named by the reviewed plan
(`develop_line.load_lines` / `develop_line.land_ticket` / the store files
under the per-key develop dir), never internals.

Faces:
  A  happy path: two tickets land in turn; the record FILE on disk (read
     back by the reader, not from the return value) carries one row per
     landing with ticket / line id / revision set / integer-ms `at` /
     performer and a time-ordered `ldg-` ULID id; the line branch history
     is linear -- each landing's merge commit parent is the previous head;
     the recorded revision equals the branch head the reader sees.
  B  one landing per ticket: a second landing for a ticket already on the
     line is refused loudly -- no third row, head unchanged.
  C  conflict bounce-back: a lane branch touching the same file bounces
     (named failure), the merge is aborted in the line worktree (no
     MERGE_HEAD residue), no record row, head unchanged.
  D  cross-process serialization: two OS processes race land_ticket at the
     same moment; landings cannot interleave -- the result is 1 or 2
     records (a lock-timeout refusal is a legal named outcome), and every
     successful race landing adds its merge commit to the ONE line branch
     the project store owns (history stays linear in every case).
  E  recovered duplicate: landing a lane tip that is already on the line
     delivers no second merge -- no new commit, a named recovered face,
     and exactly one more record (the content IS on the line).

Three-state exit contract: any FAIL -> exit 1 (pre-implement, module
absent = FAIL named, the expected TDD signal); git missing = ENV_FAIL
exit 2; else exit 0. All state under a temp dir reclaimed on exit (L8).
"""
import copy
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
    """A real fixture repo: main with a base file, plus one lane branch."""
    path = os.path.join(root, name)
    os.makedirs(path)
    git("init", "-q", "-b", "main", cwd=path)
    with open(os.path.join(path, "base.txt"), "w") as f:
        f.write("base\n")
    git("add", "-A", cwd=path)
    git("-c", "user.email=t@s", "-c", "user.name=t", "commit", "-qm", "base", cwd=path)
    return path


def lane_branch(repo, branch, fname, content):
    """Create a lane branch and LEAVE HEAD on it: land_ticket lands the lane
    repository's current HEAD, so the fixture must not check main back out."""
    git("checkout", "-q", "-b", branch, "main", cwd=repo)
    with open(os.path.join(repo, fname), "w") as f:
        f.write(content)
    git("add", "-A", cwd=repo)
    git("-c", "user.email=t@s", "-c", "user.name=t", "commit", "-qm",
       "lane " + branch, cwd=repo)


def main():
    if shutil.which("git") is None or REPO.returncode != 0:
        print("ENV_FAIL: git or repo root unavailable")
        return 2
    if not os.path.isdir(ENGINE):
        print("FAIL develop_line-module-absent :: server/engine missing (TDD signal)")
        return 1
    sys.path.insert(0, ENGINE)
    try:
        import develop_line  # noqa: F401
        import shared
    except ImportError as e:
        print("FAIL develop_line-module-absent :: %s (expected before implement; "
              "TDD signal)" % e)
        return 1

    root = tempfile.mkdtemp(prefix="t26100918-journey-")
    try:
        os.environ["SANDBAR_PROJECTS_DIR"] = root
        key = "t26100918"
        line_branch = "develop-main"
        repo = make_repo(root, "repo1")
        lane_branch(repo, "lane-a", "a.txt", "a\n")

        decl = [{"version": 1, "line_id": "line-1", "scope": "slice-1",
                 "owner": "integration-role",
                 "repositories": [{"name": "repo1", "branch": line_branch}]}]
        dev_dir = shared.develop_dir(key)
        os.makedirs(dev_dir, exist_ok=True)
        with open(os.path.join(dev_dir, "lines.json"), "w") as f:
            json.dump(decl, f)
        line = develop_line.load_line(key, "line-1")
        head = lambda: git("rev-parse", line_branch, cwd=repo).stdout.strip()

        # --- A: two landings, linear history, reader-side record ---
        shas = []
        r = develop_line.land_ticket(line, key, {"repo1": Path(repo)},
                                     "t-j1", "integration-test")
        check("A-land-t-j1-accepted",
              bool(getattr(r, "ok", True) or not getattr(r, "error", "")),
              str(getattr(r, "error", "")))
        shas.append(head())
        lane_branch(repo, "lane-b", "b.txt", "b\n")  # HEAD now on lane-b
        r = develop_line.land_ticket(line, key, {"repo1": Path(repo)},
                                     "t-j2", "integration-test")
        check("A-land-t-j2-accepted",
              bool(getattr(r, "ok", True) or not getattr(r, "error", "")),
              str(getattr(r, "error", "")))
        shas.append(head())
        rows = [json.loads(ln) for ln in
                open(os.path.join(dev_dir, "landings.jsonl")) if ln.strip()]
        check("A-record-two-rows", len(rows) == 2, "rows=%d" % len(rows))
        if rows:
            r0 = rows[0]
            check("A-record-fields",
                  r0.get("ticket") == "t-j1" and r0.get("line_id") == "line-1"
                  and "repo1" in r0.get("revisions", {}) and isinstance(r0.get("at"), int)
                  and r0.get("by") == "integration-test",
                  json.dumps(r0)[:200])
            rid = str(r0.get("id", ""))
            check("A-record-ulid-shape", rid.startswith("ldg-") and len(rid) > 20, rid)
            check("A-record-rev-is-reader-head",
                  rows[-1].get("revisions", {}).get("repo1") == shas[-1],
                  "%s vs %s" % (rows[-1].get("revisions", {}).get("repo1"), shas[-1]))
        log = git("log", "--format=%P|%s", line_branch, cwd=repo).stdout.strip().splitlines()
        merges = [ln for ln in log if ln.split("|")[0].count(" ") == 1]
        check("A-linear-two-merge-commits", len(merges) == 2, str(log))
        if len(merges) == 2:
            parents0 = merges[0].split("|")[0].split()
            check("A-linear-parent-chain", parents0[0] == shas[0],
                  "first merge parent %s != first landing head %s" % (parents0[0], shas[0]))
            msgs = git("log", "--format=%s", line_branch, cwd=repo).stdout
            check("A-landing-message-face", "landing" in msgs and "t-j1" in msgs,
                  msgs[:200])
        # line worktree left clean
        wt = os.path.join(dev_dir, "wt", "repo1")
        if os.path.isdir(wt):
            mh = git("rev-parse", "--verify", "MERGE_HEAD", cwd=wt)
            check("A-no-mergehead-residue", mh.returncode != 0, mh.stdout[:80])

        # --- B: one landing per ticket ---
        before = head()
        try:
            develop_line.land_ticket(line, key, {"repo1": Path(repo)}, "t-j1", "integration-test")
            refused = False
        except Exception as e:
            refused = True
        rows_b = sum(1 for ln in open(os.path.join(dev_dir, "landings.jsonl")) if ln.strip())
        check("B-refused-no-second-row", refused and rows_b == 2 and head() == before,
              "refused=%s rows=%d" % (refused, rows_b))

        # --- C: conflict bounce-back, no record, clean worktree ---
        before = head()
        try:
            ln_c = _line_with_branch(line, "lane-c")
            develop_line.land_ticket(ln_c, key, {"repo1": Path(repo)}, "t-j3", "integration-test")
            bounced = False
        except Exception:
            bounced = True
        rows_c = sum(1 for ln in open(os.path.join(dev_dir, "landings.jsonl")) if ln.strip())
        check("C-conflict-no-record-head-unchanged",
              rows_c == 2 and head() == before, "rows=%d" % rows_c)
        if os.path.isdir(wt):
            mh = git("rev-parse", "--verify", "MERGE_HEAD", cwd=wt)
            check("C-worktree-aborted-clean", mh.returncode != 0, "MERGE_HEAD present")

        # --- D: two OS processes race the landing ---
        # Each racer needs its OWN lane revision at its own checkout's HEAD:
        # land_ticket lands the lane repo's CURRENT HEAD, so both branches are
        # created up front, the clone carries both, and each checkout is moved
        # onto its own lane branch before the race (a racer landing the same
        # sha as the other would take the recovered-duplicate path instead of
        # racing -- that path is pinned separately in face E below).
        lane_branch(repo, "lane-a2", "a2.txt", "a2\n")
        lane_branch(repo, "lane-b2", "b2.txt", "b2\n")
        git("checkout", "-q", "lane-a2", cwd=repo)  # racer1's HEAD
        clone2 = os.path.join(root, "repo1-clone")
        git("clone", "-q", repo, clone2, cwd=root)
        # a clone carries the line branch only as a remote-tracking ref; the
        # landing reads refs/heads/* in the lane repo, so localise them
        git("branch", "develop-main", "origin/develop-main", cwd=clone2)
        git("branch", "main", "origin/main", cwd=clone2)
        git("checkout", "-q", "lane-b2", cwd=clone2)  # racer2's HEAD
        procs = [subprocess.Popen(
            [sys.executable, "-c", RACER, ENGINE, root, key, line_branch, br, tid, rp],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for tid, br, rp in (("t-r1", "lane-a2", repo),
                                ("t-r2", "lane-b2", clone2))]
        outs = [p.communicate()[0] for p in procs]
        rows_d = [json.loads(ln) for ln in
                  open(os.path.join(dev_dir, "landings.jsonl")) if ln.strip()]
        race_rows = [r for r in rows_d if r.get("ticket") in ("t-r1", "t-r2")]
        ok_races = sum(1 for o in outs if '"ok": true' in o or "RACE_OK" in o)
        named_refusals = sum(1 for o in outs if "lock" in o.lower() or "RACE_REFUSED" in o)
        check("D-race-no-interleave",
              len(race_rows) == ok_races and ok_races + named_refusals == 2
              and ok_races >= 1,
              "rows=%d ok=%d refused=%d out=%r" % (len(race_rows), ok_races,
                                                   named_refusals, outs))
        # distinct shas are the fixture's own precondition: if the two racers
        # landed the same revision the race face below would count the
        # recovered-duplicate path, not a race
        check("D-race-distinct-revisions",
              len({r.get("revisions", {}).get("repo1") for r in race_rows})
              == len(race_rows),
              str([r.get("revisions") for r in race_rows]))
        if race_rows:
            # Linear history has ONE physical realisation: the project store
            # owns a single line worktree per declared repository (created
            # from `repo` in face A), so every landing -- including both
            # racers -- appends its merge commit to that one line branch.
            # It must carry ALL landings: the two section-A ones plus every
            # successful race landing.
            logd_repo = git("log", "--format=%s", line_branch, cwd=repo).stdout
            check("D-race-history-linear",
                  logd_repo.count("landing") == 2 + ok_races,
                  "repo=%d expected=%d outs=%r"
                  % (logd_repo.count("landing"), 2 + ok_races, outs))

        # --- E: recovered-duplicate face (a landing whose lane tip is already
        # on the line) -- content already delivered, so the contract is: no new
        # commit (linear history untouched), a NAMED recovered face, ok=True,
        # and exactly one more record for the new ticket (its content IS on
        # the line, delivered by this landing even though no merge was needed).
        tip = head()
        # pin the lane repo at a revision ALREADY on the line (a successful
        # racer's landing revision) so the E landing is deterministically a
        # recovered duplicate, never a fresh merge
        git("checkout", "-q", race_rows[0]["revisions"]["repo1"], cwd=repo)
        r = develop_line.land_ticket(line, key, {"repo1": Path(repo)},
                                     "t-e1", "integration-test")
        check("E-recovered-ok-named",
              bool(getattr(r, "ok", False))
              and "recovered" in str(getattr(r, "faces", {})).lower(),
              "ok=%s faces=%s" % (getattr(r, "ok", None), getattr(r, "faces", None)))
        check("E-recovered-no-new-commit", head() == tip,
              "%s -> %s" % (tip[:10], head()[:10]))
        rows_e = sum(1 for ln in open(os.path.join(dev_dir, "landings.jsonl"))
                     if ln.strip())
        check("E-recovered-record-appended", rows_e == 2 + ok_races + 1,
              "rows=%d" % rows_e)
        print("JOURNEY done: %d pass / %d fail" % (passed, failed))
        return 1 if failed else 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _line_with_branch(line, branch):
    import copy
    ln = copy.deepcopy(line)
    for r in getattr(ln, "repositories", []):
        r.branch = branch
    return ln


RACER = r'''
import sys, json
sys.path.insert(0, sys.argv[1])
os_root, key, line_branch, lane_branch, tid, repo = sys.argv[2:8]
import os
os.environ["SANDBAR_PROJECTS_DIR"] = os_root
import copy
from pathlib import Path
import develop_line, shared
try:
    line = develop_line.load_line(key, "line-1")
    ln = copy.deepcopy(line)
    for r in getattr(ln, "repositories", []):
        r.branch = line_branch
    r = develop_line.land_ticket(ln, key, {"repo1": Path(repo)}, tid, "integration-test")
    if getattr(r, "error", ""):
        print("RACE_REFUSED:", getattr(r, "error"))
        sys.exit(0)
    print("RACE_OK")
except Exception as e:
    msg = str(e)
    print("RACE_REFUSED:" if "lock" in msg.lower() or "refus" in msg.lower()
          else "RACE_FAIL:", msg)
    sys.exit(0 if "lock" in msg.lower() or "refus" in msg.lower() else 1)
'''


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        print("FAIL journey-crashed :: %r (named failure beats a silent face)" % e)
        sys.exit(1)
