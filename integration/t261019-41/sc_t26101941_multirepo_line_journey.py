#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_t26101941_multirepo_line_journey.py — t261019-41, the multi-repository
develop-line journey: a ticket lands on a line that declares TWO repositories,
gets certified, and gets promoted — and every refusal moves NOTHING.

intent (host ruling 261019 a2, REQUIRED OUTCOME 1-4, user-visible contract):
    A. LAND, ALL DECLARED REPOS OR NONE: a ticket whose lane carries two
       member repos lands on a line declaring both — one landing row whose
       `repos` names BOTH repos with their post-landing revisions, and each
       repo realises its OWN declared branch. A `repo_proven` map that does
       not cover exactly the declared repo set is a named refusal BEFORE
       anything moves (no landing row, no line branch created). Today this
       whole leg is RED: land_to_line refuses every multi-repository line
       by name ("the per-ticket landing wires the single-repository phase")
       — the named TDD signal; green required at the integration gate/merge.
    B. CERTIFY THE SAME REPO SET: the certification read back from the
       delivery ledger names EVERY declared repo with the landing revision.
    C. PROMOTE EVERY REPO OR NONE: with repo B's main made NOT
       fast-forwardable, the promotion refuses BY NAME and repo A's main
       does NOT move (validate before act — a partial delivery is
       impossible); with the divergence removed, the same promotion
       fast-forwards BOTH mains and the row records main_before/main_after
       per repo.
    F. SINGLE-REPO BYTE IDENTITY: a one-repo line still lands exactly as
       before (one landing row, one repo) — the a1 default behavior the
       ruling freezes.

Division of intent (no intent-level duplication):
  - the multi-repo ACT truth table (missing/extra proven, corrupt manifest,
    pin ordering, act-phase promotion rollback) belongs to developer L1
    (test_t261019_41_multirepo_line_acts.py);
  - the implement-stage settle across member scopes belongs to
    t261016-21-multirepo-agent-settle;
  - single-repo landing/pin/refusal matrices belong to
    test_t261009_46_lane_version_optin (L1) and the existing line scenarios;
  - THIS entry uniquely owns the two-repo JOURNEY end to end: land ->
    certify -> promote -> nothing-moves refusals, judged from the reader
    side (git refs and the delivery ledger on disk, never writer receipts).

Fixture: self-contained two-repo project in a reclaimed tmp dir — two member
git repos, a lane container (NOT itself a repo, the production shape) with
member worktrees and a repo_worktrees.json manifest, a per-project store via
SANDBAR_PROJECTS_DIR, lines.json declaring the two-repo line. The REAL engine
modules are imported with temporalio stubs (the t260901-16 T06 technique).
Offline seconds, zero docker/Temporal-server/browser, never touches
3099/7233, never touches the real sandbar repo's git state.

