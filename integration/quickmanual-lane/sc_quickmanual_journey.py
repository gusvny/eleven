#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_quickmanual_journey.py — quickmanual lane end-to-end journey (t261019-32).

intent (the user-perceivable behavior of the quickmanual lane, design doc
docs/design/quickmanual-lane-v1.md, host ruling 261019):

  J1. EXPLICIT creation: a quick ticket starts only through an explicit
      template_id=quickmanual-lane on the ordinary create face. No agent is ever
      dispatched for it: the stub brain's ledger (the only observation face of what
      agents actually receive) stays EMPTY for the whole journey — open, work and
      every later stage dispatch nobody (this is what separates the lane from both
      the dev lane and the light lane). The template is startable in the journey's
      world through the FIXTURE REGISTRATION SEAM: the fixture project declares
      workflow_modules=qm_fixture_template.py (the sanctioned project-external
      loader, t260924-04 contract), which registers the shipped class for the
      fixture project ONLY - the production creation face stays fail-closed until
      the step-0 host amendment (workflows_v2 + generated yaml, outside this
      lane).
  J2. EVIDENCE IS MANDATORY: a ticket created WITHOUT an evidence declaration (or
      with a malformed one — unknown kind, empty name) is blocked at `open` with a
      named remedy, never waved through.
  J3. THE WORK STAGE IS A SESSION, NOT AN AGENT: the healthy ticket parks at
      `work`; while parked the timeline does not churn (no polling loop, no history
      burn — the failure mode that killed t261019-18: 'Workflow history count
      exceeds limit' from a 5-second re-poll with no backoff, fixed in 256ef448).
      The scenario itself plays the session: it writes one file inside the declared
      write set in the lane worktree and signals done with its session id + role.
  J4. IDENTITY: the signal intake refuses a session-less done signal (a named
      refusal, the ticket stays parked); a valid signal lands the session id and
      its role on the ticket face — a reader can say WHO worked, never a borrowed
      role name.
  J5. THE ORDINARY PATH: after work-done the EXISTING settle/disposal path commits
      the work (the lane branch gains a commit), the existing run_integration_tests
      and merge_check gates run against the project-declared integration command
      (the fixture registry's scenario names appear in the gate ledger — only a real
      executor reading a real registry can produce them), and the ticket reaches the
      human merge gate through the existing landing path. No arbitrate stage, ever.
  J6. NO SELF-SIGNED GATE: signing the merge with the working session's own id is
      REFUSED with a named reason and the ticket stays awaiting-human; signing as
      the executor closes the ticket and tears the lane down (archive before
      teardown, the same closing batch as every other lane).

Grey-box statement: assertions land only on public faces — client.py structured
receipts, ticket-query snapshot keys (stage/stage_state/blocked_reason/blocked_
detail/timeline/handoffs/meta), the fixture repo's git end state, the scenario's own
stub/gate ledgers. No engine-private imports, no implementation-name anchors, no
full-sentence text anchors.

Topology and isolation (light-lane journey precedent): stage = stage_docker
temporal-only throwaway stage (in-band random ports, production port set hard-
forbidden incl. 3099); the chain under test = real QuickmanualLaneWorkflow + real
activities inside a worker spawned from a --depth 1 clone of this repo (fixture
repo), with the working tree's server/engine + server/workflows overlaid file by
file and byte-compared (the fixture runs the code under test, not HEAD); the lane's
integration declaration reuses integration/t260913-03/lib_pool_exclude_lane
.build_lane (real executor + mini registry + minimal verify.yaml), declaration byte-
identical to the main repo's. All subprocess env strips the lane-worker marker trio
and pins queue/namespace/registry; ledgers live in scenario-private tmp.

Resource lifecycle: every spawned worker is TERM'ed then KILL'ed in finally and
re-checked after teardown; the stage is torn down; tmp is reclaimed (keep switch:
SANDBAR_QMLE2E_KEEP_TMP=1).

Three states: docker / image / stage or engine venv missing = print `ENV_FAIL: ...`
and exit 2; a broken assertion = exit 1; all green = exit 0. Pre-implement red is
the expected TDD signal; must be green at arbitrate/merge.

Usage: python3 integration/quickmanual-lane/sc_quickmanual_journey.py
"""
import atexit
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
INTEG = os.path.dirname(HERE)
REPO = os.path.dirname(INTEG)
sys.path.insert(0, INTEG)
sys.path.insert(0, os.path.join(INTEG, "t260904-02"))
sys.path.insert(0, os.path.join(INTEG, "t260913-03"))
from lib_gate import (Fail, accepted, parse_out_json, poc_python,  # noqa: E402
                      require_bench, require_stage, run_poc_client, stage_down)
from lib_pool_exclude_lane import build_lane  # noqa: E402
import stage_docker  # noqa: E402

LANE_MARKERS = ("SANDBAR_TASK_QUEUE", "SANDBAR_TASK_QUEUES", "SANDBAR_WATCH_WORKFLOW")
PROJECT_KEY = "quickmanual-e2e"
TID = "quickmanual-%d" % os.getpid()                 # healthy journey ticket
TID_NOEV = "quickmanual-noev-%d" % os.getpid()       # evidence-mandatory ticket
SESSION = "e2e-session-host-01"
SESSION_ROLE = "host"
WRITE_FILE = "QUICKMANUAL_PROBE.md"
GATE_NAMES = ("qm-fixture-alpha", "qm-fixture-beta", "qm-fixture-gamma")
EXCLUDED_STAGES = ("create_plan", "review_plan", "design_integration_tests",
                   "arbitrate", "acceptance_walkthrough", "implement", "ui_evidence")
G = {"tmp": "", "fixture": "", "projects": "", "ctl": "", "gate_ledger": "",
     "stub_ledger": "", "stub": "", "workers": [], "all_workers": []}

STUB_SRC = r'''
import json, os, re, sys, time
prompt = sys.argv[-1] if len(sys.argv) > 1 else ""
m = re.search(r"stage: ([a-z_]+)", prompt)
stage = m.group(1) if m else "unknown"
mt = re.search(r"ticket (\S+)", prompt)
ticket = mt.group(1) if mt else "unknown"
led = os.environ.get("QM_STUB_LEDGER") or ""
if led:
    with open(led, "a", encoding="utf-8") as f:
        f.write(json.dumps({"stage": stage, "ticket": ticket, "ts": time.time()},
                           ensure_ascii=False) + "\n")
m = re.search(r"result file (\S+?\.json)", prompt)
if m:
    with open(m.group(1), "w", encoding="utf-8") as f:
        json.dump({"status": "ok",
                   "summary": "[qm-e2e stub] %s" % stage,
                   "report": "[qm-e2e stub] %s" % stage,
                   "deliverables": [], "files_changed": [],
                   "evidence": "qm-e2e stub"}, f, ensure_ascii=False)
'''

PROBE_SRC = r'''
import json, os, sys
NAME = "<<NAME>>"
LED = "<<LED>>"
try:
    with open(LED, "a", encoding="utf-8") as f:
        f.write(json.dumps({"name": NAME, "cwd": os.getcwd(), "ts": 0},
                           ensure_ascii=False) + "\n")
except OSError:
    pass
sys.exit(0)
'''


def env_for(stage, extra=None):
    """Subprocess env single point: strip lane markers, pin stage address /
    namespace / fixture registry, isolate ledgers, declare caller identity."""
    env = dict(os.environ)
    for k in LANE_MARKERS:
        env.pop(k, None)
    env["SANDBAR_TARGET_HOST"] = "127.0.0.1:%d" % stage["ports"]["temporal"]
    env["SANDBAR_NAMESPACE"] = stage["namespace"]
    env["SANDBAR_PROJECTS_DIR"] = G["projects"]
    env["SANDBAR_CALLER_PROJECT"] = PROJECT_KEY
    env["SANDBAR_SCENARIO_LEDGER_DIR"] = os.path.join(G["tmp"], "scenario-ledger")
    env["SANDBAR_EVENT_LEDGER_DIR"] = os.path.join(G["tmp"], "event-ledger")
    env["SANDBAR_LEDGER_REUSE"] = "0"
    # 261023: the ticket's inner integration gate is a NESTED suite run. When this
    # case is launched by the executor, the outer run owns SANDBAR_INTEG_RUN_LOCK_PATH,
    # the nested run inherits it, refuses as "a run is already in progress" and the
    # gate reports 0 ran / 0 passed / 0 failed / 0 env_fail - which the ticket reads as
    # a RED gate and never reaches the human merge gate. Reproduced by holding the lock
    # and running this case directly (same two J5 failures). The fixture gets its OWN
    # lock so the outer round cannot decide the lane's gate.
    env["SANDBAR_INTEG_RUN_LOCK_PATH"] = os.path.join(G["tmp"], "gate-run.lock")
    env["QM_STUB_LEDGER"] = G["stub_ledger"]
    if extra:
        env.update(extra)
    return env


# SANCTIONED-WAIT: bounded subprocess client-call timeout, not a state wait
def cli(py, stage, sub, args, extra=None, timeout=180):
    rc, out = run_poc_client(py, sub, args, env_for(stage, extra), timeout=timeout)
    return parse_out_json(out)


def wait_snap(fail, py, stage, tid, pred, label, deadline_s):
    t0 = time.time()
    last = {}
    while time.time() - t0 < deadline_s:
        r = cli(py, stage, "ticket-query", {"ticket_id": tid})
        snap = ((r.get("result") or {}).get("snapshot") or {})
        if snap:
            last = snap
            if pred(snap):
                return snap
        time.sleep(2)
    fail.check(False, "%s (not reached within %ds; last stage=%s/%s blocked=%r)"
               % (label, deadline_s, last.get("stage"), last.get("stage_state"),
                  str(last.get("blocked_reason") or "")[:160]))
    return None


def read_jsonl(path):
    rows = []
    if not os.path.isfile(path):
        return rows
    with open(path, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                rows.append(json.loads(ln))
            except ValueError:
                rows.append({"raw": ln})
    return rows


def stub_stages_of(tid):
    return [r.get("stage") for r in read_jsonl(G["stub_ledger"])
            if r.get("ticket") == tid]


def git(*args, cwd=None):
    p = subprocess.run(["git", "-C", cwd or G["fixture"]] + list(args),
                       # SANCTIONED-WAIT: bounded git call, not a state wait
                       capture_output=True, text=True, timeout=120)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def build_fixture(fail):
    """Fixture repo + hermetic project registry + fixture lane declaration + baseline."""
    fixture = os.path.join(G["tmp"], "fixture")
    clone = subprocess.run(["git", "clone", "--depth", "1", REPO, fixture],
                           # SANCTIONED-WAIT: bounded clone, not a state wait
                           capture_output=True, text=True, timeout=600)
    if clone.returncode != 0:
        fail.bail("git clone of the fixture repo failed (environment): %s"
                  % (clone.stderr or clone.stdout)[:200], 2)
    G["fixture"] = fixture
    rc, br = git("rev-parse", "--abbrev-ref", "HEAD")
    cur = (br or "").strip()
    if cur and cur != "main":
        git("branch", "-m", "main")
    git("config", "user.email", "e2e@quickmanual.test")
    git("config", "user.name", "quickmanual-e2e")
    projects = os.path.join(fixture, ".e2e-projects")
    os.makedirs(os.path.join(projects, PROJECT_KEY), exist_ok=True)
    with open(os.path.join(projects, ".migrated"), "w", encoding="utf-8") as f:
        f.write("fixture-local hermetic registry (quickmanual e2e)\n")
    # Registration seam (t261019-32): the fixture project declares the quickmanual
    # template through the SANCTIONED project-external loader
    # (project_templates, the t260924-04 contract) so the journey world has a
    # startable template while the production face stays fail-closed until the
    # step-0 host amendment. The module is the repo file next to this scenario,
    # copied into the fixture project's main dir (the loader resolves
    # workflow_modules relative to dirs[0]); it deep-checks the class (STAGES,
    # TEMPLATE_ID agreement, patch-id collision scan, clean module) and merges it
    # for THIS PROJECT ONLY.
    seam_src = os.path.join(HERE, "qm_fixture_template.py")
    seam_dst = os.path.join(fixture, "qm_fixture_template.py")
    with open(seam_src, encoding="utf-8") as f:
        seam_text = f.read()
    with open(seam_dst, "w", encoding="utf-8") as f:
        f.write(seam_text)
    with open(os.path.join(projects, PROJECT_KEY, "project.yaml"), "w",
              encoding="utf-8") as f:
        f.write("schema: v1\nproject:\n  - key: %s\n    name: quickmanual-fixture\n"
                "    dirs:\n      - %s\npaths:\n  workflow_modules: "
                "qm_fixture_template.py\n" % (PROJECT_KEY, fixture))
    # Concurrency-slot declaration (acceptance gen3's named root cause): the
    # quickmanual lane, like every lane, judges its slot per project BEFORE the
    # first stage (concurrency.load_limit is fail-closed on an absent
    # declaration - the fixture project simply had none, so both tickets died
    # named at open). Minimal per-project declaration, same schema as
    # server/engine/concurrency.py DECL_FILE (version 1 + limit; limit 2 lets
    # the journey's two tickets hold slots concurrently). Note recorded from
    # this incident: a deterministically failing activity burns its whole
    # retry window (~minutes) before the fault reaches the ticket face - the
    # fail-named boundary makes it visible, but a fixture gap like this one
    # costs the window; fix declarations, not windows.
    with open(os.path.join(projects, PROJECT_KEY, "concurrency-limit.json"), "w",
              encoding="utf-8") as f:
        f.write('{"version": 1, "limit": 2}\n')
    G["projects"] = projects
    G["seam_registered"] = True
    target = os.path.join(REPO, "server", "engine", ".venv")
    link = os.path.join(fixture, "server", "engine", ".venv")
    if os.path.isdir(target) and not os.path.exists(link):
        os.symlink(target, link)
    build_lane(fixture, [(n, "ro", True) for n in GATE_NAMES])
    # t261022-12 (acceptance gen14 defect 2): the quickmanual fixture ticket's
    # evidence declaration is an l1_battery named "test_quickmanual_lane.py",
    # and the evidence-scope resolution (QUICKMANUAL_SCOPE_PATCH_ID) requires
    # that battery to exist as a file in the LANE (quick_scope_plan's
    # path_exists face). Both quickmanual fixture worlds build their lane
    # through this one seam, so the battery stub is written here once: a
    # passing, pytest-addressable target, green by construction.
    with open(os.path.join(fixture, "test_quickmanual_lane.py"), "w",
              encoding="utf-8") as f:
        f.write(
            '"""Fixture battery face (t261022-12): the quickmanual fixture\n'
            'ticket\'s evidence declaration names this battery; the evidence-scope\n'
            'resolution requires it to exist as a file in the lane. Passing by\n'
            'construction - the fixture world asserts the scope/plumbing faces,\n'
            'not this file."""\n'
            'def test_fixture_battery_face_is_present():\n'
            '    assert True\n')
    mini_dir = os.path.join(fixture, "integration", "mini")
    for n in GATE_NAMES:
        with open(os.path.join(mini_dir, "%s.py" % n), "w", encoding="utf-8") as f:
            f.write(PROBE_SRC.replace("<<NAME>>", n).replace("<<LED>>", G["gate_ledger"]))
    # The fixture must run the WORKING TREE's engine + workflow surfaces (HEAD lacks
    # the quickmanual class): overlay changed engine/workflow files, then require
    # byte equality on the watched set (no git-status transience).
    pc = subprocess.run(["git", "status", "--porcelain", "--", "server/engine",
                         "server/workflows"], cwd=REPO, capture_output=True,
                        # SANCTIONED-WAIT: bounded git call, not a state wait
                        text=True, timeout=120)
    copied = []
    for ln in (pc.stdout or "").splitlines():
        rel = ln[3:].strip().strip('"')
        if not rel or rel.endswith("/"):
            continue
        if not (rel.endswith(".py") or rel.endswith(".yaml")):
            continue
        src = os.path.join(REPO, rel)
        dst = os.path.join(fixture, rel)
        if not os.path.isfile(src):
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(rel)
    watched = sorted(set(copied) | {"server/engine/dev_lane.py",
                                    "server/engine/shared.py"})
    drift = []
    for rel in watched:
        a, b = os.path.join(REPO, rel), os.path.join(fixture, rel)
        if not os.path.isfile(a) or not os.path.isfile(b):
            drift.append("%s (missing)" % rel)
            continue
        with open(a, "rb") as fa, open(b, "rb") as fb:
            if fa.read() != fb.read():
                drift.append("%s (byte drift)" % rel)
    fail.check(not drift,
               "L1 fixture runs the working-tree engine (byte-equal on %d watched "
               "files; drift=%r)" % (len(watched), drift[:5]))
    git("add", "-A")
    rc, out = git("commit", "-qm", "quickmanual e2e fixture: mini integration registry")
    if rc != 0:
        fail.bail("fixture baseline commit failed: %s" % out[:200], 2)
    return fixture


