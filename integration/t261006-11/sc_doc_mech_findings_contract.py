#!/usr/bin/env python3
"""sc_doc_mech_findings_contract.py — doc-face mechanical layer (M1-M7) end-to-end
contract over a fixture library (t261006-11, grey-box L3, offline seconds, zero
docker/Temporal/browser, never touches 3099).

User-perceivable contract under test (design notes/discussions/261004-docs-face-inspection-design.md
section 3): the daily doc-face period produces MECHANICAL findings with the SAME
shape as agent findings, governed by all three false-positive disciplines
(narrow by class / narrow the rules / explicit in-comment exemption), so the
panel/report/adjudication/dedupe pipes stay single-sourced.

Binding policy: the scenario talks ONLY to the two public CLI faces
(`python3 server/engine/inspection_doc_mech.py --repo-root <root> [--base <ref> |
--no-diff] [--project <key>] [--projects-root <dir>]`, and the index builder's
operator channel `python3 server/engine/docs_index.py --project <key>
--projects-root <dir>`), each printing single-line JSON `{"ok":..., "result":...}`.
One transport-envelope level is unwrapped; a refactor that keeps the CLI contract
must not break this scenario. Diff-fed rules (M3/M5/M7) run through the CLI by
making the fixture a real git tree: base commit, then a planted change surface.

WHERE THE INDEX LIVES (t261103-20 - do not re-plant it inside a repository)
--------------------------------------------------------------------------
The documentation index is DERIVED. It is built from the documents and written
into the project's own data directory, `<projects root>/<key>/data/docs/index.json`,
OUTSIDE every repository of the project (design
docs/design/project-docs-roots-v1.md goal 5). A copy of the index inside a
repository is never the truth, and the mechanical layer does not read one: a pass
with no project key reports the named state `unlocated` and judges no index leg at
all. So this scenario builds the real artefact for a TEMP project key against a
TEMP projects root (nothing is written into the real ~/.sandbar), and then drives
the mechanical layer with that project and that projects root - the same path
production uses. The index drift the fixture asserts (a page the index does not
list, a row whose file is gone) is injected into that derived artefact after the
real build, and the malformed-input leg breaks that same artefact.

Fixture defects mirror today's measured drift (unregistered page, ghost index row,
README path drift) plus the retired-module lessons (S10 root-relative resolution,
glob tokens, historical-face exemption). Malformed inputs (a broken derived index)
are injected per the external-input three-state hook: a degrade that NAMES the index
and its reason, never a crash, never a silent pass.

Run: python3 integration/t261006-11/sc_doc_mech_findings_contract.py  (cwd=repo root)
Exit: 0 pass / 1 fail (named) / 2 env (git missing).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CLI = os.path.join(ROOT, "server", "engine", "inspection_doc_mech.py")
INDEX_CLI = os.path.join(ROOT, "server", "engine", "docs_index.py")
#: The temp project key the fixture library is registered under (whitelisted shape).
KEY = "docmechfixture"

PASS = 0
FAIL = 0
FAILURES = []


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  %s" % label)
    else:
        FAIL += 1
        FAILURES.append(label)
        print("  FAIL %s" % label)


def _child_env(projects):
    """The child environment: the registry root is pinned to the TEMP projects root
    whenever one is in play, so no code path of the layer under test can reach the
    real ~/.sandbar by falling back to the default registry root."""
    env = dict(os.environ)
    if projects:
        env["SANDBAR_PROJECTS_DIR"] = projects
    return env


def _last_json(stdout):
    """The last stdout line as JSON (the CLI contract is one JSON line)."""
    out = (stdout or "").strip()
    if not out:
        return None
    try:
        return json.loads(out.splitlines()[-1])
    except ValueError:
        return None


def run_cli(root, extra=None, projects=None, project=""):
    """Run the mechanical layer CLI; returns (rc, result-or-None, stderr).

    `projects` + `project` point the index leg at the DERIVED index of that temp
    project: the same pair production passes, so the leg is exercised for real
    instead of being fed a copy inside the scanned repository."""
    cmd = [sys.executable, CLI, "--repo-root", root]
    if project:
        cmd += ["--project", project]
    if projects:
        cmd += ["--projects-root", projects]
    cmd += (extra or [])
    # SANCTIONED-WAIT: bounded child-process cap for an offline seconds-scale CLI, not a state wait
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=180, cwd=ROOT,
                       env=_child_env(projects))
    parsed = _last_json(p.stdout)
    if isinstance(parsed, dict) and "result" in parsed:
        result = parsed.get("result")
    else:
        result = parsed
    return p.returncode, result, p.stderr


def build_derived_index(projects, key):
    """Build the DERIVED index for `key` through the builder's operator channel;
    returns (rc, result-or-None, stderr). The result names the state it reached
    (`current` when the build succeeded)."""
    cmd = [sys.executable, INDEX_CLI, "--project", key, "--projects-root", projects]
    # SANCTIONED-WAIT: bounded child-process cap for an offline seconds-scale CLI, not a state wait
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=180, cwd=ROOT,
                       env=_child_env(projects))
    parsed = _last_json(p.stdout)
    if isinstance(parsed, dict) and "result" in parsed:
        return p.returncode, parsed.get("result"), p.stderr
    return p.returncode, parsed, p.stderr


def derived_index_path(projects, key):
    """Where the builder writes the index: the project data directory, outside every
    repository of the project."""
    return os.path.join(projects, key, "data", "docs", "index.json")


def write_project(projects, key, tree):
    """Register the fixture tree as `key` in the TEMP projects root, in the real
    declaration shape: the project entry names its root directory, and `paths` holds
    the documentation-root block every consumer resolves through."""
    write(projects, os.path.join(key, "project.yaml"),
          "schema: v1\n"
          "project:\n"
          "  - key: %s\n"
          "    name: %s\n"
          "    dirs:\n"
          "      - %s\n"
          "paths:\n"
          "  docs_roots:\n"
          "    - repository: .\n"
          "      path: docs\n" % (key, key, tree))


def inject_index_drift(projects, key):
    """Inject the measured drift into the DERIVED index and return its path.

    The index is a derived artefact, so a clean build registers every page and lists
    no ghost: the two defects M1 must catch are made by editing the artefact the
    layer reads (a page that exists but is not registered, and a row whose file is
    gone). Everything else - the build time, the roots, the schema - stays as the
    builder wrote it, so the reader still reports the index as current and the
    per-page comparison really runs."""
    path = derived_index_path(projects, key)
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    rows = [d for d in (payload.get("docs") or [])
            if not str(d.get("path") or "").endswith("unregistered.md")]
    if not rows:
        return path
    phantom = dict(rows[0])
    phantom["path"] = "reference/ghost.md"
    phantom["file"] = "ghost.md"
    phantom["title"] = "Ghost"
    phantom["id"] = "%s:reference/ghost.md" % (phantom.get("root") or ".:docs")
    rows.append(phantom)
    payload["docs"] = rows
    payload["total"] = len(rows)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1)
    return path


def write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def git(root, *args):
    return subprocess.run(["git", "-C", root] + list(args),
                          capture_output=True, text=True, timeout=60)


def scan_tags(findings):
    return sorted(f.get("scan", "") for f in findings)


FM = ("---\ntitle: %s\ncategory: reference\ntags: [t]\n"
      "status: active\nupdated: 2026-10-06\n---\n\n")


def build_base(base):
    """Committed base library: docs/ (README + pages), notes/, src/.

    No index is planted here: the index is a derived artefact and lives in the temp
    project data directory (see `write_project` / `build_derived_index`). A copy
    inside the repository is never the truth."""
    write(base, "docs/reference/alpha.md", FM % "Alpha" + "Alpha page.\n")
    # defect 1: exists on disk, registered NOWHERE (today's panel-list-conventions case)
    write(base, "docs/reference/unregistered.md", FM % "U" + "Body.\n")
    # defect 2: README lists beta.md under Root level while it lives in reference/
    # defect 3: README row for ghost.md whose file is gone
    write(base, "docs/README.md",
          "# Docs\n\n## Root level\n- `beta.md` — beta page\n\n"
          "## Reference\n- `reference/alpha.md` — alpha\n- `reference/ghost.md` — gone\n")
    write(base, "docs/reference/beta.md", FM % "Beta" + "See [alpha](alpha.md) and [gone](missing.md).\n")
    # defect 4: page with no frontmatter at all
    write(base, "docs/reference/no-fm.md", "No frontmatter here.\n")
    # S10 fixed resolution: a sibling backtick path resolves against the
    # document's OWN directory — must NOT fire. A root-shaped backtick path
    # (`src/...`) resolves against the repo root — must NOT fire.
    write(base, "docs/reference/rel.md", FM % "Rel" + "Sibling: `globs.md`. Root-shaped: `src/code.py`.\n")
    # narrow-the-rules: glob shapes are never paths — must NOT fire
    write(base, "docs/reference/globs.md", FM % "G" + "Types live in `*.d.ts` and `src/**/*.py`.\n")
    # narrow-by-class: historical face exempt from path drift — must NOT fire
    write(base, "docs/design/hist.md",
          "---\ntitle: H\ncategory: design\ntags: [t]\nstatus: deprecated\nupdated: 2026-01-01\n---\n"
          "Points at `reference/vanished.md` which is gone. Superseded by `reference/alpha.md`.\n")
    # defect 5 (M6): deprecated design page WITHOUT a supersede pointer — must fire
    write(base, "docs/design/orphan.md",
          "---\ntitle: O\ncategory: design\ntags: [t]\nstatus: deprecated\nupdated: 2026-01-01\n---\n"
          "Replaced, but nobody says by whom.\n")
    # explicit exemption: a hit declared legitimate — suppressed, counted
    write(base, "docs/reference/exempt.md",
          FM % "E" + "Fixed surface: [gone](missing-target.md)\n"
          "<!-- doc-exempt: doc-m2-unreachable -->\n")
    # notes/: M4 exempt (scratchpad by design)
    write(base, "notes/scratch.md", "- [ ] todo in scratch\n")
    # defect 6 (M4): progress list written into docs/ — must fire
    write(base, "docs/reference/plan.md", FM % "P" + "- [ ] finish this\n- [x] start this\n")
    # code surface a library page mentions (for the M7 must-check direction)
    write(base, "src/code.py", "value = 1\n")
    write(base, "docs/reference/mentions.md", FM % "M" + "Wired to `src/code.py`.\n")
    for args in (["init", "-q"], ["config", "user.email", "s@x"], ["config", "user.name", "s"],
                 ["add", "-A"], ["commit", "-qm", "base"]):
        r = git(base, *args)
        if r.returncode != 0:
            return r
    return None


def apply_change_surface(base):
    """The planted change surface: what the period diff looks like."""
    # M3: NEW line carrying CJK into docs/ (docs/ must be English STE)
    write(base, "docs/reference/alpha.md", FM % "Alpha" + "Alpha page.\n这行是新增中文\n")
    # M7 direction (b): a changed page naming a code surface that does not exist
    write(base, "docs/reference/mentions.md", FM % "M" + "Wired to `src/code.py` and `src/vanished.py`.\n")
    # M7 direction (a): the changed CODE file itself
    write(base, "src/code.py", "value = 2\n")
    # M5: NEW line naming a ticket id (existence predicates degrade via CLI — named caveat)
    write(base, "docs/reference/plan.md",
          FM % "P" + "- [ ] finish this\n- [x] start this\nSee `t999999-99` for details.\n")


def main():
    print("== sc_doc_mech_findings_contract (t261006-11, doc-face mechanical layer)")
    if not os.path.exists(CLI):
        ok(False, "mechanical layer CLI exists (red until implement lands)")
        print("FAIL named: %s missing" % CLI)
        return 1
    if not os.path.exists(INDEX_CLI):
        ok(False, "the derived index builder CLI exists (red until implement lands)")
        print("FAIL named: %s missing" % INDEX_CLI)
        return 1
    if shutil.which("git") is None:
        print("ENV_FAIL: git missing on PATH")
        return 2
    base = tempfile.mkdtemp(prefix="sc-doc-mech-")
    projects = ""
    try:
        if build_base(base) is not None:
            print("ENV_FAIL: git init/commit failed in fixture tree")
            return 2
        apply_change_surface(base)
        # ---- the DERIVED index for a TEMP project, against a TEMP projects root ----
        projects = tempfile.mkdtemp(prefix="sc-doc-mech-projects-")
        write_project(projects, KEY, base)
        brc, built, berr = build_derived_index(projects, KEY)
        built = built if isinstance(built, dict) else {}
        ok(brc == 0 and built.get("ok") is not False and built.get("state") == "current"
           and int(built.get("total") or 0) > 0,
           "the DERIVED index is built for the temp project (state=%s total=%s rc=%s err=%s)"
           % (built.get("state"), built.get("total"), brc, berr[-200:]))
        index_path = derived_index_path(projects, KEY)
        if os.path.exists(index_path):
            inject_index_drift(projects, KEY)
        else:
            ok(False, "the builder wrote the derived index into the project data directory (%s)"
                      % index_path)
        rc, out, err = run_cli(base, projects=projects, project=KEY)
        ok(rc == 0 and isinstance(out, dict),
           "CLI exits 0 with single-line JSON over the fixture library (rc=%s err=%s)" % (rc, err[-200:]))
        if not isinstance(out, dict):
            print("FAIL named: no parseable JSON result; aborting deeper checks")
            return 1
        findings = out.get("findings", [])
        meta = out.get("meta", {})
        tags = scan_tags(findings)
        index_state = meta.get("docs_index_state") or {}
        ok(index_state.get("state") == "current",
           "the index leg is judged against a CURRENT derived index (state=%s reason=%s)"
           % (index_state.get("state"), str(index_state.get("reason") or "")[:160]))
        state_path = str(index_state.get("path") or "")
        index_dir = os.path.dirname(index_path)
        ok(bool(state_path)
           and os.path.realpath(state_path) == os.path.realpath(index_dir)
           and os.path.realpath(state_path).startswith(os.path.realpath(projects) + os.sep)
           and not os.path.realpath(state_path).startswith(
               os.path.realpath(base) + os.sep),
           "the index leg reads the index home in the temp project data directory, "
           "outside the fixture repository (=%s)" % (state_path or "none"))
        for fam in ("doc-m1-index", "doc-m1-readme", "doc-m1-frontmatter",
                    "doc-m2", "doc-m4", "doc-m6", "doc-m7"):
            ok(any(t.startswith(fam) for t in tags), "rule family fires: %s*" % fam)
        ok(any(f.get("scan", "").startswith("doc-m1")
               and any("unregistered.md" in ev.get("path", "") for ev in f.get("evidence", []))
               for f in findings),
           "M1 catches the page the derived index does not register (today's measured drift)")
        ok(any(f.get("scan") == "doc-m1-index"
               and any("ghost.md" in (ev.get("path", "") + ev.get("quote", ""))
                       for ev in f.get("evidence", []))
               for f in findings),
           "M1 catches the ghost row of the derived index (a row whose file is gone)")

        # ---- a copy of the index inside the repository is not the truth ----
        # Regression against re-planting the index in the scanned tree: this scenario
        # used to write docs/index.json into the fixture and expect verdicts from it.
        # A copy that contradicts the derived artefact must change nothing.
        write(base, "docs/index.json", json.dumps(
            {"docs": [{"path": "reference/unregistered.md"}]}))
        rc_plant, out_plant, err_plant = run_cli(base, projects=projects, project=KEY)
        tags_plant = scan_tags((out_plant or {}).get("findings", []))
        ok(rc_plant == 0 and tags_plant == tags,
           "a copy of the index planted in the repository changes no verdict (the "
           "derived artefact is the only index read) — delta=%s"
           % (sorted(set(tags_plant) ^ set(tags))[:4],))
        os.remove(os.path.join(base, "docs", "index.json"))

        def hits(tag):
            return [f for f in findings if f.get("scan") == tag]

        # ---- output shape: single-sourced with agent findings ----
        shape_bad = []
        for f in findings:
            if f.get("severity") not in ("high", "med", "low"):
                shape_bad.append((f.get("scan"), "severity"))
            for k in ("subject", "why", "evidence"):
                if k not in f:
                    shape_bad.append((f.get("scan"), k))
            for ev in f.get("evidence", []):
                if not {"path", "line", "quote"} <= set(ev):
                    shape_bad.append((f.get("scan"), "evidence-keys"))
            if not f.get("id"):
                shape_bad.append((f.get("scan"), "id"))
        ok(not shape_bad, "every finding carries the agent shape (severity in vocab, subject/why/evidence{path,line,quote}/id) — bad=%s" % shape_bad[:4])

        # ---- narrow by class: the must-NOT-fire list ----
        hist = [f for f in findings if "hist.md" in f.get("subject", "")
                or any("hist.md" in ev.get("path", "") for ev in f.get("evidence", []))]
        ok(not hist, "historical face (docs/design) never fires path drift — hits=%s" % hist[:2])
        globs = [f for f in hits("doc-m2-unreachable")
                 if any("*.d.ts" in ev.get("quote", "") or "**" in ev.get("quote", "")
                        for ev in f.get("evidence", []))]
        ok(not globs, "glob shapes (*.d.ts, **) are never treated as paths — hits=%s" % globs[:2])
        rel = [f for f in findings if f.get("scan", "").startswith(("doc-m2", "doc-m5"))
               and any("rel.md" in ev.get("path", "") for ev in f.get("evidence", []))]
        ok(not rel, "fixed S10 resolution: a sibling path (`globs.md`) and a root-shaped path (`src/code.py`) named in docs/reference/rel.md do NOT fire — hits=%s" % rel[:2])
        scratch = [f for f in findings if f.get("scan") == "doc-m4-progress-list"
                   and "scratch.md" in f.get("subject", "")]
        ok(not scratch, "notes/ is exempt from M4 (scratchpad by design)")

        # ---- explicit exemption: auditable, never silent ----
        ex = [f for f in findings if "exempt.md" in f.get("subject", "")
              and f.get("scan") == "doc-m2-unreachable"]
        ok(not ex, "in-comment doc-exempt suppresses the declared hit")
        ok(bool(meta.get("exempted")),
           "suppressions are counted in meta.exempted (=%s), never silent" % meta.get("exempted"))

        # ---- M3: new lines only ----
        m3 = [f for f in findings if f.get("scan", "").startswith("doc-m3")]
        ok(any(any("alpha.md" in ev.get("path", "") for ev in f.get("evidence", []))
               for f in m3),
           "M3 fires on the diff-NEW CJK line in docs/ (hits=%d)" % len(m3))

        # ---- M7 both directions ----
        ok(any("code.py" in f.get("subject", "")
               or any("code.py" in ev.get("path", "") + ev.get("quote", "")
                      for ev in f.get("evidence", []))
               for f in hits("doc-m7-must-check")),
           "M7 emits a must-check pointer for the changed code surface mentioned by a page")
        ok(any("vanished.py" in json.dumps(f.get("evidence", [])) or "vanished.py" in f.get("subject", "")
               for f in findings if f.get("scan", "").startswith("doc-m7")),
           "M7 direction (b): the changed page naming a vanished surface is flagged")

        # ---- M5 degrade is NAMED, never a silent green ----
        ok(any("ticket" in c.lower() for c in meta.get("caveats", [])),
           "M5 ticket-existence degrade is named in meta.caveats (=%s)" % meta.get("caveats"))

        # ---- malformed derived index: NAMED degrade, never a crash, never vacuous ----
        # The leg breaks the artefact the layer actually reads (the temp project's
        # derived index), so it can only pass if the index leg really consults it. A
        # pass that would also come from a word inside an unrelated string is not a
        # test: the assertions below name the file, the state, the reason and the
        # finding the degrade produces.
        with open(index_path, encoding="utf-8") as f:
            index_orig = f.read()
        write(os.path.dirname(index_path), os.path.basename(index_path), "{not json at all")
        rc2, out2, err2 = run_cli(base, projects=projects, project=KEY)
        ok(rc2 == 0 and isinstance(out2, dict),
           "broken derived index degrades, exit stays 0 (rc=%s err=%s)" % (rc2, err2[-200:]))
        state2 = (out2 or {}).get("meta", {}).get("docs_index_state") or {}
        reason2 = str(state2.get("reason") or "")
        index_dir = os.path.dirname(index_path)
        named = [f for f in (out2 or {}).get("findings", [])
                 if f.get("scan") == "doc-m1-index"
                 and any(os.path.realpath(str(ev.get("path") or ""))
                         == os.path.realpath(index_dir)
                         for ev in f.get("evidence", []))]
        ok(state2.get("state") == "failed"
           and os.path.realpath(str(state2.get("path") or "")) == os.path.realpath(index_dir)
           and os.path.basename(index_path) in reason2
           and bool(named),
           "the degrade is NAMED: state=%s, the reason names the derived index and why it "
           "is unusable (=%s), and a doc-m1-index finding carries that index as evidence "
           "(hits=%d)" % (state2.get("state"), reason2[:200], len(named)))
        ok(not any("unregistered.md" in json.dumps(f.get("evidence", []))
                   for f in (out2 or {}).get("findings", [])),
           "while the derived index is unusable no page is reported unregistered (the "
           "finding names the index, never invents page drift)")
        write(os.path.dirname(index_path), os.path.basename(index_path), index_orig)

        # ---- id stability across identical runs ----
        rc3, out3, _ = run_cli(base, projects=projects, project=KEY)
        tags3 = scan_tags(out3.get("findings", []))
        ok(tags == tags3, "two identical runs yield identical finding sets (deterministic order)")
        ids_a = sorted(f["id"] for f in findings)
        ids_b = sorted(f["id"] for f in out3.get("findings", []))
        ok(ids_a and ids_a == ids_b, "ids are content-minted and stable across periods")

        # ---- real-repo smoke: runs and returns well-formed output (behavior, not content) ----
        rc4, out4, err4 = run_cli(ROOT, ["--no-diff"], projects=projects)
        ok(rc4 == 0 and isinstance(out4, dict),
           "pointed at the real library (--no-diff) the layer runs clean and returns meta (rc=%s err=%s)" % (rc4, err4[-200:]))
        ok(((out4 or {}).get("meta", {}).get("docs_index_state") or {}).get("state") == "unlocated",
           "with no project key the index leg reports the named state 'unlocated' (a copy "
           "inside a repository is never the truth)")

        # ---- hermetic: the temp project never reaches the real registry root ----
        ok(not os.path.exists(os.path.join(os.path.expanduser("~"), ".sandbar", "projects", KEY)),
           "nothing is written into the real ~/.sandbar (the temp project key does not exist there)")
    finally:
        shutil.rmtree(base, ignore_errors=True)
        if projects:
            shutil.rmtree(projects, ignore_errors=True)

    print("\n%d ok / %d FAIL" % (PASS, FAIL))
    if FAILURES:
        print("FAIL named:")
        for f in FAILURES:
            print("  - %s" % f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
