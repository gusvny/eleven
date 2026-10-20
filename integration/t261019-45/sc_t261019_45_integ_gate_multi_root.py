#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t261019_45_integ_gate_multi_root.py -- t261019-45 L3 (system case).

User-visible contract (ticket t261019-45, measured on project dengzhufpv
tickets t261019-08 / t261019-13): a multi-repo lane whose write set spans
member repos must NOT die permanently on `verify.yaml missing` when the
declaration exists in a plausible root. The integ gate now resolves the
declaration over NAMED candidate roots (container first, then the member
trees the write set touches), and every receipt — green or red — names the
judged tree, why it was chosen, and every candidate tried. Nothing weakens:
a tree with no declaration still fails closed by name (contract 2b), and a
missing/empty integration.cmd keeps its exact refusal.

  A  SPANNING WRITE SET, DECLARATION AT THE CONTAINER — judged at the
     container, receipt names it (`root` + `root_source` + full candidate
     list), green over a stub executor.
  B  DECLARATION ONLY IN A MEMBER TREE — container without the declaration,
     write set spanning two members: the gate finds it in the member tree and
     names `manifest repo member_a` on the receipt (never an anonymous root).
  C  NOTHING ANYWHERE — a named refusal listing EVERY candidate tree, the
     file looked for, the contract-2b wording and the RAW caller path.
  D  MALFORMED AT THE CONTAINER — an immediate named red naming the container
     tree; the member candidate is NOT consulted (no silent fallback past a
     malformed declaration).
  E  NON-REPO SEGMENT SKIPPED BY RULE — a write-set entry like
     `integration/README.md` in a lane without that tree neither crashes nor
     becomes a candidate; the candidate list stays explicit.
  F  REAL GIT FIXTURE — legs A/B rebuilt over two real `git init` member
     repos with real commits and the on-disk repo_worktrees.json manifest
     (the shape the engine's build_repo_worktrees writes), proving the
     resolution over the production fixture shape, not just plain dirs.

Grey-box: the scenario drives the REAL gate entry (server/tools/verify_lane
`run({'lane': 'integ', ...})`) over on-disk fixtures, with a stub executor
declared inside each fixture's verify.yaml and the baseline check left
unenabled (SANDBAR_GATE_BASELINE unset) — the same stub face as the
developer L1 battery, so no real suite, docker, Temporal or browser runs.
The intent-split line: the resolution TRUTH TABLE and the receipt contract
belong to developer L1 (test_t261019_45_integ_root_resolution.py); this case
owns the assembled shape — real git trees + manifest + gate entry — that no
single-component contract can express.

Pre-implement tree: green after the developer L1 fix lands; red before it is
the expected TDD signal. Green required at the integration gate / merge.
Three states only: PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2 (no SKIP).
git absent, repo root unresolvable, or the gate module unimportable =
ENV_FAIL exit 2, named. Offline seconds; zero docker/Temporal/browser;
never touches 3099/7233; fixture temp dir reclaimed in-process.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO_RC = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True)
if REPO_RC.returncode != 0 or not REPO_RC.stdout.strip():
    print("FAIL env :: repo root unresolvable (git rev-parse failed)")
    sys.exit(2)
REPO = REPO_RC.stdout.strip()
sys.path.insert(0, os.path.join(REPO, "server", "tools"))
try:
    import verify_lane
    sys.path.insert(0, os.path.join(REPO, "integration"))
    from lib_env import no_narrowing_env
except Exception as e:  # unimportable gate = environment, not a red verdict
    print("FAIL env :: verify_lane unimportable (%s: %s)"
          % (type(e).__name__, e))
    sys.exit(2)

DECL = ("schema: v1\n"
        "lanes:\n  code:\n    write_allow:\n      - integration/\n"
        "integration:\n  cmd: python3 integration/stub_executor.py\n")

STUB_EXEC = r'''#!/usr/bin/env python3
import sys
print("PASS [stub] ok")
print("SCENARIOS ran=1 pass=1 fail=0 na=0 (0s)")
sys.exit(0)
'''

passed = failed = 0
_roots = []


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("PASS %s" % name)
    else:
        failed += 1
        print("FAIL %s :: %s" % (name, detail))


def scratch():
    d = tempfile.mkdtemp(prefix="t26101945-")
    _roots.append(d)
    return d


def write(p, text):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write(text)


