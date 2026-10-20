#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t26101621_multirepo_agent_settle.py — t261016-21, the implement-stage
agent settle covers EVERY repo in a multi-repo lane, not just the lane root
(KI-01M52NS7A3290FBAWY1XYSBG0E).

intent (user words: "in a multi-repo lane the implement stage must settle
every repo, not just the lane root — the agent cannot commit by itself, and
today a person has to do it for every ticket"):
    A. THE INCIDENT CHAIN, POSITIVE: a multi-repo lane (manifest
       .sandbar/repo_worktrees.json: two member repos) where the agent
       dirtied one member tree and NEVER commits — after the implement-stage settle the receipt is read from
       the READER side (git, not the writer's ok): the member scope
       carries its own commit beyond base (svc-alpha), the dirty residue is gone
       in every tree, and the receipt NAMES the member scopes (including the
       quiet member that had nothing to land) instead of silence. Today this
       is RED: the single-tree settle lands only the lane root, members stay
       dirty, and the gate later reads "[<member>] 0 commits" — the named
       TDD signal; green required at the integration gate / merge.
    B. SINGLE-REPO BYTE IDENTITY (the regression witness): a single-repo
       lane (no manifest) settles exactly as before — one commit beyond
       base, the worktree clean, and the receipt carries NO scope tag (the
       old single-anchor wording, byte-level surface). Green today; must
       stay green.
    C. FAIL-CLOSED MANIFEST: a corrupt repo_worktrees.json is a NAMED
       RuntimeError, never a silent fallback to the single-repo anchor
       (settling/merging the wrong repo is worse than an error), and no
       member commit lands on the corrupt path.

Division of intent (no intent-level duplication):
  - per-scope commit counting, note aggregation, and hardening truth tables
    belong to developer L1 (in-ticket unit battery);
  - the join-point settle_lane per-scope anchoring belongs to
    t260907-06-multirepo-journey / t260901-16 T06;
  - the merge_check self-heal repo-anchor root cause is closed by the same
    one-line fix and judged by the L1 heal leg, not re-driven here (a full
    merge_check harness is out of proportion for the same user-visible
    promise: a member tree's dirt lands a commit).

Fixture: self-contained mini multi-repo project in tmp (git init + worktree
add, the real worktree registration face, no fakes); the real
server/engine/agent_activities.py is imported with temporalio stubs (the
t260901-16 T06 technique); REPO_ROOT is injected per fixture project.
Offline seconds, zero docker/Temporal-server/browser, never touches
3099/7233, never touches the real sandbar repo's git state.

Three states: git or the engine module missing = ENV_FAIL exit 2; A/C red
pre-implement = the named TDD signal; B red any time = a real regression.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import logging
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
NAME = "t261016-21-multirepo-agent-settle"

sys.path.insert(0, str(REPO / "integration"))
from lib_result import ScenarioCheck  # noqa: E402

_ck = ScenarioCheck(detail_cap=600, flush=True)
ok = _ck.ok
finish = _ck.finish
env_fail = _ck.env_fail

if shutil.which("git") is None:
    env_fail("git missing", "git not on PATH; the fixture needs real worktree registration")
# Engine-source override seam (forensics only): lets a reader point the scenario
# at another checkout (e.g. the pre-fix HEAD) to reproduce the red TDD signal.
SRC_ENGINE = Path(os.environ.get(
    "SANDBAR_SC_T26101621_ENGINE_SRC") or str(REPO / "server" / "engine"))
if not (SRC_ENGINE / "agent_activities.py").is_file():
    env_fail("engine module missing", str(SRC_ENGINE / "agent_activities.py"))


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd)] + list(args),
                          capture_output=True, text=True)


