"""t261009-41 — the golden-fixture contract between the engine projections and
the Certification tab's pure model (review C1 placement: integration-layer L2
contract, inside the ticket write set).

The contract (plan v2 §2, review R2 binding): the model only shapes
presentation; its counts are arithmetic over engine-derived facts. This test
builds synthetic ledger rows, runs the REAL engine projections
(``freeze_state``, ``ticket_wait_state``, ``ticket_outcome`` from
``server/engine/develop_certify.py`` / ``develop_promote.py``) over them, and
serializes the exact input the model consumes to
``server/plugins/workbench/tests/fixtures/t261009-41-certification-fixture.json``.

The committed fixture is the contract surface:
- the node test (``t261009-41-certification-model.mjs``) feeds it through
  ``deriveCertificationFace`` and asserts the face;
- this test regenerates the fixture and asserts byte equality. If the engine
  changes an outcome rule, regeneration differs, this test fails, and the
  fixture (and any failed node assertion) names the drift — never silent.

Regenerate deliberately with ``SANDBAR_FIXTURE_REGEN=1`` after a sanctioned
engine change.

Scenario (mock-shaped, numbers declared here, not copied from the mock):
line ``develop-buffer``; tickets t261009-18/19 landed, covered by green
certification cert-A (run-green), promoted in prom-A (delivered); red
certification cert-B (run-red, 2 failures) opens freeze frz-A with the culprit
recorded; tickets t261009-20/21/22 landed after the red round — still waiting.
Expected model input facts: frozen=true, delivered=2, certified=2, waiting=3.
"""

import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ENGINE = REPO / "server" / "engine"
FIXTURE = (REPO / "server" / "plugins" / "workbench" / "tests" / "fixtures"
           / "t261009-41-certification-fixture.json")

sys.path.insert(0, str(ENGINE))

import develop_certify as dc  # noqa: E402
import develop_promote as dp  # noqa: E402

LINE = "develop-buffer"
T = 1791500000000  # base moment, ms
STEP = 60_000


def _repos(rev):
    return [{"repo": "sandbar", "revision": rev}]


def _landing(seq, ticket, rev, at):
    return {"kind": dc.KIND_LANDING, "id": "ldg-%s" % ticket, "ticket": ticket,
            "line": LINE, "repos": _repos(rev), "actor": "dev",
            "at": at, "seq": seq}


def _cert(seq, cid, run, rev, at, verdict_flag=True):
    return {"kind": dc.KIND_CERT, "id": cid, "line": LINE, "repos": _repos(rev),
            "run": run, "booked_red": "known-red@test", "judged_by": "pytest",
            "at": at, "seq": seq}


def _freeze_change(seq, frz, change, by, reason, at, value=None):
    row = {"kind": dc.KIND_FREEZE_CHANGE, "id": "fch-%d" % seq, "freeze": frz,
           "change": change, "by": by, "reason": reason, "at": at, "seq": seq,
           "line": LINE}
    if value is not None:
        row["value"] = value
    return row


def _promotion(seq, pid, cert, tickets, at):
    return {"kind": dp.KIND_PROMOTION, "id": pid, "certification": cert,
            "line": LINE, "repos": _repos("aaa11111"),
            "tickets": tickets, "main_before": _repos("aaa11111"),
            "main_after": _repos("bbb22222"), "signer": "host",
            "at": at, "seq": seq}


def build_rows():
    """Synthetic ledgers; order = the shared seq space of the delivery file."""
    delivery, promotions = [], []
    seq = 1
    # two landed tickets, covered by the green certification, then promoted
    delivery.append(_landing(seq, "t261009-18", "396b221a", T)); seq += 1
    delivery.append(_landing(seq, "t261009-19", "396b221a", T + STEP)); seq += 1
    # two tickets land on the line head before the green certification covers
    # it: contained in cert-A (revision equality), never promoted — the
    # promotable certified part. Landed BEFORE cert-A on purpose: landings in
    # a later red round's derived range read red_implicated, a different face.
    delivery.append(_landing(seq, "t261009-23", "396b221a", T + STEP + 30_000)); seq += 1
    delivery.append(_landing(seq, "t261009-24", "396b221a", T + STEP + 90_000)); seq += 1
    delivery.append(_cert(seq, "cert-A", "run-green", "396b221a", T + 2 * STEP)); seq += 1
    promotions.append(_promotion(1, "prom-A", "cert-A",
                                 ["t261009-18", "t261009-19"], T + 3 * STEP))
    # the red round: opens the freeze
    delivery.append(_cert(seq, "cert-B", "run-red", "396b221a", T + 4 * STEP,
                          verdict_flag=False)); seq += 1
    delivery.append({"kind": dc.KIND_FREEZE, "id": "frz-A", "line": LINE,
                     "cause": "cert-B", "at": T + 4 * STEP, "seq": seq}); seq += 1
    delivery.append(_freeze_change(seq, "frz-A", dc.CHANGE_ATTRIBUTION, "patrol",
                                   "red round cert-B", T + 4 * STEP,
                                   value="t260922-12-gate-ledger-debt-not-blocked"))
    seq += 1
    # three tickets land after the red round, on the line's new head — a
    # revision no green certification covers, so the engine reads them
    # waiting (containment is revision equality, develop_certify.landable)
    delivery.append(_landing(seq, "t261009-20", "22233344", T + 6 * STEP)); seq += 1
    delivery.append(_landing(seq, "t261009-21", "22233344", T + 7 * STEP)); seq += 1
    delivery.append(_landing(seq, "t261009-22", "22233344", T + 8 * STEP)); seq += 1
    return delivery, promotions


