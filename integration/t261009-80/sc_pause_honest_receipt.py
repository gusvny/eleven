#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_pause_honest_receipt -- t261009-80: a pause that cannot reach a segment
boundary must be HONEST, not silently inert (KI-01M4HQ5FJ8HKGY156YCE97X0K7).

Incident (261010, three times): a steward paused a ticket parked in `blocked`
(awaiting a human). The receipt said delivered:true, nothing stopped, the slot
stayed held, and neither fact was visible on the face. The snapshot query DOES
carry paused/paused_phase; the operator-facing receipt and effect statement do
not. This scenario guards the user-perceivable fix: the receipt and the face
say what WILL happen ("stops at the next segment boundary" vs "this ticket is
blocked and will not reach one; the slot stays held"), and degraded reads
degrade with a name instead of reading like success.

Run (offline, seconds, zero docker/Temporal/browser, never touches 3099/7233):

    PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3
    "$PY" -B integration/t261009-80/sc_pause_honest_receipt.py   # exit 0 = green

Grey-box contract anchors (public payload contract, not internals):
  - evaluate_pause_landing(baseline_refused, snap, op)  (server/engine/client.py)
  - pause_effect_statement(paused, status, stage_state) (server/engine/client.py)
  - _pause_receipt_face(tid, op, who, state, payload, last_snap)
    (server/engine/client.py, the pure receipt-face builder)
  - receipt keys ticket_id/signal/who/delivered (existing, must survive) and
    landing/paused/paused_phase/effect (new) on the pause/resume receipt face;
    `pause_effect` on the ticket detail face (server/tools/ticket.py, _v2_query)
    and the both-faces rule inherited from t261009-35.
Capability discovery is by contract name: a contract-preserving refactor that
keeps these public callables stays green; a missing capability is a named FAIL
(TDD signal pre-implement).

Intent split (no intent-level duplication):
  - the running-ticket pause JOURNEY (gate, at_gate phase, timeline, resume,
    refused intake matrix, pause x rework) is owned by t260908-01
    (sc_ticket_pause_gate) -- NOT re-asserted here;
  - slot-ledger release semantics (pause releases the slot on the ledger, S4)
    is owned by t261004-32-slot-ledger;
  - the console row/badge faces are owned by t260910-04 / t261008-08;
  - this entry uniquely owns: landing honesty on the receipt (including the
    blocked ticket's landed-but-inert pairing), the effect statement (paused
    vs stuck distinguishable from the face alone), the slot-stays-held plain
    statement, baseline-refusal non-misattribution, degraded-input naming,
    and the face-wiring drift guard for the new keys.

Three-state contract (no SKIP): PASS exit 0 / FAIL exit 1 / missing or
unimportable engine module chain = ENV_FAIL exit 2, named.
"""
import io
import json
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
ENGINE = os.path.join(REPO, "server", "engine")
CLIENT_PY = os.path.join(ENGINE, "client.py")
TICKET_PY = os.path.join(REPO, "server", "tools", "ticket.py")

passed, failed = 0, 0


def check(cond, label, why=""):
    global passed, failed
    if cond:
        passed += 1
        print("  ok %s" % label)
    else:
        failed += 1
        print("  FAIL %s%s" % (label, (": %s" % why) if why else ""))


def env_fail(msg):
    print("ENV_FAIL: %s" % msg)
    sys.exit(2)


def load_client_module():
    """Import the public client module under the engine venv when present.
    Unimportable chain = ENV_FAIL (exit 2), never a fake red."""
    sys.path.insert(0, ENGINE)
    try:
        import client  # noqa: PLC0415
        return client
    except Exception as e:
        env_fail("server/engine/client.py chain unimportable: %s: %s"
                 % (type(e).__name__, e))


def discover(mod, names):
    return {n: getattr(mod, n, None) for n in names}


def main():
    print("== A. capability discovery by contract name")
    client = load_client_module()
    caps = discover(client, ["evaluate_pause_landing",
                             "pause_effect_statement"])
    for name, obj in caps.items():
        check(callable(obj), "contract capability %s is a public callable" % name,
              "missing capability = named FAIL (TDD signal pre-implement)")
    ev, stmt = caps["evaluate_pause_landing"], caps["pause_effect_statement"]
    if not (callable(ev) and callable(stmt)):
        print("  (further legs need the contract capabilities; stopping red)")
        finish()

    print("== B. landing evaluator truth table (receipt honesty)")
    ref = lambda want: [{"who": "steward", "want": want, "why": "w"}]  # noqa: E731
    snap = lambda paused, phase="pending": {"paused": paused, "paused_phase": phase}  # noqa: E731
    # pause landed: flag echo visible on the same read the receipt reports.
    check(_call(ev, [], snap(True), "pause")[0] == "landed",
          "B1 pause + snap.paused=true -> landed")
    # resume landed: the cleared flag is confirmed, not assumed.
    check(_call(ev, [], snap(False), "resume")[0] == "landed",
          "B2 resume + snap.paused=false -> landed")
    # refused: a NEW refusal carrying want=pause/resume after delivery.
    check(_call(ev, [], {"refused": ref("pause")}, "pause")[0] == "refused",
          "B3 new refused entry want=pause -> refused")
    check(_call(ev, [], {"refused": ref("resume")}, "resume")[0] == "refused",
          "B4 new refused entry want=resume -> refused")
    # baseline masking: a refusal that predates delivery is never misattributed.
    base = ref("pause")
    check(_call(ev, base, {"refused": base}, "pause")[0] == "pending",
          "B5 pre-existing baseline refusal NOT misattributed (stays pending)")
    # duplicate pause / empty-state resume still surface as refusals.
    check(_call(ev, [], {"refused": ref("pause"),
                         "paused": True}, "pause")[0] == "refused",
          "B6 duplicate-pause refusal surfaces (idempotent refusal visible)")
    check(_call(ev, [], {"refused": ref("resume"),
                         "paused": False}, "resume")[0] == "refused",
          "B7 empty-state resume refusal surfaces")
    # nothing new on the snapshot -> pending (the caller owns the poll budget).
    check(_call(ev, [], snap(True), "resume")[0] == "pending",
          "B8 condition unmet on fresh snapshot -> pending")

    print("== C. effect statement: paused vs stuck readable from the face alone")
    running = stmt(True, "running", "awaiting")
    blocked = stmt(True, "blocked", "awaiting-human")
    for label, txt in (("C1 running wording", running),
                       ("C2 blocked wording", blocked)):
        check(isinstance(txt, str) and txt.strip(), label + " is a non-empty string")
    low_r, low_b = running.lower(), blocked.lower()
    check("boundary" in low_r, "C3 running wording names the segment boundary",
          running)
    check(not ("will not reach" in low_r or "slot stays held" in low_r),
          "C4 running wording does NOT claim blocked/non-effect",
          "ordinary-case wording must not read as inert (spec 4)", )
    check("not reach" in low_b or "will not" in low_b,
          "C5 blocked wording says the pause will not take effect", blocked)
    check("slot" in low_b, "C6 blocked wording says plainly the slot stays held",
          blocked)
    check(stmt(False, "blocked", "awaiting-human") in ("", None),
          "C7 not-paused -> empty statement (never fabricated)")

    print("== D. degraded and malformed inputs: named, never a crash")
    for i, args in enumerate([
        (None, None, "pause"),                                   # no snapshot at all
        ([], {"paused": True, "refused": "not-a-list"}, "pause"),  # refused wrong type
        ([], {"paused": True, "refused": [{"who": "x"}]}, "pause"),  # entry w/o want
        ([], {"paused": True, "refused": ["bare-string"]}, "pause"),
        ([], {}, "pause"),                                       # keys missing
        ([], {"paused": "yes"}, "pause"),                        # non-bool flag
    ]):
        try:
            out = _call(ev, *args)
            check(isinstance(out, tuple) and out and out[0] in
                  ("landed", "refused", "pending"),
                  "D%d evaluator degrades to a named state (args #%d)" % (i + 1, i + 1))
        except Exception as e:
            check(False, "D%d evaluator degrades to a named state" % (i + 1),
                  "raised %s: %s" % (type(e).__name__, e))
    for i, args in enumerate([
        (True, None, None),            # no status/stage_state at all
        (True, 42, ["x"]),             # wrong types
        (None, "blocked", "awaiting-human"),
    ]):
        try:
            out = stmt(*args)
            check(isinstance(out, (str, type(None))),
                  "D%d effect statement degrades without raising (args #%d)" % (i + 1, i + 1))
        except Exception as e:
            check(False, "D%d effect statement degrades without raising" % (i + 1),
                  "raised %s: %s" % (type(e).__name__, e))

    print("== E. receipt-face builder + face wiring (public key contract)")
    caps["builder"] = getattr(client, "_pause_receipt_face", None)
    check(callable(caps["builder"]),
          "E0 receipt-face builder capability is callable",
          "missing capability = named FAIL (TDD signal)")
    if callable(caps["builder"]):
        build = caps["builder"]
        base_keys = {"ticket_id", "signal", "who", "delivered"}
        # landed pause: existing keys preserved, honesty keys added, effect
        # derived from the SAME last_snap (review condition 3).
        r = build("T-1", "pause", "steward", "landed", "",
                  {"paused": True, "paused_phase": "pending",
                   "status": "blocked", "stage_state": "awaiting-human"})
        check(base_keys <= set(r), "E1 landed receipt keeps the existing key set",
              str(sorted(r)))
        check({"landing", "paused", "paused_phase", "effect"} <= set(r),
              "E2 landed receipt carries the honesty keys", str(sorted(r)))
        check(r.get("delivered") is True,
              "E3 delivered keeps its meaning (signal reached event history)")
        check("not" in str(r.get("effect", "")).lower()
              and "slot" in str(r.get("effect", "")).lower(),
              "E4 blocked pause receipt reads as INERT, not effective", str(r))
        # refused: the refusal is named, no state echo pretending success.
        r = build("T-1", "pause", "steward", "refused", "already paused", None)
        check(r.get("landing") == "refused" and "refused_why" in r,
              "E5 refused receipt names landing=refused and the why", str(r))
        check(r.get("paused") is None and not r.get("effect"),
              "E6 refused receipt echoes no pause state (absent, not faked)",
              str(r))
        # unconfirmed: still an ok receipt (delivery happened) + check-back note.
        r = build("T-1", "pause", "steward", "unconfirmed", None, None)
        check(r.get("delivered") is True and r.get("landing") == "unconfirmed",
              "E7 unconfirmed keeps delivered=true (named, not a silent lie)")
        check("query" in str(r.get("receipt_note", "")),
              "E8 unconfirmed note names the re-check face (op=query)",
              str(r.get("receipt_note")))
        # no snapshot at all within budget: degrade, never crash, never fake.
        try:
            r = build("T-1", "pause", "steward", "unconfirmed", None, "not-a-dict")
            check(isinstance(r, dict), "E9 non-dict last_snap degrades, no crash")
        except Exception as e:
            check(False, "E9 non-dict last_snap degrades, no crash",
                  "raised %s: %s" % (type(e).__name__, e))
        r = build("T-1", "resume", "steward", "landed", "",
                  {"paused": False, "paused_phase": "", "status": "running",
                   "stage_state": "awaiting"})
        check(r.get("paused") is False and bool(str(r.get("effect", "")).strip()),
              "E10 resume landed receipt confirms the flag cleared with wording",
              str(r))
    csrc = _read(CLIENT_PY, "client.py")
    tsrc = _read(TICKET_PY, "ticket.py")
    check("'pause_effect'" in tsrc or '"pause_effect"' in tsrc,
          "E11 detail face carries `pause_effect` (ticket.py)",
          "paused vs stuck must be readable from op=show alone")
    check("paused" in tsrc and "paused_phase" in tsrc,
          "E12 detail face keeps the t261009-35 pause pair")
    finish()


def _call(fn, *args):
    return fn(*args)


def _read(path, label):
    try:
        with io.open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError as e:
        env_fail("%s unreadable: %s" % (label, e))


def finish():
    global passed, failed
    print("passed=%d failed=%d" % (passed, failed))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        print("FAIL scenario crashed (bug in the scenario, not a named red)")
        sys.exit(1)
