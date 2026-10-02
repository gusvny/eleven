"""闸轮并发校准（t261002-03）单测：纯函数 + env 组装面，离线、无真子进程。

根因回顾：闸轮此前继承执行器缺省池内并发（main:3,ro:3,browser-free:3），而归属
基线强制并发 =1；低可用内存宿主上宽度>1 的控制台族假红把票挡在门外（宽度1→0/5
红，宽度4→15/41 红）。校准面单测锁三点：内存台阶、操作员覆盖优先、畸形输入显式
降级（绝不猜数、绝不静默）。"""
import os

import pytest

import agent_activities as aa


GI = 1024 ** 3


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """相关 env 全剥（缺省态基线），用例内再显式钉。"""
    for k in ("SANDBAR_POOL_CONC", "SANDBAR_CONC_POOLS", aa.CONC_CALIB_ENV):
        monkeypatch.delenv(k, raising=False)


# ---------------- calibrated_pool_width：内存台阶 ----------------

def test_width_low_memory_pins_1():
    # ~0.1GB free（宿主实况量级）→ 1：与归属基线强制 =1 逐字同宽
    assert aa.calibrated_pool_width(int(0.1 * GI), 8) == 1
    assert aa.calibrated_pool_width(2 * GI - 1, 16) == 1


def test_width_middle_step_2():
    assert aa.calibrated_pool_width(2 * GI, 8) == 2
    assert aa.calibrated_pool_width(6 * GI - 1, 8) == 2


def test_width_rich_memory_3_and_cpu_cap():
    assert aa.calibrated_pool_width(6 * GI, 8) == 3
    assert aa.calibrated_pool_width(64 * GI, 2) == 2   # CPU 只作上限夹紧
    assert aa.calibrated_pool_width(64 * GI, 1) == 1


def test_width_unmeasurable_memory_returns_none():
    assert aa.calibrated_pool_width(None, 8) is None


def test_width_cpu_none_falls_back_to_3_cap():
    assert aa.calibrated_pool_width(64 * GI, None) == 3
    assert aa.calibrated_pool_width(int(0.5 * GI), None) == 1


# ---------------- mem_available_bytes：畸形输入显式降级 ----------------

def test_mem_available_linux_proc(monkeypatch, tmp_path):
    f = tmp_path / "meminfo"
    f.write_text("MemTotal:       16000 kB\nMemAvailable:    2048 kB\n"
                 "SwapFree:           0 kB\n")
    monkeypatch.setattr(aa, "open", lambda p, *a, **k: open(f, *a, **k),
                        raising=False)
    assert aa.mem_available_bytes() == 2048 * 1024


def test_mem_available_malformed_proc_falls_to_none(monkeypatch, tmp_path):
    f = tmp_path / "meminfo"
    f.write_text("MemAvailable:   not-a-number kB\n")
    monkeypatch.setattr(aa, "open", lambda p, *a, **k: open(f, *a, **k),
                        raising=False)
    monkeypatch.setattr(aa.subprocess, "run",
                        lambda *a, **k: (_ for _ in ()).throw(
                            aa.subprocess.SubprocessError("no vm_stat")))
    assert aa.mem_available_bytes() is None


def test_mem_available_macos_vm_stat(monkeypatch):
    out = ("Mach Virtual Memory Statistics: (page size of 16384 bytes)\n"
           "Pages free:                              12345.\n"
           "Pages active:                            22222.\n"
           "Pages inactive:                          1000.\n"
           "Pages speculative:                        500.\n")

    class _P:
        returncode = 0
        stdout = out
        stderr = ""

    monkeypatch.setattr(aa.subprocess, "run", lambda *a, **k: _P())
    assert aa.mem_available_bytes() == (12345 + 500 + 1000) * 16384


def test_mem_available_vm_stat_missing_keys_none(monkeypatch):
    class _P:
        returncode = 0
        stdout = "Mach Virtual Memory Statistics: (page size of 4096 bytes)\n" \
                 "Pages free: 10.\n"          # 缺 inactive/speculative = 畸形
        stderr = ""

    monkeypatch.setattr(aa.subprocess, "run", lambda *a, **k: _P())
    assert aa.mem_available_bytes() is None


def test_mem_available_vm_stat_bad_rc_and_no_page_size(monkeypatch):
    class _Bad:
        returncode = 1
        stdout = ""
        stderr = "x"

    class _Weird:
        returncode = 0
        stdout = "no page size here\n"
        stderr = ""

    for p in (_Bad(), _Weird()):
        monkeypatch.setattr(aa.subprocess, "run", lambda *a, **k: p)
        assert aa.mem_available_bytes() is None


def test_mem_available_vm_stat_timeout_none(monkeypatch):
    def _boom(*a, **k):
        raise aa.subprocess.TimeoutExpired(cmd="vm_stat", timeout=5)

    monkeypatch.setattr(aa.subprocess, "run", _boom)
    assert aa.mem_available_bytes() is None


