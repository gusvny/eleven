#!/usr/bin/env python3
"""sc_t26100931_dismiss_reader_face.py — the dismissal read face: ticket-list
and ticket-detail augmentation, degradation contract, and the human-only CLI
operation (t261009-31).

Run directly: python3 integration/t261009-31/sc_t26100931_dismiss_reader_face.py
(cwd = repo root), or through the engine venv fallback chain (SCENARIOS entry).

Grey-box L3, offline seconds, zero docker/Temporal-server/browser, never
touches 3099. server/engine/client.py sits on the temporalio chain, so the
behavioral legs run under the engine venv; the chain being unimportable is
ENV_FAIL exit 2, not a pass.

Faces asserted (anchored to the declared contract keys `dismissed` /
`dismissed_note` / op names `dismiss` / `restore`, never to private helpers —
a keeping refactor must not break this):

  C  client read face: BOTH the list pass and the detail path augment a
     dismissed ticket's row with `dismissed:{at,who,reason}`; a ticket with no
     dismissal shows NO dismissed key (silent absence would be fine here — the
     note is for read failures, not for "not dismissed").
  D  degradation: a journal read failure means the `dismissed` key is ABSENT
     and a NAMED note travels in the payload (`dismissed_note`) — never a
     silent "not dismissed", never a crash.
  N  a dismissed row is NOT reclassified into the DONE family: the workflow
     really did fail, status stays failed; the UI ticket re-classifies out of
     the board, the engine never flips the status.
  T  the ticket tool declares `dismiss` and `restore` operations, both
     requiring who and a non-empty reason; the dismiss/restore handler issues
     no workflow signal (it never advances, closes or re-opens a ticket).
  H  the operation is a HUMAN action: the engine face carries the agent-who
     refusal (an agent may not dismiss a ticket it failed).

Intent split: the journal write/read/append contract and the refusal matrix
zero-write proof belong to t261009-31-dismiss-journal-contract (not repeated
here); the dwell rule and the board-side disappearance belong to the staged UI
ticket and are out of scope by the dispatch spec.

Pre-implementation tree: red is the expected TDD signal; green required at the
integration gate / merge. Engine client chain unimportable (temporalio) =
ENV_FAIL exit 2.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CLIENT_PY = ROOT / "server" / "engine" / "client.py"
TICKET_PY = ROOT / "server" / "tools" / "ticket.py"
DISMISS_PY = ROOT / "server" / "engine" / "ticket_dismiss.py"

PASS = 0
FAIL = 0
NA = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok %s" % label)
    else:
        FAIL += 1
        print("  FAIL %s" % label)


def section(title):
    print("\n%s" % title)


def env_fail(reason):
    print("ENV_FAIL: %s" % reason)
    sys.exit(2)


for p in (CLIENT_PY, TICKET_PY):
    if not p.is_file():
        env_fail("engine tree incomplete: %s missing" % p)

CJSRC = CLIENT_PY.read_text("utf-8")
TJSRC = TICKET_PY.read_text("utf-8")

# ---------- T. CLI declares dismiss/restore, human-only, no signal ----------
section("T the ticket tool declares the two human operations")
for op in ("dismiss", "restore"):
    ok(re.search(r"['\"]%s['\"]" % op, TJSRC) is not None,
       "T1 ticket tool declares the %s op" % op)
ok("who" in TJSRC and "reason" in TJSRC, "T2 dispatch surface carries who/reason slots")
# locate the dismissal op handler and check IT is signal-free (the surrounding
# dispatch table legitimately names other ops — judge the handler's own body)
m = re.search(r"def _dismiss_restore\b", TJSRC)
dismiss_region = ""
if m:
    nxt = re.search(r"\ndef \w+", TJSRC[m.end():])
    dismiss_region = TJSRC[m.start():m.end() + (nxt.start() if nxt else 4000)]
else:
    dismiss_region = ""  # pre-implementation: absent handler -> T3 rows below fail
for needle in ("signal", "cancel_notice", "terminate", "advance"):
    ok(needle not in dismiss_region,
       "T3 the dismissal op handler issues no workflow %s" % needle)
ok(bool(dismiss_region), "T4 the dismissal op handler body is present (%d chars)" % len(dismiss_region))

# ---------- H. the agent-who refusal exists somewhere discoverable ----------
section("H a human action: agents cannot dismiss")
gate_hits = []
for path, label in ((DISMISS_PY, "ticket_dismiss"), (TICKET_PY, "ticket.py")):
    if path.is_file():
        s = path.read_text("utf-8")
        if re.search(r"agent", s, re.I) and re.search(r"dismiss", s, re.I):
            gate_hits.append(label)
ok(bool(gate_hits), "H1 an agent-who refusal is present in %s (pre-implementation: absent = red)" %
   (gate_hits or "no surface"))

# ---------- C/D/N. the client read face ----------
section("C/D/N the client read face (behavioral legs under the engine venv)")


def venv_python():
    for cand in (ROOT / "server/engine/.venv/bin/python",
                 ROOT / "server/dsh/temporal-poc/.venv/bin/python"):  # engine-venv-compat（t260907-10 回落链行，摘除票移除旧路径）
        if cand.is_file():
            return str(cand)
    return sys.executable


PROBE = r'''
import importlib.util, json, os, shutil, sys, tempfile
root = sys.argv[1]
sys.path.insert(0, os.path.join(root, "server", "engine"))
work = tempfile.mkdtemp(prefix="itg31-reader-")
try:
    jdir = os.path.join(work, "state"); os.makedirs(jdir)
    os.environ["SANDBAR_DISMISS_DIR"] = jdir
    try:
        import client  # noqa: F401  (temporalio chain; unimportable -> report, not crash)
    except Exception as exc:
        print(json.dumps({"importable": False, "err": "%s: %s" % (type(exc).__name__, exc)}))
        sys.exit(0)
    out = {"importable": True, "seams": []}
    # discover the dismissal augmentation seam by BEHAVIOR over the declared
    # contract (a callable that yields a dismissal face for a dismissed
    # ticket and nothing for a non-dismissed one) — name-agnostic, so a
    # keeping refactor that keeps behavior cannot strand the probe.
    jp = os.path.join(jdir, "ticket-dismiss.jsonl")
    with open(jp, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"at": 1728500000.0, "ticket_id": "t260929-11",
                             "who": "host", "reason": "dead ticket", "action": "dismiss"}) + "\n")
    tid, other = "t260929-11", "t269999-99"
    row = {"id": tid, "ticket_id": tid, "status": "failed"}
    row_plain = {"id": other, "ticket_id": other, "status": "running"}
    FACE_KEYS = {"at", "who", "reason"}

    def is_face(v):
        return isinstance(v, dict) and FACE_KEYS.issubset(set(v)) and "dismissed" not in v

    def aug_hit(res):
        if isinstance(res, dict):
            if is_face(res.get("dismissed")):
                return "row-key"
            if is_face(res):
                return "face"
        if isinstance(res, list) and res and isinstance(res[0], dict):
            if is_face(res[0].get("dismissed")):
                return "list-row-key"
        return None

    face_row = {"at": 1728500000.0, "who": "host", "reason": "dead ticket"}
    for name in dir(client):
        if "dismiss" not in name.lower():
            continue
        fn = getattr(client, name, None)
        if not callable(fn):
            continue
        hit = None
        for call in (lambda: fn(row), lambda: fn([row]), lambda: fn({}, tid),
                     lambda: fn({tid: face_row}, tid),
                     lambda: fn(row, tid), lambda: fn(tid)):
            try:
                hit = aug_hit(call())
            except Exception:
                continue
            if hit:
                break
        miss = None
        if hit:
            for call in (lambda: fn(row_plain), lambda: fn([row_plain]),
                         lambda: fn({}, other), lambda: fn({other: face_row}, other)):
                try:
                    miss = aug_hit(call())
                except Exception:
                    continue
                break
        out["seams"].append({"name": name, "hit": hit or "",
                             "false_positive_on_undismissed": bool(miss)})
    print(json.dumps(out))
finally:
    shutil.rmtree(work, ignore_errors=True)
'''

proc = subprocess.run([venv_python(), "-c", PROBE, str(ROOT)],
                      capture_output=True, text=True, timeout=120)
lines = [l for l in proc.stdout.splitlines() if l.strip().startswith("{")]
face = None
if lines:
    try:
        face = json.loads(lines[-1])
    except ValueError:
        face = None
if face is None:
    env_fail("client read-face probe produced no parseable output; stderr: %s"
             % (proc.stderr or proc.stdout)[-400:])
if not face.get("importable"):
    env_fail("engine client chain unimportable (temporalio): %s" % face.get("err"))

seams = [s for s in face.get("seams", []) if s.get("hit")]
fp = [s for s in seams if s.get("false_positive_on_undismissed")]
section("C/D behavioral probe results (pre-implementation: red expected)")
ok(bool(seams), "C1 a client-module seam produces the `dismissed` augmentation for a dismissed"
   " row (seams probed: %s)" % ([s["name"] for s in face.get("seams", [])] or "none"))
ok(not fp, "C2 the seam is silent for a NON-dismissed row (no fabricated dismissal: %s)" % fp)
src_hits_list = len(re.findall(r"['\"]dismissed['\"]", CJSRC))
ok(src_hits_list >= 1, "C3 the `dismissed` contract key is present in client.py (%d sites)" % src_hits_list)
ok("dismissed_note" in CJSRC,
   "D1 the named degradation note `dismissed_note` is present in client.py")
ok(src_hits_list >= 2 or "for row in" in CJSRC,
   "C4 augmentation reaches the row population (list pass) — a detail-only face is not enough")
# N: a dismissal must NOT reclassify into the DONE family — no status write may
# sit adjacent to an augmentation site (copy-level pin; the deep status-flip
# behavior is owned by the journal contract entry, N is the tripwire here)
bad = []
for m in re.finditer(r"dismissed", CJSRC):
    window = CJSRC[m.start():m.start() + 400]
    if re.search(r"\[.status.\]\s*=|\.status\s*=", window):
        bad.append(m.start())
ok(not bad, "N1 no status write adjacent to a dismissed augmentation site (hits: %s)" % bad)

print("\nSUMMARY pass=%d fail=%d env_fail=0 na=%d" % (PASS, FAIL, NA))
sys.exit(1 if FAIL else 0)