def _init_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    r = _git(path, "init", "-q", "-b", "main")
    if r.returncode != 0:
        env_fail("git init failed", r.stderr.strip()[:200])
    _git(path, "config", "user.email", "sc-t261016-21@example.invalid")
    _git(path, "config", "user.name", "sc-t261016-21 fixture")
    (path / "README.md").write_text("base\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "base")
    return path


def _add_worktree(repo, wt_path, branch):
    r = _git(repo, "worktree", "add", "-q", str(wt_path), "-b", branch)
    if r.returncode != 0:
        env_fail("worktree add failed", (r.stderr or r.stdout).strip()[:200])


class MultiFixture:
    """One self-contained multi-repo project: two member repos born at the
    project root, a lane container holding one registered worktree per
    member, and the manifest declaring the two scopes (the KI's real shape —
    the lane container itself is NOT a worktree: nesting member worktrees
    inside a root-repo worktree trips the production gitlink guard, which is
    correct engine behavior, not this scenario's subject)."""

    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="sc-t261016-21-"))
        self.lane = self.root / ".lane" / "t261016-21"
        self.svc = _init_repo(self.root / "svc-alpha")
        self.lib = _init_repo(self.root / "lib-zeta")
        (self.svc / "src").mkdir()
        (self.svc / "src" / "app.py").write_text("v1\n", encoding="utf-8")
        _git(self.svc, "add", "-A")
        _git(self.svc, "commit", "-q", "-m", "svc base")
        _add_worktree(self.svc, self.lane / "svc-alpha", "lane/tk21-svc-alpha")
        _add_worktree(self.lib, self.lane / "lib-zeta", "lane/tk21-lib-zeta")
        mf = self.lane / ".sandbar"
        mf.mkdir(parents=True, exist_ok=True)
        (mf / "repo_worktrees.json").write_text(json.dumps([
            {"name": "svc-alpha", "repo": "svc-alpha", "branch": "lane/tk21-svc-alpha", "base_ref": "main"},
            {"name": "lib-zeta", "repo": "lib-zeta", "branch": "lane/tk21-lib-zeta", "base_ref": "main"},
        ]), encoding="utf-8")

    def dirty(self, rel, text):
        p = self.lane / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def commits_beyond_base(self, repo_rel, branch, base="main"):
        r = _git(self.root / repo_rel,
                 "rev-list", "--count", "%s..%s" % (base, branch))
        try:
            return int(r.stdout.strip())
        except ValueError:
            return -1

    def dirty_files(self, repo_rel):
        # Reader side = the LANE WORKTREE (the face the gate and a human see),
        # never the writer receipt and never the member repo checkout.
        r = _git(self.lane / repo_rel,
                 "status", "--porcelain")
        return [ln for ln in r.stdout.splitlines() if ln.strip()]

    def cleanup(self):
        for repo in (self.svc, self.lib):
            _git(repo, "worktree", "remove", "--force", str(self.lane))
            _git(repo, "worktree", "prune")
        shutil.rmtree(self.root, ignore_errors=True)


class SingleFixture:
    """A single-repo project: one repo, one worktree lane, NO manifest — the
    byte-identity witness."""

    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="sc-t261016-21-single-"))
        _init_repo(self.root)
        self.lane = self.root / ".worktrees" / "tk21-single"
        _add_worktree(self.root, self.lane, "lane/tk21-single")

    def cleanup(self):
        _git(self.root, "worktree", "remove", "--force", str(self.lane))
        _git(self.root, "worktree", "prune")
        shutil.rmtree(self.root, ignore_errors=True)


# ---- import the real engine module with temporalio stubs (T06 technique) ----
try:
    _mod = types.ModuleType("temporalio")
    _act = types.ModuleType("temporalio.activity")

    def _defn(fn=None, **kw):
        def d(f):
            return f
        return d(fn) if fn else d

    _act.defn = _defn
    _act.logger = logging.getLogger("stub")
    sys.modules["temporalio"] = _mod
    sys.modules["temporalio.activity"] = _act
    sys.path.insert(0, str(SRC_ENGINE))
    sys.path.insert(0, str(SRC_ENGINE.parent))
    sys.path.insert(0, str(REPO / "server" / "tools"))
    import agent_activities as aa  # noqa: E402
except Exception as e:  # noqa: BLE001
    env_fail("engine module unimportable", "%s: %s" % (type(e).__name__, e))
    sys.exit(2)

from types import SimpleNamespace  # noqa: E402


def _stage_args(write_set, base_ref="main"):
    """The declared AgentStageArgs input shape, fed as data (grey-box: only
    the fields _settle_with_gate consumes are provided)."""
    return SimpleNamespace(
        ticket_id="t261016-21", stage_id="implement", gen=0,
        write_set=list(write_set), base_ref=base_ref,
        path_gate=False, path_gate_rules={}, authorizations=[])