RUN_HEADERS = [
    {"id": "run-green", "repos": _repos("396b221a"), "source": "scheduled",
     "started_at": T - 5 * STEP,
     "cases": {"ran": 498, "passed": 498, "failed": 0, "env_failed": 0},
     "verdict": "green"},
    {"id": "run-red", "repos": _repos("396b221a"), "source": "scheduled",
     "started_at": T + 3 * STEP,
     "cases": {"ran": 498, "passed": 496, "failed": 2, "env_failed": 0},
     "verdict": "red"},
]

# ticket-store faces the tab renders beside the ids (data, untranslated)
TICKET_META = {
    "t261009-18": {"title": "Land a proven lane onto a declared line",
                   "epic": "develop-buffer"},
    "t261009-19": {"title": "Certify a line on a schedule",
                   "epic": "develop-buffer"},
    "t261009-20": {"title": "Guard the route change", "epic": "engine-hardening"},
    "t261009-21": {"title": "A ticket that is only waiting holds nothing",
                   "epic": "develop-buffer"},
    "t261009-22": {"title": "Draw the lane map", "epic": "console-ui"},
    "t261009-23": {"title": "Promote the certified part", "epic": "develop-buffer"},
    "t261009-24": {"title": "Chain the rounds", "epic": "develop-buffer"},
}


def build_fixture_input():
    """The exact input `deriveCertificationFace` consumes, engine-derived."""
    delivery, promotions = build_rows()
    green = {r["id"] for r in RUN_HEADERS if r["verdict"] == "green"}
    is_green = lambda run: run in green  # noqa: E731
    now_ms = T + 20 * STEP

    freeze = dc.freeze_state(delivery, LINE)
    landings = [r for r in delivery if r.get("kind") == dc.KIND_LANDING]
    wait_states = []
    for landing in landings:
        state = dc.ticket_wait_state(delivery, LINE, landing, is_green, now_ms)
        wait_states.append({"ticket": landing["ticket"], **state})
    outcomes = []
    tickets = sorted({l["ticket"] for l in landings})
    # t261009-29: promotions share the delivery ledger's one seq space, so the
    # outcome view takes ONE rows list (delivery rows + promotion rows).
    rows = delivery + promotions
    for ticket in tickets:
        view = dp.ticket_outcome(rows, ticket, is_green,
                                 ticket_record={"kind": "change"})
        outcomes.append({"ticket": ticket, "delivered_in": view["delivered_in"],
                         "ending": view["ending"]})
    return {
        "generated_by": "integration/t261009-41/test_model_fixture_contract.py",
        "input": {
            "line": {"line_id": LINE, "scope": "epic develop-buffer",
                     "owner": "host"},
            "freeze": freeze,
            "waitStates": wait_states,
            "outcomes": outcomes,
            "certs": [{k: r[k] for k in ("id", "run", "at")}
                      for r in delivery if r.get("kind") == dc.KIND_CERT],
            "runs": RUN_HEADERS,
            "ticketMeta": TICKET_META,
            "roundState": "idle",
        },
    }


def test_fixture_matches_engine_regeneration():
    fresh = build_fixture_input()
    text = json.dumps(fresh, indent=2, sort_keys=True) + "\n"
    if os.environ.get("SANDBAR_FIXTURE_REGEN") == "1":
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(text)
    assert FIXTURE.exists(), (
        "fixture missing; run with SANDBAR_FIXTURE_REGEN=1 to mint it")
    assert FIXTURE.read_text() == text, (
        "committed fixture drifted from the engine projections — regenerate "
        "with SANDBAR_FIXTURE_REGEN=1 only after a sanctioned engine change")


def test_fixture_facts_are_the_declared_scenario():
    fixture = json.loads(FIXTURE.read_text()) if FIXTURE.exists() \
        else build_fixture_input()
    inp = fixture["input"]
    assert inp["freeze"]["frozen"] is True
    certified = [w for w in inp["waitStates"] if w["state"] == dc.WAIT_CERTIFIED]
    waiting = [w for w in inp["waitStates"] if w["state"] == dc.WAIT_WAITING]
    delivered = [o for o in inp["outcomes"] if o["delivered_in"]]
    # 2 covered-and-promoted (delivered) + 2 covered-not-promoted (the
    # promotable certified part) + 3 waiting = 7 landed tickets
    assert len(certified) == 4 and len(waiting) == 3 and len(delivered) == 2
