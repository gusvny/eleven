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
     behaviour. Since t261101-15 the module carries TWO declared seams: the
     develop-buffer gate region (t261009-46) and the activity-time
     declared-line seam (t261031-43, whose legacy merge-phase hand-off is a
     host-ruled design change, not a leak). The second one is declared by
     markers, source-locked to a named symbol list, and the hand-off points
     outside it are declared one by one with a count lock. Four injected
     violations prove the guard still bites.
  C  landing write-locality: a real landing in a fixture store changes files
     ONLY under the develop area -- every other path in the store snapshot
     is unchanged, and the develop area contains no .sandbar/ coordination
     directory of its own (the line worktree is engine-owned, not a lane).

Three-state exit contract: any FAIL -> exit 1 (module absent = FAIL named,
the expected TDD signal); git missing = ENV_FAIL exit 2. Temp dir reclaimed
on exit (L8).
"""
import ast
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tokenize
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


# ---- face B2: the declared new-surface seams of agent_activities.py -----------
# t261101-15. The module declares TWO seams for the new surface:
#   S1 the develop-buffer gate region (t261009-46): the opt-in activities. No
#      legacy ticket ever executes it.
#   S2 the activity-time declared-line seam (t261031-43, delivered by t261101-05):
#      the LEGACY merge phase resolves the ticket's declared develop line at
#      activity time and hands it to its two faces. Host ruling 261031-43 makes
#      the legacy merge phase judge line-landed content, so S2 is a design change
#      and cannot live inside S1 (S1 is by declaration reachable only behind the
#      develop-buffer version gate, which a legacy merge_check never passes).
# S2 is therefore declared the same way S1 is - by name, not by line number:
#   * a marker region, source-locked in BOTH directions: every module-level
#     symbol inside it is on the declared list and every declared symbol is
#     inside it (the region cannot be emptied, and cannot silently grow);
#   * the region may not swallow the merge-path cores (an old-flow body parked
#     inside the region would silence the guard);
#   * outside both regions exactly three hand-off points are lawful, each with a
#     count lock: one resolver entry called once inside merge_check before the
#     per-scope loop, and one read of the RECORDED field per face inside
#     _merge_check_one_scope (the replay lock t261031-43 delivered).
# Everything else that names the surface outside the seams still reds.
GATE_BEGIN = "# develop-buffer gate region (t261009-46) -- begin"
GATE_END = "# develop-buffer gate region (t261009-46) -- end"
SEAM_BEGIN = "# activity-time declared-line seam (t261031-43) -- begin"
SEAM_END = "# activity-time declared-line seam (t261031-43) -- end"
#: S2's module-level symbols, locked in both directions.
SEAM_SYMBOLS = frozenset((
    "DEVELOP_LINE_SOURCE_LIVE_META",
    "DEVELOP_LINE_SOURCE_RECORDED",
    "DEVELOP_LINE_RESOLUTION_ID",
    "DEVELOP_LINE_LIVE_META_TIMEOUT_SEC",
    "_develop_line_precedence",
    "_develop_line_declaration_probe",
    "_read_ticket_live_meta",
    "_develop_line_face_note",
    "_resolve_merge_check_develop_line",
    "_merge_args_with_resolved_line",
    "_line_face_on_fault",
    "_line_resolution_receipt_row",
))
#: the one declared resolver hand-off (name level, called once per merge_check).
RESOLVER_HANDOFF = "_resolve_merge_check_develop_line"
#: the declared recorded-field read each face keeps (the t261031-43 replay lock).
RECORDED_FIELD_READ = 'getattr(args, "develop_line", "")'
#: old-flow cores the seam region must never swallow.
MERGE_PATH_CORES = ("async def merge_check(",
                    "async def _merge_check_one_scope(")
NEW_SURFACE_NAMES = ("develop_line", "develop_certify")


def b2_verdicts(acts_txt):
    """Judge face B2 on one source text. Returns [(check name, ok, detail)].

    Pure text/AST over the module, so the same function judges the real source and
    the injected violations below (the guard's teeth are proved, not assumed):
    blank the two declared regions with the line count preserved, strip comments
    and docstrings, then every remaining reference to the new surface must be one
    of the declared hand-off points. Prose never passes and a real reference never
    hides in a comment.
    """
    lines = acts_txt.splitlines()
    out = []

    def v(name, ok, detail=""):
        out.append((name, ok, detail))

    def span(begin, end):
        first, last = acts_txt.find(begin), acts_txt.find(end)
        if acts_txt.count(begin) != 1 or acts_txt.count(end) != 1 \
                or not 0 <= first < last:
            return None
        return (acts_txt.count("\n", 0, first),
                acts_txt.count("\n", 0, last + len(end)))

    gate = span(GATE_BEGIN, GATE_END)
    v("B2-gate-region-markers-present", gate is not None,
      "the develop-buffer gate-region markers must appear exactly once, begin "
      "before end, in agent_activities.py")
    seam = span(SEAM_BEGIN, SEAM_END)
    v("B2-seam-region-markers-present", seam is not None,
      "the declared-line seam markers (t261031-43) must appear exactly once, begin "
      "before end, in agent_activities.py")
    if gate is None or seam is None:
        return out  # fail-closed: no declaration, no containment judgement
    if not (gate[1] <= seam[0] or seam[1] <= gate[0]):
        v("B2-declared-seams-do-not-overlap", False,
          "the declared regions overlap (gate %r / seam %r)" % (gate, seam))
        return out

    seam_txt = "\n".join(lines[seam[0]:seam[1]])
    try:
        seam_tree = ast.parse(seam_txt)
    except SyntaxError as e:
        seam_tree = None
        v("B2-seam-source-lock", False,
          "the seam region does not parse as a module: %s" % e)
    if seam_tree is not None:
        names = set()
        for node in seam_tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                names.update(t.id for t in node.targets if isinstance(t, ast.Name))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names.add(node.target.id)
        v("B2-seam-source-lock", names == set(SEAM_SYMBOLS),
          "the seam's module-level symbols must equal the declared list "
          "(missing: %s; undeclared: %s)"
          % (sorted(set(SEAM_SYMBOLS) - names), sorted(names - set(SEAM_SYMBOLS))))
        swallowed = [core for core in MERGE_PATH_CORES if core in seam_txt]
        v("B2-seam-excludes-the-merge-path-cores", not swallowed,
          "an old-flow core sits inside the seam region, so the region is widened "
          "past its declaration: %s" % swallowed)

    region_lines = set(range(*gate)) | set(range(*seam))
    # blank the regions on WHOLE lines (the declaration spans top-level
    # statements), so the line count survives and every hit keeps its line number
    masked = ["" if i in region_lines else ln for i, ln in enumerate(lines)]
    text = "\n".join(masked)
    judged_lines = list(lines)
    doc_lines = set()
    try:
        # Comments are cut from their OWN line, never dropped with it: code that
        # carries a trailing comment is still code (t261101-15 - the injected
        # proof caught the earlier whole-line drop as a hole).
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                n, col = tok.start
                if 1 <= n <= len(judged_lines):
                    ln = judged_lines[n - 1]
                    judged_lines[n - 1] = ln[:col] + ln[tok.end[1]:]
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if (isinstance(node, (ast.Module, ast.FunctionDef,
                                 ast.AsyncFunctionDef, ast.ClassDef))
                    and node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                doc_lines.update(range(node.body[0].lineno,
                                       (node.body[0].end_lineno
                                        or node.body[0].lineno) + 1))
    except (tokenize.TokenError, SyntaxError):
        judged_lines, doc_lines = list(lines), set()  # raw text, fail-closed

    calls, faces = [], []
    undeclared = []
    for i, ln in enumerate(judged_lines, 1):
        if (i - 1) in region_lines or i in doc_lines:
            continue
        if not any(w in ln for w in NEW_SURFACE_NAMES):
            continue
        if RESOLVER_HANDOFF in ln:
            calls.append((i, ln.strip()))
        elif RECORDED_FIELD_READ in ln:
            faces.append((i, ln.strip()))
        else:
            undeclared.append((i, ln.strip()))
    v("B2-references-confined-to-gate-region", not undeclared,
      "new-surface reference outside the declared seams (line: text): %r"
      % (undeclared[:5],))

    def def_line(prefix):
        for i, ln in enumerate(lines, 1):
            if ln.startswith(prefix):
                return i
        return 0

    scope_def = def_line("async def _merge_check_one_scope(")
    merge_def = def_line("async def merge_check(")
    loop_line = 0
    for i, ln in enumerate(lines, 1):
        if i > merge_def and ln.strip() == "for sc in scopes:":
            loop_line = i
            break
    v("B2-handoff-resolver-called-once-per-call",
      len(calls) == 1 and merge_def > 0 and merge_def < calls[0][0] < loop_line,
      "the resolver entry must be declared exactly once, inside merge_check and "
      "before the per-scope loop (resolver lines: %r; merge_check line %s; scope "
      "loop line %s)" % ([c[0] for c in calls], merge_def, loop_line))
    v("B2-handoff-recorded-field-read-once-per-face",
      len(faces) == 2 and scope_def > 0
      and all(scope_def < n < merge_def for n, _ in faces),
      "each face must read the recorded field exactly once, inside "
      "_merge_check_one_scope (field-read lines: %r; scope core line %s; "
      "merge_check line %s)" % ([f[0] for f in faces], scope_def, merge_def))
    return out


def b2_injections():
    """(label, expected red check, builder) - the guard's teeth, proved.

    Each builder applies ONE violation to a copy of the real source text; the
    caller judges it through b2_verdicts, the same path as the real file. A source
    change that removes an anchor raises ValueError, and the caller reds that proof
    by name - never a silent skip.
    """
    def import_in_an_old_flow_body(src):
        merge_pos = src.index("async def merge_check(")
        loop_pos = src.index("\n    for sc in scopes:\n", merge_pos) + 1
        return (src[:loop_pos] + "    import develop_line  # injected violation\n"
                + src[loop_pos:])

    def extra_face_field_read(src):
        face_pos = src.index('line_id=str(%s or "")' % RECORDED_FIELD_READ)
        face_eol = src.index("\n", face_pos) + 1
        return (src[:face_eol]
                + '        injected_line = str(%s or "")\n' % RECORDED_FIELD_READ
                + src[face_eol:])

    def symbol_added_inside_the_seam(src):
        pos = src.index(SEAM_END)
        return (src[:pos] + "def _injected_helper():\n    return 1\n\n\n"
                + src[pos:])

    def reference_outside_both_regions(src):
        return src + "\n_INJECTED_REF = develop_certify.read_rows\n"

    return [
        ("import-inside-an-old-flow-body",
         "B2-references-confined-to-gate-region", import_in_an_old_flow_body),
        ("extra-face-field-read",
         "B2-handoff-recorded-field-read-once-per-face", extra_face_field_read),
        ("symbol-added-inside-the-seam",
         "B2-seam-source-lock", symbol_added_inside_the_seam),
        ("reference-outside-both-regions",
         "B2-references-confined-to-gate-region", reference_outside_both_regions),
    ]


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
        #       surface sits in one of the TWO declared seams: the gate-region
        #       markers, and (t261101-15) the activity-time declared-line seam
        #       whose region is source-locked to a named symbol list and whose
        #       hand-off points outside it are declared one by one with a count
        #       lock — see b2_verdicts above, which also judges four injected
        #       violations so the guard's teeth are proved, not assumed;
        #   B3  in dev_lane, every AST reference to the new surface sits in
        #       the declared seams (is_develop_buffer_ticket, the _init
        #       intake, the _dev_buffer_* steps, and since t261019-02 the
        #       close-out guard seam: the pure module-level decision core
        #       line_landing_closeout_verdict + the workflow method
        #       _line_landing_closeout_guard — host ruling 261019 lawfully
        #       makes the LEGACY merge phase consult the line landing
        #       records; the seam is version-gated behind
        #       LINE_LANDING_CLOSEOUT_GUARD_PATCH_ID, call-site order pinned
        #       by t261019-02-line-landing-closeout-guard leg G) — no other
        #       old-flow code path reaches it;
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
        for _name, _ok, _detail in b2_verdicts(acts_txt):
            check(_name, _ok, _detail)
        # The guard's teeth, proved on the same code path: each injected violation
        # of the real source text must red its declared check. An anchor that the
        # source no longer carries reds the proof by name - never a silent skip.
        for _label, _expect, _build in b2_injections():
            try:
                _mutant = _build(acts_txt)
            except ValueError as e:
                check("B2-self-proof-%s-reds" % _label, False,
                      "the injection anchor is gone from the source: %s" % e)
                continue
            _red = [n for n, ok, _d in b2_verdicts(_mutant) if not ok]
            check("B2-self-proof-%s-reds" % _label, _expect in _red,
                  "the injected violation must red %s (red checks: %r)"
                  % (_expect, _red))

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
        # Declared seams (t261019-02, host ruling 261019): the close-out
        # guard — the pure module-level decision core and the one workflow
        # method that raises the named block — lawfully read the new surface
        # on the LEGACY merge phase, version-gated (see the B3 docstring).
        GUARD_CORE_FN = "line_landing_closeout_verdict"
        GUARD_METHOD = "_line_landing_closeout_guard"
        for node in lane_tree.body:
            if isinstance(node, ast.FunctionDef):
                if node.name not in ("is_develop_buffer_ticket", GUARD_CORE_FN):
                    breaches.extend("%s" % node.name for _ in [0]
                                    if _new_names(node))
            elif isinstance(node, ast.ClassDef):
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if sub.name.startswith("_dev_buffer") or sub.name in ("_init", GUARD_METHOD):
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
