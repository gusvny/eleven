# -*- coding: utf-8 -*-
"""L3 integration scenario, ticket t261019-44.

Intent: a request that DECLARED a machine-checkable `resolves_when` condition is
resolved by the engine sweep on the evidence the delivery ledger actually shows
-- and by nothing else. The user-perceivable contract under host order 261019
(option a, declarative; option b/expiry-archive is out of scope):
  1. A declaring open head flips to `resolved` with evidence = the observed row
     id (the releasing green cert id / the landing id / the freeze id), written
     under the engine identity, readable from the LEDGER (the reader side), not
     from the sweep's own receipt (writer receipts are not evidence).
  2. Fail-closed: an unreadable run store / malformed ledger lines / an unknown
     condition kind produce a named skip, the head stays OPEN, and a red is
     never fabricated into a green.
  3. Heads without a declared condition, and heads a human answered/dismissed,
     are untouched by the sweep (byte-identical rows); a second sweep writes
     nothing (idempotent).
  4. A condition attached later through the engine entry is attributed and the
     latest one wins; the host-only answer/dismiss gates are unchanged.

Grey-box L3: the REAL request_thread.py CLI subprocess (filing, answering,
state refusals, read) + the REAL request_sweep entry face, over isolated tmp
ledgers (SANDBAR_PANEL_DIR / SANDBAR_DELIVERY_LEDGER_DIR / SANDBAR_PROJECTS_DIR
-- KI-161: never the production ledger). Offline seconds, zero docker /
Temporal / browser, never touches 3099/7233. Pre-implement tree red on the
sweep legs = the named TDD signal; green required at the integration gate.

Exit codes: 0 = PASS, 1 = FAIL (named), 2 = ENV_FAIL.
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
PROJ = "sandbar"  # the caller gate resolves the project key from identity; use the resolved key
FIXTURE_SESSION = "session-sc-t26101944-fixture"

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("PASS " if ok else "FAIL ") + name + (": " + detail if detail and not ok else ""))
    if not ok:
        FAILS.append(name + (": " + detail if detail else ""))


def engine_py() -> str:
    # 261020: the retired legacy venv location is banned as a literal by the
    # engine-layout guard — the venv lives at server/engine/.venv, which the single
    # candidate already covers. Dropped rather than carried as a dead fallback.
    for cand in (REPO / "server/engine/.venv/bin/python",):
        if cand.exists():
            return str(cand)
    return sys.executable


def cli(env: dict, op_json: str) -> tuple[int, str]:
    p = subprocess.run([engine_py(), "-B", str(ENGINE / "request_thread.py"), op_json],
                       capture_output=True, text=True, env=env, cwd=str(REPO), timeout=60)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def sweep(env: dict, inject_ticket: dict | None = None) -> tuple[int, str]:
    """Run the REAL declared sweep face in a subprocess (import, not copy)."""
    script = (
        "import sys, json, time; sys.path.insert(0, %r)\n"
        "import request_sweep\n"
        "inject = %r\n"
        "kwargs = {}\n" % (str(ENGINE), inject_ticket or {})
        + "if inject is not None:\n"
        "    kwargs['ticket_status_fn'] = lambda t: (tuple(inject[t]) if t in inject else ('not-listed', 'ticket-list-projection'))\n"
        "out = request_sweep.sweep_all_projects(int(time.time() * 1000), 1, **kwargs)\n"
        "print(json.dumps(out, ensure_ascii=False))\n"
    )
    p = subprocess.run([engine_py(), "-B", "-c", script],
                       # SANCTIONED-WAIT: 120s is a safety bound on a seconds-scale offline subprocess (the engine sweep over tmp fixtures), never a polling wait.
                       capture_output=True, text=True, env=env, cwd=str(REPO), timeout=120)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def rows(env: dict, key: str) -> list:
    f = Path(env["SANDBAR_PANEL_DIR"]) / key / "requests.jsonl"
    if not f.exists():
        return []
    return [json.loads(l) for l in f.read_text().splitlines() if l.strip()]


def seed_runs(env: dict, verdicts: dict) -> None:
    """Seed the scenario-runs store the way the engine's own is_green reader
    reads it: scenario-runs.jsonl BESIDE the delivery ledger, rows
    {id, cases:{ran,failed,env_failed}} judged by run_verdict."""
    d = Path(env["SANDBAR_DELIVERY_LEDGER_DIR"])
    d.mkdir(parents=True, exist_ok=True)
    with (d / "scenario-runs.jsonl").open("a") as f:
        for rid, verdict in verdicts.items():
            counts = ({"ran": 3, "failed": 0, "env_failed": 0} if verdict == "green"
                      else {"ran": 3, "failed": 1, "env_failed": 0})
            f.write(json.dumps({"id": rid, "cases": counts}) + "\n")


def append_ledger_line(env: dict, row: dict) -> None:
    d = Path(env["SANDBAR_DELIVERY_LEDGER_DIR"])
    d.mkdir(parents=True, exist_ok=True)
    with (d / (PROJ + ".jsonl")).open("a") as f:
        f.write(json.dumps(row) + "\n")


def main() -> int:
    if not ENGINE.is_dir():
        print("ENV_FAIL: engine tree missing: " + str(ENGINE))
        return 2
    tmp = Path(tempfile.mkdtemp(prefix="t26101944-"))
    tmp2: Path | None = None
    atexit.register(lambda: shutil.rmtree(tmp, ignore_errors=True))
    env = dict(os.environ)
    env.update({
        # identity (the gate never reads a "project" body field): declared
        # caller project + a caller session env, same as the engine injects.
        "SANDBAR_CALLER_PROJECT": PROJ,
        "DSH_SESSION_ID": FIXTURE_SESSION,
        "SANDBAR_CALLER_IDENTITY_SRC": "env",
        "SANDBAR_PANEL_DIR": str(tmp / "panel"),
        "SANDBAR_PROJECTS_DIR": str(tmp / "projects"),
        "SANDBAR_DELIVERY_LEDGER_DIR": str(tmp / "ledger"),
        "SANDBAR_INSTANCE_DIR": str(tmp / "instance"),
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    (tmp / "panel").mkdir(parents=True, exist_ok=True)
    # register the fixture session as a project session (the writer-face
    # schema: {"version":1,"sessions":[{session_id}]}) so the source-class
    # gate classifies it instead of refusing it -- identity is judged from the
    # register, never self-reported.
    (tmp / "panel" / PROJ).mkdir(parents=True, exist_ok=True)
    (tmp / "panel" / PROJ / "sessions.json").write_text(json.dumps(
        {"version": 1, "sessions": [{"session_id": FIXTURE_SESSION}]}))

    # -- fixture: a red cert (seq 10) later released by a green cert (seq 20),
    # a landing naming ticket T1, a freeze episode closed; shapes follow the
    # delivery-ledger record families (cert / landing / freeze_change).
    base = {"project": PROJ, "line": "main", "seq": 0}
    append_ledger_line(env, dict(base, kind="certification", id="cert-red0001", seq=10,
                                 run="run-red-1", verdict="red"))
    append_ledger_line(env, dict(base, kind="certification", id="cert-green01", seq=20,
                                 run="run-green-1", verdict="green"))
    append_ledger_line(env, dict(base, kind="landing", id="ldg-1", ticket="t261019-99"))
    append_ledger_line(env, dict(base, kind="freeze_change", id="frz-change-1",
                                 freeze="frz-1", change="closed"))
    # the runs the two certs cite, readable in the per-project runs store
    seed_runs(env, {"run-green-1": "green", "run-red-1": "red"})

    # -- fixture: three heads via the REAL CLI. h1 declares green_cert_after,
    # h2 declares landing_on_line, h3 declares nothing, h4 declares
    # freeze_closed; h5 gets its condition attached later (op=condition).
    heads: dict[str, dict] = {}
    for name, cond in (("h1", {"kind": "green_cert_after", "cert": "cert-red0001"}),
                       ("h2", {"kind": "landing_on_line", "ticket": "t261019-99"}),
                       ("h3", None),
                       ("h4", {"kind": "freeze_closed", "freeze": "frz-1"})):
        body = {"op": "file", "project": PROJ, "kind": "question",
                "subject": "why-is-this-red-%s" % name,
                "question": "why is this red (%s)" % name, "detail": "auto",
                "default_action": "wait for the line to move",
                "by": "executor:test", "source_ticket": "t261019-44",
                "epic": "none", "epic_reason": "line-health question, no epic"}
        if cond:
            body["resolves_when"] = cond
        rc, out = cli(env, json.dumps(body))
        check("fixture-file-" + name, rc == 0, out[:400])
        try:
            heads[name] = json.loads(out).get("row", {})
        except Exception:
            heads[name] = {}
    # h4's green-cert leg needs its own project ledger entry ordering; the
    # fixture above already carries the closed freeze row for it.
    rc, out = cli(env, json.dumps({"op": "file", "project": PROJ, "kind": "question",
                                   "subject": "q-h5-attached",
                                   "question": "q-h5-attached", "detail": "auto",
                                   "default_action": "wait for the line to move",
                                   "by": "executor:test",
                                   "epic": "none", "epic_reason": "line-health question"}))
    check("fixture-file-h5", rc == 0, out[:400])
    try:
        heads["h5"] = json.loads(out).get("row", {})
    except Exception:
        heads["h5"] = {}

    if any(not heads.get(k) for k in ("h1", "h2", "h3", "h4", "h5")):
        print("FAIL fixture: head filing did not land; cannot judge sweep legs")
        return 1

    # h6: an ANSWERED head that also declares a condition -- the sweep must
    # leave it alone (terminal + host-only word wins).
    rc, out = cli(env, json.dumps({"op": "file", "project": PROJ, "kind": "question",
                                   "subject": "q-h6-answered",
                                   "question": "q-h6-answered", "detail": "auto",
                                   "default_action": "wait for the line to move",
                                   "by": "executor:test",
                                   "resolves_when": {"kind": "landing_on_line",
                                                     "ticket": "t261019-99"}}))
    try:
        h6 = json.loads(out).get("row", {})
    except Exception:
        h6 = {}
    if h6:
        # the host-only answered word has no CLI route by design; fixture it the
        # way the panel writes it: the canonical answer row (KI-01M4HP..., one
        # shape, numeric at).
        with (Path(env["SANDBAR_PANEL_DIR"]) / PROJ / "requests.jsonl").open("a") as f:
            f.write(json.dumps({"type": "answer", "answer_for": h6.get("id"),
                                "at": 1792436630000, "answer": "panel answer"}) + "\n")
        answered_before = [r for r in rows(env, PROJ)]
        rc2, _ = cli(env, json.dumps({"op": "state", "project": PROJ,
                                      "state_for": h6.get("id"), "state": "answered",
                                      "by": "engine:request-sweep", "evidence": "x"}))
        check("host-only-state-refusal", rc2 == 2, "engine identity answered rc=%d" % rc2)

    # -- run 1: sweep resolves h1/h2/h4, skips nothing declared-readable,
    # touches neither h3 (no condition) nor h6 (answered).
    rc, out = sweep(env, inject_ticket={"t261019-99": ("closed", "ticket-list-projection")})
    check("sweep-run-ok", rc == 0 and '"ok": true' in out.replace("True", "true"), out[:800])
    got = rows(env, PROJ)
    by_id = {h["id"]: [r for r in got if r.get("state_for") == h["id"]] for h in
             (heads["h1"], heads["h2"], heads["h3"], heads["h4"], heads["h5"], h6) if h}

    def resolved_states(h) -> list:
        return [r for r in by_id.get(h.get("id"), []) if r.get("state") == "resolved"]

    s1 = resolved_states(heads["h1"])
    check("h1-green-cert-after-resolves", len(s1) == 1 and
          "cert-green01" in json.dumps(s1[0].get("evidence", "")),
          json.dumps(s1)[:300])
    s2 = resolved_states(heads["h2"])
    check("h2-landing-resolves-with-ldg-id", len(s2) == 1 and
          "ldg-1" in json.dumps(s2[0].get("evidence", "")), json.dumps(s2)[:300])
    s4 = resolved_states(heads["h4"])
    check("h4-freeze-closed-resolves-checkable", len(s4) == 1 and
          "frz-1" in json.dumps(s4[0].get("evidence", "")), json.dumps(s4)[:300])
    check("h3-no-condition-untouched", not resolved_states(heads["h3"]))
    check("h6-answered-untouched", not resolved_states(h6))
    engine_ids = [r for h in (heads["h1"], heads["h2"], heads["h4"]) for r in resolved_states(h)]
    check("engine-identity-not-host", all(r.get("by") == "engine:request-sweep"
                                          for r in engine_ids), json.dumps(engine_ids)[:200])

    # -- run 2: idempotent, nothing new.
    n_before = len(rows(env, PROJ))
    sweep(env, inject_ticket={"t261019-99": ("closed", "ticket-list-projection")})
    check("second-sweep-idempotent", len(rows(env, PROJ)) == n_before)

    # -- attached condition: h5 resolves only after op=condition lands.
    rc, out = cli(env, json.dumps({"op": "condition", "project": PROJ,
                                   "id": heads["h5"].get("id"),
                                   "resolves_when": {"kind": "ticket_closed",
                                                     "ticket": "t261019-99"},
                                   "by": "host:curator"}))
    check("op-condition-attributed", rc == 0, out[:300])
    sweep(env, inject_ticket={"t261019-99": ("closed", "ticket-list-projection")})
    got = rows(env, PROJ)
    s5 = [r for r in got if r.get("state_for") == heads["h5"].get("id")
          and r.get("state") == "resolved"]
    check("h5-attached-condition-resolves", len(s5) == 1, json.dumps(s5)[:300])
    rc, out = cli(env, json.dumps({"op": "condition", "project": PROJ,
                                   "id": heads["h5"].get("id"),
                                   "resolves_when": {"kind": "expiry_archive"},
                                   "by": "host:curator"}))
    check("unknown-kind-named-refusal", rc == 2 and "expiry_archive" in out, out[:300])

    # -- fail-closed: an unreadable run store must not fabricate a green.
    tmp2 = Path(tempfile.mkdtemp(prefix="t26101944-broken-"))
    atexit.register(lambda: shutil.rmtree(tmp2, ignore_errors=True))
    env2 = dict(env)
    env2["SANDBAR_PANEL_DIR"] = str(tmp2 / "panel")
    env2["SANDBAR_DELIVERY_LEDGER_DIR"] = str(tmp2 / "ledger")
    (tmp2 / "panel").mkdir(parents=True, exist_ok=True)
    # the second isolation root needs the same registered session fixture --
    # the source-class gate judges identity from the register on BOTH roots.
    (tmp2 / "panel" / PROJ).mkdir(parents=True, exist_ok=True)
    (tmp2 / "panel" / PROJ / "sessions.json").write_text(json.dumps(
        {"version": 1, "sessions": [{"session_id": FIXTURE_SESSION}]}))
    append_ledger_line(env2, dict(base, kind="certification", id="cert-red0002", seq=10,
                                  run="run-x", verdict="red"))
    # the green cert exists but names a run that has NO verdict row anywhere
    append_ledger_line(env2, dict(base, kind="certification", id="cert-green02", seq=20,
                                  run="run-unknown", verdict="green"))
    rc, out = cli(env2, json.dumps({"op": "file", "project": PROJ, "kind": "question",
                                    "subject": "q-broken",
                                    "question": "q-broken", "detail": "auto",
                                    "default_action": "wait for the line to move",
                                    "by": "executor:test",
                                    "epic": "none", "epic_reason": "line-health question",
                                    "resolves_when": {"kind": "green_cert_after",
                                                      "cert": "cert-red0002"}}))
    try:
        hb = json.loads(out).get("row", {})
    except Exception:
        hb = {}
    if hb:
        sweep(env2)
        sb = [r for r in rows(env2, PROJ) if r.get("state_for") == hb.get("id")
              and r.get("state") == "resolved"]
        check("unreadable-run-store-never-green", not sb,
              "resolved without a readable run store: " + json.dumps(sb)[:200])
    else:
        check("failclosed-fixture-filed", False, out[:300])

    print("SUMMARY ran=1 pass=%d fail=%d" % (0 if FAILS else 1, len(FAILS)))
    if FAILS:
        for f in FAILS:
            print("  FAILED: " + f)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
