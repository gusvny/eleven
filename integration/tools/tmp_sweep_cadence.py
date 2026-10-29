#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tmp_sweep_cadence — the daily tick body for the temp-fixture sweep (t261029-38).

The sweep tool (`sweep_tmp_fixtures.py`) answers "what can be deleted". This tool answers
"should it run now, on which root, and what does the receipt say". It is
**schedule-agnostic**: the daily face is the registered scenario
`integration/sc_t261029_38_tmp_sweep_tick.py`, which the inspection suite runs every day at
07:30 (Asia/Shanghai); a human or a cron line can call `tick` too. Nothing here installs an
OS job.

Round rule (one discriminator, source-locked by the battery):
    SANDBAR_INTEG_LEDGER_SOURCE == "inspection"  -> the tick may run
    "lane:<ticket>" / absent                     -> inert (named line, exit 0, no reads)
Plus: `INTEG_RUN_DEPTH` >= 2 and a non-empty `SANDBAR_SCENARIO_ONLY` are inert (a nested
round, or a narrowed/baseline round). `--manual` is the human escape path and stamps
`round_shape=manual`.

Exit codes (one table; a scenario turns any non-zero into a failed case):
    0  tick ran (report or apply, including a bounded partial), or an inert/skip path
    2  usage refusal
    4  wall-clock kill or TERM during the sweep (terminal receipt written)
    5  state-dir / receipt write failure
    6  degraded holder scan (candidates kept because the probe could not be trusted)
    7  previous tick stale (past 30 h); the receipt is still written and the sweep still runs
    8  unusable config.json, or state that cannot be shown safe
    9  the sweep's JSON output was unparsable / incomplete / inconsistent

State dir default `~/.sandbar/tmp-sweep` (or `$SANDBAR_TMP_SWEEP_DIR`, or `--state-dir`):
    config.json      {"mode": "report"|"apply"|"disabled", "max_age_h": 6.0, ...}
    last-run.json    {"last_success_epoch": ..., "last_status": ..., "runner_budget_s": ...}
    lock             single-flight flock
    receipts/        receipt-<UTC stamp>.json (newest 30 kept)
    latest.json      newest receipt (for the delta of the next run)
    latest.md        newest receipt in markdown (the reader face)
    history.jsonl    one line per tick (rotated at 400 lines)

It is a plain ops log: no ledger semantics (docs/reference/ledger-record-models-v1.md §D
keeps findings on the inspection period ticket).

Usage (cwd = repo root):
    python3 integration/tools/tmp_sweep_cadence.py status
    python3 integration/tools/tmp_sweep_cadence.py report
    python3 integration/tools/tmp_sweep_cadence.py enable --mode report
    python3 integration/tools/tmp_sweep_cadence.py enable --mode apply
    python3 integration/tools/tmp_sweep_cadence.py tick                  # the scheduled face
    python3 integration/tools/tmp_sweep_cadence.py tick --manual --root "$TMPDIR" \
        --state-dir out/tmp-sweep-rehearsal                              # rehearsal
