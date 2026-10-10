#!/usr/bin/env python3
"""certification-adapter.py — the read-only engine-side adapter of the executor
panel's Certification tab (t261009-44 Slice 2, plan §"the projection seam").

Why this file exists: the tab must show facts the ENGINE derives, not counts a
second implementation recomputes. This adapter imports the engine's own modules
(develop_line / develop_certify / develop_promote / shared) and calls the real
projection rules — ``freeze_state``, ``ticket_wait_state``, ``ticket_outcome``,
``run_verdict`` — over the develop ledgers, then emits ONE JSON receipt on
stdout (single line, like every engine receipt; the TS reader parses it
strictly). Nothing here writes: no ledger append, no worktree, no lock.

What it reads (all under the project store, env-mapped like the engine reads
them):
  <projects>/<key>/data/develop/lines.json   (line declaration, load_lines)
  <projects>/<key>/ledger/delivery.jsonl     (landings, certifications, freeze
                                              family, promotions, relations —
                                              the one seq space, t261009-29)
  <projects>/<key>/ledger/promotions.jsonl   (legacy promotion ledger; the
                                              migration face keeps it readable)
  $SANDBAR_RUNS_LEDGER                       (run headers, scenario-runs.jsonl
                                              shape; explicit env — the panel
                                              cannot guess a lane tree root)
  <projects>/<key>/data/tickets/<id>/archive.json  (title + epic per ticket)

Degradation contract (the ticket's "nothing is invented"): a malformed or
missing declaration / ledger rows the engine readers reject / a cited run
header that is absent — each surfaces as a NAMED reason on the receipt, never
as a guessed count and never as a silent default. Missing run headers while a
line carries certifications fail that line CLOSED (the engine's own
``is_green_not_injected`` rule, kept loud here instead of defused).

Invocation: python3 certification-adapter.py <project-key>
Exit code is always 0 with a JSON receipt when the adapter itself ran; a
crash is a traceback on stderr (the reader names that too).
"""

import json
import os
import sys
import time
from pathlib import Path

# The engine modules live at server/engine; this file lives at
# server/plugins/executor-panel/src/host/. parents[4] is the server dir.
SERVER_DIR = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(SERVER_DIR / "engine"))

import develop_certify as dc  # noqa: E402
import develop_line as dl  # noqa: E402
import develop_promote as dp  # noqa: E402
import shared  # noqa: E402


def _fail(reason):
    """One named-refusal receipt; the reader turns it into ok:false verbatim."""
    return {"ok": False, "reason": str(reason)[:500]}


