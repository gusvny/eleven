#!/usr/bin/env python3
"""sc_t26100411_ledger_record_and_replay.py — t261004-11 Part 1: the engine
records each gated executor write in the project's own ledger.

Grey-box L3, offline (no docker, no Temporal server, no browser, zero contact
with 3099/7233). Drives the engine's public gate funnel `client._executor_grant_gate`
(same public-module-function + stub-free-face seam as t261003-03) against an
isolated projects root (SANDBAR_PROJECTS_DIR) holding a real executor-grants
declaration. Assertions land only on user-perceivable behavior: the ticket-named
file `<root>/<key>/ledger/executor-actions.jsonl` gains one schema-v1 row per
gated write attempt, refused attempts are recorded, a replay does not add a
second row, an exempt (non-gated) pass records nothing, a failed append never
changes the write outcome but is loud (gap sidecar), and rows stay small with
no raw arguments.

Legs:
  A1 allowed gated write -> exactly one row at the ticket-named path with the
     schema-v1 field set (v/at/op/ticket/grant/grant_source/session/channel/
     decision=allowed/idem), line < 4096 bytes, no raw-args/receipt keys.
  A2 refused attempts recorded: ungranted op and meta-op refusal rows carry
     decision=refused with a non-empty reason and grant="".
  A3 replay: the same logical attempt a second time adds no second row (idem).
  A4 exempt channel (lane-agent surface): gate passes with zero rows written.
  A5 append failure: read-only ledger dir -> gate verdict unchanged vs the
     writable run, and the failure is loud: a gap row appears in
     executor-actions.gaps.jsonl next to the record.
  A6 path shape: the record lives only at <key>/ledger/executor-actions.jsonl;
     the event ledger events.jsonl stays untouched by gate recording.

Three-state discipline (t260904-12): engine venv missing = ENV_FAIL exit 2;
recording face not implemented = FAIL exit 1 with the leg named (TDD red is
expected until implement lands; must be green by arbitrate/merge).

intent 分工: the panel-side face (feed source, refused marker, hover, cap,
copy, gaps surface) belongs to sc_t26100411_panel_reads_project_record (same
ticket, different layer); row-field truth tables and pure-core matrices stay
with developer L1. The superseded admin-log read face of
t261003-10-recent-actions-real-source is rewritten by the implement stage per
plan Step 5; this scenario never touches admin.log.
"""
import json
import os
import shutil
import stat
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "integration"))

from lib_env import env_fail, fail_if_all_na  # noqa: E402

ENGINE_DIR = os.path.join(REPO, "server", "engine")

PY = os.path.join(ENGINE_DIR, ".venv", "bin", "python")
if not os.path.isfile(PY):
    PY = os.path.join(REPO, "server", "dsh", "temporal-poc", ".venv", "bin", "python")  # engine-venv-compat
if not os.path.isfile(PY):
    import shutil as _sh
    found = _sh.which("python3")
    if not found:
        env_fail("no python3 available (engine venv fallback chain exhausted)")
    PY = found

KEY = "proj-t26100411"
SESSION = "sess-t26100411-exec-1"
LINE_LIMIT = 4096

legs = []          # (name, ok, reason)
na_legs = []


def leg(name, ok, reason=""):
    legs.append((name, bool(ok), reason))
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, (" — " + reason) if reason else ""))


