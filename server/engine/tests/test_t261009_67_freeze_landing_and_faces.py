#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261009-67 — the freeze actually stops landings (and is visible to the
signer). Design: docs/design/develop-buffer-v1.md items 16/17/24/95/160-168.

Behaviours, each with a receipt:

1. The landing act consults the freeze (goal 16): on a frozen line a landing
   that is not the structural exemption is refused BY NAME, carrying the
   freeze episode id and the cause certification — and the refusal fires
   BEFORE any worktree mutation (nothing merged, nothing appended). Proven
   on the real path: real `git init` repos, the real delivery ledger, the
   real lock, the real ``land_ticket``.
2. The exemption stays STRUCTURAL (goals 17/95/168): the enforcement face
   takes no kind parameter — there is nothing a landing can claim about
   itself. The only path through a frozen line is a CURRENT ``repairs``
   relation naming a landing on THIS line; every gap is refused by name.
3. "Could not run" is not "red" (goal 24): a round whose runner raises
   ``CouldNotRun`` records range growth, opens NO freeze, leaves the line
   landing, and the next green certification's derived range covers the
   growth. Proven on the real round face (``run_line_round``).
4. The signer's face (goal 167): ``open_freeze_summary`` reads the open
   freeze, its cause certification, the derived culprit and the CHAIN OF
   FIXES off the ledger — with unresolved repair targets visible as gaps.
