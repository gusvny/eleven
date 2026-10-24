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
- ``SANDBAR_LINE_ROUND_RUN_STATE_DIR``  stale-run sweep bookkeeping (tests);

Asset hand-off (t261011-18): the runner exports SANDBAR_POC_PYTHON and
SANDBAR_TEMPORAL_BIN into the suite env, resolved from this runner's own
checkout; an unresolvable asset is a named could-not-run (asset_missing:<KEY>).
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
#: Pools the line round does not run — DEFAULT: none (run every pool).
#: Host order 261016 flips the protective 261012 default ("exclusive") back
#: to the declared intent: the exclusion is opt-in diagnostics, never the
#: default. The protective default made every round NARROWED without any
#: operator asking for it, and a narrowed round writes no run record, so no
#: round could ever mint a certification (t261016-12). An operator sets
#: SANDBAR_LINE_ROUND_EXCLUDE_POOLS to narrow a diagnostic round; an empty
#: value runs every pool, and a narrowed round says so on stderr.
#:
#: Know what a full default costs: a full round is the only kind that can
#: mint a certification, but a round that ends RED mints a RED
#: certification and a red certification OPENS A FREEZE —
#: `develop_certify.run_line_round` appends `open_freeze_rows` on any red,
#: and a frozen line refuses every landing except a `fix` carrying a
#: `repairs` relation. That trade is accepted: a line that can never mint
#: a certification is worth less than one that can (and may). The measured
#: red set at the line head is largely environment-induced (t260930-01,
#: t261004-28 measured 261012), not the revision's fault; a worker whose
#: operator wants a diagnostic round still sets the env var.
#:
#: Note also `develop_certify.should_freeze()` — dead code today — says a
#: freeze "opens only when the red implicates content".
EXCLUDE_POOLS_DEFAULT = ""
EXCLUDE_POOLS_ENV = "SANDBAR_LINE_ROUND_EXCLUDE_POOLS"
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
#: Assets the suite cannot resolve out of its own run tree (t261011-18): the
#: suite runs with cwd = a CLONE, whose .git is a directory, so bench's
#: main-tree fallback (main_root_of, gitfile-only) finds nothing there and
#: the gitignored .venv / temporal binary are absent too. The runner
#: resolves both keys from ITS OWN checkout (a real worktree, so the
#: fallback fires) and exports the absolute paths into the suite env
#: (ticket route 1: hand the suite the assets, never widen the isolation).
#: An unset key that cannot be resolved is a named could-not-run carrying
#: the env key — never a silent skip, never a header, never a
#: certification.
POC_PYTHON_ENV = "SANDBAR_POC_PYTHON"
TEMPORAL_BIN_ENV = "SANDBAR_TEMPORAL_BIN"
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
    stdout stays empty — the engine's CouldNotRun path carries the name
    (it reads the STDERR TAIL, develop_certify runner()). The face hook runs
    AFTER the reason is on stderr (t261012-06): its retention-failure warn
    is a SECONDARY note and must trail the round's own reason, never lead
    the ledger row. The outcome still lands on the stable face before exit
    (t261011-26)."""
    sys.stderr.write("%s could_not_run: %s\n" % (TAG, reason))
    sys.stderr.flush()
    hook = _FACE_HOOK[0]
    if hook is not None:
        try:
            hook(reason)
        except Exception:  # noqa: BLE001 — the face never masks the verdict
            pass
    sys.exit(2)


#: The active round's terminal-face hook, set/cleared by run() (die() calls
#: it so every could-not-run path lands on the face). One runner = one round.
_FACE_HOOK = [None]


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


#: Gitignored-but-required asset paths the round's clone cannot carry by
#: itself (t261011-21): prepare_tree() git-clones each candidate, and a
#: clone only carries committed files, so every cwd-relative probe into
#: these paths silently falls back inside the clone (system python3 without
#: pytest/PyYAML/temporalio, missing playwright-core candidates) and turns
#: the round red on environment, not product. Each entry names its
#: evidenced consumer:
#: - server/engine/.venv
#:     registry probes `PY=server/engine/.venv/bin/python` and the
#:     PyYAML/temporalio self-rescue chains (the missing-interpreter and
#:     much of the Temporal-shaped classes in the 261011-1649 suite log).
#: - server/engine/bin/temporal
#:     scenarios that spawn their own worker/console binary next to the
#:     interpreter (Temporal-shaped class).
#: - node_modules
#:     profile-farm / workbench surfaces resolving the bare package name
#:     from the repo root.
#: - server/ui-check/node_modules/playwright-core
#:     lib_pw_deps.mjs's LOCAL_PW candidate chain (browser/capture class).
#: The materialisation is one symlink per entry pointing at the source
#: checkout's copy (one copy on disk, the isolation never widened). An
#: entry genuinely absent from the source is NOT faked: it is reported on
#: stderr and skipped, so the scenario-side env_fail classification keeps
#: telling the truth — never a silent swallow, never a fabricated green.
CLONE_ASSETS = (
    "server/engine/.venv",
    "server/engine/bin/temporal",
    "node_modules",
    "server/ui-check/node_modules/playwright-core",
)


def materialise_assets(clone_root, source_root):
    """Link each declared gitignored asset from the source checkout into
    the freshly made clone (t261011-21). A destination that already exists
    in the clone (a committed path) is never overwritten; an entry absent
    from the source is skipped with a named stderr line; a failed link is
    a named could-not-run — never a half-provisioned clone that pretends
    to be whole. Idempotent by construction (exists-check first)."""
    for rel in CLONE_ASSETS:
        dst = Path(clone_root) / rel
        if dst.exists() or dst.is_symlink():
            continue
        src = Path(source_root) / rel
        if not src.exists():
            sys.stderr.write("%s asset_absent_in_source:%s — the clone "
                             "stays without it; scenario env-fails (if any) "
                             "stay the honest classification\n"
                             % (TAG, rel))
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.symlink(os.path.abspath(str(src)), str(dst))
        except OSError as e:
            die("asset_link_failed:%s:%s" % (rel, e))


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
    materialise_assets(dst, src)
    return dst, src, how


def exclude_pools_value(env=None):
    """Pools this round does NOT run — declared once, here. Default: none.

    Host order 261011 ('先把 exclusive 的池排除掉，把 line run 跑通先') got a round
    running, but 261012 found what that costs: an exclusion makes the round
    NARROWED, a narrowed round writes no run record, and a round without a
    record has no header to relay — so it can never become a certification
    (`run_scenarios.run_record_skip_reason` + this module's `read_header`).
    The exclusion is therefore opt-in (diagnostics), never the default: the
    certification round runs every pool. An operator sets
    SANDBAR_LINE_ROUND_EXCLUDE_POOLS to narrow a diagnostic round (an empty
    value = run every pool); when it is set, the runner says on stderr that
    this round cannot mint a certification.
    """
    env = os.environ if env is None else env
    raw = env.get(EXCLUDE_POOLS_ENV)
    if raw is None:
        return EXCLUDE_POOLS_DEFAULT
    return str(raw).strip()


def suite_argv(env=None):
    """The declared full suite command; override parsed with shlex, default
    is this interpreter plus the suite entry point. A NARROWING pool
    exclusion is appended only when the operator asked for one, and it is
    announced on stderr: such a round is a diagnostic, not a proof."""
    env = os.environ if env is None else env
    raw = str(env.get(SUITE_CMD_ENV, "")).strip()
    if not raw:
        argv = [sys.executable, "integration/run_scenarios.py"]
    else:
        argv = shlex.split(raw)
        if not argv:
            die("suite_cmd_empty:%s" % SUITE_CMD_ENV)
    excluded = exclude_pools_value(env)
    if excluded and "--exclude-pools" not in argv:
        argv = argv + ["--exclude-pools", excluded]
    if excluded or "--only" in argv:
        sys.stderr.write(
            "%s NARROWED: round is narrowed (exclude-pools=%r) — the suite "
            "writes no run record for a narrowed round, so this round can "
            "produce evidence but NO certification\n"
            % (TAG, excluded or "--only"))
    return argv


def asset_env(env):
    """The two suite-unresolvable asset keys, resolved for the suite
    (t261011-18). A key already set in the incoming environment is passed
    through verbatim (worker/test override wins, and bench's own env-first
    order means the suite would honor it anyway). Otherwise the asset is
    resolved through THIS checkout's integration/bench.py — the runner's
    own tree, a real worktree, whose main-tree fallback works where the
    run-tree clone's cannot. A genuinely absent asset is a named
    could-not-run naming the env key, raised before any suite spawn."""
    own_dir = str(Path(__file__).resolve().parent)
    inserted = False
    if own_dir not in sys.path:
        sys.path.insert(0, own_dir)
        inserted = True
    try:
        import bench  # noqa: PLC0415 — this checkout's own resolver
    except Exception as e:  # noqa: BLE001
        die("bench_module_unreadable:%s" % e)
    finally:
        # only undo an insert WE made: read_header later relies on this
        # directory staying importable (the clone's integration dir may
        # not carry scenario_ledger)
        if inserted:
            sys.path.remove(own_dir)
    out = {}
    for key, resolver in ((POC_PYTHON_ENV, bench.resolve_poc_python),
                          (TEMPORAL_BIN_ENV, bench.resolve_temporal_bin)):
        declared = str(env.get(key, "")).strip()
        if declared:
            if not Path(declared).exists():
                die("asset_missing:%s:%s=%s 不存在（env 指路优先，检查路径）"
                    % (key, key, declared))
            out[key] = env[key]
            continue
        # blank declared value: bench's resolver reads os.environ, so a
        # blank string would be taken as a (nonexistent) pointer — lift it
        # for the resolution and keep it out of the suite env
        held = os.environ.pop(key, None)
        try:
            out[key] = str(resolver())
        except bench.MissingAsset as e:
            die("asset_missing:%s:%s" % (key, str(e).replace("\n", " ")))
        finally:
            if held is not None:
                os.environ[key] = held
    return out


def suite_env(run_root, primary_revision, env=None):
    """The suite's environment: the runner-mode pins (C1 owner neutralized,
    reuse off — a fully reused round would mint a ran==0 header, which the
    engine refuses; better to not offer the trap), the run-scoped ledger dir
    (the run record is self-consistent and never intermixes with the
    worker's interactive ledger), the pinned revision, and the two asset
    keys the clone cannot resolve by itself (asset_env)."""
    env = os.environ if env is None else env
    run_env = dict(env)
    for key in (GATE_OWNER_ENV, TICKET_ENV):
        run_env.pop(key, None)
    run_env[SOURCE_ENV] = RUN_SOURCE
    run_env[REUSE_ENV] = "0"
    run_env[LEDGER_DIR_ENV] = str(Path(run_root) / "ledger")
    run_env[GIT_SHA_ENV] = primary_revision
    # 261023 host order: do NOT serialise the round. A case that goes red only under
    # contention is an UNQUALIFIED test - it is excluded from the round's path and
    # fixed later, not paid for by slowing every certification down.
    run_env.update(asset_env(env))
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


def failed_names(log_path):
    """The per-scenario fail set of this suite run (the relative-certification
    caliber, 261014): the names of scenarios whose row reads fail/not-checked,
    derived from the same per-scenario result lines the face counts — never
    from a second source. A round judged against a baseline compares THESE
    names, not the counts. Unreadable log -> empty set (the caller's counts
    face still names the could-not-run; a missing name-set never invents)."""
    try:
        text = Path(log_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out = set()
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith('{"name"'):
            continue
        try:
            row = json.loads(s)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("status") in ("fail", "not-checked"):
            name = row.get("name")
            if isinstance(name, str) and name.strip():
                out.add(name.strip())
    return sorted(out)


def unverified_names(log_path):
    """The names this round did NOT verify (status not-checked: an environment
    face - no bench, no console, connection refused), reported separately from
    the fail set (host order 261019, KI-01M55FVE2QZ0NR5AHQRHBNXX7S): a round
    that could not verify a case must not read as a content regression, and a
    red certificate opens a freeze on content guilt only. The names are still
    published, never swallowed - "not verified" is not "green". Same source as
    failed_names: the per-scenario result lines."""
    try:
        text = Path(log_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out = set()
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith('{"name"'):
            continue
        try:
            row = json.loads(s)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("status") == "not-checked":
            name = row.get("name")
            if isinstance(name, str) and name.strip():
                out.add(name.strip())
    return sorted(out)


def tail(text, n=300):
    return (text or "").strip()[-n:]


def resolve_face_dir(repos, env):
    """The develop dir this round's face publishes under (t261024-30: the
    ONE project-resolution rule). Primary: lib_round_face's lines.json
    declaration scan. Fallback: the SAME project the run row persists into
    (``_choose_project``'s ledger scan) — the silent-end day produced four
    rounds with a run row and NO round directory because the two rules
    answered "which project" differently; when the declaration scan misses,
    the ledger answer is named on stderr and used, so a round whose run row
    lands always gets its evidence dir. Returns (dir | None, line_id)."""
    import lib_round_face
    fdir, line_id = lib_round_face.resolve_develop_dir(repos, env)
    if fdir is None:
        proj, _already = _choose_project(env)
        if proj is not None:
            fdir = proj / "data" / "develop"
            sys.stderr.write(
                "%s note: face dir unresolved by lines.json declaration — "
                "falling back to the run-row project (%s)\n" % (TAG, fdir))
    return fdir, line_id


def run(env=None):
    """The whole command. Returns the exit code; the header (the one stdout
    line) is printed inside."""
    env = os.environ if env is None else env
    candidates = parse_candidates(env)
    run_root = Path(env.get(RUN_ROOT_ENV, "").strip() or tempfile.mkdtemp(
        prefix="line-round-"))
    run_root.mkdir(parents=True, exist_ok=True)
    # The round's stable face (t261011-26): resolved BEFORE anything runs so
    # even a pre-spawn could-not-run is visible. Unresolved = named degrade,
    # the round runs exactly as before, only the face is absent.
    import lib_round_face
    fdir, line_id = resolve_face_dir(
        sorted({c["repo"] for c in candidates}), env)
    face = watcher = None
    if fdir is not None:
        round_id = "round-%s-%d" % (time.strftime("%Y%m%dT%H%M%SZ",
                                                  time.gmtime()), os.getpid())
        face = lib_round_face.FaceWriter(
            fdir, round_id, line_id,
            {c["repo"]: c["revision"] for c in candidates})
        face.start()
    state = RunState(env, run_root)
    state.sweep_stale()
    state.record()
    watcher_holder = [None]

    def face_failed(reason):
        # every could-not-run path (die, signal unwind) lands here first:
        # state=failed + the named reason, distinguishable without worker.log
        if watcher_holder[0] is not None:
            watcher_holder[0].stop()
        if face is not None:
            face.retain_log(run_root / "suite.log")
            face.finish("failed", None, reason)

    _FACE_HOOK[0] = face_failed
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
            if face is not None:
                watcher = lib_round_face.LogWatcher(face, log_path)
                watcher_holder[0] = watcher
                watcher.start()
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
        if watcher is not None:
            watcher.stop()
            watcher_holder[0] = None
        if summary is None:
            die("suite_rc_%d:%s;%s"
                % (rc, why, tail(log_path.read_text(
                    encoding="utf-8", errors="replace"))))
        header, why = read_header(primary, Path(run_root) / "ledger", summary)
        if header is None:
            die("suite_rc_%d:%s" % (rc, why))
        if face is not None:
            # outcome stays visible (t261011-26 spec 4) — and TRUTHFUL
            # (t261012-01): green requires ran > 0, the face counts agree
            # with the retained log, and an unreadable count is NAMED, never
            # silently zero beside a real INTEG_SUMMARY.
            cases = header.get("cases") or {}
            header_counts = lib_round_face.normalize_summary_counts(cases)
            snap = lib_round_face.snapshot_progress(
                log_path.read_text(encoding="utf-8", errors="replace"))
            face.merge_progress(snap)
            summary_counts = snap["summary_counts"]
            if not snap["scenario_lines_seen"] and summary_counts is not None:
                # the log's per-scenario lines are in an unknown shape: the
                # face counts come from the suite's own INTEG_SUMMARY (they
                # agree with the retained log by construction); the zeros of
                # an unreadable parse are never published alone
                counts = summary_counts
                face.face["counts"] = counts
                face.face["counts_note"] = (
                    "counts from INTEG_SUMMARY: per-scenario result lines "
                    "unrecognized in suite.log")
            elif header_counts is not None or summary_counts is not None:
                counts = header_counts or summary_counts  # header wins
                if counts is summary_counts:
                    face.face["counts"] = counts
            else:
                counts = None  # nothing readable anywhere: not a proof
            if summary_counts is not None and header_counts is not None \
                    and not lib_round_face.counts_agree(header_counts,
                                                        summary_counts):
                # the incident's exact family (face 0, log ran=1): a
                # disagreement is published, and green is NOT granted from
                # either side alone
                face.face["counts_note"] = (
                    "counts disagree: header=%s INTEG_SUMMARY=%s — green is "
                    "not granted from a disagreement"
                    % (header_counts, summary_counts))
            verdict = (lib_round_face.terminal_verdict(counts)
                       if counts is not None else "no_proof")
            if verdict == "green" and "counts disagree" in \
                    face.face.get("counts_note", ""):
                verdict = "no_proof"
            reason = ""
            if verdict == "no_proof":
                if counts is None:
                    reason = "counts unreadable — no proof"
                elif counts.get("ran", 0) <= 0:
                    reason = "no scenario ran (ran=0) — no proof"
                else:
                    reason = "green refused: %s" % face.face.get(
                        "counts_note", "")
            # the ledger's run id is the round's real identity — relabel the
            # retained evidence dir to it so face and ledger join 1:1
            run_id = header.get("id")
            if isinstance(run_id, str) and run_id.strip():
                try:
                    renamed = face.run_dir.with_name(run_id)
                    face.run_dir.rename(renamed)
                    face.run_dir = renamed
                    face.face["run_id"] = run_id
                except OSError:
                    pass  # keep the provisional dir; the face still lands
            face.retain_log(log_path)
            # t261024-30: the record's verdict rides the face — an env-red
            # face (the stricter rule) must never silently disagree with the
            # green record the engine certifies under.
            face.finish("done", verdict, reason,
                        record_verdict=lib_round_face.content_verdict(counts),
                        record_rule="content-v1")
            # the relative-certification caliber (261014): the fail NAME set,
            # so the engine can judge new-regressions-vs-main, not just counts
            if isinstance(header, dict):
                header["failed_names"] = failed_names(log_path)
                # published, never swallowed: the environment face of this round
                header["unverified_names"] = unverified_names(log_path)
        # 261023: the engine persists this header and mints the certification in ONE
        # block; when that block does not run, a green round leaves NO row in the
        # project ledger and can never be certified - measured twice today (face
        # fail=0, ledger empty, line stayed frozen). The runner therefore also writes
        # the row itself, idempotently by run id, into the project ledger the engine
        # reads. A duplicate is impossible: an id already present is left alone.
        try:
            _persist_run_row(header, env)
        except Exception as _e:  # noqa: BLE001 - never fails the round
            sys.stderr.write("run-row persist skipped: %s: %s\n"
                             % (type(_e).__name__, _e))
        sys.stdout.write(json.dumps(header, ensure_ascii=False) + "\n")
        sys.stdout.flush()
        return 0
    finally:
        _FACE_HOOK[0] = None
        if watcher_holder[0] is not None:
            watcher_holder[0].stop()
        state.retire()
        shutil.rmtree(run_root, ignore_errors=True)


def _choose_project(env, skip_run_id=None):
    """The project whose ledger this round belongs to (t261024-30: the ONE
    project-resolution rule, shared with the face fallback in ``run``).

    Returns (project_dir | None, already_recorded): the project under
    $SANDBAR_PROJECTS_DIR (else ~/.sandbar/projects) whose scenario-runs
    ledger already carries a ``lane:line-round`` row (that is where this
    round's predecessors were recorded); a single project is taken as-is.
    ``already_recorded`` is True when the ledger already carries
    ``skip_run_id`` — the caller must not duplicate the row. No project
    resolvable -> (None, False) with the named stderr line, never a guess
    into the wrong ledger."""
    import json as _json
    base = Path(str(env.get("SANDBAR_PROJECTS_DIR") or "").strip()
                or os.path.expanduser("~/.sandbar/projects"))
    cands = [p for p in base.iterdir() if p.is_dir()] if base.is_dir() else []
    chosen = None
    for proj in cands:
        ledger = proj / "ledger" / "scenario-runs.jsonl"
        if not ledger.exists():
            continue
        try:
            for line in ledger.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = _json.loads(line)
                if not isinstance(row, dict):
                    continue
                if skip_run_id is not None \
                        and row.get("id") == skip_run_id:
                    return proj, True   # already recorded - never duplicate
                if str(row.get("source") or "") == RUN_SOURCE:
                    chosen = proj
        except (OSError, ValueError):
            continue
    if chosen is None and len(cands) == 1:
        chosen = cands[0]
    if chosen is None:
        sys.stderr.write("line-round project unresolved: no project ledger "
                         "carries a %s row under %s\n" % (RUN_SOURCE, base))
    return chosen, False


def _persist_run_row(header, env):
    """Append this round's header to the project ledger, idempotently by run id.

    The engine persists the header and mints the certification in ONE block; when
    that block does not run, a green round leaves no row and can never be certified
    (measured twice on 261023: face fail=0, ledger empty, line stayed frozen). The
    runner therefore also writes the row itself.

    Which project: ``_choose_project`` (the one resolution rule — the face
    fallback in ``run`` uses the SAME answer, so a round whose run row lands
    can no longer be the round whose face directory never appeared).
    """
    import json as _json
    if not isinstance(header, dict) or not header.get("id"):
        return
    chosen, already = _choose_project(env, skip_run_id=header["id"])
    if already:
        return
    if chosen is None:
        return
    # 261023: the suite's own header carries the FACE rule (env_fail != 0 -> red).
    # The engine's run_verdict is what certifies and it keys on content: ran > 0 and
    # failed == 0 is GREEN (an unavailable environment is "unverified", not guilt).
    # Writing the face verdict verbatim poisoned the ledger with a red row for a
    # round that had failed=0 - measured, and corrected below. t261024-30: the
    # rule lives in ONE place (lib_round_face.content_verdict) and the row
    # NAMES the rule it used — a reader never has to guess which caliber a
    # stored verdict came from.
    import lib_round_face
    _cases = header.get("cases") or {}
    _counts = lib_round_face.normalize_summary_counts(_cases)
    header["verdict"] = lib_round_face.content_verdict(_counts) or "red"
    header["verdict_rule"] = "content-v1"
    path = chosen / "ledger" / "scenario-runs.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(_json.dumps(header, ensure_ascii=False) + "\n")


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