def _emit(doc):
    sys.stdout.write(json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n")


def read_run_headers():
    """Run headers from $SANDBAR_RUNS_LEDGER, with the engine readers' own
    strictness (same shape as dc.read_rows: every non-object line is bad, bad
    is reported, never silently dropped — review C2b, KI-01M4HPGHVW…). An
    unset env is NOT an empty-ledger default: the caller sees the difference
    (absent_ledger: true) and a line holding certifications fails closed."""
    raw = (os.environ.get("SANDBAR_RUNS_LEDGER") or "").strip()
    if not raw:
        return None, [], "SANDBAR_RUNS_LEDGER is not set — run headers are not resolvable from the panel"
    headers, bad = [], []
    try:
        with open(raw, encoding="utf-8") as fh:
            for ln in fh:
                s = ln.strip()
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                except ValueError:
                    bad.append(s[:160])
                    continue
                if isinstance(obj, dict):
                    headers.append(obj)
                else:
                    bad.append(s[:160])
    except FileNotFoundError:
        return None, [], "run headers ledger is missing: %s" % raw
    except OSError as e:
        return None, [], "run headers ledger unreadable: %s (%s)" % (raw, e)
    return headers, bad[:10], None


def ticket_meta(project, tickets):
    """Title + epic straight from the ticket store archive; a ticket without a
    readable archive renders empty fields — data is never invented, and the
    archive path is the engine's own ``ticket_data_dir`` (same traversal
    guard). Malformed archive JSON is named per ticket in `meta_notes`."""
    meta, notes = {}, []
    for tid in tickets:
        try:
            path = shared.ticket_data_dir(project, tid) / "archive.json"
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
            m = doc.get("meta") if isinstance(doc, dict) else None
            m = m if isinstance(m, dict) else {}
            meta[tid] = {"title": m.get("title") if isinstance(m.get("title"), str) else "",
                         "epic": m.get("epic") if isinstance(m.get("epic"), str) else ""}
        except ValueError as e:
            notes.append("ticket %s archive malformed: %s" % (tid, e))
            meta[tid] = {"title": "", "epic": ""}
        except OSError:
            notes.append("ticket %s archive absent" % tid)
            meta[tid] = {"title": "", "epic": ""}
    return meta, notes[:10]


def line_input(rows, line_id, is_green, now_ms):
    """One line's model input, engine-derived. Raises CertifyError (named)
    through — the caller turns it into that line's named degradation."""
    freeze = dc.freeze_state(rows, line_id)
    landings = [r for r in rows if r.get("kind") == dc.KIND_LANDING
                and r.get("line") == line_id]
    wait_states = []
    for landing in landings:
        state = dc.ticket_wait_state(rows, line_id, landing, is_green, now_ms)
        wait_states.append({"ticket": landing.get("ticket"), **state})
    tickets = sorted({str(w.get("ticket")) for w in landings})
    outcomes = []
    for ticket in tickets:
        view = dp.ticket_outcome(rows, ticket, is_green,
                                 ticket_record={"kind": "change"})
        outcomes.append({"ticket": ticket,
                         "delivered_in": view.get("delivered_in"),
                         "ending": view.get("ending")})
    certs = [{"id": r["id"], "run": r["run"], "at": r["at"]}
             for r in rows if r.get("kind") == dc.KIND_CERT
             and r.get("line") == line_id]
    return {
        "line": {"line_id": line_id},
        "freeze": freeze,
        "waitStates": wait_states,
        "outcomes": outcomes,
        "certs": certs,
        "roundState": "idle",  # rule 9: records carry no chaining state yet
    }


def main(argv):
    if len(argv) != 2:
        _emit(_fail("usage: certification-adapter.py <project-key>"))
        return 0
    project = argv[1]
    try:
        if not shared.PROJECT_KEY_RE.match(project):
            _emit(_fail("malformed project key %r" % project))
            return 0
        lines = dl.load_lines(project)  # raises LineDeclarationError (named)
    except Exception as e:  # noqa: BLE001 — one receipt for every refusal
        _emit(_fail("%s: %s" % (type(e).__name__, e)))
        return 0

    # Ledger paths: an explicit SANDBAR_DELIVERY_LEDGER_DIR keeps its engine
    # meaning (a flat dir of <project>.jsonl files, dc.ledger_path resolves);
    # the default is the per-key project store's ledger home — built from
    # shared.perkey_projects_root (SANDBAR_PROJECTS_DIR-aware, the same env the
    # engine's other faces read) + the ledger module's own MAIN_NAME, so the
    # file name is spliced by the engine constant, never re-spliced here.
    ledger_dir_env = os.environ.get(dc.LEDGER_DIR_ENV, "").strip()
    delivery_path = dc.ledger_path(project) if ledger_dir_env else \
        shared.perkey_projects_root() / project / "ledger" / dc.MAIN_NAME
    rows, bad = dc.read_rows(delivery_path)
    if bad:
        _emit(_fail("delivery ledger has %d malformed line(s): %s"
                    % (len(bad), bad[0])))
        return 0
    promo_path = dp.promotion_path(project) if ledger_dir_env else \
        shared.perkey_projects_root() / project / "ledger" / dp.PROMOTION_NAME
    promo, pbad = dp.read_promotion_rows(promo_path)
    if pbad:
        _emit(_fail("promotion ledger has %d malformed line(s): %s"
                    % (len(pbad), pbad[0])))
        return 0
    # t261009-29: promotions share the delivery ledger's one seq space.
    allrows = list(rows) + list(promo)

    headers, hbad, hwhy = read_run_headers()
    if hbad:
        _emit(_fail("run headers ledger has %d malformed line(s): %s"
                    % (len(hbad), hbad[0])))
        return 0
    headers = headers or []
    by_id = {h.get("id"): h for h in headers}
    green_ids = {hid for hid, h in by_id.items()
                 if dc.run_verdict(h.get("cases")) == "green"}
    runs = [{"id": h.get("id"), "cases": h.get("cases"),
             "verdict": dc.run_verdict(h.get("cases")),
             "source": h.get("source"), "started_at": h.get("started_at"),
             "repos": h.get("repos")} for h in headers]

    now_ms = int(time.time() * 1000)
    per_line, meta_notes = {}, []
    all_tickets = sorted({str(r.get("ticket")) for r in allrows
                          if r.get("kind") == dc.KIND_LANDING})
    meta, meta_notes = ticket_meta(project, all_tickets)
    for line_id, line in lines.items():
        try:
            certs = [r for r in allrows if r.get("kind") == dc.KIND_CERT
                     and r.get("line") == line_id]
            if certs:
                # Fail-closed run-header rule: once the line carries
                # certifications, a caller that cannot read runs must say so,
                # and a cited run missing from the headers is a named refusal —
                # never a default green (develop_certify.ticket_wait_state's
                # own is_green contract, kept loud at the boundary).
                if hwhy:
                    raise dc.CertifyError(hwhy)
                missing = sorted({c["run"] for c in certs} - set(by_id))
                if missing:
                    raise dc.CertifyError(
                        "run headers absent for cited round(s): %s" % ", ".join(missing))
                is_green = lambda run: run in green_ids  # noqa: E731
            else:
                is_green = None  # engine contract: no certs yet, None is honest
            inp = line_input(allrows, line_id, is_green, now_ms)
            inp["line"] = {"line_id": line_id, "scope": line.scope,
                           "owner": line.owner}
            inp["runs"] = runs
            inp["ticketMeta"] = meta
            per_line[line_id] = {"ok": True, "input": inp}
        except Exception as e:  # noqa: BLE001 — the line's named degradation
            per_line[line_id] = {"ok": False,
                                 "reason": "%s: %s" % (type(e).__name__, e)}

    _emit({
        "ok": True,
        "project": project,
        "lines": [{"line_id": l.line_id, "scope": l.scope, "owner": l.owner}
                  for l in lines.values()],
        "per_line": per_line,
        "meta_notes": meta_notes,
        "runs_note": hwhy or "",
    })
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
