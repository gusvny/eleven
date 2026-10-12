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
           python3 certification-adapter.py round <project-key> <run-id>
Exit code is always 0 with a JSON receipt when the adapter itself ran; a
crash is a traceback on stderr (the reader names that too).

Round faces (t261012-03): the tab's Rounds table and the round dialog read
ONLY the faces the runner publishes at the stable path
(``integration/lib_round_face.py`` — the single writer). Two borrow rules
from the plan's fault-mode dispositions:
  - the lib's ``resolve_develop_dir`` scan is NOT imported: the adapter holds
    the validated project key, so it resolves
    ``<perkey_projects_root>/<key>/data/develop/rounds`` directly — the same
    directory the writer chose for that project; only the
    ``$SANDBAR_LINE_ROUND_FACE_DIR`` override is carried (verbatim, the test
    seam, same precedence the writer gives it);
  - the pinned vocabulary constants (CURRENT_NAME / FACE_NAME / LOG_NAME) and
    the pinned result-line regexes ARE imported — never re-spliced here.
The lib's FaceWriter IO is best-effort-but-named, so a run dir may exist
without its terminal face, and a ``current.json`` may name a pruned run:
every per-file read degrades to its OWN named state on the receipt — a
missing face is never replaced by counts, and a count the face itself marks
untrustworthy (``counts_note``) travels verbatim (KI-01M4P0FK2W87WXW2S6N8BXECYZ:
the table never renders zeros where a face should be).
"""

import json
import os
import re
import sys
import time
from pathlib import Path

# The engine modules live at server/engine; this file lives at
# server/plugins/executor-panel/src/host/. parents[4] is the server dir,
# parents[5] the repo root.
SERVER_DIR = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(SERVER_DIR / "engine"))
REPO_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO_ROOT / "integration"))

import develop_certify as dc  # noqa: E402
import develop_line as dl  # noqa: E402
import develop_promote as dp  # noqa: E402
import lib_round_face as lrf  # noqa: E402
import shared  # noqa: E402

#: The round dialog's failure rows render cap; the honest `more` count travels
#: beside it. A retention-independent reader cap (plan §B4): the writer's
#: FACE_RETAIN_ROUNDS is its disk economy, not a reader contract.
FAILURES_CAP = 20
#: The Rounds table's render cap, with an honest "N older rounds not shown".
ROUNDS_CAP = 20
#: A run id is a single path segment of the writer's own minting vocabulary
#: (`run-YYMMDD-HHMM` family): strict charset, no separators, no `..`.
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


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
    # t261009-67: the promotion signer's freeze face — the live episode, its
    # cause certification, and the chain of fix landings (with their current
    # repairs relations) read off the ledger by the engine's own derivation.
    freeze_summary = dc.open_freeze_summary(rows, line_id)
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
        "freezeSummary": freeze_summary,
        "waitStates": wait_states,
        "outcomes": outcomes,
        "certs": certs,
        "roundState": "idle",  # rule 9: records carry no chaining state yet
    }


# ---- round faces (t261012-03) -------------------------------------------

def rounds_dir(project):
    """The stable rounds path for ONE project: the override env carries the
    writer's FACE-dir semantics (`lib_round_face.resolve_develop_dir` returns
    it verbatim as the develop dir; the rounds live at `<face_dir>/rounds`),
    so the override is carried verbatim AND at the writer's level. A one-level
    divergence here renders sibling directories as phantom run rows and hides
    the real rounds, silently (acceptance_walkthrough gen1 probe; false-green
    family KI-01M4P0FK2W87WXW2S6N8BXECYZ). No projects-root scan (plan §B2):
    the key is validated upstream."""
    override = os.environ.get(lrf.FACE_DIR_ENV, "").strip()
    if override:
        return Path(override) / "rounds"
    return shared.perkey_projects_root() / project / "data" / "develop" / "rounds"


def read_face_json(path):
    """One face file -> its dict, or a named refusal. The writer's
    atomic_write_json (tmp+fsync+rename) means a torn read should not happen;
    an OSError or non-object JSON is still a NAMED state, never a default."""
    try:
        with open(path, encoding="utf-8") as fh:
            obj = json.load(fh)
    except FileNotFoundError:
        return None, None  # caller decides what absence means in its context
    except OSError as e:
        return None, "face unreadable: %s" % e
    except ValueError as e:
        return None, "face is not valid JSON: %s" % e
    if not isinstance(obj, dict):
        return None, "face is not a JSON object"
    return obj, None


def _face_sort_key(entry):
    """Newest first by the face's own started_at, run id as the tiebreak —
    never the mtime (a copied tree would reorder) and never the dir name's
    alphabetical order alone (the writer prunes by name, not by time)."""
    face = entry.get("face") if isinstance(entry.get("face"), dict) else {}
    started = face.get("started_at")
    return (started if isinstance(started, str) else "", entry.get("run_id", ""))


def read_round_faces(project):
    """The whole rounds path -> the receipt's `round_faces` section. One
    listing, ONE read per face file (never twice per row). Absence of
    current.json is the writer's own IDLE declaration — an empty live slot,
    not an error. Per-file states: {run_id, face} / {run_id, absent} (a run
    dir whose terminal face was never written — FaceWriter IO is
    best-effort) / {run_id, reason} (unreadable)."""
    rdir = rounds_dir(project)
    section = {"dir": str(rdir)}
    try:
        live, why = read_face_json(rdir / lrf.CURRENT_NAME)
        if why is not None:
            section["live"] = {"ok": False, "reason": why}
        elif live is not None:
            section["live"] = {"ok": True, "face": live}
        entries = []
        for d in sorted(rdir.iterdir()):
            if not d.is_dir():
                continue
            face, why = read_face_json(d / lrf.FACE_NAME)
            if why is None and face is not None:
                entries.append({"run_id": d.name, "face": face})
            elif why is None:
                # FaceWriter writes are best-effort-but-named: a dir without
                # its terminal face is the writer's own known state, named
                # here — never counts invented in its place.
                entries.append({"run_id": d.name,
                                "absent": "terminal face not written"})
            else:
                entries.append({"run_id": d.name, "reason": why})
    except OSError as e:
        section["error"] = "rounds path unreadable: %s" % e
        return section
    entries.sort(key=_face_sort_key, reverse=True)
    section["rounds"] = entries[:ROUNDS_CAP]
    if len(entries) > ROUNDS_CAP:
        section["older"] = len(entries) - ROUNDS_CAP
    return section


_RESULT_TAIL_RE = re.compile(r"\(([^()]*)\)\s*$")


def parse_failures(log_text, cap=FAILURES_CAP):
    """The retained suite log -> the dialog's failure rows. The pinned regexes
    are lib_round_face's own (one vocabulary; a vocabulary drift shows up as a
    missing row, never a wrong one — the lib's degrade rule). PASS lines are
    parsed too so `last judged` and a red round's full count can be named;
    only non-PASS verdicts become failure ROWS. Duration is the line's
    trailing `(…)` tail; a garbled line is skipped, never invented."""
    rows, seen, last = [], 0, None
    for line in (log_text or "").splitlines():
        line = line.strip()
        verdict = None
        for pattern, v in ((lrf._FAIL_RE, "fail"),
                           (lrf._ENV_FAIL_RE, "env_fail"),
                           (lrf._PASS_RE, "pass")):
            m = pattern.match(line)
            if m:
                verdict, name = v, m.group(1)
                break
        if verdict is None:
            continue
        seen += 1
        tail = _RESULT_TAIL_RE.search(line)
        row = {"name": name, "verdict": verdict,
               "duration": tail.group(1).strip() if tail else ""}
        # `last judged` carries the log's OWN verdict token (PASS/FAIL/ENV_FAIL)
        # — the face's vocabulary, not a re-spelled one.
        last = {"name": name, "verdict": verdict.upper(),
                "duration": row["duration"]}
        if verdict != "pass":
            rows.append(row)
    rows.sort(key=lambda r: 0 if r["verdict"] == "fail" else 1)
    return {"rows": rows[:cap], "more": max(0, len(rows) - cap),
            "judged": seen, "last": last}


def wrote_clauses(project, run_id):
    """The ONE Wrote line's facts: every delivery-ledger row citing this run
    (certifications carry a `run` field), plus every freeze episode whose
    `cause` is one of those certifications. Rows with a missing or non-string
    `run` field cannot cite this run and are ignored (plan §C4); rows of a
    foreign kind that DO cite the run are counted in a named note, not
    silently dropped."""
    ledger_dir_env = os.environ.get(dc.LEDGER_DIR_ENV, "").strip()
    delivery_path = dc.ledger_path(project) if ledger_dir_env else \
        shared.perkey_projects_root() / project / "ledger" / dc.MAIN_NAME
    try:
        rows, _bad = dc.read_rows(delivery_path)
    except Exception as e:  # noqa: BLE001 — one named clause, never a crash
        return ["the delivery ledger could not be read: %s" % e], ""
    clauses, cert_ids, foreign = [], set(), 0
    # The engine kinds that cite a run: certifications (the plan's Wrote
    # subject) and range growth (its range rows carry `run` too). Any OTHER
    # kind citing the run still renders its clause — nothing silently
    # dropped — and is counted in the note.
    run_citing_kinds = (dc.KIND_CERT, dc.KIND_RANGE_GROWTH)
    for r in rows:
        kind = r.get("kind")
        run = r.get("run")
        rid = r.get("id")
        if isinstance(run, str) and run == run_id:
            if kind == dc.KIND_CERT and isinstance(rid, str):
                cert_ids.add(rid)
                clauses.append("certification %s (line %s)"
                               % (rid, r.get("line", "?")))
            elif isinstance(rid, str):
                if kind not in run_citing_kinds:
                    foreign += 1
                clauses.append("%s %s" % (kind, rid))
        elif kind == dc.KIND_FREEZE and isinstance(r.get("cause"), str) \
                and r["cause"] in cert_ids:
            clauses.append("freeze %s opened (line %s)"
                           % (rid, r.get("line", "?")))
    note = "%d citing row(s) of an unrecognized kind" % foreign if foreign else ""
    return clauses, note


def round_receipt(project, run_id):
    """The `round` mode: one round's dialog facts from the retained evidence
    only — the terminal face verbatim-or-named, the failures parsed from the
    retained log, the ONE Wrote line, and the log path. No engine internals
    beyond the delivery ledger the tab already reads."""
    rdir = rounds_dir(project)
    run_dir = rdir / run_id
    receipt = {"ok": True, "project": project, "run": run_id,
               "face": None, "face_reason": None,
               "failures": None, "failures_absent": None,
               "trigger": None, "trigger_note": "",
               "wrote": [], "wrote_note": "",
               "log_path": str(run_dir / lrf.LOG_NAME),
               "log_absent": None}
    face, why = read_face_json(run_dir / lrf.FACE_NAME)
    if why is not None:
        receipt["face_reason"] = why
    elif face is None:
        # A running round has no terminal face yet: its LIVE face is the
        # record the dialog shows (the mock's result-so-far block) — but only
        # when the live pointer still names THIS run; another round's live
        # face is never borrowed.
        live, live_why = read_face_json(rdir / lrf.CURRENT_NAME)
        if live_why is None and live is not None and live.get("run_id") == run_id:
            face = live
        else:
            receipt["face_reason"] = "no terminal face is retained for this run"
    if face is not None:
        receipt["face"] = face
    try:
        log_text = (run_dir / lrf.LOG_NAME).read_text(encoding="utf-8",
                                                      errors="replace")
    except FileNotFoundError:
        receipt["log_absent"] = "retained log not written"
        # the Failures block names the same absence — an absent log is never
        # an empty failures table implying zero failures (plan §C3)
        receipt["failures_absent"] = receipt["log_absent"]
    except OSError as e:
        receipt["log_absent"] = "retained log unreadable: %s" % e
        receipt["failures_absent"] = receipt["log_absent"]
    else:
        receipt["failures"] = parse_failures(log_text)
    clauses, note = wrote_clauses(project, run_id)
    receipt["wrote"], receipt["wrote_note"] = clauses, note
    # Trigger: the run header's own `source` (auto/manual) — the header ledger
    # the tab already reads; an unset env or an absent header renders as a
    # named null, never as a guessed trigger word.
    headers, _bad, hwhy = read_run_headers()
    if hwhy:
        receipt["trigger_note"] = hwhy
    else:
        for h in headers or []:
            if h.get("id") == run_id:
                src = h.get("source")
                receipt["trigger"] = src if isinstance(src, str) and src else None
                break
    return receipt


def main(argv):
    # t261012-03: the round-dialog mode. Usage-refusal receipts, like every
    # refusal here — the reader surfaces them verbatim, never guesses.
    if len(argv) >= 2 and argv[1] == "round":
        if len(argv) != 4:
            _emit(_fail("usage: certification-adapter.py round <project-key> <run-id>"))
            return 0
        project, run_id = argv[2], argv[3]
        if not shared.PROJECT_KEY_RE.match(project):
            _emit(_fail("malformed project key %r" % project))
            return 0
        if not RUN_ID_RE.match(run_id) or ".." in run_id:
            _emit(_fail("malformed run id %r" % run_id[:80]))
            return 0
        _emit(round_receipt(project, run_id))
        return 0
    if len(argv) != 2:
        _emit(_fail("usage: certification-adapter.py <project-key>"))
        return 0
    project = argv[1]
    if not shared.PROJECT_KEY_RE.match(project):
        _emit(_fail("malformed project key %r" % project))
        return 0
    # t261012-03 (fault 2, acceptance_walkthrough gen1): the Rounds table's
    # source is INDEPENDENT of the line declaration's readability — a refusal
    # receipt still carries the round-faces section (best-effort: its own
    # failures are named inside the section), so the tab never loses the
    # table because lines.json or a ledger is unreadable.
    rounds_section = read_round_faces(project)

    def _refuse(reason):
        doc = _fail(reason)
        doc["round_faces"] = rounds_section
        _emit(doc)
        return 0

    try:
        lines = dl.load_lines(project)  # raises LineDeclarationError (named)
    except Exception as e:  # noqa: BLE001 — one receipt for every refusal
        return _refuse("%s: %s" % (type(e).__name__, e))

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
        return _refuse("delivery ledger has %d malformed line(s): %s"
                       % (len(bad), bad[0]))
    promo_path = dp.promotion_path(project) if ledger_dir_env else \
        shared.perkey_projects_root() / project / "ledger" / dp.PROMOTION_NAME
    promo, pbad = dp.read_promotion_rows(promo_path)
    if pbad:
        return _refuse("promotion ledger has %d malformed line(s): %s"
                       % (len(pbad), pbad[0]))
    # t261009-29: promotions share the delivery ledger's one seq space.
    allrows = list(rows) + list(promo)

    headers, hbad, hwhy = read_run_headers()
    if hbad:
        return _refuse("run headers ledger has %d malformed line(s): %s"
                       % (len(hbad), hbad[0]))
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
        # t261012-03: the Rounds table's own source — the faces the runner
        # publishes at the stable path. A section-level error (unreadable
        # path) degrades the TABLE by name while the rest of the tab's
        # receipt stays usable; it never fails the whole receipt.
        "round_faces": rounds_section,
    })
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