Three states: git or the engine module missing = ENV_FAIL exit 2; A-D red
pre-implement = the named TDD signal; F red any time = a real regression.
"""
import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
NAME = "t261019-41-multirepo-line-journey"

sys.path.insert(0, str(REPO / "integration"))
from lib_result import ScenarioCheck  # noqa: E402

_ck = ScenarioCheck(detail_cap=600, flush=True)
ok = _ck.ok
finish = _ck.finish
env_fail = _ck.env_fail

if shutil.which("git") is None:
    env_fail("git missing", "git not on PATH; the fixture needs real worktrees")
SRC_ENGINE = Path(os.environ.get(
    "SANDBAR_SC_T26101941_ENGINE_SRC") or str(REPO / "server" / "engine"))
if not (SRC_ENGINE / "agent_activities.py").is_file():
    env_fail("engine module missing", str(SRC_ENGINE / "agent_activities.py"))

PROJECT = "t41proj"
TICKET = "t261019-41"
LINE = "dev"


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd)] + list(args),
                          capture_output=True, text=True)


def _rev(cwd, ref):
    r = _git(cwd, "rev-parse", "--verify", ref)
    return r.stdout.strip() if r.returncode == 0 else ""


def _init_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    r = _git(path, "init", "-q", "-b", "main")
    if r.returncode != 0:
        env_fail("git init failed", r.stderr.strip()[:200])
    _git(path, "config", "user.email", "sc-t261019-41@example.invalid")
    _git(path, "config", "user.name", "sc-t261019-41 fixture")
    (path / "README.md").write_text("base\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "base")
    return path


def _add_worktree(repo, wt_path, branch):
    r = _git(repo, "worktree", "add", "-q", str(wt_path), "-b", branch)
    if r.returncode != 0:
        env_fail("worktree add failed", (r.stderr or r.stdout).strip()[:200])


class LineFixture:
    """One self-contained two-repo project: two member repos, a lane container
    holding one registered worktree per member plus the multi-repo manifest,
    and the project store (SANDBAR_PROJECTS_DIR) declaring the two-repo line.
    The lane container itself is NOT a worktree (the production shape — the
    t261016-21 fixture's gitlink lesson)."""

    def __init__(self, single=False):
        prefix = "sc-t261019-41-single-" if single else "sc-t261019-41-"
        self.root = Path(tempfile.mkdtemp(prefix=prefix))
        self.single = single
        self.projects = self.root / "projects"
        self.lane = self.root / ".lane" / "t261019-41"
        if single:
            self.alpha = _init_repo(self.root / "solo")
            self.lane = self.root / ".lane" / "t261019-41-solo"
            _add_worktree(self.alpha, self.lane / "solo", "lane/t41-solo")
            repos = [{"name": "solo", "branch": "line/solo"}]
        else:
            self.alpha = _init_repo(self.root / "alpha")
            self.beta = _init_repo(self.root / "beta")
            (self.alpha / "src").mkdir()
            (self.alpha / "src" / "app.py").write_text("v1\n", encoding="utf-8")
            _git(self.alpha, "add", "-A")
            _git(self.alpha, "commit", "-q", "-m", "alpha base")
            (self.beta / "lib").mkdir()
            (self.beta / "lib" / "z.py").write_text("v1\n", encoding="utf-8")
            _git(self.beta, "add", "-A")
            _git(self.beta, "commit", "-q", "-m", "beta base")
            _add_worktree(self.alpha, self.lane / "alpha", "lane/t41-alpha")
            _add_worktree(self.beta, self.lane / "beta", "lane/t41-beta")
            dot = self.lane / ".sandbar"   # 261020: the retired name is banned in new code (naming gate A); the engine coordination dir is .sandbar
            dot.mkdir(parents=True, exist_ok=True)
            (dot / "repo_worktrees.json").write_text(json.dumps([
                {"name": "alpha", "repo": "alpha", "branch": "lane/t41-alpha",
                 "base_ref": "main"},
                {"name": "beta", "repo": "beta", "branch": "lane/t41-beta",
                 "base_ref": "main"},
            ]), encoding="utf-8")
            repos = [{"name": "alpha", "branch": "line/alpha"},
                     {"name": "beta", "branch": "line/beta"}]
        develop = self.projects / PROJECT / "data" / "develop"
        develop.mkdir(parents=True, exist_ok=True)
        (develop / "lines.json").write_text(json.dumps([
            {"version": 1, "line_id": LINE, "scope": "t41", "owner": "host",
             "repositories": repos}]), encoding="utf-8")
        # The delivery-ledger root: develop_dir reads SANDBAR_PROJECTS_DIR
        # fresh per call, but ledger_path prefers a process pin and only an
        # unpinned process falls back to env — so the fixture drives the
        # flat-dir env channel (SANDBAR_DELIVERY_LEDGER_DIR, read per call)
        # instead of relying on import order.
        os.environ["SANDBAR_DELIVERY_LEDGER_DIR"] = str(self.root / "ledger")

    def member(self, name):
        return self.alpha if (self.single or name == "alpha") else self.beta

    def lane_member(self, name):
        return self.lane / (name if not self.single else "solo")

    def lane_commit(self, name, rel, text):
        wt = self.lane_member(name)
        p = wt / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        _git(wt, "add", "-A")
        r = _git(wt, "commit", "-q", "-m", "lane work %s" % name)
        if r.returncode != 0:
            env_fail("fixture lane commit failed", r.stderr.strip()[:200])
        return _rev(wt, "HEAD")

    def main_sha(self, name):
        return _rev(self.member(name), "refs/heads/main")

    def branch_sha(self, name):
        branch = "line/solo" if self.single else "line/%s" % name
        return _rev(self.member(name), "refs/heads/%s" % branch)

    def diverge_main(self, name="beta"):
        repo = self.member(name)
        r = _git(repo, "rev-parse", "--verify", "refs/heads/main")
        if r.returncode != 0:
            env_fail("fixture diverge failed", "no main in %s" % name)
        (repo / "DIVERSION.md").write_text("divergent\n", encoding="utf-8")
        cur = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        _git(repo, "checkout", "-q", "main")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "divergent main commit")
        sha = _rev(repo, "refs/heads/main")
        _git(repo, "checkout", "-q", cur)
        return sha

    def cleanup(self):
        for name in ([("solo")] if self.single else ["alpha", "beta"]):
            _git(self.member(name), "worktree", "remove", "--force",
                 str(self.lane_member(name)))
            _git(self.member(name), "worktree", "prune")
        shutil.rmtree(self.root, ignore_errors=True)


