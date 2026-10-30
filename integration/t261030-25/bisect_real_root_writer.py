#!/usr/bin/env python3
"""Bisect which test fixture writes the REAL projects root (t261030-25, KI-429).

The instrument: ``lib_real_root_watch`` fingerprints the real root BY CONTENT
before and after a candidate run. This driver runs candidates (a scenario cmd,
a pytest battery, any shell command) and reports DIRTY / CLEAN per attempt, so
the writer is NAMED by measurement instead of guessed.

Modes:
- ``one``    -- run one ``--label/--cmd`` pair, print what changed;
- ``sweep``  -- run every candidate alone, report the dirty ones;
- ``bisect`` -- group bisection over the candidate list: a batch whose run
  leaves the root byte-unchanged is discarded whole, a dirty batch is split
  in half until one candidate is left (that one is the named writer).

Candidate sources: ``--from-registry`` (every entry of
``integration/run_scenarios.py``, the same cmd the round runs), ``--grep TOKEN``
(registry entries whose FILE mentions the token, cheap narrowing before a
bisect), or ``--candidates FILE`` (one ``label<TAB>cmd`` per line).

Isolation of the bisect itself (two layers, both mandatory in the default
mode):

1. ``--repo`` points the candidates at a SCRATCH tree (a git worktree/clone), so
   the hunt cannot dirty the checkout it is instrumenting;
2. ``--decoy`` (DEFAULT ON) gives every candidate a THROWAWAY HOME whose
   projects root is a MIRROR of the project under measurement, and watches
   THAT. A candidate that follows ``~`` or ``SANDBAR_PROJECTS_DIR`` therefore
   writes the decoy, never production. The real root is still snapshotted
   around every attempt as a read-only GUARD: if a candidate hardcodes a
   production path and escapes the decoy, the attempt is reported
   ``ESCAPE::DIRTY`` and named loudly -- the harness never writes production
   state itself (t261030-25: an early version did, by measuring in place; the
   live worker's then-stale reconciliation minted certifications from the rows
   the candidates left behind).

Every attempt is appended to the ``--out`` JSON report and printed as one line:
``[attempt N] label=<l> before=<hash> after=<hash> CLEAN|DIRTY ...``.
``--no-decoy`` measures the real root directly and is refused unless
``--i-know-this-writes-production`` is also given.
"""

import argparse
import atexit
import json
import os
import pathlib
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lib_real_root_watch as watch  # noqa: E402


def load_registry(repo):
    """The round's own candidate list (name, cmd) read out of the registry
    module, WITHOUT importing its heavy tail: exec the module and read
    ``SCENARIOS``."""
    path = pathlib.Path(repo) / "integration" / "run_scenarios.py"
    ns = {"__name__": "sandbar_registry_probe", "__file__": str(path)}
    code = compile(path.read_text(encoding="utf-8"), str(path), "exec")
    old = sys.argv
    sys.argv = [str(path)]
    try:
        exec(code, ns)  # noqa: S102 - reading the declared registry, not running it
    finally:
        sys.argv = old
    out = []
    for entry in ns["SCENARIOS"]:
        out.append({"label": entry[0], "cmd": entry[2], "pool": entry[3] if len(entry) > 3 else "main"})
    return out


def scenario_file(repo, cmd):
    """The file a registry cmd names (for --grep narrowing)."""
    parts = cmd.split()
    for token in parts:
        if token.endswith((".py", ".mjs")):
            return pathlib.Path(repo) / token
    return None


def read_candidates(path):
    out = []
    for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" in line:
            label, cmd = line.split("\t", 1)
        else:
            label, cmd = line, line
        out.append({"label": label.strip(), "cmd": cmd.strip(), "pool": "?"})
    return out


def run_cmd(cmd, cwd, timeout, env=None):
    """Run one candidate; kill its whole process group on timeout. Returns
    (rc, elapsed_s, tail) where the tail is the last bytes of stderr+stdout."""
    started = time.time()
    child_env = dict(os.environ if env is None else env)
    try:
        proc = subprocess.Popen(
            ["/bin/sh", "-c", cmd], cwd=str(cwd), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            start_new_session=True, env=child_env)
    except OSError as e:
        return ("spawn_error:%s" % e), time.time() - started, ""
    try:
        out, _ = proc.communicate(timeout=timeout)
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            out, _ = proc.communicate(timeout=10)
        except Exception:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                pass
            out, _ = proc.communicate()
        rc = "timeout"
    elapsed = time.time() - started
    text = (out or b"").decode("utf-8", "replace")
    return rc, elapsed, text[-400:]


