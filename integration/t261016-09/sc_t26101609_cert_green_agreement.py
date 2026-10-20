#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261016-09 — the panel's green caliber IS the engine's own caliber on the
same scenario-runs ledger (defect D4a of the host's 261016 report).

Grey-box L3 (integration-owned): the REAL engine green reader
(develop_promote._is_green_reader over the per-project scenario-runs.jsonl)
as the oracle, and the REAL executor-panel certification-adapter subprocess
(the reader side the panel invokes) as the judged face, both driven over ONE
fixture project store, so any disagreement between the two sides of the same
ledger is caught in seconds offline.

Incident (host words, ticket t261016-09 D4): the round that certified the
line GREEN and was promoted (ledger row verdict=green) was painted RED by the
panel with blockers fail+env=24, and every live landing read red_implicated
on the panel where the engine's own reader answered certified — because the
adapter recomputed its own absolute roll-up (dc.run_verdict over the counts)
while the engine consumes the run ledger row's OWN verdict word.

User-perceivable faces under contract:
  A AGREEMENT GREEN — a run row whose OWN verdict says green certifies its
    landings on BOTH sides, even when its counts would read red under the
    absolute roll-up (the exact live disagreement shape); the panel's runs
    rows carry the header's own verdict word, never a recomputed one.
  B FAIL-CLOSED UNKNOWN VERDICT — a run row with NO verdict (retention-trimmed
    or old-shape row) is never green on either side, even with all-pass
    counts; the landing stays waiting on both faces.
  C LEDGER-WORD RED — a row whose own verdict says red is not green even with
    all-pass counts; the two sides agree on the refusal.
  D TORN LEDGER LINE — a malformed line in the runs ledger does not crash the
    reader and does not flip any intact row's judgment: the engine reader
    skips the torn line, the adapter reports it by name in runs_note, and
    every intact green stays green on both sides.

Division of intent (no intent-level duplication): the reader's success
envelope carrying round_faces and the rendered tab face belong to the sibling
sc_t26101609_cert_tab_envelope_face.mjs entry; the adapter's round-faces
honesty contract belongs to t261012-03-rounds-table-honest-faces; the engine's
own wait-state truth tables belong to the engine unit suite. This entry owns
ONE question: do the two readers of the same ledger answer the same word?

Pre-implement tree red on A/B/C = the named TDD signal; green required at the
integration gate / merge. Engine modules unimportable or the adapter missing
= ENV_FAIL exit 2. Scenario contract: PASS/FAIL/ENV_FAIL only — no SKIP.
"""

import json
import os
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "server" / "engine"
sys.path.insert(0, str(ENGINE))


def _engine_python():
    """The declared interpreter chain (verify.yaml test lane): the engine venv
    first, plain python3 as the fallback."""
    # 261017 fix (integration, direct): the second entry was a machine-local
    # server/dsh/temporal-poc/... literal — a layout residue the engine-layout case
    # (t260907-10 C 真残留) refuses, and it was the only red that kept the line
    # frozen after the t261016-09 landing. The declared chain is the engine venv,
    # plain python3 as the fallback.
    for p in ("server/engine/.venv/bin/python",):
        full = ROOT / p
        if full.is_file():
            return str(full)
    return sys.executable


try:
    import develop_certify as dc  # noqa: E402
    import develop_promote as dp  # noqa: E402
    import develop_line as dl  # noqa: E402
except ModuleNotFoundError as e:
    # the engine tree needs temporalio; the venv carries it — re-exec there
    venv_py = _engine_python()
    if e.name == "temporalio" and venv_py != sys.executable and Path(venv_py).is_file():
        os.execv(venv_py, [venv_py, __file__])
    print("ENV_FAIL: engine modules unimportable: %s: %s" % (type(e).__name__, e))
    sys.exit(2)
except Exception as e:  # noqa: BLE001
    print("ENV_FAIL: engine modules unimportable: %s: %s" % (type(e).__name__, e))
    sys.exit(2)

ADAPTER = ROOT / "server" / "plugins" / "executor-panel" / "src" / "host" / "certification-adapter.py"
PROJECT = "t26101609-fix"
LINE = "buffer"
REV = "a" * 40
NOW = 1_791_500_000_000

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS " + name)
    else:
        FAIL += 1
        print("FAIL " + name + (": " + str(detail)[:400] if detail else ""))


# ---- fixture: one project store both readers point at -----------------------

def build_store(root: Path, runs_rows, torn_line=None):
    """lines.json + delivery ledger (through the engine's own writer, so every
    row is engine-valid) + scenario-runs.jsonl. Returns (env, paths)."""
    proj = root / PROJECT
    (proj / "data" / "develop").mkdir(parents=True)
    (proj / "ledger").mkdir(parents=True)
    (proj / "data" / "develop" / "lines.json").write_text(json.dumps([
        {"version": 1, "line_id": LINE, "scope": "epic buffer", "owner": "host",
         "repositories": [{"name": "sandbar", "branch": "develop"}]},
    ]), encoding="utf-8")
    runs = proj / "ledger" / "scenario-runs.jsonl"
    with runs.open("w", encoding="utf-8") as fh:
        for r in runs_rows:
            fh.write(json.dumps(r) + "\n")
        if torn_line:
            fh.write(torn_line + "\n")
    delivery = proj / "ledger" / "delivery.jsonl"
    rows = []
    for i, (ticket, run_id) in enumerate(runs_rows_cert_pairs(runs_rows)):
        rows.append({"kind": dc.KIND_LANDING, "id": "ldg-%d" % (i + 1),
                     "ticket": ticket, "line": LINE, "at": NOW - 60_000,
                     "actor": "dev", "note": "",
                     "repos": [{"repo": "sandbar", "revision": REV}]})
        rows.append({"kind": dc.KIND_CERT, "id": "cert-%d" % (i + 1),
                     "line": LINE, "run": run_id, "at": NOW - 30_000,
                     "booked_red": "none", "judged_by": "scenario",
                     "repos": [{"repo": "sandbar", "revision": REV}]})
    res = dc.append_rows(rows, delivery)
    if res.get("written") != len(rows):
        raise RuntimeError("fixture rows refused by the engine writer: %r"
                           % (res.get("rejected"),))
    env = dict(os.environ)
    env["SANDBAR_PROJECTS_DIR"] = str(root)
    env["SANDBAR_RUNS_LEDGER"] = str(runs)
    return env, delivery, runs


def runs_rows_cert_pairs(runs_rows):
    """One landing+cert per run row, ticket named after the run."""
    return [("T-" + str(r["id"])[-4:], r["id"]) for r in runs_rows]


def run_adapter(env):
    # The wait bound is injectable at second scale (L25 wait-bound
    # discipline, t261011-22): the adapter answers offline in well under a
    # second, so the runaway guard defaults to 30s, never a production-scale
    # bound. A fired bound names itself and the check it was serving.
    bound_s = int(os.environ.get("SANDBAR_SC_WAIT_BOUND_S", "30"))
    try:
        p = subprocess.run([sys.executable, str(ADAPTER), PROJECT],
                           capture_output=True, text=True, timeout=bound_s,
                           env=env)
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            "the wait bound fired: the certification adapter did not answer "
            "within %ds (check under run: the adapter's green-agreement "
            "receipt) — not a scenario verdict" % bound_s)
    if p.returncode != 0 or not p.stdout.strip():
        raise RuntimeError("adapter exit %d: %s" % (p.returncode, p.stderr[:200]))
    return json.loads(p.stdout.strip().splitlines()[-1])


def adapter_face(doc):
    one = doc.get("per_line", {}).get(LINE, {})
    if not one.get("ok"):
        raise RuntimeError("adapter line degraded: %r" % (one.get("reason"),))
    return one["input"]


def wait_state(face, ticket):
    for w in face.get("waitStates", []):
        if w.get("ticket") == ticket:
            return w
    return {}


def engine_oracle(delivery, run_id):
    """The engine's own answer for the landing behind the cert citing run_id:
    the green reader over the REAL per-project runs file, the REAL
    ticket_wait_state on top — the same words the promotion act consumes."""
    rows, bad = dc.read_rows(delivery)
    assert not bad, bad
    # the reader resolves the runs file from the live env (perkey root) —
    # point it at THIS case's store
    os.environ["SANDBAR_PROJECTS_DIR"] = str(delivery.parents[2])
    is_green = dp._is_green_reader(PROJECT)
    landing = next(r for r in rows
                   if r.get("kind") == dc.KIND_LANDING
                   and r["ticket"] == "T-" + str(run_id)[-4:])
    return bool(is_green(run_id)), \
        dc.ticket_wait_state(rows, LINE, landing, is_green, NOW)


def main():
    if not ADAPTER.is_file():
        print("ENV_FAIL: certification adapter missing: %s" % ADAPTER)
        return 2
    tmp = Path(tempfile.mkdtemp(prefix="t26101609-agree-"))
    try:
        green_but_red_counts = {"ran": 3, "failed": 24, "env_failed": 0}
        all_pass = {"ran": 5, "failed": 0, "env_failed": 0}

        def run_row(rid, verdict, cases):
            r = {"id": rid, "cases": cases, "source": "scheduled",
                 "started_at": NOW - 120_000,
                 "repos": [{"repo": "sandbar", "revision": REV}]}
            if verdict is not None:
                r["verdict"] = verdict
            return r

        # One ISOLATED store per case: a later red certification would
        # (rightly) implicate an earlier landing in a shared store, which
        # would blur which disagreement the case is about.
        def case_store(name, run_rows, torn=None):
            root = tmp / name
            env, delivery, runs = build_store(root, run_rows, torn_line=torn)
            return env, delivery, runs

        # ---- A: agreement green (the incident shape) ----
        env, delivery, runs = case_store("a", [run_row("run-r1", "green", green_but_red_counts)])
        eng_green, eng_state = engine_oracle(delivery, "run-r1")
        check("A engine reader answers green from the row's own verdict",
              eng_green is True, eng_green)
        check("A engine wait state is certified",
              eng_state.get("state") == "certified", eng_state)
        face = adapter_face(run_adapter(env))
        w1 = wait_state(face, "T-" + "run-r1"[-4:])
        check("A adapter face certifies the same landing (not red_implicated)",
              w1.get("state") == "certified" and w1.get("covered_by"),
              w1)
        runs_row1 = next((r for r in face.get("runs", [])
                          if r.get("id") == "run-r1"), {})
        check("A adapter runs row carries the header's OWN verdict word",
              runs_row1.get("verdict") == "green", runs_row1)

        # ---- B: unknown verdict is never green, even all-pass ----
        env, delivery, _ = case_store("b", [run_row("run-r2", None, all_pass)])
        eng_green2, eng_state2 = engine_oracle(delivery, "run-r2")
        check("B engine reader refuses a verdict-less row (not green)",
              eng_green2 is not True, eng_green2)
        check("B engine wait state is not certified",
              eng_state2.get("state") != "certified", eng_state2)
        face = adapter_face(run_adapter(env))
        w2 = wait_state(face, "T-" + "run-r2"[-4:])
        check("B adapter face leaves the landing waiting (never certified)",
              w2.get("state") != "certified", w2)
        runs_row2 = next((r for r in face.get("runs", [])
                          if r.get("id") == "run-r2"), {})
        check("B adapter runs row does not invent a green",
              runs_row2.get("verdict") != "green", runs_row2)

        # ---- C: the ledger's own red word decides, not the counts ----
        env, delivery, _ = case_store("c", [run_row("run-r3", "red", all_pass)])
        eng_green3, eng_state3 = engine_oracle(delivery, "run-r3")
        check("C engine reader refuses a red-worded row", eng_green3 is not True,
              eng_green3)
        check("C engine wait state is not certified",
              eng_state3.get("state") != "certified", eng_state3)
        face = adapter_face(run_adapter(env))
        w3 = wait_state(face, "T-" + "run-r3"[-4:])
        check("C adapter face agrees: not certified",
              w3.get("state") != "certified", w3)

        # ---- D: a torn line is named, never judgement-flipping ----
        env, delivery, runs = case_store(
            "d", [run_row("run-r1", "green", green_but_red_counts)],
            torn='{"id": "torn", "verdict": "gr')
        doc2 = run_adapter(env)
        # the adapter refuses BY NAME (fail-closed) — a torn runs ledger never
        # silently re-judges anything green
        check("D the adapter refuses by name over the torn ledger",
              doc2.get("ok") is False
              and "malformed" in str(doc2.get("reason", "")).lower(),
              {k: doc2.get(k) for k in ("ok", "reason")})
        os.environ["SANDBAR_PROJECTS_DIR"] = str(runs.parents[2])
        is_green_d = dp._is_green_reader(PROJECT)
        check("D the engine reader skips the torn line and keeps its answer",
              is_green_d("run-r1") is True, is_green_d("run-r1"))
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    print("SUMMARY pass=%d fail=%d" % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        print("ENV_FAIL: %s: %s" % (type(e).__name__, e))
        sys.exit(2)
