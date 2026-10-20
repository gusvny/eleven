#!/usr/bin/env python3
"""sc_doc_mech_findings_contract.py — doc-face mechanical layer (M1-M7) end-to-end
contract over a fixture library (t261006-11, grey-box L3, offline seconds, zero
docker/Temporal/browser, never touches 3099).

User-perceivable contract under test (design notes/discussions/261004-docs-face-inspection-design.md
section 3): the daily doc-face period produces MECHANICAL findings with the SAME
shape as agent findings, governed by all three false-positive disciplines
(narrow by class / narrow the rules / explicit in-comment exemption), so the
panel/report/adjudication/dedupe pipes stay single-sourced.

Binding policy: the scenario talks ONLY to the public CLI
(`python3 server/engine/inspection_doc_mech.py --repo-root <root> [--base <ref> |
--no-diff]`, single-line JSON `{"ok":..., "result":{findings, meta}}`). One
transport-envelope level is unwrapped; a refactor that keeps the CLI contract
must not break this scenario. Diff-fed rules (M3/M5/M7) run through the CLI by
making the fixture a real git tree: base commit, then a planted change surface.

Fixture defects mirror today's measured drift (unregistered page, README path
drift) plus the retired-module lessons (S10 root-relative resolution, glob
tokens, historical-face exemption). Malformed inputs (broken index.json) are
injected per the external-input three-state hook: named degrade in meta, never
a crash, never a silent pass.

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


def run_cli(root, extra=None):
    """Run the mechanical layer CLI; returns (rc, result-or-None, stderr)."""
    cmd = [sys.executable, CLI, "--repo-root", root] + (extra or [])
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=180, cwd=ROOT)
    out = p.stdout.strip()
    parsed = None
    result = None
    if out:
        try:
            parsed = json.loads(out.splitlines()[-1])
        except ValueError:
            parsed = None
    if isinstance(parsed, dict) and "result" in parsed:
        result = parsed.get("result")
    else:
        result = parsed
    return p.returncode, result, p.stderr


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
    """Committed base library: docs/ (index.json + README + pages), notes/, src/."""
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
    # defect 7 (M1 machine leg): index.json with a ghost entry
    write(base, "docs/index.json", json.dumps({
        "docs": [
            {"path": "reference/alpha.md", "title": "Alpha"},
            {"path": "reference/beta.md", "title": "Beta"},
            {"path": "reference/globs.md", "title": "G"},
            {"path": "reference/rel.md", "title": "Rel"},
            {"path": "reference/exempt.md", "title": "E"},
            {"path": "reference/plan.md", "title": "P"},
            {"path": "reference/mentions.md", "title": "M"},
            {"path": "reference/no-fm.md", "title": "NF"},
            {"path": "design/hist.md", "title": "H"},
            {"path": "design/orphan.md", "title": "O"},
            {"path": "reference/ghost.md", "title": "Ghost"},
        ]
    }, indent=1))
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
    if shutil.which("git") is None:
        print("ENV_FAIL: git missing on PATH")
        return 2
    base = tempfile.mkdtemp(prefix="sc-doc-mech-")
    try:
        if build_base(base) is not None:
            print("ENV_FAIL: git init/commit failed in fixture tree")
            return 2
        apply_change_surface(base)
        rc, out, err = run_cli(base)
        ok(rc == 0 and isinstance(out, dict),
           "CLI exits 0 with single-line JSON over the fixture library (rc=%s err=%s)" % (rc, err[-200:]))
        if not isinstance(out, dict):
            print("FAIL named: no parseable JSON result; aborting deeper checks")
            return 1
        findings = out.get("findings", [])
        meta = out.get("meta", {})
        tags = scan_tags(findings)
        for fam in ("doc-m1-index", "doc-m1-readme", "doc-m1-frontmatter",
                    "doc-m2", "doc-m4", "doc-m6", "doc-m7"):
            ok(any(t.startswith(fam) for t in tags), "rule family fires: %s*" % fam)
        ok(any(f.get("scan", "").startswith("doc-m1")
               and any("unregistered.md" in ev.get("path", "") for ev in f.get("evidence", []))
               for f in findings),
           "M1 catches the unregistered page (today's measured drift)")

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

        # ---- malformed inputs: named degrade, never a crash ----
        with open(os.path.join(base, "docs", "index.json"), encoding="utf-8") as f:
            index_orig = f.read()
        write(base, "docs/index.json", "{not json at all")
        rc2, out2, err2 = run_cli(base)
        ok(rc2 == 0 and isinstance(out2, dict),
           "broken index.json degrades, exit stays 0 (rc=%s err=%s)" % (rc2, err2[-200:]))
        ok(any("index" in c.lower() for c in out2.get("meta", {}).get("caveats", [])),
           "the degrade is named in meta.caveats (=%s)" % out2.get("meta", {}).get("caveats"))
        write(base, "docs/index.json", index_orig)

        # ---- id stability across identical runs ----
        rc3, out3, _ = run_cli(base)
        tags3 = scan_tags(out3.get("findings", []))
        ok(tags == tags3, "two identical runs yield identical finding sets (deterministic order)")
        ids_a = sorted(f["id"] for f in findings)
        ids_b = sorted(f["id"] for f in out3.get("findings", []))
        ok(ids_a and ids_a == ids_b, "ids are content-minted and stable across periods")

        # ---- real-repo smoke: runs and returns well-formed output (behavior, not content) ----
        rc4, out4, err4 = run_cli(ROOT, ["--no-diff"])
        ok(rc4 == 0 and isinstance(out4, dict),
           "pointed at the real library (--no-diff) the layer runs clean and returns meta (rc=%s err=%s)" % (rc4, err4[-200:]))
    finally:
        shutil.rmtree(base, ignore_errors=True)

    print("\n%d ok / %d FAIL" % (PASS, FAIL))
    if FAILURES:
        print("FAIL named:")
        for f in FAILURES:
            print("  - %s" % f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