"""
from __future__ import annotations

import argparse
import errno
import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
SWEEP = HERE / "sweep_tmp_fixtures.py"

#: Age gate used in production. 6 h equals the sweep default and the engine alarm line
#: (`inspection.yaml` tmp_fixture_max_age_h: 6), and it leaves about 2x margin over the
#: worst observed suite round (5916.4 s = 98.6 min, 20261008; KI-078 records 3 h).
DEFAULT_MAX_AGE_H = 6.0
#: A tick runs at most once per window. 20 h is below the daily cadence so a late tick
#: still runs; a manual tick inside the window is a named skip unless --force.
MIN_INTERVAL_H = 20.0
#: Stale red: a daily cadence plus 6 h grace. Baseline (no previous receipt) never reds.
STALE_AFTER_H = 30.0
#: Bounded batch: entries per tick (about 5x the measured 75,902 entries/day inflow) and
#: a wall-clock budget clamped to 10% of the runner's budget (570 s when the inspection
#: round injects SANDBAR_INTEG_RUN_BUDGET_SEC=5700).
TICK_LIMIT_ENTRIES = 400000
TICK_BUDGET_CAP_S = 600
TICK_BUDGET_MIN_S = 60
TICK_BUDGET_FLOOR_S = 60
#: Size-estimate cost inside a suite round: 2 samples per prefix, 1 s each.
TICK_SAMPLE = 2
TICK_SAMPLE_BUDGET_S = 1.0
#: Retention: a receipt history must not become the next unbounded growth.
RECEIPTS_KEEP = 30
HISTORY_MAX_LINES = 400
#: Extra wall clock on top of the sweep budget before the runner kills the child.
SWEEP_MARGIN_S = 120
#: Environment keys this tool reads (all injected by the engine, never by a ticket).
LEDGER_SOURCE_ENV = "SANDBAR_INTEG_LEDGER_SOURCE"
INSPECTION_SHAPE = "inspection"
DEPTH_ENV = "INTEG_RUN_DEPTH"
NARROW_ENV = "SANDBAR_SCENARIO_ONLY"
RUNNER_BUDGET_ENV = "SANDBAR_INTEG_RUN_BUDGET_SEC"

EXIT_OK, EXIT_USAGE, EXIT_TERM, EXIT_WRITE = 0, 2, 4, 5
EXIT_DEGRADED, EXIT_STALE, EXIT_CONFIG, EXIT_SWEEP_OUTPUT = 6, 7, 8, 9


# ---------------------------------------------------------------- pure predicates

def round_shape(env=None):
    """Which round is this? Pure, one key (`agent_activities.py` injects it).

    `inspection` = the daily inspection suite; `lane` = a per-ticket gate round;
    `manual` = anything else (a human ran the suite, or nothing was injected).
    """
    env = os.environ if env is None else env
    src = str(env.get(LEDGER_SOURCE_ENV) or "").strip()
    if src == INSPECTION_SHAPE:
        return "inspection"
    if src.startswith("lane:"):
        return "lane"
    return "manual"


def round_depth(env=None):
    """Integrator nesting depth (1 = the top round, 2+ = a nested round)."""
    env = os.environ if env is None else env
    try:
        return int(str(env.get(DEPTH_ENV) or "1").strip() or "1")
    except (TypeError, ValueError):
        return 1


def inert_reason(env=None, manual=False):
    """Why this round must not tick ("" = it may). Named, never silent."""
    env = os.environ if env is None else env
    if manual:
        return ""
    shape = round_shape(env)
    if shape != INSPECTION_SHAPE:
        return "shape=%s (only the daily inspection round ticks)" % shape
    if round_depth(env) >= 2:
        return "depth=%d (nested round)" % round_depth(env)
    if str(env.get(NARROW_ENV) or "").strip():
        return "narrowed (SANDBAR_SCENARIO_ONLY=%s)" % env.get(NARROW_ENV)
    return ""


def clamp_budget(env_budget, state_budget=None):
    """Sweep budget in seconds -> (seconds, source).

    The inspection round injects `SANDBAR_INTEG_RUN_BUDGET_SEC` (5700 today: the executor
    timeout 6000 minus the chain margin, clamped under the runner budget 6600). Ten percent
    of it is the tick's share, so a tick can never eat the round. A manual tick has no
    injected value, so it reuses the last observed runner budget from the state dir; with
    neither, it falls back to the 60 s floor (and the receipt says `budget_source=floor`,
    where ~39k entries per manual apply is below the daily inflow — see the `deficit` note).
    """
    raw = 0.0
    source = "floor"
    for value, name in ((env_budget, "env"), (state_budget, "state")):
        try:
            v = float(value or 0)
        except (TypeError, ValueError):
            v = 0.0
        if v > 0:
            raw, source = v, name
            break
    if raw <= 0:
        return TICK_BUDGET_FLOOR_S, "floor"
    return int(max(TICK_BUDGET_MIN_S, min(TICK_BUDGET_CAP_S, raw * 0.1))), source


def due(last_success_epoch, now, min_interval_h=MIN_INTERVAL_H):
    """Is a tick due? -> (bool, reason). A missing/unusable clock is due (fail-open here
    is safe: the age gate and the holder guards are what protect running suites)."""
    if not isinstance(last_success_epoch, (int, float)) or last_success_epoch <= 0:
        return True, "no previous success"
    gap_h = max(0.0, (float(now) - float(last_success_epoch)) / 3600.0)
    if gap_h >= float(min_interval_h):
        return True, "last success %.1fh ago" % gap_h
    return False, "last success %.1fh ago (< %.1fh window)" % (gap_h, float(min_interval_h))


def staleness(last_success_epoch, now, stale_after_h=STALE_AFTER_H):
    """-> (is_stale, age_h). No previous success = baseline (never stale)."""
    if not isinstance(last_success_epoch, (int, float)) or last_success_epoch <= 0:
        return False, None
    age_h = max(0.0, (float(now) - float(last_success_epoch)) / 3600.0)
    return age_h > float(stale_after_h), round(age_h, 2)


def build_sweep_argv(python, sweep_path, root, apply_, max_age_h, limit, budget_s,
                     sample, sample_budget_s):
    """The apply/report argv. Pure, so the battery can pin its shape.

    Invariants: no `--kill-carriers` (a sweep never kills processes), no `--prefix` (the
    whitelist is the gate), `--apply` only in apply mode, and the age gate always explicit.
    """
    argv = [python, str(sweep_path), "--root", str(root),
            "--max-age-h", "%.1f" % float(max_age_h), "--json",
            "--sample", str(int(sample)),
            "--sample-budget-s", "%.1f" % float(sample_budget_s)]
    if apply_:
        argv += ["--apply", "--limit", str(int(limit)), "--budget-s", "%.0f" % float(budget_s)]
    return argv


def build_count_argv(python, sweep_path, root, prefixes, sample=2, sample_budget_s=1.0):
    """The foreign-family count argv: `--count-only`, never `--apply`."""
    argv = [python, str(sweep_path), "--root", str(root), "--json", "--count-only",
            "--sample", str(int(sample)), "--sample-budget-s", "%.1f" % float(sample_budget_s)]
    for p in prefixes:
        argv += ["--prefix", str(p)]
    return argv


CONFIG_MODES = ("report", "apply", "disabled")
CONFIG_NUMERIC = ("max_age_h", "min_interval_h", "sample_budget_s")


def parse_config(text):
    """Config text -> (cfg, error). `error` is a named refusal ("" = usable).

    No config file at all is not an error: the caller treats it as `report` mode, so the
    cadence runs from day one and deletes nothing until a person enables apply.
    """
    raw = (text or "").strip()
    if not raw:
        return None, "config_malformed: empty file"
    try:
        data = json.loads(raw)
    except ValueError as e:
        return None, "config_malformed: %s" % e
    if not isinstance(data, dict):
        return None, "config_type_error: top level is %s" % type(data).__name__
    mode = data.get("mode", "report")
    if not isinstance(mode, str):
        return None, "config_type_error: mode"
    if mode not in CONFIG_MODES:
        return None, "config_unknown_mode: %s" % mode
    cfg = {"mode": mode, "max_age_h": DEFAULT_MAX_AGE_H, "min_interval_h": MIN_INTERVAL_H,
           "sample": TICK_SAMPLE, "sample_budget_s": TICK_SAMPLE_BUDGET_S,
           "root": data.get("root")}
    for key in CONFIG_NUMERIC + ("sample",):
        if key not in data:
            continue
        value = data[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None, "config_type_error: %s" % key
        cfg[key] = value
    if cfg["sample"] < 0:
        return None, "config_type_error: sample"
    if cfg["max_age_h"] < 1.0:      # the sweep's own --apply floor
        return None, "config_age_below_floor: %s" % cfg["max_age_h"]
    if cfg["max_age_h"] <= 0:
        return None, "config_age_below_floor: %s" % cfg["max_age_h"]
    return cfg, ""


def parse_last_run(text):
    """`last-run.json` text -> (data, error). Malformed state is named, not fatal."""
    raw = (text or "").strip()
    if not raw:
        return {}, "state_unreadable: empty file"
    try:
        data = json.loads(raw)
    except ValueError as e:
        return {}, "state_unreadable: %s" % e
    if not isinstance(data, dict):
        return {}, "state_type_error: top level is %s" % type(data).__name__
    for key in ("last_success_epoch", "runner_budget_s"):
        if key in data and data[key] is not None:
            if isinstance(data[key], bool) or not isinstance(data[key], (int, float)):
                return {}, "state_type_error: %s" % key
    return data, ""


def parse_sweep_output(text):
    """The sweep's `--json` text -> (payload, error). Three named refusals (exit 9)."""
    raw = (text or "").strip()
    if not raw:
        return None, "sweep_output_unparsable: empty output"
    try:
        data = json.loads(raw)
    except ValueError as e:
        return None, "sweep_output_unparsable: %s" % e
    if not isinstance(data, dict):
        return None, "sweep_output_unparsable: top level is %s" % type(data).__name__
    for key in ("swept", "candidates_total", "entries"):
        if key not in data:
            return None, "sweep_output_incomplete: missing %s" % key
    swept = data.get("swept")
    total = data.get("candidates_total")
    if isinstance(swept, (int, float)) and isinstance(total, (int, float)) and swept > total:
        return None, "sweep_output_inconsistent: swept %s > candidates %s" % (swept, total)
    return data, ""


