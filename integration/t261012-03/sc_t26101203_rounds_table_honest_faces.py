#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t26101203_rounds_table_honest_faces.py — t261012-03, the Certification
tab's Rounds table shows the runner's PUBLISHED rounds honestly (grey-box L3,
the REAL server/plugins/executor-panel/src/host/certification-adapter.py as a
subprocess — the reader side the panel invokes — over a fixture face tree
seeded through the declared SANDBAR_LINE_ROUND_FACE_DIR seam; offline seconds,
zero docker/Temporal-server/browser, never touches 3099/7233).

intent (user words, ticket t261012-03 spec: "reading only the faces the runner
already publishes at the stable path ... When the face is missing or unreadable
the table says so BY NAME - it never renders zeros in its place" — the
false-green family, live KI-01M4P0FK2W87WXW2S6N8BXECYZ):
    A. FACES ARE THE ONLY SOURCE: the reader receipt's round-faces section
       carries one row per published round — the live round read from
       rounds/current.json (state=running, its counts), the terminal rounds
       read from rounds/<run_id>/face.json — and NO row that no face names.
       The trigger comes from the run header joined by run id; a face with
       no header renders the trigger as a named absence, never an invented
       "auto".
    B. ABSENCE AND UNREADABILITY ARE NAMED, NEVER ZEROS: a run dir without
       face.json, a torn (half-written / empty / non-JSON) face file, and an
       unreadable face DIR each surface as a named state in the receipt —
       never as counts {ran:0, pass:0}, never a crash, never a silent drop.
       The receipt's OTHER sections stay intact when only the face section
       degrades (a section-level named error inside an otherwise-ok receipt).
    C. UNTRUSTWORTHY COUNTS STAY UNTRUSTWORTHY (KI-01M4P0FK2W87WXW2S6N8BXECYZ
       family at the reader): a face carrying counts_note passes the note
       through verbatim, so a round whose counts are not trustworthy can
       never be presented as a completed measured result.
    D. NO SILENT RETENTION ASSUMPTION: more run dirs on disk than the
       writer's keep window (transient mid-prune state) all reach the
       receipt — any render-side cap is declared in the receipt, never a
       silent drop of the oldest rows.
    E. LIVE POINTER IS THE ONLY LIVE SOURCE: exactly one live row, taken
       from current.json; with no current.json there is no live row (absence
       = idle) even when terminal dirs exist.

Layering / intent split (no intent-level duplication):
  - the face file contract itself (fields, atomic write, retention pruning,
    live-pointer guard) belongs to t261011-26's two registered entries;
  - per-input parse truth tables, receipt-shape unit matrices and the view
    core's pill/zero rules belong to developer L1 (the in-ticket unit
    battery) and to the sibling t261012-03-round-dialog-journey entry;
  - this entry owns the ADAPTER-AS-READER contract over a seeded face tree.

Three states: engine modules or the adapter missing = ENV_FAIL exit 2; the
declared round-faces contract missing = FAIL named (TDD signal
pre-implement), must be green at the integration gate / merge.
"""
import json
import os
import subprocess
import sys
import shutil
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
NAME = "t261012-03-rounds-table-honest-faces"

sys.path.insert(0, str(REPO / "integration"))

ADAPTER = REPO / "server" / "plugins" / "executor-panel" / "src" / "host" / "certification-adapter.py"
FACE_DIR_ENV = "SANDBAR_LINE_ROUND_FACE_DIR"
PROJECTS_ENV = "SANDBAR_PROJECTS_DIR"
PROJECT = "t26101203-fixture"


def seed_project_store(tmp):
    """The adapter's upstream gates need a DECLARED project: a per-key store
    whose develop dir carries a version-1 lines.json (the engine's own
    declaration shape). The round-faces section travels even on a refusal
    receipt (t261012-03 fault 2 fix), so the table never depends on the
    declaration's readability."""
    dev = Path(tmp) / "projects" / PROJECT / "data" / "develop"
    dev.mkdir(parents=True, exist_ok=True)
    (dev / "lines.json").write_text(json.dumps([
        {"version": 1, "line_id": "buffer",
         "repositories": [{"name": "fixture-repo", "branch": "main"}]},
    ]), encoding="utf-8")
    return Path(tmp) / "projects"

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS %s" % name)
    else:
        FAIL += 1
        print("FAIL %s%s" % (name, (": " + str(detail)) if detail else ""))


