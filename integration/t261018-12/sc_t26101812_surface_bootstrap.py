#!/usr/bin/env python3
"""sc_t26101812_surface_bootstrap.py — t261018-12: the dead prev-base chain gets a
lawful, operator-declared restart, and fail-closed is never weakened.

Grey-box L3, the REAL run_inspection_surface public face (server/engine/
agent_activities.py) + the REAL ledger reader (inspection_inspect.
read_prev_ledger_doc) over a self-contained real tmp git repo + tmp ledger dir.
Offline seconds, zero docker/Temporal/browser, never touches 3099/7233.

Legs:
  A THE INCIDENT, fail-closed kept — a base-less blocked prev doc (the on-disk
    shape docs-sync/simplify-face have written every period since 20261010) and
    NO bootstrap file → verdict=unavailable, the ORIGINAL reason verbatim, empty
    prev_base and rows: the period still refuses to invent a diff.
  B DECLARED RESTART — an operator drops a valid surface-bootstrap-<id>.json
    (schema 1, full 40-hex sha of a real past commit) → the surface computes a
    REAL diff against the declared base, names the declared-bootstrap source and
    records the operator reason in the note.
  C CHAIN WINS — a live report chain (lane.base_ref) beats a stale bootstrap:
    the base comes from the chain, the note does not claim a bootstrap restart.
  D MALFORMED / UNRESOLVABLE bootstrap is refused BY NAME — bad JSON, wrong
    schema, non-sha ref, and a well-formed but nonexistent 40-hex sha each yield
    verdict=unavailable with "declared bootstrap refused" + the defect, never a
    diff, never a silent ignore.
  E THE PILE STOPS GROWING (two-period journey) — after one declared restart,
    period P+1 with NO bootstrap file inherits a real base through the normal
    report chain (scan_meta.inspect.base_head level) and runs clean.
  F THE HEALTHY FLOW IS UNTOUCHED — an integration-tests-shaped prev doc with
    lane.base_ref and no bootstrap resolves exactly as before.

Intent split (no intent-level duplication): the pure validator truth table and
the activity wiring unit matrix belong to developer L1 (server/engine/tests);
sc_check_inspection_produce_chain / sc_check_auto_rework_trace own the produce
chain, not the surface base chain; this entry owns the user-visible restart
journey over the real activity.

Pre-implement tree: B/C/D/E red = the named TDD signal; green required at the
integration gate / merge. git absent or the engine modules unimportable =
ENV_FAIL exit 2.

Run directly: python3 integration/t261018-12/sc_t26101812_surface_bootstrap.py
(cwd = repo root).
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "server" / "engine"))

PASS = 0
FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok   %s" % label)
    else:
        FAIL += 1
        print("  FAIL %s" % label)


def env_fail(msg):
    print("ENV_FAIL: %s" % msg)
    sys.exit(2)


def git(repo, *args):
    p = subprocess.run(["git", "-C", str(repo)] + list(args),
                       capture_output=True, text=True, check=False)
    if p.returncode != 0:
        env_fail("git %s failed: %s" % (args[0], (p.stderr or "").strip()[:200]))
    return (p.stdout or "").strip()


def make_repo():
    """Two real commits: base sha (empty tree + seed file) then a change."""
    repo = Path(tempfile.mkdtemp(prefix="sb-t26101812-repo-"))
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "t@example")
    git(repo, "config", "user.name", "t")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    base_sha = git(repo, "rev-parse", "HEAD")
    (repo / "changed.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "endpoint")
    end_sha = git(repo, "rev-parse", "HEAD")
    return repo, base_sha, end_sha


def blocked_prev_doc(ledger, inst, period):
    """The exact on-disk shape the incident wrote (blocked, NO base anywhere)."""
    doc = {"kind": "inspection", "instance_id": inst, "period": period,
           "status": "blocked", "stage": "surface", "stage_state": "blocked",
           "red_line": "", "findings": [], "heartbeat": "",
           "blocked_reason": "no usable previous-period base point"}
    (ledger / ("inspection-%s-%s.json" % (inst, period))).write_text(
        json.dumps(doc), encoding="utf-8")


def write_bootstrap(ledger, inst, payload, raw=None):
    path = ledger / ("surface-bootstrap-%s.json" % inst)
    if raw is not None:
        path.write_text(raw, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def run_surface(base_dir, ledger, inst, period, base_head):
    from agent_activities import run_inspection_surface
    try:
        return asyncio.run(run_inspection_surface({
            "instance_id": inst, "period": period, "base_dir": str(base_dir),
            "base_head": base_head, "ledger_dir": str(ledger)}))
    except Exception as e:  # a crash IS a fail, named
        return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}


def main():
    if shutil.which("git") is None:
        env_fail("git not on PATH")
    try:
        import agent_activities  # noqa: F401
        import inspection_surface  # noqa: F401
    except Exception as e:
        env_fail("engine modules unimportable (%s: %s)" % (type(e).__name__, e))

    tmp = Path(tempfile.mkdtemp(prefix="sb-t26101812-"))
    repo, base_sha, end_sha = make_repo()
    inst = "docs-sync"
    period = "20261018"
    try:
        # ---- A: the incident, fail-closed kept (no bootstrap) ----
        print("A incident: base-less blocked prev doc, no bootstrap file")
        led = tmp / "led-a"
        led.mkdir()
        blocked_prev_doc(led, inst, "20261017")
        r = run_surface(repo, led, inst, period, end_sha)
        surf = r.get("surface") or {}
        ok(r.get("ok") is True and surf.get("verdict") == "unavailable",
           "A1 chain dead + no bootstrap -> unavailable (got %r)" % surf.get("verdict"))
        ok(str(surf.get("reason") or "").startswith(
            "no usable previous-period base point"),
           "A2 the ORIGINAL blocked reason verbatim (got %r)"
           % str(surf.get("reason"))[:80])
        ok(not surf.get("prev_base") and not surf.get("rows"),
           "A3 fail-closed: no base, no invented diff rows")

        # ---- B: declared restart ----
        print("B declared restart via bootstrap file")
        led = tmp / "led-b"
        led.mkdir()
        blocked_prev_doc(led, inst, "20261017")
        write_bootstrap(led, inst, {"schema": 1, "base_ref": base_sha,
                                    "reason": "bootstrap after chain death"})
        r = run_surface(repo, led, inst, period, end_sha)
        surf = r.get("surface") or {}
        ok(surf.get("verdict") != "unavailable",
           "B1 declared base revives the period (verdict %r, err %r)"
           % (surf.get("verdict"), r.get("error")))
        ok(str(surf.get("prev_base") or "") == base_sha,
           "B2 diff base IS the declared commit (got %r)" % str(surf.get("prev_base"))[:12])
        ok(surf.get("prev_base_source") == "declared bootstrap file",
           "B3 source names the declared bootstrap (got %r)"
           % surf.get("prev_base_source"))
        note = str(surf.get("note") or "")
        ok("OPERATOR-DECLARED" in note and inst in note and period in note,
           "B4 note names the operator-declared restart, instance and period")
        ok(any("changed.py" in str(row) for row in surf.get("rows") or []),
           "B5 the diff is REAL (declared base -> endpoint shows changed.py)")

        # ---- C: chain wins over a stale bootstrap ----
        print("C live report chain beats a stale bootstrap")
        led = tmp / "led-c"
        led.mkdir()
        live = {"kind": "inspection", "instance_id": inst, "period": "20261017",
                "findings": [], "lane": {"base_ref": base_sha}}
        (led / ("inspection-%s-20261017.json" % inst)).write_text(
            json.dumps(live), encoding="utf-8")
        write_bootstrap(led, inst, {"schema": 1, "base_ref": "0" * 40,
                                    "reason": "stale"})
        r = run_surface(repo, led, inst, period, end_sha)
        surf = r.get("surface") or {}
        ok(surf.get("verdict") != "unavailable" and surf.get("prev_base") == base_sha,
           "C1 base comes from the chain, not the stale file (got %r)"
           % str(surf.get("prev_base"))[:12])
        ok(surf.get("prev_base_source") == "prev lane.base_ref",
           "C2 source is the chain level (got %r)" % surf.get("prev_base_source"))
        ok("OPERATOR-DECLARED" not in str(surf.get("note") or ""),
           "C3 note does not claim a bootstrap restart")

        # ---- D: malformed / unresolvable bootstrap refused BY NAME ----
        print("D malformed and unresolvable bootstrap fail closed, named")
        cases = [
            ("bad-json", {"raw": "{not json"}),
            ("wrong-schema", {"payload": {"schema": 2, "base_ref": base_sha}}),
            ("not-a-sha", {"payload": {"schema": 1, "base_ref": "main"}}),
            ("nonexistent-sha", {"payload": {"schema": 1,
                                             "base_ref": "ab" * 20}}),
        ]
        for name, kw in cases:
            led = tmp / ("led-d-" + name)
            led.mkdir()
            blocked_prev_doc(led, inst, "20261017")
            write_bootstrap(led, inst, kw.get("payload"), raw=kw.get("raw"))
            r = run_surface(repo, led, inst, period, end_sha)
            surf = r.get("surface") or {}
            ok(surf.get("verdict") == "unavailable"
               and "declared bootstrap refused" in str(surf.get("reason") or ""),
               "D/%s refused by name (verdict %r)" % (name, surf.get("verdict")))
            ok(not surf.get("rows"), "D/%s no diff invented" % name)

        # ---- E: the pile stops growing (two-period journey) ----
        print("E period P+1 inherits the base through the normal report chain")
        led = tmp / "led-e"
        led.mkdir()
        blocked_prev_doc(led, inst, "20261017")
        bp = write_bootstrap(led, inst, {"schema": 1, "base_ref": base_sha,
                                         "reason": "restart"})
        r = run_surface(repo, led, inst, period, end_sha)
        surf = r.get("surface") or {}
        bp.unlink()  # the operator's one-time drop is gone; only the report remains
        next_doc = {"kind": "inspection", "instance_id": inst,
                    "period": period, "findings": [],
                    "scan_meta": {"inspect": {"base_head": end_sha}}}
        (led / ("inspection-%s-%s.json" % (inst, period))).write_text(
            json.dumps(next_doc), encoding="utf-8")
        r2 = run_surface(repo, led, inst, "20261019", end_sha)
        surf2 = r2.get("surface") or {}
        ok(surf.get("verdict") != "unavailable",
           "E1 restart period ran clean (err %r)" % r.get("error"))
        ok(surf2.get("verdict") != "unavailable"
           and surf2.get("prev_base") == end_sha,
           "E2 P+1 inherited the endpoint as ITS prev base, no bootstrap file "
           "(verdict %r, err %r)" % (surf2.get("verdict"), r2.get("error")))
        ok(surf2.get("prev_base_source") == "prev scan_meta.inspect.base_head",
           "E3 inheritance travelled the normal report chain (got %r)"
           % surf2.get("prev_base_source"))

        # ---- F: the healthy flow is untouched ----
        print("F integration-tests-shaped lane doc, no bootstrap, unchanged")
        led = tmp / "led-f"
        led.mkdir()
        live = {"kind": "inspection", "instance_id": inst, "period": "20261017",
                "findings": [], "lane": {"base_ref": base_sha}}
        (led / ("inspection-%s-20261017.json" % inst)).write_text(
            json.dumps(live), encoding="utf-8")
        r = run_surface(repo, led, inst, period, end_sha)
        surf = r.get("surface") or {}
        ok(surf.get("verdict") != "unavailable" and surf.get("prev_base") == base_sha
           and surf.get("prev_base_source") == "prev lane.base_ref",
           "F1 healthy chain path byte-identical behavior")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("PASS=%d FAIL=%d" % (PASS, FAIL))
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
