#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Board reader real-shape lock (t260929-07; env/product split from t261101-19).

WHY THIS CASE EXISTS (t260929-07). makeBoardReader once accepted only
`{result:{ok,tickets}}`. The real entry `client.py ticket-list {}` prints
`{ok:true,result:{count,tickets}}`, with NO `ok` key inside `result`. Every
stub-driven scenario fed the reader rows that the implementation itself had
shaped, so the suite stayed green while reconcile was always degraded (the
KI-148/150 self-proving fixture family). This case reads the engine's ACTUAL
stdout instead.

THE SPLIT THIS CASE NOW MAKES (t261101-19, measured defect: the case booked a
product red inside a line round and passed standalone on the same tree, because
the round pinned a TEST target that was not running). Two failure families are
now named apart:

  - a missing CONTEXT is not a content red. An engine target this environment
    cannot reach, or one that is not the target the reader was told to read,
    books a NAMED ENV_FAIL (exit 2). The name says which check failed and what
    the evidence was.
  - a reader that GOT a board document and handled it wrong still reds by name
    (exit 1). The same holds for a reader whose own shelling is broken (spawn
    failure), because no target is involved in that shape.

The distinction is made from evidence this case can see: the error KIND in the
reader's own text (a connection error from the real engine entry, or a call
that produced no answer at all) is a context failure; a shape/contract error is
a product failure. Leg C is never skipped, and it never passes without rows.

LEGS
  A  real-entry probe. One read-only `client.py ticket-list {}` against the
     deployed engine. A connection-kind envelope, a nonzero exit, a timeout or
     non-JSON stdout = ENV_FAIL named with the target in force and who stated it.
  B  real-shape lock. Leg A's byte-identical stdout through the shipped parse
     path (`parseTicketListDoc`), plus the envelope contract: the real document
     is an envelope whose inner `result` carries no `ok` key. An engine-side
     contract change turns this red on purpose.
  C  reader end to end. `makeBoardReader(repo)()` has three named outcomes:
     accepted rows = pass; no board document at all = ENV_FAIL corroborated by
     a second probe of this case; a document the reader rejected, or a spawn
     defect of its own = product red by name.
  D  malformed input matrix. HERMETIC: it runs before the engine probe, so a
     malformed stdout is always judged, whatever the target does.
  E  envelope form. HERMETIC, same rule as D.
  F  split truth table. HERMETIC. The classifier is pinned over the measured
     error strings (including the line round's own recorded evidence), over the
     shipped parse path's real rejections (no malformed document may read as an
     environment red), and over a live self-proof: the shipped reader, given a
     provably closed port, must land in the environment class.

THREE STATES. node, the shipped reader module, the engine entry or a provably
closed port absent = ENV_FAIL exit 2. A reader or parse defect = FAIL exit 1 by
name. Zero writes, zero docker, zero 3099/7233/8233 contact.

Run directly: python3 integration/t260929-07/sc_watchdog_board_reader_real_shape.py
(cwd = repo root).
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import socket
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
ENGINE = ROOT / "server" / "engine"
NODE_TS = ROOT / "server" / "plugins" / "watchdog" / "node.ts"

sys.path.insert(0, str(HERE.parent))
from lib_env import clean_narrowing_env  # noqa: E402  (t260930-09 clean point)

#: The suite's own target statement (integration/run_scenarios.py
#: TEST_TARGET_SOURCE_ENV). It carries the suite's convenience value, not the
#: deployment's, so this case strips it and names what it stripped (t261017-10).
SUITE_TARGET_MARKER = "SANDBAR_SUITE_STATED_TARGET"
TARGET_ENV = "SANDBAR_TARGET_HOST"
DEFAULT_TARGET = "127.0.0.1:7233"
ENGINE_PROBE_TIMEOUT_S = 90
NODE_CALL_TIMEOUT_S = 120
#: The shipped reader's own wrapper for "the engine call produced no board
#: document" (server/plugins/watchdog/node.ts makeBoardReader catch branch).
READER_NO_ANSWER_MARK = "ticket-list 不可达（引擎离线/超时）"
#: Ports a self-proof may use for "provably nothing listens". Each candidate is
#: connected to first; a candidate that accepts is skipped by name below, never
#: assumed. No project port (3099/3199/7233/8233/17233/18233) is ever a candidate.
CLOSED_PORT_CANDIDATES = (1, 7, 9, 64999, 65533)

