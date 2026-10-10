#!/usr/bin/env python3
"""The line round's declared runner (t261009-77).

The develop buffer's proving act is driven by a command declared through
``SANDBAR_LINE_ROUND_RUNNER`` in the WORKER's environment (changing it needs a
worker restart). This script is that command. The contract it satisfies is
``develop_certify.resolve_runner``'s docstring (server/engine/develop_certify.py):

- input: ``SANDBAR_LINE_ROUND_CANDIDATES`` — the candidate revision set as
  JSON (``[{"repo": ..., "revision": ...}]``) in the environment;
- a tree of its own: every candidate repo is CLONED from its source checkout
  and checked out at the candidate revision — the run can never touch the
  delivered checkout (``refuse_delivered_checkout``'s concern is structural);
- output: EXACTLY ONE JSON run header on stdout (nothing else — the engine
  ``json.loads`` the whole stdout), the ledger's own header relayed verbatim,
  so the counts are the same recount the suite produced (no second counting)
  and the case rows carry the run id;
- exit 0 on success — INCLUDING a completed-but-red round (a red is a proof
  that opens the freeze path); every could-not-run path exits nonzero with a
  named reason on stderr and NEVER a fabricated header.

How "ran" is separated from "could not run": the suite
(``integration/run_scenarios.py``, the declared full suite) writes its run
record — rows then one header validated against the same recount — and
prints ``INTEG_SUMMARY`` with the additive ``run_id`` key before its exit-code
decision. The runner reads that header back from the run-scoped ledger and
relays it. Missing summary, missing run id, missing header (interrupted run)
are each a named nonzero exit.

Environment seams:
- ``SANDBAR_LINE_ROUND_SUITE_CMD``   suite command override (shlex-split;
                                     default: this interpreter +
                                     ``integration/run_scenarios.py``);
- ``SANDBAR_LINE_ROUND_REPO_PATH_<NAME>``  per-repo source checkout; a repo
                                     without one falls back to the checkout
                                     this runner file lives in;
- ``SANDBAR_LINE_ROUND_RUN_ROOT``    run-tree parent override (tests);
- ``SANDBAR_LINE_ROUND_RUN_STATE_DIR``  stale-run sweep bookkeeping (tests).
"""
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CANDIDATES_ENV = "SANDBAR_LINE_ROUND_CANDIDATES"
SUITE_CMD_ENV = "SANDBAR_LINE_ROUND_SUITE_CMD"
REPO_PATH_PREFIX = "SANDBAR_LINE_ROUND_REPO_PATH_"
RUN_ROOT_ENV = "SANDBAR_LINE_ROUND_RUN_ROOT"
STATE_DIR_ENV = "SANDBAR_LINE_ROUND_RUN_STATE_DIR"
#: Runner-mode neutralization (review C1): the suite must write its own run
#: record. A worker env that happens to carry the gate-owner flag would make
#: the round write nothing and the read-back find no header — honest but
#: spuriously named; the runner removes the inherited flag instead.
GATE_OWNER_ENV = "SANDBAR_INTEG_LEDGER_OWNER"
TICKET_ENV = "SANDBAR_TICKET_ID"
SOURCE_ENV = "SANDBAR_INTEG_LEDGER_SOURCE"
REUSE_ENV = "SANDBAR_LEDGER_REUSE"
GIT_SHA_ENV = "SANDBAR_GIT_SHA"
LEDGER_DIR_ENV = "SANDBAR_SCENARIO_LEDGER_DIR"
#: What the run record wears. The record model (docs/reference/
#: ledger-record-models-v1.md) proposes `scheduled`, but the store's closed
#: source vocabulary today (scenario_ledger._check_source) accepts only
#: `baseline` / `inspection` / `lane:<x>` — a `scheduled` row would be
#: rejected wholesale and the round would find no header. `lane:line-round`
#: is the honest member of TODAY's vocabulary (widening the vocabulary is a
#: store-schema change, a separate ticket).
RUN_SOURCE = "lane:line-round"
CLONE_TIMEOUT_S = 900
#: A stale run tree is swept on the next startup only after this age — a
#: still-warm tree from a SIGKILLed runner is swept later, never raced.
STALE_SWEEP_MIN_AGE_S = 3600
TAG = "LINE_ROUND_RUNNER"


