#!/usr/bin/env python3
"""sc_t26100928_one_home_landing_record.py -- t261009-28 L3 (integration role).

User-visible contract (ticket t261009-28 core claim + record-models rule "the
delivery records share ONE ordering space"): a landing performed by the LANDING
ACT is recorded ONCE, in the DELIVERY LEDGER, through the ledger's own writer
-- so it carries the writer-assigned seq and is computable everywhere the
"may this content be delivered" question is answered. Before this ticket the
landing act wrote a second shape (landings.jsonl, no seq) that the
certification / waiting / promotion faces could not see at all.

Grey-box L3: real git subprocesses on fixture repos, the public surfaces named
by the reviewed plan (develop_line.load_line / land_ticket,
develop_certify.ledger_path / read_rows / validate_row / append_rows /
derive_range / should_certify / has_landing), the delivery-ledger FILE read
back from disk (reader side, not the return value). Isolated
SANDBAR_PROJECTS_DIR + SANDBAR_DELIVERY_LEDGER_DIR; offline seconds; zero
docker/browser; never touches 3099.

Faces:
  A  one record in one home: after an accepted landing the delivery-ledger
     file on disk holds exactly ONE landing row -- kind/id(ldg-)/ticket/line/
     repos(repo+revision = the branch head the reader sees)/actor, a positive
     integer seq assigned by the ledger writer, validate_row-clean -- and the
     retired per-line landings.jsonl is NOT created.
  B  the shared ordering space is computable, both directions: a
     certification excludes the landing that precedes it, and a landing
     after that certification shows up as covered by derive_range (previous
     certification + covered landings + certified prefix derived from
     record order alone).
  C  the tick decision sees the landing: should_certify("change") answers
     True via the covered range -- the landing is no longer invisible to the
     flow's derived facts.
  D  the public reader face moved home: has_landing answers from the delivery
     ledger.

Intent split (no duplication): the landing act's own guarantees (linear
history, one-per-ticket refusal, conflict rollback, cross-process
serialization, recovered duplicate) stay owned by the adapted
t261009-18-line-landing-journey; record-truth tables and malformed matrices
belong to developer L1. Pre-implementation tree = FAIL named (TDD signal);
green required at the integration gate / merge. git or repo root missing =
ENV_FAIL exit 2.
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


def lane_branch(repo, branch, fname, content):
    """Head stays on the lane branch: land_ticket lands the current HEAD."""
    git("checkout", "-q", "-b", branch, "main", cwd=repo)
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

    root = tempfile.mkdtemp(prefix="t26100928-onehome-")
    try:
        os.environ["SANDBAR_PROJECTS_DIR"] = root
        ledger_dir = os.path.join(root, "ledger")
        os.environ[develop_certify.LEDGER_DIR_ENV] = ledger_dir
        key = "t26100928a"
        branch = "develop-main"
        repo = make_repo(root, "repo1")
        lane_branch(repo, "lane-a", "a.txt", "a\n")
        declare_line(key, "repo1", branch)
        line = develop_line.load_line(key, "line-1")
        head = lambda: git("rev-parse", branch, cwd=repo).stdout.strip()

        # --- A: the landing act writes ONE row, in the delivery ledger ---
        r = develop_line.land_ticket(line, key, {"repo1": Path(repo)},
                                     "t-a1", "integration-test")
        check("A-landing-accepted",
              bool(getattr(r, "ok", True) or not getattr(r, "error", "")),
              str(getattr(r, "error", "")))
        lpath = develop_certify.ledger_path(key)
        check("A-ledger-file-exists", lpath.is_file(), str(lpath))
        rows = develop_certify.read_rows(lpath)[0] if lpath.is_file() else []
        landings = [x for x in rows if isinstance(x, dict)
                    and x.get("kind") == develop_certify.KIND_LANDING]
        check("A-exactly-one-landing-row", len(landings) == 1,
              "rows=%d landings=%d" % (len(rows), len(landings)))
        row = landings[0] if landings else {}
        clean, why = develop_certify.validate_row(dict(row))
        check("A-row-validate_row-clean", clean is not None, why)
        check("A-ldg-id", str(row.get("id", "")).startswith("ldg-"), row.get("id", ""))
        check("A-ticket-line-actor",
              row.get("ticket") == "t-a1" and row.get("line") == "line-1"
              and isinstance(row.get("actor"), str) and row["actor"].strip(),
              json.dumps(row)[:200])
        revs = {x.get("repo"): x.get("revision")
                for x in row.get("repos", []) if isinstance(x, dict)}
        check("A-repos-carry-landed-head", revs.get("repo1") == head(),
              "recorded=%s head=%s" % (revs.get("repo1"), head()))
        check("A-writer-assigned-seq",
              isinstance(row.get("seq"), int) and not isinstance(row.get("seq"), bool)
              and row["seq"] > 0, row.get("seq"))
        check("A-no-stored-base", "base" not in row and "revisions" not in row,
              json.dumps(row)[:200])
        retired = os.path.join(shared.develop_dir(key), "landings.jsonl")
        check("A-second-shape-not-written", not os.path.exists(retired), retired)

        # --- B: the ONE ordering space is computable (both directions) ---
        landed = revs.get("repo1") or head()
        cert = {"kind": develop_certify.KIND_CERT, "id": "cert-b1",
                "line": "line-1", "repos": [{"repo": "repo1", "revision": landed}],
                "run": "run-b1", "booked_red": "no", "judged_by": "integration-test",
                "at": 1}
        ap = develop_certify.append_rows([cert], lpath)
        check("B-cert-appended", ap.get("written") == 1, json.dumps(ap))
        rows2 = develop_certify.read_rows(lpath)[0]
        rng = develop_certify.derive_range(rows2, "line-1")
        prev = rng.get("previous_certification") or {}
        covered = rng.get("covered_landings") or []
        check("B-prev-certification", prev.get("id") == "cert-b1", prev.get("id"))
        # the certification covers only landings AFTER it: the pre-cert
        # landing t-a1 is excluded, a post-cert landing t-a2 is covered
        check("B-pre-cert-landing-excluded",
              row.get("id") not in [x.get("id") for x in covered],
              json.dumps([x.get("id") for x in covered]))
        lane_branch(repo, "lane-c", "c.txt", "c\n")
        r = develop_line.land_ticket(line, key, {"repo1": Path(repo)},
                                     "t-a2", "integration-test")
        check("B-post-cert-landing-accepted",
              bool(getattr(r, "ok", True) or not getattr(r, "error", "")),
              str(getattr(r, "error", "")))
        rows3 = develop_certify.read_rows(lpath)[0]
        rng2 = develop_certify.derive_range(rows3, "line-1")
        covered2 = [x.get("ticket") for x in rng2.get("covered_landings") or []]
        check("B-post-cert-landing-covered", covered2 == ["t-a2"],
              json.dumps(covered2))
        check("B-certified-prefix", rng2.get("certified_prefix") ==
              [{"repo": "repo1", "revision": landed}], rng2.get("certified_prefix"))

        # --- C: the tick decision sees the landing ---
        yes, why = develop_certify.should_certify("change", rows3, "line-1",
                                                  guard_held=False)
        check("C-should-certify-range-non-empty", yes is True and why == "range_non_empty",
              "%r %r" % (yes, why))

        # --- D: the reader face answers from the new home ---
        check("D-has_landing-from-delivery-ledger",
              develop_line.has_landing(key, "t-a1", "line-1") is True,
              "has_landing returned a non-true answer")
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