# ---- import the real engine modules with temporalio stubs (T06 technique) ----
_orig_projects = os.environ.get("SANDBAR_PROJECTS_DIR")
try:
    _mod = types.ModuleType("temporalio")
    _act = types.ModuleType("temporalio.activity")

    def _defn(fn=None, **kw):
        def d(f):
            return f
        return d(fn) if fn else d

    _act.defn = _defn
    _act.logger = logging.getLogger("stub")
    _wf = types.ModuleType("temporalio.workflow")
    _wf.defn = _defn
    sys.modules["temporalio"] = _mod
    sys.modules["temporalio.activity"] = _act
    sys.modules["temporalio.workflow"] = _wf
    sys.path.insert(0, str(SRC_ENGINE))
    sys.path.insert(0, str(SRC_ENGINE.parent))
    import agent_activities as aa  # noqa: E402
    import develop_line as dl  # noqa: E402
    import develop_certify as dc  # noqa: E402
    import develop_promote as dp  # noqa: E402
except Exception as e:  # noqa: BLE001
    env_fail("engine module unimportable", "%s: %s" % (type(e).__name__, e))
    sys.exit(2)


def _rows(fx):
    rows, bad = dc.read_rows(dc.ledger_path(PROJECT))
    return rows, bad


def _landings(fx, ticket=TICKET):
    rows, bad = _rows(fx)
    return [r for r in rows if r.get("kind") == dc.KIND_LANDING
            and r.get("ticket") == ticket and r.get("line") == LINE]


def _land(fx, repo_proven):
    if fx.single:
        args = aa.LandToLineArgs(
            ticket_id=TICKET, project_key=PROJECT, line_id=LINE,
            worktree=str(fx.lane_member("solo")),
            proven_sha=_rev(fx.lane_member("solo"), "HEAD"))
    else:
        args = aa.LandToLineArgs(
            ticket_id=TICKET, project_key=PROJECT, line_id=LINE,
            worktree=str(fx.lane), proven_sha="", repo_proven=repo_proven)
    return asyncio.run(aa.land_to_line(args))


