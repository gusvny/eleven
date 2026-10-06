#!/usr/bin/env python3
"""inspection_aggregate_report — cross-face / cross-period aggregate weekly page
(t261006-14, epic inspection ticket 3; grey-box L2/L3, offline, zero docker /
Temporal server / browser / 3099).

User-facing promise under test: a reader who wants "what is new, what got
fixed, what is overdue" gets ONE page derived from the existing artifacts
(period ledgers + verdicts + spawn/reopen journals + ticket states), never a
second hand-maintained register, and the aggregate writes nothing except its
own report file. Missing/damaged inputs are NAMED ("not available"), never
silently blank.

Sections
  A wiring face  : the trigger ops channel exposes the weekly subcommand; the
                   aggregate module is importable WITHOUT temporalio (pure
                   layer); the deadman ledger pattern does not admit the
                   `aggregate-` prefix.
  B deadman safe : an aggregate report file sitting in the ledger dir is
                   INVISIBLE to inspection_deadman (LEDGER_NAME_RE /
                   ledger_periods) — per-period deadman accounting must not
                   count the aggregate as a period ledger.
  C one page     : end-to-end derivation over a two-instance fixture tree via
                   the pure layer (build_aggregate, contract: per-instance,
                   injected ticket_lookup) — new findings per severity with
                   the first-seen-in-window rule, fixed vs still_open (verdict
                   winner across periods + injected ticket state), overdue
                   (older than the stated age, no verdict, no ticket state
                   injected), and the pure layer stays read-only.
  D shell reader : the weekly subcommand derives offline, writes EXACTLY its
                   own aggregate-<instance>-<anchor>.json into the ledger
                   dir, and the page is read back from the FILE on disk
                   (reader-side discipline — the writer's stdout is not
                   evidence).
  E damaged input: a malformed verdicts JSON for one period is named in the
                   page's not-available face and never silently zeroes the
                   roll-up; a torn trailing .jsonl journal line (the borrowed
                   journal readers' declared gap) is counted in a visible
                   journal_note.
  F hygiene      : determinism (same inputs -> identical page), declared
                   ordering key, degraded ticket states stay conservative
                   (lookup=None -> ticket_states_available=false, findings
                   stay in still_open, never guessed fixed).

Pre-implement red expected (TDD signal): a missing module / entry point /
subcommand is a NAMED FAIL, never a crash, never a silent pass. Must be green
at arbitrate/merge.

Run directly: python3 integration/t261006-14/sc_inspection_aggregate_report.py
(cwd = repo root).
"""
import json
import re
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
        print("  ok  %s" % label)
    else:
        FAIL += 1
        print("  FAIL %s" % label)


def section(title):
    print("\n== %s" % title)


# --------------------------------------------------------------------------
# fixture tree (offline, deterministic; no LLM, no temporal, no network)
# --------------------------------------------------------------------------
P1, P2 = "20260922", "20261006"

DECL = """schema: v1
instances:
  - id: inst-a
    enabled: true
    project_key: aggfix
    workflow: InspectionPeriodicWorkflow
    template: inspection-lite
    schedule:
      kind: cron
      cron: 0 3 * * 1
  - id: inst-b
    enabled: true
    project_key: aggfix
    workflow: InspectionPeriodicWorkflow
    template: inspection-lite
    schedule:
      kind: cron
      cron: 0 3 * * 1
"""


def period_ledger(instance, period, findings):
    return {
        "instance_id": instance,
        "period": period,
        "heartbeat": False,
        "summary": {"findings": len(findings)},
        "findings": findings,
    }