#: The files a decoy projects root needs to look like the real one to a round:
#: the line declaration, the ledgers the readers consult, and the face tree.
DECOY_COPY = (
    "data/develop/lines.json",
    "data/develop/landings.jsonl",
    "ledger/delivery.jsonl",
    "ledger/scenario-runs.jsonl",
    "ledger/run_watch_state.json",
)


def build_decoy(project):
    """A throwaway HOME whose projects root mirrors ``project``. Returns
    (home, project_dir). Only the small files a round reads are copied; the
    two oversized append-only ledgers are replaced by empty files (their
    size/mtime witness is meaningless on a copy)."""
    import shutil
    import tempfile
    home = pathlib.Path(tempfile.mkdtemp(prefix="sandbar-decoy-home-"))
    # reclaim on every exit path: the decoy is a throwaway copy, never left
    # behind to be mistaken for state
    atexit.register(shutil.rmtree, home, True)
    real_project = watch.project_dir(project)
    decoy_project = home / ".sandbar" / "projects" / project
    for rel in DECOY_COPY:
        src = real_project / rel
        dst = decoy_project / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_file():
            shutil.copyfile(src, dst)
        else:
            dst.write_text("", encoding="utf-8")
    rounds = real_project / "data" / "develop" / "rounds"
    if rounds.is_dir():
        shutil.copytree(rounds, decoy_project / "data" / "develop" / "rounds")
    for rel in ("ledger/events.jsonl", "ledger/scenario-results.jsonl"):
        (decoy_project / rel).write_text("", encoding="utf-8")
    return home, decoy_project