5. The chain of fixes stays visible (goal 166): a fix landing during a
   freeze leaves the freeze open; the landings-since-open set read off the
   records is exactly the fix landings (the next red's candidate culprits).

External-input discipline: hand-written ledger rows (including malformed
ones) over REAL temp delivery ledgers and real temp git repos; no external
source. Integration entries are NOT run here. Tests anchor on named
reasons and record ids, never on refusal-sentence wording (review
condition 1).
"""

import json
import sys
import unittest
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

import develop_certify as dc  # noqa: E402
import develop_line as dl  # noqa: E402
import shared  # noqa: E402

LINE = "develop"
EV_TICKET = {"what": "ticket", "ref": "t1"}


def landing(ticket="t1", line=LINE, lid="ldg-a01", at=1000, rev="rev1",
            seq=1):
    return {"kind": dc.KIND_LANDING, "id": lid, "ticket": ticket,
            "line": line, "repos": [{"repo": "sandbar", "revision": rev}],
            "actor": "test", "at": at, "seq": seq}


def cert(cid="cert-01", at=2000, seq=2):
    return {"kind": dc.KIND_CERT, "id": cid, "line": LINE,
            "repos": [{"repo": "sandbar", "revision": "rev1"}],
            "run": "run-01", "at": at, "seq": seq}


def repair(**kw):
    base = {"id": "rel-r01", "from": "t2", "to": "t1",
            "kind": dc.REL_KIND_REPAIRS, "recorded_by": "host",
            "reason": "fixes t1's landing", "evidence": dict(EV_TICKET),
            "at": 1791510000000}
    base.update(kw)
    return base


def frozen_rows(extra=()):
    """A frozen line: landing + cert + episode + its open-state change."""
    return [landing(), cert(),
            {"kind": dc.KIND_FREEZE, "id": "frz-01", "line": LINE,
             "cause": "cert-01", "seq": 3, "at": 3000},
            {"kind": dc.KIND_FREEZE_CHANGE, "id": "frzc-01", "line": LINE,
             "freeze": "frz-01", "change": "attribution",
             "value": "boundary, culprit not isolated", "seq": 4, "at": 3001}
            ] + list(extra)


# ----------------------------------------------- (2) the structural face itself

class LandingFreezeFaceTest(unittest.TestCase):
    """``landing_freeze_face``: the landing act's judge. No kind parameter —
    pinned by signature, because a claimable kind is the hole item 17 bans."""

    def test_face_takes_no_kind_parameter(self):
        import inspect
        params = inspect.signature(dc.landing_freeze_face).parameters
        assert "kind" not in params and "ticket_kind" not in params
        assert set(params) == {"rows", "line", "ticket_id", "patch_ids"}

    def test_unfrozen_line_allows_every_landing(self):
        face = dc.landing_freeze_face([], LINE, "t9")
        assert face == {"allowed": True, "reason": "", "freeze": None,
                        "cause": None, "relation": None, "repaired": None}
        closed = frozen_rows([{"kind": dc.KIND_FREEZE_CHANGE,
                               "id": "frzc-02", "line": LINE,
                               "freeze": "frz-01", "change": "closed",
                               "by": "host", "reason": "green round",
                               "seq": 5, "at": 4000}])
        assert dc.landing_freeze_face(closed, LINE, "t9")["allowed"] is True

    def test_frozen_line_without_relation_refused_by_name_with_ids(self):
        face = dc.landing_freeze_face(frozen_rows(), LINE, "t9")
        assert face["allowed"] is False
        assert face["reason"] == "freeze_landing_refused"
        assert face["freeze"] == "frz-01"
        assert face["cause"] == "cert-01"

    def test_relation_naming_the_line_grants_with_the_repaired_landing(self):
        face = dc.landing_freeze_face(frozen_rows([repair()]), LINE, "t2")
        assert face["allowed"] is True and face["reason"] == ""
        assert face["relation"] == "rel-r01"
        assert face["repaired"] == "ldg-a01"

    def test_relation_naming_the_landing_by_id_grants(self):
        rel = repair(to="ldg-a01")
        face = dc.landing_freeze_face(frozen_rows([rel]), LINE, "t2")
        assert face["allowed"] is True and face["repaired"] == "ldg-a01"

    def test_patch_named_relation_grants_only_with_the_map(self):
        rel = repair(to="patch:abc", evidence={"what": "patch_id",
                                               "ref": "p-123"})
        face = dc.landing_freeze_face(frozen_rows([rel]), LINE, "t2")
        assert face["allowed"] is False
        assert face["reason"].startswith("repair_target_unresolved:")
        assert face["freeze"] == "frz-01" and face["cause"] == "cert-01"
        face = dc.landing_freeze_face(frozen_rows([rel]), LINE, "t2",
                                      patch_ids={"ldg-a01": "p-123"})
        assert face["allowed"] is True and face["repaired"] == "ldg-a01"

    def test_superseded_relation_is_not_an_exemption(self):
        # a correction by ANOTHER ticket drops the relation out of the
        # current set — the corrected ticket's exemption dies with it.
        sup = repair(id="rel-r03", **{"from": "t3"},
                     **{"to": "ldg-a01"},
                     supersedes_relation="rel-r01")
        face = dc.landing_freeze_face(frozen_rows([repair(), sup]),
                                      LINE, "t2")
        assert face["allowed"] is False
        assert face["reason"] == "freeze_landing_refused"

    def test_cross_line_target_is_no_exemption_on_this_line(self):
        rows = frozen_rows([landing(ticket="t1", line="docs",
                                    lid="ldg-d01", at=1001)])
        face = dc.landing_freeze_face(rows + [repair(to="ldg-d01")],
                                      LINE, "t2")
        assert face["allowed"] is False
        assert face["reason"].startswith("repair_target_unresolved:")

    def test_malformed_inputs_refused_by_name(self):
        with pytest.raises(dc.CertifyError):
            dc.landing_freeze_face(frozen_rows(), "", "t2")
        with pytest.raises(dc.CertifyError):
            dc.landing_freeze_face(frozen_rows(), LINE, "")
        with pytest.raises(dc.CertifyError):
            dc.landing_freeze_face(frozen_rows(), LINE, "t2",
                                   patch_ids="p-123")

    def test_malformed_rows_never_crash_the_face(self):
        rows = frozen_rows([None, 7, "junk", {"kind": "landing"}])
        face = dc.landing_freeze_face(rows, LINE, "t9")
        assert face["allowed"] is False
        assert face["reason"] == "freeze_landing_refused"


# ------------------------------------------- (4)+(5) the signer's freeze face

class OpenFreezeSummaryTest(unittest.TestCase):
    """``open_freeze_summary``: what the promotion signer reads."""

    def test_unfrozen_line_shows_no_freeze(self):
        s = dc.open_freeze_summary([], LINE)
        assert s["frozen"] is False and s["fix_landings"] == []\
            and s["pending_fixes"] == []
        with pytest.raises(dc.CertifyError):
            dc.open_freeze_summary([], "")

    def test_signer_sees_freeze_cause_and_chain(self):
        # t1 landed BEFORE the freeze; t2 (fix) and t3 (fix of the fix) during.
        fix_ldg = landing(ticket="t2", lid="ldg-f01", at=3500, rev="rev2")
        fix2_ldg = landing(ticket="t3", lid="ldg-f02", at=3600, rev="rev3")
        rows = frozen_rows([
            fix_ldg, fix2_ldg,
            repair(),                                        # t2 repairs t1
            repair(id="rel-r02", **{"from": "t3", "to": "ldg-f01"}),
        ])
        s = dc.open_freeze_summary(rows, LINE)
        assert s["frozen"] is True
        assert s["freeze"] == "frz-01" and s["cause"] == "cert-01"
        assert s["culprit"] == "boundary, culprit not isolated"
        assert s["opened_at"] == 3000
        # landings-since-open = the fix landings exactly (goal 166); the
        # pre-freeze landing is NOT in the chain.
        assert [f["landing"] for f in s["fix_landings"]] == \
            ["ldg-f01", "ldg-f02"]
        assert s["fix_landings"][0]["repairs"] == \
            [{"id": "rel-r01", "repaired": "ldg-a01"}]
        assert s["fix_landings"][1]["repairs"] == \
            [{"id": "rel-r02", "repaired": "ldg-f01"}]

    def test_recorded_but_not_yet_landed_fix_is_visible(self):
        # item 167's "or will reopen": the relation exists, the landing does
        # not — the signer still sees which fix is coming.
        s = dc.open_freeze_summary(frozen_rows([repair(**{"from": "t-coming"})]),
                                   LINE)
        assert s["pending_fixes"] == [{"ticket": "t-coming",
                                       "relation": "rel-r01"}]

    def test_unresolved_repair_stays_a_visible_gap(self):
        rel = repair(to="patch:x", evidence={"what": "patch_id",
                                             "ref": "p-9"})
        s = dc.open_freeze_summary(frozen_rows([landing(ticket="t2",
                                                        lid="ldg-f01",
                                                        at=3500),
                                                rel]), LINE)
        assert s["fix_landings"][0]["repairs"] == \
            [{"id": "rel-r01", "repaired": None}]

    def test_malformed_rows_never_crash_the_summary(self):
        s = dc.open_freeze_summary(frozen_rows([None, 7, {"kind": "landing"}]),
                                   LINE)
        assert s["frozen"] is True and s["fix_landings"] == []


# --------------------------------------- (3) could-not-run is not red (goal 24)

def _green(ran=10):
    return {"id": dc.mint_id("run"), "cases": {"ran": ran, "failed": 0,
                                               "env_failed": 0}}


def _ldg(rev, ticket="t1"):
    return {"kind": dc.KIND_LANDING, "id": dc.mint_id("ldg"),
            "ticket": ticket, "line": LINE,
            "repos": [{"repo": "sandbar", "revision": rev}],
            "actor": "test", "at": 1}


def test_could_not_run_grows_range_opens_no_freeze_and_still_lands(tmp_path):
    path = tmp_path / "delivery.jsonl"
    read = lambda: dc.read_rows(path)  # noqa: E731
    append = lambda batch: dc.append_rows(batch, path)  # noqa: E731
    append([_ldg("rev1")])
    guard = tmp_path / "guard.json"

    def boom(candidate):
        raise dc.CouldNotRun("runner_timeout:1s")

    out = dc.run_line_round(LINE, "change", guard, boom, read, append,
                            "judge", "inv-v1", now_ms=1000)
    assert out["rounds"][-1]["state"] == dc.STATE_GREW
    rows, _ = read()
    growth = [r for r in rows if r.get("kind") == dc.KIND_RANGE_GROWTH]
    assert growth and all(g["line"] == LINE for g in growth)
    # no red, no freeze, nothing that stops landings (goal 24)
    assert not [r for r in rows if r.get("kind") == dc.KIND_FREEZE]
    assert dc.freeze_state(rows, LINE)["frozen"] is False
    # the range the next certification must cover still holds the landing
    assert [l["ticket"] for l in dc.derive_range(rows, LINE)
            ["covered_landings"]] == ["t1"]

    # the next (green) round certifies the SAME range: the growth is real
    def ok(candidate):
        assert [c["revision"] for c in candidate] == ["rev1"]
        return _green()

    out2 = dc.run_line_round(LINE, "change", guard, ok, read, append,
                             "judge", "inv-v1", now_ms=2000)
    assert out2["rounds"][-1]["state"] == dc.STATE_CERTIFIED
    rows2, _ = read()
    assert len(dc._of_kind(rows2, dc.KIND_CERT, LINE)) == 1
    assert dc.derive_range(rows2, LINE)["covered_landings"] == []
    # the line was never frozen: landings stay legal throughout
    assert dc.landing_freeze_face(rows2, LINE, "t2")["allowed"] is True


# --------------------------------- (1) the landing act consults the freeze

def _git(*args, cwd):
    import subprocess
    p = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                       text=True)
    assert p.returncode == 0, (args, p.stderr)
    return p.stdout.strip()


@pytest.fixture()
def landing_env(tmp_path, monkeypatch):
    """A declared line, a real lane repo and a REAL delivery ledger — the
    whole landing act without any integration entry."""
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(tmp_path / "projects"))
    monkeypatch.setenv("SANDBAR_DELIVERY_LEDGER_DIR", str(tmp_path / "ledger"))
    repo = tmp_path / "lane"
    repo.mkdir()
    _git("init", "-b", "main", cwd=repo)
    _git("config", "user.email", "t@example.test", cwd=repo)
    _git("config", "user.name", "t", cwd=repo)
    (repo / "a.txt").write_text("hi\n", encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-m", "seed", cwd=repo)
    # the lane works on its own branch; the LINE branch exists but is never
    # checked out in the lane repo (the landing seeds its own worktree for it)
    _git("branch", "develop", cwd=repo)
    _git("checkout", "-B", "lane", cwd=repo)
    decl = [{"line_id": LINE, "scope": "epic x", "owner": "integration",
             "repositories": [{"name": "r", "branch": "develop"}],
             "extra_scenarios": [], "version": 1}]
    d = shared.develop_dir("proj")
    d.mkdir(parents=True, exist_ok=True)
    (d / "lines.json").write_text(json.dumps(decl), encoding="utf-8")
    line = dl.load_line("proj", LINE)
    return {"repo": repo, "line": line,
            "base": _git("rev-parse", "HEAD", cwd=repo),
            "ledger": dl.ledger_path("proj")}


def _freeze_ledger(ledger, base):
    """A frozen line on the REAL ledger: a certification of the base
    revision, the freeze episode, its open state."""
    dc.append_rows([
        {"kind": dc.KIND_LANDING, "id": dc.mint_id("ldg"), "ticket": "t9",
         "line": LINE, "repos": [{"repo": "r", "revision": base}],
         "actor": "test", "at": 1500},
        {"kind": dc.KIND_CERT, "id": dc.mint_id("cert"), "line": LINE,
         "repos": [{"repo": "r", "revision": base}], "run": "run-x",
         "booked_red": "inv", "judged_by": "test", "at": 2000},
        {"kind": dc.KIND_FREEZE, "id": dc.mint_id("frz"), "line": LINE,
         "cause": "cert-unknown", "at": 3000},
    ], ledger)


def _commit_lane(repo, msg="work"):
    (repo / "b.txt").write_text("w\n", encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-m", msg, cwd=repo)
    return _git("rev-parse", "HEAD", cwd=repo)


def test_frozen_line_refuses_a_plain_landing_by_name(landing_env):
    env = landing_env
    _freeze_ledger(env["ledger"], env["base"])
    _commit_lane(env["repo"])
    before = _git("rev-parse", "develop", cwd=env["repo"])
    with pytest.raises(dl.LineFrozenError) as ei:
        dl.land_ticket(env["line"], "proj", {"r": env["repo"]},
                       "t-plain", "tester")
    msg = str(ei.value)
    # named refusal carrying the freeze episode id and the cause certification
    assert "freeze_landing_refused" in msg
    frz = [r for r in dc.read_rows(env["ledger"])[0]
           if r.get("kind") == dc.KIND_FREEZE][0]
    assert frz["id"] in msg
    assert "cert-unknown" in msg
    # nothing mutated: the line tip did not move, no landing was recorded
    assert _git("rev-parse", "develop", cwd=env["repo"]) == before
    rows, _ = dc.read_rows(env["ledger"])
    assert not [r for r in rows if r.get("kind") == dc.KIND_LANDING
                and r.get("ticket") == "t-plain"]
    # and the line is still frozen for the next attempt (nothing consumed)
    assert dc.freeze_state(rows, LINE)["frozen"] is True


def test_structural_exemption_lands_through_the_freeze(landing_env):
    env = landing_env
    _freeze_ledger(env["ledger"], env["base"])
    _commit_lane(env["repo"])
    # the fix's repairs relation names the frozen line's own landing ("t9")
    # by ticket — recorded through the ledger's own writer, the only way an
    # exemption can ever exist.
    dc.append_rows([{"id": dc.mint_id("rel"), "from": "t-fix", "to": "t9",
                     "kind": dc.REL_KIND_REPAIRS, "recorded_by": "host",
                     "reason": "fixes the implicated landing",
                     "evidence": {"what": "ticket", "ref": "t9"},
                     "at": 1791510000000}], env["ledger"])
    res = dl.land_ticket(env["line"], "proj", {"r": env["repo"]},
                         "t-fix", "tester")
    assert res.ok is True
    rows, _ = dc.read_rows(env["ledger"])
    ldgs = [r for r in rows if r.get("kind") == dc.KIND_LANDING
            and r.get("ticket") == "t-fix"]
    assert len(ldgs) == 1
    # the line's tip now carries the fix
    assert _git("rev-parse", "develop", cwd=env["repo"]) != env["base"]
    # the freeze is untouched by the fix landing (goal 166: it closes only
    # on a recorded closure) and the signer's summary shows the chain
    assert dc.freeze_state(rows, LINE)["frozen"] is True
    s = dc.open_freeze_summary(rows, LINE)
    assert [f["ticket"] for f in s["fix_landings"]] == ["t-fix"]
