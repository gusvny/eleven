"""t261028_57 / ticket t261029-14 L1: the in-lane code gate's wait is DERIVED
from the declared check budgets, and an outer-wait expiry is a named budget fact
instead of an unnamed red.

Defect (measured three times on 261028, KI-401 family): agent_activities wrapped
the verify_lane code spawn in a bare 900s wait while verify.yaml declared the
engine-suite check at 1000s. The outer wait was SMALLER than the inner budget by
construction, so on a loaded host the check could never use the budget it
declares: the run was reaped and the merge gate reported
"verify_lane timed out (>900s)" naming no check - a could-not-run rendered as an
unnamed red.

Faces under test:
  - verify_lane_code_gate_budget: the pure derivation
    (max(declared budgets, documented default) + documented chain margin);
  - _read_verify_lane_check_budgets: reads the SAME verify.yaml verify_lane reads
    (path=<tree>), and names why it fell back to the documented default;
  - code_gate_expiry_receipt: the named receipt (budget used, slowest check, host
    load) that stays blocking;
  - _verify_lane_code_expiry_row: the merge_check row carrying those facts;
  - the gate's green/red rows are the pre-ticket dicts, byte for byte (driven
    through the real _merge_check_one_scope with a stubbed verify_lane process);
  - source locks: no bare literal decides the wait, and the process group is
    reaped BEFORE the expiry receipt is built.

Everything here is fixture level: a temp git lane and a fake verify_lane process.
The real suite is never run from this file.

Run: server/engine/.venv/bin/python -m pytest \
      server/engine/tests/test_t261028_57_gate_budget_derivation.py -q
"""
import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parent.parent
REPO = POC.parents[1]
sys.path.insert(0, str(POC))

import agent_activities as aa  # noqa: E402
import dev_lane as dl  # noqa: E402
from shared import MergeCheckArgs  # noqa: E402

# The legacy red-row copy, escaped so this file stays ASCII (the copy-language
# gate owns product surfaces; this is a pinned expectation, not new copy).
LEGACY_RED_NEXT_ACTION = ("\u6309 detail \u91cc\u7684\u7ea2\u706f\u9879\u4fee\u590d"
                          "\u540e\u53d1 retry_qc \u91cd\u9a8c")
CJK_SEMI = "\uff1b"  # the existing detail separator, kept byte-identical


# ---------------------------------------------------------------- derivation --

def test_the_two_documented_numbers_are_the_contract():
    """The default and the margin are documented numbers, not accidentals: the
    default is verify_lane's own default for a check that declares no timeout."""
    assert aa.VERIFY_LANE_CHECK_DEFAULT_BUDGET_SEC == 600
    assert aa.VERIFY_LANE_CODE_GATE_CHAIN_MARGIN_SEC > 0


def test_declared_budgets_derive_the_wait_plus_the_documented_margin():
    checks = [{"id": "py-compile", "cmd": "x"},
              {"id": "test", "cmd": "pytest", "timeout": 1000}]
    wait, facts = aa.verify_lane_code_gate_budget(checks)
    assert wait == 1000 + aa.VERIFY_LANE_CODE_GATE_CHAIN_MARGIN_SEC
    assert wait == facts["wait_sec"]
    assert facts["slowest_id"] == "test"
    assert facts["slowest_budget_sec"] == 1000
    assert facts["declared_checks"] == 2
    assert facts["margin_sec"] == aa.VERIFY_LANE_CODE_GATE_CHAIN_MARGIN_SEC
    assert facts["no_declared_checks"] is False
    # An undeclared check inside a declaration gets the documented default and is
    # NAMED as defaulted (never a silent 0 that would shrink the wait).
    assert facts["defaulted_ids"] == ["py-compile"]
    assert facts["budgets"][0] == {"id": "py-compile",
                                   "budget_sec": aa.VERIFY_LANE_CHECK_DEFAULT_BUDGET_SEC,
                                   "declared": False}
    assert facts["budgets"][1] == {"id": "test", "budget_sec": 1000, "declared": True}