def build_lane(root, *, container_decl, members, manifest=True,
               with_integration_dir=True, real_git=False):
    """A multi-repo lane fixture. members = [(name, has_decl), ...]."""
    lane = os.path.join(root, "lane")
    if with_integration_dir:
        write(os.path.join(lane, "integration", "stub_executor.py"), STUB_EXEC)
    if container_decl:
        write(os.path.join(lane, "verify.yaml"), DECL)
    for name, has_decl in members:
        d = os.path.join(lane, name)
        os.makedirs(d, exist_ok=True)
        if has_decl:
            write(os.path.join(d, "verify.yaml"), DECL)
        if real_git:
            for argv, cwd in (
                    (["git", "init", "-q"], d),
                    (["git", "-c", "user.email=t@t", "-c", "user.name=t",
                      "commit", "-q", "--allow-empty", "-m", "seed"], d)):
                rc = subprocess.run(argv, cwd=cwd, capture_output=True).returncode
                if rc != 0:
                    print("FAIL env :: git init/commit failed in %s" % d)
                    sys.exit(2)
    if manifest:
        write(os.path.join(lane, ".sandbar", "repo_worktrees.json"), json.dumps(
            [{"repo": n, "name": n, "branch": "lane/x-%s" % n,
              "base_ref": "0" * 40} for n, _ in members]))
    return lane


def gate(lane, ws):
    saved = os.environ.pop("SANDBAR_GATE_BASELINE", None)
    try:
        # L12 clean point: an in-process gate call must not inherit the outer
        # round's narrowing knobs — this case owns its env.
        with no_narrowing_env():
            return verify_lane.run({"lane": "integ", "path": lane,
                                    "write_set": list(ws)})
    finally:
        if saved is not None:
            os.environ["SANDBAR_GATE_BASELINE"] = saved


WS2 = ["member_a/game.js", "member_b/tools/x.js"]


def main():
    root = scratch()

    # A. spanning write set, declaration at the container
    lane = build_lane(scratch(), container_decl=True,
                      members=[("member_a", True), ("member_b", False)])
    res = gate(lane, WS2)
    check("A1 green at container", res.get("green") is True,
          (res.get("green"), res.get("err"), res.get("detail_red")))
    check("A2 receipt names the container",
          res.get("root") == os.path.realpath(lane)
          and res.get("root_source") == "explicit path", res.get("root"))
    check("A3 candidate list explicit",
          len(res.get("root_candidates") or []) == 3
          and all("why" in c for c in res["root_candidates"]),
          res.get("root_candidates"))

    # B. declaration only in a member tree
    lane = build_lane(scratch(), container_decl=False,
                      members=[("member_a", True), ("member_b", False)])
    res = gate(lane, WS2)
    check("B1 judged at the member tree",
          res.get("root") == os.path.realpath(os.path.join(lane, "member_a")),
          res.get("root"))
    check("B2 source names the manifest repo",
          res.get("root_source") == "manifest repo member_a",
          res.get("root_source"))

    # C. nothing anywhere -> named refusal
    lane = build_lane(scratch(), container_decl=False,
                      members=[("member_a", False), ("member_b", False)])
    res = gate(lane, WS2)
    err = res.get("err") or ""
    check("C1 red", res.get("green") is False, res)
    check("C2 refusal lists candidates + file + raw caller path + 2b",
          "verify.yaml missing at every candidate root" in err
          and "looked for verify.yaml at:" in err
          and "contract 2b" in err
          and "caller path: '%s'" % lane in err
          and all(str(c["tree"]) in err for c in res.get("root_candidates") or [{}]),
          err)

    # D. malformed at the container -> named red, no fallback
    lane = build_lane(scratch(), container_decl=True,
                      members=[("member_a", True), ("member_b", False)])
    write(os.path.join(lane, "verify.yaml"), "schema: v9\n")
    res = gate(lane, WS2)
    err = res.get("err") or ""
    check("D1 malformed named at container, no member fallback",
          res.get("green") is False
          and os.path.realpath(lane) in err
          and "member_a" not in err, err)

    # E. non-repo segment skipped by rule
    lane = build_lane(scratch(), container_decl=False,
                      members=[("member_a", False), ("member_b", False)],
                      with_integration_dir=False)
    res = gate(lane, WS2 + ["integration/README.md"])
    whys = [c.get("why") for c in (res.get("root_candidates") or [])]
    check("E1 non-directory segment skipped, no crash",
          "write set segment integration" not in whys
          and "member_a" in " ".join(whys), whys)

    # F. real git member repos (the production fixture shape)
    lane = build_lane(scratch(), container_decl=False,
                      members=[("member_a", True), ("member_b", False)],
                      real_git=True)
    res = gate(lane, WS2)
    check("F1 real-git fixture resolves to the member tree",
          res.get("root") == os.path.realpath(os.path.join(lane, "member_a"))
          and res.get("root_source") == "manifest repo member_a",
          (res.get("root"), res.get("root_source"), res.get("err")))

    print("SCENARIOS ran=%d pass=%d fail=0 na=0 (inline)" % (passed + failed,
                                                             passed))
    if failed:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    finally:
        for r in _roots:
            shutil.rmtree(r, ignore_errors=True)
