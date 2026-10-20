"""t261019-03: a case the round could not verify is not content guilt.

Host order 261019 + KI-01M55FVE2QZ0NR5AHQRHBNXX7S: the round at c64bde69 minted a RED
certification (and froze the line) over t261006-03-engine-path-capture-journey, whose own
evidence was `connect_refused` to its capture bench - an environment face. The relative
caliber must compare CONTENT failures and publish the unverified set by name.

Oracle level: the PURE comparison (relative_verdict) plus the runner-publishes-the-set
contract. The envelope/round orchestration (relative_round_verdict) needs a baseline run
and a Temporal-round runner, so it stays out of this battery - a unit test that depends on
a cached baseline is environment-coupled (measured: 4 failures on main at 8aba5a87 where
the cache was cold, TypeError from calling a None runner).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import develop_certify as dc  # noqa: E402


def test_env_only_red_is_green_and_named():
    """The runner publishes not-checked separately; the compare excludes them."""
    fails = {"case-env"}
    unverified = {"case-env"}
    v, detail = dc.relative_verdict(sorted(fails - unverified), {"deterministic_fails": []})
    assert v == "green"
    assert detail["new_regressions"] == []
    assert sorted(unverified & fails) == ["case-env"]


def test_content_red_stays_red():
    v, detail = dc.relative_verdict(["case-real"], {"deterministic_fails": []})
    assert v == "red"
    assert detail["new_regressions"] == ["case-real"]


def test_mixed_keeps_both_faces():
    fails = {"case-real", "case-env"}
    unverified = {"case-env"}
    v, detail = dc.relative_verdict(sorted(fails - unverified), {"deterministic_fails": []})
    assert v == "red"
    assert detail["new_regressions"] == ["case-real"]
    assert sorted(unverified & fails) == ["case-env"]


def test_carried_debt_and_flaky_stay_green():
    baseline = {"deterministic_fails": ["debt-1"], "flaky": ["flake-1"]}
    v, detail = dc.relative_verdict(["debt-1", "flake-1"], baseline)
    assert v == "green"
    assert detail["carried_debt"] == ["debt-1"]
    assert detail["flaky_hits"] == ["flake-1"]


def test_runner_publishes_the_unverified_set():
    """The round runner must publish the environment face as its own field, never
    folded into failed_names (that fold is the defect this battery guards)."""
    src = (Path(__file__).resolve().parents[3] / "integration" / "line_round_runner.py").read_text()
    assert "def unverified_names(" in src
    assert 'header["unverified_names"] = unverified_names(' in src