def start_worker(py, stage, watch, queues=None):
    extra = {
        "SANDBAR_TASK_QUEUES": queues or "sandbar-ticket-%s" % watch,
        "SANDBAR_WATCH_WORKFLOW": watch,
        "SANDBAR_WATCH_INTERVAL_SEC": "2",
        "SANDBAR_AGENT_CMD": "%s %s" % (py, G["stub"]),
        "SANDBAR_UI_CAPTURE_STUB": "1",
    }
    log = open(os.path.join(G["tmp"], "worker-%s.log" % watch), "wb")
    proc = subprocess.Popen([py, os.path.join(G["fixture"], "server", "engine",
                                              "worker.py")],
                            env=env_for(stage, extra), cwd=REPO, stdout=log,
                            stderr=subprocess.STDOUT, start_new_session=True)
    G["workers"].append(proc)
    G["all_workers"].append(proc)
    return proc


def stop_all_workers(fail, label):
    procs, G["workers"] = list(G["workers"]), []
    for i, proc in enumerate(procs):
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=20)
            except Exception:
                proc.kill()
                proc.wait(timeout=10)
        fail.check(proc.poll() is not None,
                   "%s#%d worker reaped (rc=%s)" % (label, i + 1, proc.returncode))


def stray_procs(marker):
    try:
        buf = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True,
                             text=True, timeout=60).stdout
    except Exception:  # noqa: BLE001
        return None
    me = os.getpid()
    out = []
    for ln in (buf or "").splitlines():
        m = re.match(r"^\s*(\d+)\s+(.*)$", ln)
        if m and int(m.group(1)) != me and marker in m.group(2):
            out.append(m.group(1))
    return out