class Harness:
    def __init__(self, project, repo, timeout, root=None, decoy=True):
        self.project = project
        self.repo = pathlib.Path(repo)
        self.timeout = timeout
        self.root = root
        self.decoy = decoy
        self.attempts = []
        self.home = None
        self.decoy_project = None
        if decoy:
            self.home, self.decoy_project = build_decoy(project)

    def child_env(self):
        """The environment candidates run in. Decoy mode redirects ``~`` (and
        the projects seam) at the throwaway tree, so no candidate can resolve
        a production path through either."""
        env = dict(os.environ)
        if self.decoy:
            env["HOME"] = str(self.home)
            env["SANDBAR_PROJECTS_DIR"] = str(
                self.home / ".sandbar" / "projects")
        return env

    def watch_root(self):
        if self.decoy:
            return self.decoy_project
        return self.root

    def snap(self):
        return watch.snapshot(self.project, root=self.watch_root())

    def real_guard(self):
        return watch.snapshot(self.project)

    def _escape(self, before_real):
        after_real = self.real_guard()
        if watch.diff(before_real, after_real) == ([], [], []):
            return None
        return watch.describe(before_real, after_real)

    def attempt(self, label, cmd):
        before = self.snap()
        real_before = self.real_guard()
        started = time.time()
        rc, elapsed, tail = run_cmd(cmd, self.repo, self.timeout,
                                    env=self.child_env())
        after = self.snap()
        escape = self._escape(real_before)
        row = {
            "label": label,
            "cmd": cmd,
            "rc": rc,
            "elapsed_s": round(elapsed, 2),
            "before": watch.digest(before),
            "after": watch.digest(after),
            "added": watch.diff(before, after)[0],
            "removed": watch.diff(before, after)[1],
            "changed": watch.diff(before, after)[2],
            "tail": tail,
            "escaped_real_root": escape,
            "watch_target": str(self.watch_root() or watch.project_dir(self.project)),
        }
        row["dirty"] = bool(row["added"] or row["removed"] or row["changed"])
        self.attempts.append(row)
        n = len(self.attempts)
        print("[attempt %d] %s n=%d before=%s after=%s %s"
              % (n, label, 1, row["before"], row["after"],
                 ("DIRTY " + watch.describe(before, after)) if row["dirty"]
                 else "CLEAN"), flush=True)
        if escape:
            row["dirty"] = True
            print("[attempt %d] ESCAPE::DIRTY the candidate wrote the REAL "
                  "projects root (%s) -- it ignored the decoy HOME and the "
                  "projects seam; reported, never reverted" % (n, escape),
                  flush=True)
        return row

    def batch(self, members):
        """Run a whole batch as ONE attempt (serial inside)."""
        label = "batch[%d]: %s .. %s" % (
            len(members), members[0]["label"], members[-1]["label"])
        before = self.snap()
        real_before = self.real_guard()
        started = time.time()
        rcs = []
        for member in members:
            rc, _, _ = run_cmd(member["cmd"], self.repo, self.timeout,
                               env=self.child_env())
            rcs.append(rc)
        after = self.snap()
        escape = self._escape(real_before)
        row = {
            "label": label,
            "cmd": "BATCH",
            "members": [m["label"] for m in members],
            "rc": sorted({str(r) for r in rcs}),
            "elapsed_s": round(time.time() - started, 2),
            "before": watch.digest(before),
            "after": watch.digest(after),
            "added": watch.diff(before, after)[0],
            "removed": watch.diff(before, after)[1],
            "changed": watch.diff(before, after)[2],
            "tail": "",
            "escaped_real_root": escape,
            "watch_target": str(self.watch_root() or watch.project_dir(self.project)),
        }
        row["dirty"] = bool(row["added"] or row["removed"] or row["changed"])
        self.attempts.append(row)
        print("[attempt %d] %s before=%s after=%s %s"
              % (len(self.attempts), label, row["before"], row["after"],
                 ("DIRTY " + watch.describe(before, after)) if row["dirty"]
                 else "CLEAN"), flush=True)
        if escape:
            print("[attempt %d] ESCAPE::DIRTY the batch wrote the REAL "
                  "projects root (%s)" % (len(self.attempts), escape),
                  flush=True)
        return row

    def bisect(self, candidates):
        """Group bisection. Returns the list of named writers (label + the
        evidence row that named it)."""
        named = []
        queue = [candidates]
        while queue:
            group = queue.pop(0)
            if not group:
                continue
            row = self.batch(group)
            if not row["dirty"]:
                continue
            if len(group) == 1:
                named.append({"label": group[0]["label"],
                              "cmd": group[0]["cmd"],
                              "evidence": row})
                continue
            mid = len(group) // 2
            queue.insert(0, group[:mid])
            queue.insert(1, group[mid:])
        return named

    def sweep(self, candidates):
        dirty = []
        for member in candidates:
            row = self.attempt(member["label"], member["cmd"])
            if row["dirty"]:
                dirty.append({"label": member["label"], "cmd": member["cmd"],
                              "evidence": row})
        return dirty


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("one", "sweep", "bisect"), default="bisect")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--project", default="sandbar")
    ap.add_argument("--root", default="", help="watch this project dir instead of the real one")
    ap.add_argument("--from-registry", action="store_true")
    ap.add_argument("--grep", default="", help="narrow registry entries to files mentioning TOKEN")
    ap.add_argument("--candidates", default="", help="label<TAB>cmd per line")
    ap.add_argument("--limit", type=int, default=0, help="only the first N candidates")
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--no-decoy", action="store_true",
                    help="measure the REAL root in place (production writes!)")
    ap.add_argument("--i-know-this-writes-production", action="store_true",
                    help="required together with --no-decoy")
    ap.add_argument("--label", default="candidate")
    ap.add_argument("--cmd", default="")
    ap.add_argument("--out", default="")
    args = ap.parse_args(argv)

    if args.mode == "one" and not args.cmd:
        ap.error("--mode one needs --cmd")
    if args.candidates:
        candidates = read_candidates(args.candidates)
    elif args.from_registry:
        candidates = load_registry(args.repo)
        if args.grep:
            keep = []
            for entry in candidates:
                path = scenario_file(args.repo, entry["cmd"])
                if path is None:
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                if args.grep in text:
                    keep.append(entry)
            candidates = keep
    else:
        candidates = []
    if args.limit:
        candidates = candidates[:args.limit]

    decoy = not args.no_decoy
    if not decoy and not args.i_know_this_writes_production:
        ap.error("--no-decoy measures (and can WRITE) the real projects root; "
                 "it needs --i-know-this-writes-production. The default is the "
                 "decoy: candidates cannot reach production state at all.")
    if not decoy:
        sys.stderr.write(
            "WARNING: measuring the REAL projects root in place. Any candidate "
            "that writes production state will do so for real.\n")
    harness = Harness(args.project, args.repo, args.timeout,
                      root=args.root or None, decoy=decoy)
    if args.mode == "one":
        dirty = harness.attempt(args.label, args.cmd)
        named = [{"label": args.label, "cmd": args.cmd, "evidence": dirty}] \
            if dirty["dirty"] else []
    elif args.mode == "sweep":
        named = harness.sweep(candidates)
    else:
        named = harness.bisect(candidates)

    report = {
        "mode": args.mode,
        "repo": str(pathlib.Path(args.repo).resolve()),
        "project": args.project,
        "watch_root": harness.snap()["root"],
        "decoy": decoy,
        "real_root": str(watch.project_dir(args.project)),
        "candidate_count": len(candidates),
        "named_writers": named,
        "attempts": harness.attempts,
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if args.out:
        pathlib.Path(args.out).write_text(json.dumps(report, indent=1) + "\n",
                                         encoding="utf-8")
    print("\nNAMED WRITERS: %s"
          % (", ".join(w["label"] for w in named) if named else "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
