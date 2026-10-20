#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261016-11 scenario 2: the line is not a lane - landed line content is
never foreign (grey-box L3, offline seconds, stdlib + real git, zero
docker/Temporal/browser, never touches 3099/7233).

intent (registered in run_scenarios.py SCENARIOS; this file is its body):
ticket t261016-11, host order 261016 requirement (2): "the repair rule must
recognize that the LINE is not a lane - the line legitimately carries landed
content that main does not have yet, so 'absent on main' can never mean
'foreign, delete it' there." Measured incident: commit bb73e620 applied
"absent on the repair source -> git rm -f" inside a line round and deleted 7
paths / 1160 lines the candidate legitimately carried, leaving the importer
behind, so the tree could not even import the engine.

This entry drives the REAL delivered judgment (server/engine foreign_write)
over a REAL line-shaped git tree, the way the repair consumes it: a fixture
repo whose main branch lacks the content and whose line branch carries the
REAL blobs from the measured landing commit 496aa0c8, judged via the real
three-dot `git diff --name-status -z` parsed by the module's own parser.

- A line-carried paths are NOT foreign: every path from the measured
  bb73e620 deletion list, judged with the line candidate ref named, stays out
  of the foreign verdict (the line legitimately carries content main lacks).
- B the guard is not vacuous: the SAME tree judged WITHOUT a line candidate
  classifies exactly those paths foreign (positive control - if both arms
  agreed, A would prove nothing).
- C the judgment stays honest at the boundary: a line-only file whose content
  DIFFERS from the line ref tip is still foreign in the guarded arm (hash
  equality, never a name-based amnesty).
- D the incident set is real: the fixture's line-branch blob hash equals the
  hash read from 496aa0c8 in this repository, so the tree under judgment is
  the measured content, not a lookalike.

Anchored to the DECLARED post-fix surface (plan step 2, accepted at
review_plan; delivered blob verified): `foreign_files` accepts an injected
`line_owned` predicate, and the module ships `line_owned(path, own_hash,
blob_hash_of, line_refs)` - hash equality against line candidate refs, so a
path whose blob is byte-identical at a line ref is not foreign. If the
delivered module lacks that surface or behavior, this entry FAILS by name
(delivery incomplete, never an environment note).

Intent split (no intent-level duplication): the pure-function truth tables
(malformed refs, non-str paths, faulting hashers, parse tails) belong to
developer L1 (server/engine/tests); the carrier-cases-never-write-the-tree
journey belongs to the sibling t261016-11 carrier scenario; the
importer-refusal floor belongs to the sibling self-consistency scenario.
THIS entry uniquely owns "the real line-shaped diff over real landing blobs:
landed content survives the judgment".

Three states: PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2 (no SKIP in the
gate). git unavailable = ENV_FAIL. The delivered module absent, unimportable,
or lacking the declared line-not-lane surface = FAIL named. Pre-implement
tree red = the named TDD signal; green required at the integration gate /
merge.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "integration"))
from lib_env import clean_narrowing_env  # noqa: E402  (L12: git subprocesses run on a clean env - no inherited lane-round narrowing knob may touch the fixture judgment)

ENGINE = REPO / "server" / "engine"
LANDING = "496aa0c8"
MODULE = ENGINE / "foreign_write.py"

#: The measured bb73e620 deletion set (ticket spec MEASURED block, verbatim).
LINE_CARRIED = [
    "server/engine/foreign_write.py",
    "server/engine/tests/test_t261012_09_foreign_write_set.py",
    "integration/t261012-09/sc_t26101209_conflict_face_main_side.py",
    "integration/t261012-09/sc_t26101209_foreign_restore_merge_gate.py",
    "integration/run_scenarios.py",
    "integration/test_anchors.json",
    "server/engine/shared.py",
]
#: Out-of-set fixture write set: makes every LINE_CARRIED path a foreign
#: candidate under the unguarded rule, exactly the bb73e620 shape.
FIXTURE_WRITE_SET = ["docs/"]
#: A line-only file edited AFTER landing (differs from the ref tip).
EDITED = "server/engine/edited_after_landing.py"
FAILS = []


def env_fail(msg):
    print("ENV_FAIL: %s" % msg)
    sys.exit(2)


def fail_named(msg):
    print("FAIL %s" % msg)
    sys.exit(1)


def git(args, cwd, check=True, binary=False):
    try:
        p = subprocess.run(["git"] + args, cwd=str(cwd), env=clean_narrowing_env(),
                           capture_output=True, text=not binary, timeout=120)  # SANCTIONED-WAIT: a ceiling on a bounded local git call, no condition is waited on
    except OSError as e:
        env_fail("git unavailable: %s" % e)
    except subprocess.TimeoutExpired:
        env_fail("git %s exceeded 120s" % args[0])
    if check and p.returncode != 0:
        raise AssertionError("git %s: %s" % (" ".join(args),
                                             (p.stderr or p.stdout)[-300:]))
    return p.stdout


def check(name, cond, detail=""):
    if cond:
        print("ok %s" % name)
    else:
        FAILS.append(name)
        print("FAIL %s %s" % (name, detail))