def main():
    root = tempfile.mkdtemp(prefix="t26100411-engine-")

    def cleanup():
        # restore write permission so rm -r works on the read-only leg's dir
        ledger_dir = os.path.join(root, KEY, "ledger")
        try:
            os.chmod(ledger_dir, 0o700)
        except OSError:
            pass
        shutil.rmtree(root, ignore_errors=True)

    import atexit
    atexit.register(cleanup)

    proj = os.path.join(root, KEY)
    os.makedirs(os.path.join(proj, "ledger"))
    decl = {"version": 1, "grants": {"sign": True},
            "executor_sessions": [SESSION],
            "updated_by": "scenario", "updated_at": int(time.time() * 1000)}
    with open(os.path.join(proj, "executor-grants.json"), "w", encoding="utf-8") as f:
        json.dump(decl, f)

    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "SANDBAR_PROJECTS_DIR": root,
        "SANDBAR_CALLER_IDENTITY_SRC": "arg",
        "DSH_SESSION_ID": SESSION,
        "HOME": os.environ.get("HOME", root),
    }

    # run the whole leg battery in the engine interpreter (single process so the
    # in-process dedupe set behaves; env seam keeps the tree isolated)
    script = r'''
import json, os, sys
ENGINE = sys.argv[1]
ROOT = sys.argv[2]
KEY = sys.argv[3]
SESSION = sys.argv[4]
sys.path.insert(0, ENGINE)
os.chdir(ENGINE)
for k in ("SANDBAR_PROJECTS_DIR", "SANDBAR_CALLER_IDENTITY_SRC"):
    os.environ[k] = {"SANDBAR_PROJECTS_DIR": ROOT, "SANDBAR_CALLER_IDENTITY_SRC": "arg"}[k]
os.environ.pop("SANDBAR_CALLER_SURFACE", None)
os.environ["DSH_SESSION_ID"] = SESSION

import client, executor_grants

out = {}
def rows():
    p = os.path.join(ROOT, KEY, "ledger", "executor-actions.jsonl")
    if not os.path.exists(p):
        return None, []
    with open(p, encoding="utf-8") as f:
        return p, [json.loads(l) for l in f.read().splitlines() if l.strip()]

ident = {"src": "arg", "value": KEY}

# A1 allowed gated write
g1 = client._executor_grant_gate(dict(ident), "sign", KEY, ticket="t1")
out["a1_keys"] = g1.get("keys")
out["a1_err"] = g1.get("err")
p, rs = rows()
out["a1_path"] = p
out["a1_rows"] = rs
if rs:
    out["a1_len"] = max(len(json.dumps(r)) for r in rs)

# A2 refusals: ungranted op (cleanup) + meta-op
g2 = client._executor_grant_gate(dict(ident), "cancel", KEY, ticket="t1")
g2b = client._executor_grant_gate(dict(ident), "manage-grants", KEY, ticket="t1")
out["a2_err_cancel"] = bool(g2.get("err"))
out["a2_err_meta"] = bool(g2b.get("err"))
_, rs2 = rows()
out["a2_rows"] = [r for r in (rs2 or []) if r.get("decision") == "refused"]

# A3 replay: same attempt again -> no second row
client._executor_grant_gate(dict(ident), "sign", KEY, ticket="t1")
_, rs3 = rows()
out["a3_allowed_count"] = len([r for r in (rs3 or []) if r.get("decision") == "allowed"
                               and r.get("ticket") == "t1"])
out["a3_total"] = len(rs3 or [])

# A4 exempt channel: lane-agent surface -> no gate, no row.
# The identity-src derivation env wins over identity["src"] (client._executor_channel
# reads it first), so the exempt leg must set the knob to "env" too — otherwise the
# channel stays "arg" and the named session is gated (test-side env bug, fixed in
# arbitration: the exempt pass was never actually exercised).
os.environ["SANDBAR_CALLER_SURFACE"] = "lane-agent"
os.environ["SANDBAR_CALLER_IDENTITY_SRC"] = "env"
ident_env = {"src": "env", "value": KEY}
g4 = client._executor_grant_gate(dict(ident_env), "sign", KEY, ticket="t1")
_, rs4 = rows()
out["a4_err"] = g4.get("err")
out["a4_keys_empty"] = g4.get("keys") == {}
out["a4_total"] = len(rs4 or [])
os.environ.pop("SANDBAR_CALLER_SURFACE", None)
os.environ["SANDBAR_CALLER_IDENTITY_SRC"] = "arg"

# A5 append failure: the record file made unwritable, gate verdict unchanged, gap
# loud. Injection target fixed in arbitration: chmod on the DIRECTORY does not fail
# an append to an already-existing file (O_APPEND write needs file, not dir, write
# permission), so the old injection never exercised the failure face.
ld = os.path.join(ROOT, KEY, "ledger")
ap = os.path.join(ld, "executor-actions.jsonl")
os.chmod(ap, 0o400)
g5 = client._executor_grant_gate(dict(ident), "sign", KEY, ticket="t2")
os.chmod(ap, 0o600)
out["a5_allowed"] = g5.get("err") is None and bool(g5.get("keys"))
gap = os.path.join(ld, "executor-actions.gaps.jsonl")
out["a5_gap_exists"] = os.path.exists(gap)
if os.path.exists(gap):
    with open(gap, encoding="utf-8") as f:
        out["a5_gap_rows"] = [json.loads(l) for l in f.read().splitlines() if l.strip()]

# A6 path shape: record only at ledger/, events ledger untouched
out["a6_stray_root_file"] = os.path.exists(os.path.join(ROOT, KEY, "executor-actions.jsonl"))
out["a6_events_exists"] = os.path.exists(os.path.join(ROOT, KEY, "ledger", "events.jsonl"))

print("RESULT_JSON=" + json.dumps(out))
'''
    import subprocess
    r = subprocess.run([PY, "-c", script, ENGINE_DIR, root, KEY, SESSION],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        leg("engine-runner", False, "engine interpreter exited %d: %s"
            % (r.returncode, (r.stderr or r.stdout).strip()[-400:]))
        fail_if_all_na(len(legs), len(na_legs), "t261004-11-record")
        print("SUMMARY pass=%d fail=%d env_fail=0 na=0"
              % (sum(1 for l in legs if l[1]), sum(1 for l in legs if not l[1])))
        sys.exit(1)
    line = [l for l in r.stdout.splitlines() if l.startswith("RESULT_JSON=")]
    out = json.loads(line[0][len("RESULT_JSON="):]) if line else {}

    # A1
    ok = (out.get("a1_err") is None
          and isinstance(out.get("a1_rows"), list) and len(out.get("a1_rows")) == 1
          and out.get("a1_path", "").endswith(os.path.join(KEY, "ledger", "executor-actions.jsonl")))
    leg("a1-allowed-row-at-project-ledger-path", ok,
        "" if ok else "err=%s rows=%s path=%s" % (out.get("a1_err"), out.get("a1_rows"), out.get("a1_path")))
    if out.get("a1_rows"):
        row = out["a1_rows"][0]
        need = {"v", "at", "op", "ticket", "grant", "grant_source", "session",
                "channel", "decision", "idem"}
        extra_forbidden = {"args", "receipt", "declaration", "payload"}
        ok2 = (set(row.keys()) == need | ({"reason"} if row.get("decision") == "refused" else set())
               and row.get("decision") == "allowed"
               and row.get("op") == "sign" and row.get("ticket") == "t1"
               and row.get("grant") == "sign"
               and row.get("session") == SESSION and row.get("channel") == "arg"
               and isinstance(row.get("at"), int) and row.get("at", 0) > 0
               and isinstance(row.get("v"), int)
               and out.get("a1_len", 0) < LINE_LIMIT
               and not (set(row.keys()) & extra_forbidden))
        leg("a1-schema-v1-fields-small-no-raw-args", ok2,
            "" if ok2 else "row=%s len=%s" % (row, out.get("a1_len")))
    else:
        leg("a1-schema-v1-fields-small-no-raw-args", False, "no row recorded (recording face missing?)")

    # A2
    rrows = out.get("a2_rows") or []
    ok = (out.get("a2_err_cancel") and out.get("a2_err_meta") and len(rrows) >= 2
          and all(r.get("decision") == "refused" and str(r.get("reason") or "").strip()
                  for r in rrows)
          and all(r.get("grant") in ("", None) for r in rrows))
    leg("a2-refused-attempts-recorded-with-reason", ok,
        "" if ok else "cancel_err=%s meta_err=%s rows=%s" % (out.get("a2_err_cancel"), out.get("a2_err_meta"), rrows))

    # A3
    leg("a3-replay-does-not-add-second-row",
        out.get("a3_allowed_count") == 1,
        "allowed t1 rows=%s total=%s" % (out.get("a3_allowed_count"), out.get("a3_total")))

    # A4
    leg("a4-exempt-channel-writes-no-row",
        out.get("a4_err") is None and out.get("a4_keys_empty") and out.get("a4_total") == out.get("a3_total"),
        "err=%s keys_empty=%s total=%s" % (out.get("a4_err"), out.get("a4_keys_empty"), out.get("a4_total")))

    # A5
    gaps = out.get("a5_gap_rows") or []
    leg("a5-append-failure-loud-verdict-unchanged",
        out.get("a5_allowed") and out.get("a5_gap_exists") and len(gaps) >= 1,
        "allowed=%s gap_exists=%s gaps=%s" % (out.get("a5_allowed"), out.get("a5_gap_exists"), gaps))

    # A6
    leg("a6-record-path-shape-events-ledger-untouched",
        not out.get("a6_stray_root_file") and not out.get("a6_events_exists"),
        "stray=%s events=%s" % (out.get("a6_stray_root_file"), out.get("a6_events_exists")))

    fail_if_all_na(len(legs), len(na_legs), "t261004-11-record")
    passed = sum(1 for l in legs if l[1])
    failed = len(legs) - passed
    print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (passed, failed))
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
