#!/usr/bin/env python3
"""The line round's live face and retained evidence (t261011-26).

The round used to be invisible while it ran: its suite log lived in a
per-round system temp directory and was deleted the moment the round ended,
and nothing answered "how is the round doing". This module gives the round a
STABLE public face under the project's develop data dir, next to
``lines.json``:

- ``<develop_dir>/rounds/current.json``  — the LIVE face. It exists ONLY
  while a round is running; ABSENCE MEANS IDLE (the same rule
  workbench ``certification-model.ts`` already declares for its
  ``roundState`` input: absent = idle, nothing invented). One writer =
  ``integration/line_round_runner.py``; no other process writes this file.
- ``<develop_dir>/rounds/<run_id>/``     — the retained evidence of one
  round: ``face.json`` (the TERMINAL record: state done/failed plus the
  outcome — green / red / the named could-not-run reason — and the same
  live fields) and ``suite.log`` (the round's full suite output, retained
  rolling for the last ``FACE_RETAIN_ROUNDS`` rounds instead of being
  deleted from a system temp dir).

The face shape (the contract, documented here because this module is the
single writer)::

    {"run_id": "...", "line": "..." | null,
     "revision": {repo: revision},
     "started_at": "<iso-8601 UTC>", "updated_at": "<iso-8601 UTC>",
     "state": "running" | "done" | "failed",
     "pool": "<pool name>" | "unknown",
     "counts": {"ran": n, "pass": n, "fail": n, "env_fail": n},
     "counts_note": "counts unreadable: <why>" | "counts disagree: <...>",
     "last_scenario": {"name": "...", "verdict": "PASS|FAIL|ENV_FAIL"} | null,
     "outcome": {"verdict": "green|red|no_proof", "reason": "..."} | null}

``outcome`` is present only on the terminal ``face.json`` (never on a live
``current.json``), so "timed out" / "could not run" / "red" / "green" are
distinguishable from records alone, without reading worker.log. The verdict
vocabulary is FOUR-way distinguishable (t261012-01 spec 1+4): ``green``
(requires ran > 0 — ``terminal_verdict``), ``red``, ``no_proof`` (ran == 0 or
an unreadable count — never green, never red), and ``state=failed`` with the
named could-not-run reason. ``counts_note`` appears only when the counts are
NOT a trustworthy roll-up of the log: unreadable per-scenario lines beside a
real summary, or header/summary disagreement — the face never publishes
silent zeros next to a real summary, and never grants green from a
disagreement.

Vocabulary pin (review condition 2): the log parser below recognises the
suite's output lines AS THEY ARE PRINTED TODAY by
``integration/run_scenarios.py`` — ``PASS [name] (dur)`` /
``FAIL [name] exit=N (dur)`` / ``ENV_FAIL [name] exit=N (dur)`` result
blocks (~line 6220), the pool banners ``点名 [name]（池=…）`` /
``跳过 [name]（池=…）`` and the pool-exclusion summary
``本轮跳过池=…（少 N 条）``, and the ``INTEG_SUMMARY `` end mark. Any other
or garbled line is IGNORED (named here, silent in code by design — the
degrade rule), so vocabulary drift shows up as a stale face
(counts stop moving, pool stays ``unknown``), never as a wrong count.

Develop-dir resolution fault modes (review condition 3, borrowed
implementation = the enumeration rule of
``develop_certify.declared_line_projects``): the runner knows only the
candidate repos, so this module scans the projects root
(``SANDBAR_PROJECTS_DIR`` or ``~/.sandbar/projects``) for the project whose
``lines.json`` declares one of them. Declared dispositions:
- ``SANDBAR_LINE_ROUND_FACE_DIR`` override wins verbatim (tests);
- no project declares a candidate repo  -> None, named stderr degrade;
- MULTIPLE projects declare it          -> first in sorted order wins,
  with a named stderr line naming both (single-repo lines are the norm;
  the face stays honest because ``line`` is read from that declaration);
- unreadable projects root / torn lines.json -> skipped, named; the scan
  NEVER raises into the round;
- a declaration whose repo set is empty is impossible by schema
  (``repositories must be a non-empty list``) — a hand-made empty one is
  treated as "no match", same disposition.
An unresolved face dir is a NAMED degrade: the round still runs and its
header still relays; only the face is absent.
"""
import json
import os
import re
import shutil
import sys
import threading
import time
from pathlib import Path

