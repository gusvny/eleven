"""parse_arbitration_summary verdict 提取边界（t260902-10）。

锁契约：**唯一** verdict=token 才提取；缺失/零个/多个/非法 → 空串。
「多个→空串」是本票对「取首个匹配」的有意修正：多个=畸形仲裁摘要，
取任何一个都是猜，交给 workflow 格式纠正重试（dev_lane 空 verdict 路径）。
"""
from shared import parse_arbitration_summary


def test_single_valid_verdicts():
    for v in ("pass", "tests-fault", "code-fault"):
        assert parse_arbitration_summary("verdict=%s 结论如下" % v) == v
        assert parse_arbitration_summary("verdict=" + v) == v


def test_missing_marker():
    assert parse_arbitration_summary("一切正常，建议通过") == ""
    assert parse_arbitration_summary("") == ""
    assert parse_arbitration_summary("verdict= 结论忘写了") == ""


def test_none_input():
    assert parse_arbitration_summary(None) == ""


def test_illegal_value():
    # 合法词表之外的值不算 verdict 标记
    assert parse_arbitration_summary("verdict=maybe-ok") == ""
    assert parse_arbitration_summary("verdict=pass-fault") == ""


def test_multiple_verdicts_return_empty():
    """多个 token = 畸形摘要 → 空串（不取首个、不猜）。"""
    assert parse_arbitration_summary("verdict=pass 但其实 verdict=code-fault") == ""
    assert parse_arbitration_summary("verdict=pass\nverdict=pass") == ""
    assert parse_arbitration_summary("verdict=code-fault verdict=code-fault") == ""


def test_single_token_with_other_text():
    # 前后任意文本不干扰；含 verdict= 字样的非标记文本（无合法值）不算
    assert parse_arbitration_summary("# 仲裁\nverdict=tests-fault\n理由：测试集断言错") == "tests-fault"
    assert parse_arbitration_summary("对比 verdict= 形如字样 verdict=pass") == "pass"