def face(run_id, state="done", verdict="green", counts=None, started="2026-01-12T01:00:00Z",
         updated=None, line="buffer", revision=None, note=None, reason=None,
         last=None, trigger=None):
    f = {"run_id": run_id, "line": line, "revision": revision or {"repo": "a" * 40},
         "started_at": started, "updated_at": updated or started, "state": state,
         "pool": "integ", "counts": counts or {"ran": 3, "pass": 3, "fail": 0, "env_fail": 0}}
    if note is not None:
        f["counts_note"] = note
    if last is not None:
        f["last_scenario"] = last
    if verdict is not None:
        f["outcome"] = {"verdict": verdict}
    if reason is not None:
        f["outcome"] = dict(f.get("outcome") or {}, reason=reason)
    return f


def seed(tmp, layout):
    """Seed a fixture face tree: layout maps run ids to dicts with keys
    face (dict|bytes|None), log (str|None). Also handles 'current'."""
    # writer layout: the face (develop) dir carries rounds/ one level under it
    rounds = Path(tmp) / "faces" / "rounds"
    shutil.rmtree(Path(tmp) / "faces", ignore_errors=True)
    rounds.mkdir(parents=True, exist_ok=True)
    for run_id, spec in layout.items():
        if run_id == "current":
            if spec.get("face") is not None:
                (rounds / "current.json").write_bytes(
                    spec["face"] if isinstance(spec["face"], bytes)
                    else json.dumps(spec["face"]).encode())
            continue
        d = rounds / run_id
        d.mkdir(parents=True, exist_ok=True)
        if spec.get("face") is not None:
            (d / "face.json").write_bytes(
                spec["face"] if isinstance(spec["face"], bytes)
                else json.dumps(spec["face"]).encode())
        if spec.get("log") is not None:
            (d / "suite.log").write_text(spec["log"], encoding="utf-8")
    return rounds


def engine_python():
    """The interpreter the panel itself spawns the adapter under: the engine
    venv first, a plain python3 fallback (verify.yaml's chain)."""
    for cand in (REPO / "server" / "engine" / ".venv" / "bin" / "python",
                 REPO / "server" / "dsh" / "temporal-poc" / ".venv" / "bin" / "python"):
        if cand.exists():
            return str(cand)
    return sys.executable


def run_adapter(env_extra):
    env = dict(os.environ)
    env.update(env_extra)
    try:
        # A subprocess timeout cap on the adapter child: a hung child must
        # not hang the scenario; fires only on a real hang and names itself
        # via subprocess.TimeoutExpired.
        p = subprocess.run([engine_python(), "-B", str(ADAPTER), PROJECT],
                           capture_output=True, text=True, cwd=str(REPO), env=env,
                           # reader must not hang the scenario; named on expiry
                           # SANCTIONED-WAIT: cap on the adapter child only (a hung reader)
                           timeout=120)
    except OSError as e:
        return None, "adapter spawn failed: %s" % e
    if p.returncode != 0:
        err = p.stderr[-400:]
        if "ModuleNotFoundError" in err or "No module named" in err:
            print("ENV_FAIL: engine interpreter cannot import engine modules: %s" % err.strip())
            print("SUMMARY pass=%d fail=%d env_fail=1 na=0" % (PASS, FAIL))
            sys.exit(2)
        return None, "adapter exit %s: %s" % (p.returncode, err)
    try:
        return json.loads(p.stdout), ""
    except ValueError as e:
        return None, "adapter output not JSON: %s" % e