FACE_DIR_ENV = "SANDBAR_LINE_ROUND_FACE_DIR"
PROJECTS_DIR_ENV = "SANDBAR_PROJECTS_DIR"
#: How often the watcher re-reads the suite log (seconds). Cheap: one stat
#: + read of a text file; never blocks the suite (daemon thread).
FACE_POLL_S = 2.0
#: Rolling retention for per-round evidence directories.
FACE_RETAIN_ROUNDS = 10
#: The only directory shapes the retention window may ever delete: the
#: provisional dir this writer creates (`round-<ts>-<pid>`) and the evidence
#: dir it relabels to the ledger run id (`run-<id>`). Anything else living in
#: the shared rounds dir (fixture leftovers, scratch) is foreign — t261012-06:
#: a name sort over a shared directory once deleted exactly the live round
#: dirs because `run-` fixture dirs outranked `round-` lexically.
ROUND_DIR_RE = re.compile(r"^(?:round|run)-")
CURRENT_NAME = "current.json"
FACE_NAME = "face.json"
LOG_NAME = "suite.log"
TAG = "LINE_ROUND_FACE"

#: Pinned vocabulary (see module docstring). Anchored, never paraphrased.
_PASS_RE = re.compile(r"^PASS \[(.+?)\] \(")
_FAIL_RE = re.compile(r"^FAIL \[(.+?)\] exit=\S+")
_ENV_FAIL_RE = re.compile(r"^ENV_FAIL \[(.+?)\] exit=\S+")
_POOL_RE = re.compile(r"^(?:点名|跳过) \[(.+?)\]（池=(.+?)）")
_POOL_EXCLUDED_RE = re.compile(r"^本轮跳过池=(.+?)（少 \d+ 条）")
SUMMARY_PREFIX = "INTEG_SUMMARY "

#: Count vocabulary, both spellings the suite prints (pinned like the block
#: regexes above). The INTEG_SUMMARY lines of ``run_scenarios.py`` (main path
#: ~line 6400 and budget-exhausted path ~line 5820) use ``ran / pass / fail /
#: not_checked``; the ledger run header's ``cases`` and the engine's
#: ``develop_certify.run_verdict`` use ``ran / passed / failed / env_failed``;
#: ``REPROBE_SUMMARY`` prints ``passed / failed / env_fail``. All fold to one
#: canonical shape here, so a verdict never reads a 0 out of a renamed key.
_SUMMARY_KEY_ALIASES = {
    "ran": ("ran",),
    "pass": ("pass", "passed"),
    "fail": ("fail", "failed"),
    "env_fail": ("not_checked", "env_fail", "env_failed"),
}


def normalize_summary_counts(obj):
    """A summary-shaped dict -> the canonical counts (partial: only the keys
    actually present), or None when no known count key hits at all. Integers
    only (a float like NaN is not a count, a bool is not a proof)."""
    if not isinstance(obj, dict):
        return None
    out = {}
    for canon, aliases in _SUMMARY_KEY_ALIASES.items():
        for alias in aliases:
            v = obj.get(alias)
            if isinstance(v, int) and not isinstance(v, bool):
                out[canon] = v
                break
    return out or None


def counts_agree(header_counts, summary_counts):
    """True when the two canonical counts disagree on NO key the summary
    actually carries. The summary may be partial (some sites print only
    ``ran``); missing keys on either side are not a disagreement — a partial
    witness is not a contradicting one."""
    return all(header_counts.get(k) == v
               for k, v in summary_counts.items())