# ---------------------------------------------------------------- filesystem faces

def utc_now(epoch=None):
    return datetime.fromtimestamp(time.time() if epoch is None else epoch,
                                  tz=timezone.utc)


def utc_stamp(epoch=None):
    return utc_now(epoch).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc_file_stamp(epoch=None):
    return utc_now(epoch).strftime("%Y%m%dT%H%M%SZ")


def state_dir(args):
    """State dir: --state-dir > $SANDBAR_TMP_SWEEP_DIR > ~/.sandbar/tmp-sweep (absolute)."""
    raw = args.state_dir or os.environ.get("SANDBAR_TMP_SWEEP_DIR") or ""
    base = Path(raw).expanduser() if raw else Path.home() / ".sandbar" / "tmp-sweep"
    return str(base.resolve())


def write_atomic(path, text):
    """Write a file atomically; a failure is raised to the caller (never swallowed)."""
    tmp = "%s.tmp.%d" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def read_text(path):
    """File text, or None when the path is absent/unusable.

    A path that is not a directory (or not readable) is treated as absent here; the write
    face names it later as `state_write_failed` (exit 5), so nothing is silent.
    """
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def tool_rev():
    """Repo head and the sweep tool blob id; 'unknown' when git is unavailable."""
    out = {"head": None, "sweep_sha": None}
    for key, argv in (("head", ["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"]),
                      ("sweep_sha", ["git", "-C", str(REPO), "hash-object", str(SWEEP)])):
        try:
            r = subprocess.run(argv, capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                out[key] = r.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return out


def rotate_history(path, keep=HISTORY_MAX_LINES):
    """Keep the newest `keep` lines of history.jsonl (a receipt log must stay bounded)."""
    text = read_text(path)
    if not text:
        return
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) <= keep:
        return
    write_atomic(path, "\n".join(lines[-keep:]) + "\n")