def test_missing_declaration_falls_back_to_the_documented_default():
    for bad in (None, [], {}, 0, "lanes: code: checks: - id: a"):
        wait, facts = aa.verify_lane_code_gate_budget(bad)
        assert wait == (aa.VERIFY_LANE_CHECK_DEFAULT_BUDGET_SEC
                        + aa.VERIFY_LANE_CODE_GATE_CHAIN_MARGIN_SEC), bad
        assert facts["no_declared_checks"] is True
        assert facts["declared_checks"] == 0
        assert facts["slowest_id"] == ""


def test_malformed_budgets_never_shrink_the_wait_and_are_named():
    checks = [{"id": "bad-str", "cmd": "x", "timeout": "soon"},
              {"id": "zero", "cmd": "x", "timeout": 0},
              {"id": "negative", "cmd": "x", "timeout": -5},
              "not-a-mapping",
              {"id": "bool", "cmd": "x", "timeout": True},
              {"id": "numstr", "cmd": "x", "timeout": "240"}]
    wait, facts = aa.verify_lane_code_gate_budget(checks)
    assert facts["defaulted_ids"] == ["bad-str", "zero", "negative", "#3", "bool"]
    # The documented default outweighs the one parseable declaration, and a string
    # number IS a declaration, exactly as verify_lane's `int(c.get('timeout') or
    # 600)` reads it.
    assert facts["slowest_id"] == "bad-str"
    assert facts["slowest_budget_sec"] == aa.VERIFY_LANE_CHECK_DEFAULT_BUDGET_SEC
    assert facts["budgets"][-1] == {"id": "numstr", "budget_sec": 240, "declared": True}
    assert wait == facts["slowest_budget_sec"] + aa.VERIFY_LANE_CODE_GATE_CHAIN_MARGIN_SEC


def test_the_wait_never_undercuts_a_declared_budget():
    """The regression this ticket exists for: no declared check budget may be
    larger than the wait the gate grants it (measured: 1000 declared vs 900)."""
    for budgets in ([1000], [1], [60, 1000], [1000, 1000, 1000]):
        checks = [{"id": "c%d" % i, "cmd": "x", "timeout": b}
                  for i, b in enumerate(budgets)]
        wait, facts = aa.verify_lane_code_gate_budget(checks)
        for entry in facts["budgets"]:
            assert wait > entry["budget_sec"], (budgets, entry)
        assert wait == max(budgets) + aa.VERIFY_LANE_CODE_GATE_CHAIN_MARGIN_SEC


def test_derived_wait_is_always_finite_and_positive():
    for checks in (None, [], [{}], [{"id": "a"}]):
        wait, _facts = aa.verify_lane_code_gate_budget(checks)
        assert isinstance(wait, int) and 0 < wait < 10 ** 6


# ------------------------------------------------------- declaration reader --

def _declaration(tmp_path, text):
    (tmp_path / "verify.yaml").write_text(text, encoding="utf-8")
    return tmp_path


def test_reader_returns_the_declared_checks(tmp_path):
    tree = _declaration(tmp_path, "lanes:\n  code:\n    checks:\n"
                                  "      - id: a\n        cmd: x\n        timeout: 700\n")
    checks, diag = aa._read_verify_lane_check_budgets(tree)
    assert diag == "" and checks == [{"id": "a", "cmd": "x", "timeout": 700}]
    wait, _facts = aa.verify_lane_code_gate_budget(checks)
    assert wait == 700 + aa.VERIFY_LANE_CODE_GATE_CHAIN_MARGIN_SEC


def test_reader_names_every_fallback_instead_of_inventing_a_declaration(tmp_path):
    missing, diag = aa._read_verify_lane_check_budgets(tmp_path)
    assert missing == [] and "no verify.yaml" in diag

    bad = tmp_path / "bad"
    bad.mkdir()
    _declaration(bad, "lanes: {{ not yaml\n")
    checks, diag = aa._read_verify_lane_check_budgets(bad)
    assert checks == [] and "unreadable" in diag

    empty = tmp_path / "empty"
    empty.mkdir()
    _declaration(empty, "lanes:\n  code:\n    write_allow:\n      - a\n")
    checks, diag = aa._read_verify_lane_check_budgets(empty)
    assert checks == [] and "declares no lanes.code.checks" in diag


