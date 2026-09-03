"""integration_route 三态×轮次上限矩阵（t260902-10，纯函数，离线）。"""
import pytest

from shared import integration_route, MAX_CODE_FAULT_ROUNDS, MAX_TESTS_FAULT_ROUNDS


def test_pass_routes_to_acceptance():
    assert integration_route("pass", 0, 0) == "acceptance"
    # pass 不受轮次影响
    assert integration_route("pass", 99, 99) == "acceptance"


def test_tests_fault_within_limit():
    for rounds in range(MAX_TESTS_FAULT_ROUNDS + 1):  # 0..5（含上限）继续迭代测试集
        assert integration_route("tests-fault", rounds, 0) == "run_integration_tests"


def test_tests_fault_over_limit_blocked():
    r = integration_route("tests-fault", MAX_TESTS_FAULT_ROUNDS + 1, 0)
    assert r.startswith("blocked:")
    assert "测试集迭代" in r and str(MAX_TESTS_FAULT_ROUNDS) in r  # 文案含上限


def test_code_fault_within_limit():
    for rounds in range(MAX_CODE_FAULT_ROUNDS + 1):
        assert integration_route("code-fault", 0, rounds) == "implement"


def test_code_fault_over_limit_blocked():
    r = integration_route("code-fault", 0, MAX_CODE_FAULT_ROUNDS + 1)
    assert r.startswith("blocked:")
    assert "developer" in r and str(MAX_CODE_FAULT_ROUNDS) in r


@pytest.mark.parametrize("bad", ["", "Pass", "PASS", "skip", "verdict=pass", None])
def test_illegal_verdict_blocked(bad):
    r = integration_route(bad, 0, 0)
    assert r.startswith("blocked:")
    assert "verdict" in r