def prune_receipts(receipts_dir, keep=RECEIPTS_KEEP):
    try:
        files = sorted(Path(receipts_dir).glob("receipt-*.json"))
    except OSError:
        return
    for old in files[:-keep] if keep else []:
        try:
            old.unlink()
        except OSError:
            pass


def newest_receipt(receipts_dir):
    try:
        files = sorted(Path(receipts_dir).glob("receipt-*.json"))
    except OSError:
        return None
    return str(files[-1]) if files else None


# ---------------------------------------------------------------- the tick

class _Terminated(Exception):
    pass


def _on_term(signum, frame):
    raise _Terminated("signal %d" % signum)


def run_child(argv, timeout_s):
    """Run the sweep as a child in its own group; TERM then KILL on timeout.

    Every path returns: (returncode|None, stdout, stderr, timed_out). No orphan survives.
    """
    try:
        proc = subprocess.Popen(argv, cwd=str(REPO), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, start_new_session=True)
    except (OSError, subprocess.SubprocessError) as e:
        return None, "", "%s: %s" % (type(e).__name__, e), False
    try:
        out, err = proc.communicate(timeout=timeout_s)
        return proc.returncode, out, err, False
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except OSError:
            pass
        try:
            out, err = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except OSError:
                pass
            try:
                out, err = proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                out, err = "", "child did not exit after SIGKILL"
        return proc.returncode, out, err, True


def _load_previous(state):
    """Previous receipt (for the delta): latest.json, else the newest dated receipt."""
    text = read_text(os.path.join(state, "latest.json"))
    path = os.path.join(state, "latest.json")
    if text:
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data, path
            return {"_unreadable": True, "receipt_path": path}, path
        except ValueError:
            return {"_unreadable": True, "receipt_path": path}, path
    newest = newest_receipt(os.path.join(state, "receipts"))
    if newest:
        try:
            return json.loads(read_text(newest) or "{}"), newest
        except ValueError:
            return {"_unreadable": True, "receipt_path": newest}, newest
    return None, None