def main():
    fail = Fail("quickmanual-lane workflow e2e (t261019-32)")
    stats = {"pass": 0}

    def check(cond, msg):
        r = fail.check(cond, msg)
        if r:
            stats["pass"] += 1
        return r

    stage_mod = None
    G["tmp"] = tempfile.mkdtemp(prefix="sandbar-quickmanual-e2e-")
    atexit.register(lambda: shutil.rmtree(G["tmp"], ignore_errors=True)
                    if not os.environ.get("SANDBAR_QMLE2E_KEEP_TMP") else None)
    G["gate_ledger"] = os.path.join(G["tmp"], "gate-ledger.jsonl")
    G["stub_ledger"] = os.path.join(G["tmp"], "stub-ledger.jsonl")
    G["stub"] = os.path.join(G["tmp"], "qm_stub.py")
    with open(G["stub"], "w", encoding="utf-8") as f:
        f.write(STUB_SRC)
    try:
        # ---------- L0 environment and red lines ----------
        bench = require_bench(fail)
        py = poc_python(bench)
        stage_mod, stage = require_stage(fail, "qm-e2e-%d" % os.getpid(),
                                         "qm-e2e-%d" % os.getpid())
        fe = int(stage["ports"]["temporal"])
        check(fe not in stage_docker.FORBIDDEN_PORTS,
              "L0 stage port %d outside the forbidden set (incl. 3099)" % fe)
        check(all(k not in env_for(stage) for k in LANE_MARKERS),
              "L0 subprocess env strips the lane-worker marker trio")

        # ---------- L1 fixture ----------
        build_fixture(fail)

        # ---------- J1/J2: two tickets, both explicit, one without evidence ----------
        start_worker(py, stage, TID)
        start_worker(py, stage, TID_NOEV)
        _rc, br = git("rev-parse", "--short", "HEAD")
        base_ref = (br or "").strip()
        create = dict(template_id="quickmanual-lane", project=PROJECT_KEY,
                      base_ref=base_ref, caller_project=PROJECT_KEY,
                      write_set=[WRITE_FILE])
        _rc, out = run_poc_client(py, "ticket-start", dict(
            create, ticket_id=TID,
            title="[e2e] quickmanual journey (session works, gates hold, no self-sign)",
            user_request="integration e2e: a session repairs this in the lane; "
                         "evidence = the L1 battery named below",
            evidence={"kind": "l1_battery", "name": "test_quickmanual_lane.py"},
        # SANCTIONED-WAIT: bounded client call, not a state wait
        ), env_for(stage), timeout=300)
        good, why = accepted(out, TID)
        check(good, "J1 healthy quickmanual ticket accepted on the explicit create "
                    "face (%s)" % why)
        _rc, out2 = run_poc_client(py, "ticket-start", dict(
            create, ticket_id=TID_NOEV,
            title="[e2e] quickmanual without an evidence declaration",
            user_request="integration e2e: evidence is mandatory; this ticket "
                         "declares none",
        # SANCTIONED-WAIT: bounded client call, not a state wait
        ), env_for(stage), timeout=300)
        good2, why2 = accepted(out2, TID_NOEV)
        check(good2, "J2 evidence-less ticket accepted at creation (the gate lives "
                     "at open, not at the create face; %s)" % why2)

        # ---------- J2: the evidence gate blocks at open ----------
        if good2:
            s2 = wait_snap(fail, py, stage, TID_NOEV,
                           lambda x: x.get("stage") == "open"
                           and x.get("stage_state") == "blocked",
                           "J2 evidence-less ticket blocked at open", 300)
            if s2 is not None:
                reason2 = str(s2.get("blocked_reason") or "")
                d2 = s2.get("blocked_detail") or {}
                blob2 = json.dumps({"reason": reason2, "detail": d2},
                                   ensure_ascii=False)
                check("evidence" in blob2.lower(),
                      "J2 the block names the failed check: evidence "
                      "(got %r)" % reason2[:160])
                stub2 = stub_stages_of(TID_NOEV)
                check(stub2 == [],
                      "J2 no agent dispatched for the blocked ticket either "
                      "(got %r)" % (stub2,))

        # ---------- J3: the healthy ticket parks at work; nobody is dispatched ----------
        # the parked state is `awaiting` (waiting for the session's signal; the
        # running face belongs to stages with an in-flight activity)
        snap = wait_snap(fail, py, stage, TID,
                         lambda x: x.get("stage") == "work"
                         and x.get("stage_state") in ("awaiting", "running"),
                         "J3 healthy ticket parks at the work stage", 300)
        if snap is not None:
            check(stub_stages_of(TID) == [],
                  "J1 the stub-brain ledger is EMPTY for the ticket (no agent "
                  "dispatch anywhere in open/work; got %r)" % stub_stages_of(TID))
            tl0 = len(snap.get("timeline") or [])
            time.sleep(8)
            r = cli(py, stage, "ticket-query", {"ticket_id": TID})
            snap2 = (r.get("result") or {}).get("snapshot") or {}
            tl1 = len(snap2.get("timeline") or [])
            check(snap2.get("stage") == "work"
                  and snap2.get("stage_state") in ("awaiting", "running")
                  and tl1 == tl0,
                  "J3 parked ticket is quiet: stage stays work and the timeline "
                  "does not churn in an 8s window (%d -> %d entries; the no-backoff "
                  "poll loop of t261019-18 would burn both)" % (tl0, tl1))

            # ---------- J4a: session-less done signal refused ----------
            # fields ride the op args TOP level (the client/ticket entries read
            # session from the op args); after this fix the refusal exercises the
            # workflow-side identity intake, not just the client-shape error
            r = cli(py, stage, "ticket", {"op": "work_done", "ticket_id": TID,
                                          "role": SESSION_ROLE})
            refused = (r.get("ok") is not True) or str(r.get("error") or "")
            snap3 = (cli(py, stage, "ticket-query",
                         {"ticket_id": TID}).get("result") or {}).get("snapshot") or {}
            check(snap3.get("stage") == "work"
                  and snap3.get("stage_state") in ("awaiting", "running"),
                  "J4a a done signal without a session id leaves the ticket parked "
                  "at work (reply error=%r)" % str(r.get("error") or "")[:120])
            check(bool(str(refused).strip()),
                  "J4a the refusal is loud (non-empty reply/error face)")

            # ---------- J3/J4: the session works, then signals done ----------
            ws = str((((snap2.get("meta") or {}).get("workspace") or {})
                      .get("path")) or "")
            if not ws:
                # fall back to the conventional lane path under the fixture repo
                ws = ""
                for root, dirs, files in os.walk(G["fixture"]):
                    if os.path.basename(root) == ".lane" and TID.replace("-", "") in \
                            os.path.basename(os.path.normpath(
                                os.path.join(root, ".."))).replace("-", ""):
                        ws = os.path.join(root, os.listdir(root)[0])
                        break
            work_file = None
            if ws and os.path.isdir(ws):
                work_file = os.path.join(ws, WRITE_FILE)
                with open(work_file, "w", encoding="utf-8") as f:
                    f.write("quickmanual e2e: the session's one-file repair\n")
            check(bool(work_file and os.path.isfile(work_file)),
                  "J3 the session wrote its repair inside the lane worktree (%r)"
                  % (work_file,))
            r = cli(py, stage, "ticket", {"op": "work_done", "ticket_id": TID,
                                          "session": SESSION,
                                          "role": SESSION_ROLE})
            done_ok, done_why = (r.get("ok") is True,
                                 str(r.get("error") or "")[:120])
            check(done_ok, "J3 a done signal WITH a session id + role is accepted "
                           "(%s)" % (done_why or "ok"))

            # ---------- J4b: identity on the face ----------
            # Assert on the PUBLIC worked_by snapshot key directly (acceptance
            # gen5 item 2: the earlier find_worked_by JSON walk returned the
            # FIRST dict embedding the session id - a settle check item that
            # carries no role - so the role check read the wrong record and
            # failed although the face held the role; the key is the same
            # grey-box snapshot family this journey already relies on).
            snap4 = wait_snap(fail, py, stage, TID,
                              lambda x: bool(x.get("worked_by"))
                              and x.get("stage") in ("run_integration_tests",
                                                     "merge_check", "merge"),
                              "J4 identity recorded and the chain advanced past "
                              "work", 420)
            if snap4 is not None:
                rec = snap4.get("worked_by") or {}
                check(str(rec.get("session") or "") == SESSION,
                      "J4b the ticket face records WHO worked (worked_by.session "
                      "== the session id; got %r)" % (rec,))
                check(str(rec.get("role") or "") == SESSION_ROLE,
                      "J4b the record carries the session's role (worked_by.role; "
                      "got %r)" % (rec,))
                tl = [str(e.get("stage") or "") for e in (snap4.get("timeline") or [])]
                check(not (set(tl) & set(EXCLUDED_STAGES)),
                      "J5 no dev-lane-only stage ever appears on the timeline "
                      "(got %r)" % sorted(set(tl) & set(EXCLUDED_STAGES)))
                check(stub_stages_of(TID) == [],
                      "J5 the stub-brain ledger is STILL empty after settle and "
                      "the gates (the whole lane is agent-free; got %r)"
                      % stub_stages_of(TID))
                # ---------- J5: gates ran the declared command; merge gate reached ----------
                gate_names = sorted({r.get("name") for r in read_jsonl(G["gate_ledger"])})
                check(gate_names == sorted(GATE_NAMES),
                      "J5 the integration gate ran the fixture registry's declared "
                      "scenarios (got %r)" % gate_names)
                s5 = wait_snap(fail, py, stage, TID,
                               lambda x: x.get("stage") == "merge"
                               and x.get("stage_state") == "awaiting-human",
                               "J5 healthy ticket reaches the human merge gate", 420)
                if s5 is not None:
                    # ---------- J6: no self-signed merge ----------
                    r = cli(py, stage, "ticket", {"op": "sign", "ticket_id": TID,
                                                  "who": SESSION, "gate": "merge",
                                                  "decision": "approve"})
                    # The delivery receipt only proves the signal reached the
                    # server (ok=true delivered=true) - the refusal lives on the
                    # TICKET FACE: exactly one refused record with who = the
                    # working session, want carrying the sign attempt, and the
                    # why naming the no-self-sign rule (acceptance round 8:
                    # assert the refusal where it happens).
                    s6 = (cli(py, stage, "ticket-query",
                              {"ticket_id": TID}).get("result") or {}).get("snapshot") or {}
                    recs = [r0 for r0 in (s6.get("refused") or [])
                            if isinstance(r0, dict)
                            and str(r0.get("who") or "") == SESSION
                            and "sign" in str(r0.get("want") or "")
                            and "no self-sign" in str(r0.get("why") or "")]
                    check(len(recs) >= 1,
                          "J6 the WORKING session cannot sign the merge - the "
                          "face carries the named refusal (who=%s, want~sign, "
                          "why~no self-sign; got %r)"
                          % (SESSION, (s6.get("refused") or [])[:3]))
                    check(s6.get("stage") == "merge"
                          and s6.get("stage_state") == "awaiting-human",
                          "J6 after the refused self-sign the ticket is still "
                          "awaiting-human (stage=%r/%r)"
                          % (s6.get("stage"), s6.get("stage_state")))
                    r = cli(py, stage, "ticket", {"op": "sign", "ticket_id": TID,
                                                  "who": "e2e-executor",
                                                  "gate": "merge",
                                                  "decision": "approve"})
                    check(r.get("ok") is True,
                          "J6 the executor signs and the ticket closes (reply "
                          "error=%r)" % str(r.get("error") or "")[:140])
                    s7 = wait_snap(fail, py, stage, TID,
                                   lambda x: x.get("stage_state") == "closed"
                                   or str(x.get("status") or "") == "closed",
                                   "J6 signed ticket closes", 300)
                    if s7 is not None:
                        check(str(s7.get("status") or "") == "closed"
                              or s7.get("stage_state") == "closed",
                              "J6 end state closed (status=%r stage_state=%r)"
                              % (s7.get("status"), s7.get("stage_state")))
    finally:
        stop_all_workers(fail, "L7 worker reaping")
        if stage_mod is not None:
            stage_down(stage_mod, "qm-e2e-%d" % os.getpid())
        strays = stray_procs(os.path.basename(G.get("tmp") or "@none@"))
        if strays is not None:
            check(not strays, "L7 no stray scenario process survives teardown "
                              "(got %r)" % strays[:5])
    fail.finish()


if __name__ == "__main__":
    sys.exit(main())