def test_mem_available_zero_pages_none(monkeypatch):
    class _P:
        returncode = 0
        stdout = "page size of 4096 bytes\nPages free: 0.\n" \
                 "Pages inactive: 0.\nPages speculative: 0.\n"
        stderr = ""

    monkeypatch.setattr(aa.subprocess, "run", lambda *a, **k: _P())
    assert aa.mem_available_bytes() is None


# ---------------- conc_calibration_env：优先级与注入面 ----------------

def test_auto_low_memory_injects_width_1(monkeypatch):
    monkeypatch.setattr(aa, "mem_available_bytes", lambda: int(0.1 * GI))
    env, reason, w = aa.conc_calibration_env()
    assert w == 1
    assert env["SANDBAR_POOL_CONC"] == "1"
    assert env["SANDBAR_CONC_POOLS"] == "main:1,ro:1,browser-free:1"
    assert "width=1" in reason and "mem_available=" in reason


def test_auto_rich_memory_injects_width_3(monkeypatch):
    monkeypatch.setattr(aa, "mem_available_bytes", lambda: 32 * GI)
    monkeypatch.setattr(aa.os, "cpu_count", lambda: 8)
    env, reason, w = aa.conc_calibration_env()
    assert w == 3
    assert env["SANDBAR_POOL_CONC"] == "3"


def test_auto_unmeasurable_no_injection_named_reason(monkeypatch):
    monkeypatch.setattr(aa, "mem_available_bytes", lambda: None)
    env, reason, w = aa.conc_calibration_env()
    assert env == {} and w is None
    assert "memory unmeasurable" in reason


def test_operator_override_pool_conc_wins(monkeypatch):
    monkeypatch.setenv("SANDBAR_POOL_CONC", "2")
    env, reason, w = aa.conc_calibration_env()
    assert env == {} and w is None
    assert "SANDBAR_POOL_CONC set by operator" in reason


def test_operator_override_conc_pools_wins(monkeypatch):
    monkeypatch.setenv("SANDBAR_CONC_POOLS", "main:1")
    env, reason, w = aa.conc_calibration_env()
    assert env == {} and w is None
    assert "SANDBAR_CONC_POOLS set by operator" in reason


def test_knob_off_disables(monkeypatch):
    monkeypatch.setenv(aa.CONC_CALIB_ENV, "off")
    monkeypatch.setattr(aa, "mem_available_bytes",
                        lambda: (_ for _ in ()).throw(AssertionError("must not probe")))
    env, reason, w = aa.conc_calibration_env()
    assert env == {} and w is None and "off" in reason


def test_knob_pinned_integer(monkeypatch):
    monkeypatch.setenv(aa.CONC_CALIB_ENV, "2")
    monkeypatch.setattr(aa, "mem_available_bytes",
                        lambda: (_ for _ in ()).throw(AssertionError("must not probe")))
    env, reason, w = aa.conc_calibration_env()
    assert w == 2 and env["SANDBAR_CONC_POOLS"] == "main:2,ro:2,browser-free:2"


def test_knob_malformed_value_no_injection_named_reason(monkeypatch):
    monkeypatch.setenv(aa.CONC_CALIB_ENV, "banana")
    env, reason, w = aa.conc_calibration_env()
    assert env == {} and w is None
    assert "malformed" in reason and "banana" in reason


def test_knob_empty_and_zero_values_degrade_safely(monkeypatch):
    # 空串 = auto；0/负 = 夹紧到 1（不许下发 0/负宽度给执行器）
    for v, expect in (("", 1), ("0", 1), ("-3", 1)):
        monkeypatch.setenv(aa.CONC_CALIB_ENV, v)
        monkeypatch.setattr(aa, "mem_available_bytes", lambda: int(0.1 * GI))
        env, reason, w = aa.conc_calibration_env()
        assert w == expect
        assert env["SANDBAR_POOL_CONC"] == str(expect)
        monkeypatch.delenv(aa.CONC_CALIB_ENV)


# ---------------- 接线面：_run_scenarios 源内必须真实下单 ----------------

def test_run_scenarios_wires_calibration():
    """接线存在性（活动函数需 Temporal 上下文，不便真调）：校准单点必须被
    _run_scenarios 消费，且校准面回执字段在 shared 结果类型上（additive）。"""
    import inspect

    import shared

    src = inspect.getsource(aa._run_scenarios)
    assert "conc_calibration_env()" in src
    assert "_extra_env.update(_cal_env)" in src
    assert hasattr(shared.IntegrationRunResult(), "conc_calibration")
    assert shared.IntegrationRunResult().conc_calibration == {}  # 缺省=零漂移


def test_calibration_env_not_stripped_by_subprocess_env(monkeypatch):
    """注入面必须可达子进程：conc 键不在 integ_subprocess_env 的剥除集里。"""
    from shared import TEST_STUB_ENV_KNOBS, WORKER_ROUTING_ENV_KNOBS
    for k in ("SANDBAR_POOL_CONC", "SANDBAR_CONC_POOLS", aa.CONC_CALIB_ENV):
        assert k not in TEST_STUB_ENV_KNOBS
        assert k not in WORKER_ROUTING_ENV_KNOBS
