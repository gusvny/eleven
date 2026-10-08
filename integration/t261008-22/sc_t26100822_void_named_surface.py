#!/usr/bin/env python3
"""t261008-22 scenario 1 — the named void surface for a terminal blocked
inspection period ticket (grey-box L2/L3, offline seconds, zero docker /
Temporal / browser, never touches 3099).

User-visible promise under test (host order 261008): a mechanically-rejected
(blocked) inspection ticket gets a human exit — "Void with a reason" — that
RECORDS who voided it and why in the engine's own ledgers (acceptance 4), and
never looks like a success that hides the rejected findings (reject rules).

Legs:
  A1  happy path: a fixture period whose ledger doc carries the blocked face
      (ticket_id match + non-empty blocked_reason) is voided with who+reason;
      the void journal gains exactly one row carrying instance / period /
      ticket_id / who / reason / at, and the period ledger doc gains a voided
      field carrying the SAME who/reason verbatim (face × record agreement).
  A2  reason-less / who-less / agent-named voids are refused BY NAME with zero
      side effects: every refusal leaves the ledger directory byte-identical
      (no journal row, no doc rewrite — asserted by byte-compare, not by
      trusting a return value).
  A3  population refusals: a served (unproven) face, an unreadable ledger doc,
      a wrong ticket_id — each refused by name, zero writes. Void only applies
      to blocked tickets; served findings can never be voided away.
  A4  idempotence: a second void of the same ticket is refused and names the
      FIRST disposition (who/reason/at) — no second journal row, first
      disposition stands and stays visible.
  A5  a malformed (torn) pre-existing journal row does not block a fresh void
      of another ticket in the same ledger dir — it is counted, never fatal,
      never silently dropped (external-input discipline).
  A6  findings are not erased: after a successful void the doc still carries
      the original blocked_reason verbatim (voiding must not read as success).

Intent split: the reopen/redirect journal machinery and the panel/ranking
faces belong to their own entries in this ticket's set; this entry owns the
void surface's named-termination contract on the engine's own evidence files.

Pre-implement = FAIL naming the missing surface (TDD-phase red expected);
must be green at arbitrate/merge. Engine tree unimportable = ENV_FAIL exit 2.
"""
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

results = []  # (name, status, detail)


def rec(name, status, detail=""):
    results.append((name, status, detail))
    print("[%s] %s%s" % (status.upper(), name, (" — " + detail) if detail else ""))


INST = "integration-tests"
PERIOD = "20261002"
TICKET = "t261002-12"
WHO = "host"
REASON = "inspect output carried two findings blocks; parser refused to guess; voided by hand"


def ledger_dir(root: Path) -> Path:
    d = root / "ledger"
    d.mkdir(parents=True, exist_ok=True)
    return d


def seed_blocked_doc(root: Path, ticket_id=TICKET, blocked_reason="findings 围栏块必须恰一块，实际 2 块"):
    p = ledger_dir(root) / tick.ledger_file_name(INST, PERIOD)
    p.write_text(json.dumps({"ticket_id": ticket_id, "kind": "inspection",
                             "blocked_reason": blocked_reason, "stage": "inspect",
                             "findings": []}, ensure_ascii=False), encoding="utf-8")
    return p


def journal_file(root: Path):
    return ledger_dir(root) / tick.REOPEN_JOURNAL_NAME


def dir_digest(root: Path):
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = p.read_bytes()
    return out


def find_void_surface():
    """Locate the plan-declared void surface: void_period_ticket (+ the void
    journal reader) on inspection_ticketing or a sibling module. Returns
    (module_name, void_fn, read_fn) or (None, None, None)."""
    candidates = []
    try:
        candidates.append(("inspection_ticketing", tick))
    except Exception:
        pass
    try:
        import inspection_void  # noqa: F401
        candidates.append(("inspection_void", inspection_void))
    except Exception:
        pass
    for name, mod in candidates:
        fn = getattr(mod, "void_period_ticket", None)
        rd = getattr(mod, "read_void_journal", None)
        if fn is not None:
            return name, fn, rd
    return (None, None, None)


try:
    import inspection_ticketing as tick  # noqa: E402
except Exception as e:  # environment red, nothing verified
    lib_env.env_fail("engine inspection_ticketing unimportable: %s" % e)