def test_this_repo_declaration_fits_inside_the_activity_cap():
    """Project-level consistency: the derived wait must let every declared check
    use its own budget AND still be reachable inside the merge_check activity's
    start_to_close (otherwise the named inner expiry could never be reported)."""
    checks, diag = aa._read_verify_lane_check_budgets(REPO)
    assert diag == "", "this repo declares code-lane checks (%s)" % diag
    wait, facts = aa.verify_lane_code_gate_budget(checks)
    assert wait > facts["slowest_budget_sec"]  # no declared budget is undercut
    assert wait < float(dl.MERGE_CHECK_TO.total_seconds()), (
        "derived wait %ds must stay inside MERGE_CHECK_TO=%ss"
        % (wait, dl.MERGE_CHECK_TO.total_seconds()))


# ----------------------------------------------------------- expiry receipt --

def _declared_facts():
    checks = [{"id": "py-compile", "cmd": "x"},
              {"id": "test", "cmd": "pytest", "timeout": 1000},
              {"id": "lint", "cmd": "y"}]
    return aa.verify_lane_code_gate_budget(checks)


def test_expiry_receipt_names_the_budget_the_slowest_check_and_the_load():
    wait, facts = _declared_facts()
    detail, structured = aa.code_gate_expiry_receipt(
        wait, facts, 1120.4, loadavg=[41.2, 38.7, 35.1])
    assert "could not complete within its derived budget (1120s" in detail
    assert "slowest declared check 'test' 1000s" in detail
    assert "slowest check: test" in detail
    assert "declared budget 1000s" in detail
    assert "gate wall used 1120.4s" in detail
    assert "machine load 41.20 38.70 35.10 (1m/5m/15m)" in detail
    assert "environment/budget fact, not a red check" in detail
    assert "documented default 600s applied: py-compile, lint" in detail
    # The old wording (the one that named nothing) is gone, not merely softened.
    assert "timed out (>900s)" not in detail
    assert "verify_lane timed out" not in detail
    assert structured == {
        "budget_sec": 1120,
        "gate_elapsed_sec": 1120.4,
        "margin_sec": aa.VERIFY_LANE_CODE_GATE_CHAIN_MARGIN_SEC,
        "loadavg": [41.2, 38.7, 35.1],
        "verdict_kind": "could_not_complete",
        "slowest_check": "test",
        "slowest_check_budget_sec": 1000,
    }


def test_expiry_receipt_without_a_declaration_says_so():
    wait, facts = aa.verify_lane_code_gate_budget([])
    detail, structured = aa.code_gate_expiry_receipt(
        wait, facts, 720.0, read_diag="no verify.yaml at /x/verify.yaml", loadavg=None)
    assert "no declared check budget was read" in detail
    assert "documented default 600s" in detail
    assert "machine load not available on this platform" in detail
    assert "declaration: no verify.yaml at /x/verify.yaml" in detail
    assert structured["no_declared_checks"] is True
    assert "slowest_check" not in structured
    assert structured["declaration_diag"] == "no verify.yaml at /x/verify.yaml"


def test_expiry_row_stays_blocking_and_carries_the_facts():
    wait, facts = _declared_facts()
    detail, structured = aa.code_gate_expiry_receipt(
        wait, facts, 1120.4, loadavg=[41.2, 38.7, 35.1])
    row = aa._verify_lane_code_expiry_row(detail, structured)
    assert row["green"] is False  # an expiry always blocks, never a silent green
    assert row["id"] == "verify_lane_code"
    assert row["item"] == "In-lane verify_lane code is green"
    assert row["reason_code"] == "gate_budget_exhausted"  # separable from verify_red
    assert row["verdict_kind"] == "could_not_complete"
    assert row["budget_sec"] == 1120
    assert row["slowest_check"] == "test"
    assert row["loadavg"] == [41.2, 38.7, 35.1]
    assert "environment/budget fact" in row["next_action"]
    assert row["detail"] == detail
    # Structured names ride along untouched when the receipt carried them.
    assert aa._verify_lane_code_expiry_row(detail, structured,
                                           red_names=["a.py::t"])["red_items"] == [
        {"name": "a.py::t"}]


