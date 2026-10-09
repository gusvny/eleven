#!/usr/bin/env python3
"""sc_line_declaration_contract.py -- t261009-18 L2 contract face (integration role).

User-visible contract (ticket acceptance (a)(d); design goals 5/18/19; the
fact-ledger loud-failure rule): a line EXISTS as a declared thing, and a
broken declaration is refused BY NAME -- never an empty default, never a
guessed line. The extra proof set is read from the declaration / the
declared inventory (may legitimately be empty today) -- never a hand-kept
list in the module. Grey-box L2: the declaration reader's public face over
real store files, offline seconds, zero docker/browser, never touches 3099.

Faces:
  A  absent lines.json -> a named error, not an empty list (KI-188 family:
     an unreadable ledger must not become "nothing known").
  B  malformed JSON -> named error, file path in the message.
  C  unknown shape version -> named error.
  D  two lines claiming the same (repository, branch) -> refused by name
     (branch is never a line's identity, goal 19; a shared branch would
     make the linear-history promise undefinable).
  E  a lawful multi-repository declaration loads -- the set shape is real,
     not a single-repo assumption (goal 18).
  F  the extra proof set: an empty declaration yields an EMPTY set (the
     T0.3 hand-off is legal), and the module carries no hard-coded
     scenario-name list (goal 5: one inventory, two uses).

Three-state exit contract: any FAIL -> exit 1 (module absent = FAIL named,
the expected TDD signal); python/repo missing = ENV_FAIL exit 2. Temp dir
reclaimed on exit (L8).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("PASS %s" % name)
    else:
        failed += 1
        print("FAIL %s :: %s" % (name, detail))


def write_decl(dev_dir, obj):
    with open(os.path.join(dev_dir, "lines.json"), "w") as f:
        f.write(obj if isinstance(obj, str) else json.dumps(obj))


def tries_loud(fn):
    """True if fn raises a named (non-empty message) error."""
    try:
        fn()
        return False, ""
    except Exception as e:
        return True, str(e)


def main():
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True)
    if top.returncode != 0 or not shutil.which("python3"):
        print("ENV_FAIL: git/python unavailable")
        return 2
    engine = os.path.join(top.stdout.strip(), "server", "engine")
    if not os.path.isdir(engine):
        print("FAIL develop_line-module-absent :: server/engine missing (TDD signal)")
        return 1
    sys.path.insert(0, engine)
    try:
        import develop_line  # noqa: F401
        import shared
    except ImportError as e:
        print("FAIL develop_line-module-absent :: %s (expected before implement; "
              "TDD signal)" % e)
        return 1

    root = tempfile.mkdtemp(prefix="t26100918-decl-")
    try:
        os.environ["SANDBAR_PROJECTS_DIR"] = root
        key = "t26100918d"
        dev_dir = shared.develop_dir(key)
        os.makedirs(dev_dir, exist_ok=True)
        load = lambda: develop_line.load_lines(key)

        # A: absent declaration
        loud, msg = tries_loud(load)
        check("A-absent-named-error", loud and bool(msg.strip()), "loud=%s" % loud)

        # B: malformed JSON
        write_decl(dev_dir, "{not json")
        loud, msg = tries_loud(load)
        check("B-malformed-named-error", loud and "lines.json" in msg, msg[:150])

        # C: unknown shape version
        write_decl(dev_dir, {"version": 999, "line_id": "l", "scope": "s",
                             "owner": "o", "repositories": []})
        loud, msg = tries_loud(load)
        check("C-unknown-version-named", loud and bool(msg.strip()), msg[:150])

        # D: two lines on the same (repo, branch)
        d1 = {"version": 1, "line_id": "line-1", "scope": "s", "owner": "o",
              "repositories": [{"name": "r", "branch": "develop-x"}]}
        d2 = dict(d1, line_id="line-2")
        write_decl(dev_dir, [d1, d2])
        loud, msg = tries_loud(load)
        check("D-duplicate-branch-refused", loud and bool(msg.strip()), msg[:150])

        # E: lawful multi-repo declaration loads
        ok = {"version": 1, "line_id": "line-1", "scope": "slice", "owner": "int",
              "repositories": [{"name": "r1", "branch": "develop-a"},
                               {"name": "r2", "branch": "develop-b"}]}
        write_decl(dev_dir, [ok])
        try:
            lines = load()
            line = lines.get("line-1")
            names = [r.name for r in getattr(line, "repositories", [])]
            check("E-multirepo-shape-loads",
                  sorted(names) == ["r1", "r2"] and line.line_id
                  != line.repositories[0].branch,
                  "line_id must not be the branch (goal 19); names=%r" % names)
        except Exception as e:
            check("E-multirepo-shape-loads", False, str(e)[:150])

        # F: extra set from declaration, never hard-coded
        try:
            empty = develop_line.extra_scenarios(lines["line-1"], None)
            check("F-extra-set-empty-legal", list(empty) == [], repr(empty)[:100])
        except Exception as e:
            check("F-extra-set-empty-legal", False, str(e)[:150])
        src = open(os.path.join(engine, "develop_line.py")).read()
        literals = re.findall(r'["\'](sc_[a-z0-9_]+|[a-z0-9-]+-faces)["\']', src)
        check("F-no-hardcoded-scenario-names", not literals, str(literals[:5]))
        print("DECL done: %d pass / %d fail" % (passed, failed))
        return 1 if failed else 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