def main():
    mod_name, void_fn, read_fn = find_void_surface()
    if void_fn is None:
        # Pre-implement red: name the missing face, exit product red.
        rec("A0 void-surface-present", "fail",
            "no void_period_ticket on inspection_ticketing/inspection_void — the named "
            "void surface (plan v2 Step 1) is not landed")
    else:
        tmp = Path(tempfile.mkdtemp(prefix="t26100822-void-"))
        try:
            # ---- A1 happy path: named void recorded in BOTH evidence faces ----
            root = tmp / "a1"
            seed_blocked_doc(root)
            try:
                out = void_fn(ledger_dir(root), instance_id=INST, period=PERIOD,
                              ticket_id=TICKET, who=WHO, reason=REASON)
                ok = True if isinstance(out, dict) and out.get("ok") is not False else bool(out is not None and not isinstance(out, dict))
                rows = read_fn(ledger_dir(root)) if read_fn else []
                mine = [r for r in rows if str(r.get("ticket_id")) == TICKET]
                doc = tick.read_period_ledger_doc(ledger_dir(root), INST, PERIOD) or {}
                voided = doc.get("voided") if isinstance(doc, dict) else None
                good = (ok and len(mine) == 1
                        and str(mine[0].get("who")) == WHO
                        and str(mine[0].get("reason")) == REASON
                        and str(mine[0].get("instance")) == INST
                        and str(mine[0].get("period")) == PERIOD
                        and bool(str(mine[0].get("at") or "").strip()))
                good = good and isinstance(voided, dict) \
                    and str(voided.get("who")) == WHO and str(voided.get("reason")) == REASON
                rec("A1 void-records-who-reason-in-both-faces", "pass" if good else "fail",
                    "module=%s journal_rows=%d doc.voided=%r" % (mod_name, len(mine), voided))
            except Exception as e:
                rec("A1 void-records-who-reason-in-both-faces", "fail",
                    "void raised: %s: %s" % (type(e).__name__, e))

            # ---- A2 reason-less / who-less / agent-who: named refusal, zero writes ----
            for tag, kw in (
                ("A2a empty-reason-refused-zero-writes", dict(who=WHO, reason="")),
                ("A2b whitespace-reason-refused-zero-writes", dict(who=WHO, reason="   ")),
                ("A2c empty-who-refused-zero-writes", dict(who="", reason=REASON)),
                ("A2d agent-who-refused-zero-writes", dict(who="developer", reason=REASON)),
            ):
                root = tmp / tag.replace(" ", "")
                seed_blocked_doc(root)
                before = dir_digest(root)
                try:
                    out = void_fn(ledger_dir(root), instance_id=INST, period=PERIOD,
                                  ticket_id=TICKET, **kw)
                    refused = isinstance(out, dict) and out.get("ok") is False and str(out.get("error") or "").strip()
                    unchanged = dir_digest(root) == before
                    rec(tag, "pass" if (refused and unchanged) else "fail",
                        "refused=%s unchanged=%s error=%r" % (bool(refused), unchanged,
                                                              (out or {}).get("error") if isinstance(out, dict) else out))
                except ValueError as e:
                    unchanged = dir_digest(root) == before
                    rec(tag, "pass" if unchanged else "fail",
                        "raised ValueError (named refusal channel): %.80s; unchanged=%s" % (e, unchanged))
                except Exception as e:
                    rec(tag, "fail", "unexpected %s: %s" % (type(e).__name__, e))

            # ---- A3 population refusals ----
            # served (unproven) face
            root = tmp / "a3-served"
            seed_blocked_doc(root, blocked_reason="")
            before = dir_digest(root)
            try:
                out = void_fn(ledger_dir(root), instance_id=INST, period=PERIOD,
                              ticket_id=TICKET, who=WHO, reason=REASON)
                refused = isinstance(out, dict) and out.get("ok") is False and "error" in out
                rec("A3a served-ticket-void-refused", "pass" if (refused and dir_digest(root) == before) else "fail",
                    "error=%r" % ((out or {}).get("error"),))
            except ValueError as e:
                rec("A3a served-ticket-void-refused", "pass" if dir_digest(root) == before else "fail",
                    "raised ValueError: %.80s" % e)
            except Exception as e:
                rec("A3a served-ticket-void-refused", "fail", "%s: %s" % (type(e).__name__, e))
            # unreadable doc
            root = tmp / "a3-unreadable"
            ledger_dir(root)
            (ledger_dir(root) / tick.ledger_file_name(INST, PERIOD)).write_text("{not json", encoding="utf-8")
            before = dir_digest(root)
            try:
                out = void_fn(ledger_dir(root), instance_id=INST, period=PERIOD,
                              ticket_id=TICKET, who=WHO, reason=REASON)
                refused = isinstance(out, dict) and out.get("ok") is False
                rec("A3b unreadable-doc-void-refused-no-guess", "pass" if (refused and dir_digest(root) == before) else "fail",
                    "error=%r" % ((out or {}).get("error"),))
            except ValueError as e:
                rec("A3b unreadable-doc-void-refused-no-guess", "pass" if dir_digest(root) == before else "fail",
                    "raised ValueError: %.80s" % e)
            except Exception as e:
                rec("A3b unreadable-doc-void-refused-no-guess", "fail", "%s: %s" % (type(e).__name__, e))
            # wrong ticket id in the doc
            root = tmp / "a3-wrongtid"
            seed_blocked_doc(root, ticket_id="t-other")
            before = dir_digest(root)
            try:
                out = void_fn(ledger_dir(root), instance_id=INST, period=PERIOD,
                              ticket_id=TICKET, who=WHO, reason=REASON)
                refused = isinstance(out, dict) and out.get("ok") is False
                rec("A3c wrong-ticket-id-void-refused", "pass" if (refused and dir_digest(root) == before) else "fail",
                    "error=%r" % ((out or {}).get("error"),))
            except ValueError as e:
                rec("A3c wrong-ticket-id-void-refused", "pass" if dir_digest(root) == before else "fail",
                    "raised ValueError: %.80s" % e)
            except Exception as e:
                rec("A3c wrong-ticket-id-void-refused", "fail", "%s: %s" % (type(e).__name__, e))

            # ---- A4 idempotence: first disposition stands, visible ----
            root = tmp / "a4"
            seed_blocked_doc(root)
            try:
                void_fn(ledger_dir(root), instance_id=INST, period=PERIOD,
                        ticket_id=TICKET, who=WHO, reason=REASON)
                before = dir_digest(root)
                out = void_fn(ledger_dir(root), instance_id=INST, period=PERIOD,
                              ticket_id=TICKET, who="host-2", reason="second attempt")
                rows = read_fn(ledger_dir(root)) if read_fn else []
                refused = isinstance(out, dict) and out.get("ok") is False
                names_first = refused and WHO in str(out.get("error") or "")
                good = refused and names_first and len(rows) == 1 and dir_digest(root) == before
                rec("A4 double-void-refused-names-first", "pass" if good else "fail",
                    "rows=%d refused=%s names_first=%s error=%r" % (len(rows), refused, names_first,
                                                                    (out or {}).get("error")))
            except Exception as e:
                rec("A4 double-void-refused-names-first", "fail", "%s: %s" % (type(e).__name__, e))

            # ---- A5 torn journal row does not block a fresh void ----
            root = tmp / "a5"
            seed_blocked_doc(root)
            with open(journal_file(root), "a", encoding="utf-8") as f:
                f.write("{torn line\n")
            seed2 = ledger_dir(root) / tick.ledger_file_name(INST, "20261009")
            seed2.write_text(json.dumps({"ticket_id": "t2", "blocked_reason": "x"}, ensure_ascii=False),
                             encoding="utf-8")
            try:
                out = void_fn(ledger_dir(root), instance_id=INST, period="20261009",
                              ticket_id="t2", who=WHO, reason=REASON)
                rows = read_fn(ledger_dir(root)) if read_fn else []
                mine = [r for r in rows if str(r.get("ticket_id")) == "t2"]
                rec("A5 torn-row-not-fatal", "pass" if (mine and len(mine) == 1) else "fail",
                    "ok=%r t2_rows=%d" % (out if not isinstance(out, dict) else out.get("ok"), len(mine)))
            except Exception as e:
                rec("A5 torn-row-not-fatal", "fail", "%s: %s" % (type(e).__name__, e))

            # ---- A6 findings not erased ----
            root = tmp / "a6"
            p = seed_blocked_doc(root)
            before_doc = json.loads(p.read_text("utf-8"))
            try:
                void_fn(ledger_dir(root), instance_id=INST, period=PERIOD,
                        ticket_id=TICKET, who=WHO, reason=REASON)
                after_doc = json.loads(p.read_text("utf-8"))
                same = all(after_doc.get(k) == before_doc.get(k) for k in ("blocked_reason", "findings", "ticket_id"))
                rec("A6 blocked-face-preserved-after-void", "pass" if same else "fail",
                    "blocked_reason_same=%s" % (after_doc.get("blocked_reason") == before_doc.get("blocked_reason")))
            except Exception as e:
                rec("A6 blocked-face-preserved-after-void", "fail", "%s: %s" % (type(e).__name__, e))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # ---- verdict ----
    fails = [r for r in results if r[1] == "fail"]
    envs = [r for r in results if r[1] == "env_fail"]
    nas = [r for r in results if r[1] == "na"]
    print("SUMMARY pass=%d fail=%d env_fail=%d na=%d" % (
        len(results) - len(fails) - len(envs) - len(nas), len(fails), len(envs), len(nas)))
    sys.exit(1 if fails or (nas and len(nas) == len(results)) else (2 if envs else 0))


if __name__ == "__main__":
    main()
