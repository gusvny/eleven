#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_ticket_list_projection_parity.py — t261011-02 L3, two-face parity.

Intent (ticket t261011-02, user words: "the CLI row says what the engine row
says"): for the SAME ticket at the SAME moment, the CLI board face
(`server/tools/ticket.py` list) must agree per-key with the engine row face
(`server/engine/client.py` ticket-list rows). The predecessor defect: the CLI
projection rebuilt rows through fixed key whitelists, so lane_version /
develop_line (t261009-76), and earlier paused / paused_phase (t260908-01,
t260910-04) and exec_status / close_health / close_health_reason (t261009-21-03
family) never survived — the operator board read every ticket as legacy.

Faces under test (grey-box, bindings shallow):
  ENGINE FACE — the real engine row builder `_row_from_meta`, loaded in-process
    from the real client.py, driven over REAL meta shapes (a develop-buffer
    opt-in ticket, a between-segment paused ticket, a minimal no-snapshot
    closed row). close_ts is added by the row caller on the same face.
  CLI FACE — the real public op entry `ticket.run({'op': 'list'})`, fed the
    engine rows at the declared `_poc` transport seam (three-arg stub contract,
    t260922-10) — the only seam between the two faces.

The scenario goes RED if either face drops or recomputes a key:
  A per-key AGREEMENT — every key/value of the real engine row appears with the
    same value in the CLI row, for the develop-buffer ticket AND the paused
    ticket (the ticket's two named covers) plus the closed shape.
  B KEY-SET PARITY — the CLI emitted key set covers the full live engine key
    set (read from the real builder, never hardcoded); the day the engine adds
    a key and the projection does not carry it, this reds by name.
  C HONEST ABSENCE — an old-engine row missing the newer keys reads honestly
    empty (never guessed from other fields, never a crash).
  D SINGLE SOURCE — the CLI face must not re-derive: the engine-formatted
    `updated` string and epoch `updated_ts` arrive verbatim.

Scope guard (ticket NOT IN SCOPE): the console and the engine row face itself
are never touched — the engine face here is read, never modified.

Run: python3 integration/t261011-02/sc_ticket_list_projection_parity.py (cwd=repo root).
Exit: 0 PASS / 1 FAIL (named) / 2 ENV_FAIL (engine tree or ticket.py unreadable).
Offline seconds; zero docker/Temporal/browser; never touches 3099/7233.
"""
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))

PASS = 0
FAIL = 0


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


def _load(name, path):
    if not os.path.isfile(path):
        print("ENV_FAIL: %s missing: %s" % (name, path))
        sys.exit(2)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---- load both faces ----------------------------------------------------------
sys.path.insert(0, os.path.join(REPO, "server", "engine"))
try:
    client = _load("t26101102_engine_client", os.path.join(REPO, "server", "engine", "client.py"))
    ticket = _load("t26101102_ticket", os.path.join(REPO, "server", "tools", "ticket.py"))
except Exception as e:
    print("ENV_FAIL: engine/ticket modules unimportable: %r" % e)
    sys.exit(2)


# ---- real meta shapes (the engine row face is the single source) --------------

def meta_develop_buffer():
    # the buffer's first opt-in ticket (t261009-80 shape)
    return {"project": "sandbar", "workflow_id": "wf-80", "role": "developer",
            "status": "running", "title": "buffer first ticket",
            "stage": "implement", "stage_state": "running",
            "handoffs": [{}, {}], "pending": [],
            "worktree": ".lane/t261009-80", "workspace": "ws",
            "created": "2026-10-11 02:00:00", "updated": 1760135040,
            "lane_version": "develop-buffer-v1", "develop_line": "develop-buffer",
            "authorizations": [], "paused": False, "paused_phase": ""}


def meta_paused():
    # a between-segment paused ticket (t260908-01 face)
    m = meta_develop_buffer()
    m.update({"workflow_id": "wf-paused", "id": None, "title": "paused ticket",
              "lane_version": "", "develop_line": "",
              "paused": True, "paused_phase": "at_gate"})
    return m


def meta_legacy():
    # an old-engine ticket: no lane keys, no pause pair, no health keys at all
    m = meta_develop_buffer()
    m.update({"workflow_id": "wf-old", "title": "legacy"})
    for k in ("lane_version", "develop_line", "paused", "paused_phase"):
        m.pop(k, None)
    return m


def engine_row(meta, exec_status="RUNNING", close_ts=0.0):
    row = dict(client._row_from_meta("t-face", meta, exec_status))
    if close_ts:
        row["close_ts"] = close_ts  # caller-added on the same engine face
    return row


def cli_rows(engine_rows):
    """Feed the real engine rows across the transport seam into the real CLI
    face (public op entry), return the emitted rows keyed by id."""
    def fake_poc(subcmd, payload, caller=None):
        assert subcmd == "ticket-list"
        return {"ok": True, "result": {"tickets": [dict(r) for r in engine_rows]}}
    ticket._poc = fake_poc
    out = ticket.run({"op": "list"})
    return out, {r["id"]: r for r in out["tickets"]}


# ---- A + B: parity, the two named covers --------------------------------------

section("A/B two-face parity: develop-buffer ticket")
r_dev = engine_row(meta_develop_buffer(), "RUNNING", close_ts=0.0)
out, by_id = cli_rows([r_dev])
cli = by_id.get("t-face")
ok(cli is not None, "A develop-buffer ticket appears on the CLI face")
if cli:
    ok(cli.get("lane_version") == "develop-buffer-v1",
       "A lane_version agrees (%r)" % cli.get("lane_version"))
    ok(cli.get("develop_line") == "develop-buffer",
       "A develop_line agrees (%r)" % cli.get("develop_line"))
    missing = sorted(k for k in r_dev if k not in cli)
    ok(not missing, "B every live engine key carried (missing=%r)" % missing)
    bad = {k: (r_dev[k], cli.get(k)) for k in r_dev
           if k in cli and cli[k] != r_dev[k]}
    ok(not bad, "A no key recomputed/rename-drifted (diffs=%r)" % bad)

section("A/B two-face parity: currently paused ticket")
r_pause = engine_row(meta_paused(), "RUNNING", close_ts=0.0)
out, by_id = cli_rows([r_pause])
cli = by_id.get("t-face")
ok(cli is not None, "A paused ticket appears on the CLI face")
if cli:
    ok(cli.get("paused") is True and cli.get("paused_phase") == "at_gate",
       "A pause pair agrees (paused=%r phase=%r)" % (
           cli.get("paused"), cli.get("paused_phase")))
    missing = sorted(k for k in r_pause if k not in cli)
    ok(not missing, "B every live engine key carried (missing=%r)" % missing)
    bad = {k: (r_pause[k], cli.get(k)) for k in r_pause
           if k in cli and cli[k] != r_pause[k]}
    ok(not bad, "A no key recomputed/rename-drifted (diffs=%r)" % bad)

section("B closed-row shape (engine minimal variant + caller close_ts)")
r_closed = engine_row(meta_legacy(), "COMPLETED", close_ts=1760149200.0)
r_closed.pop("paused", None)
r_closed.pop("paused_phase", None)  # the minimal closed row omits the pair
out, by_id = cli_rows([r_closed])
cli = by_id.get("t-face")
ok(cli is not None, "B closed row appears on the CLI face")
if cli:
    ok(cli.get("close_health") == "ok" and cli.get("exec_status") == "COMPLETED",
       "B health/exec_status carried on the closed row")
    ok(cli.get("close_ts") == 1760149200.0, "B caller-added close_ts carried")
    missing = sorted(k for k in r_closed if k not in cli)
    ok(not missing, "B every closed-shape key carried (missing=%r)" % missing)

# ---- C: honest absence on a legacy row ----------------------------------------

section("C honest absence on a legacy (old-engine) row")
r_old = engine_row(meta_legacy(), "RUNNING")
for k in ("lane_version", "develop_line", "paused", "paused_phase",
          "close_health", "close_health_reason", "exec_status"):
    r_old.pop(k, None)
out, by_id = cli_rows([r_old])
cli = by_id.get("t-face")
ok(cli is not None, "C legacy row does not crash the list")
if cli:
    ok(cli.get("lane_version") == "" and cli.get("develop_line") == "",
       "C lane keys read honestly empty (legacy stays legacy, never guessed)")
    ok(cli.get("paused_phase") == "" and not cli.get("paused"),
       "C pause pair reads honestly empty")

# ---- D: single source, never re-derived ---------------------------------------

section("D the CLI face never re-derives")
r_d = engine_row(meta_develop_buffer(), "RUNNING")
r_d["updated"] = "12-31 23:59"   # engine-formatted at the engine's read point
r_d["updated_ts"] = 1
out, by_id = cli_rows([r_d])
cli = by_id.get("t-face")
ok(cli is not None and cli.get("updated") == "12-31 23:59"
   and cli.get("updated_ts") == 1,
   "D engine-formatted updated / epoch updated_ts arrive verbatim (got %r/%r)"
   % (cli and cli.get("updated"), cli and cli.get("updated_ts")))

# ---- verdict -------------------------------------------------------------------

print("\nPASS=%d FAIL=%d" % (PASS, FAIL))
if FAIL:
    print("FAIL: the CLI board face does not say what the engine row says")
    sys.exit(1)
print("PASS: CLI row face and engine row face agree per-key")
sys.exit(0)
