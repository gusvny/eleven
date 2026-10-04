#!/usr/bin/env python3
"""Main-sync conflict-resolution context carries the red line + parse-level
self-check contract (t261004-35, grey-box L3, offline seconds, zero docker /
Temporal / network / subprocess, never touches 3099).

User-visible contract under test (host order 261004): when the engine hands a
main-sync merge conflict to the lane agent, the context text it hands over must
itself carry (a) the forbidden-integration red line — naming the same entries
the settle scan enforces, with the whole-round-fail consequence — and (b) the
parse-level self-check recipe (python syntax, JSON validity, git diff --check,
node --check), never by running the suite; and must keep the existing clauses
(resolve file by file, touch only the conflicted files, do NOT commit). This is
the measured gap of t261004-29: the lane ran the scenario runner to self-check
and the settle scan failed the whole round, discarding a correct resolution.

Legs:
  A  light lane: the English conflict-context text the agent receives (the
     LIGHT_MAIN_SYNC_TEXTS["conflict_ctx"] block) carries both new clauses and
     keeps the preserved ones; its entry list is a rendered placeholder filled
     by the dev-lane render (same source as the matcher).
  B  dev lane (the default lane, the one that failed on t261004-29): the
     conflict-context text carries the same clauses in the Chinese historical
     text, and names every entry declared by FORBIDDEN_ENTRIES.
  C  same-source: the entry list in the prompt is rendered from
     FORBIDDEN_ENTRIES (not hand-written), so a rename/addition on the
     enforcement side lands in the prompt in the same batch.
  D  red line not weakened, guidance does not self-incriminate: the public
     enforcement matcher still flags `python3 integration/run_scenarios.py`
     (also through sh -c recursion) and each other declared entry, while every
     self-check command the prompt recommends (`python3 -m py_compile`,
     `python3 -m json.tool`, `git diff --check`, `node --check`) scans clean.

Binding note (declared, grey-box): legs A/B assert against the prompt-text
blocks in the engine source — these blocks are the literal strings handed to
the agent, but they live inline (dev lane) / in a module dict whose import
pulls temporalio (light lane), so the scenario reads the text rather than
importing the workflow. If a later ticket lifts the texts to an importable
seam, this scenario should switch to rendering it; that rewrite is a test
obligation, not an engine failure.

Pre-implement this scenario is red (TDD signal: the clauses do not exist yet);
it must be green at arbitrate/merge. Failures are always named — never a
silent skip.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO, "server", "engine"))

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS" if cond else "FAIL") + " :: " + name
          + ((" :: " + detail[:200]) if (detail and not cond) else ""), flush=True)


def _block(src, anchor, span):
    i = src.find(anchor)
    return (i, src[i:i + span] if i >= 0 else "")


def main():
    from integration_discipline import FORBIDDEN_ENTRIES, scan_bash_command

    light_src = open(os.path.join(REPO, "server", "engine", "light_lane.py"),
                     encoding="utf-8").read()
    dev_src = open(os.path.join(REPO, "server", "engine", "dev_lane.py"),
                   encoding="utf-8").read()
    li, light = _block(light_src, '"conflict_ctx"', 2600)
    di, dev = _block(dev_src, '"conflict_ctx"', 2600)
    check("B0 both conflict_ctx blocks exist", li >= 0 and di >= 0)

    # --- A: light-lane text carries both new clauses, keeps the old ones ---
    check("A1 forbidden clause with round-fail consequence",
          "must NOT run any integration entry" in light
          and "fails the entire round" in light)
    check("A2 self-check: py_compile", "py_compile" in light)
    check("A3 self-check: JSON validity", "json.tool" in light)
    check("A4 self-check: git diff --check", "git diff --check" in light)
    check("A5 self-check: node --check", "node --check" in light)
    check("A6 never run the suite", "never by running the suite" in light)
    check("A7 keeps touch-only-conflicted-files",
          "touch only the conflicted files" in light)
    check("A8 keeps do-NOT-commit", "do NOT git commit" in light)
    check("A9 keeps resolve-file-by-file", "file by file" in light)
    check("A10 entry list is a rendered placeholder (filled at handoff)",
          "named: %s" in light)

    # --- B: dev-lane default text carries the same clauses ---
    check("B1 forbidden clause with round-fail consequence",
          "must NOT run any integration entry" in dev
          and "fails the entire round" in dev)
    check("B2 self-check: py_compile", "py_compile" in dev)
    check("B3 self-check: JSON validity", "json.tool" in dev)
    check("B4 self-check: git diff --check", "git diff --check" in dev)
    check("B5 self-check: node --check", "node --check" in dev)
    check("B6 never run the suite", "never by running the suite" in dev)
    check("B7 keeps 不要 git commit", "不要 git commit" in dev)
    check("B8 keeps 只动冲突文件", "只动冲突文件" in dev)
    check("B9 keeps 逐个文件解掉冲突标记", "逐个文件解掉冲突标记" in dev)

    # --- C: prompt entry list is rendered from FORBIDDEN_ENTRIES ---
    joined = re.search(r'"、"\.join\(\s*name for _key, name in '
                       r'integration_discipline\.FORBIDDEN_ENTRIES', dev_src)
    check("C1 dev renders the entry list from FORBIDDEN_ENTRIES",
          joined is not None)
    check("C2 dev text takes the rendered list at the naming spot",
          "named: %s" in dev)
    check("C3 dev passes the rendered list into the conflict text",
          "_forbidden_entries_names" in dev)

    # --- D: red line intact; recommended self-checks scan clean ---
    hits = scan_bash_command("python3 integration/run_scenarios.py")
    check("D1 matcher still flags the scenario runner", bool(hits),
          json.dumps(hits)[:120])
    hits2 = scan_bash_command("bash -c 'python3 integration/run_scenarios.py'")
    check("D2 matcher flags it through sh -c recursion", bool(hits2))
    for cmd, entry in [
        ("python3 integration/with_stage.sh x", "with_stage.sh"),
        ("python3 integration/baselines/foo.py", "baselines"),
        ("node integration/t0000/sc_x.mjs", "sc_*"),
        ("python3 server/tools/admin.py call verify_lane", "verify_lane"),
    ]:
        check("D3 matcher flags entry %s" % entry, bool(scan_bash_command(cmd)))
    for cmd in [
        "python3 -m py_compile server/engine/dev_lane.py",
        "python3 -m json.tool result.json",
        "git diff --check",
        "node --check integration/lib_env.mjs",
    ]:
        hits = scan_bash_command(cmd)
        check("D4 self-check scans clean: %s" % cmd, not hits,
              json.dumps(hits)[:160])

    failed = [r for r in results if not r[1]]
    print("SCENARIO ran=%d fail=%d" % (len(results), len(failed)), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
