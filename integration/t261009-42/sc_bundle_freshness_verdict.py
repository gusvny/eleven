#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261009-42 integration scenario: the bundle freshness check verifies freshness,
not a diff.

intent (the ticket's user-visible contract, spec items (2)(3)(4)(5)(6)):
Merge-check item 3.5 must decide "is the committed out prefix the output of this
lane's src?" by rebuilding the DECLARED entry in a temp copy and byte-comparing,
with a three-state verdict:
  - rebuilt-and-identical  -> GREEN ("out did not change" is a fact, not an offence)
  - rebuilt-and-different  -> RED with today's identity (bundle_freshness / bundle_stale)
  - could-not-establish    -> RED degraded, NAMING the failed step, never "assumed fresh"
Fail-closed faces that must NOT change: missing/malformed declaration, entry not
declared (legacy diff-based verdict both ways), src untouched -> no item. The old
genuinely-stale case must still red (spec (5)). The temp copy must be reaped on
every terminal path (spec (4)), judged from the public filesystem face.

Incident being guarded (ticket body, 261010): t261009-35 (type-only src change) and
t261009-41 (new unreferenced file) both rebuilt byte-identical output yet the check
stayed red with an unsatisfiable retry_qc loop, because the verdict approximated
"stale?" with "did out change in the diff?".

Intent split (no duplication, checked against the registered set):
- t260903-12-sc_merge_checks_pairs owns declaration-file alignment with the real repo;
- t261009-38-bundle-out-gate-land / -mergecheck-pair-agreement own the settle path
  gate and the write-set whitelist, and EXPLICITLY exclude the bundle_freshness red;
- the three-state freshness verdict itself is THIS entry's new face.
- the parser/helper truth tables belong to developer L1 (white-box, not re-laid here).

Pre-implement tree: every new-state subcase FAILS naming the legacy verdict (TDD
signal); green required at the integration gate / merge.
Run: PY -B integration/t261009-42/sc_bundle_freshness_verdict.py  (cwd = repo root)
Three-state exit: PASS 0 / FAIL 1 / ENV_FAIL 2. Offline, seconds, zero docker /
Temporal transport / browser, never touches 3099.
"""
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "integration"))
sys.path.insert(0, str(REPO / "integration" / "t260904-18"))

from lib_t260904_18 import (  # noqa: E402
    check, env_fail, git, summary, temporalio_available,
)

SRC = "srcs/client/"
OUT = "builds/lib/"
OUTFILE = OUT + "client.js"

STUB_ADMIN = """#!/usr/bin/env python3
import json, sys
sys.stdout.write(json.dumps(
    {"ok": True, "result": {"green": True, "exit_code": 0, "red_count": 0}}))
"""


def checks_yaml(entry=None, budget=None, extra_key=None):
    lines = ["# project merge checks\n", "bundle_pairs:\n",
             "  - src: %s\n" % SRC, "    out: %s\n" % OUT]
    if entry is not None:
        lines.append("    entry: %s\n" % entry)
    if budget is not None:
        lines.append("    budget_s: %s\n" % budget)
    if extra_key is not None:
        lines.append("    not_a_known_key: oops\n")
    return "".join(lines)


def entry_script(body):
    return "#!/bin/sh\n" + body


BUILD_OK = entry_script('mkdir -p builds/lib\nprintf "fresh bundle\\n" > builds/lib/client.js\n')
BUILD_FAIL = entry_script('echo "toolchain exploded" >&2\nexit 3\n')
BUILD_SLOW = entry_script('sleep 30\n')

BASE_FILES = {
    "server/admin.py": STUB_ADMIN,
    SRC + "widget.ts": "export const w = 1\n",
    OUTFILE: "fresh bundle\n",
    "tools/build-bundle.sh": BUILD_OK,
}


def make_lane(prefix, *, committed_out, src_changed, checks, entry_body=BUILD_OK,
              out_dirty=None):
    """main repo + .lane/t1 worktree; the lane commit touches src (and optionally out)."""
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    g = lambda *a, cwd=None: git(*a, cwd=cwd or tmp)  # noqa: E731
    g("init", "-b", "main")
    g("config", "user.email", "itest@example.com")
    g("config", "user.name", "itest")
    (tmp / "base.txt").write_text("base\n", encoding="utf-8")
    base = dict(BASE_FILES)
    base[OUTFILE] = committed_out
    for rel, text in base.items():
        f = tmp / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    (tmp / "tools" / "build-bundle.sh").chmod(0o755)
    g("add", "-A")
    g("commit", "-m", "base with declared chain")
    g("worktree", "add", ".lane/t1", "-b", "lane")
    wt = tmp / ".lane" / "t1"
    # the lane's work per variant; src_changed=False keeps src untouched so the
    # noise-reduction stance (no item) is actually exercised, not assumed
    if src_changed:
        wt.joinpath(SRC + "widget.ts").write_text("export const w = 2\n", encoding="utf-8")
    else:
        p = wt.joinpath("docs/note.md")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("lane work without src\n", encoding="utf-8")
    if entry_body is not None:
        p = wt / "tools" / "build-bundle.sh"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(entry_body, encoding="utf-8")
        p.chmod(0o755)
    if checks is not None:
        p = wt / "server" / "merge-checks.yaml"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(checks, encoding="utf-8")
    if out_dirty is not None:
        p = wt / OUTFILE
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(out_dirty, encoding="utf-8")
    g("add", "-A", cwd=wt)
    g("commit", "-m", "lane work", cwd=wt)
    merge_base = g("merge-base", "main", "lane").strip()
    return tmp, wt, merge_base


def bundle_items(checks):
    return [c for c in checks
            if c.get("id") == "bundle_freshness"
            or str(c.get("item", "")).startswith("bundle")]


def run_merge(wt, merge_base):
    import asyncio
    import agent_activities
    from agent_activities import MergeCheckArgs
    # t261019-28: this fixture PLANTS its own files (the build entry under
    # tools/, the merge-checks declaration under server/, the committed bundle
    # under builds/). They must be inside the declared write set, or the
    # merge_check foreign-file repair (t261012-09, KI-01M4PAVBP6EZFGYC2VVQ0Z90J7)
    # correctly reverts them to main's version BEFORE the bundle item judges:
    # the failing entry becomes main's working one and the declaration vanishes,
    # so T3a/T3c read green and T5 falls back to the diff heuristic. The engine
    # rule is right (a lane owns only its declared paths); the fixture was the
    # party out of date. Every assertion is untouched.
    res = asyncio.run(agent_activities.merge_check(MergeCheckArgs(
        ticket_id="t26100942sc", worktree=str(wt), branch="lane",
        base_ref=merge_base,
        write_set=["srcs/", "tools/", "server/", "builds/"])))
    return bundle_items(res.checks)


def one_item(items, label):
    ok = len(items) == 1
    check(label + " (exactly one bundle item)", ok, "items=%r" % (items,))
    return items[0] if ok else {}


FORBIDDEN = ("assumed fresh", "presumed fresh")


def main():
    try:
        from lib_t260904_18 import merge_fixture_repo  # noqa: F401  probe fixture chain
    except Exception as e:
        env_fail("fixture chain unavailable (%s: %s)" % (type(e).__name__, e))
        return 2
    if not temporalio_available():
        env_fail("temporalio unavailable in this interpreter: the real merge_check "
                 "driver cannot run; arbitrate/merge venv must be all green")
        return 2
    sys.path.insert(0, str(REPO / "server" / "engine"))
    try:
        import agent_activities  # noqa: F401
        from agent_activities import MergeCheckArgs  # noqa: F401
    except Exception as e:
        env_fail("engine agent_activities unimportable (%s: %s)" % (type(e).__name__, e))
        return 2

    tmpdirs_before = set(Path(tempfile.gettempdir()).iterdir())
    try:
        # T1 rebuilt-and-identical -> GREEN (the incident shape: out unchanged is a fact)
        tmp, wt, mb = make_lane("t26100942-t1-", committed_out="fresh bundle\n",
                                src_changed=True,
                                checks=checks_yaml(entry="tools/build-bundle.sh"))
        try:
            it = one_item(run_merge(wt, mb), "T1 identical rebuild")
            check("T1 green (rebuilt-and-identical, not a diff demand)",
                  it.get("green") is True, "item=%r" % (it,))
            check("T1 evidence line names the state (rebuilt/identical)",
                  "rebuilt" in str(it.get("detail", "")).lower()
                  and "identical" in str(it.get("detail", "")).lower(),
                  "detail=%r" % (it.get("detail"),))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        # T2 rebuilt-and-different -> RED, today's identity (spec (5): stale still reds)
        tmp, wt, mb = make_lane("t26100942-t2-", committed_out="old bundle\n",
                                src_changed=True,
                                checks=checks_yaml(entry="tools/build-bundle.sh"))
        try:
            it = one_item(run_merge(wt, mb), "T2 stale rebuild")
            check("T2 red (rebuilt-and-different)", it.get("green") is False,
                  "item=%r" % (it,))
            check("T2 identity kept (reason_code=bundle_stale, pair files named)",
                  it.get("reason_code") == "bundle_stale"
                  and SRC in str(it.get("files")) and OUT in str(it.get("files")),
                  "item=%r" % (it,))
            check("T2 evidence line names the state (different/stale)",
                  "different" in str(it.get("detail", "")).lower()
                  or "stale" in str(it.get("detail", "")).lower(),
                  "detail=%r" % (it.get("detail"),))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        # T3 could-not-establish -> RED degraded, naming the failed step, never green
        for name, body, cfg, needle in (
                ("T3a exit", BUILD_FAIL, checks_yaml(entry="tools/build-bundle.sh"), "exit"),
                ("T3b entry file missing", BUILD_OK,
                 checks_yaml(entry="tools/no-such-entry.sh"), "not found"),
                ("T3c budget exceeded", BUILD_SLOW,
                 checks_yaml(entry="tools/build-bundle.sh", budget=1), "budget")):
            tmp, wt, mb = make_lane("t26100942-t3-", committed_out="fresh bundle\n",
                                    src_changed=True, checks=cfg, entry_body=body)
            try:
                it = one_item(run_merge(wt, mb), name + " degraded")
                check(name + " red degraded (never silently green)",
                      it.get("green") is False, "item=%r" % (it,))
                det = str(it.get("detail", ""))
                check(name + " names the failed establishment step (%s)" % needle,
                      needle in det.lower(), "detail=%r" % (det,))
                check(name + " never claims freshness",
                      not any(f in det.lower() for f in FORBIDDEN), "detail=%r" % (det,))
            finally:
                shutil.rmtree(tmp, ignore_errors=True)

        # T4/T5 entry not declared -> today's diff-based verdict, BOTH ways (fail-closed)
        tmp, wt, mb = make_lane("t26100942-t4-", committed_out="fresh bundle\n",
                                src_changed=True, checks=checks_yaml())
        try:
            it = one_item(run_merge(wt, mb), "T4 legacy no-entry")
            check("T4 legacy verdict kept (src changed, no out change, no entry -> red)",
                  it.get("green") is False, "item=%r" % (it,))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        tmp, wt, mb = make_lane("t26100942-t5-", committed_out="old bundle\n",
                                src_changed=True, checks=checks_yaml(),
                                out_dirty="hand rebuilt\n")
        try:
            it = one_item(run_merge(wt, mb), "T5 legacy rebuilt-in-diff")
            check("T5 legacy verdict kept (out changed in diff -> green, declaration governs)",
                  it.get("green") is True, "item=%r" % (it,))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        # T6 malformed optional key -> fail-closed named red (no new back door)
        tmp, wt, mb = make_lane("t26100942-t6-", committed_out="fresh bundle\n",
                                src_changed=True,
                                checks=checks_yaml(entry="tools/build-bundle.sh",
                                                   extra_key=True))
        try:
            it = one_item(run_merge(wt, mb), "T6 malformed key")
            check("T6 red fail-closed with named diagnosis",
                  it.get("green") is False and str(it.get("detail", "")) != "",
                  "item=%r" % (it,))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        # T7 src untouched -> no item (noise-reduction stance unchanged)
        tmp, wt, mb = make_lane("t26100942-t7-", committed_out="fresh bundle\n",
                                src_changed=False,
                                checks=checks_yaml(entry="tools/build-bundle.sh"))
        try:
            import asyncio
            import agent_activities
            from agent_activities import MergeCheckArgs
            res = asyncio.run(agent_activities.merge_check(MergeCheckArgs(
                ticket_id="t26100942sc", worktree=str(wt), branch="lane",
                base_ref=mb, write_set=["docs/"])))
            check("T7 src untouched -> no bundle item",
                  len(bundle_items(res.checks)) == 0, "checks=%r" % (res.checks,))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        # T8 spec (4): the temp copy is reaped on every terminal path, judged from the
        # public filesystem face (no leftover temp dir from any of the runs above).
        leftovers = sorted(p.name for p in Path(tempfile.gettempdir()).iterdir()
                           if p.name not in tmpdirs_before
                           and p.name.startswith("t26100942-"))
        check("T8 no temp copy left behind on any terminal path", not leftovers,
              "leftovers=%r" % (leftovers,))
    finally:
        pass
    return summary()


if __name__ == "__main__":
    sys.exit(main())