# ------------------------------------------------- green/red rows unchanged --

def _git(*args, cwd):
    p = subprocess.run(["git"] + list(args), cwd=str(cwd),
                       capture_output=True, text=True)
    assert p.returncode == 0, "git %s failed: %s" % (" ".join(args), p.stderr)
    return p.stdout


def _init_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    _git("init", "-b", "main", cwd=path)
    _git("config", "user.email", "ut@example.com", cwd=path)
    _git("config", "user.name", "ut", cwd=path)
    (path / ".gitignore").write_text(".lane/\n", encoding="utf-8")
    (path / "f.txt").write_text("base\n", encoding="utf-8")
    _git("add", "-A", cwd=path)
    _git("commit", "-m", "base", cwd=path)
    return path


@pytest.fixture()
def repo_lane(tmp_path):
    root = _init_repo(tmp_path / "proj")
    br = "lane/t261029ut"
    lane = root / ".lane" / "t261029ut"
    _git("worktree", "add", "-b", br, str(lane), cwd=root)
    (lane / "f.txt").write_text("lane change\n", encoding="utf-8")
    _git("add", "-A", cwd=lane)
    _git("commit", "-m", "lane work", cwd=lane)
    return root, lane, br


class _FakeProc:
    """The stubbed verify_lane child: canned receipt bytes, or a hang."""

    def __init__(self, payload=None, hang=False):
        self.pid = 0
        self.returncode = None if hang else 0
        self._payload = payload
        self._hang = hang

    async def communicate(self):
        if self._hang:
            await asyncio.sleep(30)
        return json.dumps(self._payload or {}).encode("utf-8"), b""


def _spawn_stub(payload=None, hang=False):
    async def _spawn(*_a, **_k):
        return _FakeProc(payload, hang)
    return _spawn


def _run_scope(root, lane, br):
    sc = {"tree": lane, "repo": root, "branch": br, "base_ref": "main",
          "write_set": ["f.txt"], "name": "", "repo_rel": ""}
    args = MergeCheckArgs(ticket_id="t261029ut", worktree=str(lane), branch=br,
                          write_set=["f.txt"])
    return asyncio.run(aa._merge_check_one_scope(args, sc, lane, False))


def _gate_rows(core):
    return [c for c in core["checks"] if c.get("id") == "verify_lane_code"]


def test_green_check_row_is_byte_identical_to_the_pre_ticket_row(repo_lane, monkeypatch):
    root, lane, br = repo_lane
    monkeypatch.setattr(aa.asyncio, "create_subprocess_exec", _spawn_stub(
        {"ok": True, "result": {"green": True, "exit_code": 0, "red_count": 0,
                                "checks": []}}))
    rows = _gate_rows(_run_scope(root, lane, br))
    assert len(rows) == 1
    assert rows[0] == {"item": "In-lane verify_lane code is green", "green": True,
                       "detail": "exit=0 red=0", "id": "verify_lane_code"}
    assert list(rows[0]) == ["item", "green", "detail", "id"]  # key order unchanged


