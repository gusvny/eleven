# -*- coding: utf-8 -*-
"""run_watch —— the executor's run watch over the delivery ledger (t261019-25,
redo of t261019-14; design authority docs/design/executor-operational-envelope-v1.md
section 1, host order 261019).

Problem it closes: nobody owns the run face. A red certification freezes the
line and nothing acts on it; a round that stops running is only noticed by
whoever happens to look (measured 261018-19: both freezes of the night were
raised and cleared by hand by integration, hours apart).

The contract (section 1, verbatim in spirit): once per tick, per declared
line, the watch reads the delivery ledger and the rounds directory and takes
EXACTLY ONE of:

  green certification                  -> nothing
  red, environment-only regressions    -> name the environment face; record the
                                          closure through the engine's own
                                          releasing rule (a ``closed``
                                          freeze-change row) ONLY when a green
                                          certification after the red exists,
                                          else open a fix ticket citing the
                                          evidence row
  red with content regressions         -> open (or reuse) a fix ticket naming
                                          the regressing cases and the run id;
                                          never a rerun for a new answer
  pending landings, no round N hours   -> a ``run-stalled`` request naming the
                                          last round, its verdict and the
                                          pending range
  a round that ended without a row     -> name it, retry once; a second silent
                                          end is a ``run-silent`` request,
                                          never a silent accept

Hard boundaries (design section 2 tier table):
  - the watch NEVER writes a certification, NEVER edits a run record, NEVER
    lifts a judgement stop;
  - it is read-only over the ledger and the rounds directory; the only writes
    are fix tickets (through the engine client's dev-lane start seam),
    closure rows (through the engine's own writer ``develop_certify.append_rows``),
    and requests (``executor_requests.append_request``) — every action carries
    the row id(s) it acted on.

Inputs are the records, nothing else (no second source of truth):
  - delivery ledger: ``develop_certify.ledger_path`` (certs cite runs; the
    verdict lives on the run header, never on the cert);
  - run headers: ``<ledger dir>/scenario-runs.jsonl`` (the store the round
    itself writes; scenario_ledger's shape run-ledger-v1);
  - run case rows: ``integration/scenario_ledger``'s store (per-scenario
    verdicts — the evidence that names an environment face);
  - rounds directory: ``<develop_dir>/rounds/<run_id>/face.json`` terminal
    faces plus the live ``current.json`` (lib_round_face's contract).

Declared liberty (review gen1 R2, binding): ``run_watch_state.json`` under the
ledger directory holds ONLY idempotency keys (opened fix ticket per run id,
filed request per evidence key) and the silent-round retry counter. It holds
NO fact the ledger owns — no verdicts, no freeze state. A missing or corrupt
state file is treated as EMPTY (fail toward RE-action, never toward silence)
and the corruption is named in the tick result.

Fail directions (review gen1 R4 / C1):
  - a red run whose case rows are absent or unreadable classifies as NOT
    environment-only -> fix ticket. Env-only is only ever classified on
    present evidence;
  - a red with BOTH kinds of regressions is a content red (the env-only gate
    requires failed == 0), so the mixed red opens a fix ticket, never a
    closure.

Import discipline: temporalio-free and engine-import-light — every engine and
integration import is lazy inside a function, so the decision core is unit
testable in a bare interpreter (the same discipline executor_delivery follows).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

#: "no round for N hours" — the design's N. Override: env
#: SANDBAR_RUN_WATCH_STALLED_HOURS (a malformed value falls back to the
#: default, named in the tick result, never guessed differently silently).
STALLED_HOURS_DEFAULT = 6.0
STALLED_HOURS_ENV = "SANDBAR_RUN_WATCH_STALLED_HOURS"

STATE_NAME = "run_watch_state.json"
RUNS_NAME = "scenario-runs.jsonl"
FORCE_MARKER_NAME = "run-watch-force"

REQUEST_KIND_STALLED = "run-stalled"
REQUEST_KIND_SILENT = "run-silent"

ACTIONS = ("none", "close_freeze", "fix_ticket", "request", "retry_round")


# ---------- small helpers (pure) ----------


def stalled_ms_from_env(env: Optional[Dict[str, str]] = None) -> Tuple[float, str]:
    """The N-hours threshold. Returns (ms, note) — a malformed override keeps
    the default and SAYS so (a silent fallback would look like a decision)."""
    env = dict(os.environ if env is None else env)
    raw = str(env.get(STALLED_HOURS_ENV) or "").strip()
    if not raw:
        return STALLED_HOURS_DEFAULT * 3600.0 * 1000.0, ""
    try:
        hours = float(raw)
        if hours <= 0:
            raise ValueError("not positive")
        return hours * 3600.0 * 1000.0, ""
    except ValueError:
        return (STALLED_HOURS_DEFAULT * 3600.0 * 1000.0,
                "stalled_hours_override_malformed:%r" % raw)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _integration_dir() -> Path:
    return _repo_root() / "integration"


def _certs(rows: List[dict], line: str) -> List[dict]:
    import develop_certify as dc
    return dc._of_kind(rows, dc.KIND_CERT, line)


def _landings(rows: List[dict], line: str) -> List[dict]:
    import develop_certify as dc
    return dc._of_kind(rows, dc.KIND_LANDING, line)


def header_verdicts(headers: List[dict]) -> Dict[str, str]:
    """run id -> header verdict, for the ids whose header is well-shaped
    enough to carry one. A malformed header is simply absent here (the caller
    names the gap), never guessed green."""
    out: Dict[str, str] = {}
    for h in headers or ():
        if isinstance(h, dict) and isinstance(h.get("id"), str) \
                and h.get("verdict") in ("green", "red"):
            out[h["id"]] = h["verdict"]
    return out


def classify_red(header: dict, case_rows: List[dict],
                 case_rows_readable: bool = True) -> Dict[str, Any]:
    """Classify one red run: environment-only vs content. Returns a dict with
    ``env_only`` (bool), ``content_names`` / ``env_names`` (evidence scenario
    names from the run's case rows), ``cases`` (the header's own counts) and
    ``case_rows_readable`` (whether the per-scenario evidence was present).

    Fail direction (review R4, binding): env-only is only ever classified on
    PRESENT evidence — the header counts AND readable case rows. When the case
    rows are absent (retention rolled them) the classification fails toward
    "not environment-only" -> fix ticket, never toward a records-only closure."""
    cases = (header or {}).get("cases") or {}
    failed = int(cases.get("failed") or 0)
    env_failed = int(cases.get("env_failed") or 0)
    content_names: List[str] = []
    env_names: List[str] = []
    for r in case_rows or ():
        if not isinstance(r, dict) or r.get("run") != (header or {}).get("id"):
            continue
        v = r.get("verdict")
        name = str(r.get("scenario") or "")
        if v == "fail" and name:
            content_names.append(name)
        elif v == "env_fail" and name:
            env_names.append(name)
    env_only = (case_rows_readable and failed == 0 and env_failed > 0)
    return {"env_only": env_only,
            "content_names": sorted(set(content_names)),
            "env_names": sorted(set(env_names)),
            "case_rows_readable": bool(case_rows_readable),
            "cases": cases}


def _is_green_lookup(verdicts: Dict[str, str]) -> Callable[[Any], bool]:
    """The ``is_green`` callable develop_certify's coverage faces take: a run
    id is green iff its run header says green. An unknown run is NOT green
    (a caller that cannot read runs must say so, not guess)."""
    return lambda rid: verdicts.get(rid) == "green"


# ---------- read faces (file IO, named degrade) ----------


def read_ledger_rows(project: str, ledger_dir: Optional[str] = None
                     ) -> Tuple[List[dict], List[str], Path]:
    """The delivery ledger's rows for one project, through the engine's own
    reader (develop_certify.read_rows — malformed lines are returned, never
    swallowed). Returns (rows, bad_lines, ledger_path)."""
    import develop_certify
    path = develop_certify.ledger_path(project, ledger_dir)
    rows, bad = develop_certify.read_rows(path)
    return rows, list(bad or []), Path(path)


def read_run_headers(ledger_path: Path) -> Tuple[List[dict], List[str]]:
    """The run headers from the ledger directory (the round's own store).
    A malformed line is named, never swallowed; an absent file is an empty
    ledger, not an error."""
    target = Path(ledger_path).parent / RUNS_NAME
    headers: List[dict] = []
    bad: List[str] = []
    try:
        with open(str(target), encoding="utf-8") as fh:
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
        return [], []
    except OSError as e:
        bad.append("runs_store_unreadable:%s:%s" % (type(e).__name__, e))
        return [], bad
    return headers, bad


def read_case_rows(run_id: str, env: Optional[Dict[str, str]] = None
                   ) -> Tuple[List[dict], str]:
    """The scenario case rows of one run, from integration/scenario_ledger's
    store (its SANDBAR_SCENARIO_LEDGER_DIR override is honoured, so tests pin
    a temp store). Returns (rows, note) — an unloadable module or unreadable
    store returns an empty list with a NAMED note (the caller fails toward
    'not environment-only', R4), never a guessed classification."""
    import sys
    int_dir = str(_integration_dir())
    if int_dir not in sys.path:
        sys.path.insert(0, int_dir)
    try:
        import scenario_ledger
    except Exception as e:  # noqa: BLE001 — named degrade, not a crash
        return [], "case_rows_module_unavailable:%s:%s" % (type(e).__name__, e)
    try:
        rows, _bad = scenario_ledger.read_rows()
    except Exception as e:  # noqa: BLE001
        return [], "case_rows_store_unreadable:%s:%s" % (type(e).__name__, e)
    return [r for r in (rows or []) if isinstance(r, dict)
            and r.get("run") == run_id], ""


def read_rounds(project: str, env: Optional[Dict[str, str]] = None
                ) -> Tuple[List[dict], List[str]]:
    """The rounds directory faces for one project: one entry per RETAINED
    terminal face (state done/failed with its outcome verdict), sorted by
    started_at, plus ``live`` for a present current.json (a round in flight —
    never treated as an ended round). Malformed faces are named, never
    guessed."""
    import shared
    rounds_dir = Path(shared.develop_dir(project)) / "rounds"
    env = dict(os.environ if env is None else env)
    override = str(env.get("SANDBAR_LINE_ROUND_FACE_DIR") or "").strip()
    if override:
        rounds_dir = Path(override)
    faces: List[dict] = []
    bad: List[str] = []
    live = False
    try:
        names = sorted(p.name for p in rounds_dir.iterdir() if p.is_dir())
    except OSError as e:
        if not Path(rounds_dir).exists():
            return [], []  # no rounds yet = an empty history, not an error
        return [], ["rounds_dir_unreadable:%s:%s" % (type(e).__name__, e)]
    for name in names:
        run_dir = rounds_dir / name
        face_path = run_dir / "face.json"
        try:
            face = json.loads(face_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            bad.append("face_unreadable:%s:%s" % (name, type(e).__name__))
            continue
        if not isinstance(face, dict):
            bad.append("face_not_object:%s" % name)
            continue
        outcome = face.get("outcome") or {}
        faces.append({
            "run_id": str(face.get("run_id") or name),
            "state": face.get("state"),
            "verdict": outcome.get("verdict") if isinstance(outcome, dict) else None,
            "reason": (outcome.get("reason") or "") if isinstance(outcome, dict) else "",
            "started_at": str(face.get("started_at") or ""),
            "updated_at": str(face.get("updated_at") or ""),
        })
    if (rounds_dir / "current.json").exists():
        live = True
    faces.sort(key=lambda f: f["started_at"] or f["updated_at"])
    if faces:
        faces[-1]["live_after"] = live
    return faces, bad


# ---------- state (the declared liberty, review gen1 R2) ----------


def state_path(ledger_path: Path) -> Path:
    return Path(ledger_path).parent / STATE_NAME


def load_state(path: Path) -> Tuple[dict, str]:
    """Load the idempotency state. Absent = empty (fresh watch). Corrupt =
    EMPTY + a named note (fail toward RE-action, never toward silence — the
    review's binding condition). The file holds no ledger-owned fact, so an
    empty reset can never contradict the records; at worst it re-files a
    deduped action the records can absorb."""
    try:
        obj = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, ""
    except (OSError, ValueError) as e:
        return {}, "state_unreadable_treated_empty:%s:%s" % (type(e).__name__, e)
    if not isinstance(obj, dict):
        return {}, "state_not_object_treated_empty"
    out = {"fix_tickets": {}, "requests": {}, "silent_retry": {}}
    for key in out:
        v = obj.get(key)
        if isinstance(v, dict):
            out[key] = {str(k): v[k] for k in v}
    return out, ""


def save_state(path: Path, state: dict) -> str:
    """Atomic-ish write (tmp + rename in the same directory). A failed write
    is named; the caller still returns its action (the write happened through
    the real writers — only the idempotency memory is at risk, and its fail
    direction is re-action)."""
    tmp = Path(str(path) + ".tmp-%d" % os.getpid())
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True),
                       encoding="utf-8")
        os.replace(str(tmp), str(path))
        return ""
    except OSError as e:
        try:
            tmp.unlink()
        except OSError:
            pass
        return "state_write_failed:%s:%s" % (type(e).__name__, e)


# ---------- decision (PURE — no IO, no clock, no writes) ----------


def decide(rows: List[dict], line: str, headers: List[dict],
           rounds: List[dict],
           case_rows_fn: Callable[[str], Tuple[List[dict], str]],
           state: dict, now_ms: int, stalled_ms: float) -> Dict[str, Any]:
    """One action per tick, precedence in spec order (review C1: the content
    red is judged BEFORE the env-only gate, so a mixed red is a content red).

    ``case_rows_fn(run_id)`` supplies the run's scenario rows (injected so the
    decision stays pure; the caller wires the store read). All other inputs
    are records. The returned action dict always names the row ids it acted
    on (``evidence``)."""
    import develop_certify as dc

    certs = _certs(rows, line)
    verdicts = header_verdicts(headers)
    is_green = _is_green_lookup(verdicts)
    anomalies: List[str] = []

    def _terminal_rounds() -> List[dict]:
        return [f for f in rounds if f.get("state") in ("done", "failed")]

    def _pending_landings() -> List[dict]:
        rng = dc.derive_range(rows, line)
        return list(rng.get("covered_landings") or [])

    def _stalled_or_silent() -> Optional[Dict[str, Any]]:
        pending = _pending_landings()
        oldest = min([int(l.get("at") or 0) for l in pending], default=0)
        terminal = _terminal_rounds()
        last_round = terminal[-1] if terminal else None
        # --- stalled: pending landings, no round for N hours -------------
        if pending and oldest > 0 and (now_ms - oldest) > stalled_ms:
            last_ended = last_round is not None and not last_round.get("live_after")
            if last_ended or last_round is None:
                # "naming the last round, its verdict": the newest round face;
                # with no round face at all, the last certification's run is
                # the closest thing to a last round the records hold.
                line_certs = _certs(rows, line)
                last_cert = line_certs[-1] if line_certs else None
                last_id = ((last_round or {}).get("run_id")
                           or (last_cert or {}).get("run"))
                last_verdict = ((last_round or {}).get("verdict")
                                or header_verdicts(headers).get(last_id))
                req_id = "run-stalled:%s:%s" % (line, pending[0].get("id"))
                return {
                    "action": "request",
                    "kind": REQUEST_KIND_STALLED,
                    "evidence": {"pending_landings": [l.get("id") for l in pending],
                                 "oldest_landing_at": oldest,
                                 "last_round": last_id,
                                 "last_round_verdict": last_verdict,
                                 "line": line},
                    "request_kind": REQUEST_KIND_STALLED,
                    # <= 60 chars (the request card limit, executor_requests
                    # QUESTION_MAX) even for long line ids; the detail carries
                    # the round id, its verdict and the pending range
                    "question": ("run-stalled on line %s: %d pending "
                                 "landing(s)" % (line, len(pending))),
                    "detail": {"pending": [l.get("id") for l in pending],
                               "oldest_landing_at": oldest,
                               "last_round": last_id,
                               "verdict": last_verdict,
                               "line": line},
                    "dedupe_key": req_id,
                }
        # --- silent: a round that ended without a run row ----------------
        for face in reversed(terminal):
            rid = face.get("run_id") or ""
            has_row = rid in verdicts or any(
                c.get("run") == rid for c in certs)
            if has_row:
                break  # the newest ended round answered; nothing silent after it
            retries = int((state.get("silent_retry") or {}).get(rid) or 0)
            evidence = {"round": rid, "state": face.get("state"),
                        "reason": face.get("reason"), "line": line}
            if retries == 0:
                return {"action": "retry_round", "evidence": evidence,
                        "run_id": rid,
                        "note": "round ended without a run row; retrying once"}
            dedupe = "run-silent:%s:%s" % (line, rid)
            return {
                "action": "request",
                "kind": REQUEST_KIND_SILENT,
                "evidence": evidence,
                "request_kind": REQUEST_KIND_SILENT,
                "question": "run-silent on line %s: no run row" % line,
                "detail": {"round": rid, "reason": face.get("reason"),
                           "state": face.get("state"), "line": line,
                           "retried": True},
                "dedupe_key": dedupe,
            }
        return None

    # --- open freeze whose cause is an env-only red (any age) ------------
    # The closure question is about the FREEZE, not about the latest cert: a
    # releasing green certification that FOLLOWED the red is by definition
    # newer than it, so the latest cert is green exactly when the closure is
    # possible. Judgement stops / content freezes are never touched here.
    import develop_certify as dc
    fs = dc.freeze_state(rows, line)
    if fs.get("frozen") and fs.get("cause"):
        cause_cert = next((c for c in certs if c.get("id") == fs["cause"]), None)
        cause_run = (cause_cert or {}).get("run")
        cause_header = next((h for h in headers
                             if isinstance(h, dict) and h.get("id") == cause_run), None)
        if cause_cert is not None and verdicts.get(cause_run) == "red" \
                and cause_header is not None:
            case_rows_c, case_note_c = case_rows_fn(cause_run)
            if case_note_c:
                anomalies.append("case_rows_unreadable:%s:%s"
                                 % (cause_run, case_note_c))
            cls_f = classify_red(cause_header, case_rows_c,
                                 case_rows_readable=bool(case_rows_c))
            counts = (cause_header.get("cases") or {})
            env_shaped = (int(counts.get("failed") or 0) == 0
                          and int(counts.get("env_failed") or 0) > 0)
            if cls_f["env_only"]:
                releasing = dc._releasing_green_cert(rows, line, cause_cert,
                                                     is_green)
                if releasing is not None:
                    return {"action": "close_freeze",
                            "evidence": {"freeze": fs.get("episode"),
                                         "red_cert": cause_cert.get("id"),
                                         "run": cause_run,
                                         "releasing_cert": releasing.get("id"),
                                         "line": line},
                            "env_faces": cls_f["env_names"]}
                return _fix_ticket_action(
                    line, cause_run, cause_cert,
                    cls_f["env_names"] or
                    ["<environment face unnamed — case rows unavailable>"],
                    state, kind="environment")
            if env_shaped and not cls_f["case_rows_readable"]:
                # review R4: env-only is only classified on present evidence;
                # with the case rows gone the closure fails toward the
                # human-checkable action — the fix ticket, never the records-
                # only closure.
                return _fix_ticket_action(
                    line, cause_run, cause_cert,
                    ["<case rows unavailable — env-only not provable>"],
                    state, kind="environment")

    latest = certs[-1] if certs else None
    if latest is not None:
        rid = latest.get("run")
        header = next((h for h in headers
                       if isinstance(h, dict) and h.get("id") == rid), None)
        if latest.get("run") and verdicts.get(rid) == "green":
            sub = _stalled_or_silent()
            if sub:
                return sub
            return {"action": "none",
                    "note": "latest certification is green",
                    "evidence": {"cert": latest.get("id"), "run": rid}}
        if latest.get("run") and verdicts.get(rid) == "red":
            if header is None:
                # A red cert citing a run whose header is gone is a named
                # anomaly — never classified, never closed over.
                anomalies.append("red_cert_run_header_missing:%s:%s"
                                 % (latest.get("id"), rid))
            else:
                case_rows, case_note = case_rows_fn(rid)
                if case_note:
                    anomalies.append("case_rows_unreadable:%s:%s" % (rid, case_note))
                cls = classify_red(header, case_rows,
                                   case_rows_readable=bool(case_rows))
                freeze_open, episode = _open_freeze_for(rows, line, latest.get("id"))
                if not cls["env_only"]:
                    # content red (includes the mixed red, review C1)
                    return _fix_ticket_action(
                        line, rid, latest, cls["content_names"] or
                        ["<case rows unavailable — classification stayed content>"],
                        state, kind="content")
                # environment-only
                if freeze_open:
                    releasing = dc._releasing_green_cert(rows, line, latest, is_green)
                    if releasing is not None:
                        return {
                            "action": "close_freeze",
                            "evidence": {"freeze": episode, "red_cert": latest.get("id"),
                                         "run": rid, "releasing_cert": releasing.get("id")},
                            "env_faces": cls["env_names"],
                        }
                    return _fix_ticket_action(
                        line, rid, latest, cls["env_names"] or
                        ["<environment face unnamed — case rows unavailable>"],
                        state, kind="environment")
                later_green = any(c.get("seq", 0) > latest.get("seq", 0)
                                  and verdicts.get(c.get("run")) == "green"
                                  for c in certs)
                if later_green:
                    sub = _stalled_or_silent()
                    if sub:
                        return sub
                    return {"action": "none",
                            "note": ("env-only red already released: a green "
                                     "certification follows it"),
                            "evidence": {"red_cert": latest.get("id"), "run": rid}}
                return _fix_ticket_action(
                    line, rid, latest, cls["env_names"] or
                    ["<environment face unnamed — case rows unavailable>"],
                    state, kind="environment")
        elif latest.get("run") and rid not in verdicts:
            # no readable header for the cited run (missing or malformed
            # verdict) — a named anomaly, never classified, never closed over
            anomalies.append("latest_cert_run_header_missing:%s:%s"
                             % (latest.get("id"), rid))
    sub = _stalled_or_silent()
    if sub:
        if anomalies:
            sub["anomalies"] = anomalies
        return sub
    out = {"action": "none", "note": "no actionable run face",
           "evidence": {"line": line}}
    if anomalies:
        out["anomalies"] = anomalies
    return out


def _open_freeze_for(rows: List[dict], line: str,
                     cert_id: str) -> Tuple[bool, Optional[str]]:
    """Is there an OPEN freeze episode whose cause is this certification?
    Replays the change records exactly as develop_certify.freeze_state does,
    but keyed to a cause rather than to the latest episode."""
    import develop_certify as dc
    episodes = [r for r in rows if isinstance(r, dict)
                and r.get("kind") == dc.KIND_FREEZE
                and r.get("line") == line and r.get("cause") == cert_id]
    if not episodes:
        return False, None
    ep = episodes[-1]
    frozen = True
    for ch in dc._of_kind(rows, dc.KIND_FREEZE_CHANGE, line):
        if ch.get("freeze") != ep.get("id"):
            continue
        if ch.get("change") == dc.CHANGE_CLOSED:
            frozen = False
        elif ch.get("change") == dc.CHANGE_REOPENED:
            frozen = True
    return frozen, ep.get("id")


def _fix_ticket_action(line: str, run_id: str, cert: dict, names: List[str],
                       state: dict, kind: str) -> Dict[str, Any]:
    """The fix-ticket action, reuse-first (review R3): the state's run-id ->
    ticket-id memory is checked first; the caller still liveness-checks the
    ticket through the injected ``ticket_open`` seam. The dedupe key is the
    run id — one red run, one fix ticket, never a rerun for a new answer."""
    known = (state.get("fix_tickets") or {}).get(run_id)
    return {
        "action": "fix_ticket",
        "kind": kind,
        "evidence": {"red_cert": cert.get("id"), "run": run_id, "line": line,
                     "cases": list(names)},
        "run_id": run_id,
        "names": list(names),
        "known_ticket": known,
        "title": "Fix %s regression on line %s (run %s)" % (kind, line, run_id),
        "body": ("Run watch (%s red): run %s regressed on line %s. Certification "
                 "%s. Cases: %s. Evidence: delivery-ledger cert %s, run header "
                 "%s. Do not re-run for a new answer; the range only grows."
                 % (kind, run_id, line, cert.get("id"),
                    ", ".join(names) or "(none named)", cert.get("id"), run_id)),
    }


# ---------- write actions (the only writes the watch may make) ----------


def _executor_request_env(project: str) -> Tuple[Optional[Dict[str, str]], str]:
    """The identity env for a watch-filed request: the project's DECLARED
    executor session (the executor owns the run face, so the request is filed
    under its name — never an invented session). No declared session = a named
    refusal and NO write (fail-closed; the executor declaration is a host
    decision)."""
    import executor_grants
    import shared
    load = executor_grants.load_declaration(project)
    sessions = list(load.get("executor_sessions") or ()) if load.get("ok") else ()
    if not sessions:
        return None, ("no_declared_executor_session:%s — the watch files no "
                      "request (the host names the executor session in the "
                      "declaration)" % project)
    return {shared.CALLER_PROJECT_ENV: project,
            executor_grants.CALLER_SESSION_ENVS[0]: str(sessions[0]),
            shared.CALLER_IDENTITY_SRC_ENV: "declared-session"}, ""


def append_request_row(project: str, kind: str, question: str,
                       detail: Dict[str, Any], now_ms: int,
                       env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """One request row through executor_requests.append_request (the module's
    own writer — the watch is not a second writer). Returns the receipt or
    refusal verbatim; a refusal writes nothing."""
    import executor_requests
    body = {"kind": kind, "question": question[:400],
            "detail": json.dumps(detail, ensure_ascii=False, sort_keys=True)[:800],
            "default_action": "run-watch re-checks the records next tick"}
    ident, note = _executor_request_env(project)
    if ident is None:
        return {"ok": False, "field": "identity", "error": note}
    # identity keys OVERRIDE the base env (a poisoned ambient session id can
    # never leak into the row); ledger-LOCATION keys forward from the base.
    use_env = dict(os.environ if env is None else env)
    use_env.update(ident)
    # delivered_via="engine-process" (truthful: the watch runs in the engine
    # worker) — the identity names the DECLARED executor session the run face
    # belongs to, but the append is performed by the engine on its behalf.
    return executor_requests.append_request(body, now_ms, env=use_env,
                                            cwd=str(_repo_root()),
                                            delivered_via="engine-process")


def close_freeze_row(project: str, evidence: Dict[str, Any], at_ms: int,
                     ledger_dir: Optional[str] = None) -> Dict[str, Any]:
    """The closure write: ONE ``closed`` freeze-change row through the
    engine's own writer, citing the releasing green certification by id (an
    evidence stop lifted without a cited row id is a defect, design section 2).
    A content red can never reach here — decide() only emits close_freeze on
    the env-only branch, and this function re-checks the cited run's header
    counts before writing (defence in depth, never trust the caller)."""
    import develop_certify as dc
    ledger = dc.ledger_path(project, ledger_dir)
    rows, bad = dc.read_rows(ledger)
    if bad:
        return {"ok": False, "error": "ledger_has_malformed_lines:%d" % len(bad)}
    red_cert_id = evidence.get("red_cert")
    run_id = evidence.get("run")
    cert = next((c for c in _certs(rows, str(evidence.get("line") or ""))
                 if c.get("id") == red_cert_id), None)
    if cert is None:
        return {"ok": False, "error": "red_cert_not_found:%s" % red_cert_id}
    headers, _hb = read_run_headers(ledger)
    header = next((h for h in headers if h.get("id") == run_id), None)
    if header is None or header.get("verdict") != "red":
        return {"ok": False, "error": "run_header_missing_or_not_red:%s" % run_id}
    cases = header.get("cases") or {}
    if int(cases.get("failed") or 0) > 0:
        return {"ok": False,
                "error": "content_regression_present_never_closes:%s" % run_id}
    releasing = dc._releasing_green_cert(
        rows, str(cert.get("line") or ""), cert,
        _is_green_lookup(header_verdicts(headers)))
    if releasing is None:
        return {"ok": False, "error": "no_releasing_green_cert:%s" % red_cert_id}
    row = dc.freeze_change_row(
        evidence["freeze"], dc.CHANGE_CLOSED, "run-watch",
        "env-only red released by a later green certification",
        value=str(releasing.get("id") or ""), at_ms=at_ms,
        line=str(cert.get("line") or ""))
    res = dc.append_rows([row], ledger)
    if res.get("written") != 1:
        return {"ok": False, "error": "closure_row_rejected:%r" % (res.get("rejected"),)}
    return {"ok": True, "row": row, "seq": (res.get("seqs") or [None])[0],
            "releasing_cert": releasing.get("id")}


def _mint_fix_ticket_id(run_id: str, at_ms: int) -> str:
    """A deterministic ticket id per run id: a start that races a twin lands
    on the same workflow id, so the second start is Temporal-level deduped
    (review R3's bounded-race answer)."""
    day = time.strftime("%y%m%d", time.gmtime(at_ms / 1000.0))
    return "t%s-runwatch-%s" % (day, str(run_id).replace("run-", ""))[:64]


def default_start_fix_ticket(project: str, action: Dict[str, Any],
                             at_ms: int) -> Dict[str, Any]:
    """The production ticket seam: the engine client's dev-lane start face
    (cmd_ticket_start), called in-process. The engine is an exempt channel
    for that face's gates (same-project caller), so no grant is invented
    here; the receipt is verbatim. Any failure is a named refusal — never a
    partial ticket."""
    ticket_id = _mint_fix_ticket_id(action.get("run_id") or "", at_ms)
    try:
        import asyncio
        import client as engine_client
        args = {"ticket_id": ticket_id,
                "template_id": "dev-lane",
                "project": project,
                "title": action.get("title") or "Fix line regression",
                "user_request": action.get("body") or "",
                "spec": action.get("body") or "",
                "caller_project": project}
        out = asyncio.run(engine_client.cmd_ticket_start(args))
        out.setdefault("ticket_id", ticket_id)
        return out
    except Exception as e:  # noqa: BLE001 — named, never a half ticket
        return {"ok": False, "error": "fix_ticket_start_failed:%s:%s"
                % (type(e).__name__, e), "ticket_id": ticket_id}


def default_ticket_open(project: str, ticket_id: str) -> Optional[bool]:
    """Liveness of a previously opened fix ticket: True (still running), False
    (terminal — a NEW ticket may be opened), None (cannot tell — reuse
    conservatively). Best-effort describe; any failure answers None."""
    try:
        import asyncio
        import client as engine_client
        from temporalio.client import WorkflowExecutionStatus  # noqa: F401

        async def _probe():
            handle = engine_client.client.get_workflow_handle(ticket_id)
            desc = await handle.describe()
            return desc.status in (
                WorkflowExecutionStatus.RUNNING,
                WorkflowExecutionStatus.CONTINUED_AS_NEW,
                WorkflowExecutionStatus.PAUSED)
        return asyncio.run(_probe())
    except Exception:  # noqa: BLE001
        return None


def default_retry_round(project: str) -> Dict[str, Any]:
    """The one silent-round retry: the engine's own FORCED round (the same
    round the tick runs, trigger=manual) — never a private second runner."""
    try:
        import develop_certify
        return {"ok": True,
                "result": develop_certify.line_round_run_now(project)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "retry_round_failed:%s:%s"
                % (type(e).__name__, e)}


# ---------- the tick (read + decide + at most one write) ----------


def run_watch_tick(project: str, now_ms: Optional[int] = None,
                   ledger_dir: Optional[str] = None,
                   start_fix_ticket: Optional[Callable[..., Dict[str, Any]]] = None,
                   ticket_open: Optional[Callable[..., Optional[bool]]] = None,
                   retry_round: Optional[Callable[..., Dict[str, Any]]] = None,
                   env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """One watch pass over ONE project's declared lines. Per line: read,
    decide, act (at most one write). A broken line is a named entry, never
    the pass's death (the same contract as the line-round tick)."""
    import develop_line
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    env = dict(os.environ if env is None else env)
    stalled_ms, stalled_note = stalled_ms_from_env(env)
    start_fix_ticket = start_fix_ticket or default_start_fix_ticket
    ticket_open = ticket_open or default_ticket_open
    retry_round = retry_round or default_retry_round

    out: Dict[str, Any] = {"lines": [], "summary": ""}
    try:
        rows, bad, ledger_path = read_ledger_rows(project, ledger_dir)
    except Exception as e:  # noqa: BLE001
        out["summary"] = "run_watch: ledger unreadable (%s: %s)" % (type(e).__name__, e)
        return out
    if bad:
        out["ledger_malformed_lines"] = bad
    headers, hbad = read_run_headers(ledger_path)
    if hbad:
        out["runs_store_malformed_lines"] = hbad
    state, state_note = load_state(state_path(ledger_path))
    if state_note:
        out["state_note"] = state_note
    try:
        lines = develop_line.load_lines(project)
    except Exception as e:  # noqa: BLE001
        out["summary"] = "run_watch: line declaration unreadable (%s: %s)" \
            % (type(e).__name__, e)
        return out
    rounds_all, rbad = read_rounds(project, env)
    if rbad:
        out["rounds_malformed"] = rbad
    if stalled_note:
        out["stalled_note"] = stalled_note

    state_dirty = False
    for line_id, _line in sorted(lines.items()):
        entry: Dict[str, Any] = {"line": line_id}
        try:
            action = decide(rows, line_id, headers, rounds_all,
                            lambda rid: read_case_rows(rid, env),
                            state, now_ms, stalled_ms)
            entry["decision"] = {k: v for k, v in action.items()
                                 if k != "body"}
            performed: Dict[str, Any] = {}
            if action["action"] == "close_freeze":
                performed = close_freeze_row(project, action["evidence"], now_ms,
                                             ledger_dir)
            elif action["action"] == "fix_ticket":
                performed = _perform_fix_ticket(project, action, ticket_open,
                                                start_fix_ticket, now_ms, state)
                if performed.get("ok") and not performed.get("reused"):
                    state.setdefault("fix_tickets", {})[action["run_id"]] = \
                        performed.get("ticket_id")
                    state_dirty = True
            elif action["action"] == "request":
                performed = _perform_request(project, action, now_ms, state, env)
                if performed.get("ok"):
                    state.setdefault("requests", {})[action["dedupe_key"]] = \
                        performed.get("request_id")
                    state_dirty = True
            elif action["action"] == "retry_round":
                performed = retry_round(project)
                state.setdefault("silent_retry", {})[action["run_id"]] = \
                    int((state.get("silent_retry") or {}).get(action["run_id"]) or 0) + 1
                state_dirty = True
            entry["result"] = performed
        except Exception as e:  # noqa: BLE001 — one line's failure is an entry
            entry["error"] = "watch_line_failed:%s:%s" % (type(e).__name__, e)
        out["lines"].append(entry)
    if state_dirty:
        note = save_state(state_path(ledger_path), state)
        if note:
            out["state_note"] = note
    acted = [l["line"] for l in out["lines"]
             if l.get("decision", {}).get("action") not in (None, "none")]
    out["summary"] = ("run_watch: %d lines, acted on %s"
                      % (len(out["lines"]), acted if acted else "none"))
    return out


def _perform_fix_ticket(project: str, action: Dict[str, Any],
                        ticket_open: Callable[..., Optional[bool]],
                        start_fix_ticket: Callable[..., Dict[str, Any]],
                        now_ms: int, state: dict) -> Dict[str, Any]:
    """Open-or-reuse the fix ticket. Reuse: the state's ticket id, when it is
    still live (or uncheckable — reuse conservatively). Open: through the
    injected seam; a refusal is returned named, zero writes."""
    known = action.get("known_ticket")
    if known:
        alive = ticket_open(project, str(known))
        if alive is not False:
            return {"ok": True, "reused": True, "ticket_id": str(known),
                    "liveness": alive}
    res = start_fix_ticket(project, action, now_ms)
    if res.get("ok"):
        return {"ok": True, "reused": False,
                "ticket_id": res.get("ticket_id"),
                "evidence": action.get("evidence")}
    return res


def _perform_request(project: str, action: Dict[str, Any], now_ms: int,
                     state: dict, env: Dict[str, str]) -> Dict[str, Any]:
    """File the stalled/silent request, deduped by evidence key (one open
    request per condition; the memory is the watch's own state file, whose
    fail direction is re-file — never silence)."""
    key = action.get("dedupe_key") or ""
    known = (state.get("requests") or {}).get(key)
    if known:
        return {"ok": True, "reused": True, "request_id": str(known)}
    res = append_request_row(project, action.get("request_kind") or "",
                             action.get("question") or "",
                             action.get("detail") or {}, now_ms, env=env)
    if isinstance(res, dict) and res.get("ok"):
        row = res.get("row") or res.get("request") or {}
        res["request_id"] = str(row.get("id") or key)
        res["evidence"] = action.get("evidence")
    return res


# ---------- engine-level entries ----------


def run_watch_tick_engine(now_ms: Optional[int] = None) -> Dict[str, Any]:
    """The engine-level tick body: one pass per line-declaring project (the
    same enumeration the line-round tick uses). One project's failure is an
    entry, never the pass's death. This is what the scan tick's activity
    calls."""
    import develop_certify
    out: Dict[str, Any] = {}
    try:
        projects = develop_certify.declared_line_projects()
    except Exception as e:  # noqa: BLE001
        return {"projects": {}, "summary": "run_watch: %s: %s"
                % (type(e).__name__, e)}
    for project_key in projects:
        try:
            out[project_key] = run_watch_tick(project_key, now_ms=now_ms)
        except Exception as e:  # noqa: BLE001
            out[project_key] = {"lines": [], "summary":
                                "run_watch: project pass failed (%s: %s)"
                                % (type(e).__name__, e)}
    total = sum(len(r.get("lines") or []) for r in out.values())
    return {"projects": out,
            "summary": "run_watch: %d projects, %d lines" % (len(out), total)}


def run_watch_now(project: Optional[str] = None) -> Dict[str, Any]:
    """The forced face: one pass NOW, one project or every declared one.
    In-process (the engine worker's own files), no Temporal round trip — the
    watch's writes go through the ledger writers, not through workflows."""
    if project:
        return {"projects": {project: run_watch_tick(project)},
                "summary": "run_watch_now: 1 project"}
    return run_watch_tick_engine()
