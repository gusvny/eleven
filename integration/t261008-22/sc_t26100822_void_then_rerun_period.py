#!/usr/bin/env python3
"""t261008-22 scenario 2 — void then re-run on the SAME period: the two exits
compose, the audit trail agrees, and the in-flight ordering is respected
(grey-box L3, offline seconds, zero docker / Temporal server / browser, never
touches 3099; open_period_ticket rides a stub client — the established
engine-test seam, no live workflow is ever started).

User-visible promises under test (host order 261008):
  - after voiding a blocked ticket, a re-run of the same period opens a NEW
    ticket with the audit link (old -> new) present in the reopen journal,
    carrying the named reason (acceptance: L3 void-then-rerun evidence);
  - while the period is still LIVE, a re-run is refused with the engine's own
    named refusal ("同期已有在飞巡检 … 先记名 cancel 后再重跑") and no second
    ticket is ever started (no double run);
  - a blocked-completed slot without a named reason stays fail-closed (KI-192).

Legs:
  B1 blocked-completed reopenable: fixture blocked face + stub COMPLETED
     ticket -> open_period_ticket(reopen_reason=...) opens a NEW ticket for
     the SAME period; the journal row links OLD->NEW with the reason verbatim.
  B2 in-flight refusal: the same period described RUNNING -> ok:false whose
     error names the in-flight refusal (substring pins, KI-051 — never the
     whole sentence), and the stub client started ZERO new workflows.
  B3 void-then-rerun composition: after the void surface records the void of
     the OLD ticket's ledger face, the re-run still succeeds and the two
     journals agree on the same old ticket id (void must not block the exit).
  B4 blocked-completed WITHOUT a reason: named fail-closed refusal, no ticket.

Intent split: the void surface's own refusal/zero-write contract belongs to
sc_t26100822_void_named_surface; the UI pass-through and ranking faces belong
to the mjs entries; this entry owns the two exits' composition and ordering on
the engine period machinery.

Pre-implement = FAIL naming the missing face (TDD-phase red expected); green
at arbitrate/merge. Engine tree / stub fixtures unimportable = ENV_FAIL exit 2.
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "integration"))
sys.path.insert(0, str(REPO / "server" / "engine"))

import lib_env  # noqa: E402

try:
    import inspection_ticketing as tick  # noqa: E402
except Exception as e:
    lib_env.env_fail("engine inspection_ticketing unimportable: %s" % e)

# Shared fixture seam: the developer test tree's stub client (explicitly
# allowed reuse of fixtures/helpers across layers).
STUB_MOD = REPO / "server" / "engine" / "tests" / "test_t260916_02_inspection_ticketing.py"
if not STUB_MOD.exists():
    lib_env.env_fail("stub fixture module missing: %s" % STUB_MOD)
sys.path.insert(0, str(STUB_MOD.parent))
try:
    from test_t260916_02_inspection_ticketing import FakeClient, FakeWf  # noqa: E402
except Exception as e:
    lib_env.env_fail("stub client unimportable: %s" % e)

try:
    import shared  # noqa: E402
    INS_SA = shared.INSPECTION_INSTANCE_SA_NAME
    PER_SA = shared.INSPECTION_PERIOD_SA_NAME
except Exception as e:
    lib_env.env_fail("shared SA names unimportable: %s" % e)

results = []


def rec(name, status, detail=""):
    results.append((name, status, detail))
    print("[%s] %s%s" % (status.upper(), name, (" — " + detail) if detail else ""))


INST = "integration-tests"
PERIOD = "20261002"
OLD, NEW = "t261002-12", "t261002-22"
REASON = "mechanical rejection (two findings blocks) — human re-run with named reason"


def wf_stub(status):
    # The dedup query reads the SA attribution stamps; a stub without them is
    # invisible to find_period_ticket_ids (fixture discipline: mirror the
    # real face — instance + period stamps, like the dev battery's wf()).
    return FakeWf(OLD, status=status, sa={INS_SA: INST, PER_SA: PERIOD})


def seed_blocked(root: Path, ticket_id=OLD):
    d = root / "ledger"
    d.mkdir(parents=True, exist_ok=True)
    (d / tick.ledger_file_name(INST, PERIOD)).write_text(
        json.dumps({"ticket_id": ticket_id, "blocked_reason": "findings 围栏块必须恰一块，实际 2 块",
                    "stage": "inspect"}, ensure_ascii=False), encoding="utf-8")
    return d


def seed_supersede_journal(root: Path):
    d = root / "ledger"
    with open(d / tick.REOPEN_JOURNAL_NAME, "a", encoding="utf-8") as f:
        f.write(json.dumps({"at": "2026-10-02T00:00:00", "instance": INST, "period": PERIOD,
                            "terminated_ticket_id": "t261002-01", "new_ticket_id": OLD,
                            "reason": "earlier reopen"}, ensure_ascii=False) + "\n")


def open_ticket(root: Path, client, **kw):
    old = os.environ.get("SANDBAR_INSPECTION_DIR")
    os.environ["SANDBAR_INSPECTION_DIR"] = str(root / "ledger")
    try:
        base = dict(instance_id=INST, period=PERIOD, project_key="sandbar",
                    repo_root="/repo", scan_face="test", decl_path="", task_queue="tq")
        base.update(kw)
        return asyncio.run(tick.open_period_ticket(client, **base))
    finally:
        if old is None:
            os.environ.pop("SANDBAR_INSPECTION_DIR", None)
        else:
            os.environ["SANDBAR_INSPECTION_DIR"] = old


def journal_rows(root: Path):
    return tick.reopen_journal_rows(root / "ledger")


def find_void_fn():
    fn = getattr(tick, "void_period_ticket", None)
    if fn is None:
        try:
            import inspection_void
            fn = getattr(inspection_void, "void_period_ticket", None)
        except Exception:
            fn = None
    return fn


def main():
    tmp = Path(tempfile.mkdtemp(prefix="t26100822-rerun-"))
    try:
        # ---- B1 blocked-completed reopenable with a named reason ----
        try:
            root = tmp / "b1"
            seed_blocked(root)
            client = FakeClient([wf_stub("COMPLETED")])
            out = open_ticket(root, client, reopen_reason=REASON)
            res = out.get("result") or {}
            new_tid = str(res.get("ticket_id") or "")
            rows = journal_rows(root)
            link = [r for r in rows if str(r.get("terminated_ticket_id")) == OLD
                    and str(r.get("new_ticket_id")) == new_tid]
            good = (out.get("ok") is True and res.get("triggered") and new_tid and new_tid != OLD
                    and len(link) == 1 and str(link[0].get("reason")) == REASON)
            rec("B1 blocked-completed-rerun-opens-new-ticket-with-journal-link",
                "pass" if good else "fail",
                "new=%s link_rows=%d reason_ok=%s" % (new_tid, len(link),
                                                      bool(link) and link[0].get("reason") == REASON))
        except Exception as e:
            rec("B1 blocked-completed-rerun-opens-new-ticket-with-journal-link", "fail",
                "%s: %s" % (type(e).__name__, e))

        # ---- B2 in-flight refusal verbatim, zero double-run ----
        try:
            root = tmp / "b2"
            seed_blocked(root)
            client = FakeClient([wf_stub("RUNNING")])
            before_started = len(getattr(client, "started", []) or [])
            out = open_ticket(root, client, reopen_reason=REASON)
            err = str(out.get("error") or "")
            named = out.get("ok") is False and ("在飞" in err or "RUNNING" in err) \
                and ("cancel" in err or "重跑" in err)
            after_started = len(getattr(client, "started", []) or [])
            started_new = [s for s in (getattr(client, "started", []) or [])[before_started:]]
            good = named and after_started == before_started
            rec("B2 in-flight-rerun-refused-verbatim-no-double-run", "pass" if good else "fail",
                "err=%.120s started_new=%r" % (err, started_new))
        except Exception as e:
            rec("B2 in-flight-rerun-refused-verbatim-no-double-run", "fail",
                "%s: %s" % (type(e).__name__, e))

        # ---- B3 void then re-run: the exits compose, journals agree ----
        try:
            void_fn = find_void_fn()
            if void_fn is None:
                rec("B3 void-then-rerun-compose", "fail",
                    "void_period_ticket not landed — void half of the human exit missing")
            else:
                root = tmp / "b3"
                seed_blocked(root)
                seed_supersede_journal(root)
                v = void_fn(root / "ledger", instance_id=INST, period=PERIOD,
                            ticket_id=OLD, who="host", reason="voided by hand")
                client = FakeClient([FakeWf("t261002-01", status="COMPLETED",
                                            sa={INS_SA: INST, PER_SA: PERIOD}), wf_stub("COMPLETED")])
                out = open_ticket(root, client, reopen_reason=REASON)
                res = out.get("result") or {}
                new_tid = str(res.get("ticket_id") or "")
                rows = journal_rows(root)
                # The reopen's audit link may be expressed either as a
                # terminated->new pair or as a collapsed list on the new row;
                # accept the documented shapes, require OLD linked to new_tid
                # with the reason verbatim (KI-192 three-trace family).
                link = [r for r in rows if str(r.get("new_ticket_id")) == new_tid
                        and (OLD == str(r.get("terminated_ticket_id"))
                             or OLD in str(r.get("terminated_ticket_id") or "").split(",")
                             or OLD in [str(x) for x in (r.get("collapsed_ticket_ids") or [])])
                        and str(r.get("reason")) == REASON]
                doc = tick.read_period_ledger_doc(root / "ledger", INST, PERIOD) or {}
                voided_ok = isinstance(doc.get("voided"), dict)
                sup = str((out.get("result") or {}).get("superseded_ticket_id") or "")
                good = (isinstance(v, dict) and v.get("ok") is not False
                        and out.get("ok") is True and len(link) == 1 and voided_ok
                        and OLD in sup)
                rec("B3 void-then-rerun-compose", "pass" if good else "fail",
                    "void_ok=%r rerun_ok=%r link=%d doc_voided=%s rerun_err=%.160s" % (
                        (v or {}).get("ok") if isinstance(v, dict) else v, out.get("ok"),
                        len(link), voided_ok, out.get("error")))
        except Exception as e:
            rec("B3 void-then-rerun-compose", "fail", "%s: %s" % (type(e).__name__, e))

        # ---- B4 blocked-completed without reason: fail-closed ----
        try:
            root = tmp / "b4"
            seed_blocked(root)
            client = FakeClient([wf_stub("COMPLETED")])
            before_started = len(getattr(client, "started", []) or [])
            out = open_ticket(root, client, reopen_reason="")
            named = out.get("ok") is False and str(out.get("error") or "").strip()
            no_start = len(getattr(client, "started", []) or []) == before_started
            rec("B4 blocked-completed-without-reason-named-refusal",
                "pass" if (named and no_start) else "fail",
                "err=%.120s" % ((out.get("error") or ""),))
        except Exception as e:
            rec("B4 blocked-completed-without-reason-named-refusal", "fail",
                "%s: %s" % (type(e).__name__, e))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    fails = [r for r in results if r[1] == "fail"]
    envs = [r for r in results if r[1] == "env_fail"]
    nas = [r for r in results if r[1] == "na"]
    print("SUMMARY pass=%d fail=%d env_fail=%d na=%d" % (
        len(results) - len(fails) - len(envs) - len(nas), len(fails), len(envs), len(nas)))
    sys.exit(1 if fails or (nas and len(nas) == len(results)) else (2 if envs else 0))


if __name__ == "__main__":
    main()
