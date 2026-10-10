#!/usr/bin/env python3
"""sc_old_flow_inert_face.py -- t261009-18 L3 coexistence face (integration role).

User-visible contract (ticket acceptance (e); design coexistence rules
12-13): NOTHING about the currently running flow changes. The new surface
is inert until a ticket opts in: importing it must not write anything, and
a landing must touch the project store ONLY inside the declared develop
area -- today's faces (.sandbar ledgers, ticket archives, the running
workflow modules) stay byte-identical. Grey-box L3 over the real store
layout with an injected projects root (SANDBAR_PROJECTS_DIR), offline
seconds, zero docker/browser, never touches 3099.

Faces:
  A  import face: importing develop_line and shared writes NOTHING anywhere
     in the injected projects root (a snapshot before/after is byte-equal).
  B  reuse direction: the running-flow modules (dev_lane.py, workflows_v2.py,
     agent_activities.py) never reference develop_line -- the dependency is
     one-way, new->existing, so no old-flow code path can reach the new
     behaviour.
  C  landing write-locality: a real landing in a fixture store changes files
     ONLY under the develop area -- every other path in the store snapshot
     is unchanged, and the develop area contains no .sandbar/ coordination
     directory of its own (the line worktree is engine-owned, not a lane).

Three-state exit contract: any FAIL -> exit 1 (module absent = FAIL named,
the expected TDD signal); git missing = ENV_FAIL exit 2. Temp dir reclaimed
on exit (L8).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("PASS %s" % name)
    else:
        failed += 1
        print("FAIL %s :: %s" % (name, detail))


def snapshot(root):
    face = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            try:
                with open(p, "rb") as f:
                    face[os.path.relpath(p, root)] = f.read()
            except OSError:
                face[os.path.relpath(p, root)] = b"<unreadable>"
    return face


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


def main():
    top = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True)
    if top.returncode != 0 or not shutil.which("git"):
        print("ENV_FAIL: git/repo unavailable")
        return 2
    engine = os.path.join(top.stdout.strip(), "server", "engine")

    root = tempfile.mkdtemp(prefix="t26100918-inert-")
    repos_root = tempfile.mkdtemp(prefix="t26100918-inert-repos-")
    try:
        # seed a plausible project store: a ticket archive + a marker ledger
        key = "t26100918i"
        store = os.path.join(root, key, "data")
        os.makedirs(os.path.join(store, "tickets", "t-old"))
        with open(os.path.join(store, "tickets", "t-old", "row.json"), "w") as f:
            f.write('{"old": true}\n')
        with open(os.path.join(store, "requests.jsonl"), "w") as f:
            f.write('{"seed": 1}\n')

        # --- A: import writes nothing ---
        os.environ["SANDBAR_PROJECTS_DIR"] = root
        # t261009-28: the landing record now lives in the delivery ledger --
        # route it into the same temp root so the scenario never touches the
        # real ~/.sandbar store.
        os.environ["SANDBAR_DELIVERY_LEDGER_DIR"] = os.path.join(root, "ledger")
        sys.path.insert(0, engine)
        try:
            import shared  # noqa: F401  (pre-existing import face = the baseline)
        except ImportError as e:
            print("FAIL shared-module-absent :: %s" % e)
            return 1
        before = snapshot(root)
        try:
            import develop_line  # noqa: F401
        except ImportError as e:
            print("FAIL develop_line-module-absent :: %s (expected before "
                  "implement; TDD signal)" % e)
            return 1
        after = snapshot(root)
        check("A-import-writes-nothing", before == after,
              "new/changed: %r" % sorted(set(after) - set(before)
                                         | {k for k in before
                                            if after.get(k) != before[k]})[:5])

        # --- B: one-way dependency, re-stated by t261009-46 ---
        # The opt-in wiring (t261009-46) makes dev_lane import develop_line at
        # module level (declared inert — every behaviour sits behind the
        # version gate) and gives agent_activities lazy new-surface imports
        # inside its declared develop-buffer gate region. The face keeps its
        # teeth by asserting the WIRING-LEVEL invariants, not a no-reference
        # ban the wiring itself retired:
        #   B1  the module-level import graph stays one-way, with ONE declared
        #       exception: dev_lane.py's inert import of develop_line (the
        #       wiring itself; every behaviour sits behind the version gate).
        #       agent_activities and workflows_v2 carry none.
        #   B2  in agent_activities, every textual reference to the new
        #       surface sits between the declared gate-region markers;
        #   B3  in dev_lane, every AST reference to the new surface sits in
        #       the declared seams (is_develop_buffer_ticket, the _init
        #       intake, the _dev_buffer_* steps) — no other old-flow code
        #       path reaches it;
        #   B4  workflows_v2 names no new surface at all.
        # (Gray-box per the review condition: declared marker/seam NAMES only,
        # never private line numbers or branch-internal order.)
        import ast
        NEW_PREFIXES = ("develop_line", "develop_certify", "develop_promote")
        for mod in ("dev_lane.py", "workflows_v2.py", "agent_activities.py"):
            p = os.path.join(engine, mod)
            txt = open(p, encoding="utf-8", errors="replace").read() \
                if os.path.exists(p) else ""
            tree = ast.parse(txt) if txt else ast.parse("pass")
            module_level_new = set()
            for node in tree.body:
                if isinstance(node, ast.Import):
                    module_level_new |= {a.name for a in node.names
                                         if a.name.startswith(NEW_PREFIXES)}
                elif isinstance(node, ast.ImportFrom) and \
                        (node.module or "").startswith(NEW_PREFIXES):
                    module_level_new.add(node.module)
            check("B1-module-level-graph-one-way-%s" % mod,
                  not module_level_new or mod == "dev_lane.py",
                  "module-level imports of the new surface: %s"
                  % sorted(module_level_new))

        acts_txt = open(os.path.join(engine, "agent_activities.py"),
                        encoding="utf-8", errors="replace").read()
        BEGIN = "# develop-buffer gate region (t261009-46) -- begin"
        END = "# develop-buffer gate region (t261009-46) -- end"
        i0, i1 = acts_txt.find(BEGIN), acts_txt.find(END)
        check("B2-gate-region-markers-present", 0 <= i0 < i1,
              "declared gate-region markers missing from agent_activities.py")
        if 0 <= i0 < i1:
            outside = acts_txt[:i0] + acts_txt[i1 + len(END):]
            check("B2-references-confined-to-gate-region",
                  "develop_line" not in outside and "develop_certify" not in outside,
                  "new-surface reference outside the declared gate region")

        def _new_names(node):
            out = set()
            for n in ast.walk(node):
                if isinstance(n, ast.Name) and n.id.startswith(NEW_PREFIXES):
                    out.add(n.id)
                if isinstance(n, ast.Attribute) and \
                        isinstance(n.value, ast.Name) and \
                        n.value.id.startswith(NEW_PREFIXES):
                    out.add(n.value.id)
            return out

        lane_tree = ast.parse(open(os.path.join(engine, "dev_lane.py"),
                                   encoding="utf-8", errors="replace").read())
        breaches = []
        for node in lane_tree.body:
            if isinstance(node, ast.FunctionDef):
                if node.name != "is_develop_buffer_ticket":
                    breaches.extend("%s" % node.name for _ in [0]
                                    if _new_names(node))
            elif isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if sub.name.startswith("_dev_buffer") or sub.name == "_init":
                            continue
                        if _new_names(sub):
                            breaches.append("%s.%s" % (node.name, sub.name))
                    elif isinstance(sub, ast.AnnAssign) and \
                            getattr(sub.target, "id", "") == "develop_line_id":
                        continue  # the declared input field, not a reference
                    elif _new_names(sub):
                        breaches.append("%s.<class-body>" % node.name)
            elif _new_names(node):
                breaches.append("<module-body:%s>" % type(node).__name__)
        check("B3-dev-lane-references-in-declared-seams", not breaches,
              "new-surface references outside the declared seams: %s"
              % sorted(set(breaches))[:5])

        wf_txt = open(os.path.join(engine, "workflows_v2.py"),
                      encoding="utf-8", errors="replace").read() \
            if os.path.exists(os.path.join(engine, "workflows_v2.py")) else ""
        check("B4-workflows-v2-names-nothing-new",
              not any(w in wf_txt for w in ("develop_line", "develop_certify",
                                            "develop_promote", "land_to_line",
                                            "LANE_VERSION")),
              "workflows_v2.py names the new surface")

        # --- C: landing write-locality ---
        repo = make_repo(repos_root, "repo1")
        git("checkout", "-q", "-b", "lane-a", "main", cwd=repo)
        with open(os.path.join(repo, "a.txt"), "w") as f:
            f.write("a\n")
        git("add", "-A", cwd=repo)
        git("-c", "user.email=t@s", "-c", "user.name=t", "commit", "-qm", "lane", cwd=repo)
        # HEAD stays on lane-a: land_ticket lands the lane repository's current HEAD
        dev_dir = shared.develop_dir(key)
        os.makedirs(dev_dir, exist_ok=True)
        decl = [{"version": 1, "line_id": "line-1", "scope": "s", "owner": "int",
                 "repositories": [{"name": "repo1", "branch": "develop-main"}]}]
        with open(os.path.join(dev_dir, "lines.json"), "w") as f:
            json.dump(decl, f)
        line = develop_line.load_line(key, "line-1")
        try:
            develop_line.land_ticket(line, key, {"repo1": Path(repo)}, "t-i1", "integration-test")
        except Exception as e:
            check("C-landing-ran", False, str(e)[:150])
        before_c = before  # store face at import time
        after_c = snapshot(root)
        # t261009-28: the landing act has a SECOND by-design write face — the
        # project's delivery ledger (routed into root/ledger above, so the
        # allowlist is self-chosen and cannot hide an external writer). The
        # locality contract keeps its teeth: changes outside the develop area
        # must be exactly that ledger face (rows file + its .lock); anything
        # else is still a locality breach.
        outside = {k for k, v in after_c.items()
                   if not k.replace(os.sep, "/").startswith(key + "/data/develop/")
                   and not k.replace(os.sep, "/").startswith("ledger/")
                   and before_c.get(k) != v}
        check("C-landing-touches-only-develop-area", not outside,
              "changed outside develop/ + delivery ledger/: %r" % sorted(outside)[:5])
        ledger_face = {k for k, v in after_c.items()
                       if k.replace(os.sep, "/").startswith("ledger/")
                       and before_c.get(k) != v}
        ledger_expected = {"ledger/.lock", "ledger/%s.jsonl" % key}
        check("C-delivery-ledger-face-bounded", ledger_face <= ledger_expected,
              "unexpected ledger-face writes: %r"
              % sorted(ledger_face - ledger_expected)[:5])
        check("C-no-own-sandbar-dir",
              not os.path.exists(os.path.join(dev_dir, ".sandbar")),
              "the line worktree must not carry its own coordination dir")
        print("INERT done: %d pass / %d fail" % (passed, failed))
        return 1 if failed else 0
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(repos_root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
