#!/usr/bin/env python3
"""t260922-03 探针 live 档修复回归（离线纯逻辑 + dsh 桩会话，秒级零网络零 npm）。

守三面（KI 故障A/B 回归 + review_plan 条款落地）：
- LIVE_PROMPT 占位符与实参机械对账（故障A）：漂移必炸/对齐必过/渲染含双路径；
- 凭据缺失三态归因（故障B）：ENV 行点名 provider 路由+补救变量+「补齐仍报疑版本
  接缝破法」提示（review 意见2）；rc=0 健全会话日志含字面不翻红（意见3）；日志缺席
  按未知失败 FAIL 点名路径（意见4）；坏字节/空文件降级 ENV 点名不 traceback；
- Rows.exit_code 三态优先级 ENV > FAIL > PASS 回归锁（review 意见5 的技术底座）。
被测模块按路径载入（探针脚本无包结构）；dsh 桩=可执行 python 小脚本模拟 dsh 的
退出码与日志行为，不触真被测件。
"""
import importlib.util
import pathlib
import stat
import time

import pytest

PROBE = pathlib.Path(__file__).resolve().parent / "probe_dsh_seam.py"

CRED_LINE = ('dsh: MISSING_CREDENTIAL: llm-deepseek: no API key for provider route '
             '"deepseek-official"; store DEEPSEEK_API_KEY through the credentials '
             'service or export DEEPSEEK_API_KEY')

STUB_CRED_FAIL = (
    "import sys\n"
    "print(%r, file=sys.stderr, flush=True)\n"
    "sys.exit(3)\n" % CRED_LINE
)
STUB_HEALTHY_WITH_LITERAL = (
    "import sys\n"
    "print(%r, file=sys.stderr, flush=True)\n"
    "sys.exit(0)\n" % CRED_LINE
)
STUB_SLOW_CRED = (
    "import sys, time\n"
    "print(%r, file=sys.stderr, flush=True)\n"
    "time.sleep(60)\n" % CRED_LINE
)
STUB_SLOW_PLAIN = "import time\ntime.sleep(60)\n"
STUB_PLAIN_FAIL = (
    "import sys\n"
    "print('boom', file=sys.stderr, flush=True)\n"
    "sys.exit(1)\n"
)