def die(reason):
    """The one could-not-run exit: named reason on stderr, nonzero exit,
    stdout stays empty — the engine's CouldNotRun path carries the name."""
    sys.stderr.write("%s could_not_run: %s\n" % (TAG, reason))
    sys.exit(2)


def parse_candidates(env=None):
    """The candidate revision set in, validated. Malformed input is refused
    by name, never guessed (fixed-payload matrix in the unit battery)."""
    env = os.environ if env is None else env
    raw = str(env.get(CANDIDATES_ENV, "")).strip()
    if not raw:
        die("candidates_env_unset:%s" % CANDIDATES_ENV)
    try:
        data = json.loads(raw)
    except ValueError as e:
        die("candidates_not_json:%s" % e)
    if not isinstance(data, list) or not data:
        die("candidates_not_nonempty_list")
    clean = []
    for member in data:
        if not isinstance(member, dict) \
                or not isinstance(member.get("repo"), str) or not member["repo"] \
                or not isinstance(member.get("revision"), str) \
                or not member["revision"]:
            die("candidate_member_malformed:%r" % (member,))
        clean.append({"repo": member["repo"], "revision": member["revision"]})
    return clean


def self_repo_root():
    """The checkout this runner file is delivered in — the default source."""
    return Path(__file__).resolve().parent.parent


def source_for(repo, env=None):
    """Per-repo source checkout: the declared path env first, the runner's
    own checkout as fallback. Returns (path, declared_or_default)."""
    env = os.environ if env is None else env
    key = REPO_PATH_PREFIX + re.sub(r"[^A-Z0-9]+", "_", repo.upper())
    raw = str(env.get(key, "")).strip()
    if raw:
        return Path(raw), "declared:%s" % key
    return self_repo_root(), "default:self-checkout"


def nested(a, b):
    """True when path a equals b or lives inside b (realpath-resolved)."""
    a, b = Path(os.path.realpath(str(a))), Path(os.path.realpath(str(b)))
    return a == b or b in a.parents


