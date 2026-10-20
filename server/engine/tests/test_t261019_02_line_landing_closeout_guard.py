"""t261019-02 unit tests: the line-landing close-out guard decision core.

The ticket (host ruling 261019): a ticket whose landing row already exists on
a declared develop line must reach main only through a green line
certification followed by a signed promotion — the legacy per-ticket human
merge gate (a direct squash close-out) must refuse named, before a signature
is consumed. The decision core under test is
``dev_lane.line_landing_closeout_verdict(project_key, ticket_id)``:

  - ""            -> the legacy gate proceeds (incl. the VACUOUS cases:
                     no lines.json = zero declared lines; absent ledger);
  - non-empty str -> the named refusal the workflow feeds to _blocked.

Locked here (write set: server/engine/dev_lane.py):
  - vacuous pass: missing lines.json; absent delivery ledger; declared line
    with no landing row;
  - named block: landing row present (ruling quoted, line named, both ways
    out named, retry_qc explicitly does not clear it); malformed lines.json;
    corrupt delivery ledger rows (the read_rows ``bad`` face); malformed /
    empty project or ticket key.

Run: server/engine/.venv/bin/python -B -m pytest \
      server/engine/tests/test_t261019_02_line_landing_closeout_guard.py -q
"""
import json
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import dev_lane as dl  # noqa: E402  (conftest puts server/engine on sys.path)

PROJ = "proj-guard-a01"


@pytest.fixture()
def projects_root(tmp_path, monkeypatch):
    """A per-test project store root: develop_dir resolves under
    SANDBAR_PROJECTS_DIR and the delivery ledger under
    SANDBAR_DELIVERY_LEDGER_DIR (both read fresh on every call; the ledger
    env is the reader's own isolation seam — the default home path is never
    touched by these tests)."""
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(root))
    ledgers = tmp_path / "delivery-ledgers"
    ledgers.mkdir()
    monkeypatch.setenv("SANDBAR_DELIVERY_LEDGER_DIR", str(ledgers))
    return root


def _develop_dir(root):
    d = root / PROJ / "data" / "develop"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ledger(root):
    # SANDBAR_DELIVERY_LEDGER_DIR is a flat dir holding <project>.jsonl.
    d = root.parent / "delivery-ledgers"
    d.mkdir(parents=True, exist_ok=True)
    return d / ("%s.jsonl" % PROJ)


def _declare_line(root, line_id="develop-buffer"):
    dd = _develop_dir(root)
    dd.joinpath("lines.json").write_text(json.dumps([{
        "line_id": line_id,
        "scope": "epic guard",
        "owner": "engine",
        "repositories": [{"name": "sandbar", "branch": "develop-buffer"}],
    }]), encoding="utf-8")


def _landing_row(ticket_id="t261019-02", line_id="develop-buffer"):
    # The delivery-ledger landing row shape (ledger-record-models-v1): only
    # kind/ticket/line matter to the guard's has_landing match.
    return {"kind": "landing", "id": "ldg-01J9Z6QK3M7X2P4T8V0N5R",
            "seq": 41077,
            "ticket": ticket_id, "line": line_id,
            "revisions": {"sandbar": "77c264da"}}


# ---- vacuous cases: "" means the legacy gate proceeds untouched ------------

def test_no_line_declaration_is_vacuous(projects_root):
    # A project that never adopted develop lines: no lines.json at all.
    assert dl.line_landing_closeout_verdict(PROJ, "t261019-02") == ""


def test_absent_ledger_with_declared_line_is_vacuous(projects_root):
    _declare_line(projects_root)
    assert dl.line_landing_closeout_verdict(PROJ, "t261019-02") == ""


def test_declared_line_without_landing_passes(projects_root):
    _declare_line(projects_root)
    _ledger(projects_root).write_text(
        json.dumps(_landing_row(ticket_id="someone-else")) + "\n", encoding="utf-8")
    assert dl.line_landing_closeout_verdict(PROJ, "t261019-02") == ""


# ---- named blocks ----------------------------------------------------------

def test_landing_row_blocks_named(projects_root):
    _declare_line(projects_root)
    _ledger(projects_root).write_text(
        json.dumps(_landing_row()) + "\n", encoding="utf-8")
    v = dl.line_landing_closeout_verdict(PROJ, "t261019-02")
    assert v, "a line-landed ticket must not pass the guard"
    assert "261019" in v
    assert "line round" in v and "promotion" in v   # ruling, both ways out
    assert "develop-buffer" in v                     # the line is named
    assert "retry_qc" in v                           # not cleared by retry_qc


def test_landing_match_is_per_ticket_and_per_line(projects_root):
    _declare_line(projects_root)
    rows = [_landing_row(ticket_id="other-ticket"),
            _landing_row(line_id="some-other-line")]
    _ledger(projects_root).write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    assert dl.line_landing_closeout_verdict(PROJ, "t261019-02") == ""


def test_malformed_line_declaration_blocks_named(projects_root):
    dd = _develop_dir(projects_root)
    dd.joinpath("lines.json").write_text("{not json", encoding="utf-8")
    v = dl.line_landing_closeout_verdict(PROJ, "t261019-02")
    assert "malformed" in v and "line declaration" in v


def test_corrupt_ledger_rows_block_named(projects_root):
    _declare_line(projects_root)
    # A landing row hiding behind a corrupt neighbor: the bad face must block
    # BEFORE any has_landing match is trusted (fail closed over corrupt
    # records, never judged).
    _ledger(projects_root).write_text(
        "{corrupt line\n" + json.dumps(_landing_row()) + "\n", encoding="utf-8")
    v = dl.line_landing_closeout_verdict(PROJ, "t261019-02")
    assert v, "a corrupt ledger must block even when the good rows match nothing"
    assert "malformed line" in v


def test_corrupt_ledger_blocks_even_when_landing_row_visible(projects_root):
    # Same corrupt neighbor, but this time the ticket HAS a visible landing:
    # the ledger-corruption refusal wins (it comes first) and never lets the
    # close-out through on a half-readable ledger.
    _declare_line(projects_root)
    _ledger(projects_root).write_text(
        "{corrupt line\n" + json.dumps(_landing_row(ticket_id="other")) + "\n",
        encoding="utf-8")
    assert "malformed line" in dl.line_landing_closeout_verdict(PROJ, "t261019-02")


def test_malformed_project_key_blocks_named(projects_root):
    v = dl.line_landing_closeout_verdict("../escape", "t261019-02")
    assert v and "project key malformed" in v


def test_empty_keys_block_named(projects_root):
    assert "non-empty" in dl.line_landing_closeout_verdict("", "t261019-02")
    assert "non-empty" in dl.line_landing_closeout_verdict(PROJ, "  ")


def test_blank_lines_in_ledger_are_not_corruption(projects_root):
    _declare_line(projects_root)
    _ledger(projects_root).write_text(
        "\n" + json.dumps(_landing_row(ticket_id="other")) + "\n\n", encoding="utf-8")
    assert dl.line_landing_closeout_verdict(PROJ, "t261019-02") == ""


def test_patch_id_registered():
    # The workflow-side gate exists and is a fresh id (replay discipline).
    assert dl.LINE_LANDING_CLOSEOUT_GUARD_PATCH_ID == \
        "t261019-02-line-landing-closeout-guard-v1"
