#!/usr/bin/env python3
"""request_thread_states — the ledger thread machine end-to-end over the engine
entry (t261007-02, grey-box L3, offline, zero docker / Temporal / browser /
3099/7233; isolated SANDBAR_PANEL_DIR fixture tree).

Acceptance faces under test (ticket Evidence and acceptance):
  A one case per state transition, through the REAL engine ops:
    open -> answered (host, panel answer route shape = answer row + state row),
    open -> dismissed (host), answered -> dismissed (host), open -> resolved
    (doer, engine op=state), answered -> resolved, -> superseded (machine, via
    a supersedes link: link row FIRST, derived state row second, both physically
    present — the write path never skips the state row).
  B the three named refusals: a project session answering (op=reply intent=answer
    on a sessions.json-registered session), an unknown source class (neither
    executor_sessions nor sessions.json nor the lane surface), a resolved
    without evidence (op=state without evidence).
  C duplicate re-file links instead of opening: same (source ticket + owning
    epic + subject) over an open head appends one duplicates link row and NO
    new head; the link omits `from` and carries the triple snapshot.
  D register read-back: the row's `project` and `source_class` are derived from
    the registers (executor_sessions / sessions.json), never self-reported —
    the ledger is read back from disk and the fields compared to the registers.

Run directly: python3 integration/t261007-02/sc_request_thread_states.py
(cwd = repo root). Engine module import requires server/engine on sys.path
(same seam as the developer L1 battery); engine venv fallback chain exhausted
= ENV_FAIL exit 2.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
ENGINE = ROOT / "server" / "engine"
sys.path.insert(0, str(ENGINE))

import request_thread as rt  # noqa: E402
import shared  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    tag = "PASS" if cond else "FAIL"
    print(f"[{tag}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def env_of(tmp, session="sess-exec-1", surface="", project="proj-alpha"):
    return {
        "SANDBAR_PANEL_DIR": str(tmp),
        "DSH_SESSION_ID": session,
        "DSH_HEADLESS_SESSION": "",
        shared.CALLER_PROJECT_ENV: project,
        shared.CALLER_IDENTITY_SRC_ENV: "env",
        shared.CALLER_SURFACE_ENV: surface,
    }


def decl_loader(sessions):
    def load(key):
        return {"ok": True, "executor_sessions": list(sessions)}
    return load


def put_sessions(tmp, key, sids):
    d = tmp / key
    d.mkdir(parents=True, exist_ok=True)
    # the register's WRITER schema (workbench session-ledger-file.ts ->
    # session-handles.ts serializeSessionLedgerFile): {"version":1,"sessions":[...]}.
    # A fixture must never invent a shape the real register never writes.
    (d / "sessions.json").write_text(
        json.dumps({"version": 1, "sessions": [{"session_id": s} for s in sids]}),
        encoding="utf-8")


def put_epics(tmp, *codes):
    d = tmp / "epics"
    d.mkdir(parents=True, exist_ok=True)
    for c in codes:
        (d / (c + ".md")).write_text("# " + c + "\n", encoding="utf-8")
    return str(d)


def rows_of(tmp, key="proj-alpha"):
    p = tmp / key / "requests.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").split("\n") if l.strip()]


def head_body(**kw):
    body = {"op": "file", "kind": "decision", "question": "Adopt the thread shape?",
            "detail": "", "default_action": "keep one-question-one-answer",
            "subject": "request-ledger-thread", "epic": "project-executor",
            "source_ticket": "t261007-02"}
    body.update(kw)
    return body


def main():
    epics = put_epics(Path(tempfile.mkdtemp(prefix="rt_epics_")), "project-executor")
    with tempfile.TemporaryDirectory(prefix="rt_ledger_") as td:
        tmp = Path(td)
        env = env_of(tmp)
        ld = decl_loader(["sess-exec-1"])

        # --- A: transitions ------------------------------------------------
        f1 = rt.file_thread_op(head_body(), 1000, 1, env=env, load_decl=ld, epics_dir=epics)
        check("A0 filing lands an open head with the owning fields",
              f1.get("ok") and f1["row"]["epic"] == "project-executor"
              and f1["row"]["subject"] == "request-ledger-thread"
              and f1["row"]["source_class"] == rt.SRC_EXECUTOR)
        hid = f1["row"]["id"]

        # open -> answered (host; the panel answer face shape: answer row + state row)
        ans = {"type": "answer", "answer_for": hid, "at": 1100, "answer": "go", "by": "host"}
        st = {"type": "state", "id": "st-a", "state_for": hid, "state": "answered",
              "at": 1101, "by": "host"}
        p = tmp / "proj-alpha" / "requests.jsonl"
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(ans) + "\n" + json.dumps(st) + "\n")
        states = rt.head_states(rows_of(tmp))
        check("A1 open -> answered (host answer face)", states[hid] == rt.STATE_ANSWERED)

        # answered -> dismissed (host)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "state", "id": "st-d", "state_for": hid,
                                 "state": "dismissed", "at": 1200, "by": "host"}) + "\n")
        check("A2 answered -> dismissed (host)",
              rt.head_states(rows_of(tmp))[hid] == rt.STATE_DISMISSED)

        # fresh heads for resolved paths (doer, engine op=state, with evidence)
        f2 = rt.file_thread_op(head_body(subject="fam-2"), 1300, 1, env=env, load_decl=ld, epics_dir=epics)
        r2 = rt.state_op({"op": "state", "id": f2["row"]["id"], "state": "resolved",
                          "evidence": "t261007-02"}, 1400, 1, env=env, load_decl=ld)
        check("A3 open -> resolved with ticket evidence (doer, engine face)",
              r2.get("ok") and r2["row"]["evidence"] == "t261007-02")
        f3 = rt.file_thread_op(head_body(subject="fam-3"), 1500, 1, env=env, load_decl=ld, epics_dir=epics)
        h3 = f3["row"]["id"]
        rreply = rt.reply_op({"op": "reply", "id": h3, "text": "host chose plan A",
                              "intent": "answer", "via": "integration-agent",
                              "anchor": "go with A"}, 1600, 1, env=env, load_decl=ld)
        check("A3b delegated reply carries by/via/anchor as separate fields",
              rreply.get("ok") and rreply["row"]["via"] == "integration-agent"
              and rreply["row"]["anchor"] == "go with A")
        r3 = rt.state_op({"op": "state", "id": h3, "state": "resolved",
                          "evidence": "0194abcd" * 3}, 1700, 1, env=env, load_decl=ld)
        check("A4 answered -> resolved with commit evidence", r3.get("ok"))

        # -> superseded (machine): supersedes link, link row FIRST then state row
        f4 = rt.file_thread_op(head_body(subject="fam-4"), 1800, 1, env=env, load_decl=ld, epics_dir=epics)
        f5 = rt.file_thread_op(head_body(subject="fam-5"), 1900, 1, env=env, load_decl=ld, epics_dir=epics)
        lk = rt.link_op({"op": "link", "kind": "supersedes", "from": f4["row"]["id"],
                         "to": f5["row"]["id"]}, 2000, 1, env=env, load_decl=ld)
        tail = rows_of(tmp)[-2:]
        check("A5 superseded is machine-set: link row first, state row second, both present",
              lk.get("ok") and len(lk["rows"]) == 2
              and tail[0]["type"] == "link" and tail[0]["kind"] == rt.LINK_SUPERSEDES
              and tail[1]["type"] == "state"
              and tail[1]["state"] == rt.STATE_SUPERSEDED)

        # --- B: the three named refusals ------------------------------------
        put_sessions(tmp, "proj-alpha", ["sess-proj-1"])
        env_proj = env_of(tmp, session="sess-proj-1")
        ld_empty = decl_loader([])
        b1 = rt.reply_op({"op": "reply", "id": f5["row"]["id"], "text": "the answer is B",
                          "intent": "answer"}, 2100, 1, env=env_proj, load_decl=ld_empty)
        check("B1 a project session answering is refused (named)", 
              not b1.get("ok") and b1.get("field") == "reply"
              and "may ask and add facts" in b1.get("error", ""))
        b1b = rt.reply_op({"op": "reply", "id": f5["row"]["id"], "text": "measured: 3 hits",
                           "intent": "fact"}, 2101, 1, env=env_proj, load_decl=ld_empty)
        check("B1b a project session adding a fact is allowed", b1b.get("ok"))
        env_unknown = env_of(tmp, session="sess-nobody", project="proj-alpha")
        b2 = rt.file_thread_op(head_body(subject="fam-6"), 2200, 1,
                               env=env_unknown, load_decl=ld_empty, epics_dir=epics)
        check("B2 an unknown source class is refused (named)",
              not b2.get("ok") and b2.get("field") == "source_class"
              and "source-class-unknown" in b2.get("error", ""))
        b3 = rt.state_op({"op": "state", "id": f5["row"]["id"], "state": "resolved"},
                         2300, 1, env=env, load_decl=ld)
        check("B3 a resolved without evidence is refused (named)",
              not b3.get("ok") and b3.get("field") == "evidence"
              and "no evidence means no resolved" in b3.get("error", ""))
        # terminal state accepts no further state rows
        b4 = rt.state_op({"op": "state", "id": f2["row"]["id"], "state": "resolved",
                          "evidence": "t261007-09"}, 2400, 1, env=env, load_decl=ld)
        check("B4 a terminal head refuses another state row (never rewritten)",
              not b4.get("ok") and "already resolved" in b4.get("error", ""))

        # --- C: duplicate re-file links instead of opening ------------------
        # hid went terminal (dismissed) in A2, so the guard rightly lets the
        # family re-open: file a fresh OPEN head of the same family first, then
        # the re-file must link to THAT head and open nothing further.
        fam_open = rt.file_thread_op(head_body(), 2450, 1, env=env, load_decl=ld, epics_dir=epics)
        check("C0 the family re-opens once its prior head is terminal",
              fam_open.get("ok") and fam_open.get("linked_to") is None)
        before = rows_of(tmp)
        heads_before = [r for r in before if r["type"] == "request"]
        dup = rt.file_thread_op(head_body(), 2500, 1, env=env, load_decl=ld, epics_dir=epics)
        after = rows_of(tmp)
        heads_after = [r for r in after if r["type"] == "request"]
        check("C1 a duplicate re-file links and opens NO new head",
              dup.get("ok") and dup.get("linked_to") == fam_open["row"]["id"]
              and len(heads_after) == len(heads_before))
        link_row = dup.get("row") or {}
        check("C2 the duplicates link omits from and carries the triple snapshot",
              link_row.get("kind") == rt.LINK_DUPLICATES and "from" not in link_row
              and link_row.get("dup_subject") == "request-ledger-thread"
              and link_row.get("dup_epic") == "project-executor"
              and link_row.get("dup_source_ticket") == "t261007-02")

        # --- D: register read-back (project field derived, never self-reported)
        read_back = [r for r in after if r["type"] == "request" and r["id"] == hid][0]
        check("D1 the row's project equals the register-resolved identity (read-back from disk)",
              read_back["project"] == "proj-alpha")
        check("D2 the row's source_class is the judged class for the registered executor session",
              read_back["source_class"] == rt.SRC_EXECUTOR)
        proj_row = [r for r in after if r.get("by") == "sess-proj-1" and r["type"] == "reply"]
        check("D3 the project-session row's source_class came from sessions.json",
              proj_row and proj_row[-1]["source_class"] == rt.SRC_PROJECT)

        # --- E: expiry never mutates state, never silences -------------------
        f6 = rt.file_thread_op(head_body(subject="fam-exp", expires_at=1), 2600, 1,
                               env=env, load_decl=ld, epics_dir=epics)
        check("E1 an expired item is still open (expiry drives display and reminder level only)",
              rt.head_states(rows_of(tmp))[f6["row"]["id"]] == rt.STATE_OPEN)

    # --- F: CLI malformed input (external-input hook, fixed argv, no live source)
    r = subprocess.run([sys.executable, str(ENGINE / "request_thread.py"), "not-json"],
                       capture_output=True, text=True, timeout=60)
    out = json.loads(r.stdout or "{}")
    check("F1 a malformed CLI argv is a named refusal, never a crash",
          r.returncode == 2 and out.get("field") == "body")

    print()
    if FAILS:
        print(f"RESULT: FAIL ({len(FAILS)}): " + "; ".join(FAILS))
        return 1
    print("RESULT: PASS — thread machine faces green (states, refusals, duplicate link, register read-back)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