def prepare_tree(candidate, run_root, env=None):
    """Clone one candidate repo into the run tree at its revision. Own tree
    by construction; a clone into / over the source checkout is refused by
    name before git runs."""
    repo, revision = candidate["repo"], candidate["revision"]
    src, how = source_for(repo, env)
    if not Path(src).is_dir():
        die("source_missing:%s:%s" % (repo, src))
    dst = Path(run_root) / repo
    if nested(dst, src) or nested(src, dst):
        die("tree_overlaps_source_checkout:%s:%s" % (dst, src))
    try:
        proc = subprocess.run(
            ["git", "clone", "--quiet", "--no-hardlinks", str(src), str(dst)],
            capture_output=True, text=True, timeout=CLONE_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        die("clone_timeout:%s:%ds" % (repo, CLONE_TIMEOUT_S))
    except OSError as e:
        die("clone_unreachable:%s:%s" % (repo, e))
    if proc.returncode != 0:
        die("clone_failed:%s:%s" % (repo, proc.stderr.strip()[-300:]))
    try:
        proc = subprocess.run(
            ["git", "-C", str(dst), "checkout", "--quiet", "--detach",
             revision],
            capture_output=True, text=True, timeout=300)
    except (subprocess.TimeoutExpired, OSError) as e:
        die("checkout_unreachable:%s:%s" % (repo, e))
    if proc.returncode != 0:
        die("checkout_failed:%s@%s:%s"
            % (repo, revision, proc.stderr.strip()[-300:]))
    return dst, src, how


def suite_argv(env=None):
    """The declared full suite command; override parsed with shlex, default
    is this interpreter plus the suite entry point."""
    env = os.environ if env is None else env
    raw = str(env.get(SUITE_CMD_ENV, "")).strip()
    if not raw:
        return [sys.executable, "integration/run_scenarios.py"]
    argv = shlex.split(raw)
    if not argv:
        die("suite_cmd_empty:%s" % SUITE_CMD_ENV)
    return argv


def suite_env(run_root, primary_revision):
    """The suite's environment: the runner-mode pins (C1 owner neutralized,
    reuse off — a fully reused round would mint a ran==0 header, which the
    engine refuses; better to not offer the trap), the run-scoped ledger dir
    (the run record is self-consistent and never intermixes with the
    worker's interactive ledger) and the pinned revision."""
    run_env = dict(os.environ)
    for key in (GATE_OWNER_ENV, TICKET_ENV):
        run_env.pop(key, None)
    run_env[SOURCE_ENV] = RUN_SOURCE
    run_env[REUSE_ENV] = "0"
    run_env[LEDGER_DIR_ENV] = str(Path(run_root) / "ledger")
    run_env[GIT_SHA_ENV] = primary_revision
    return run_env


def parse_integ_summary(log_path):
    """The suite's completion signal: the last INTEG_SUMMARY line. Missing or
    unparseable returns (None, why) — the caller names the could-not-run."""
    try:
        text = Path(log_path).read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return None, "suite_log_unreadable:%s" % e
    summary = None
    for line in text.splitlines():
        if line.startswith("INTEG_SUMMARY "):
            try:
                summary = json.loads(line[len("INTEG_SUMMARY "):])
            except ValueError:
                return None, "integ_summary_malformed"
    if summary is None:
        return None, "integ_summary_missing"
    if not isinstance(summary, dict):
        return None, "integ_summary_not_object"
    return summary, None


def tail(text, n=300):
    return (text or "").strip()[-n:]


def run(env=None):
    """The whole command. Returns the exit code; the header (the one stdout
    line) is printed inside."""
    env = os.environ if env is None else env
    candidates = parse_candidates(env)
    run_root = Path(env.get(RUN_ROOT_ENV, "").strip() or tempfile.mkdtemp(
        prefix="line-round-"))
    run_root.mkdir(parents=True, exist_ok=True)
    state = RunState(env, run_root)
    state.sweep_stale()
    state.record()
    try:
        clones = {}
        for candidate in candidates:
            clones[candidate["repo"]] = prepare_tree(candidate, run_root, env)[0]
        primary = next((p for p in clones.values()
                        if (p / "integration" / "run_scenarios.py").is_file()),
                       None)
        if primary is None:
            die("suite_tree_missing:no candidate clone carries "
                "integration/run_scenarios.py")
        primary_candidate = next(c for c in candidates
                                 if clones[c["repo"]] == primary)
        log_path = run_root / "suite.log"
        argv = suite_argv(env)
        with open(log_path, "wb") as log:
            try:
                proc = subprocess.Popen(
                    argv, cwd=str(primary),
                    env=suite_env(run_root, primary_candidate["revision"]),
                    stdout=log, stderr=subprocess.STDOUT,
                    start_new_session=True)
            except OSError as e:
                die("suite_unreachable:%s" % e)
            hit = {"signum": 0}

            def on_signal(signum, frame):
                hit["signum"] = signum
                raise KeyboardInterrupt  # unwinds into the handler below

            prev_term = signal.signal(signal.SIGTERM, on_signal)
            prev_int = signal.signal(signal.SIGINT, on_signal)
            try:
                rc = proc.wait()
            except KeyboardInterrupt:
                # process-group termination face: a killed runner must not
                # orphan a half-running suite writing into a dying tree
                try:
                    os.killpg(proc.pid, signal.SIGTERM)
                    proc.wait(timeout=10)
                except Exception:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                        proc.wait(timeout=10)
                    except Exception:
                        pass
                die("runner_signaled:%d" % hit["signum"])
            finally:
                signal.signal(signal.SIGTERM, prev_term)
                signal.signal(signal.SIGINT, prev_int)
        summary, why = parse_integ_summary(log_path)
        if summary is None:
            die("suite_rc_%d:%s;%s"
                % (rc, why, tail(log_path.read_text(
                    encoding="utf-8", errors="replace"))))
        header, why = read_header(primary, Path(run_root) / "ledger", summary)
        if header is None:
            die("suite_rc_%d:%s" % (rc, why))
        sys.stdout.write(json.dumps(header, ensure_ascii=False) + "\n")
        sys.stdout.flush()
        return 0
    finally:
        state.retire()
        shutil.rmtree(run_root, ignore_errors=True)


def read_header(primary, ledger_dir, summary):
    """Read the suite's own header back from the run-scoped ledger by the
    summary's run id (the relay, not a second counting)."""
    ledger_dir = Path(ledger_dir)
    run_id = summary.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        return None, "run_id_missing_from_summary"
    sys.path.insert(0, str(Path(primary) / "integration"))
    try:
        import scenario_ledger  # noqa: PLC0415 — the clone's own store
    except Exception as e:  # noqa: BLE001
        return None, "ledger_module_unreadable:%s" % e
    finally:
        sys.path.pop(0)
    try:
        headers, bad = scenario_ledger.read_runs(
            path=ledger_dir / "scenario-runs.jsonl")
    except Exception as e:  # noqa: BLE001
        return None, "ledger_unreadable:%s" % e
    finally:
        sys.modules.pop("scenario_ledger", None)
    for header in headers:
        if isinstance(header, dict) and header.get("id") == run_id:
            if not isinstance(header.get("cases"), dict) \
                    or not isinstance(header.get("id"), str):
                return None, "run_header_malformed:%s" % run_id
            return header, None
    return None, "run_header_missing:%s%s" % (
        run_id, (";%s" % ",".join(map(str, bad))) if bad else "")


class RunState:
    """Best-effort stale-tree bookkeeping: a runner SIGKILLed by the engine's
    timeout cannot run its finally, so the NEXT startup sweeps its leftover
    tree (older than the grace age, owner process gone). Unavailable state
    storage degrades to a named stderr note — hygiene, never a judge."""

    def __init__(self, env, run_root):
        self.run_root = str(run_root)
        self.path = Path(
            str(env.get(STATE_DIR_ENV, "")).strip()
            or os.path.join(os.path.expanduser("~"), ".sandbar",
                            "line-round-runner")) / "runs.jsonl"
        self.ok = False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.ok = True
        except OSError as e:
            sys.stderr.write("%s warn: state dir unavailable (%s) — stale "
                             "sweep disabled\n" % (TAG, e))

    def _lines(self):
        try:
            return [json.loads(ln) for ln in
                    self.path.read_text(encoding="utf-8").splitlines()
                    if ln.strip()]
        except (OSError, ValueError):
            return []

    def sweep_stale(self, now=None):
        if not self.ok:
            return
        now = time.time() if now is None else now
        kept = []
        for entry in self._lines():
            root, pid, at = entry.get("root"), entry.get("pid"), \
                entry.get("at", 0)
            fresh = (now - at) < STALE_SWEEP_MIN_AGE_S
            alive = False
            if isinstance(pid, int) and pid > 0:
                try:
                    os.kill(pid, 0)
                    alive = True
                except OSError:
                    alive = False
            if root != self.run_root and not alive and not fresh \
                    and isinstance(root, str) and root.startswith(
                        tempfile.gettempdir()):
                shutil.rmtree(root, ignore_errors=True)
            else:
                kept.append(entry)
        try:
            self.path.write_text(
                "".join(json.dumps(e) + "\n" for e in kept),
                encoding="utf-8")
        except OSError:
            pass

    def record(self):
        if not self.ok:
            return
        try:
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"root": self.run_root,
                                     "pid": os.getpid(),
                                     "at": time.time()}) + "\n")
        except OSError:
            pass

    def retire(self):
        if not self.ok:
            return
        kept = [e for e in self._lines()
                if e.get("root") != self.run_root or e.get("pid") != os.getpid()]
        try:
            self.path.write_text(
                "".join(json.dumps(e) + "\n" for e in kept), encoding="utf-8")
        except OSError:
            pass


def main():
    sys.exit(run())


if __name__ == "__main__":
    main()
