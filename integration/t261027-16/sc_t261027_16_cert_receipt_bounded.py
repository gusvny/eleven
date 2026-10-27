#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t261027_16_cert_receipt_bounded.py — the certification read face stays
BOUNDED on a fat ledger and refuses BY NAME when it cannot (ticket t261027-16).

Incident (host report 261027, measured on this host): the executor panel
spawned certification-adapter.py with maxBuffer 1 MB; the adapter answered
1.29-1.41 MB because per_line.<line>.input.runs carried EVERY run header of
the project (3.6k rows), inflated by the per-case failed_detail evidence
tails t261026-15 added. execFile answered "stdout maxBuffer length exceeded",
stdout was empty, and parseCertReceipt degraded to "certification receipt is
not valid JSON". The tab was unusable. The user-visible contract after the
fix (ticket deliverables a-d):

  a the receipt is BOUNDED to what the face derives (certification range +
    the recent rounds the Rounds section can show), and the receipt NAMES the
    window (runs_window: shown/total/older) - never a silent truncate;
  b failed_detail and every other per-case payload never leave the adapter -
    the runs projection carries header-level counts/verdict/revision only;
  c an oversize receipt is refused BY NAME ("receipt too large: N bytes,
    window M"), and a reader-side spawn-buffer overflow is also refused by
    name - never the generic "not valid JSON" wording;
  d with a real-shape 3.6k-row fat ledger the receipt stays under a declared
    cap and the derived face still answers; a deliberately oversized receipt
    names the reason.

Grey-box L3, the REAL adapter subprocess over an isolated temp projects root
(SANDBAR_PROJECTS_DIR + SANDBAR_RUNS_LEDGER) with a synthetic 3.6k-row fat
ledger, the REAL reader module over a stub execFile (node
--experimental-strip-types), and the REAL adapter main() in-process for the
deliberate-oversize refusal (cap patched at the module seam). Offline seconds,
zero docker/Temporal-server/browser, never touches 3099/7233.

Intent split (no duplication): the pure-helper truth tables (bounded_runs,
count projection words) and the reader unit matrix belong to developer L1
(server/plugins/executor-panel/tests/); THIS entry uniquely owns the
user-perceivable journey: a fat ledger in, a bounded + windowed receipt out,
a named refusal when the face cannot stay honest.

Run directly: python3 integration/t261027-16/sc_t261027_16_cert_receipt_bounded.py
(cwd=repo root). PASS=0, FAIL=1, ENV_FAIL=2.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server" / "engine"))

ADAPTER = ROOT / "server" / "plugins" / "executor-panel" / "src" / "host" / "certification-adapter.py"
READER = ROOT / "server" / "plugins" / "executor-panel" / "src" / "host" / "certification-reader.ts"
RECEIPT_MAX_BYTES = 1_000_000  # the declared cap, same constant the reader spawns with
ROUNDS_CAP = 20                # the Rounds table's render cap (the window derives from it)
FAT = "x" * 4096               # one failed_detail evidence tail
N_ROWS = 3600                  # the host-measured ledger shape
PROJECT = "certbound"
CITED_OLD_RUN = "run-260101-0000"  # the OLDEST header, cited by a cert: must survive the window

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


def engine_python():
    py = ROOT / "server" / "engine" / ".venv" / "bin" / "python"
    return str(py) if py.is_file() else sys.executable


def build_fixture(root):
    """Isolated projects root: one declared line, a landing + a cert citing
    the OLDEST of N fat run headers, and the fat headers ledger itself."""
    proj = root / PROJECT
    (proj / "data" / "develop").mkdir(parents=True)
    (proj / "ledger").mkdir(parents=True)
    import develop_line as dl  # noqa: E402  (engine import for the declared version)
    lines = [{"version": dl.DECLARATION_VERSION,
              "line_id": "main-line", "scope": "core", "owner": "ci",
              "repositories": [{"name": "sandbar", "branch": "main"}]}]
    (proj / "data" / "develop" / "lines.json").write_text(json.dumps(lines), encoding="utf-8")
    delivery = proj / "ledger" / "delivery.jsonl"
    rows = [
        {"id": "landing-1", "kind": "landing", "ticket": "T-1", "line": "main-line",
         "seq": 1, "at": "2026-01-02T00:00:00Z",
         "repos": [{"repo": "sandbar", "revision": "a" * 8}]},
        {"id": "cert-1", "kind": "certification", "ticket": "T-1", "line": "main-line",
         "run": CITED_OLD_RUN, "seq": 2, "at": "2026-01-02T01:00:00Z",
         "repos": [{"repo": "sandbar", "revision": "a" * 8}]},
    ]
    delivery.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    headers = root / "run-headers.jsonl"
    with headers.open("w", encoding="utf-8") as fh:
        for i in range(N_ROWS):
            fh.write(json.dumps({
                "id": CITED_OLD_RUN if i == 0 else "run-%07d" % i,
                "verdict": "green" if i % 3 else "red",
                "started_at": 1700000000000 + i * 1000,
                "source": "lane", "repos": [{"name": "sandbar", "sha": "a" * 8}],
                "cases": [{"name": "case-%d" % j, "outcome": "passed",
                           "failed_detail": FAT} for j in range(3)],
            }) + "\n")
    return headers


def run_adapter(env, project=PROJECT):
    # SANCTIONED-WAIT: runaway-spawn guard on the adapter subprocess, not a
    # wait — the scenario sleeps nowhere; a hit names this face.
    proc = subprocess.run([engine_python(), "-B", str(ADAPTER), project],
                          # SANCTIONED-WAIT: runaway-spawn guard, not a wait.
                          capture_output=True, env=env, cwd=str(ROOT), timeout=120)
    return proc


def main():
    section("ENV gates")
    if not ADAPTER.is_file() or not READER.is_file():
        print("ENV_FAIL: adapter/reader face files missing under server/plugins/executor-panel/")
        return 2
    node = None
    for cand in ("node", "/opt/homebrew/bin/node", "/usr/local/bin/node"):
        try:
            subprocess.run([cand, "--version"], capture_output=True, timeout=15)
            node = cand
            break
        except (OSError, subprocess.TimeoutExpired):
            continue
    if node is None:
        print("ENV_FAIL: node is not resolvable — the reader face cannot be driven")
        return 2

    with tempfile.TemporaryDirectory(prefix="sc-t261027-16-") as td:
        root = Path(td)
        headers = build_fixture(root)
        env = dict(os.environ)
        env["SANDBAR_PROJECTS_DIR"] = str(root)
        env["SANDBAR_RUNS_LEDGER"] = str(headers)
        env.pop("SANDBAR_DELIVERY_LEDGER_DIR", None)
        env.pop("SANDBAR_ROUNDS_FACE_DIR", None)

        section("A/D. Bounded windowed face over the REAL 3.6k-row fat ledger (a, b, d)")
        proc = run_adapter(env)
        if proc.returncode != 0:
            print("  FAIL adapter exited %d: %s" % (proc.returncode, proc.stderr.decode()[:400]))
            return 1
        stdout = proc.stdout.decode("utf-8", "replace")
        try:
            doc = json.loads(stdout)
        except ValueError as e:
            print("  FAIL receipt is not valid JSON: %s" % e)
            return 1
        ok(doc.get("ok") is True, "the fat-ledger receipt is ok:true (the tab is usable)")
        w = doc.get("runs_window")
        ok(isinstance(w, dict), "the receipt NAMES the window (runs_window present, deliverable a)")
        if isinstance(w, dict):
            ok(w.get("total") == N_ROWS, "runs_window.total names the whole ledger (%s)" % w.get("total"))
            ok(isinstance(w.get("older"), int) and w["older"] == w.get("total", 0) - w.get("shown", 0),
               "runs_window.older = total - shown (never a silent truncate)")
            ok(w.get("shown", N_ROWS) <= ROUNDS_CAP + 1,
               "shown stays within the Rounds cap (+cited): %s" % w.get("shown"))
        runs = (doc.get("per_line", {}).get("main-line", {}).get("input", {}) or {}).get("runs", [])
        ok(isinstance(runs, list) and len(runs) <= ROUNDS_CAP + 1,
           "the per-line runs list is bounded (%s rows, not %d)" % (len(runs), N_ROWS))
        ok(len(stdout.encode()) < RECEIPT_MAX_BYTES,
           "the receipt stays under the declared %d-byte cap (%d bytes, deliverable d)"
           % (RECEIPT_MAX_BYTES, len(stdout.encode())))
        ok("failed_detail" not in stdout,
           "failed_detail never leaves the adapter (byte-level, deliverable b)")
        proj_keys = {k for r in runs if isinstance(r, dict) for k in (r.get("cases") or {})} \
            if runs else set()
        ok(proj_keys <= {"ran", "passed", "failed", "env_failed", "absent"},
           "per-run cases carry header-level counts only (keys: %s)" % sorted(proj_keys))
        ok(any(isinstance(r, dict) and r.get("id") == CITED_OLD_RUN for r in runs),
           "the cert-cited run OLDER than the window survives (the range stays derivable)")
        line = doc.get("per_line", {}).get("main-line", {})
        ok(line.get("ok") is True, "the line renders (no refusal, no invented degradation)")

        section("B. Deliberately oversized receipt refuses BY NAME (c)")
        sys.path.insert(0, str(ADAPTER.parent))
        try:
            import certification_adapter as ca  # noqa: E402  (module name differs? fallback below)
        except ImportError:
            import importlib.util as ilu
            spec = ilu.spec_from_file_location("cert_adapter_u", ADAPTER)
            ca = ilu.module_from_spec(spec)
            spec.loader.exec_module(ca)
        old_cap = getattr(ca, "RECEIPT_MAX_BYTES", None)
        if old_cap is None:
            print("  FAIL the declared cap RECEIPT_MAX_BYTES is absent from the adapter "
                  "(pre-implement red = the named TDD signal)")
            return 1
        saved_env = {k: os.environ.get(k) for k in ("SANDBAR_PROJECTS_DIR", "SANDBAR_RUNS_LEDGER")}
        try:
            import io
            from contextlib import redirect_stdout
            os.environ["SANDBAR_PROJECTS_DIR"] = str(root)
            os.environ["SANDBAR_RUNS_LEDGER"] = str(headers)
            ca.RECEIPT_MAX_BYTES = 10  # forces the oversize branch on any real receipt
            buf = io.StringIO()
            with redirect_stdout(buf):
                ca.main(["certification-adapter.py", PROJECT])
            ref = json.loads(buf.getvalue())
        finally:
            ca.RECEIPT_MAX_BYTES = old_cap
            for k, v in saved_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        ok(ref.get("ok") is False, "the oversized receipt refuses (ok:false)")
        reason = str(ref.get("reason", ""))
        ok(reason.startswith("receipt too large"), "the refusal names oversize: %r" % reason[:60])
        ok("bytes" in reason and "window" in reason,
           "the refusal names N bytes AND the window (deliverable c wording)")

        section("C. Reader face: a spawn-buffer overflow is refused by name, never "
                "\"not valid JSON\" (c)")
        node_script = root / "reader_probe.mjs"
        node_script.write_text(
            "import { spawnCertificationRead, parseCertReceipt } from %r;\n"
            "const err = new Error('stdout maxBuffer length exceeded');\n"
            "err.code = 'ENOBUFS';\n"
            "const r = await spawnCertificationRead('certbound', {\n"
            "  execFileFn: (f, a, o, cb) => cb(err, Buffer.from(''), ''),\n"
            "});\n"
            "console.log(JSON.stringify(r));\n"
            "const good = parseCertReceipt(JSON.stringify({ ok: true, project: 'p',\n"
            "  lines: [{ line_id: 'l', scope: '', owner: '' }],\n"
            "  per_line: {}, meta_notes: [], runs_note: '', round_faces: {},\n"
            "  runs_window: { shown: 20, total: 3600, older: 3580, cap: 20 } }));\n"
            "console.log(JSON.stringify(good));\n" % str(READER), encoding="utf-8")
        nproc = subprocess.run(
            [node, "--experimental-strip-types", str(node_script)],
            # SANCTIONED-WAIT: runaway-spawn guard on the reader probe subprocess, not a wait.
            capture_output=True, cwd=str(ROOT), timeout=120,
            env={**env, "NODE_OPTIONS": ""})
        if nproc.returncode != 0:
            print("  FAIL reader probe exited %d: %s" % (nproc.returncode, nproc.stderr.decode()[:400]))
            return 1
        outlines = [l for l in nproc.stdout.decode().splitlines() if l.startswith("{")]
        if len(outlines) < 2:
            print("  FAIL reader probe produced %d JSON lines" % len(outlines))
            return 1
        refuse, good = json.loads(outlines[0]), json.loads(outlines[1])
        ok(refuse.get("ok") is False, "the maxBuffer overflow reads ok:false")
        rr = str(refuse.get("reason", ""))
        ok("receipt too large" in rr, "the reader names oversize: %r" % rr[:80])
        ok("not valid JSON" not in rr, "the reader NEVER degrades to \"not valid JSON\"")
        ok(good.get("ok") is True and isinstance(good.get("runs_window"), dict),
           "a healthy receipt still parses and carries runs_window (regression face)")

    section("Summary")
    print("ran=%d pass=%d fail=%d" % (PASS + FAIL, PASS, FAIL))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001 — an unscripted crash is a FAIL with a name
        print("FAIL unscripted: %s: %s" % (type(e).__name__, e))
        sys.exit(1)
