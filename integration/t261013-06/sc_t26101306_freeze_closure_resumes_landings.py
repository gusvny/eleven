#!/usr/bin/env python3
"""sc_t26101306_freeze_closure_resumes_landings.py — a freeze can actually
END, and the line then accepts ordinary landings again (ticket t261013-06,
the develop-buffer line's freeze-path carrier).

Run directly (cwd = repo root):
python3 integration/t261013-06/sc_t26101306_freeze_closure_resumes_landings.py

Why this entry exists. The line froze on a red certification, and every
landing that was not the carrier was refused. The carrier ends the incident
in two steps: main's batch reaches the line, and the freeze episode is then
closed by a recorded change row. No engine code writes that closure row
today, so a person writes it into the ledger. The existing entries pin the
other halves: t261009-67 pins the refusal and the repairs-relation
exemption, and it also pins that a fix landing does NOT close the episode;
t261009-41 pins the projection replay (frozen / culprit); t261009-30 and
t261009-41 pin the decisions that open an episode. Nothing pins the closing
half as a user-perceivable behaviour: that the recorded closure unfreezes
the line and ordinary landings resume, and that a closure row which does not
name this episode never closes it.

The user-perceivable contract this entry owns:

  A  THE CLOSURE IS READ FROM THE RECORD — a closure row written through the
     engine's own writer makes the line read unfrozen, with the moment taken
     from the row and the episode and cause still readable (a closure ends
     the freeze; it erases no record), and the landing face has nothing left
     to exempt.

  B  THE LINE RESUMES — an ORDINARY ticket (no repairs relation, nothing to
     exempt) lands through the real landing act: one landing row on the
     line, and the named refusal a frozen line gives is gone. This is the
     user-visible end of the incident.

  C  THE CLOSURE MUST NAME THE EPISODE — a closure row for ANOTHER episode
     id and a closure row carrying ANOTHER line each leave the line frozen,
     and the landing act still refuses BY NAME with the episode id and the
     cause certification id. A closure that cannot name what it closes
     closes nothing. The change word itself is checked on the write side: an
     unknown word is refused by name with nothing written, and a ledger line
     carrying one (the hand-edited shape) never closes the episode and never
     crashes the read.

  D  REOPENED FREEZES AGAIN — a reopened row recorded after the closure puts
     the line back under the freeze (no closed moment) and the ordinary
     landing is refused by name again.

Intent split (no intent-level duplication):
  - the refusal shape, the repairs-relation exemption and "a fix landing
    keeps the episode open" belong to t261009-67 (this entry opens episodes
    and closures only as fixture state through the engine's own writer);
  - the freeze open/close DECISIONS and the red ladder belong to
    t261009-30 and t261009-41;
  - the replay of frozen / culprit and the panel projections belong to
    t261009-41;
  - the relation ROW contract belongs to t261009-62; the two-direction
    reader belongs to t261009-66;
  - the pure read truth tables (including CHANGE_CLOSED / CHANGE_REOPENED
    unit cases) belong to the developer L1 battery
    (integration/tests/test_t261009_21_certify.py, server/engine/tests).

Grey-box: the real engine public faces (freeze_state, landing_freeze_face,
land_ticket, freeze_change_row, open_freeze_rows, append_rows) over a real
temp delivery ledger, real `git init` fixture repos, and the real landing
act. Offline seconds, zero docker / Temporal / browser, never touches 3099
or 7233. Proof is read back from the ledger FILE and from the public faces,
never from a return value alone.

Engine modules unimportable or git absent = ENV_FAIL exit 2.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
INTEG = os.path.dirname(HERE)
REPO = os.path.dirname(INTEG)
ENGINE = os.path.join(REPO, "server", "engine")
if os.path.isdir(ENGINE):
    sys.path.insert(0, ENGINE)
if os.path.isdir(INTEG):
    sys.path.insert(0, INTEG)

from lib_result import ScenarioCheck  # noqa: E402

_ck = ScenarioCheck(ok_fmt="  ok %s", fail_fmt="  FAIL %s", detail_cap=700,
                    flush=True)

try:
    import develop_certify as dc  # noqa: E402
    import develop_line as dl  # noqa: E402
    import shared  # noqa: E402
except Exception as exc:  # noqa: BLE001
    _ck.env_fail("engine modules", "engine tree absent/unimportable: %s" % exc)

NAME = "t261013-06-freeze-closure-resumes-landings"
LINE = "buffer"
OTHER_LINE = "sandbox"
LINE_BRANCH = "develop"
TMPDIRS = []


def _git(*args, cwd, check_rc=True):
    p = subprocess.run(["git"] + list(args), cwd=str(cwd),
                       capture_output=True, text=True)
    if check_rc and p.returncode != 0:
        raise AssertionError("git %s failed: %s" % (" ".join(args), p.stderr))
    return p


def _rev(repo, ref):
    return _git("rev-parse", "--verify", ref, cwd=repo,
                check_rc=False).stdout.strip()


def _init_repo(path):
    path = str(path)
    os.makedirs(path, exist_ok=True)
    _git("init", "-b", "main", cwd=path)
    _git("config", "user.email", "it@example.com", cwd=path)
    _git("config", "user.name", "it", cwd=path)
    with open(os.path.join(path, "main.txt"), "w") as fh:
        fh.write("base\n")
    _git("add", "-A", cwd=path)
    _git("commit", "-m", "base", cwd=path)
    return path


def _lane_commit(repo, fname, text, msg, branch="lane"):
    """Rebuild the lane branch from main with one commit of ticket work —
    the shape every ticket's lane has."""
    repo = str(repo)
    _git("checkout", "-B", branch, "main", cwd=repo)
    with open(os.path.join(repo, fname), "w") as fh:
        fh.write(text)
    _git("add", "-A", cwd=repo)
    _git("commit", "-m", msg, cwd=repo)
    return _git("rev-parse", "HEAD", cwd=repo).stdout.strip()