def _write_receipt(state, receipt):
    """Write receipts/receipt-<stamp>.json, latest.json, latest.md, history.jsonl."""
    receipts_dir = os.path.join(state, "receipts")
    os.makedirs(receipts_dir, exist_ok=True)
    stamp = utc_file_stamp(receipt.get("ended_utc_epoch"))
    path = os.path.join(receipts_dir, "receipt-%s.json" % stamp)
    receipt["receipt_path"] = path
    receipt["header"] = header_line(receipt)
    import tmp_leak_receipt as rr          # local import: keeps the pure faces testable
    write_atomic(path, rr.dumps(receipt))
    write_atomic(os.path.join(state, "latest.json"), rr.dumps(receipt))
    write_atomic(os.path.join(state, "latest.md"), rr.render_markdown(receipt))
    line = json.dumps({"ended_utc": receipt.get("ended_utc"), "status": receipt.get("status"),
                       "mode": receipt.get("mode"), "shape": receipt.get("round_shape"),
                       "swept": (receipt.get("counts") or {}).get("swept"),
                       "backlog": (receipt.get("counts") or {}).get("candidates_total"),
                       "delta": ((receipt.get("delta") or {}).get("whitelisted") or {}).get("delta"),
                       "receipt": path}, ensure_ascii=False)
    with open(os.path.join(state, "history.jsonl"), "a", encoding="utf-8") as f:
        f.write(line + "\n")
    rotate_history(os.path.join(state, "history.jsonl"))
    prune_receipts(receipts_dir)
    return path


def header_line(receipt):
    """The one line a reader scans (owned by the receipt module: root, backlog, delta,
    top leaker, cross-repo family)."""
    import tmp_leak_receipt as rr
    return rr.header_line(receipt)


def cmd_tick(args):
    state = state_dir(args)
    manual = bool(args.manual)
    shape = "manual" if manual else round_shape()
    depth = round_depth()
    # Inert paths come first: no config read, no state read, no host-temp-root read.
    why = inert_reason(manual=manual)
    if why:
        print("TMP-SWEEP TICK inert reason=%s" % why)
        print("TMP-SWEEP INERT: no host-temp-root read, no state write, no delete")
        return EXIT_OK

    cfg_text = read_text(os.path.join(state, "config.json"))
    if cfg_text is None:
        cfg = {"mode": "report", "max_age_h": DEFAULT_MAX_AGE_H,
               "min_interval_h": MIN_INTERVAL_H, "sample": TICK_SAMPLE,
               "sample_budget_s": TICK_SAMPLE_BUDGET_S, "root": None}
        cfg_source = "default"
    else:
        cfg, err = parse_config(cfg_text)
        if err:
            print("TMP-SWEEP CONFIG REFUSED: %s (state dir %s)" % (err, state))
            print("TMP-SWEEP TICK failed reason=%s" % err)
            return EXIT_CONFIG
        cfg_source = "config"
    # An explicit --mode is the caller's own statement and beats the stored config: the daily
    # scenario runs `--mode report` so a host that enabled apply can never make the scheduled
    # receipt face delete, and a rehearsal can always force the read-only mode.
    if args.mode and args.mode != cfg["mode"]:
        cfg["mode"] = args.mode
        cfg_source += "+cli"
    if cfg["mode"] == "disabled":
        print("TMP-SWEEP TICK inert reason=disabled (config %s)"
              % os.path.join(state, "config.json"))
        return EXIT_OK

    root = args.root or cfg.get("root") or os.environ.get("TMPDIR") or "/tmp"
    root = os.path.abspath(os.path.expanduser(str(root)))
    if not os.path.isdir(root):
        print("TMP-SWEEP CONFIG REFUSED: config_root_invalid: %s" % root)
        return EXIT_CONFIG
    root_real = os.path.realpath(root)

    now = float(args.now) if args.now else time.time()
    last_text = read_text(os.path.join(state, "last-run.json"))
    if last_text is None:
        last, state_err = {}, ""          # fresh state dir: baseline, not an error
    else:
        last, state_err = parse_last_run(last_text)
    if state_err:
        print("TMP-SWEEP STATE %s (due gate falls back to the newest receipt)" % state_err)
        newest = newest_receipt(os.path.join(state, "receipts"))
        if newest:
            try:
                prev = json.loads(read_text(newest) or "{}")
                if isinstance(prev, dict) and isinstance(prev.get("ended_utc_epoch"), (int, float)):
                    last = {"last_success_epoch": prev["ended_utc_epoch"],
                            "due_source": "receipt_fallback"}
            except ValueError:
                pass
    last_success = (last or {}).get("last_success_epoch")
    is_due, due_reason = due(last_success, now, cfg.get("min_interval_h") or MIN_INTERVAL_H)
    if not is_due and not args.force:
        print("TMP-SWEEP TICK skip reason=due-gate: %s" % due_reason)
        return EXIT_OK

    try:
        os.makedirs(os.path.join(state, "receipts"), exist_ok=True)
        lock_path = os.path.join(state, "lock")
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    except OSError as e:
        # KI-389 shape: a tool that cannot write its root must say so and exit non-zero.
        print("TMP-SWEEP WRITE FAILED: state_write_failed: %s: %s: %s"
              % (state, type(e).__name__, e))
        print("TMP-SWEEP TICK failed reason=state_write_failed")
        return EXIT_WRITE
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            if e.errno in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
                print("TMP-SWEEP TICK skip reason=lock-held (another tick is running)")
                return EXIT_OK
            raise
        return _tick_locked(args, state=state, cfg=cfg, cfg_source=cfg_source,
                            root=root, root_real=root_real, shape=shape, depth=depth,
                            now=now, last=last or {}, state_err=state_err)
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)