def terminal_verdict(counts):
    """The engine's rule, pinned from ``develop_certify.run_verdict``:
    green iff ran > 0 AND fail == 0 AND env_fail == 0 — ran == 0 is never a
    proof (a live incident made that rule, t261012-01). One deliberate
    divergence: the engine collapses ran == 0 to red; the FACE says
    ``no_proof`` instead — a round that ran nothing is not a failure either,
    and the four terminal outcomes (green / red / no_proof / failed+reason)
    must stay distinguishable. Unreadable counts (None) -> ``no_proof``:
    an unreadable count is not a proof."""
    if not counts:
        return "no_proof"
    if counts.get("ran", 0) <= 0:
        return "no_proof"
    if counts.get("fail", 0) == 0 and counts.get("env_fail", 0) == 0:
        return "green"
    return "red"


def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def snapshot_progress(text):
    """Pure: the whole suite-log text -> the progress the face should carry.
    Parses a SNAPSHOT (never deltas), so re-parsing the grown file is safe
    and idempotent. Unknown/garbled lines are IGNORED for the running counts
    (degrade rule) but NAMED in the return: ``scenario_lines_seen`` false
    beside a summary means the face's zero counts are an unreadable log, not
    a quiet round — the caller publishes a ``counts_note``, never the zeros
    alone (t261012-01 spec 3)."""
    counts = {"ran": 0, "pass": 0, "fail": 0, "env_fail": 0}
    # 261015: the suite prints a scenario's row in BOTH vocabularies (its JSON
    # row and a text line). Counting both doubled every round (measured:
    # 641 scenarios -> ran=1282). Keep them apart and prefer the machine
    # readable one when it is present.
    jcounts = {"ran": 0, "pass": 0, "fail": 0, "env_fail": 0}
    json_seen = False
    jlast = None
    last = None
    pool = "unknown"
    summary_seen = False
    scenario_lines_seen = False
    summary_counts = None
    summary_error = None
    for line in (text or "").splitlines():
        line = line.strip()
        if line.startswith(SUMMARY_PREFIX):
            summary_seen = True
            try:
                payload = json.loads(line[len(SUMMARY_PREFIX):])
            except ValueError as e:
                summary_error = "integ_summary_malformed:%s" % e
            else:
                summary_counts = normalize_summary_counts(payload)
                if summary_counts is None:
                    summary_error = "integ_summary_counts_unreadable"
            continue
        m = _POOL_EXCLUDED_RE.match(line)
        if m:
            continue  # exclusion names what did NOT run; pool stays honest
        # 261015: the suite writes its per-scenario rows as JSON
        # ({"name": …, "status": "pass"|"fail"|"env_fail"|"not-checked"}). The
        # text vocabulary below alone left EVERY JSON row unrecognized, and the
        # measured cost was severe: a round that judged hundreds of scenarios
        # published counts of ran=1 (taken from the suite's own summary) and
        # could reach green on them. Recognise the JSON shape too — one
        # vocabulary for the counts, whichever way the suite prints it.
        if line.startswith('{"name"'):
            try:
                row = json.loads(line)
            except ValueError:
                row = None
            if isinstance(row, dict) and row.get("name"):
                status = str(row.get("status") or "").strip().lower()
                name = str(row["name"])
                if status in ("pass", "ok", "passed"):
                    jcounts["pass"] += 1
                    jlast = {"name": name, "verdict": "PASS"}
                elif status in ("fail", "failed"):
                    jcounts["fail"] += 1
                    jlast = {"name": name, "verdict": "FAIL"}
                elif status in ("env_fail", "env-fail", "not-checked",
                                "not_checked"):
                    # a row that was not judged is not a pass either: it is the
                    # "could not be checked" family the env count already names
                    jcounts["env_fail"] += 1
                    jlast = {"name": name, "verdict": "ENV_FAIL"}
                else:
                    continue  # unknown status: never a counted row
                jcounts["ran"] += 1
                json_seen = True
            continue
        m = _POOL_RE.match(line)
        if m:
            pool = m.group(2)
            continue
        m = _ENV_FAIL_RE.match(line)
        if m:
            scenario_lines_seen = True
            counts["ran"] += 1
            counts["env_fail"] += 1
            last = {"name": m.group(1), "verdict": "ENV_FAIL"}
            continue
        m = _FAIL_RE.match(line)
        if m:
            scenario_lines_seen = True
            counts["ran"] += 1
            counts["fail"] += 1
            last = {"name": m.group(1), "verdict": "FAIL"}
            continue
        m = _PASS_RE.match(line)
        if m:
            scenario_lines_seen = True
            counts["ran"] += 1
            counts["pass"] += 1
            last = {"name": m.group(1), "verdict": "PASS"}
    if json_seen:
        # the machine-readable rows are the authoritative per-scenario vocabulary
        counts = jcounts
        if jlast is not None:
            last = jlast
        scenario_lines_seen = True
    out = {"counts": counts, "pool": pool,
           "last_scenario": last, "summary_seen": summary_seen,
           "scenario_lines_seen": scenario_lines_seen,
           "summary_counts": summary_counts, "summary_error": summary_error}
    return out