fx = MultiFixture()
single = SingleFixture()
_orig_root = aa.REPO_ROOT
try:
    # ---- A: the incident chain — agent dirties a member tree, never commits ----
    aa.REPO_ROOT = fx.root
    fx.dirty("svc-alpha/src/app.py", "v2 agent edit\n")
    note = aa._settle_with_gate(_stage_args(
        ["svc-alpha/src/app.py", "lib-zeta/lib/z.py"]), fx.lane)
    note = note or ""
    ok(fx.commits_beyond_base("svc-alpha", "lane/tk21-svc-alpha") >= 1,
       "A1 the MEMBER scope carries its own commit beyond base (the incident "
       "shape '0 commits + dirty worktree' is gone)",
       "svc-alpha commits beyond main: %d" % fx.commits_beyond_base("svc-alpha", "lane/tk21-svc-alpha"))
    ok(not fx.dirty_files("svc-alpha"),
       "A2 the member tree is CLEAN after the settle (no human hand-holding)",
       "svc-alpha residue: %r" % fx.dirty_files("svc-alpha"))
    ok("svc-alpha" in note,
       "A3 the receipt NAMES the landed member scope (reader can see per-scope "
       "fate, not one silent single-tree line)",
       "note: %r" % note[:300])
    ok("lib-zeta" in note,
       "A4 the QUIET member (nothing to land) is named too, never dropped "
       "from the receipt",
       "note: %r" % note[:300])
    landed = _git(fx.lane / "svc-alpha", "show", "HEAD:src/app.py")
    ok(landed.returncode == 0 and "v2 agent edit" in landed.stdout,
       "A5 the member commit carries the agent's CONTENT (not an empty token commit)",
       "show rc=%d out=%r" % (landed.returncode, landed.stdout[:80]))
    ok(fx.commits_beyond_base("lib-zeta", "lane/tk21-lib-zeta") == 0,
       "A6 the quiet member gets NO empty filler commit (a no-op scope stays a no-op)",
       "lib-zeta commits beyond main: %d" % fx.commits_beyond_base("lib-zeta", "lane/tk21-lib-zeta"))

    # ---- B: single-repo byte identity ----
    aa.REPO_ROOT = single.root
    (single.lane / "app.py").write_text("single-repo agent edit\n", encoding="utf-8")
    note_b = aa._settle_with_gate(_stage_args(["app.py"]), single.lane)
    note_b = note_b or ""
    rc = _git(single.root, "rev-list", "--count", "main..lane/tk21-single")
    ok(rc.stdout.strip() == "1",
       "B1 a single-repo lane lands EXACTLY ONE commit (old behavior, unchanged)",
       "commits beyond main: %r" % rc.stdout.strip())
    ok(not note_b.strip().startswith("["),
       "B2 the single-repo receipt carries NO scope tag (the old single-anchor "
       "wording, byte-level surface)",
       "note: %r" % note_b[:200])
    st = _git(single.lane, "status", "--porcelain")
    ok(not st.stdout.strip(),
       "B3 the single-repo worktree is clean (same as ever)",
       "residue: %r" % st.stdout[:120])

    # ---- C: corrupt manifest = named RuntimeError, fail-closed ----
    fx2 = MultiFixture()
    try:
        aa.REPO_ROOT = fx2.root
        (fx2.lane / ".sandbar" / "repo_worktrees.json").write_text(
            "{ not json", encoding="utf-8")
        raised = None
        try:
            aa._settle_with_gate(_stage_args(["anything.md"]), fx2.lane)
        except RuntimeError as e:
            raised = str(e)
        ok(raised is not None and "manifest" in raised.lower(),
           "C1 a corrupt manifest is a NAMED RuntimeError (never a silent "
           "fallback to the single-repo anchor)",
           "raised: %r" % (raised or "(no exception — fell through silently)"))
        ok(fx2.commits_beyond_base("svc-alpha", "lane/tk21-svc-alpha") == 0,
           "C2 nothing landed on any member under the corrupt manifest "
           "(fail-closed, not settle-the-wrong-repo)",
           "svc-alpha commits beyond main: %d"
           % fx2.commits_beyond_base("svc-alpha", "lane/tk21-svc-alpha"))
    finally:
        fx2.cleanup()
finally:
    aa.REPO_ROOT = _orig_root
    fx.cleanup()
    single.cleanup()

finish(NAME)
