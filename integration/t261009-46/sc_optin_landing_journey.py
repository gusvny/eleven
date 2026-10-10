#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_optin_landing_journey.py -- t261009-46 L3 journey: a ticket that opts in
to the new lane version lands its PROVEN revision on its declared line, and a
bad version name is never defaulted (grey-box L3, real git subprocesses on
fixture repos, offline seconds, stdlib only, zero docker/Temporal/browser,
never touches 3099/7233).

intent: this entry owns the opt-in landing journey the ticket spec names:
  A  the opt-in refusal matrix -- an unknown, empty, non-str, whitespace or
     wrong-case version name is refused BY NAME (the bad value appears in the
     message) and is never silently read as either version; the lawful names
     come back canonical.
  B  a develop-buffer ticket's proven revision lands on its declared line via
     the landing act: the line branch advances to a merge commit carrying the
     lane's content, MAIN DOES NOT MOVE, and the delivery ledger gains exactly
     ONE landing row for the ticket (read back from the ledger FILE, reader
     side).
  C  the revision that lands is the PROVEN one, not the current tip: with the
     lane checkout drifted ahead of the proven revision on a clean tree, the
     landing pins the checkout and lands the PROVEN revision -- the tip's
     content never reaches the line.
  D  a checkout that CANNOT be pinned (dirty tree over a drifted HEAD) refuses
     BY NAME, the line branch does not move, and the delivery ledger gains no
     row -- landing something else is never the fallback.

Surfaces anchored (approved plan, public faces only): develop_line's lane
version constants and parse/pin helpers with their named errors, and the
agent_activities land_to_line activity. Absent surface = FAIL named (the
expected TDD signal before implement); green required at the integration
gate / merge. git or repo root missing = ENV_FAIL exit 2.
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


def lane_commit(repo, fname, content, msg):
    """One commit on the lane branch, HEAD left on it (the landing consumes the
    lane checkout's current HEAD)."""
    with open(os.path.join(repo, fname), "w") as f:
        f.write(content)
    git("add", "-A", cwd=repo)
    git("-c", "user.email=t@s", "-c", "user.name=t", "commit", "-qm", msg, cwd=repo)
    return git("rev-parse", "HEAD", cwd=repo).stdout.strip()


def rev(repo, ref):
    return git("rev-parse", ref, cwd=repo).stdout.strip()


def landing_rows(certify, key):
    rows, bad = certify.read_rows(certify.ledger_path(key))
    check("ledger-reads-clean", not bad, str(bad)[:160])
    return certify._of_kind(rows, certify.KIND_LANDING)


def err_text(fn, *a, **kw):
    try:
        fn(*a, **kw)
        return None
    except Exception as e:  # the named-refusal faces are the point
        return "%s: %s" % (type(e).__name__, e)


def call_land(mod, ticket_id, key, line_id, worktrees, proven):
    """Drive the landing activity through its declared public shape. The
    activity face is async; the args dataclass has settled as either the
    per-repository maps (worktrees/proven) or the single-scope fields
    (worktree/proven_sha) -- build whichever the declared shape carries."""
    import asyncio
    from dataclasses import fields as dc_fields
    land = mod.land_to_line
    names = {f.name for f in dc_fields(mod.LandToLineArgs)}
    wt_name, wt_path = sorted(worktrees.items())[0]
    sha = proven[wt_name]
    if "worktrees" in names:
        args = mod.LandToLineArgs(ticket_id=ticket_id, project_key=key,
                                  line_id=line_id,
                                  worktrees={k: str(v) for k, v in worktrees.items()},
                                  proven=dict(proven))
    else:
        args = mod.LandToLineArgs(ticket_id=ticket_id, project_key=key,
                                  line_id=line_id, worktree=str(wt_path),
                                  proven_sha=sha)
    coro = land(args)
    if hasattr(coro, "__await__"):
        return asyncio.run(coro)
    return coro