def _append_green_cert(fx, run_id):
    land = _landings(fx)[-1]
    cand = [{"repo": r["repo"], "revision": r["revision"]}
            for r in land.get("repos", [])]
    row = dc.build_certification(
        cand, {"id": run_id, "cases": {"ran": 3}}, booked_red="none",
        judged_by="sc-t261019-41", line=LINE)
    dc.append_rows([row], dc.ledger_path(PROJECT))
    runs = fx.projects / PROJECT / "ledger" / "scenario-runs.jsonl"
    runs.parent.mkdir(parents=True, exist_ok=True)
    with open(runs, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"id": run_id, "verdict": "green"}) + "\n")
    return row


fx = LineFixture()
try:
    os.environ["SANDBAR_PROJECTS_DIR"] = str(fx.projects)

    # ---- D (first, so nothing has moved yet): incomplete proven map refuses ----
    sha_a = fx.lane_commit("alpha", "src/feature.py", "feature alpha\n")
    res_d = _land(fx, {"alpha": sha_a})
    ok(res_d.ok is False,
       "D1 a proven map MISSING a declared repo is refused (per-repo proven "
       "anchoring is declared, never assumed)",
       "ok=%r err=%r" % (res_d.ok, (res_d.error or "")[:200]))
    ok("beta" in (res_d.error or ""),
       "D2 the refusal NAMES the uncovered repository",
       "err=%r" % (res_d.error or "")[:200])
    ok(not _landings(fx),
       "D3 no landing row exists after the refusal (nothing landed)",
       "rows=%r" % [r.get("id") for r in _landings(fx)])
    ok(fx.branch_sha("alpha") == "" and fx.branch_sha("beta") == "",
       "D4 no line branch was created by the refusal (nothing moved)",
       "line/alpha=%r line/beta=%r"
       % (fx.branch_sha("alpha"), fx.branch_sha("beta")))

    # ---- A: the journey's landing act, both repos ----
    sha_b = fx.lane_commit("beta", "lib/w.py", "feature beta\n")
    res_a = _land(fx, {"alpha": sha_a, "beta": sha_b})
    ok(res_a.ok is True,
       "A1 a two-repository line LANDS both declared repos through the same "
       "act (today RED: every multi-repo line refuses by name — the named "
       "TDD signal)",
       "ok=%r err=%r" % (res_a.ok, (res_a.error or "")[:250]))
    lands = _landings(fx)
    ok(len(lands) == 1,
       "A2 exactly ONE landing row carries the ticket",
       "rows=%r" % [r.get("id") for r in lands])
    repos = {r.get("repo"): r.get("revision")
             for r in (lands[0].get("repos", []) if lands else [])}
    ok(repos.get("alpha") and repos.get("beta"),
       "A3 the landing row NAMES BOTH repos with revisions (the record model "
       "is multi-repo end to end)",
       "repos=%r" % repos)
    ok(fx.branch_sha("alpha") == repos.get("alpha"),
       "A4 repo alpha realised its OWN declared branch line/alpha at the "
       "landed revision (per-repo branch honoured)",
       "line/alpha=%r" % fx.branch_sha("alpha"))
    ok(fx.branch_sha("beta") == repos.get("beta"),
       "A5 repo beta realised its OWN declared branch line/beta at the "
       "landed revision",
       "line/beta=%r" % fx.branch_sha("beta"))

    # ---- B: certification follows the same repository set ----
    cert = _append_green_cert(fx, "run-t41-green")
    cert_repos = {r.get("repo"): r.get("revision")
                  for r in cert.get("repos", [])}
    ok(cert_repos.get("alpha") == repos.get("alpha")
       and cert_repos.get("beta") == repos.get("beta"),
       "B1 the certification names EVERY declared repo at its landing "
       "revision (cert and landing share one repository set)",
       "cert repos=%r" % cert_repos)

    # ---- C: promotion — every repo or none ----
    before_a, before_b = fx.main_sha("alpha"), fx.main_sha("beta")
    div = fx.diverge_main("beta")
    beta_at_refusal = fx.main_sha("beta")  # where the divergence left it
    refused = None
    try:
        dp.promote_buffer(PROJECT, LINE, signer="host")
    except dp.PromotionRefused as e:
        refused = str(e)
    ok(refused is not None and "beta" in refused,
       "C1 a promotion where ONE repo cannot fast-forward refuses BY NAME",
       "refused=%r" % (refused or "(no refusal — promotion proceeded)"))
    ok(fx.main_sha("alpha") == before_a,
       "C2 repo alpha's main did NOT move under the refused promotion "
       "(a partial delivery is impossible)",
       "alpha main=%r before=%r" % (fx.main_sha("alpha"), before_a))
    ok(fx.main_sha("beta") == beta_at_refusal,
       "C3 repo beta's main did not move PAST its divergence under the "
       "refused promotion (nothing delivered)",
       "beta main=%r at_refusal=%r" % (fx.main_sha("beta"), beta_at_refusal))
    rows_now, _ = _rows(fx)
    promos = [r for r in rows_now if r.get("kind") == dc.KIND_PROMOTION]
    ok(not promos,
       "C4 no promotion row was appended by the refused act",
       "promo rows=%r" % [r.get("id") for r in promos])

    # remove the divergence: beta main back to its promoted base
    _git(fx.beta, "update-ref", "refs/heads/main", before_b)
    _git(fx.beta, "reset", "-q", "--hard")
    promo = dp.promote_buffer(PROJECT, LINE, signer="host")
    ok(fx.main_sha("alpha") == repos.get("alpha"),
       "C5 the promotion fast-forwards repo alpha's main to the certified "
       "revision (reader side: the real ref)",
       "alpha main=%r want=%r" % (fx.main_sha("alpha"), repos.get("alpha")))
    ok(fx.main_sha("beta") == repos.get("beta"),
       "C6 the promotion fast-forwards repo beta's main too (every repo "
       "moves together)",
       "beta main=%r want=%r" % (fx.main_sha("beta"), repos.get("beta")))
    mb = {r.get("repo"): r.get("revision") for r in promo.get("main_before", [])}
    ma = {r.get("repo"): r.get("revision") for r in promo.get("main_after", [])}
    ok(mb.get("alpha") == before_a and mb.get("beta") == before_b
       and ma.get("alpha") == repos.get("alpha")
       and ma.get("beta") == repos.get("beta"),
       "C7 the promotion row records main_before/main_after PER REPO (the "
       "audit face covers the whole repository set)",
       "before=%r after=%r" % (mb, ma))