def _tick_locked(args, *, state, cfg, cfg_source, root, root_real, shape, depth, now,
                 last, state_err):
    import tmp_leak_receipt as rr
    import sweep_tmp_fixtures as sw

    budget_s, budget_source = clamp_budget(os.environ.get(RUNNER_BUDGET_ENV),
                                           (last or {}).get("runner_budget_s"))
    started = time.time()
    started_utc = utc_stamp(started)
    previous, previous_path = _load_previous(state)
    stale, stale_age = staleness((last or {}).get("last_success_epoch"), started)
    notes = []
    if state_err:
        notes.append("state: %s" % state_err)
    if cfg_source:
        notes.append("config source: %s" % cfg_source)
    if stale:
        notes.append("stale: last success %s was %.1fh ago (> %.0fh bound)"
                     % (utc_stamp((last or {}).get("last_success_epoch")), stale_age,
                        STALE_AFTER_H))

    apply_mode = cfg["mode"] == "apply"
    argv = build_sweep_argv(sys.executable, SWEEP, root, apply_mode, cfg["max_age_h"],
                            TICK_LIMIT_ENTRIES, budget_s, cfg["sample"],
                            cfg["sample_budget_s"])
    status = "ok"
    exit_code = EXIT_OK
    sweep_payload = None
    duration = 0.0
    try:
        rc, out, err, timed_out = run_child(argv, budget_s + SWEEP_MARGIN_S)
        duration = time.time() - started
        if timed_out:
            status, exit_code = "terminated", EXIT_TERM
            notes.append("wall-clock: sweep killed after %.0fs (budget %.0fs + %ds margin)"
                         % (duration, budget_s, SWEEP_MARGIN_S))
            sweep_payload = _salvage_json(out)
        else:
            sweep_payload, output_err = parse_sweep_output(out)
            if output_err:
                status, exit_code = "failed", EXIT_SWEEP_OUTPUT
                notes.append(output_err)
                sweep_payload = None
            elif rc == sw.EXIT_DEGRADED:
                status, exit_code = "degraded", EXIT_DEGRADED
                notes.append("degraded holder scan: %s" % (sweep_payload.get("degraded_reason")
                                                           or "probe unavailable"))
            elif rc not in (0, None):
                status, exit_code = "failed", EXIT_SWEEP_OUTPUT
                notes.append("sweep exit=%s: %s" % (rc, (err or "").strip()[-300:]))
            elif timed_out:
                pass
    except _Terminated as e:
        status, exit_code = "terminated", EXIT_TERM
        notes.append("terminated by %s" % e)
        sweep_payload = None
    if sweep_payload is None and status in ("terminated", "failed"):
        sweep_payload = {"entries": 0, "untouched": 0, "swept": 0, "candidates_total": 0,
                         "failed": 0, "summary": "no usable sweep output"}

    foreign_payload = None
    if status in ("ok", "degraded"):
        count_argv = build_count_argv(sys.executable, SWEEP, root,
                                      sorted(rr.FOREIGN_MINT),
                                      cfg["sample"], cfg["sample_budget_s"])
        try:
            _crc, cout, _cerr, ctimed = run_child(count_argv, max(60, int(budget_s)))
            foreign_payload, ferr = parse_sweep_output(cout)
            if ctimed or ferr:
                notes.append("foreign count unavailable: %s"
                             % ("timeout" if ctimed else ferr))
                foreign_payload = None
        except _Terminated:
            notes.append("foreign count interrupted")

    if stale and status == "ok":
        status, exit_code = "stale_red", EXIT_STALE

    owners = rr.load_owners(str(REPO), sw.TMP_FIXTURE_PREFIXES)
    ctx = {
        "mode": cfg["mode"], "round_shape": shape, "round_depth": depth,
        "root": root_real, "state_dir": state,
        "started_utc": started_utc, "ended_utc": utc_stamp(), "duration_s": duration,
        "started_utc_epoch": round(started, 3), "ended_utc_epoch": round(time.time(), 3),
        "max_age_h": cfg["max_age_h"], "limit": TICK_LIMIT_ENTRIES if apply_mode else None,
        "budget_s": budget_s, "budget_source": budget_source,
        "flags": {"apply": apply_mode, "sample": cfg["sample"],
                  "sample_budget_s": cfg["sample_budget_s"], "kill_carriers": False,
                  "force": bool(args.force), "manual": bool(args.manual)},
        "tool_rev": tool_rev(), "status": status,
        "degraded": status == "degraded", "degraded_reason": None, "notes": notes,
    }
    receipt = rr.build_receipt(sweep_json=sweep_payload, foreign_json=foreign_payload,
                               previous=previous, owners=owners, ctx=ctx)
    notes.append("budget: %ss (%s); limit=%s; age=%sh"
                 % (budget_s, budget_source, TICK_LIMIT_ENTRIES if apply_mode else "-",
                    cfg["max_age_h"]))
    if not apply_mode:
        notes.append("report mode: nothing deleted this tick (enable --mode apply to reclaim)")
    receipt["notes"] = notes
    try:
        path = _write_receipt(state, receipt)
    except OSError as e:
        print("TMP-SWEEP WRITE FAILED: state_write_failed: %s: %s" % (state, e))
        return EXIT_WRITE
    # K1: a stale_red / degraded / partial tick is still a successful tick for the clock,
    # because the sweep ran and the receipt exists. terminated / failed are not.
    clock_statuses = ("ok", "partial", "degraded", "stale_red")
    new_last = {"last_status": status, "last_receipt": path,
                "last_run_epoch": receipt["ended_utc_epoch"],
                "runner_budget_s": float(os.environ.get(RUNNER_BUDGET_ENV) or 0) or
                                   (last or {}).get("runner_budget_s"),
                "round_shape": shape}
    if status in clock_statuses:
        new_last["last_success_epoch"] = receipt["ended_utc_epoch"]
    else:
        new_last["last_success_epoch"] = (last or {}).get("last_success_epoch")
    try:
        write_atomic(os.path.join(state, "last-run.json"),
                     json.dumps(new_last, ensure_ascii=False, indent=2) + "\n")
    except OSError as e:
        print("TMP-SWEEP WRITE FAILED: state_write_failed (last-run): %s: %s" % (state, e))
        return EXIT_WRITE
    print(receipt.get("header") or header_line(receipt))
    if stale:
        print("TMP-SWEEP STALE: last success %s age %.1fh receipt=%s — run "
              "`python3 integration/tools/tmp_sweep_cadence.py status`"
              % (utc_stamp((last or {}).get("last_success_epoch")), stale_age or 0.0, path))
    for n in notes:
        if n.startswith(("degraded", "sweep_output", "wall-clock", "terminated", "stale")):
            print("TMP-SWEEP NOTE: %s" % n)
    return exit_code