def build_fixture(root):
    """Two instances; inst-b keeps only P1 so the newer expected period has no
    ledger file (the missing-period face must name it, not stay blank)."""
    led = root / "ledgers"
    shutil.rmtree(led, ignore_errors=True)   # fresh tree per fixture build
    led.mkdir(parents=True)
    (led / ("inspection-inst-a-%s.json" % P1)).write_text(json.dumps(
        period_ledger("inst-a", P1, [
            {"id": "f-old", "scan": "s1", "severity": "med",
             "verified": True, "suppressed": False, "recurring": False},
            {"id": "f-sup", "scan": "s2", "severity": "high",
             "verified": True, "suppressed": True, "recurring": False},
            {"id": "f-over", "scan": "s1", "severity": "low",
             "verified": True, "suppressed": False, "recurring": False},
        ]), indent=1), encoding="utf-8")
    (led / ("inspection-inst-a-%s.json" % P2)).write_text(json.dumps(
        period_ledger("inst-a", P2, [
            {"id": "f-old", "scan": "s1", "severity": "med",
             "verified": True, "suppressed": False, "recurring": True},
            {"id": "f-new", "scan": "s3", "severity": "high",
             "verified": True, "suppressed": False, "recurring": False},
            {"id": "f-over", "scan": "s1", "severity": "low",
             "verified": True, "suppressed": False, "recurring": True},
        ]), indent=1), encoding="utf-8")
    (led / ("inspection-inst-a-%s-verdicts.json" % P1)).write_text(json.dumps(
        {"entries": [
            {"finding_id": "f-old", "verdict": "to-fix", "who": "host",
             "note": "first call"},
        ]}, indent=1), encoding="utf-8")
    (led / ("inspection-inst-a-%s-verdicts.json" % P2)).write_text(json.dumps(
        {"entries": [
            {"finding_id": "f-old", "verdict": "false-positive", "who": "host",
             "note": "recanted later"},
            {"finding_id": "f-new", "verdict": "to-fix", "who": "host",
             "note": "fix it"},
        ]}, indent=1), encoding="utf-8")
    (led / "inspection-spawn.jsonl").write_text(
        json.dumps({"instance_id": "inst-a", "period": P2,
                    "finding_id": "f-new", "ticket_id": "t-fix-1"}) + "\n",
        encoding="utf-8")
    (led / "inspection-reopen.jsonl").write_text("", encoding="utf-8")
    (led / ("inspection-inst-b-%s.json" % P1)).write_text(json.dumps(
        period_ledger("inst-b", P1, [
            {"id": "b-1", "scan": "s9", "severity": "med",
             "verified": True, "suppressed": False, "recurring": False},
        ]), indent=1), encoding="utf-8")
    (root / "inspection.yaml").write_text(DECL, encoding="utf-8")
    return led


def load_aggregate():
    """Import the aggregate pure layer; return module or None (named FAIL)."""
    if not (ROOT / "server" / "engine" / "inspection_aggregate.py").is_file():
        return None
    try:
        import inspection_aggregate  # noqa: F401
        return inspection_aggregate
    except Exception as e:  # noqa: BLE001 - named, never silent
        print("  (import inspection_aggregate failed: %s: %s)"
              % (type(e).__name__, e))
        return None


def agg(mod, inst, led, ticket_lookup=None, **overrides):
    """Invoke the declared pure entry. Signature drift = named failure."""
    fn = getattr(mod, "build_aggregate", None)
    if fn is None:
        raise RuntimeError("build_aggregate entry point missing")
    args = dict(window_days=7, overdue_days=7, cron="0 3 * * 1",
                ticket_lookup=ticket_lookup)
    args.update(overrides)
    return fn(inst, led, **args)


def run_weekly(repo_root, led, tmp, instance):
    """The public shell face: inspection_trigger.py weekly (offline default)."""
    env_copy = {k: v for k, v in __import__("os").environ.items()
                if k != "SANDBAR_INSPECTION_DIR"}
    return subprocess.run(
        [sys.executable, "-B", "server/engine/inspection_trigger.py", "weekly",
         "--instance", instance, "--ledger-dir", str(led),
         "--decl-path", str(Path(tmp) / "inspection.yaml")],
        cwd=str(repo_root), capture_output=True, text=True, env=env_copy,
        timeout=60)


def ids(items):
    return sorted(str(e.get("id")) for e in items or [])


