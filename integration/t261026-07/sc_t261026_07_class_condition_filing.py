#!/usr/bin/env python3
"""L3 integration scenario, ticket t261026-07 (build A: the class->condition table).

Intent: a request the executor files in a class that has a declared closing
condition carries that condition ON ITS FACE at filing time, and a request in
a class that is the human's word says so on its face -- so nobody waits for a
machine that will never come. The user-perceivable contract under host order
261026 ("the executor should close what it can close itself"):
  1. A `run-silent` filing carries a `resolves_when` whose kind is in the
     closed condition vocabulary and whose parameter names a citable row
     (a certification on that line) -- never a guessed id, never omitted.
  2. A `run-stalled` filing carries a condition that a later round row on the
     line can satisfy (the `round_after` kind the ticket adds).
  3. A `blocker` filing carries a condition naming its subject ticket
     (`ticket_closed` or `landing_on_line`).
  4. A `finding` or `question` filing is stamped on its face as NOT
     auto-closable (a human answer closes it) -- the stamp is readable from
     the LEDGER row (the reader side), not from the writer's receipt.
  5. A malformed condition parameter is refused with an error that names the
     failed check -- never a silent drop of the condition field.

Grey-box L3: the REAL executor_requests filing face and the REAL
run_watch filing path (append_request_row), read back through the on-disk
requests ledger over isolated tmp stores (KI-161: never the production
ledger). Offline seconds; zero docker / Temporal / browser; never touches
3099/7233.

Run: python3 -B integration/t261026-07/sc_t261026_07_class_condition_filing.py
(cwd = repo root)

Pre-implement tree red = the named TDD signal (a missing face FAILs by name,
never an anonymous crash); green required at the integration gate / merge.
Intent split: the sweep's EVALUATION of a declared condition (condition holds
-> resolved with evidence) is owned by t261019-44-request-sweep-resolution;
the residue pass over UNCONDITIONED heads is owned by
t261026-07-watch-sweep-residue; THIS entry uniquely owns what lands on the
row's face at filing time. Exit codes: 0 = PASS, 1 = FAIL (named), 2 =
ENV_FAIL.
"""
from __future__ import annotations

import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ENGINE = REPO / "server" / "engine"
PROJ = "sandbar"

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("PASS " if ok else "FAIL ") + name + (": " + detail if detail and not ok else ""))
    if not ok:
        FAILS.append(name + (": " + detail if detail else ""))


def engine_py() -> str:
    for cand in (REPO / "server/engine/.venv/bin/python",):
        if cand.exists():
            return str(cand)
    return sys.executable