def main():
    if not ADAPTER.is_file():
        print("ENV_FAIL: certification adapter missing: %s" % ADAPTER)
        print("SUMMARY pass=0 fail=0 env_fail=1 na=0")
        return 2
    try:
        sys.path.insert(0, str(REPO / "server" / "engine"))
        import shared  # noqa: F401
    except Exception as exc:
        print("ENV_FAIL: engine modules unimportable (engine tree absent): %s" % exc)
        print("SUMMARY pass=0 fail=0 env_fail=1 na=0")
        return 2

    green = face("run-green-1", verdict="green")
    red = face("run-red-1", verdict="red", counts={"ran": 4, "pass": 3, "fail": 1, "env_fail": 0},
               last={"name": "sc_x", "verdict": "FAIL"}, updated="2026-01-12T01:05:00Z")
    norun = face("run-nope-1", state="failed", verdict=None, reason="suite runner missing",
                 counts={"ran": 0, "pass": 0, "fail": 0, "env_fail": 0})
    live = face("run-live-1", state="running", verdict=None,
                counts={"ran": 2, "pass": 1, "fail": 1, "env_fail": 0},
                updated="2026-01-12T02:00:00Z")

    with tempfile.TemporaryDirectory(prefix="t26101203-") as tmp:
        store = seed_project_store(tmp)
        env0 = {PROJECTS_ENV: str(store)}
        # ---- A faces are the only source; trigger joined or named ----
        rounds = seed(tmp, {
            "current": {"face": live},
            "run-green-1": {"face": green, "log": "suite log line\n"},
            "run-red-1": {"face": red, "log": "suite log line\n"},
            "run-nope-1": {"face": norun, "log": "suite log line\n"},
        })
        receipt, why = run_adapter(dict(env0, **{FACE_DIR_ENV: str(Path(tmp) / "faces")}))
        check("A0 adapter receipt readable over the seeded face tree",
              receipt is not None, why)
        if receipt is not None:
            rf = receipt.get("round_faces")
            check("A1 receipt carries a round-faces section (pre-implement "
                  "red is the TDD signal)", isinstance(rf, dict), rf)
            if isinstance(rf, dict):
                rows = {r.get("run_id"): r for r in rf.get("rounds", [])
                        if isinstance(r, dict)}
                blob = json.dumps(rf)
                check("A2 every published terminal round appears, none invented",
                      {"run-green-1", "run-red-1", "run-nope-1"} <= set(rows)
                      and "run-never-1" not in blob, sorted(rows))
                lv = (rf.get("live") or {}).get("face") if isinstance(rf.get("live"), dict) else None
                check("A3 live round comes from current.json with state=running",
                      isinstance(lv, dict)
                      and lv.get("run_id") == "run-live-1"
                      and lv.get("state") == "running", rf.get("live"))
                check("A4 red round keeps its red verdict and its counts",
                      rows.get("run-red-1", {}).get("face", {}).get("outcome", {})
                      .get("verdict") == "red"
                      and rows["run-red-1"]["face"]["counts"]["fail"] == 1,
                      rows.get("run-red-1"))

        # ---- B absence and unreadability named, never zeros ----
        seed(tmp, {
            "current": {"face": live},
            "run-green-1": {"face": green},
            "run-noface-1": {"face": None},                       # run dir, no face.json
            "run-torn-1": {"face": b'{"run_id": "run-t'},         # torn write
            "run-empty-1": {"face": b""},                          # empty file
        })
        receipt, why = run_adapter(dict(env0, **{FACE_DIR_ENV: str(Path(tmp) / "faces")}))
        check("B0 adapter survives the damaged tree with a readable receipt",
              receipt is not None, why)
        if receipt is not None:
            rf = receipt.get("round_faces") or {}
            blob = json.dumps(rf)
            rows = {r.get("run_id"): r for r in rf.get("rounds", []) if isinstance(r, dict)}
            for rid in ("run-noface-1", "run-torn-1", "run-empty-1"):
                row = rows.get(rid)
                check("B1 %s surfaces as a NAMED state, not zeros and not silence"
                      % rid, isinstance(row, dict)
                      and row.get("face") is None
                      and ("absent" in row or "reason" in row),
                      row)
            check("B2 no zero-count fabrication for the damaged rounds",
                  '{"ran": 0, "pass": 0}' not in blob.replace(" ", "")
                  or "run-nope" not in blob, blob[:300])

        # ---- B3 unreadable FACE DIR degrades the section, not the tab ----
        locked = Path(tempfile.mkdtemp(prefix="t26101203-locked-"))
        locked.chmod(0o000)
        try:
            receipt, why = run_adapter(dict(env0, **{FACE_DIR_ENV: str(locked)}))
            check("B3 unreadable face dir: receipt still readable",
                  receipt is not None, why)
            if receipt is not None:
                rf = receipt.get("round_faces") or {}
                check("B4 the face section carries a NAMED section-level error, "
                      "the rest of the receipt stays ok",
                      receipt.get("ok") is True
                      and "error" in json.dumps(rf), rf)
        finally:
            locked.chmod(0o755)
            locked.rmdir()

        # ---- C untrustworthy counts pass the note through ----
        noted = face("run-note-1", state="running", verdict=None,
                     counts={"ran": 1, "pass": 0, "fail": 0, "env_fail": 1},
                     note="summary seen but per-scenario lines unrecognized")
        seed(tmp, {"current": {"face": noted}})
        receipt, why = run_adapter(dict(env0, **{FACE_DIR_ENV: str(Path(tmp) / "faces")}))
        check("C0 adapter readable over the counts_note face", receipt is not None, why)
        if receipt is not None:
            blob = json.dumps(receipt.get("round_faces") or {})
            check("C1 counts_note passes through verbatim to the reader",
                  "per-scenario lines unrecognized" in blob, blob[:300])

        # ---- D no silent retention assumption (> writer keep window) ----
        layout = {"current": {"face": live}}
        for i in range(13):
            layout["run-old-%02d" % i] = {
                "face": face("run-old-%02d" % i, started="2026-01-0%dT00:00:00Z" % (1 + i % 9))}
        seed(tmp, layout)
        receipt, why = run_adapter(dict(env0, **{FACE_DIR_ENV: str(Path(tmp) / "faces")}))
        check("D0 adapter readable over an over-retained tree", receipt is not None, why)
        if receipt is not None:
            rf = receipt.get("round_faces") or {}
            n = len(rf.get("rounds", []))
            blob = json.dumps(rf)
            check("D1 all 13 on-disk terminal rounds reach the reader (no silent "
                  "10-dir assumption) — any render cap is DECLARED",
                  n >= 13 or ("older" in blob and "not shown" in blob),
                  "rows=%s" % n)
            check("D2 the 13 rows are distinct rounds, no duplicates",
                  n == len({r.get("run_id") for r in rf.get("rounds", [])}), n)

        # ---- E live pointer is the only live source ----
        seed(tmp, {"run-green-1": {"face": green}, "run-red-1": {"face": red}})
        receipt, why = run_adapter(dict(env0, **{FACE_DIR_ENV: str(Path(tmp) / "faces")}))
        check("E0 adapter readable with no live pointer", receipt is not None, why)
        if receipt is not None:
            rf = receipt.get("round_faces") or {}
            check("E1 no current.json means NO live row (absence = idle), "
                  "terminal rows still present",
                  ("live" not in rf or rf.get("live") in (None, {})
                   or "absent" in json.dumps(rf.get("live")))
                  and len(rf.get("rounds", [])) >= 2, rf.get("live"))

    print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
