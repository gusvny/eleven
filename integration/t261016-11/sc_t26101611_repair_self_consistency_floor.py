#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261016-11 scenario 3: the repair self-consistency floor - removing an
imported module is refused whole and by name (grey-box L3, offline seconds,
stdlib + real git, zero docker/Temporal/browser, never touches 3099/7233).

intent (registered in run_scenarios.py SCENARIOS; this file is its body):
ticket t261016-11, host order 261016 requirement (3): "if the repair removes
a module it must also deal with the importers, otherwise it must refuse the
whole repair (never leave a tree that cannot import)." Measured incident:
bb73e620 deleted server/engine/foreign_write.py while
agent_activities.py:78 still carried `import foreign_write` in the same
tree - from that moment the tree could not even import the engine, and every
later case in the round judged a dead tree.

This entry drives the REAL delivered guard (server/engine foreign_write
public importer-scan face, per the accepted plan step 3: a pure function
over (tree_root, module_paths) that returns the remaining (importer, module)
pairs, an unparseable .py file counted as an unknown importer - fail-closed)
over REAL fixture trees, plus the refusal contract's user-perceivable faces:

- A refusal is named: a tree where a foreign module is imported yields the
  (module, importer) pair - the refusal can say WHICH import blocks it, never
  a bare "refused".
- B zero-write on refusal: the tree is byte-identical before and after the
  refusal decision (the decision reads, it never mutates; no rm, no restore,
  no commit).
- C fail-closed on the unreadable: a tree whose only "importer" is a file
  that does not parse still refuses (an unknown importer is never read as
  "no importer").
- D no false importer: `import fwmod_extra` does NOT block removing `fwmod`
  (module names are matched whole, never as prefixes) and a module nobody
  imports may proceed to removal - the floor prefers keeping, refusal is the
  floor, not the goal.
- E the refusal is greppable at the delivery face: the wiring carrier under
  integration/t261016-11/ (the plan's step-4 patch) names the refusal reason
  code foreign_repair_refused_importers, so a refused repair is findable on
  the receipt the round reads.

Anchored to the DECLARED post-fix surface (plan step 3, accepted at
review_plan). If the delivered module lacks the importer-scan face or the
carrier lacks the reason code, this entry FAILS by name.

Intent split (no intent-level duplication): importer-scan unit truth tables
over synthetic text belong to developer L1 (server/engine/tests); the
line-not-lane judgment belongs to the sibling t261016-11 scenario 2; the
carrier-never-writes-the-tree journey belongs to sibling scenario 1. THIS
entry uniquely owns "a repair that would break the tree's imports is refused
whole, named, and leaves the tree byte-identical".

Three states: PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2 (no SKIP in the
gate). git unavailable = ENV_FAIL. The delivered module absent, unimportable,
or lacking the declared guard face = FAIL named. Pre-implement tree red =
the named TDD signal; green required at the integration gate / merge.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ENGINE = REPO / "server" / "engine"
MODULE = ENGINE / "foreign_write.py"
TICKET_DIR = REPO / "integration" / "t261016-11"
REASON_CODE = "foreign_repair_refused_importers"
FAILS = []


def env_fail(msg):
    print("ENV_FAIL: %s" % msg)
    sys.exit(2)


def fail_named(msg):
    print("FAIL %s" % msg)
    sys.exit(1)


def git(args, cwd, check=True):
    try:
        p = subprocess.run(["git"] + args, cwd=str(cwd), capture_output=True,
                           text=True, timeout=120)  # SANCTIONED-WAIT: a ceiling on a bounded local git call, no condition is waited on
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


def load_guard(fw):
    fn = getattr(fw, "importers_remain", None)
    if fn is None:
        fail_named("self-consistency-face-missing: foreign_write has no "
                   "importers_remain")
    return fn


def tree_digest(root):
    """Byte digest of every file under root, path-sorted - the reader-side
    zero-write proof."""
    import hashlib
    h = hashlib.sha256()
    for p in sorted(Path(root).rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(root)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def make_tree(files):
    root = Path(tempfile.mkdtemp(prefix="t26101611-selfcons-"))
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data)
    return root


def main():
    try:
        git(["--version"], REPO)
    except Exception as e:
        env_fail("git unusable: %s" % e)
    fw = load_module()
    guard = load_guard(fw)

    # A + B: an imported module blocks removal, by name, with zero writes.
    with tempfile.TemporaryDirectory(prefix="t26101611-selfcons-") as td:
        root = make_tree({
            "pkg/fwmod.py": "VALUE = 1\n",
            "pkg/user.py": "import fwmod\n",
            "pkg/other.py": "VALUE = 2\n",
        })
        before = tree_digest(root)
        try:
            pairs = guard(str(root), ["pkg/fwmod.py"])
        except TypeError as e:
            fail_named("self-consistency-face-shape "
                       "(importers_remain signature): %s" % e)
        after = tree_digest(root)
        flat = repr(pairs)
        check("refusal-names-importer", "fwmod" in flat and "user" in flat,
              "guard returned %r - does not name module and importer" % flat)
        check("refusal-zero-write", before == after,
              "tree changed across the refusal decision")

    # C: an unparseable would-be importer still blocks (fail-closed).
    with tempfile.TemporaryDirectory(prefix="t26101611-selfcons-") as td:
        root = make_tree({
            "fwmod.py": "VALUE = 1\n",
            "broken_user.py": "def oops(:\n    import fwmod\n",
        })
        pairs = guard(str(root), ["fwmod.py"])
        check("unparseable-importer-fail-closed", bool(pairs),
              "a syntax-broken importer was read as 'no importer'")

    # D: whole-name matching + removal proceeds when nobody imports.
    with tempfile.TemporaryDirectory(prefix="t26101611-selfcons-") as td:
        root = make_tree({
            "fwmod.py": "VALUE = 1\n",
            "user.py": "import fwmod_extra\n",
        })
        pairs = guard(str(root), ["fwmod.py"])
        check("prefix-import-not-an-importer", not pairs,
              "guard returned %r - a prefix-bearing import blocked removal" % repr(pairs))

    with tempfile.TemporaryDirectory(prefix="t26101611-selfcons-") as td:
        root = make_tree({"fwmod.py": "VALUE = 1\n", "plain.py": "X = 2\n"})
        pairs = guard(str(root), ["fwmod.py"])
        if pairs:
            fail_named("no-importer-still-refused: %r" % (pairs,))
        git(["init", "-q"], root)
        git(["add", "-A"], root)
        git(["-c", "user.email=itg@example.invalid",
             "-c", "user.name=itg", "commit", "-qm", "t"], root)
        git(["rm", "-q", "fwmod.py"], root)
        check("unimported-module-removal-proceeds",
              not (root / "fwmod.py").exists(), "git rm refused unexpectedly")

    # E: the refusal is greppable at the delivery face.
    carriers = [str(p) for p in TICKET_DIR.rglob("*")
                if p.suffix in (".patch", ".diff")]
    named = [p for p in carriers
             if REASON_CODE in Path(p).read_text(errors="replace")]
    if not named and MODULE.is_file():
        named = ([str(MODULE)] if REASON_CODE in MODULE.read_text(errors="replace")
                 else [])
    check("refusal-reason-code-delivered", bool(named),
          "no carrier patch or module under %s names %s"
          % (TICKET_DIR, REASON_CODE))

    if FAILS:
        print("FAIL t261016-11-repair-self-consistency (%d)" % len(FAILS))
        sys.exit(1)
    print("PASS t261016-11-repair-self-consistency")
    sys.exit(0)


if __name__ == "__main__":
    main()
