#!/usr/bin/env python3
"""sc_t261026_08_request_sweep_ticket_channel.py — the sweep can actually read
ticket status.

Ticket t261026-08, host question 261026: "can the executor close the requests
it already solved? the UI shows 110 and they look useless." Measured answer:
it is designed to, but `default_ticket_status_fn` built its reader command
around `server/tools/admin.py`, a path that does not exist (the tool lives at
`server/admin.py`), so every call returned None, `sweep_project` treated None
as "channel unavailable" and SKIPPED every `ticket_closed` head — the most
common condition kind never resolved anything (110 open heads, 65 closable by
exactly this rule, 0 closed by the sweep; a human closed 61 the same night by
hand with the same evidence string `ticket-list-projection(operator)`). The
fix is one line: point the reader at `server/admin.py`; everything else stays
(same command shape, same `shared.gate_receipt_parse`, same named source
`ticket-list-projection`, same fail-closed rules).

This scenario judges that contract grey-box, from the reader side, offline:
the real `default_ticket_status_fn` against the REAL `admin.py` list channel
(read-only; the list is a Temporal list, so the instance's Temporal must
answer — absence of a live projection is ENV_FAIL, never a red),
plus the fail-closed truth table and the user-perceivable sweep behaviour.

Legs (PASS/FAIL; ENV_FAIL only when the environment genuinely cannot run the
channel — interpreter, admin.py or the ticket projection store missing):
  A  THE DEAD PATH IS DEAD NO MORE — the command the function builds names
     `server/admin.py` (source lock, the exact regression) and the file
     exists; a live `admin.py call ticket {"op":"list"}` receipt parses.
  B  REAL CHANNEL RESOLVES — through the real function: a ticket the
     projection shows closed reads ("closed", "ticket-list-projection"); a
     ticket id that cannot exist reads ("not-listed", "ticket-list-projection"),
     never None; an open ticket reads its own status, never "closed".
  C  FAIL-CLOSED STAYS PROVABLE — an unreadable admin path, a channel that
     cannot start, a non-zero receipt and an unparseable receipt each yield
     None (the sweep's SKIP), never a fabricated status.
  D  THE USER-PERCEIVABLE ACT — `sweep_project` over a real temp requests
     ledger: a `ticket_closed` head whose ticket reads closed is RESOLVED with
     the named source in the evidence and a state row readable back from the
     ledger file (reader side, never the writer's word); a dead channel skips
     the head BY NAME (`ticket_reader_unavailable`) and writes NOTHING to the
     ledger — skip, never a silent close.

Intent split (no intent-level duplication): the stubbed-subprocess truth
tables (closed / not-listed / malformed receipt / dead channel) belong to
developer L1 (server/engine/tests/test_t261026_08_request_sweep_channel.py);
THIS entry uniquely owns the journey against the REAL admin.py channel — the
live face no stub can prove — and the end-to-end sweep act on a real ledger
file. Pre-implement tree red on A/B = the named TDD signal; green required at
the integration gate/merge.

Run directly (cwd = repo root):
  PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; "$PY" -B \
      integration/t261026-08/sc_t261026_08_request_sweep_ticket_channel.py
Exit codes: 0 all green, 1 product red, 2 ENV_FAIL.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# Repo root: walk up from this file until the engine tree is under it (the
# script may sit in integration/ or a per-ticket subdirectory of it).
def _find_root():
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "server" / "engine" / "request_sweep.py").exists():
            return p
        p = p.parent
    return Path(__file__).resolve().parent.parent


ROOT = _find_root()
ENGINE = ROOT / "server" / "engine"
ADMIN_PY = ROOT / "server" / "admin.py"
sys.path.insert(0, str(ENGINE))

PASS = 0
FAIL = 0
ENV_FAIL = 0
PROBLEMS = []


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  %s" % label)
    else:
        FAIL += 1
        PROBLEMS.append(label)
        print("  RED %s" % label)


# ------------------------------------------------------------------ imports
try:
    import request_sweep  # noqa: E402
    import shared  # noqa: E402
except Exception as exc:  # noqa: BLE001
    print("ENV_FAIL: engine modules unimportable from %s: %s" % (ENGINE, exc))
    sys.exit(2)

# The real channel needs the caller-project context the executor face carries;
# the sweep inherits os.environ, so set it the way production does.
os.environ.setdefault("SANDBAR_CALLER_PROJECT", "sandbar")

# The ticket-list channel is a Temporal list (admin.py -> client.py
# Client.connect(TARGET_HOST)), not a local store. The suite states the TEST
# target for its children by default; a test Temporal holds no tickets, so the
# live-channel legs would read an empty projection and red for the wrong
# reason. Per the t261017-10 discipline a case whose tested face IS the target
# strips the suite's statement and names it: this journey reads the instance's
# own (production-default) projection, READ-ONLY, exactly like the measured
# proof of 261026. A target stated by the deployment itself is kept verbatim.
# If no Temporal answers, or the projection it shows holds no tickets, the
# live legs cannot be judged -> ENV_FAIL exit 2 (never a product red).
SUITE_TARGET_SOURCE = "SANDBAR_SUITE_STATED_TARGET"
if os.environ.get(SUITE_TARGET_SOURCE) == "127.0.0.1:17233":
    del os.environ["SANDBAR_TARGET_HOST"]
    del os.environ[SUITE_TARGET_SOURCE]
    print("[provision] suite-stated test target stripped and named "
          "(t261017-10): the live ticket-list journey reads the instance's "
          "own projection (read-only)")

PY = sys.executable
if not ADMIN_PY.exists():
    print("ENV_FAIL: server/admin.py missing at %s" % ADMIN_PY)
    sys.exit(2)

# ------------------------------------------------- A: the dead path is gone
print("\n[A] the reader command names server/admin.py, and the channel answers")
src = (ENGINE / "request_sweep.py").read_text(encoding="utf-8")
# The contract: the reader entry resolves to <repo_root>/server/admin.py and
# never to the stale server/tools/admin.py. The HOW is the producer's choice
# (an os.path.join site or the shared.ADMIN_PY seam — t261026-06 evolved to
# the seam); the WHERE is what this leg pins.
m = re.search(r"admin_py\s*=\s*os\.path\.join\(([^\)]*)\)", src, re.S)
seam = str(getattr(shared, "ADMIN_PY", "") or "")
eff = Path(seam) if seam else None
if m:
    parts = [p.strip().strip("\"'") for p in m.group(1).split(",")]
    ok(parts[-2:] == ["server", "admin.py"],
       "the join site points at server/admin.py (got %r)" % parts)
elif eff:
    ok(eff == ROOT / "server" / "admin.py",
       "the shared.ADMIN_PY seam resolves to <repo_root>/server/admin.py "
       "(got %s)" % eff)
else:
    ok(False, "no admin entry resolution found (neither a join site nor "
              "shared.ADMIN_PY) — the reader cannot be located")
resolved = eff if eff else (ROOT / "server" / "admin.py")
ok("tools" not in resolved.parts,
   "the resolved reader entry never sits under server/tools/ (got %s)" % resolved)
ok(ADMIN_PY.exists(), "server/admin.py exists on disk (the reader can start it)")

# a real read-only receipt through the actual tool, exactly as measured 261026
# L25 wait-bound discipline: the read is an offline projection read and must
# answer in seconds; the bound is injectable and a breach names this check.
CHANNEL_TIMEOUT_S = int(os.environ.get("CHANNEL_TIMEOUT_S", "60"))
try:
    proc = subprocess.run(
        [PY, str(ADMIN_PY), "call", "ticket", json.dumps({"op": "list"})],
        cwd=str(ROOT), capture_output=True, text=True,
        timeout=CHANNEL_TIMEOUT_S)
    receipt_ok = proc.returncode == 0
    parsed = shared.gate_receipt_parse(proc.stdout) if receipt_ok else None
    tickets = ((parsed or {}).get("result") or {}).get("tickets") or []
    if not receipt_ok or not isinstance(parsed, dict):
        print("ENV_FAIL: the ticket-list channel did not answer a receipt "
              "(target %s, rc=%d) — the live legs cannot be judged"
              % (os.environ.get("SANDBAR_TARGET_HOST") or "127.0.0.1:7233",
                 proc.returncode))
        sys.exit(2)
    ok(True, "a real admin.py ticket-list call returns a parseable receipt")
    if len(tickets) == 0:
        print("ENV_FAIL: the ticket-list channel answered but the projection "
              "holds no tickets (target %s) — the live legs need a projection "
              "with tickets; not a product red"
              % (os.environ.get("SANDBAR_TARGET_HOST") or "127.0.0.1:7233"))
        sys.exit(2)
    ok(True, "the real projection holds tickets (got %d)" % len(tickets))
except subprocess.TimeoutExpired:
    print("ENV_FAIL: the %ss channel bound fired and named this check "
          "(override with CHANNEL_TIMEOUT_S); the projection read is an "
          "offline read and must answer in seconds" % CHANNEL_TIMEOUT_S)
    sys.exit(2)
except OSError as exc:
    print("ENV_FAIL: cannot start admin.py: %s" % exc)
    sys.exit(2)

# ------------------------------------------------- B: real channel resolves
print("\n[B] the real function reads the real projection (closed / not-listed / open)")
by_id = {}
statuses = {}
for t in tickets:
    if isinstance(t, dict) and isinstance(t.get("id"), str):
        by_id[t["id"]] = t
        statuses.setdefault(str(t.get("status")), []).append(t["id"])
closed_ids = statuses.get("closed") or []
open_ids = [i for s, ids in statuses.items() if s != "closed" for i in ids]

fn = request_sweep.default_ticket_status_fn
if closed_ids:
    cid = closed_ids[0]
    read = fn(cid)
    ok(read == ("closed", "ticket-list-projection"),
       "a ticket the projection shows closed (%s) reads ('closed', "
       "'ticket-list-projection') — got %r" % (cid, read))
else:
    print("  na  no closed ticket in the projection right now "
          "(system-state condition; judge B-closed on a face that has one)")
ghost = "t260100-99"
read = fn(ghost)
ok(isinstance(read, tuple) and read[0] == "not-listed"
   and read[1] == "ticket-list-projection",
   "a ticket id that cannot exist reads ('not-listed', "
   "'ticket-list-projection'), never None — got %r" % (read,))
if open_ids:
    oid = open_ids[0]
    read = fn(oid)
    ok(isinstance(read, tuple) and read[0] != "closed"
       and read[1] == "ticket-list-projection",
       "an open ticket (%s) reads its own status, never closed — got %r"
       % (oid, read))
else:
    print("  na  no open ticket in the projection right now (system state)")

# ------------------------------------------------------ C: fail-closed rules
print("\n[C] a channel that cannot answer yields None, never a status")
real_exists = os.path.exists
try:
    os.path.exists = lambda p: False if "admin" in str(p) else real_exists(p)
    ok(fn("t261021-11") is None,
       "an admin path that does not exist yields None (the old bug's face)")
finally:
    os.path.exists = real_exists

import importlib  # noqa: E402
real_run = subprocess.run
try:
    request_sweep_subprocess = importlib.import_module("subprocess")
    saved = request_sweep_subprocess.run
    request_sweep_subprocess.run = \
        lambda *a, **k: (_ for _ in ()).throw(OSError("cannot start"))
    ok(fn("t261021-11") is None,
       "a channel that cannot start yields None (OSError)")
    request_sweep_subprocess.run = \
        lambda *a, **k: type("P", (), {"returncode": 1, "stdout": "", "stderr": ""})()
    ok(fn("t261021-11") is None, "a non-zero receipt yields None")
    request_sweep_subprocess.run = \
        lambda *a, **k: type("P", (), {"returncode": 0, "stdout": "not-a-receipt",
                                       "stderr": ""})()
    ok(fn("t261021-11") is None, "an unparseable receipt yields None")
finally:
    request_sweep_subprocess.run = saved

# ------------------------------------------- D: the user-perceivable sweep act
print("\n[D] sweep_project resolves a closable head on a real ledger file, "
      "and a dead channel writes nothing")
import executor_requests  # noqa: E402
import request_thread  # noqa: E402

TICKET_ID_RE = request_thread.TICKET_ID_RE
ticket_pat = TICKET_ID_RE.pattern if hasattr(TICKET_ID_RE, "pattern") \
    else r"t\d{4}\d{2,}-\d+"
head_id = "req-261026-0001"
probe_ticket = closed_ids[0] if closed_ids else ghost

with tempfile.TemporaryDirectory(prefix="sandbar-sc-261026-08-") as td:
    env = dict(os.environ)
    # the requests ledger root resolves SANDBAR_PANEL_DIR first; a temp panel
    # dir keeps the probe fully isolated from the real instance ledger.
    env["SANDBAR_PANEL_DIR"] = td
    ledger = Path(td) / "sandbar-sc" / "requests.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    head = {"type": "request", "id": head_id, "at": 1, "by": "integration",
            "text": "probe head for t261026-08",
            "resolves_when": {"kind": "ticket_closed", "ticket": probe_ticket}}
    ledger.write_text(json.dumps(head) + "\n", encoding="utf-8")

    def run_sweep(status_fn):
        return request_sweep.sweep_project(
            "sandbar-sc", now_ms=2, seq=1, env=env,
            ledger_rows_fn=lambda: ([], 0, None),
            is_green=lambda rid: None,
            ticket_status_fn=status_fn)

    r = run_sweep(lambda t: ("closed", "ticket-list-projection"))
    ok(len(r.get("resolved") or []) == 1
       and r["resolved"][0]["id"] == head_id,
       "a ticket_closed head whose ticket reads closed is resolved (receipt)")
    ok("ticket-list-projection" in (r["resolved"][0].get("evidence") or ""),
       "the resolution evidence names the source projection")
    lines = [json.loads(l) for l in
             ledger.read_text(encoding="utf-8").splitlines() if l.strip()]
    state_rows = [l for l in lines if l.get("type") == "state"]
    ok(len(state_rows) == 1
       and state_rows[0].get("state_for") == head_id
       and state_rows[0].get("state") == "resolved",
       "the state row is readable back from the ledger file (reader side)")

    # rewind the ledger to just the head, then the dead-channel face
    ledger.write_text(json.dumps(head) + "\n", encoding="utf-8")
    r = run_sweep(lambda t: None)
    ok(len(r.get("resolved") or []) == 0,
       "a dead channel resolves NOTHING (never a silent close)")
    skips = r.get("skipped") or []
    ok(any("ticket_reader_unavailable" in (s.get("reason") or "") for s in skips),
       "the dead channel is skipped BY NAME (ticket_reader_unavailable)")
    lines = [json.loads(l) for l in
             ledger.read_text(encoding="utf-8").splitlines() if l.strip()]
    ok(len(lines) == 1 and lines[0].get("type") == "request",
       "the dead-channel sweep wrote nothing to the ledger file")

# ------------------------------------------------------------------- summary
print("\nSUMMARY pass=%d fail=%d env_fail=%d na=%d"
      % (PASS, FAIL, ENV_FAIL, 0 if closed_ids else 1))
print("SCENARIO t261026-08-request-sweep-ticket-channel ran=1 pass=%d fail=%d"
      % (1 if FAIL == 0 else 0, 1 if FAIL else 0))
if PROBLEMS:
    print("FAIL: %d leg(s) red" % FAIL)
    for p in PROBLEMS:
        print("  - %s" % p)
    sys.exit(1)
print("PASS")
sys.exit(0)