finally:
    os.environ.pop("SANDBAR_DELIVERY_LEDGER_DIR", None)
    if _orig_projects is None:
        os.environ.pop("SANDBAR_PROJECTS_DIR", None)
    else:
        os.environ["SANDBAR_PROJECTS_DIR"] = _orig_projects
    fx.cleanup()

# ---- F: single-repo byte identity (the a1 default the ruling freezes) ----
single = LineFixture(single=True)
try:
    os.environ["SANDBAR_PROJECTS_DIR"] = str(single.projects)
    single.lane_commit("solo", "app.py", "solo feature\n")
    res_f = _land(single, {})
    ok(res_f.ok is True,
       "F1 a single-repository line still lands exactly as before (the a1 "
       "default behavior is byte-identical)",
       "ok=%r err=%r" % (res_f.ok, (res_f.error or "")[:200]))
    slands = _landings(single)
    ok(len(slands) == 1 and len(slands[0].get("repos", [])) == 1
       and slands[0]["repos"][0].get("repo") == "solo",
       "F2 the single-repo landing row carries exactly ONE repository (old "
       "record shape unchanged)",
       "repos=%r" % (slands[0].get("repos") if slands else None))
finally:
    os.environ.pop("SANDBAR_DELIVERY_LEDGER_DIR", None)
    if _orig_projects is None:
        os.environ.pop("SANDBAR_PROJECTS_DIR", None)
    else:
        os.environ["SANDBAR_PROJECTS_DIR"] = _orig_projects
    single.cleanup()

finish(NAME)