def test_red_check_row_is_byte_identical_to_the_pre_ticket_row(repo_lane, monkeypatch):
    root, lane, br = repo_lane
    failing = "FAILED server/engine/tests/test_x.py::test_y"
    monkeypatch.setattr(aa.asyncio, "create_subprocess_exec", _spawn_stub(
        {"ok": False,
         "result": {"green": False, "exit_code": 1, "red_count": 2,
                    "checks": [{"id": "lint", "level": "red",
                                "items": [{"detail": failing}]}]}}))
    rows = _gate_rows(_run_scope(root, lane, br))
    assert len(rows) == 1
    assert rows[0] == {
        "item": "In-lane verify_lane code is green",
        "green": False,
        "detail": "exit=1 red=2" + CJK_SEMI + failing,
        "id": "verify_lane_code",
        "reason_code": "verify_red",
        "next_action": LEGACY_RED_NEXT_ACTION,
        "red_items": [{"name": "server/engine/tests/test_x.py::test_y"}],
    }
    assert list(rows[0]) == ["item", "green", "detail", "id", "reason_code",
                             "next_action", "red_items"]


def test_expired_outer_wait_yields_the_named_row_and_reaps_the_group(repo_lane, monkeypatch):
    """Driven through the real gate: a hung verify_lane child expires the derived
    wait. The row must be the named budget fact (blocking, never a silent green)
    and the process group must be reaped BEFORE the receipt is built."""
    root, lane, br = repo_lane
    reaped = []

    async def _reap(proc, tag="", **_kw):
        reaped.append(tag)
        return "stubbed reap"

    monkeypatch.setattr(aa, "VERIFY_LANE_CODE_GATE_CHAIN_MARGIN_SEC", 0)
    monkeypatch.setattr(aa, "_read_verify_lane_check_budgets",
                        lambda tree: ([{"id": "test", "cmd": "pytest",
                                        "timeout": 1}], ""))
    monkeypatch.setattr(aa, "_machine_loadavg", lambda: [41.2, 38.7, 35.1])
    monkeypatch.setattr(aa, "reap_spawn_group", _reap)
    monkeypatch.setattr(aa.asyncio, "create_subprocess_exec", _spawn_stub(hang=True))

    rows = _gate_rows(_run_scope(root, lane, br))
    assert len(rows) == 1
    row = rows[0]
    assert row["green"] is False                      # still blocking
    assert row["reason_code"] == "gate_budget_exhausted"
    assert row["budget_sec"] == 1                     # the derived budget, named
    assert row["slowest_check"] == "test"
    assert row["slowest_check_budget_sec"] == 1
    assert row["gate_elapsed_sec"] >= 1.0
    assert row["loadavg"] == [41.2, 38.7, 35.1]       # load visibility
    detail = row["detail"]
    assert "could not complete within its derived budget (1s" in detail
    assert "slowest check: test" in detail
    assert "machine load 41.20 38.70 35.10" in detail
    assert "not a red check" in detail
    assert "timed out (>900s)" not in detail
    assert reaped == ["verify-lane-code"]             # reaped on expiry, as before


# ------------------------------------------------------------ source locks --

def _gate_block():
    src = (POC / "agent_activities.py").read_text("utf-8")
    start = src.index('_gate_checks, _gate_decl_diag = '
                      '_read_verify_lane_check_budgets(sc["tree"])')
    end = src.index("if _gate_expiry:", start)
    return src, src[start:end]


def test_no_bare_literal_decides_the_code_gate_wait():
    src, block = _gate_block()
    assert "timeout=900" not in block
    assert ">900s" not in block
    assert "verify_lane timed out" not in src          # the unnamed wording is gone
    assert "timeout=_gate_wait_sec" in block
    assert ("_gate_wait_sec, _gate_facts = verify_lane_code_gate_budget("
            "_gate_checks)") in block
    assert "wait_budget_exhausted(_v_wait_t0, _gate_wait_sec)" in block


def test_process_group_is_reaped_before_the_expiry_receipt():
    _src, block = _gate_block()
    assert block.count('reap_spawn_group(vp, tag="verify-lane-code")') == 2
    assert block.count("code_gate_expiry_receipt(") == 2
    for hit in (i for i in range(len(block))
                if block.startswith("code_gate_expiry_receipt(", i)):
        assert 'reap_spawn_group(vp, tag="verify-lane-code")' in block[max(0, hit - 700):hit]