#: A connection failure named by the real engine entry itself. Narrow on
#: purpose: only a transport failure is a context red.
CONNECTION_RE = re.compile(
    r"Transient\w*Error|连接 temporal server 失败|Failed client connect|connection refused",
    re.I)
#: A spawn failure of the reader's own shelling. No target is involved, so this
#: one stays a product red.
SPAWN_RE = re.compile(
    r"ENOENT|EACCES|ENOEXEC|EPERM|Permission denied|No such file|not found", re.I)

PASS = 0
FAIL = 0


def trim(text, limit=300):
    """One-line, bounded rendering of evidence (the run record reads one line)."""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[:limit] + "…"


def ok(cond, leg, detail=None):
    """One judged leg row. A red row also lands as `FAIL <leg> — <reason>`, the
    shape the run record parses into named failing legs (t261031-14)."""
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✓ %s" % leg, flush=True)
        return True
    FAIL += 1
    why = "no detail" if detail is None else trim(detail)
    print("  ✗ %s :: %s" % (leg, why), flush=True)
    print("FAIL %s — %s" % (leg, why), flush=True)
    return False


def section(title):
    print("\n%s" % title, flush=True)


def summary(env_failed=0, na=0):
    print("\nSUMMARY pass=%d fail=%d env_fail=%d na=%d"
          % (PASS, FAIL, env_failed, na), flush=True)


def env_fail(reason):
    """The named missing-context exit (exit 2). Never a content red."""
    summary(env_failed=1)
    print("ENV_FAIL: %s" % trim(reason, 900), flush=True)
    sys.exit(2)


def pick_python():
    venv = ENGINE / ".venv" / "bin" / "python"
    if venv.is_file():
        return str(venv)
    fallback = shutil.which("python3")
    if fallback:
        return fallback
    env_fail("server/engine/.venv/bin/python and python3 are both absent; the "
             "engine cannot be probed")


def classify_reader_failure(error):
    """Pure: one reader error text -> "env" (context) or "product" (content).

    Evidence only: the reader's own message. A connection failure named by the
    real engine entry is a context failure. A call that produced no answer at
    all (killed by its own bound, no diagnostics) is a context failure too,
    because no board document reached the reader and therefore no reader
    contract was judged. A spawn defect of the reader's own shelling, a
    shape/contract rejection, or a silent failure are product failures.
    """
    if not isinstance(error, str) or not error.strip():
        return "product"          # a silent failure is the reader's own break
    if CONNECTION_RE.search(error):
        return "env"
    if SPAWN_RE.search(error):
        return "product"
    if READER_NO_ANSWER_MARK in error:
        body = error.split(READER_NO_ANSWER_MARK, 1)[1]
        # node prints "Command failed: <cmd> <args>\n<stderr>"; a killed child
        # leaves the command echo and no diagnostics at all.
        tail = body.split("\n", 1)[1].strip() if "\n" in body else ""
        if not tail:
            return "env"
    return "product"


