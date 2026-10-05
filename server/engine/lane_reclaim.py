#!/usr/bin/env python3
"""Orphan lane-worker probe and guarded reclaim (t261005-03, clause C).

Why this exists: the 261005 sweep found 63 processes with ppid=1, 57 of them with a
cwd under `.lane/<ticket>/` — the oldest alive for 15 days, 0.66 GB RSS combined.
Nothing made that count visible, and nothing had a sanctioned way to reclaim the
processes. This module is the home for both, per end state:

- ticket terminal        → the worker self-retires (worker.py watch, existing);
- worker replacement     → the draining handover (worker.py meta state + guard and
                           the console ensure side, this ticket's clause A);
- console restart        → the ppid guard (existing) PLUS this probe: the temporal-tools
                           supervisor runs it once at boot and the count is logged loudly.

Reading face (the acceptance clause reads the ZERO here, not a tool's "ok"):
    python3 server/engine/lane_reclaim.py --json
    → {"orphans": [...], "count": N}   # count must be 0 after terminal/replacement/restart

Reclaim (killing belongs to humans — KI-033 family discipline):
    python3 server/engine/lane_reclaim.py                # dry run: classifies, kills nothing
    python3 server/engine/lane_reclaim.py --apply        # SIGTERM the condemned rows only

Condemn guard (all must hold; anything else is skipped WITH its reason):
  1. ppid == 1                      (adopted — its spawning parent is gone)
  2. cwd under the lane root        (the `.lane/` radius)
  3. cmdline mentions worker.py     (a worker process — an agent/editor running inside
                                    a lane is NOT condemned: false-kill guard)
  4. owned by the current user      (never signals other users' processes)
  5. pid not named by any live worker pidfile/meta in the engine data dir
                                    (the resident worker and healthy lane workers stay
                                    untouched; a meta also protects its pid)

Known false-kill modes and how the guard carries them (review C1):
- pid reuse after a crash: the row is probed NOW (cwd/cmdline read at scan time), so a
  recycled pid is judged by what the process is today, not by what died there — carried.
- a lane worker still serving after its console legitimately exited: ppid==1 alone would
  hit it, but (5) protects any pid a live pidfile/meta names, and the worker's own
  SANDBAR_WATCH_PPID self-retire lands within one watch interval anyway — carried via (5).
- pidfile pointing at a recycled pid: the pidfile then names a pid that is NOT the row's
  worker; the row is judged on its own probe. A stale pidfile can only over-protect
  (skip), never condemn — conservative by design.
- foreground processes whose cwd is a lane (agents, pytest runs): condemned ONLY if
  their cmdline mentions worker.py — carried via (3).
Probe failures are named per pid (a row that cannot be propped is reported as
`unverifiable`, never silently condemned and never silently dropped).
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
from typing import Any, Callable, Dict, List, Optional

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_LANE_ROOT = REPO_ROOT / ".lane"
DEFAULT_DATA_DIR = pathlib.Path(__file__).resolve().parent / "data"


# ---------------------------------------------------------------- probing

def _ps_rows() -> List[Dict[str, Any]]:
    """One `ps` snapshot: {pid, ppid, user, lstart, command}. ps failure = named raise
    (the scan face is useless without it — fail loud, never return a silent [])."""
    out = subprocess.run(
        ["ps", "ax", "-o", "pid=,ppid=,user=,lstart=,command="],
        capture_output=True, text=True, timeout=15)
    if out.returncode != 0:
        raise RuntimeError("ps failed (rc=%s): %s" % (out.returncode, out.stderr.strip()[:200]))
    rows: List[Dict[str, Any]] = []
    for line in out.stdout.splitlines():
        parts = line.split()
        # lstart = 5 tokens (Mon DD HH:MM:SS YYYY) then command; be lenient with shapes.
        if len(parts) < 7:
            continue
        try:
            pid, ppid = int(parts[0]), int(parts[1])
        except ValueError:
            continue  # malformed ps line: skipped, ps headers etc.
        rows.append({"pid": pid, "ppid": ppid, "user": parts[2],
                     "lstart": " ".join(parts[3:8]),
                     "command": " ".join(parts[8:])})
    return rows


def _cwd_of(pid: int) -> Dict[str, Any]:
    """The process cwd. Linux: /proc symlink readlink. macOS/others: `lsof -a -p PID
    -d cwd -Fn`. Returns {"cwd": str} or {"error": str} — a per-pid failure is named,
    never treated as "outside the lane" (that would be a silent over-condemn)."""
    proc = pathlib.Path("/proc/%d/cwd" % pid)
    if proc.exists():
        try:
            return {"cwd": os.readlink(str(proc))}
        except OSError as e:
            return {"error": "readlink /proc/%d/cwd failed (%s)" % (pid, e)}
    try:
        out = subprocess.run(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
                             capture_output=True, text=True, timeout=10)
        for line in out.stdout.splitlines():
            if line.startswith("n") and len(line) > 1:
                return {"cwd": line[1:]}
        if out.returncode != 0:
            return {"error": "lsof failed (rc=%s): %s" % (
                out.returncode, out.stderr.strip()[:160])}
        return {"error": "lsof reported no cwd (the process may have exited)"}
    except FileNotFoundError:
        return {"error": "neither /proc nor lsof on this host \u2014 cwd cannot be proven"}
    except subprocess.TimeoutExpired:
        return {"error": "lsof timed out \u2014 cwd cannot be proven"}


def scan_lane_processes(lane_root: "str | pathlib.Path" = DEFAULT_LANE_ROOT,
                        ps_rows_fn: Callable[[], List[Dict[str, Any]]] = _ps_rows,
                        cwd_fn: Callable[[int], Dict[str, Any]] = _cwd_of,
                        uid: Optional[int] = None) -> List[Dict[str, Any]]:
    """Every process whose cwd is under the lane root (ANY parent) — the examined set
    the reclaim receipt names pid by pid, so a spared process is always visible. The
    orphan count is the ppid==1 subset (scan_orphans)."""
    return _scan_cwd_rows(lane_root, ps_rows_fn, cwd_fn, uid, orphans_only=False)


def scan_orphans(lane_root: "str | pathlib.Path" = DEFAULT_LANE_ROOT,
                 ps_rows_fn: Callable[[], List[Dict[str, Any]]] = _ps_rows,
                 cwd_fn: Callable[[int], Dict[str, Any]] = _cwd_of,
                 uid: Optional[int] = None) -> List[Dict[str, Any]]:
    """All ppid==1 processes whose cwd is under the lane root (unverifiable cwd rows are
    listed with their error, not dropped — the count stays honest). Injectables make the
    scan unit-testable without spawning real processes."""
    return _scan_cwd_rows(lane_root, ps_rows_fn, cwd_fn, uid, orphans_only=True)


def _scan_cwd_rows(lane_root: "str | pathlib.Path",
                   ps_rows_fn: Callable[[], List[Dict[str, Any]]],
                   cwd_fn: Callable[[int], Dict[str, Any]],
                   uid: Optional[int], orphans_only: bool) -> List[Dict[str, Any]]:
    root = os.path.realpath(str(lane_root))
    if uid is None:
        uid = os.getuid()
    out: List[Dict[str, Any]] = []
    for r in ps_rows_fn():
        if orphans_only and r.get("ppid") != 1:
            continue
        try:
            pid = int(r["pid"])
        except (KeyError, TypeError, ValueError):
            continue  # malformed row (unparsable pid): never a candidate
        row: Dict[str, Any] = dict(r)
        cw = cwd_fn(pid)
        row.update(cw)  # "cwd" or "error"
        cwd = row.get("cwd") or ""
        try:
            row["cwd_under_lane"] = bool(cwd) and os.path.realpath(
                cwd).startswith(root + os.sep)
        except OSError as e:
            row["cwd_under_lane"] = False
            row.setdefault("error", "realpath failed (%s)" % e)
        row["own_user"] = (r.get("user") == _current_user_name(uid))
        out.append(row)
    return out


def _current_user_name(uid: int) -> str:
    try:
        import pwd
        return pwd.getpwuid(uid).pw_name
    except Exception:  # noqa: BLE001 \u2014 no name: compare by the uid string (conservative)
        return str(uid)


# ---------------------------------------------------------------- classification

def _protected_pids(data_dir: "str | pathlib.Path") -> "set[int]":
    """Pids named by any worker pidfile / meta sidecar in the engine data dir (parse
    failures are skipped — the protect set over-protects, never under-protects)."""
    protected: set = set()
    d = pathlib.Path(str(data_dir))
    if not d.is_dir():
        return protected
    for pf in list(d.glob("worker*.pid")) + list(d.glob("worker*.meta")):
        try:
            raw = pf.read_text("utf-8")
            data = json.loads(raw) if pf.suffix == ".meta" else raw.strip()
            pid = int((data or {}).get("pid")) if isinstance(data, dict) else int(data)
            if pid > 0:
                protected.add(pid)
        except (ValueError, OSError, TypeError, AttributeError):
            continue  # malformed pidfile/meta: cannot protect a pid we cannot read
    return protected


def is_provable_orphan(row: Dict[str, Any]) -> bool:
    """The COUNT face (t261005-03 arbitration gen2): a row counts as an orphan only
    when its cwd was PROVEN under the lane root (and it is a ppid=1 row, which the
    scan already guarantees). A row whose probe FAILED is named in the receipt but
    NEVER in the count — on any real host some ppid=1 daemons cannot be probed, so
    counting unprovable rows would make the acceptance zero reading undeliverable.
    The other direction is guarded too: a proven orphan is never demoted to
    unprovable (cwd_under_lane true => counted, full stop)."""
    return bool(row.get("cwd_under_lane")) and not row.get("error")


def classify_orphans(rows: List[Dict[str, Any]],
                     lane_root: "str | pathlib.Path" = DEFAULT_LANE_ROOT,
                     data_dir: "str | pathlib.Path" = DEFAULT_DATA_DIR,
                     current_user: Optional[str] = None,
                     protected_pids: "Optional[set[int]]" = None) -> List[Dict[str, Any]]:
    """Pure classifier: each row gets verdict 'condemn' | 'skip' + reason (t261005-03
    guard set; the false-kill tradeoffs are documented in the module header)."""
    if current_user is None:
        current_user = _current_user_name(os.getuid())
    if protected_pids is None:
        protected_pids = _protected_pids(data_dir)
    out: List[Dict[str, Any]] = []
    for r in rows:
        row = dict(r)
        reasons: List[str] = []
        if r.get("error"):
            reasons.append("probe failed, cannot be proven: %s" % r["error"])
        elif not r.get("cwd_under_lane"):
            reasons.append("cwd outside the lane radius (%s)" % (r.get("cwd") or "?"))
        if "worker.py" not in str(r.get("command") or ""):
            reasons.append("cmdline is not worker.py (a non-worker process inside a lane is never condemned)")
        if r.get("user") != current_user:
            reasons.append("not the current user (%s != %s) \u2014 never signals another user's process"
                           % (r.get("user"), current_user))
        if r.get("ppid") != 1:
            reasons.append("ppid != 1 (the spawning parent is alive) - not an orphan")
        if int(r.get("pid") or 0) in (protected_pids or set()):
            reasons.append("pid is named by a live pidfile/meta (a live worker is never touched)")
        row["verdict"] = "skip" if reasons else "condemn"
        row["reason"] = "; ".join(reasons) if reasons else "all five guards passed"
        out.append(row)
    return out


def reclaim(classified: List[Dict[str, Any]], apply: bool = False,
            kill_fn: Callable[[int, int], None] = os.kill) -> List[Dict[str, Any]]:
    """SIGTERM the condemned rows (graceful — never SIGKILL from this tool; the worker's
    own graceful path finishes in-flight activities). Dry run by default: killing
    belongs to humans. Every action/reason is returned for the receipt."""
    results: List[Dict[str, Any]] = []
    for r in classified:
        if r.get("verdict") != "condemn":
            results.append({"pid": r.get("pid"), "action": "skipped",
                            "reason": r.get("reason")})
            continue
        if not apply:
            results.append({"pid": r.get("pid"), "action": "would_kill(dry-run)",
                            "reason": "condemned (--apply to execute)"})
            continue
        try:
            kill_fn(int(r["pid"]), 15)
            results.append({"pid": r.get("pid"), "action": "sigterm_sent",
                            "reason": "graceful stop (the worker finishes its own in-flight activities)"})
        except ProcessLookupError:
            results.append({"pid": r.get("pid"), "action": "already_gone",
                            "reason": "exited before the signal"})
        except OSError as e:
            results.append({"pid": r.get("pid"), "action": "error",
                            "reason": "%s: %s" % (type(e).__name__, e)})
    return results


# ---------------------------------------------------------------- CLI

def _print_json(payload: Dict[str, Any]) -> None:
    """Single stdout exit for JSON receipts (the statement-level guard, t261004-26
    family): a lone surrogate in a dynamic payload must never take the whole receipt
    down — unencodable characters become visible backslash escapes, everything else is
    byte-identical (same shape as client._emit)."""
    print(json.dumps(payload, ensure_ascii=False)
          .encode("utf-8", "backslashreplace").decode("utf-8"))


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="orphan lane-worker probe / guarded reclaim")
    p.add_argument("--lane-root", default=str(DEFAULT_LANE_ROOT))
    p.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    p.add_argument("--json", action="store_true", help="JSON receipt (the boot probe face)")
    p.add_argument("--apply", action="store_true",
                   help="SIGTERM condemned pids (default dry-run \u2014 killing belongs to humans)")
    args = p.parse_args(argv)
    try:
        rows = scan_orphans(args.lane_root)
    except Exception as e:  # noqa: BLE001 — a scan failure must be loud (never a silent zero)
        msg = {"error": "scan failed (%s: %s)" % (type(e).__name__, e)}
        if args.json:
            _print_json(msg)
        else:
            print("lane_reclaim: %s" % msg["error"], file=sys.stderr)
        return 2
    classified = classify_orphans(rows, args.lane_root, args.data_dir)
    orphans = [r for r in classified if is_provable_orphan(r)]
    unprovable = [r for r in classified
                  if r.get("error") and not r.get("cwd_under_lane")]
    actions = reclaim(classified, apply=args.apply)
    receipt = {
        "lane_root": str(args.lane_root),
        "orphans": [{k: r.get(k) for k in
                     ("pid", "ppid", "user", "lstart", "cwd", "error", "command",
                      "verdict", "reason")} for r in orphans],
        "count": len(orphans),
        "unprovable": [{k: r.get(k) for k in
                        ("pid", "ppid", "user", "command", "error", "verdict",
                         "reason")} for r in unprovable],
        "unprovable_count": len(unprovable),
        "condemned": sum(1 for r in classified if r.get("verdict") == "condemn"),
        "actions": actions,
        "mode": "apply" if args.apply else "dry-run",
    }
    if args.json:
        _print_json(receipt)
    else:
        print("lane_reclaim: %d processes with ppid=1 and cwd under %s (condemn %d, mode=%s)"
              % (receipt["count"], args.lane_root, receipt["condemned"],
                 receipt["mode"]))
        for r in orphans:
            print("  pid=%s cwd=%s verdict=%s (%s)"
                  % (r.get("pid"), r.get("cwd") or r.get("error"),
                     r.get("verdict"), r.get("reason")))
        for r in receipt["unprovable"]:
            print("  unprovable pid=%s (%s) - %s"
                  % (r.get("pid"), r.get("error"), r.get("reason")))
        for a in actions:
            if a["action"] != "skipped":
                print("  -> pid=%s %s (%s)" % (a["pid"], a["action"], a["reason"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
