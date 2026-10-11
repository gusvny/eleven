#!/usr/bin/env python3
"""line-face-adapter.py — the left column's engine-side line-face read adapter
(t261011-19). Structure and degradation discipline are pattern-copied from the
executor panel's certification-adapter.py (same directory depth: parents[4]
resolves to server/ from server/plugins/workbench/src/host/ — unit-asserted in
tests/t261011-19-line-face-ui.mjs). The full fault-mode trade-off checklist for
that borrowed implementation (nine source modes, each carried/not-carried with
handling) is in the create_plan gen1 report for this ticket.

Why this file exists: the left column's LineOn pill must show facts the ENGINE
derives, never a state the front end recomputes. This adapter imports the
engine's own modules (develop_line / develop_certify / develop_promote /
shared) and calls the real projection rules — freeze_state, ticket_wait_state
(landing by landing, with the engine's strict is_green contract),
ticket_outcome, run_verdict — over the develop ledgers, then emits ONE
single-line JSON receipt on stdout:

    {"ok": true, "project": ..., "frozen": <bool>, "faces": [
        {"ticket": ..., "line": ..., "face": ..., "overdue": <bool>}, ...]}

face ∈ on_line | waiting | red_implicated | certified | delivered | withdrawn
(the engine row words; on_line is the host layer's membership assembly, never
emitted here — a ticket with no landing row gets no entry at all). `overdue`
is the engine's own boolean (ticket_wait_state); no declared wait bound exists
in today's lines.json schema, so wait_bound_ms stays None and the flag is
honestly False until the engine declares a bound — the `!` pill suffix is
wired but never minted here.

Face precedence per ticket (engine words only, one pill per ticket):
  1. outcome.ending reverted/withdrawn  -> withdrawn
  2. outcome.delivered_in               -> delivered
  3. latest landing's ticket_wait_state -> certified | red_implicated | waiting
A ticket landed on several lines resolves to the line with the latest landing
at; ties break by landing id (deterministic, no clock race).

Reads (all under the project store, env-mapped like the engine reads them):
  <projects>/<key>/data/develop/lines.json            (load_lines)
  <projects>/<key>/ledger/delivery.jsonl              (one seq space)
  <projects>/<key>/ledger/promotions.jsonl
  $SANDBAR_RUNS_LEDGER                                (run headers)

Degradation contract (nothing is invented): malformed/missing declaration,
ledger rows the engine readers reject, an unset/empty $SANDBAR_RUNS_LEDGER
(NOT an empty-ledger default), or cited run headers absent while the line
carries certifications — each surfaces as a NAMED reason on the receipt, never
as a guessed state and never as a silent default green. Per-line failures
degrade that line only; other lines still emit faces. Nothing here writes:
no ledger append, no worktree, no lock.

Invocation: python3 line-face-adapter.py <project-key>
Exit code is always 0 with a JSON receipt when the adapter itself ran; a
crash is a traceback on stderr (the node.ts reader names that too: a non-zero
exit, empty stdout, or non-JSON stdout all become one named line_face_error
and the list passes through un-enriched).
"""

import json
import os
import sys
import time
from pathlib import Path

# The engine modules live at server/engine; this file lives at
# server/plugins/workbench/src/host/. parents[4] is the server dir.
SERVER_DIR = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(SERVER_DIR / "engine"))

import develop_certify as dc  # noqa: E402
import develop_line as dl  # noqa: E402
import develop_promote as dp  # noqa: E402
import shared  # noqa: E402

FACES = ("on_line", "waiting", "red_implicated", "certified",
         "delivered", "withdrawn")


def _fail(reason):
    """One named-refusal receipt; the reader turns it into ok:false verbatim."""
    return {"ok": False, "reason": str(reason)[:500]}