# ==========================================================================
def main():
    tmp = Path(tempfile.mkdtemp(prefix="sandbar-sc-agg-"))
    try:
        mod = load_aggregate()

        # ---------------- A wiring face ----------------
        section("A wiring face (weekly subcommand + pure layer + name)")
        trig_src = (ROOT / "server" / "engine" / "inspection_trigger.py"
                    ).read_text("utf-8")
        ok('"weekly"' in trig_src, "trigger declares the weekly face")
        ok(mod is not None,
           "inspection_aggregate.py exists and imports without temporalio")
        if mod is not None:
            src = (ROOT / "server" / "engine" / "inspection_aggregate.py"
                   ).read_text("utf-8")
            ok(not re.search(r"^\s*(from|import)\s+temporalio", src, re.M),
               "aggregate module stays temporalio-free (pure layer)")
        dead_src = (ROOT / "server" / "engine" / "inspection_deadman.py"
                    ).read_text("utf-8")
        m = re.search(r"LEDGER_NAME_RE = re\.compile\(\s*r?\"([^\"]+)\"",
                      dead_src, re.S)
        ok(m is not None and "aggregate-" not in m.group(1),
           "deadman ledger pattern does not admit the aggregate- prefix")

        # ---------------- B deadman non-interference ----------------
        section("B deadman non-interference (aggregate is not a period)")
        from inspection_deadman import LEDGER_NAME_RE, ledger_periods
        led = build_fixture(tmp)
        probe = led / ("aggregate-inst-a-%s.json" % P2)
        probe.write_text("{}", encoding="utf-8")
        ok(LEDGER_NAME_RE.match(probe.name) is None,
           "LEDGER_NAME_RE rejects aggregate-<inst>-<period>.json")
        lp = ledger_periods(led, "inst-a")
        ok(lp["periods"] == {P1, P2},
           "ledger_periods sees only the period ledgers (aggregate invisible)"
           ": %s" % sorted(lp["periods"]))
        ok(lp["malformed"] == [],
           "the aggregate file raises no malformed noise")

        if mod is None:
            print("\npre-implement red: aggregate module missing; sections "
                  "C-F cannot bind (named FAILs already counted)")
        else:
            # ---------------- C one page (pure layer) ----------------
            section("C one page (new / fixed / open / overdue / missing)")
            lookup = lambda f: (  # noqa: E731 - stub ticket-state reader
                {"ticket_id": "t-fix-1", "state": "completed", "closed": True}
                if f.get("id") == "f-new" else None)
            page = agg(mod, "inst-a", led, ticket_lookup=lookup)
            ok(page.get("anchor_period") == P2,
               "anchor period = newest readable ledger period (%s)"
               % page.get("anchor_period"))
            new_ids = ids(page["new_findings"]["items"])
            ok(new_ids == ["f-new"],
               "new this week = first seen in the window only: %s "
               "(f-old predates the window, f-sup is suppressed)" % new_ids)
            sev = page["new_findings"]["by_severity"]
            ok(sev.get("high") == 1 and sev.get("med") == 0,
               "new findings broken down per severity: %s" % sev)
            ok(ids(page["fixed"]) == ["f-new"],
               "closed fix ticket resolves its finding into fixed: %s"
               % ids(page["fixed"]))
            ok("f-old" not in ids(page["still_open"] + page["overdue"]),
               "newest-period verdict (false-positive) wins over the older "
               "to-fix: f-old adjudicated, not open, not overdue")
            ok(ids(page["overdue"]) == ["f-over"],
               "finding older than the stated age with no verdict and no "
               "ticket state lands in overdue: %s" % ids(page["overdue"]))
            # a ticket-state reader that answers for EVERY finding (never
            # None) is the "real reader" face: the page says states are
            # available (contract: any None answer degrades the flag).
            page_full = agg(mod, "inst-a", led, ticket_lookup=lambda f: {
                "ticket_id": "t-" + str(f.get("id")),
                "state": "completed", "closed": f.get("id") == "f-new"})
            ok(page_full.get("ticket_states_available") is True,
               "a reader that answers for every finding flips the flag true")
            ok(ids(page_full["fixed"]) == ["f-new"],
               "full-reader page: only the closed ticket counts as fixed")

            # ---------------- D shell reader face ----------------
            section("D shell reader face (weekly writes its own file only)")
            led2 = build_fixture(tmp)
            before = sorted(p.relative_to(tmp).as_posix()
                            for p in tmp.rglob("*") if p.is_file())
            r = run_weekly(ROOT, led2, tmp, "inst-a")
            lines = [ln for ln in (r.stdout or "").strip().splitlines()
                     if ln.startswith("{")]
            receipt0 = json.loads(lines[-1]) if lines else {}
            doc0 = receipt0.get("result") or {}   # receipt shape: {ok, result}
            # exit code is 1 BY CONTRACT when overdue/missed are non-empty
            # (alarmed page) — the receipt itself must say ok.
            ok(lines and receipt0.get("ok") is True and r.returncode in (0, 1),
               "weekly emits a single-line ok receipt (rc=%d, alarmed=%s)"
               % (r.returncode, doc0.get("alarmed")))
            after = sorted(p.relative_to(tmp).as_posix()
                           for p in tmp.rglob("*") if p.is_file())
            added = [f for f in after if f not in before]
            ok(added == ["ledgers/aggregate-inst-a-%s.json" % P2],
               "exactly one new file in the tree, the aggregate's own report: "
               "%s" % added)
            doc = json.loads((led2 / ("aggregate-inst-a-%s.json" % P2))
                             .read_text("utf-8"))
            ok(doc.get("kind") == "inspection-aggregate",
               "reader face: the file on disk parses to the aggregate page")
            ok(doc.get("anchor_period") == P2 and doc.get("instance_id") == "inst-a",
               "page names its instance and anchor period")
            # inst-b: P1 exists, later expected periods have no ledger file
            r2 = run_weekly(ROOT, led2, tmp, "inst-b")
            lines2 = [ln for ln in (r2.stdout or "").strip().splitlines()
                      if ln.startswith("{")]
            doc2 = ((json.loads(lines2[-1]) or {}).get("result") or {}
                    if lines2 else {})
            ok(bool(doc2.get("missed_periods")),
               "periods that produced no report are named in missed_periods: "
               "%s (rc=%d, stderr=%s)" % (doc2.get("missed_periods"),
                                          r2.returncode,
                                          (r2.stderr or "")[:200]))
            ok(doc0.get("alarmed") is True and doc2.get("alarmed") is True,
               "page raises the alarmed flag when misses/overdue are non-empty")

            # ---------------- E damaged input ----------------
            section("E damaged input (named, never silent)")
            led3 = build_fixture(tmp)
            (led3 / ("inspection-inst-a-%s-verdicts.json" % P2)).write_text(
                "{not json", encoding="utf-8")
            jrnl = led3 / "inspection-spawn.jsonl"
            jrnl.write_text(jrnl.read_text("utf-8")
                            + '{"instance_id": "inst-a", "period": "%s"' % P2,
                            encoding="utf-8")  # torn trailing line
            page3 = agg(mod, "inst-a", led3)
            na = " ".join(str(e.get("reason", "")) for e in
                          page3["periods_not_available"])
            ok("verdicts" in na.lower() or
               any("verdicts" in str(k) for k in
                   [e.get("period") for e in page3["periods_not_available"]]),
               "malformed verdicts file is named in the not-available face: %s"
               % page3["periods_not_available"])
            ok("f-new" in ids(page3["still_open"]),
               "a damaged verdicts file never silently zeroes the roll-up "
               "(f-new stays open, named path)")
            ok(sum(page3["journal_note"].values()) >= 1,
               "torn journal tail counted in a visible journal_note: %s"
               % page3["journal_note"])

            # ---------------- F hygiene ----------------
            section("F hygiene (determinism / ordering / degraded states)")
            led4 = build_fixture(tmp)
            p_a = agg(mod, "inst-a", led4, ticket_lookup=lookup)
            p_b = agg(mod, "inst-a", led4, ticket_lookup=lookup)
            ok(json.dumps(p_a, sort_keys=True) == json.dumps(p_b, sort_keys=True),
               "same inputs -> identical page (determinism)")
            ok(bool(p_a.get("ordering")),
               "page declares its ordering explicitly")
            page5 = agg(mod, "inst-a", led4, ticket_lookup=None)
            ok(page5.get("ticket_states_available") is False,
               "no ticket-state reader -> page flags ticket_states_available=false")
            ok("f-new" in ids(page5["still_open"]),
               "ticket states unavailable -> findings stay conservatively in "
               "still_open, never guessed fixed")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\nsummary: pass=%d fail=%d" % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