def make_dsh_stub(tmp, body):
    stub = tmp / "dsh_stub.py"
    stub.write_text("#!/usr/bin/env python3\n" + body, "utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    return stub


def load_probe():
    spec = importlib.util.spec_from_file_location("probe_dsh_seam_under_test", PROBE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def probe():
    return load_probe()


def run_stub(probe, tmp_path, body, timeout=30):
    """桩会话：返回 ((rc, err, cred_missing), 日志路径)。"""
    stub = make_dsh_stub(tmp_path, body)
    home = tmp_path / "home"
    home.mkdir()
    lane = tmp_path / "lane"
    lane.mkdir()
    log = tmp_path / "session.log"
    res = probe.run_session(stub, home, lane, "桩会话", log, timeout=timeout)
    return res, log


# ---- 占位符守卫（故障A 回归）----

def test_live_prompt_placeholder_count(probe):
    assert probe.LIVE_PROMPT.count("%s") == 2


def test_placeholder_guard_drift_raises(probe):
    with pytest.raises(AssertionError) as ei:
        probe._assert_placeholder_count("仅 %s 一个", 2, "漂移样本")
    assert "漂移" in str(ei.value)


def test_placeholder_guard_match_passes(probe):
    probe._assert_placeholder_count("a %s b %s c", 2, "对齐样本")


def test_render_contains_both_paths(probe, tmp_path):
    w = tmp_path / "lane" / "probe_write_here.txt"
    e = tmp_path / "esc" / ".git" / "probe_escape.txt"
    out = probe.render_live_prompt(w, e)
    assert str(w) in out and str(e) in out


# ---- run_session 凭据守望（故障B 回归 + 意见3）----

def test_run_session_cred_fail_flagged(probe, tmp_path):
    (rc, err, cred), log = run_stub(probe, tmp_path, STUB_CRED_FAIL)
    assert rc == 3 and cred is True and err is None
    assert probe._log_contains_credential_marker(log)


def test_run_session_healthy_with_literal_not_flagged(probe, tmp_path):
    """意见3：rc=0 的完整会话日志含 MISSING_CREDENTIAL 字面也不得翻红。"""
    (rc, err, cred), log = run_stub(probe, tmp_path, STUB_HEALTHY_WITH_LITERAL)
    assert rc == 0 and cred is False and err is None
    assert probe._log_contains_credential_marker(log)  # 字面确在日志里（排除假通过）


def test_run_session_early_abort_beats_timeout(probe, tmp_path):
    """早停守望：日志自报即收割，不空等到超时（实测曾静默等满 900s）。"""
    t0 = time.monotonic()
    (rc, err, cred), log = run_stub(probe, tmp_path, STUB_SLOW_CRED, timeout=30)
    elapsed = time.monotonic() - t0
    assert rc is None and cred is True
    assert elapsed < 25, "守望未早停（耗时 %.1fs）" % elapsed
    assert "收割" in (err or "")


def test_run_session_timeout_without_cred(probe, tmp_path):
    """纯超时（无凭据字面）：原语义零改动（超时文本+非凭据），且收割真发生。"""
    t0 = time.monotonic()
    (rc, err, cred), log = run_stub(probe, tmp_path, STUB_SLOW_PLAIN, timeout=3)
    elapsed = time.monotonic() - t0
    assert rc is None and cred is False
    assert "超时" in (err or "")
    assert elapsed < 15, "超时路径未收割（耗时 %.1fs）" % elapsed


def test_run_session_plain_fail_not_cred(probe, tmp_path):
    (rc, err, cred), log = run_stub(probe, tmp_path, STUB_PLAIN_FAIL)
    assert rc == 1 and cred is False


def test_marker_probe_absent_and_bad_bytes(probe, tmp_path):
    """外部输入畸形态：缺席/坏字节一律按无标记，绝不 traceback。"""
    assert probe._log_contains_credential_marker(tmp_path / "absent.log") is False
    bad = tmp_path / "bad.log"
    bad.write_bytes(b"\xff\xfe\x00broken")
    assert probe._log_contains_credential_marker(bad) is False
    good = tmp_path / "good.log"
    good.write_text("x " + probe.CRED_MARKER + " y", "utf-8")
    assert probe._log_contains_credential_marker(good) is True


# ---- classify_credential_failure（意见2/4 + 畸形输入）----

def test_classify_env_names_route_remedy_and_esc_stance(probe, tmp_path):
    log = tmp_path / "cred.log"
    log.write_text(CRED_LINE + "\n", "utf-8")
    r = probe.Rows()
    probe.classify_credential_failure(log, "桩面", r)
    assert r.count("ENV") == 1
    detail = "".join(x[2] for x in r.rows)
    assert "deepseek-official" in detail
    assert "DEEPSEEK_API_KEY" in detail
    assert "疑版本接缝凭据语义变更" in detail  # 意见2：环境红不吞真破法
    assert str(log) in detail
    assert r.exit_code == probe.EXIT_ENV_FAIL
    assert r.count("INVENTORY") == 1  # 报错原文行留证


def test_classify_wrapped_message_extracts_var(probe, tmp_path):
    """真实 dsh 报错为两行折行：route 在 marker 行、store VAR 在续行（selftest
    双行形状曾抓到「只扫 marker 行」的提取缺陷，本用例锁死）。"""
    log = tmp_path / "wrapped.log"
    log.write_text(
        'dsh: MISSING_CREDENTIAL: llm-deepseek: no API key for provider route "deepseek-official";\n'
        "     store DEEPSEEK_API_KEY through the credentials service … or export DEEPSEEK_API_KEY …\n",
        "utf-8")
    r = probe.Rows()
    probe.classify_credential_failure(log, "桩面", r)
    assert r.count("ENV") == 1
    detail = "".join(x[2] for x in r.rows)
    assert "deepseek-official" in detail
    assert "DEEPSEEK_API_KEY" in detail
    assert "未知" not in detail


def test_classify_missing_log_fail_names_path(probe, tmp_path):
    """意见4：日志缺席（dsh 未写就崩）不 traceback，按未知失败 FAIL 点名路径。"""
    absent = tmp_path / "nope.log"
    r = probe.Rows()
    probe.classify_credential_failure(absent, "桩面", r)
    assert r.count("FAIL") == 1 and r.count("ENV") == 0
    assert str(absent) in "".join(x[2] for x in r.rows)


def test_classify_bad_bytes_degrades_to_env_unknown_route(probe, tmp_path):
    bad = tmp_path / "bad.log"
    bad.write_bytes(b"\xff\xfe\x00")
    r = probe.Rows()
    probe.classify_credential_failure(bad, "桩面", r)
    assert r.count("ENV") == 1
    assert "未知路由" in "".join(x[2] for x in r.rows)


def test_classify_empty_log_degrades_to_env_unknown_route(probe, tmp_path):
    empty = tmp_path / "empty.log"
    empty.write_bytes(b"")
    r = probe.Rows()
    probe.classify_credential_failure(empty, "桩面", r)
    assert r.count("ENV") == 1
    assert "未知路由" in "".join(x[2] for x in r.rows)


def test_classify_huge_line_truncated_no_crash(probe, tmp_path):
    big = tmp_path / "big.log"
    big.write_text("x" * 100000 + probe.CRED_MARKER + "\n", "utf-8")
    r = probe.Rows()
    probe.classify_credential_failure(big, "桩面", r)
    assert r.count("ENV") == 1
    raw = [x[2] for x in r.rows if x[1] == "凭据缺失 原文"]
    assert raw and len(raw[0]) <= 300


# ---- 三态优先级回归锁（意见5 技术底座）----

def test_exit_code_priority_env_over_fail_over_pass(probe):
    r = probe.Rows()
    r.fail("产品红")
    r.add("ENV", "环境红")
    assert r.exit_code == probe.EXIT_ENV_FAIL
    r2 = probe.Rows()
    r2.fail("产品红")
    assert r2.exit_code == probe.EXIT_FAIL
    assert probe.Rows().exit_code == probe.EXIT_PASS