def engine_ticket_list(py, env):
    """One read-only board read through the real entry. Never raises.

    Returns {"doc": <parsed JSON or None>, "raw": <stdout, byte-identical>,
    "text": <one-line evidence>, "timeout": bool, "rc": int|None}.
    """
    out = {"doc": None, "raw": "", "text": "", "timeout": False, "rc": None}
    try:
        proc = subprocess.run(
            [py, "client.py", "ticket-list", json.dumps({})],
            cwd=str(ENGINE), env=env, capture_output=True, text=True,
            timeout=ENGINE_PROBE_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        out["timeout"] = True
        out["text"] = ("client.py did not answer within %ds"
                       % ENGINE_PROBE_TIMEOUT_S)
        return out
    except OSError as e:
        out["text"] = "client.py could not start: %s" % e
        return out
    out["rc"] = proc.returncode
    out["raw"] = proc.stdout
    out["text"] = (proc.stderr or proc.stdout or "").strip()[:400]
    if proc.returncode != 0:
        return out
    try:
        out["doc"] = json.loads(proc.stdout)
    except ValueError:
        out["text"] = "stdout is not JSON: %r" % proc.stdout[:200]
        return out
    return out


def doc_reason(doc):
    """The engine's own error text from an error envelope, or ''."""
    if isinstance(doc, dict) and doc.get("ok") is False:
        return str(doc.get("error") or "")
    return ""


def owned_env():
    """The env this case owns for the engine it judges.

    Returns (env, target_label, owner_label). The suite's own target statement is
    stripped and named (t261017-10); a deployment statement is kept verbatim.
    """
    env = clean_narrowing_env(base=dict(os.environ))
    suite_stated = (os.environ.get(SUITE_TARGET_MARKER) or "").strip()
    owner = "the deployment env"
    if suite_stated and env.get(TARGET_ENV) == suite_stated:
        print("INTEG_ENV_OWNED: scrubbed suite-stated %s=%s — this case reads the "
              "engine the deployment runs" % (TARGET_ENV, suite_stated), flush=True)
        env.pop(TARGET_ENV, None)
        owner = "the deployment default (the suite's TEST target was scrubbed)"
    elif env.get(TARGET_ENV):
        owner = "the deployment env"
    else:
        owner = "the deployment default (no target stated in this env)"
    target = env.get(TARGET_ENV) or "%s (engine default)" % DEFAULT_TARGET
    return env, target, owner


def run_node(node, script, env, what):
    """Run one node probe script. Returns (parsed dict or None, note)."""
    try:
        proc = subprocess.run(
            [node, "--input-type=module", "-e", script],
            capture_output=True, text=True, env=env, timeout=NODE_CALL_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return None, "%s: node did not answer within %ds" % (what, NODE_CALL_TIMEOUT_S)
    except OSError as e:
        return None, "%s: node could not start: %s" % (what, e)
    if proc.returncode != 0:
        return None, "%s: node exit %d :: %s" % (
            what, proc.returncode, (proc.stderr or proc.stdout or "")[:400])
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1]), ""
    except (ValueError, IndexError):
        return None, "%s: node output is not JSON :: %s" % (what, proc.stdout[:300])


HERMETIC_SCRIPT = r"""
const m = await import(new URL('file://' + process.env.NODE_TS, import.meta.url).href);
const out = { hasParse: typeof m.parseTicketListDoc === 'function' };
if (out.hasParse) {
  out.env_ok = m.parseTicketListDoc('{"result":{"ok":true,"tickets":[{"id":"a"}]}}');
  out.env_err = m.parseTicketListDoc('{"result":{"ok":false,"error":"boom"}}');
  out.bad_json = m.parseTicketListDoc('<html>not json');
  out.empty = m.parseTicketListDoc('');
  out.no_tickets = m.parseTicketListDoc('{"count":1}');
  out.tickets_not_array = m.parseTicketListDoc('{"tickets":"nope"}');
  out.result_null = m.parseTicketListDoc('{"result":null,"tickets":[{"id":"a"}]}');
}
console.log(JSON.stringify(out));
"""

READER_SCRIPT = r"""
const m = await import(new URL('file://' + process.env.NODE_TS, import.meta.url).href);
const out = {};
out.reader = await m.makeBoardReader(process.env.REPO)();
console.log(JSON.stringify(out));
"""

LIVE_SCRIPT = r"""
const m = await import(new URL('file://' + process.env.NODE_TS, import.meta.url).href);
const fs = await import('node:fs');
const raw = fs.readFileSync(process.env.RAW_FILE, 'utf8');
const out = { live: m.parseTicketListDoc(raw) };
out.reader = await m.makeBoardReader(process.env.REPO)();
console.log(JSON.stringify(out));
"""

#: Fixed strings the split table is pinned against, including the line round's
#: own recorded evidence (t261101-19 body: leg C's error text, verbatim shape).
SPLIT_TABLE = (
    ("the line round's own leg C evidence (a call killed by its own bound)",
     "ticket-list 不可达（引擎离线/超时）：Command failed: /private/var/folders/x/"
     "line-round-osmdukh7/sandbar/server/engine/.venv/bin/python client.py "
     "ticket-list {}\n", "env"),
    ("the engine entry's own connection failure, wrapped by the reader",
     'ticket-list 回执异常（tickets 非数组）：{"ok":false,"error":'
     '"TransientConnectError: 连接 temporal server 失败（127.0.0.1:17233，瞬时，'
     '请刷新重试）：RuntimeError: Failed client connect"', "env"),
    ("the reader's own shelling is broken (no target involved)",
     "ticket-list 不可达（引擎离线/超时）：Command failed: "
     "/repo/server/engine/.venv/bin/python client.py ticket-list {}\n"
     "spawn /repo/server/engine/.venv/bin/python ENOENT", "product"),
    ("a shape rejection of a document that did arrive",
     'ticket-list 回执异常（tickets 非数组）：{"count":1}', "product"),
    ("a silent failure (no reason at all)", "", "product"),
)