def _declare(project):
    decl = [
        {"line_id": LINE, "scope": "epic x", "owner": "integration",
         "repositories": [{"name": "r", "branch": LINE_BRANCH}],
         "extra_scenarios": [], "version": 1},
        {"line_id": OTHER_LINE, "scope": "epic y", "owner": "integration",
         "repositories": [{"name": "r", "branch": "sandbox-line"}],
         "extra_scenarios": [], "version": 1},
    ]
    d = shared.develop_dir(project)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "lines.json"), "w") as fh:
        json.dump(decl, fh)


def _rows(project):
    return dc.read_rows(dc.ledger_path(project))


def _append(project, rows, expect=1):
    res = dc.append_rows(rows, dc.ledger_path(project))
    if res.get("written") != expect:
        raise AssertionError("append_rows wrote %r not %s: %s"
                             % (res.get("written"), expect, res))
    return res


def _cert_row(cid, line, revision, at):
    return {"kind": dc.KIND_CERT, "id": cid, "line": line,
            "repos": [{"repo": "r", "revision": revision}],
            "run": "run-00000000000000000000000000", "booked_red": "b@x",
            "judged_by": "it", "at": at}


def _landing_rows(project, line_id=LINE):
    rows, bad = _rows(project)
    if bad:
        raise AssertionError("malformed ledger lines: %s" % bad)
    return [r for r in rows
            if r.get("kind") == dc.KIND_LANDING and r.get("line") == line_id]


def _freeze_fixture(project, revision, at):
    """Open one freeze episode through the engine's own writer: a red
    certification on the line plus the episode keyed to it. Opening is
    fixture state; the DECISION belongs to t261009-30 / t261009-41."""
    cert = _cert_row("cert-" + "0" * 24, LINE, revision, at)
    _append(project, [cert])
    frz = dc.open_freeze_rows(cert, at_ms=at + 1)[0]
    _append(project, [frz])
    return cert["id"], frz["id"]


def _change_row(project, frz_id, at, *, line_arg=LINE, change=None,
                freeze_arg=None):
    """Write one change row through the engine's own writer — the path a
    person uses for the closure, since no engine code writes it."""
    row = dc.freeze_change_row(
        freeze_arg if freeze_arg is not None else frz_id,
        change if change is not None else dc.CHANGE_CLOSED,
        "integration",
        "the carrier landed main's batch; the line's red no longer holds",
        at_ms=at, line=line_arg)
    _append(project, [row])
    return row