def load_module():
    if not MODULE.is_file():
        fail_named("foreign_write-not-delivered: %s absent" % MODULE)
    sys.path.insert(0, str(ENGINE))
    try:
        import foreign_write as fw
        return fw
    except Exception as e:
        fail_named("foreign_write-unimportable: %s" % e)


def require_line_owned(fw):
    if not hasattr(fw, "line_owned"):
        fail_named("line-not-lane-surface-missing: foreign_write has no "
                   "line_owned predicate")
    return fw.line_owned


def build_fixture(root, fw):
    """main branch WITHOUT the content; line branch carrying the REAL
    496aa0c8 blobs plus one post-landing-edited file."""
    def w(rel, data):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    root.mkdir(parents=True, exist_ok=True)
    git(["init", "-q", "-b", "main"], root)
    git(["config", "user.email", "itg@example.invalid"], root)
    git(["config", "user.name", "itg-fixture"], root)
    w("docs/readme.md", b"main baseline\n")
    git(["add", "-A"], root)
    git(["commit", "-qm", "main base"], root)
    git(["checkout", "-qb", "line"], root)
    for rel in LINE_CARRIED:
        raw = git(["cat-file", "blob", "%s:%s" % (LANDING, rel)], REPO,
                  check=False, binary=True)
        if raw is None or (isinstance(raw, bytes) and not raw and
                           git(["cat-file", "-e", "%s:%s" % (LANDING, rel)],
                               REPO, check=False).returncode != 0):
            env_fail("landing blob unreadable: %s" % rel)
        w(rel, raw if isinstance(raw, bytes) else raw.encode())
    w(EDITED, git(["cat-file", "blob",
                   "%s:server/engine/shared.py" % LANDING], REPO, binary=True))
    git(["add", "-A"], root)
    git(["commit", "-qm", "line carries landed content"], root)
    # The residual shape (line_owned's documented boundary): a line-carried
    # file whose WORKING-TREE content was modified after landing - it differs
    # from the line ref tip, so the tip-hash guard must not amnesty it.
    (root / EDITED).write_bytes(
        git(["cat-file", "blob",
             "%s:server/engine/shared.py" % LANDING], REPO, binary=True)
        + b"\n# edited after landing\n")


def changed_paths(root, fw):
    base = git(["merge-base", "main", "line"], root).strip()
    z = git(["diff", "--name-status", "-z", "%s...line" % base], root)
    pairs = fw.parse_name_status_z(z)
    return [p for _st, p in pairs]


def blob_hash_of(root, path, ref):
    out = git(["rev-parse", "%s:%s" % (ref, path)], root, check=False).strip()
    return out or None


def judged(root, fw, guarded, extra=()):
    """Run the real judgment the way the repair does: real three-dot -z diff
    parsed by the module's own parser; the guarded arm injects the delivered
    line_owned predicate fed by real git blob lookups."""
    paths = changed_paths(root, fw) + list(extra)
    if not guarded:
        return set(fw.foreign_files(paths, write_set=FIXTURE_WRITE_SET))
    def pred(p):
        own = git(["hash-object", str(root / p)], root, check=False).strip()
        return fw.line_owned(
            p, own,
            lambda path, ref: blob_hash_of(root, path, ref),
            ["line"])
    return set(fw.foreign_files(paths, write_set=FIXTURE_WRITE_SET,
                                line_owned=pred))


def main():
    try:
        git(["--version"], REPO)
    except Exception as e:
        env_fail("git unusable: %s" % e)
    if git(["cat-file", "-t", LANDING], REPO, check=False).strip() != "commit":
        env_fail("landing commit %s not reachable in this clone" % LANDING)
    fw = load_module()
    require_line_owned(fw)

    with tempfile.TemporaryDirectory(prefix="t26101611-line-tree-") as td:
        root = Path(td) / "repo"
        build_fixture(root, fw)

        guarded = judged(root, fw, True, extra=[EDITED])
        unguarded = judged(root, fw, False)
        escaped = [p for p in LINE_CARRIED if p in guarded]
        check("line-carried-content-kept", not escaped,
              "judged foreign under line guard: %s" % escaped)
        missing = [p for p in LINE_CARRIED if p not in unguarded]
        check("guard-not-vacuous", not missing,
              "without a line candidate these stayed unjudged: %s" % missing)
        check("hash-boundary-honest", EDITED in guarded,
              "edited-after-landing file escaped the foreign verdict")
        landed = git(["rev-parse", "%s:%s" % (LANDING, LINE_CARRIED[0])],
                     REPO).strip()
        fixture = git(["rev-parse", "line:%s" % LINE_CARRIED[0]], root).strip()
        check("fixture-is-measured-content", landed == fixture,
              "blob mismatch landing=%s fixture=%s" % (landed, fixture))

    if FAILS:
        print("FAIL t261016-11-line-not-lane (%d)" % len(FAILS))
        sys.exit(1)
    print("PASS t261016-11-line-not-lane")
    sys.exit(0)


if __name__ == "__main__":
    main()
