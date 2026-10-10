#!/usr/bin/env python3
"""sc_t26100967_freeze_stops_landings.py — the freeze actually stops
landings, and the signer can see it (ticket t261009-67, host order 261009
P2-e, docs/design/develop-buffer-v1.md items 17 / 24 / 95 / 160 / 166 /
167).

Run directly (cwd = repo root):
python3 integration/t261009-67/sc_t26100967_freeze_stops_landings.py

Grey-box L3, offline seconds, real `git init` fixture repos in temp dirs,
the REAL delivery ledger (temp file, engine's own writer/reader) and the
REAL executor-panel certification adapter as a subprocess (the reader-side
face a promotion signer actually reads). Zero docker/Temporal/browser,
never touches 3099/7233.

The user-perceivable contract this entry owns (t261009-67 spec (1)-(5)):

  A  A FROZEN LINE REFUSES A LANDING BY NAME — with an open freeze on the
     line, land_ticket refuses (the landing act itself consults the
     freeze; before this ticket it walked straight past), the refusal
     names the freeze episode id AND the cause certification id (ids, not
     prose), the lane repository is untouched (nothing merged, nothing
     appended — all-or-nothing before any mutation), and the refusal for a
     ticket that merely calls itself a fix is the SAME refusal: nothing
     the ticket says about itself is consulted.

  B  THE EXEMPTION IS STRUCTURAL, VIA THE RECORDED REPAIRS RELATION — on
     the frozen line a fix ticket WITH a current repairs relation naming a
     landing on THIS line lands; with a SUPERSEDED (corrected) relation it
     is refused; with a relation targeting a landing on ANOTHER line it is
     refused (scoping, never guessed). An unfrozen line behaves exactly as
     before, relation or not (the control).

  C  COULD-NOT-RUN IS NOT RED, ON THE REAL LANDING PATH — after a range
     growth row (a proof that could not be produced) in the ledger, the
     line still lands (the landing act never reads an unavailable proof as
     a freeze), no freeze episode exists, and the growth is a recorded row
     the next certification's derived range must cover (derive_range over
     the real ledger, read back from disk).

  D  THE FREEZE IS VISIBLE TO WHOEVER SIGNS THE NEXT PROMOTION — the
     signer face names the open freeze, its cause certification, the
     culprit landing it implicates, and the fix landings that reopen it,
     read back FROM THE LEDGER; and the REAL certification-adapter
     subprocess (the panel's read side, invoked the way the panel invokes
     it) reports the freeze on the line it renders. Malformed ledger rows
     degrade to a NAMED note in the adapter receipt — never a crash,
     never a fabricated freeze.

  E  THE CHAIN OF FIXES STAYS VISIBLE — a fix landing during the freeze
     does NOT close the episode (freeze_state stays frozen with no
     CHANGE_CLOSED row anywhere), and the landings-since-open set read off
     the records is exactly the fix landings — the candidate-culprit set
     the next fix's repairs relation must name (goal 166).

Intent split (no intent-level duplication):
  - the may_land / ticket_outcome consumer faces of the repairs relation
    belong to t261009-63 (its scenario pins the face over a frozen ledger
    WITHOUT the landing act) — never re-asserted here beyond what the
    landing act itself must be proven to consult;
  - the relation ROW contract (evidence shape, recorder entitlement,
    correction mechanics) belongs to t261009-62;
  - freeze open/close DECISIONS (when a red opens one, the ladder) belong
    to t261009-30/-41 — this entry opens episodes only as fixture state
    through the engine's own writer;
  - the two-direction relation reader and promotion repairs naming belong
    to t261009-66.

Pre-implementation tree red = FAIL named (TDD signal: legs A/B/D fail on
today's main because the landing path never consults the freeze and the
signer face is not composed); green required at the integration gate /
merge. Engine modules unimportable = ENV_FAIL exit 2.
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
REPO = os.path.dirname(os.path.dirname(HERE))

ENGINE = os.path.join(REPO, "server", "engine")
if os.path.isdir(ENGINE):
    sys.path.insert(0, ENGINE)

try:
    import develop_certify as dc  # noqa: E402
    import develop_line as dl  # noqa: E402
    import shared  # noqa: E402
except Exception as exc:  # noqa: BLE001
    print("ENV_FAIL: engine modules unimportable (engine tree absent): %s"
          % exc)
    print("SUMMARY pass=0 fail=0 env_fail=1 na=0")
    sys.exit(2)

ADAPTER = os.path.join(REPO, "server", "plugins", "executor-panel", "src",
                       "host", "certification-adapter.py")
if not os.path.isfile(ADAPTER):
    print("ENV_FAIL: certification adapter missing: %s" % ADAPTER)
    print("SUMMARY pass=0 fail=0 env_fail=1 na=0")
    sys.exit(2)

PASS = 0
FAIL = 0
TMPDIRS = []

LINE = "buffer"
OTHER_LINE = "sandbox"


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS %s" % name)
    else:
        FAIL += 1
        print("FAIL %s%s" % (name, (": " + str(detail)) if detail else ""))


# ------------------------------------------------------------------ fixtures

def _git(*args, cwd, check_rc=True):
    p = subprocess.run(["git"] + list(args), cwd=str(cwd),
                       capture_output=True, text=True)
    if check_rc and p.returncode != 0:
        raise AssertionError("git %s failed: %s" % (" ".join(args), p.stderr))
    return p


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
    repo = str(repo)
    _git("checkout", "-B", branch, "main", cwd=repo)
    with open(os.path.join(repo, fname), "w") as fh:
        fh.write(text)
    _git("add", "-A", cwd=repo)
    _git("commit", "-m", msg, cwd=repo)
    return _git("rev-parse", "HEAD", cwd=repo).stdout.strip()


def _declare(project, tmp):
    decl = [
        {"line_id": LINE, "scope": "epic x", "owner": "integration",
         "repositories": [{"name": "r", "branch": "develop"}],
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
    rows, bad = dc.read_rows(dc.ledger_path(project))
    return rows, bad


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


def _landing_row(lid, ticket, line, revision, at, actor="engine"):
    return {"kind": dc.KIND_LANDING, "id": lid, "ticket": ticket,
            "line": line, "actor": actor, "at": at,
            "repos": [{"repo": "r", "revision": revision}]}


def _repairs_row(rel_id, from_ticket, to_ref, at, evidence_what="landing"):
    what = evidence_what if evidence_what in dc.RELATION_EVIDENCE_WHATS \
        else "ticket"
    ref = to_ref if evidence_what != "patch_id" else "pid-1"
    return {"kind": dc.REL_KIND_REPAIRS, "id": rel_id,
            "from": from_ticket, "to": to_ref,
            "recorded_by": "patrol",
            "reason": "repairs the landing that turned the line red",
            "evidence": {"what": what, "ref": ref}, "at": at}


def _freeze_fixture(project, revision, at):
    """Open a freeze episode through the engine's own writer: a red cert on
    the line + the episode keyed to it (fixture state; the DECISION to
    open belongs to t261009-30/-41 and is not re-asserted)."""
    cert = _cert_row("cert-" + "0" * 24, LINE, revision, at)
    _append(project, [cert])
    frz = dc.open_freeze_rows(cert, at_ms=at + 1)[0]
    _append(project, [frz])
    return cert["id"], frz["id"]


class _Env:
    """One isolated project: temp projects dir, temp delivery ledger, one
    real git repo declared on the line."""

    def __init__(self):
        self.tmp = tempfile.mkdtemp(prefix="t26100967-")
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
        self.old_proj = os.environ.get("SANDBAR_PROJECTS_DIR")
        self.old_ledger = os.environ.get("SANDBAR_DELIVERY_LEDGER_DIR")
        self.old_runs = os.environ.get("SANDBAR_RUNS_LEDGER")
        os.environ["SANDBAR_PROJECTS_DIR"] = self.projects
        os.environ["SANDBAR_DELIVERY_LEDGER_DIR"] = self.ledger
        os.environ["SANDBAR_RUNS_LEDGER"] = self.runs
        self.project = "proj"
        _declare(self.project, self.tmp)
        self.repo = Path(_init_repo(os.path.join(self.tmp, "repo")))
        self.line = dl.load_line(self.project, LINE)

    def cleanup(self):
        if self.old_proj is not None:
            os.environ["SANDBAR_PROJECTS_DIR"] = self.old_proj
        else:
            os.environ.pop("SANDBAR_PROJECTS_DIR", None)
        if self.old_ledger is not None:
            os.environ["SANDBAR_DELIVERY_LEDGER_DIR"] = self.old_ledger
        else:
            os.environ.pop("SANDBAR_DELIVERY_LEDGER_DIR", None)
        if self.old_runs is not None:
            os.environ["SANDBAR_RUNS_LEDGER"] = self.old_runs
        else:
            os.environ.pop("SANDBAR_RUNS_LEDGER", None)


def _landing_ids(project, line_id=LINE):
    rows, bad = _rows(project)
    assert not bad, bad
    return [r["id"] for r in rows
            if r.get("kind") == dc.KIND_LANDING and r.get("line") == line_id]


def _row_count(project):
    rows, _ = _rows(project)
    return len(rows)


# ---------------------------------------------------------------- A: refusal

def leg_a(env):
    """A frozen line refuses a landing BY NAME; nothing merges, nothing is
    appended; a self-declared fix reads as the same refusal."""
    rev = _lane_commit(env.repo, "a.txt", "one\n", "lane work")
    before = _row_count(env.project)
    cert_id, frz_id = _freeze_fixture(env.project, rev, 1791507005123)

    # A1 the plain landing is refused, naming the episode and the cause.
    refused_msg = ""
    landed = False
    try:
        res = dl.land_ticket(env.line, env.project, {"r": env.repo},
                             "t-plain", "engine")
        landed = bool(getattr(res, "ok", False))
    except dl.LandingError as e:
        refused_msg = str(e)
    except Exception as e:  # noqa: BLE001
        refused_msg = "%s: %s" % (type(e).__name__, e)
    check("A1 frozen-line landing refused (pre-implement red is the TDD "
          "signal)", (not landed) and bool(refused_msg), refused_msg)
    check("A2 refusal names the freeze episode id", frz_id in refused_msg,
          refused_msg)
    check("A3 refusal names the cause certification id",
          cert_id in refused_msg, refused_msg)

    # A4 nothing was merged into the line and nothing was appended.
    check("A4 zero records appended on refusal",
          _row_count(env.project) == before + 2, _row_count(env.project))
    branched = _git("rev-parse", "--verify", "develop", cwd=env.repo,
                    check_rc=False)
    check("A5 lane repo untouched (no line branch created, HEAD still lane)",
          branched.returncode != 0
          and _git("rev-parse", "--abbrev-ref", "HEAD",
                   cwd=env.repo).stdout.strip() == "lane")

    # A6 a ticket that merely calls itself a fix gets the SAME refusal:
    # nothing the ticket says about itself is consulted (no kind parameter
    # exists at the landing act to lie about).
    msg2 = ""
    landed2 = False
    try:
        res = dl.land_ticket(env.line, env.project, {"r": env.repo},
                             "t-fix-i-declare-myself", "engine")
        landed2 = bool(getattr(res, "ok", False))
    except dl.LandingError as e:
        msg2 = str(e)
    except Exception as e:  # noqa: BLE001
        msg2 = "%s: %s" % (type(e).__name__, e)
    check("A6 self-declared fix refused (pre-implement red = it walked "
          "past)", (not landed2) and bool(msg2), msg2)
    check("A7 self-declared refusal carries the same freeze facts",
          frz_id in msg2 and cert_id in msg2, msg2)


# ------------------------------------------------------- B: structural exempt

def leg_b(env):
    """The exemption is the recorded repairs relation, judged at the
    landing act: current same-line relation lands, superseded and
    cross-line do not; the unfrozen control stays byte-normal."""
    base_rev = _git("rev-parse", "HEAD", cwd=env.repo).stdout.strip()

    # Control first: the UNFROZEN line lands exactly as before.
    _lane_commit(env.repo, "ctl.txt", "control\n", "control work")
    try:
        res = dl.land_ticket(env.line, env.project, {"r": env.repo},
                             "t-ctl", "engine")
        ok = bool(getattr(res, "ok", False))
    except Exception as e:  # noqa: BLE001
        ok = False
        print("  control landing raised: %s" % e)
    check("B0 unfrozen line lands unchanged (control)",
          ok and len(_landing_ids(env.project)) == 1,
          _landing_ids(env.project))
    control_ldg = _landing_ids(env.project)[0]

    # Fixture landing that the freeze implicates (the culprit on record).
    culprit_rev = _lane_commit(env.repo, "culprit.txt", "bad\n", "culprit")
    _append(env.project, [_landing_row("ldg-" + "0" * 26, "t-culprit", LINE,
                                       culprit_rev, 1791507005999)])
    cert_id, frz_id = _freeze_fixture(env.project, base_rev,
                                      1791507015123)

    # B1 current same-line repairs relation -> the fix lands.
    _lane_commit(env.repo, "fix.txt", "fixed\n", "the fix")
    _append(env.project, [_repairs_row("rel-" + "0" * 24, "t-fix1",
                                       control_ldg, 1791507025000)])
    try:
        res = dl.land_ticket(env.line, env.project, {"r": env.repo},
                             "t-fix1", "engine")
        ok = bool(getattr(res, "ok", False))
    except Exception as e:  # noqa: BLE001
        ok = False
        print("  fix landing raised: %s" % e)
    check("B1 fix with current same-line repairs relation lands "
          "(pre-implement red is the TDD signal)", ok,
          _landing_ids(env.project))
    rows, _ = _rows(env.project)
    fix_ldgs = [r["id"] for r in rows if r.get("kind") == dc.KIND_LANDING
                and r.get("ticket") == "t-fix1"]
    check("B2 the fix landing is recorded once",
          len(fix_ldgs) == 1, fix_ldgs)

    # B3 superseded relation grants nothing.
    supersedes = {"kind": dc.REL_KIND_SUPERSEDES, "id": "rel-" + "1" * 24,
                  "from": "t-fixer", "to": "rel-" + "0" * 24,
                  "recorded_by": "patrol",
                  "reason": "correction: wrong culprit named",
                  "evidence": {"what": "ticket", "ref": "t-culprit"},
                  "at": 1791507035000}
    _append(env.project, [supersedes])
    _lane_commit(env.repo, "fix2.txt", "fix2\n", "the second fix")
    msg = ""
    landed = False
    try:
        res = dl.land_ticket(env.line, env.project, {"r": env.repo},
                             "t-fix2", "engine")
        landed = bool(getattr(res, "ok", False))
    except dl.LandingError as e:
        msg = str(e)
    except Exception as e:  # noqa: BLE001
        msg = "%s: %s" % (type(e).__name__, e)
    check("B3 superseded repairs relation does not exempt (pre-implement "
          "red = walked past)", (not landed) and frz_id in msg, msg)

    # B4 a relation naming a landing on ANOTHER line is a scoping refusal.
    _append(env.project, [_landing_row("ldg-" + "1" * 26, "t-other",
                                       OTHER_LINE, base_rev,
                                       1791507045000)])
    rel3 = _repairs_row("rel-" + "3" * 24, "t-fix3", "ldg-" + "1" * 26,
                        1791507046000)
    _append(env.project, [rel3])
    _lane_commit(env.repo, "fix3.txt", "fix3\n", "the third fix")
    msg = ""
    landed = False
    try:
        res = dl.land_ticket(env.line, env.project, {"r": env.repo},
                             "t-fix3", "engine")
        landed = bool(getattr(res, "ok", False))
    except dl.LandingError as e:
        msg = str(e)
    except Exception as e:  # noqa: BLE001
        msg = "%s: %s" % (type(e).__name__, e)
    check("B4 cross-line repair target refused on this line's freeze "
          "(pre-implement red = walked past)",
          (not landed) and frz_id in msg, msg)


# --------------------------------------------------- C: could-not-run is not red

def leg_c(env):
    """After a range-growth row the line still lands; no freeze exists;
    the growth is a recorded row the next certification must cover."""
    rows_before = _row_count(env.project)
    _append(env.project, [dc.could_not_run_row(
        LINE, "runner died before any case executed", at_ms=1791507055000)])
    check("C1 growth is a recorded row (never a freeze)",
          any(r.get("kind") == dc.KIND_RANGE_GROWTH
              for r in _rows(env.project)[0]))
    rows, _ = _rows(env.project)
    check("C2 no freeze episode was opened by the unavailable proof",
          not dc.freeze_state(rows, LINE)["frozen"])
    _lane_commit(env.repo, "after-cnr.txt", "grew\n", "lands after cnr")
    try:
        res = dl.land_ticket(env.line, env.project, {"r": env.repo},
                             "t-after-cnr", "engine")
        ok = bool(getattr(res, "ok", False))
    except Exception as e:  # noqa: BLE001
        ok = False
        print("  landing after growth raised: %s" % e)
    check("C3 the line keeps landing while the proof was unavailable "
          "(pre-implement green expected)", ok, _landing_ids(env.project))
    rows, _ = _rows(env.project)
    rng = dc.derive_range(rows, LINE)
    covered = [l.get("ticket") for l in (rng.get("covered_landings") or [])]
    check("C4 the landings after the growth sit in the range the next "
          "certification must cover", "t-after-cnr" in covered, rng)


# ------------------------------------------------------------ D: signer face

def _run_adapter(env):
    p = subprocess.run([sys.executable, "-B", ADAPTER, env.project],
                       capture_output=True, text=True, cwd=REPO)
    if p.returncode != 0:
        return None, "adapter exit %s: %s" % (p.returncode, p.stderr[-400:])
    try:
        return json.loads(p.stdout), ""
    except ValueError as e:
        return None, "adapter output not JSON: %s" % e


def leg_d(env):
    """The signer face names the freeze, its cause and the fix chain —
    through the model face (contract name on develop_certify) and through
    the REAL adapter subprocess the panel invokes."""
    rev = _git("rev-parse", "HEAD", cwd=env.repo).stdout.strip()
    culprit_rev = _lane_commit(env.repo, "d-culprit.txt", "bad\n", "d culprit")
    _append(env.project, [_landing_row("ldg-" + "2" * 26, "t-d-culprit",
                                       LINE, culprit_rev, 1791507065000)])
    cert_id, frz_id = _freeze_fixture(env.project, rev, 1791507075000)
    _append(env.project, [dc.freeze_change_row(
        frz_id, dc.CHANGE_ATTRIBUTION, "patrol", "bisect named the landing",
        value="ldg-" + "2" * 26, at_ms=1791507085000, line=LINE)])
    _append(env.project, [_repairs_row("rel-" + "4" * 24, "t-d-fix",
                                       "ldg-" + "2" * 26, 1791507095000)])

    # D1 the model face exists under its contract name and answers.
    summary = getattr(dc, "open_freeze_summary", None)
    if summary is None:
        check("D1 signer face open_freeze_summary exists (pre-implement "
              "red is the TDD signal)", False, "attribute missing")
        return
    rows, _ = _rows(env.project)
    s = summary(rows, LINE)
    check("D2 face says frozen with the episode id", s.get("frozen") is True
          and s.get("freeze") == frz_id, s)
    check("D3 face names the cause certification", s.get("cause") == cert_id,
          s)
    check("D4 face names the attributed culprit landing",
          "ldg-" + "2" * 26 in json.dumps(s), s)
    check("D5 face names the fix that reopens it",
          "t-d-fix" in json.dumps(s), s)

    # D6 the REAL adapter (reader side) reports the freeze to the signer.
    receipt, why = _run_adapter(env)
    if receipt is None:
        check("D6 adapter receipt readable", False, why)
        return
    check("D6 adapter receipt readable (reader side, from disk)", True, why)
    check("D7 adapter receipt carries the open freeze on the line",
          frz_id in json.dumps(receipt) and cert_id in json.dumps(receipt),
          json.dumps(receipt)[:400])

    # D8 a malformed freeze row degrades NAMED, never a crash, never a
    # fabricated freeze (reader-side discipline).
    env2 = _Env()
    try:
        bad = os.path.join(env2.ledger, env2.project + ".jsonl")
        with open(bad, "a") as fh:
            fh.write('{"kind":"freeze","id":"not-a-frz"}\n')
            fh.write("{torn\n")
        receipt2, why2 = _run_adapter(env2)
        if receipt2 is None:
            check("D8 malformed rows degrade named in the receipt", False,
                  why2)
        else:
            blob = json.dumps(receipt2)
            check("D8 malformed rows degrade NAMED (fail closed, never a "
                  "guessed freeze)",
                  "malformed" in blob.lower(), blob[:400])
        check("D9 adapter never crashed on the malformed ledger",
              receipt2 is not None, why2)
    finally:
        env2.cleanup()


# ------------------------------------------------------- E: the chain visible

def leg_e(env):
    """A fix landing during the freeze keeps the freeze open; the
    landings-since-open set read off the records IS the fix chain."""
    rev = _git("rev-parse", "HEAD", cwd=env.repo).stdout.strip()
    culprit_rev = _lane_commit(env.repo, "e-culprit.txt", "bad\n", "e culprit")
    _append(env.project, [_landing_row("ldg-" + "3" * 26, "t-e-culprit",
                                       LINE, culprit_rev, 1791507115000)])
    cert_id, frz_id = _freeze_fixture(env.project, rev, 1791507125000)
    _append(env.project, [_repairs_row("rel-" + "5" * 24, "t-e-fix1",
                                       "ldg-" + "3" * 26, 1791507135000)])
    _lane_commit(env.repo, "e-fix1.txt", "f1\n", "first fix")
    try:
        res = dl.land_ticket(env.line, env.project, {"r": env.repo},
                             "t-e-fix1", "engine")
        ok1 = bool(getattr(res, "ok", False))
    except Exception as e:  # noqa: BLE001
        ok1 = False
        print("  first fix landing raised: %s" % e)
    check("E1 first fix lands during the freeze", ok1,
          _landing_ids(env.project))

    rows, _ = _rows(env.project)
    st = dc.freeze_state(rows, LINE)
    check("E2 the freeze stays open after a fix landing (no closed change)",
          st.get("frozen") is True
          and not any(r.get("kind") == dc.KIND_FREEZE_CHANGE
                      and r.get("change") == dc.CHANGE_CLOSED
                      for r in rows), st)

    summary = getattr(dc, "open_freeze_summary", None)
    if summary is not None:
        s = summary(rows, LINE)
        chain = json.dumps(s.get("fix_landings") or s)
        check("E3 the chain names the first fix's landing",
              "t-e-fix1" in chain, s)
    else:
        check("E3 the chain names the first fix's landing (face missing "
              "pre-implement)", False, "open_freeze_summary missing")

    # The candidate-culprit set for the NEXT fix: landings since the
    # episode opened, read off the records.
    rows, _ = _rows(env.project)
    opened_at = next(r["at"] for r in rows if r.get("id") == frz_id)
    since = [r["ticket"] for r in rows
             if r.get("kind") == dc.KIND_LANDING
             and r.get("line") == LINE and r.get("at", 0) >= opened_at]
    check("E4 landings since open = exactly the fix chain (the next fix "
          "names the previous fix)", since == ["t-e-fix1"], since)

    # Second fix names the first fix's landing as its candidate culprit.
    first_fix_ldg = [r["id"] for r in rows
                     if r.get("kind") == dc.KIND_LANDING
                     and r.get("ticket") == "t-e-fix1"]
    if first_fix_ldg and summary is not None:
        _append(env.project, [_repairs_row("rel-" + "6" * 24, "t-e-fix2",
                                           first_fix_ldg[0],
                                           1791507145000)])
        _lane_commit(env.repo, "e-fix2.txt", "f2\n", "second fix")
        try:
            res = dl.land_ticket(env.line, env.project, {"r": env.repo},
                                 "t-e-fix2", "engine")
            ok2 = bool(getattr(res, "ok", False))
        except Exception as e:  # noqa: BLE001
            ok2 = False
            print("  second fix landing raised: %s" % e)
        rows, _ = _rows(env.project)
        s = summary(rows, LINE)
        check("E5 second fix (repairs the first fix's landing) lands and "
              "the chain shows both", ok2 and "t-e-fix2" in json.dumps(s),
              json.dumps(s)[:400])
    else:
        check("E5 second fix leg runnable (pre-implement red)", False,
              "first fix landing missing")


def main():
    print("== t261009-67 the freeze actually stops landings ==")
    for name, fn in (("A frozen line refuses a landing by name", leg_a),
                     ("B structural exemption via the repairs relation",
                      leg_b),
                     ("C could-not-run is not red on the landing path",
                      leg_c),
                     ("D the freeze is visible to the signer", leg_d),
                     ("E the chain of fixes stays visible", leg_e)):
        env = _Env()
        try:
            print("-- leg %s" % name)
            fn(env)
        except Exception as exc:  # noqa: BLE001
            check("leg %s completed" % name, False,
                  "%s: %s" % (type(exc).__name__, exc))
        finally:
            env.cleanup()
    for d in TMPDIRS:
        shutil.rmtree(d, ignore_errors=True)
    print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