def _try_land(env, ticket):
    """Return (landed, refusal-text) from the REAL landing act."""
    try:
        res = dl.land_ticket(env.line, env.project, {"r": env.repo},
                             ticket, "engine")
        return bool(getattr(res, "ok", False)), ""
    except dl.LandingError as e:
        return False, str(e)
    except Exception as e:  # noqa: BLE001
        return False, "%s: %s" % (type(e).__name__, e)


class _Env:
    """One isolated project: temp projects dir, temp delivery ledger, one
    real git repo declared on the line, and the line's first landing already
    on record (so the ledger certifies a revision the line carries — the
    state every later landing sits on)."""

    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="t26101306-")
        TMPDIRS.append(self.tmp)
        self.projects = os.path.join(self.tmp, "projects")
        self.ledger = os.path.join(self.tmp, "ledger")
        self.runs = os.path.join(self.tmp, "runs.jsonl")
        with open(self.runs, "w") as fh:
            fh.write(json.dumps({"id": "run-00000000000000000000000000",
                                 "cases": {"ran": 3, "failed": 0,
                                           "env_failed": 0}}) + "\n")
        os.makedirs(self.projects, exist_ok=True)
        os.makedirs(self.ledger, exist_ok=True)
        self.old = {k: os.environ.get(k) for k in
                    ("SANDBAR_PROJECTS_DIR", "SANDBAR_DELIVERY_LEDGER_DIR",
                     "SANDBAR_RUNS_LEDGER")}
        os.environ["SANDBAR_PROJECTS_DIR"] = self.projects
        os.environ["SANDBAR_DELIVERY_LEDGER_DIR"] = self.ledger
        os.environ["SANDBAR_RUNS_LEDGER"] = self.runs
        self.project = "proj"
        _declare(self.project)
        self.repo = Path(_init_repo(os.path.join(self.tmp, "repo")))
        self.line = dl.load_line(self.project, LINE)
        # The line's first landing: it seeds the line branch. Before the
        # line's first certification the act derives no predecessor.
        _lane_commit(self.repo, "control.txt", "control\n", "control work")
        landed, msg = _try_land(self, "t-control")
        if not landed:
            raise AssertionError("control landing failed: %s" % msg)
        self.line_rev = _rev(self.repo, LINE_BRANCH)
        if not self.line_rev:
            raise AssertionError("control landing created no line branch")

    def next_lane(self, fname, text, msg):
        return _lane_commit(self.repo, fname, text, msg)

    def restore(self):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ------------------------------------------------- A/B: closure and resume

def leg_a_b(env):
    """A the closure is read from the record; B the line resumes ordinary
    landings."""
    cert_id, frz_id = _freeze_fixture(env.project, env.line_rev,
                                      1791871000000)

    # A0 control: while the episode is open an ordinary ticket is refused,
    # and the refusal names the episode and the cause — the state the
    # carrier has to escape.
    env.next_lane("a0.txt", "a0\n", "ordinary work A0")
    landed, msg = _try_land(env, "t-ordinary-before")
    _ck.ok((not landed) and frz_id in msg and cert_id in msg,
           "A0 open episode refuses an ordinary landing by name "
           "(episode + cause ids)", msg)

    close = _change_row(env.project, frz_id, 1791872000000)

    # A1/A2 the record, read back from the ledger through the public face.
    rows, _ = _rows(env.project)
    st = dc.freeze_state(rows, LINE)
    _ck.ok(st.get("frozen") is False and st.get("closed_at") == close["at"],
           "A1 closure read from the record: unfrozen with the row's moment",
           st)
    _ck.ok(st.get("episode") == frz_id and st.get("cause") == cert_id,
           "A2 the closed episode stays readable (id + cause kept, nothing "
           "erased)", st)
    face = dc.landing_freeze_face(rows, LINE, "t-ordinary-after")
    _ck.ok(face.get("allowed") is True and not face.get("relation"),
           "A3 with the episode closed the landing face has nothing to "
           "exempt", face)

    # B the real act: an ordinary ticket lands, and exactly one landing row
    # is added for the line.
    before = len(_landing_rows(env.project))
    env.next_lane("b.txt", "b\n", "ordinary work B")
    landed, msg = _try_land(env, "t-ordinary-after")
    after = _landing_rows(env.project)
    _ck.ok(landed, "B1 the line resumes: an ordinary ticket lands after the "
                   "recorded closure", msg)
    _ck.ok(len(after) == before + 1,
           "B2 exactly one landing row was written for the line",
           [r.get("id") for r in after])
    if after:
        _ck.ok(after[-1].get("ticket") == "t-ordinary-after",
               "B3 the new landing row names the ticket that landed",
               after[-1])