def _salvage_json(text):
    """Best-effort parse of a killed child's stdout (the JSON may be complete)."""
    payload, _err = parse_sweep_output(text)
    return payload


def cmd_status(args):
    state = state_dir(args)
    cfg_text = read_text(os.path.join(state, "config.json"))
    if cfg_text is None:
        mode, cfg_err = "report", None
    else:
        cfg, cfg_err = parse_config(cfg_text)
        mode = cfg["mode"] if cfg else "unusable"
    last_raw = read_text(os.path.join(state, "last-run.json"))
    last, state_err = ({}, "") if last_raw is None else parse_last_run(last_raw)
    last_success = (last or {}).get("last_success_epoch")
    is_stale, age_h = staleness(last_success, time.time())
    is_due, due_reason = due(last_success, time.time(),
                             (parse_config(cfg_text)[0] or {}).get("min_interval_h", MIN_INTERVAL_H)
                             if cfg_text else MIN_INTERVAL_H)
    latest_md = os.path.join(state, "latest.md")
    print("state_dir=%s" % state)
    print("mode=%s%s" % (mode, (" (config refused: %s)" % cfg_err) if cfg_err else ""))
    print("last_success_utc=%s" % (utc_stamp(last_success) if last_success else "never"))
    print("last_status=%s" % ((last or {}).get("last_status") or "never"))
    print("age_h=%s stale=%s (bound %.0fh)" % (age_h if age_h is not None else "-", is_stale,
                                               STALE_AFTER_H))
    print("due=%s (%s)" % (is_due, due_reason))
    print("latest_receipt=%s" % (os.path.join(state, "latest.json")
                                 if os.path.exists(os.path.join(state, "latest.json")) else "none"))
    print("reader=%s" % (latest_md if os.path.exists(latest_md) else "none"))
    if state_err:
        print("state_note=%s" % state_err)
    text = read_text(latest_md)
    if text:
        print("header=%s" % text.splitlines()[0].lstrip("# ").strip())
    return EXIT_OK


