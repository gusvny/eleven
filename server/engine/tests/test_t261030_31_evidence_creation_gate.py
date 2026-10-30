"""t261030-31 UT: the evidence declaration is judged at the creation face.

Incident (found while opening t261030-30): the first create carried a list-valued
`evidence.name` -- shared.quick_evidence_validate accepts lists -- but
TicketInput.evidence was annotated Dict[str, str]. The Temporal data converter
therefore could not decode the workflow input, and the ticket came out
unstartable AND uncancellable.

Behavior pinned here (the REAL client.cmd_ticket_start, stubbed _connect -- no
Temporal, no network):
  A. A malformed declaration is refused at creation, before _connect(), with the
     validator's named reason. The same declaration used to reach the workflow
     start and die in the input decode.
  B. A valid declaration (one name, or a list of names) travels VERBATIM into
     TicketInput and then decodes through the real SDK data converter, so the
     workflow input can never be the thing that fails.
  C. An absent declaration stays empty: the quickmanual `open` gate owns the
     evidence-absent block (design guardrail 3), so this face must not take that
     decision.

Run: repo root `server/engine/.venv/bin/python -m pytest \
server/engine/tests/test_t261030_31_evidence_creation_gate.py -q`.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmp_reclaim import mkdtemp_reclaimed  # noqa: E402  (registry + atexit reclaim)

import client  # noqa: E402
import shared  # noqa: E402

PROJECT_KEY = "evidence-gate"


def _mk_registry(root, key, name, dirs):
    d = Path(root) / key
    d.mkdir(parents=True)
    content = "schema: v1\nproject:\n  - key: %s\n    name: %s\n    dirs:\n" % (key, name)
    for p in dirs:
        content += "      - %s\n" % p
    (d / "project.yaml").write_text(content, encoding="utf-8")


@pytest.fixture()
def world(monkeypatch):
    """A registered single-repo project, so creation can derive the lane."""
    tmp = mkdtemp_reclaimed("t261030-31-evidence-")
    home = os.path.join(tmp, "home")
    os.makedirs(os.path.join(home, ".lane"))
    _mk_registry(os.path.join(tmp, "reg"), PROJECT_KEY, "evidence gate", [home])
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", os.path.join(tmp, "reg"))
    return SimpleNamespace(home=home)


class _FakeHandle:
    def __init__(self):
        self.started = None
        self.connect_calls = 0
        self.id = "fake-wf-id"
        self.result_run_id = "fake-run-id"

    async def start_workflow(self, cls, inp, **kw):
        self.started = (cls, inp, kw)
        return self


def _start(monkeypatch, **over):
    """Run the real creation entry with a stubbed Temporal connection."""
    fake = _FakeHandle()

    async def _fake_connect():
        fake.connect_calls += 1
        return fake

    monkeypatch.setattr(client, "_connect", _fake_connect)
    args = {
        "ticket_id": "t261030-31-ut",
        "template_id": "quickmanual-lane",
        "project": PROJECT_KEY,
        "title": "UT evidence creation gate",
        "write_set": ["server/engine/tests/"],
        "body": "x",
        # declared caller identity, same project: this battery judges the evidence
        # face, not the cross-project gate
        "caller_project": PROJECT_KEY,
    }
    args.update(over)
    out = asyncio.run(client.cmd_ticket_start(args))
    return out, fake


def _decode(inp):
    """Decode a TicketInput exactly as the workflow input is decoded."""
    from temporalio.converter import DataConverter
    conv = DataConverter.default.payload_converter
    return conv.from_payloads(conv.to_payloads([inp]), [shared.TicketInput])[0]


# ---- A. malformed declarations are refused at creation ----------------------

@pytest.mark.parametrize("bad,frag", [
    (["a", "b"], "must be an object"),
    ("check", "must be an object"),
    ({"kind": "not-a-kind", "name": ["a"]}, "not one of"),
    ({"kind": "scenario", "name": []}, "empty"),
    ({"kind": "scenario", "name": ["a", ""]}, "non-empty string"),
    ({"kind": "scenario", "name": ["a", "a"]}, "repeats"),
    ({"kind": "check"}, "name missing"),
    ({"kind": "check", "name": None}, "name missing"),
    ({"kind": "check", "name": "x" * 501}, "over"),
])
def test_malformed_declaration_is_refused_before_connect(world, monkeypatch,
                                                         bad, frag):
    out, fake = _start(monkeypatch, evidence=bad)
    assert out.get("ok") is False, out
    err = str(out.get("error") or "")
    assert "ticket-start refused" in err, err
    assert frag in err, "the refusal names the failing check: %r" % err
    assert fake.connect_calls == 0, "refused before _connect()"
    assert fake.started is None, "no workflow was started"


# ---- B. valid declarations start and decode ---------------------------------

@pytest.mark.parametrize("ev", [
    {"kind": "check", "name": "integ"},
    {"kind": "scenario", "name": ["alpha", "beta"]},
    {"kind": "l1_battery", "name": "test_quickmanual_lane.py"},
])
def test_valid_declaration_starts_and_its_input_decodes(world, monkeypatch, ev):
    out, fake = _start(monkeypatch, evidence=ev)
    assert out.get("ok") is True, out
    assert fake.connect_calls == 1
    _cls, inp, _kw = fake.started
    # verbatim: normalisation (strip, list->display form) belongs to the open stage
    assert inp.evidence == ev
    decoded = _decode(inp)
    assert decoded.evidence == ev, "the workflow input decodes the declaration"
    assert decoded.ticket_id == "t261030-31-ut"


def test_list_valued_name_is_not_folded_at_creation(world, monkeypatch):
    """The incident's exact shape: a list of scenario names stays a list."""
    ev = {"kind": "scenario", "name": ["one", "two"]}
    out, fake = _start(monkeypatch, evidence=ev)
    assert out.get("ok") is True, out
    carried = fake.started[1].evidence
    assert carried["name"] == ["one", "two"], carried
    assert carried["name"] != "one, two"


# ---- C. absence stays absence ----------------------------------------------

@pytest.mark.parametrize("absent", ["missing", "empty"])
def test_absent_declaration_passes_through_empty(world, monkeypatch, absent):
    over = {} if absent == "missing" else {"evidence": {}}
    out, fake = _start(monkeypatch, **over)
    assert out.get("ok") is True, out
    assert fake.started[1].evidence == {}