# ------------------------------------------- C: a closure that names nothing

def leg_c(env):
    """A closure row that does not name this episode closes nothing; the
    change word is checked on the write side; the landing act keeps refusing
    by name."""
    cert_id, frz_id = _freeze_fixture(env.project, env.line_rev,
                                      1791873000000)

    # Two shapes the writer accepts but that name something else.
    _change_row(env.project, frz_id, 1791873100000,
                freeze_arg="frz-" + "9" * 26)
    _change_row(env.project, frz_id, 1791873200000, line_arg=OTHER_LINE)

    # The change word itself: the writer refuses an unknown one BY NAME and
    # writes nothing (never a silent record).
    bad = dc.freeze_change_row(frz_id, "closedish", "integration",
                               "unknown change word", at_ms=1791873300000,
                               line=LINE)
    res = dc.append_rows([bad], dc.ledger_path(env.project))
    reasons = " ".join(str(r.get("reason") or "")
                       for r in (res.get("rejected") or []))
    _ck.ok(res.get("written") == 0 and "change" in reasons,
           "C1 the writer refuses an unknown change word by name with "
           "nothing written (no silent record)", res)

    # The hand-edited shape: such a line can still reach the reader, and it
    # must neither close the episode nor crash the read.
    rows, _ = _rows(env.project)
    seq = max([int(r.get("seq") or 0) for r in rows] or [0]) + 1
    hand = dict(bad, seq=seq)
    with open(dc.ledger_path(env.project), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(hand) + "\n")

    rows, _ = _rows(env.project)
    st = dc.freeze_state(rows, LINE)
    _ck.ok(st.get("frozen") is True and st.get("closed_at") is None,
           "C2 a foreign-episode closure, a foreign-line closure and a "
           "hand-edited unknown change word all leave the line frozen", st)
    _ck.ok(st.get("episode") == frz_id and st.get("cause") == cert_id,
           "C3 the open episode still carries its id and cause", st)

    env.next_lane("c.txt", "c\n", "ordinary work C")
    landed, msg = _try_land(env, "t-ordinary-scoped")
    _ck.ok((not landed) and frz_id in msg and cert_id in msg,
           "C4 the landing act still refuses by name with episode + cause",
           msg)
    _ck.ok(len(_landing_rows(env.project)) == 1,
           "C5 a refusal writes no new landing row (the control landing is "
           "the only one on the line)",
           [r.get("id") for r in _landing_rows(env.project)])


# -------------------------------------------------------- D: reopened again

def leg_d(env):
    """A reopened row puts the line back under the freeze."""
    cert_id, frz_id = _freeze_fixture(env.project, env.line_rev,
                                      1791874000000)
    _change_row(env.project, frz_id, 1791874100000)
    rows, _ = _rows(env.project)
    _ck.ok(dc.freeze_state(rows, LINE).get("frozen") is False,
           "D1 the closure lands first (control for the reopen)",
           dc.freeze_state(rows, LINE))

    _change_row(env.project, frz_id, 1791874200000,
                change=dc.CHANGE_REOPENED)
    rows, _ = _rows(env.project)
    st = dc.freeze_state(rows, LINE)
    _ck.ok(st.get("frozen") is True and st.get("closed_at") is None,
           "D2 a reopened row freezes the line again (no closed moment)", st)

    env.next_lane("d.txt", "d\n", "ordinary work D")
    landed, msg = _try_land(env, "t-ordinary-reopened")
    _ck.ok((not landed) and frz_id in msg and cert_id in msg,
           "D3 after the reopen the ordinary landing is refused by name",
           msg)


def main():
    if shutil.which("git") is None:
        _ck.env_fail("git", "git is not on PATH")
    for leg in (leg_a_b, leg_c, leg_d):
        env = _Env()
        try:
            leg(env)
        finally:
            env.restore()


if __name__ == "__main__":
    try:
        main()
    finally:
        for d in TMPDIRS:
            shutil.rmtree(d, ignore_errors=True)
    _ck.finish(NAME)