def closed_port():
    """A loopback port that provably refuses a connection (or None)."""
    for port in CLOSED_PORT_CANDIDATES:
        sock = socket.socket()
        sock.settimeout(0.5)
        try:
            sock.connect(("127.0.0.1", port))
        except OSError:
            return port
        finally:
            sock.close()
    return None


def main():
    if not NODE_TS.is_file():
        env_fail("server/plugins/watchdog/node.ts is absent; this repo is not in "
                 "the expected shape")
    if not (ENGINE / "client.py").is_file():
        env_fail("server/engine/client.py is absent; the engine entry is not in place")
    node = shutil.which("node")
    if not node:
        env_fail("node is absent; the watchdog host half cannot be loaded")
    py = pick_python()
    probe_env, target, owner = owned_env()

    # ---------- D/E/F HERMETIC: judged before any engine contact ----------
    section("D/E hermetic: the shipped parse path over fixed documents")
    her_env = dict(probe_env, NODE_TS=str(NODE_TS))
    hermetic, note = run_node(node, HERMETIC_SCRIPT, her_env, "hermetic parse probe")
    if hermetic is None:
        ok(False, "D/E the shipped reader module loads and runs", note)
        summary()
        sys.exit(1)
    has_parse = hermetic.get("hasParse") is True
    ok(has_parse,
       "B/E the implementation exports the shared parse path parseTicketListDoc",
       "parseTicketListDoc is not exported (TDD red: the implementation is absent)")

    def bad(name, label):
        r = hermetic.get(name) or {}
        ok(r.get("ok") is False and isinstance(r.get("error"), str)
           and r.get("error") != "", label, r)

    if has_parse:
        bad("bad_json", "D non-JSON stdout -> structured ok:false with a reason")
        bad("empty", "D empty stdout -> structured ok:false")
        bad("no_tickets", "D missing tickets -> structured ok:false")
        bad("tickets_not_array", "D non-array tickets -> structured ok:false")
        bad("result_null", "D result present but null -> structured ok:false (never read as an unreachable engine)")
        env_err = hermetic.get("env_err") or {}
        ok(env_err.get("ok") is False and "boom" in str(env_err.get("error")),
           "D envelope ok:false -> the engine's own error text passes through", env_err)
        env_ok = hermetic.get("env_ok") or {}
        ok(env_ok.get("ok") is True
           and (env_ok.get("tickets") or [{}])[0].get("id") == "a",
           "E envelope form {result:{ok:true,tickets}} is still accepted (both shapes kept)",
           env_ok)

    section("F hermetic: the env/product split table and a live self-proof")
    for label, text, want in SPLIT_TABLE:
        got = classify_reader_failure(text)
        ok(got == want, "F split table: %s -> %s" % (label, want), got)
    # No malformed document may ever read as an environment red: the shipped
    # parse path's own rejections are judged product-class.
    if has_parse:
        for name in ("bad_json", "empty", "no_tickets", "tickets_not_array",
                     "result_null"):
            err = str((hermetic.get(name) or {}).get("error") or "")
            ok(classify_reader_failure(err) == "product",
               "F a shape rejection (%s) is never booked as an environment red" % name,
               err)
    port = closed_port()
    if port is None:
        env_fail("no provably closed loopback port among %r; the live self-proof "
                 "cannot model an unreachable target" % (CLOSED_PORT_CANDIDATES,))
    self_env = clean_narrowing_env(
        {TARGET_ENV: "127.0.0.1:%d" % port, "NODE_TS": str(NODE_TS),
         "REPO": str(ROOT)}, base=dict(os.environ))
    self_out, note = run_node(node, READER_SCRIPT, self_env,
                              "closed-port reader self-proof")
    reader_self = (self_out or {}).get("reader") or {}
    ok(reader_self.get("ok") is False,
       "F the shipped reader fails when nothing listens on the target (port %d)" % port,
       note or reader_self)
    ok(classify_reader_failure(reader_self.get("error")) == "env",
       "F the shipped reader's own unreachable-target error lands in the environment class",
       reader_self.get("error"))

    # ---------- A real-entry probe ----------
    section("A real-entry probe: client.py ticket-list {} (read-only), target=%s" % target)
    probe = engine_ticket_list(py, probe_env)
    live_doc = probe["doc"]
    if live_doc is None:
        if probe["timeout"]:
            env_fail("A the real engine entry did not answer within %ds (target=%s; "
                     "stated by %s): %s"
                     % (ENGINE_PROBE_TIMEOUT_S, target, owner, probe["text"]))
        if probe["rc"] not in (None, 0):
            env_fail("A the real engine entry exited %d (target=%s; stated by %s): %s"
                     % (probe["rc"], target, owner, probe["text"]))
        env_fail("A the real engine entry printed no JSON board document "
                 "(target=%s; stated by %s): %s" % (target, owner, probe["text"]))
    reason = doc_reason(live_doc)
    if CONNECTION_RE.search(reason):
        env_fail("A the engine target is unreachable in this environment "
                 "(target=%s; stated by %s): the real entry exits 0 with a "
                 "connection-failure envelope: %s" % (target, owner, reason[:400]))
    ok(isinstance(live_doc, dict), "A the real entry printed a JSON object",
       type(live_doc).__name__)
    if not isinstance(live_doc, dict):
        summary()
        sys.exit(1)

    # ---------- B/C: the live document through the shipped paths ----------
    section("B/C live: the shipped parse path and the reader end to end")
    # The document handed to the shipped parse path must be leg A's stdout,
    # byte-identical, never a re-render.
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as tf:
        tf.write(probe["raw"])
        raw_path = tf.name
    try:
        live_env = dict(probe_env, NODE_TS=str(NODE_TS), RAW_FILE=raw_path,
                        REPO=str(ROOT))
        live, note = run_node(node, LIVE_SCRIPT, live_env, "live parse/reader probe")
    finally:
        os.unlink(raw_path)  # tmp reclaim (L8)
    if live is None:
        ok(False, "B/C the shipped reader module loads and runs on the live document", note)
        summary()
        sys.exit(1)

    parsed = live.get("live") or {}
    ok(parsed.get("ok") is True,
       "B the live entry stdout through the shipped parse path -> ok=true", parsed)
    rows = parsed.get("tickets") or []
    ok(len(rows) > 0, "B the live board yields rows>0", len(rows))
    ok(all(isinstance(r, dict) and r.get("id") for r in rows),
       "B every live row carries an id", rows[:2])
    ok("result" in live_doc and isinstance(live_doc.get("result"), dict)
       and "ok" not in live_doc["result"],
       "B shape contract: the real document is an envelope whose inner result carries "
       "no ok key (an engine-side contract change turns this red on purpose)",
       {k: (list(v.keys()) if isinstance(v, dict) else type(v).__name__)
        for k, v in live_doc.items()})

    reader = live.get("reader") or {}
    if reader.get("ok") is True:
        ok(True, "C makeBoardReader(repo)() end to end ok=true")
        ok(len(reader.get("rows") or []) > 0, "C the reader yields rows>0",
           len(reader.get("rows") or []))
    else:
        why = reader.get("error")
        kind = classify_reader_failure(why)
        if kind == "env":
            # No board document reached the reader, so no reader contract was
            # judged. Corroborate with this case's own probe and name it.
            again = engine_ticket_list(py, probe_env)
            again_reason = doc_reason(again["doc"])
            if again["doc"] is None or CONNECTION_RE.search(again_reason):
                env_fail(
                    "C the engine target did not answer this case's own probe either "
                    "(target=%s; stated by %s): the reader got no board document, so no "
                    "reader contract was judged. reader error: %s | own probe: %s"
                    % (target, owner, why, again["text"] or again_reason))
            env_fail(
                "C the reader got no board document inside its own budget while this "
                "case's own probe read the same engine (target=%s; stated by %s): the "
                "target's answer time failed, not a reader contract. reader error: %s"
                % (target, owner, why))
        # The reader got a document (or its own shelling broke). Product red.
        # The leg name says WHICH check failed: a target was never involved in
        # a spawn failure, so that shape is named apart from a shape rejection.
        if SPAWN_RE.search(str(why or "")):
            leg = ("C makeBoardReader(repo)() can run the engine entry "
                   "(its own shelling is broken, no target involved)")
        else:
            leg = ("C makeBoardReader(repo)() end to end ok=true — the reader "
                   "rejected a board document")
        ok(False, leg, why)
        ok(False, "C the reader yields rows>0", "no rows: %s" % trim(why, 200))

    summary()
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
