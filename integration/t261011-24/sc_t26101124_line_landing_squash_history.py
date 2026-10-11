#!/usr/bin/env python3
"""sc_t26101124_line_landing_squash_history.py -- t261011-24 L3 (integration role).

User-visible contract (ticket t261011-24, host order 261011 '缓冲票 → 线 应该
squash 吧'): a develop-buffer landing must read as ONE commit per ticket on the
line, the same recipe the main close-out uses — not a real merge that drags
every lane step commit (and every lane-side main merge) into the line's
history. Measured defect shape: line HEAD 6efc7b3e was a 2-parent merge whose
first parent was itself a merge.

  A  ONE COMMIT PER LANDING — two landings in turn each add EXACTLY ONE
     commit to the line branch; every landing commit is single-parent whose
     parent is the previous line head; the landing commit's message names the
     ticket id and the destination line; the landing record's revision (read
     back from the delivery-ledger FILE) equals the line head the reader sees.
  B  LANE HISTORY EXCLUDED — the lanes carry multiple step commits; none of
     those shas appear anywhere in the line branch's history (the host's
     exact complaint, judged by sha over `git rev-list`).
  C  CONFLICT BOUNCE-BACK KEEPS ITS TEETH ON THE LINE PATH — a conflicting
     lane refuses by name, the line worktree shows no merge-state residue
     (no MERGE_HEAD, no unmerged entries), no record row, head unmoved; after
     the lane resolves and re-lands (the Temporal timeout-retry shape), the
     landing succeeds with exactly one new commit.
  D  CRASH RECOVERY (KI-213 family, re-scoped) — a landing whose commit
     already reached the line but whose record was lost (fixture: the row is
     removed from the temp ledger) re-lands WITHOUT a new commit and appends
     the missing record naming the CURRENT head — never a rewritten sha.
  E  GITLINK REFUSAL CARRIES OVER — a lane diff containing a nested-repo
     gitlink refuses by name (the t260916-20 silent-loss red line applies to
     the line too), no record, head unmoved.
  F  MAIN CLOSE-OUT UNTOUCHED (shared-recipe regression) — the legacy main
     close-out act still produces exactly ONE single-parent commit per ticket
     naming the ticket; the recipe refactor this ticket performs must be
     behaviour-neutral on main.

Grey-box L3: real git subprocesses on fixture repos, the public surfaces
(develop_line.load_line / land_ticket / LandingError; agent_activities
_squash_merge MergeResult), the delivery-ledger FILE read back from disk.
Isolated SANDBAR_PROJECTS_DIR + ledger dir; offline seconds; zero
docker/Temporal/browser; never touches 3099/7233. tier: the develop-buffer
landing journey's history-shape contract over real git fixtures plus the
main close-out regression act; cost: seconds.

Intent split (no duplication): the ancestor fail-closed gate and the
legacy-ledger refusal belong to t261009-28-legacy-ancestor-gate; the freeze
consultation belongs to t261009-67-freeze-stops-landings; duplicate landing
refusal, cross-process serialization and the linear-record reader journey
belong to t261009-18-line-landing-journey (its leg A stays green under the
squash shape — same count, now single-parent); main-side dirt classification
and prose exemption belong to t261011-16-prose-dirt-landing. This entry owns
the HISTORY SHAPE delta (one squash commit per ticket, lane commits absent),
the line-path conflict/crash recovery acts and the gitlink carry-over. The
cleanup recipe's unit truth table and malformed-input taxonomy belong to
developer L1. Pre-implementation tree: A/B/E red, C/D/F shaped by today's
real merge (expected TDD signal); green required at the integration gate /
merge. git absent or engine modules unimportable = ENV_FAIL exit 2.
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


def commit_all(repo, msg):
    git("add", "-A", cwd=repo)
    return git("-c", "user.email=t@s", "-c", "user.name=t", "commit", "-qm", msg,
               cwd=repo)


def make_repo(root, name):
    path = os.path.join(root, name)
    os.makedirs(path)
    git("init", "-q", "-b", "main", cwd=path)
    with open(os.path.join(path, "base.txt"), "w") as f:
        f.write("base\n")
    commit_all(path, "base")
    return path


def lane_two_steps(repo, branch, base_ref, fname, lines):
    """A lane branch carrying TWO step commits (the shape the host complained
    about: every step commit used to enter the line history)."""
    git("checkout", "-q", "-b", branch, base_ref, cwd=repo)
    for i, line in enumerate(lines):
        with open(os.path.join(repo, fname), "a") as f:
            f.write(line + "\n")
        c = commit_all(repo, "lane step %d on %s" % (i + 1, branch))
        assert c.returncode == 0, c.stderr
    return [l.split()[0] for l in git(
        "rev-list", "--ancestry-path", "%s..%s" % (base_ref, branch),
        cwd=repo).stdout.split()]


def declare_line(key, repo_name, branch):
    import shared
    dev_dir = shared.develop_dir(key)
    os.makedirs(dev_dir, exist_ok=True)
    with open(os.path.join(dev_dir, "lines.json"), "w") as f:
        json.dump([{"version": 1, "line_id": "line-1", "scope": "slice",
                    "owner": "integration-role",
                    "repositories": [{"name": repo_name, "branch": branch}]}], f)


def landing_rows(key):
    import develop_certify
    lpath = develop_certify.ledger_path(key)
    if not os.path.exists(lpath):
        return []
    rows = develop_certify.read_rows(lpath)[0]
    return [x for x in rows if isinstance(x, dict)
            and x.get("kind") == develop_certify.KIND_LANDING]


def try_land(line, key, repo, ticket):
    import develop_line
    try:
        r = develop_line.land_ticket(line, key, {repo_name_of(key): Path(repo)},
                                     ticket, "integration-test")
        return ("ok" if getattr(r, "ok", False) else "not-ok"), r
    except develop_line.LandingError as e:
        return "refused", e
    except Exception as e:
        return "wrong-exc:%s" % type(e).__name__, e


def repo_name_of(key):
    return {"k1": "repo1", "k2": "repo2", "k3": "repo3",
            "k4": "repo4", "k5": "repo5"}.get(key, "repoX")


def rev_list(repo, ref):
    return git("rev-list", ref, cwd=repo).stdout.split()


def heads(repo, branch):
    p = git("rev-parse", branch, cwd=repo)
    return p.stdout.strip() if p.returncode == 0 else ""


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
        print("FAIL develop-modules-absent :: %s (TDD signal)" % e)
        return 1
    try:
        import agent_activities
    except ImportError as e:
        print("ENV_FAIL: agent_activities unimportable (temporalio missing?): %s" % e)
        return 2

    root = tempfile.mkdtemp(prefix="t26101124-squash-")
    try:
        os.environ["SANDBAR_PROJECTS_DIR"] = root
        os.environ[develop_certify.LEDGER_DIR_ENV] = os.path.join(root, "ledger")
        branch = "develop-main"

        # ---- A + B: two landings, one squash commit each, lane history out ----
        repo = make_repo(root, "repo1")
        base_head = heads(repo, "main")
        base_cnt = len(rev_list(repo, "main"))
        lane1 = lane_two_steps(repo, "lane-t1", "main", "f1.txt",
                               ["t1-step-1", "t1-step-2"])
        declare_line("k1", "repo1", branch)
        line1 = develop_line.load_line("k1", "line-1")
        st1, r1 = try_land(line1, "k1", repo, "t-squash-1")
        check("A-landing1-ok", st1 == "ok", "%s %r" % (st1, r1))
        head1 = heads(repo, branch)
        lane2 = lane_two_steps(repo, "lane-t2", branch, "f2.txt",
                               ["t2-step-1", "t2-step-2"])
        line1 = develop_line.load_line("k1", "line-1")
        st2, r2 = try_land(line1, "k1", repo, "t-squash-2")
        check("A-landing2-ok", st2 == "ok", "%s %r" % (st2, r2))
        head2 = heads(repo, branch)

        check("A-one-commit-per-landing",
              len(rev_list(repo, branch)) == base_cnt + 2,
              "line count %d != base+2 (%d)" % (len(rev_list(repo, branch)),
                                                base_cnt + 2))
        parents2 = git("rev-parse", "%s^@" % branch, cwd=repo).stdout.split()
        check("A-tip-single-parent", len(parents2) == 1, str(parents2))
        check("A-parent-chain", parents2 and parents2[0] == head1,
              "%s != %s" % (parents2, head1))
        log = git("log", "--format=%s", branch, cwd=repo).stdout
        check("A-msg-names-ticket-and-line",
              "t-squash-1" in log and "t-squash-2" in log and "line-1" in log,
              log[:300])
        rows = landing_rows("k1")
        check("A-record-reads-line-head",
              len(rows) == 2 and all(
                  any(rr.get("repo") == "repo1" and rr.get("revision") == h
                      for rr in row.get("repos", []))
                  for row, h in zip(rows, [head1, head2])),
              json.dumps(rows)[:300])

        check("B-lane-commits-excluded",
              not (set(lane1) | set(lane2)) & set(rev_list(repo, branch)),
              "lane step commits leaked into line history: %s"
              % ((set(lane1) | set(lane2)) & set(rev_list(repo, branch))))
        check("B-line-heads-advanced",
              head1 != base_head and head2 != head1,
              "%s %s %s" % (base_head, head1, head2))

        # ---- C: conflict bounce-back + retry after resolve ----
        # the lane branches from the PREVIOUS line head (head2) and edits
        # f2.txt; the line then advances f2.txt itself -> a genuine content
        # conflict when the landing squashes the lane onto the advanced line
        git("checkout", "-q", "-B", "lane-t3", head2, cwd=repo)
        with open(os.path.join(repo, "f2.txt"), "a") as f:
            f.write("t3-clash-same-line\n")
        commit_all(repo, "t3 clash on f2")
        # advance the line INSIDE its engine worktree (the branch is checked
        # out there; a checkout in the origin repo would be refused and the
        # commit would silently land on the lane branch)
        wt_dir = os.path.join(shared.develop_dir("k1"), "wt", "repo1")
        with open(os.path.join(wt_dir, "f2.txt"), "a") as f:
            f.write("line-side-advance\n")
        commit_all(wt_dir, "line advance on f2")
        conflict_base = heads(repo, branch)
        line1 = develop_line.load_line("k1", "line-1")
        st3, e3 = try_land(line1, "k1", repo, "t-squash-3")
        check("C-conflict-refused-named", st3 == "refused", "%s %r" % (st3, e3))
        check("C-no-record", len(landing_rows("k1")) == 2,
              str(landing_rows("k1"))[:200])
        check("C-head-unmoved", heads(repo, branch) == conflict_base,
              heads(repo, branch))
        wt_dir = os.path.join(shared.develop_dir("k1"), "wt", "repo1")
        mh = git("rev-parse", "-q", "--verify", "MERGE_HEAD", cwd=wt_dir)
        check("C-no-mergehead-residue", mh.returncode != 0, mh.stdout[:80])
        lsu = git("ls-files", "-u", cwd=wt_dir)
        check("C-no-unmerged-residue", not (lsu.stdout or "").strip(),
              lsu.stdout[:200])
        # the lane resolves onto the advanced line (the retry shape) and lands
        git("checkout", "-q", "lane-t3", cwd=repo)
        mg = git("rebase", branch, cwd=repo)
        if mg.returncode != 0:
            # resolve the clash the way a lane would: keep both edits, commit
            with open(os.path.join(repo, "f2.txt"), "a") as f:
                f.write("t3-resolved-onto-line\n")
            git("add", "-A", cwd=repo)
            env = dict(os.environ, GIT_EDITOR="true")
            subprocess.run(
                ["git", "-c", "user.email=t@s", "-c", "user.name=t",
                 "rebase", "--continue"], cwd=repo, env=env,
                capture_output=True, text=True)
        line1 = develop_line.load_line("k1", "line-1")
        st3r, r3 = try_land(line1, "k1", repo, "t-squash-3")
        check("C-retry-lands", st3r == "ok", "%s %r" % (st3r, r3))
        check("C-retry-one-commit",
              len(rev_list(repo, branch)) == base_cnt + 4,
              str(len(rev_list(repo, branch))))

        # ---- D: crash recovery (commit on line, record lost) ----
        lane_two_steps(repo, "lane-t4", branch, "f4.txt", ["t4-step"])
        line1 = develop_line.load_line("k1", "line-1")
        st4, r4 = try_land(line1, "k1", repo, "t-squash-4")
        check("D-landing-ok", st4 == "ok", "%s %r" % (st4, r4))
        head4 = heads(repo, branch)
        lpath = develop_certify.ledger_path("k1")
        with open(lpath, encoding="utf-8") as f:
            raw = [ln for ln in f.read().splitlines() if ln.strip()]
        kept = [ln for ln in raw
                if not (json.loads(ln).get("kind") == develop_certify.KIND_LANDING
                        and json.loads(ln).get("ticket") == "t-squash-4")]
        with open(lpath, "w", encoding="utf-8") as f:
            f.write("\n".join(kept) + "\n")
        check("D-record-removed", len(landing_rows("k1")) == 3, "")
        line1 = develop_line.load_line("k1", "line-1")
        st4r, r4r = try_land(line1, "k1", repo, "t-squash-4")
        check("D-recovery-ok", st4r == "ok", "%s %r" % (st4r, r4r))
        check("D-recovery-no-new-commit", heads(repo, branch) == head4,
              "%s != %s" % (heads(repo, branch), head4))
        rows4 = landing_rows("k1")
        check("D-recovery-record-names-current-head",
              any(any(rr.get("repo") == "repo1" and rr.get("revision") == head4
                      for rr in row.get("repos", []))
                  for row in rows4 if row.get("ticket") == "t-squash-4"),
              json.dumps(rows4)[-300:])

        # ---- E: gitlink refusal carries over to the line path ----
        repo5 = make_repo(root, "repo5")
        nested = os.path.join(repo5, "nested")
        os.makedirs(nested)
        git("init", "-q", cwd=nested)
        with open(os.path.join(nested, "n.txt"), "w") as f:
            f.write("n\n")
        commit_all(nested, "nested base")
        git("checkout", "-q", "-b", "lane-git", "main", cwd=repo5)
        git("add", "nested", cwd=repo5)
        gl = commit_all(repo5, "lane adds a gitlink")
        check("E-fixture-is-gitlink",
              "160000" in git("ls-files", "-s", cwd=repo5).stdout, "")
        declare_line("k5", "repo5", branch)
        line5 = develop_line.load_line("k5", "line-1")
        head5 = heads(repo5, branch) or "(no line branch yet)"
        st5, e5 = try_land(line5, "k5", repo5, "t-git")
        check("E-gitlink-refused-named", st5 == "refused", "%s %r" % (st5, e5))
        check("E-gitlink-refusal-names",
              "gitlink" in str(e5).lower() or "160000" in str(e5)
              or "嵌套" in str(e5), str(e5)[:200])
        check("E-no-record", len(landing_rows("k5")) == 0, "")

        # ---- F: main close-out regression (recipe refactor is neutral) ----
        repo6 = make_repo(root, "repo6")
        wt6 = repo6  # bare-enough fixture: the close-out act runs on the checkout
        lane6 = lane_two_steps(repo6, "lane-t6", "main", "f6.txt",
                               ["t6-step-1", "t6-step-2"])
        git("checkout", "-q", "main", cwd=repo6)
        mbase = len(rev_list(repo6, "main"))
        m = agent_activities._squash_merge(repo6, Path(wt6), "lane-t6",
                                           "t-main-close", defer_teardown=True)
        check("F-closeout-ok", bool(getattr(m, "ok", False)),
              "ok=%r action=%r error=%r" % (getattr(m, "ok", None),
                                            getattr(m, "action", None),
                                            getattr(m, "error", "")))
        check("F-one-commit-per-ticket",
              len(rev_list(repo6, "main")) == mbase + 1,
              str(len(rev_list(repo6, "main"))))
        fparents = git("rev-parse", "main^@", cwd=repo6).stdout.split()
        check("F-single-parent", len(fparents) == 1, str(fparents))
        flog = git("log", "--format=%s", "main", cwd=repo6).stdout
        check("F-msg-names-ticket", "t-main-close" in flog, flog[:200])
        check("F-lane-steps-excluded",
              not set(lane6) & set(rev_list(repo6, "main")), "")

        print("SUMMARY t26101124_line_landing_squash_history "
              "passed=%d failed=%d" % (passed, failed))
        return 1 if failed else 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