def atomic_write_json(path, obj):
    """The one write face: tmp file in the SAME directory, fsync, rename.
    A reader never sees a torn file; a crash leaves the previous face."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp-%d" % os.getpid())
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(str(tmp), str(path))


def resolve_develop_dir(repos, env=None):
    """The develop data dir whose lines.json declares one of ``repos``.
    Returns (path, line_id | None) or (None, None) — a None is a named
    stderr degrade, never an exception into the round (fault modes in the
    module docstring)."""
    env = os.environ if env is None else env
    override = str(env.get(FACE_DIR_ENV, "")).strip()
    if override:
        return Path(override), None
    root = str(env.get(PROJECTS_DIR_ENV, "")).strip() \
        or os.path.join(os.path.expanduser("~"), ".sandbar", "projects")
    try:
        entries = sorted(Path(root).iterdir())
    except OSError as e:
        sys.stderr.write("%s degrade: projects root unreadable (%s) — no "
                         "round face will be published\n" % (TAG, e))
        return None, None
    want = set(repos)
    matches = []
    for proj in entries:
        decl = proj / "data" / "develop" / "lines.json"
        if not decl.is_file():
            continue
        try:
            data = json.loads(decl.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                continue
            for raw in data:
                if not isinstance(raw, dict):
                    continue
                names = {r.get("name") for r in raw.get("repositories", [])
                         if isinstance(r, dict)}
                if names & want:
                    matches.append(((proj / "data" / "develop"),
                                    raw.get("line_id")))
        except (OSError, ValueError) as e:
            sys.stderr.write("%s degrade: declaration unreadable %s (%s)\n"
                             % (TAG, decl, e))
    if len(matches) > 1:
        # declared rule (review condition 3): sorted-first wins, the
        # ambiguity is NAMED so a second writer is never born silently
        sys.stderr.write("%s note: %d projects declare candidates %s — the "
                         "face publishes under the first (%s)\n"
                         % (TAG, len(matches), sorted(want), matches[0][0]))
    if matches:
        return matches[0]
    sys.stderr.write("%s degrade: no project declares candidates %s — no "
                     "round face will be published\n" % (TAG, sorted(want)))
    return None, None


def _read_current_run_id(rounds_dir):
    """The run id the live pointer on disk currently names — the guard that
    keeps one round from deleting another's pointer (review condition 1)."""
    try:
        obj = json.loads((Path(rounds_dir) / CURRENT_NAME)
                         .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return obj.get("run_id") if isinstance(obj, dict) else None


class FaceWriter:
    """Writes and retires the live face and the retained round evidence.
    All IO is best-effort-but-named: a failed face write never fails the
    round (stderr note), because the round's verdict belongs to the suite,
    not to its face."""

    def __init__(self, develop_dir, run_id, line, revisions):
        self.rounds_dir = Path(develop_dir) / "rounds"
        self.run_id = run_id
        self.line = line
        self.revisions = dict(revisions or {})
        self.run_dir = self.rounds_dir / str(run_id)
        self._foreign_named = False
        self.face = {
            "run_id": run_id, "line": line, "revision": self.revisions,
            "started_at": _now_iso(), "updated_at": _now_iso(),
            "state": "running", "pool": "unknown",
            "counts": {"ran": 0, "pass": 0, "fail": 0, "env_fail": 0},
            "last_scenario": None, "outcome": None,
        }

    def start(self):
        try:
            self.run_dir.mkdir(parents=True, exist_ok=True)
            self._prune()
            self.publish()  # guarded: never steals a foreign live pointer
        except OSError as e:
            sys.stderr.write("%s warn: face start failed (%s)\n" % (TAG, e))

    def merge_progress(self, snap):
        note = None
        if snap.get("summary_seen") and not snap.get("scenario_lines_seen"):
            # t261012-01 spec 3: a real summary beside unrecognized
            # per-scenario lines must not read as zeros — name it.
            note = ("counts unreadable: no recognizable per-scenario result "
                    "lines in suite.log%s" % (
                        "; " + snap["summary_error"]
                        if snap.get("summary_error") else ""))
        self.face.update({"pool": snap["pool"],
                          "counts": snap["counts"],
                          "last_scenario": snap["last_scenario"],
                          "updated_at": _now_iso()})
        if note is not None:
            self.face["counts_note"] = note
        else:
            self.face.pop("counts_note", None)

    def finish(self, state, verdict=None, reason=None):
        """Terminal write: face.json inside the run dir (outcome stays
        visible), then retire the live pointer ONLY IF it still names THIS
        run — a second, newer round may already own it."""
        self.face["state"] = state
        self.face["updated_at"] = _now_iso()
        self.face["outcome"] = {"verdict": verdict, "reason": reason or ""}
        try:
            atomic_write_json(self.run_dir / FACE_NAME, self.face)
        except OSError as e:
            sys.stderr.write("%s warn: terminal face write failed (%s)\n"
                             % (TAG, e))
        try:
            if _read_current_run_id(self.rounds_dir) == self.run_id:
                (self.rounds_dir / CURRENT_NAME).unlink()
        except OSError as e:
            sys.stderr.write("%s warn: live pointer retire failed (%s)\n"
                             % (TAG, e))

    def retain_log(self, src_path):
        """Copy the suite log into the run dir (retained evidence). The
        run tree may be deleted right after — the copy happens FIRST. A copy
        failure is a NAMED SECONDARY note on the face (`evidence_note`),
        never the round's reason (t261012-06): the verdict belongs to the
        suite; a missing copy only hides the evidence, not the outcome."""
        try:
            shutil.copyfile(str(src_path), str(self.run_dir / LOG_NAME))
        except OSError as e:
            self.face["evidence_note"] = ("suite log retention failed: %s"
                                          % e)
            sys.stderr.write("%s warn: suite log retention failed (%s)\n"
                             % (TAG, e))

    def publish(self):
        """Write the live pointer — but NEVER take one over that still names
        a DIFFERENT run (arbitration 261011 round 1, leg C1): an overlapping
        round (two projects, or a straggler runner) owns the pointer until
        it retires it; stealing it here would let this round's guarded
        finish delete a stranger's live face. A foreign pointer is named ONCE
        on stderr and this round publishes NO live face (its terminal record
        still lands)."""
        on_disk = _read_current_run_id(self.rounds_dir)
        if on_disk is not None and on_disk != self.run_id:
            if not self._foreign_named:
                self._foreign_named = True
                sys.stderr.write(
                    "%s note: live pointer names another round (%s) — this "
                    "round (%s) publishes no live face; its terminal record "
                    "still lands\n" % (TAG, on_disk, self.run_id))
            return
        self._write_current()

    def _write_current(self):
        try:
            atomic_write_json(self.rounds_dir / CURRENT_NAME, self.face)
        except OSError as e:
            sys.stderr.write("%s warn: live face write failed (%s)\n"
                             % (TAG, e))

    def _prune(self):
        """Rolling retention keyed on the ROUND-DIR SHAPE, ordered by mtime
        (t261012-06): the newest FACE_RETAIN_ROUNDS round-shaped dirs survive.
        A name sort over a shared directory is banned — foreign dirs (`run-`
        fixture leftovers once outranked every `round-` dir lexically) must
        never enter the window, and a dir named by the live pointer on disk
        or THIS round's own dir survives regardless of age (a round that is
        being written is never pruned). Note the mtime property: a dir's
        mtime moves when a file is written into it, so an old evidence dir
        receiving a late write can legitimately jump the window."""
        try:
            live = _read_current_run_id(self.rounds_dir)
            shaped = [d for d in self.rounds_dir.iterdir()
                      if d.is_dir() and ROUND_DIR_RE.match(d.name)]
            shaped.sort(key=lambda d: d.stat().st_mtime, reverse=True)
            old = (shaped[FACE_RETAIN_ROUNDS:]
                   if len(shaped) > FACE_RETAIN_ROUNDS else [])
            foreign = [d.name for d in self.rounds_dir.iterdir()
                       if d.is_dir() and not ROUND_DIR_RE.match(d.name)]
            if foreign:
                # named, never deleted: the window owns only round evidence
                sys.stderr.write(
                    "%s note: %d foreign dir(s) under rounds/ left untouched "
                    "(retention keys on round dirs only): %s\n"
                    % (TAG, len(foreign), ",".join(sorted(foreign)[:5])))
            removed = []
            for d in old:
                if d.name == str(live) or d.name == str(self.run_id):
                    continue
                shutil.rmtree(d, ignore_errors=True)
                if not d.exists():
                    removed.append(d.name)
            if removed:
                # t261011-26 leg D2: a real prune names itself on stderr,
                # non-fatally. The prune runs at face start — before the
                # suite — so a narrowed or could-not-run round names it too:
                # the evidence bookkeeping stays honest on every path the
                # face exists on. A dir with nothing to prune stays silent
                # (leg D1).
                sys.stderr.write(
                    "%s note: retention pruned %d old round dir(s) beyond "
                    "the keep window (FACE_RETAIN_ROUNDS=%d): %s\n"
                    % (TAG, len(removed), FACE_RETAIN_ROUNDS,
                       ",".join(removed[:5])))
        except OSError as e:
            sys.stderr.write("%s warn: retention prune failed (%s)\n"
                             % (TAG, e))


class LogWatcher(threading.Thread):
    """Tail-polls the suite log and refreshes the live face. Daemon thread;
    ``stop()`` joins it on EVERY runner exit path (normal, could-not-run,
    signal unwind) — no orphaned thread, no leaked fd, full terminal-state
    reclamation. A read error degrades to a named stderr note."""

    def __init__(self, writer, log_path, poll_s=FACE_POLL_S):
        super().__init__(daemon=True, name="line-round-face")
        self.writer = writer
        self.log_path = Path(log_path)
        self.poll_s = poll_s
        self._halt = threading.Event()  # NOT named _stop: Thread reserves it

    def run(self):
        while not self._halt.wait(self.poll_s):
            try:
                text = self.log_path.read_text(encoding="utf-8",
                                               errors="replace")
            except OSError:
                continue  # log not created yet / mid-rotation: try again
            self.writer.merge_progress(snapshot_progress(text))
            self.writer.publish()

    def stop(self):
        self._halt.set()
        self.join(timeout=self.poll_s * 3)