def _emit(doc):
    sys.stdout.write(json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n")


def read_run_headers():
    """Run headers from $SANDBAR_RUNS_LEDGER, with the engine readers' own
    strictness (same shape as dc.read_rows). An unset env is NOT an
    empty-ledger default: the caller sees the difference and a line holding
    certifications fails CLOSED (the engine's own is_green_not_injected rule,
    kept loud here instead of defused)."""
    raw = (os.environ.get("SANDBAR_RUNS_LEDGER") or "").strip()
    if not raw:
        return None, [], "SANDBAR_RUNS_LEDGER is not set — run headers are not resolvable"
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


def _is_green_factory(green_ids):
    return lambda run: run in green_ids


def line_faces(rows, line_id, is_green, now_ms):
    """One line's per-ticket faces, engine-derived. Raises (named) through —
    the caller turns it into that line's named degradation."""
    landings = [r for r in rows if r.get("kind") == dc.KIND_LANDING
                and r.get("line") == line_id]
    faces = {}
    for landing in landings:
        ticket = str(landing.get("ticket") or "")
        if not ticket:
            continue
        wait = dc.ticket_wait_state(rows, line_id, landing, is_green, now_ms)
        prev = faces.get(ticket)
        # Latest landing wins; ties break by landing id (deterministic).
        if prev is not None and (landing.get("at") or 0) < prev[0]:
            continue
        if prev is not None and (landing.get("at") or 0) == prev[0] \
                and str(landing.get("id") or "") <= prev[1]:
            continue
        state = str(wait.get("state") or "")
        face = {"waiting": "waiting", "certified": "certified",
                "red_implicated": "red_implicated",
                # reverted (a withdraws relation): the ticket's own life is
                # over — the pill vocabulary names it withdrawn.
                "reverted": "withdrawn"}.get(state)
        if face is None:
            continue
        faces[ticket] = (landing.get("at") or 0, str(landing.get("id") or ""),
                         {"ticket": ticket, "line": line_id, "face": face,
                          "overdue": wait.get("overdue") is True})
    outcomes = {}
    for ticket in sorted(faces):
        view = dp.ticket_outcome(rows, ticket, is_green,
                                 ticket_record={"kind": "change"})
        outcomes[ticket] = view
    return faces, outcomes


def main(argv):
    if len(argv) != 2:
        _emit(_fail("usage: line-face-adapter.py <project-key>"))
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

    # Ledger paths: identical resolution to certification-adapter.py (an
    # explicit SANDBAR_DELIVERY_LEDGER_DIR keeps its engine meaning; the
    # default splices the file name from the engine constants, never here).
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
    # Promotions share the delivery ledger's one seq space (t260910-04 rule).
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

    now_ms = int(time.time() * 1000)
    merged, notes, frozen_any = {}, [], False
    for line_id in lines:
        try:
            if dc.freeze_state(allrows, line_id).get("frozen"):
                frozen_any = True
            certs = [r for r in allrows if r.get("kind") == dc.KIND_CERT
                     and r.get("line") == line_id]
            if certs:
                # Fail-closed run-header rule (carried from the certification
                # adapter): a line with certifications and unreadable run
                # headers is a named refusal, never a default green.
                if hwhy:
                    raise dc.CertifyError(hwhy)
                missing = sorted({c["run"] for c in certs} - set(by_id))
                if missing:
                    raise dc.CertifyError(
                        "run headers absent for cited round(s): %s"
                        % ", ".join(missing))
                is_green = _is_green_factory(green_ids)
            else:
                is_green = None  # engine contract: no certs yet, None is honest
            faces, outcomes = line_faces(allrows, line_id, is_green, now_ms)
            for ticket, (_, _, entry) in faces.items():
                view = outcomes.get(ticket) or {}
                ending = str(view.get("ending") or "")
                if ending in ("withdrawn", "reverted"):
                    entry = dict(entry, face="withdrawn", overdue=False)
                elif view.get("delivered_in"):
                    entry = dict(entry, face="delivered", overdue=False)
                merged[ticket] = entry
        except Exception as e:  # noqa: BLE001 — that line's named degradation
            notes.append("line %s: %s: %s" % (line_id, type(e).__name__, e))

    _emit({
        "ok": True,
        "project": project,
        "frozen": frozen_any,
        "faces": [merged[t] for t in sorted(merged)],
        "notes": notes[:10],
        "runs_note": hwhy or "",
    })
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