def cmd_report(args):
    state = state_dir(args)
    path = os.path.join(state, "latest.md")
    text = read_text(path)
    if not text:
        print("TMP-SWEEP REPORT: no receipt yet (state dir %s)" % state)
        return EXIT_OK
    print("# receipt: %s" % path)
    print(text)
    return EXIT_OK


def cmd_enable(args):
    state = state_dir(args)
    os.makedirs(state, exist_ok=True)
    cfg = {"mode": args.mode, "max_age_h": DEFAULT_MAX_AGE_H,
           "min_interval_h": MIN_INTERVAL_H, "sample": TICK_SAMPLE,
           "sample_budget_s": TICK_SAMPLE_BUDGET_S}
    if args.root:
        cfg["root"] = os.path.abspath(os.path.expanduser(args.root))
    try:
        write_atomic(os.path.join(state, "config.json"),
                     json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")
    except OSError as e:
        print("TMP-SWEEP WRITE FAILED: state_write_failed: %s: %s" % (state, e))
        return EXIT_WRITE
    print("TMP-SWEEP ENABLED mode=%s state_dir=%s" % (args.mode, state))
    if args.mode == "apply":
        print("TMP-SWEEP NOTE: apply deletes aged whitelisted fixtures on the next daily tick; "
              "run `tick --manual --mode report` first if you want a dry run.")
    return EXIT_OK


def cmd_disable(args):
    state = state_dir(args)
    os.makedirs(state, exist_ok=True)
    try:
        write_atomic(os.path.join(state, "config.json"),
                     json.dumps({"mode": "disabled"}, ensure_ascii=False, indent=2) + "\n")
    except OSError as e:
        print("TMP-SWEEP WRITE FAILED: state_write_failed: %s: %s" % (state, e))
        return EXIT_WRITE
    print("TMP-SWEEP DISABLED state_dir=%s" % state)
    return EXIT_OK


def build_parser():
    ap = argparse.ArgumentParser(description="Daily tick body for the temp-fixture sweep "
                                             "(report by default; apply after `enable --mode apply`)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, with_root=True):
        p.add_argument("--state-dir", default=None,
                       help="state dir (default: $SANDBAR_TMP_SWEEP_DIR or ~/.sandbar/tmp-sweep)")
        if with_root:
            p.add_argument("--root", default=None,
                           help="sweep root (default: config root, $TMPDIR)")
        p.add_argument("--now", type=float, default=None, help="clock seam for the cases (epoch)")

    t = sub.add_parser("tick", help="run one tick (the scheduled face)")
    common(t)
    t.add_argument("--manual", action="store_true",
                   help="human tick: bypasses the round-shape gate, stamps round_shape=manual")
    t.add_argument("--force", action="store_true", help="ignore the due gate")
    t.add_argument("--mode", choices=CONFIG_MODES, default=None, help="override the config mode")
    t.set_defaults(func=cmd_tick)

    for name, fn in (("status", cmd_status), ("report", cmd_report),
                     ("enable", cmd_enable), ("disable", cmd_disable)):
        p = sub.add_parser(name, help="")
        common(p, with_root=(name != "enable"))
        if name == "enable":
            p.add_argument("--mode", choices=CONFIG_MODES, default="report")
            p.add_argument("--root", default=None, help="sweep root to store in the config")
        p.set_defaults(func=fn)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _on_term)
        except (ValueError, OSError):
            pass
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