def run_py(env: dict, script: str, timeout: int = 120) -> tuple[int, str]:
    p = subprocess.run([engine_py(), "-B", "-c", script],
                       capture_output=True, text=True, env=env, cwd=str(REPO),
                       timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def rows(env: dict, proj: str = PROJ) -> list:
    f = Path(env["SANDBAR_PANEL_DIR"]) / proj / "requests.jsonl"
    if not f.exists():
        return []
    return [json.loads(l) for l in f.read_text().splitlines() if l.strip()]


def session_env(tmp: Path) -> dict:
    env = dict(os.environ)
    env.update({
        "SANDBAR_CALLER_PROJECT": PROJ,
        "DSH_SESSION_ID": "session-sc-t261026-07-filing",
        "SANDBAR_CALLER_IDENTITY_SRC": "env",
        "SANDBAR_PANEL_DIR": str(tmp / "panel"),
        "SANDBAR_PROJECTS_DIR": str(tmp / "projects"),
        "SANDBAR_DELIVERY_LEDGER_DIR": str(tmp / "ledger"),
        "SANDBAR_INSTANCE_DIR": str(tmp / "instance"),
        "PYTHONDONTWRITEBYTECODE": "1",
        # the lane injects its own surface tag; the scenario is an external-env caller
        "SANDBAR_CALLER_SURFACE": "",
    })
    return env


def declare_executor(env: dict) -> None:
    """Name the fixture session as the project's declared executor session
    (the declaration seam: the host names executor sessions; the scenario
    writes the same declaration shape the Grants page writes)."""
    d = Path(env["SANDBAR_PROJECTS_DIR"]) / PROJ
    d.mkdir(parents=True, exist_ok=True)
    (d / "executor-grants.json").write_text(json.dumps(
        {"version": 1, "grants": {}, "executor_sessions": [env["DSH_SESSION_ID"]],
         "updated_by": "scenario", "updated_at": 0}))

def register_session(env: dict) -> None:
    d = Path(env["SANDBAR_PANEL_DIR"]) / PROJ
    d.mkdir(parents=True, exist_ok=True)
    (d / "sessions.json").write_text(json.dumps(
        {"version": 1, "sessions": [{"session_id": env["DSH_SESSION_ID"]}]}))


def file_request(env: dict, body: dict) -> tuple[dict, str]:
    script = (
        "import sys, json, time; sys.path.insert(0, %r)\n"
        "import executor_requests\n"
        "body = json.loads(%r)\n"
        "out = executor_requests.append_request(body, int(time.time() * 1000))\n"
        "print(json.dumps(out, ensure_ascii=False))\n" % (str(ENGINE), json.dumps(body))
    )
    rc, out = run_py(env, script)
    try:
        return json.loads(out), out
    except Exception:
        return {}, out


def watch_file(env: dict, project: str, kind: str, question: str,
               detail: dict) -> tuple[dict, str]:
    rw = {"kind": "round_after", "line": detail.get("line", "develop-buffer")}
    script = (
        "import sys, json, time; sys.path.insert(0, %r)\n"
        "import run_watch\n"
        "out = run_watch.append_request_row(%r, %r, %r, json.loads(%r), int(time.time() * 1000),\n"
        "       resolves_when=json.loads(%r))\n"
        "print(json.dumps(out, ensure_ascii=False))\n"
        % (str(ENGINE), project, kind, question, json.dumps(detail), json.dumps(rw))
    )
    rc, out = run_py(env, script)
    try:
        return json.loads(out), out
    except Exception:
        return {}, out


def main() -> int:
    if not ENGINE.is_dir():
        print("ENV_FAIL: engine tree missing: " + str(ENGINE))
        return 2
    tmp = Path(tempfile.mkdtemp(prefix="t261026-07-filing-"))
    atexit.register(lambda: shutil.rmtree(tmp, ignore_errors=True))
    env = session_env(tmp)
    register_session(env)
    declare_executor(env)

    now = {"v": 0}

    def base(kind, question, extra=None):
        now["v"] += 1
        body = {"kind": kind, "question": question,
                "subject": question, "detail": "auto",
                "default_action": "wait", "by": "executor:watch",
                "epic": "none", "epic_reason": "line-health"}
        body.update(extra or {})
        return body

    # --- A1: run-silent carries a citable certification condition -----------
    body = base("run-silent", "run-silent on line develop-buffer: no run row",
                {"resolves_when": {"kind": "green_cert_after",
                                   "cert": "cert-sc070001"}})
    rec, out = file_request(env, body)
    head = rec.get("row", {}) if isinstance(rec, dict) else {}
    if head:
        rw = head.get("resolves_when")
        check("run-silent-carries-condition",
              isinstance(rw, dict) and rw.get("kind") == "green_cert_after"
              and str(rw.get("cert", "")).startswith("cert-"),
              "row resolves_when: " + json.dumps(rw)[:200])
    else:
        check("run-silent-filing-face", False, "no row in receipt: " + out[:300])

    # --- A2: run-stalled carries a round-row condition (the watch path) -----
    rec2, out2 = watch_file(env, PROJ, "run-stalled",
                            "run-stalled on line develop-buffer: 2 pending",
                            {"line": "develop-buffer", "last_round": "round-1"})
    head2 = rec2.get("row", {}) if isinstance(rec2, dict) else {}
    if head2:
        rw2 = head2.get("resolves_when")
        check("run-stalled-carries-round-condition",
              isinstance(rw2, dict) and rw2.get("kind") == "round_after",
              "watch-filed row resolves_when: " + json.dumps(rw2)[:200])
    else:
        check("run-stalled-watch-filing-face", False, "no row: " + out2[:300])

    # --- A3: blocker carries a condition naming its subject ticket ----------
    body3 = base("blocker", "blocker: t26102001 fix needed",
                 {"ticket": "t102607-1",
                  "resolves_when": {"kind": "ticket_closed",
                                    "ticket": "t102607-1"}})
    rec3, out3 = file_request(env, body3)
    head3 = rec3.get("row", {}) if isinstance(rec3, dict) else {}
    if head3:
        rw3 = head3.get("resolves_when")
        check("blocker-carries-ticket-condition",
              isinstance(rw3, dict) and rw3.get("kind") in
              ("ticket_closed", "landing_on_line")
              and rw3.get("ticket") == "t102607-1",
              "blocker resolves_when: " + json.dumps(rw3)[:200])
    else:
        check("blocker-filing-face", False, "no row: " + out3[:300])

    # --- A4: finding/question stamped NOT auto-closable on the face ---------
    for kind in ("finding", "question"):
        rec4, out4 = file_request(env, base(kind, kind + ": human word"))
        h = rec4.get("row", {}) if isinstance(rec4, dict) else {}
        if h:
            face = json.dumps(h, ensure_ascii=False)
            stamped = (h.get("auto_closable") is False
                       or "auto-closable" in face or "auto_closable" in face)
            note = "answer" in face or "human" in face
            check(kind + "-stamped-not-auto-closable", stamped and note,
                  "row face: " + face[:300])
        else:
            check(kind + "-filing-face", False, "no row: " + out4[:300])

    # reader side: the stamp must be on the LEDGER row, not only the receipt
    ledger_rows = rows(env)
    fq = [r for r in ledger_rows if r.get("kind") in ("finding", "question")]
    check("reader-side-face-stamp",
          bool(fq) and all(json.dumps(r, ensure_ascii=False).count(
              "auto_closable") + json.dumps(r, ensure_ascii=False).count(
              "auto-closable") >= 1 for r in fq),
          "ledger rows for finding/question: " + json.dumps(fq)[:300])

    # --- A5: malformed condition refused, the failed check named ------------
    body5 = base("run-silent", "run-silent malformed condition",
                 {"resolves_when": {"kind": "green_cert_after", "cert": ""}})
    rec5, out5 = file_request(env, body5)
    err = json.dumps(rec5, ensure_ascii=False) + out5
    named = rec5.get("ok") is False and ("cert" in err or "field" in rec5)
    check("malformed-condition-refused-named", named,
          "receipt: " + err[:300])
    orphaned = [r for r in rows(env)
                if r.get("question") == "run-silent malformed condition"
                and r.get("state", "open") == "open"
                and r.get("resolves_when") is not None]
    check("malformed-condition-never-silently-stored", not orphaned,
          "rows carrying the refused condition: " + json.dumps(orphaned)[:200])

    print("SUMMARY ran=1 pass=%d fail=%d" % (0 if FAILS else 1, len(FAILS)))
    if FAILS:
        for f in FAILS:
            print("  FAILED: " + f)
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print("ENV_FAIL: scenario could not run: %s: %s" % (type(e).__name__, e))
        sys.exit(2)