def main():
    if shutil.which("git") is None or REPO.returncode != 0:
        print("ENV_FAIL: git or repo root unavailable")
        return 2
    if not os.path.isdir(ENGINE):
        print("FAIL engine-tree-absent :: %s (TDD signal)" % ENGINE)
        return 1
    sys.path.insert(0, ENGINE)
    try:
        import develop_certify
        import develop_line
        import shared
    except ImportError as e:
        print("FAIL engine-module-unimportable :: %s" % e)
        return 1

    root = tempfile.mkdtemp(prefix="t26100946-journey-")
    try:
        os.environ["SANDBAR_PROJECTS_DIR"] = root
        os.environ["SANDBAR_DELIVERY_LEDGER_DIR"] = os.path.join(root, "ledger")
        key = "t26100946"
        line_branch = "develop-main"
        repo = make_repo(root, "repo1")
        git("checkout", "-q", "-b", "lane-t46", "main", cwd=repo)

        dev_dir = shared.develop_dir(key)
        os.makedirs(dev_dir, exist_ok=True)
        with open(os.path.join(dev_dir, "lines.json"), "w") as f:
            json.dump([{"version": 1, "line_id": "line-1", "scope": "t46",
                        "owner": "integration-role",
                        "repositories": [{"name": "repo1", "branch": line_branch}]}], f)
        line = develop_line.load_line(key, "line-1")

        # --- A: the opt-in refusal matrix (never defaulted, refuses by name) ---
        lawful = getattr(develop_line, "LANE_VERSION_DEVELOP_BUFFER", None), \
            getattr(develop_line, "LANE_VERSION_LEGACY", None)
        parse = getattr(develop_line, "parse_lane_version", None)
        if parse is None or not all(lawful):
            print("FAIL optin-surface-absent :: parse_lane_version / version "
                  "constants missing (expected before implement; TDD signal)")
            return 1
        for bad in ["develop-buffer-v2", 123, " develop-buffer-v1",
                    "DEVELOP-BUFFER-V1", "develop-buffer-v1 "]:
            msg = err_text(parse, bad)
            if msg is None:
                check("refused-%r" % (bad,), False, "malformed name was accepted")
            else:
                named = str(bad).strip() in msg or type(bad).__name__ in msg
                check("refused-%r" % (bad,), named, "refusal does not name the value: %s" % msg[:120])
        # the ABSENT shape (None / "") is the legacy ticket's field: it resolves
        # to the legacy version by declaration, never refused, never migrated
        for absent in [None, ""]:
            try:
                got = parse(absent)
            except Exception as e:
                got = "raised %s" % e
            check("absent-is-legacy-%r" % (absent,),
                  got == develop_line.LANE_VERSION_LEGACY, "got %r" % (got,))
        for good in lawful:
            try:
                got = parse(good)
            except Exception as e:
                got = "raised %s" % e
            check("canonical-%s" % good, got == good, "got %r" % (got,))

        # --- B: opt-in landing end to end (proven sha -> the line, main unmoved) ---
        try:
            import agent_activities as acts
        except ImportError as e:
            print("FAIL agent-activities-unimportable :: %s" % e)
            return 1
        if not hasattr(acts, "land_to_line"):
            print("FAIL land-activity-absent :: agent_activities.land_to_line "
                  "missing (expected before implement; TDD signal)")
            return 1
        main_before = rev(repo, "main")
        proven = lane_commit(repo, "b.txt", "b\n", "the proven work")
        r = call_land(acts, "t46-b", key, "line-1",
                      {"repo1": Path(repo)}, {"repo1": proven})
        line_tip = rev(repo, line_branch)
        check("land-receipt-ok", getattr(r, "ok", False) is True and not getattr(r, "error", "x"),
              "ok=%r error=%r" % (getattr(r, "ok", None), getattr(r, "error", "")[:120]))
        check("line-carries-proven",
              subprocess.run(["git", "merge-base", "--is-ancestor", proven, line_tip],
                             cwd=repo).returncode == 0,
              "proven %s not on line tip %s" % (proven[:12], line_tip[:12]))
        check("line-is-merge-commit",
              len(git("log", "-1", "--format=%P", line_branch, cwd=repo)
                  .stdout.split()) == 2,
              "line tip parents: %r" % git("log", "-1", "--format=%P", line_branch,
                                           cwd=repo).stdout.strip())
        check("main-did-not-move", rev(repo, "main") == main_before,
              "main moved without a promotion")
        rows = landing_rows(develop_certify, key)
        check("one-landing-row", len(rows) == 1, "rows=%d" % len(rows))
        if rows:
            row = rows[0]
            check("row-names-ticket-line",
                  row.get("ticket") == "t46-b" and row.get("line") == "line-1",
                  str(row)[:200])
            repo_heads = {h.get("repo"): h.get("revision") for h in row.get("repos", [])
                          if isinstance(h, dict)}
            check("row-head-is-line-tip", repo_heads.get("repo1") == line_tip,
                  "row says %r, reader sees %r" % (repo_heads.get("repo1"), line_tip))
        receipt_revs = getattr(r, "revisions", None) or {}
        if receipt_revs:
            check("receipt-matches-reader", receipt_revs.get("repo1") == line_tip,
                  "receipt says %r, reader sees %r" % (receipt_revs.get("repo1"), line_tip))
        else:
            check("receipt-matches-reader", False, "receipt carries no revisions map")

        # --- C: the PROVEN revision lands, not the drifted tip (clean tree pins) ---
        repo2 = make_repo(root, "repo2")
        git("checkout", "-q", "-b", "lane-c", "main", cwd=repo2)
        decl2 = os.path.join(dev_dir, "lines.json")
        with open(decl2) as f:
            decl = json.load(f)
        decl.append({"version": 1, "line_id": "line-2", "scope": "t46c",
                     "owner": "integration-role",
                     "repositories": [{"name": "repo2", "branch": "develop-c"}]})
        with open(decl2, "w") as f:
            json.dump(decl, f)
        line2 = develop_line.load_line(key, "line-2")
        sha_proven = lane_commit(repo2, "c.txt", "v1\n", "proven rev")
        sha_tip = lane_commit(repo2, "c.txt", "v2\n", "later tip, NOT proven")
        r2 = call_land(acts, "t46-c", key, "line-2", {"repo2": Path(repo2)},
                       {"repo2": sha_proven})
        ok2 = getattr(r2, "ok", False) is True
        check("drift-clean-pins-and-lands", ok2, repr(r2)[:160])
        if ok2:
            shown = git("show", "develop-c:c.txt", cwd=repo2).stdout
            check("landed-content-is-proven", shown.strip() == "v1",
                  "line carries %r" % shown[:40])
            parents = git("log", "-1", "--format=%P", "develop-c", cwd=repo2).stdout.split()
            check("merge-parent-is-proven", sha_proven in parents,
                  "parents=%r tip=%s" % (parents, sha_tip[:12]))
            checkout_txt = git("show", "HEAD:c.txt", cwd=repo2).stdout
            check("checkout-was-pinned-to-proven", checkout_txt.strip() == "v1",
                  "lane HEAD content %r after landing" % checkout_txt[:40])

        # --- D: a checkout that cannot be pinned refuses by name, zero writes ---
        repo3 = make_repo(root, "repo3")
        git("checkout", "-q", "-b", "lane-d", "main", cwd=repo3)
        decl.append({"version": 1, "line_id": "line-3", "scope": "t46d",
                     "owner": "integration-role",
                     "repositories": [{"name": "repo3", "branch": "develop-d"}]})
        with open(decl2, "w") as f:
            json.dump(decl, f)
        line3 = develop_line.load_line(key, "line-3")
        sha_d = lane_commit(repo3, "d.txt", "d\n", "proven for D")
        lane_commit(repo3, "d.txt", "drift\n", "drifted tip")
        with open(os.path.join(repo3, "d.txt"), "a") as f:
            f.write("dirty\n")
        before3 = rev(repo3, "HEAD")
        pin = getattr(develop_line, "pin_lane_revision", None)
        msg_pin = err_text(pin, Path(repo3), sha_d) if pin else None
        r3 = call_land(acts, "t46-d", key, "line-3",
                       {"repo3": Path(repo3)}, {"repo3": sha_d})
        msg_act = getattr(r3, "error", "") if getattr(r3, "ok", True) is False else None
        named = (msg_act is not None) and ("pin" in msg_act.lower() or
                                           "proven" in msg_act.lower() or
                                           "dirty" in msg_act.lower() or
                                           "head" in msg_act.lower())
        check("drift-dirty-refuses-by-name",
              getattr(r3, "ok", True) is False and named,
              "expected a named pin refusal in the receipt, got ok=%r error=%r"
              % (getattr(r3, "ok", None), (msg_act or "")[:160]))
        check("refusal-names-shas", msg_pin is None or
              (sha_d[:7] in msg_pin or sha_d[:12] in msg_pin),
              "pin refusal does not name the proven sha: %s" % (msg_pin or "-"))
        rows_d = landing_rows(develop_certify, key)
        check("no-row-on-refusal", len(rows_d) == 2, "rows=%d" % len(rows_d))
        check("line-d-never-created",
              git("rev-parse", "--verify", "-q", "develop-d", cwd=repo3).returncode != 0,
              "line branch exists despite refusal")
        check("lane-head-untouched-by-refusal", rev(repo3, "HEAD") == before3,
              "lane checkout moved during a refused landing")

        print("SUMMARY t26100946-optin-landing-journey pass=%d fail=%d" % (passed, failed))
        return 1 if failed else 0
    finally:
        os.environ.pop("SANDBAR_PROJECTS_DIR", None)
        os.environ.pop("SANDBAR_DELIVERY_LEDGER_DIR", None)
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
