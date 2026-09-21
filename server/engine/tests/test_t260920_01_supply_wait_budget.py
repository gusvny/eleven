#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260920-01（stage-ops 票①）：供给面判据接线回归锁 + 供给段等待预算 UT。

覆盖（工单验收①②③④ + review_plan 条件②③④）：
- ① 供给失败用例（真实出口形态贯通）：tmp 泳道 verify.yaml supply → 真进程
  stage_docker daemon-probe（PATH 假 docker）→ verify_lane._integ 真实包装
  err（「supply 装配失败（need=…，exit=2）…供给面红点名」）→ IntegrationRunResult
  → _tests_supply_assembly_fail → _tests_round_account：不计轮 + 留痕含
  「不计入」+ 点名供给面（review 条件④：贯通用例用真实输出形态，不用手工串）。
- ② 等待超预算用例：daemon-probe（预算内未就绪 exit 2 + STAGE_WAIT 点名）、
  do_ensure 同项目互斥锁被占（sleeper 持 flock，预算内诚实红）、
  _wait_booting 超预算上抛（绝不落回冷路径并发再起）、capacity-0.lock 被占。
- ③ 等待点名用例：STAGE_WAIT 行含「在等谁/已等多久/为何未就绪」（节流常量收紧
  后逐轮可断言）。
- ④ 反用例不退化（review 条件③：只补 C2 未覆盖形态）：ran="3"/env_fail="2"
  字段畸形、activity 故障文案（H2 家族）、半标记 error、真产品红照计轮。
- review 条件②反用例：预算压缩不触及自家冷起 boot 健康窗（do_ensure 顶层
  timeout 原样透传 _boot_new_stage）。
- 签名↔闸出口漂移锁：读 server/tools/verify_lane.py 活台词，两态包装格式串
  在场且格式化后命中 shared 签名（「签名措辞与闸出口不一致」的永久防漂钉）。

UT 全程禁网络/真 docker/真 Temporal：假 docker 走 PATH 注入，锁根全部指 tmp
（SANDBAR_STAGE_LOCK_DIR + _LOCK_ROOT_CACHE 重置）；消费外部输入的畸形族
（预算 env 畸形 / error 非字符串 / 半标记文案）显式覆盖。
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]

sys.path.insert(0, str(REPO / "integration"))
import stage_docker as sd  # noqa: E402

sys.path.insert(0, str(REPO / "server" / "tools"))
import verify_lane  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import shared  # noqa: E402

from shared import tests_round_step as step_rounds  # noqa: E402
from shared import (  # noqa: E402
    tests_supply_assembly_error as supply_sig,
)
# 别名导入：tests_* 裸名会被 pytest 误收集为测试（t260917-09 同款坑，注释钉过）
from shared import tests_supply_assembly_note as supply_note  # noqa: E402


# ---------------------------------------------------------------- fixtures

@pytest.fixture()
def lockroot(tmp_path, monkeypatch):
    """tmp 锁根注入：env 指路 + 模块级缓存重置（lock_root 的 _LOCK_ROOT_CACHE）。"""
    root = tmp_path / "locks"
    root.mkdir()
    monkeypatch.setenv("SANDBAR_STAGE_LOCK_DIR", str(root))
    sd._LOCK_ROOT_CACHE = None
    yield root
    sd._LOCK_ROOT_CACHE = None


def _fake_docker_bin(tmp_path, body: str) -> Path:
    """假 docker 注入（PATH 前插）：body 为 sh 片段，不碰真 daemon。"""
    bin_ = tmp_path / "fakebin"
    bin_.mkdir(exist_ok=True)
    exe = bin_ / "docker"
    exe.write_text("#!/bin/sh\n%s\n" % body, encoding="utf-8")
    exe.chmod(0o755)
    return bin_


def _hold_lock(lockroot, name: str, hold_s: int = 30) -> subprocess.Popen:
    """sleeper 持锁用例：独立进程 flock 持 <lockroot>/<name>，打印 held 后沉睡；
    调用方负责 kill（全终态回收）。"""
    path = lockroot / name
    src = ("import fcntl,sys,time\n"
           "fd=open(%r,'a+')\n"
           "fcntl.flock(fd,fcntl.LOCK_EX)\n"
           "print('held',flush=True)\n"
           "time.sleep(%d)\n" % (str(path), hold_s))
    p = subprocess.Popen([sys.executable, "-c", src],
                         stdout=subprocess.PIPE, text=True)
    assert p.stdout is not None and p.stdout.readline().strip() == "held"
    return p


def _supply_lane(tmp_path, cmd: str) -> Path:
    """迷你泳道：最小合法 verify.yaml（过 _validate_cfg），supply 单条指向真
    stage_docker daemon-probe。"""
    lane = tmp_path / "lane"
    lane.mkdir()
    (lane / "verify.yaml").write_text(
        "schema: v1\n"
        "lanes:\n"
        "  code:\n"
        "    write_allow:\n"
        "      - server/\n"
        "integration:\n"
        "  cmd: \"true\"\n"
        "  supply:\n"
        "    - need: 测试台供给（UT 假台）\n"
        "      cmd: '%s'\n"
        "      timeout: 60\n" % cmd, encoding="utf-8")
    return lane


def _run_e2e_supply_exit2(tmp_path, monkeypatch) -> str:
    """真出口形态贯通用例（review 条件④）：daemon-probe 真进程 + 假 docker
    （睡 1s 失败）→ verify_lane 真实两态包装 err。返回 err 原文。"""
    fakebin = _fake_docker_bin(tmp_path, "sleep 1; exit 1")
    monkeypatch.setenv("PATH", str(fakebin) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("SANDBAR_STAGE_WAIT_BUDGET_S", "3")
    lane = _supply_lane(
        tmp_path,
        "%s %s daemon-probe" % (sys.executable,
                                REPO / "integration" / "stage_docker.py"))
    out = verify_lane._integ({"path": str(lane)})
    assert out.get("green") is False and out.get("err")
    return str(out["err"])


def _devlane_wf():
    import dev_lane
    return object.__new__(dev_lane.DevLaneWorkflow)


# ---------- A. 供给失败用例：真实出口形态 → 豁免不计轮 + 留痕点名（验收①） ----------

def test_a_e2e_exit2_receipt_exempt_and_named(tmp_path, monkeypatch):
    err = _run_e2e_supply_exit2(tmp_path, monkeypatch)
    # 真闸出口三要素（verify_lane 包装 + stage_docker 真负载）
    assert "supply 装配失败（need=测试台供给（UT 假台）" in err
    assert "exit=2" in err and "供给面红点名" in err
    assert "docker daemon 等待超预算" in err and "已等" in err
    # 判据面：零跑回执（agent_activities err 翻译形态：仅 error 字段非零默认）
    ir = shared.IntegrationRunResult(error=err)
    wf = _devlane_wf()
    assert wf._tests_supply_assembly_fail(ir)
    assert wf._tests_env_side_red(ir)
    # 计路面：不计轮 + 豁免账 + 留痕（要求①：含「不计入」+ 点名供给面）
    tr, ex, counted, note = asyncio.run(wf._tests_round_account(3, 0, ir))
    assert (tr, ex, counted) == (3, 1, False)
    assert "不计入" in note and "供给" in note and "supply 装配" in note
    # 原始证据随留痕上台面：留痕带 error 前缀截断窗（既有口径 [:120]），
    # 窗内是 STAGE_WAIT 点名头（真实负载），完整 ENV_FAIL 尾在 err 全文已断言
    assert "仍在等 docker daemon" in note
    # 留痕单写者：文案与 shared 纯函数逐字节同源
    assert note == supply_note(err)


def test_a_timeout_state_signature_and_note():
    """超时态（预算兜底前的另一供给失败形态）同命中签名与留痕单写者。"""
    err = ("supply 装配超时（need=测试台供给（UT 假台），>60s）——供给面红点名，不静默")
    assert supply_sig(err)
    ir = shared.IntegrationRunResult(error=err)
    wf = _devlane_wf()
    tr, ex, counted, note = asyncio.run(wf._tests_round_account(0, 0, ir))
    assert (tr, ex, counted) == (0, 1, False)
    assert "不计入" in note and "supply 装配超时" in note


def test_a_signature_gate_exit_drift_lock():
    """签名↔闸出口漂移锁：verify_lane 活台词两态格式串在场，格式化后必命中
    shared 签名——闸出口措辞一变本钉先红（宁窄勿宽口径的单写者防漂面）。"""
    src = (REPO / "server" / "tools" / "verify_lane.py").read_text("utf-8")
    fail_fmt = ("'supply 装配失败（need=%s，exit=%d）：%s——供给面红点名，不静默'")
    time_fmt = "'supply 装配超时（need=%s，>%ds）——供给面红点名，不静默'"
    assert fail_fmt % ("x", 2, "boom") and fail_fmt in src
    assert time_fmt % ("x", 60) and time_fmt in src
    for err in (fail_fmt % ("need-x", 2, "ENV_FAIL: boom——不硬等"),
                time_fmt % ("need-x", 60)):
        assert supply_sig(err), err
        for m in shared.SUPPLY_ASSEMBLY_ERROR_MARKS:
            assert m in err


def test_a_supply_note_single_writer_and_malformed():
    # 畸形 error 不抛、保守可读（消费外部输入纪律）
    for bad in (None, "", 3.5, b"supply"):
        n = supply_note(bad)
        assert "不计入" in n and "供给" in n
    assert supply_note("").endswith("：<空>）——不计入 tests-fault 轮次")
    long_err = "supply 装配失败（need=x，exit=2）：" + "长" * 300 + "——供给面红点名，不静默"
    assert len(supply_note(long_err)) < len(long_err)
    assert long_err[:120] in supply_note(long_err)


def test_a_dev_lane_note_sites_intact():
    """两处「本轮不计入 tests-fault 轮次」handoff 站点仍在（串行+平行）——
    留痕上台面的结构用例（t260917-04 守卫锚的同族轻量自证）。"""
    src = (REPO / "server" / "engine" / "dev_lane.py").read_text("utf-8")
    assert src.count("本轮不计入 tests-fault 轮次") == 2


# ---------- B. 等待超预算用例（验收②）+ 点名（验收③） ----------

def test_b_daemon_probe_overbudget_exit2_and_naming(tmp_path, monkeypatch):
    fakebin = _fake_docker_bin(tmp_path, "exec sleep 30")   # daemon 假死形态
    env = dict(os.environ, PATH=str(fakebin) + os.pathsep + os.environ["PATH"],
               SANDBAR_STAGE_WAIT_BUDGET_S="2",
               SANDBAR_STAGE_LOCK_DIR=str(tmp_path / "locks"))
    (tmp_path / "locks").mkdir()
    t0 = time.time()
    p = subprocess.run(
        [sys.executable, str(REPO / "integration" / "stage_docker.py"),
         "daemon-probe"],
        capture_output=True, text=True, env=env, timeout=60)
    assert p.returncode == 2                       # ENV_FAIL 三态（exit 2）
    assert "ENV_FAIL: docker daemon 等待超预算" in p.stderr
    assert "不硬等" in p.stderr
    assert time.time() - t0 < 15                   # 绝不硬等到 900s 兜底
    assert json.loads(p.stdout) if p.stdout.strip() else True  # 失败面无假 JSON


def test_b_daemon_probe_progress_naming(tmp_path, monkeypatch, capsys):
    """点名用例（验收③）：等 daemon 时 stderr 周期点名（在等谁/已等多久/为何）。"""
    fakebin = _fake_docker_bin(tmp_path, "sleep 0.2; exit 1")  # 快败→多轮探
    monkeypatch.setenv("PATH", str(fakebin) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("SANDBAR_STAGE_WAIT_BUDGET_S", "2")
    with pytest.raises(sd.StageError) as ei:
        sd.cmd_daemon_probe()
    assert ei.value.kind == "env" and ei.value.exit_code == 2
    err = capsys.readouterr().err
    assert "STAGE_WAIT" in err and "docker daemon" in err
    assert "已等" in err and "预算" in err


def test_b_daemon_probe_healthy_ok(tmp_path, monkeypatch, capsys):
    fakebin = _fake_docker_bin(tmp_path, "echo fake-ok")       # daemon 在场形态
    monkeypatch.setenv("PATH", str(fakebin) + os.pathsep + os.environ["PATH"])
    assert sd.cmd_daemon_probe() == sd.EXIT_OK
    doc = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert doc["daemon"] == "ok" and doc["budget_s"] == sd.wait_budget_s()


def test_b_ensure_lock_busy_overbudget(lockroot, tmp_path, monkeypatch, capsys):
    """同项目互斥锁被别人持台：预算内诚实红（exit 2）+ 点名，不硬等 600s。"""
    holder = _hold_lock(lockroot, "ensure-supplybusy.lock")
    try:
        monkeypatch.setenv("SANDBAR_STAGE_WAIT_BUDGET_S", "2")
        monkeypatch.setattr(sd, "STAGE_WAIT_PING_EVERY_S", 0.0)  # 收紧点名节流
        t0 = time.time()
        with pytest.raises(sd.StageError) as ei:
            sd.do_ensure("supplybusy", ["temporal"], {}, 600)
        assert ei.value.kind == "env" and ei.value.exit_code == 2
        msg = str(ei.value)
        # 守卫兼容：保留既有「互斥等待超时」标记短语（C5 同族判别面），预算为新增字段
        assert "ensure 互斥等待超时" in msg and "ENV_FAIL" in msg
        assert "等待预算" in msg and "不硬等" in msg and "supplybusy" in msg
        assert time.time() - t0 < 10
        err = capsys.readouterr().err
        assert "STAGE_WAIT" in err and "ensure 互斥锁" in err and "已等" in err
    finally:
        holder.kill()
        holder.wait()


def test_b_wait_booting_overbudget_raises_never_double_boot(lockroot, monkeypatch,
                                                            capsys):
    """booting 等待超预算：诚实红上抛（绝不落回冷路径并发再起——不变式用例）。"""
    lease = sd.new_lease("bootproj", os.getpid(), ["temporal"])
    lease["state"] = "booting"
    sd.write_lease("bootproj", lease)
    fd = os.open(str(lockroot / "ensure-bootproj.lock"),
                 os.O_RDWR | os.O_CREAT, 0o644)
    monkeypatch.setenv("SANDBAR_STAGE_WAIT_BUDGET_S", "1")
    monkeypatch.setattr(sd, "STAGE_WAIT_PING_EVERY_S", 0.0)
    try:
        t0 = time.time()
        with pytest.raises(sd.StageError) as ei:
            sd._wait_booting("bootproj", fd, time.time() + 600)
        assert ei.value.kind == "env"
        assert "booting 等待超预算" in str(ei.value)
        assert "不硬等也不并发再起" in str(ei.value)
        assert time.time() - t0 < 6
        assert "STAGE_WAIT" in capsys.readouterr().err
    finally:
        os.close(fd)


def test_b_capacity_lock_busy_overbudget(lockroot, monkeypatch, capsys):
    holder = _hold_lock(lockroot, "capacity-0.lock")
    try:
        monkeypatch.setenv("SANDBAR_STAGE_WAIT_BUDGET_S", "1")
        monkeypatch.setattr(sd, "STAGE_WAIT_PING_EVERY_S", 0.0)
        t0 = time.time()
        with pytest.raises(sd.StageError) as ei:
            sd.capacity_acquire("capproj", {"lease_id": "l1"}, 600)
        assert ei.value.kind == "env" and ei.value.exit_code == 2
        msg = str(ei.value)
        # 守卫兼容：保留既有「锁等待超时」标记短语，预算为新增字段
        assert "capacity-0.lock" in msg and "锁等待超时" in msg
        assert "等待预算" in msg and "ENV_FAIL" in msg
        assert time.time() - t0 < 8
        assert "STAGE_WAIT" in capsys.readouterr().err
    finally:
        holder.kill()
        holder.wait()


def test_b_heartbeat_grace_budgeted_and_named(lockroot, monkeypatch, capsys):
    """心跳宽限窗入预算帽：grace=min(stall_grace, 剩余 deadline, 预算)。"""
    lease = sd.new_lease("hbproj", os.getpid(), ["temporal"])
    lease.update(state="up", heartbeat_ts=time.time() - 9999, ttl_sec=30)
    sd.write_lease("hbproj", lease)
    fd = os.open(str(lockroot / "ensure-hbproj.lock"),
                 os.O_RDWR | os.O_CREAT, 0o644)
    monkeypatch.setenv("SANDBAR_STAGE_STALL_GRACE_S", "30")
    monkeypatch.setenv("SANDBAR_STAGE_WAIT_BUDGET_S", "1")
    monkeypatch.setattr(sd, "STAGE_WAIT_PING_EVERY_S", 0.0)
    try:
        t0 = time.time()
        st = sd._wait_heartbeat_recovery("hbproj", fd, time.time() + 600)
        assert not sd.lease_reusable(st)          # 宽限到期仍未恢复=诚实返回
        assert time.time() - t0 < 5               # 被预算帽住（未吃满 30s 宽限）
        assert "STAGE_WAIT" in capsys.readouterr().err
    finally:
        os.close(fd)


# ---------- C. 预算读数器：畸形回退（消费外部输入纪律） ----------

@pytest.mark.parametrize("raw,expect", [
    (None, 120.0), ("", 120.0), ("abc", 120.0), ("-3", 120.0), ("0", 120.0),
    ("2.5", 2.5), ("900", 900.0),
])
def test_c_wait_budget_reader_malformed_fallback(monkeypatch, raw, expect):
    if raw is None:
        monkeypatch.delenv("SANDBAR_STAGE_WAIT_BUDGET_S", raising=False)
    else:
        monkeypatch.setenv("SANDBAR_STAGE_WAIT_BUDGET_S", raw)
    assert sd.wait_budget_s() == expect


# ---------- D. review 条件②反用例：预算不误伤自家 boot 健康窗 ----------

def test_d_budget_never_caps_own_boot_window(lockroot, monkeypatch):
    captured = {}

    def _fake_boot(project, services_list, opts, timeout, cold_cleanup=False,
                   keep=False, **kw):
        captured["timeout"] = timeout
        captured["cold_cleanup"] = cold_cleanup
        return {"project": project, "booted": True}

    monkeypatch.setattr(sd, "_boot_new_stage", _fake_boot)
    monkeypatch.setenv("SANDBAR_STAGE_WAIT_BUDGET_S", "1")   # 预算极小也不许传染
    st = sd.do_ensure("bootwin", ["temporal"], {}, 555)
    assert st.get("booted") is True
    assert captured["timeout"] == 555      # 冷起健康窗原样透传，未被预算压缩
    assert captured["cold_cleanup"] is True


# ---------- E. 反用例不退化（验收④；review 条件③：只补 C2 未覆盖形态） ----------

def _supply_ir(**kw):
    d = dict(ran=0, passed=0, failed=0, env_fail=0,
             error="supply 装配失败（need=x，exit=2）：ENV_FAIL——供给面红点名，不静默")
    d.update(kw)
    return shared.IntegrationRunResult(**d)


def test_e_field_malformed_shapes_stay_conservative():
    wf = _devlane_wf()
    assert not wf._tests_supply_assembly_fail(_supply_ir(ran="3"))     # int("3")>0
    assert not wf._tests_supply_assembly_fail(_supply_ir(env_fail="2"))  # 畸形计数
    assert not wf._tests_supply_assembly_fail(_supply_ir(blockers=["gate-x"]))
    # C2 未覆盖的负例形态：activity 故障文案（H2 家族——非签名启动级出口）
    assert not wf._tests_supply_assembly_fail(_supply_ir(
        error="集成测试 activity 故障：CancelledError: cancelled"))
    # 半标记：只有「供给面红」无「supply 装配」→ 不命中（宁窄勿宽）
    assert not supply_sig("——供给面红点名，不静默")


def test_e_product_red_still_counts():
    """真产品红照旧计轮、照旧红（验收④主断言；与 C2 混合面互补）。"""
    wf = _devlane_wf()
    ir = shared.IntegrationRunResult(ran=5, passed=3, failed=2,
                                     details=[{"name": "case-a", "exit": 1}])
    assert not wf._tests_env_side_red(ir)
    tr, ex, counted, note = step_rounds("tests-fault", 0, 0)
    assert (tr, ex, counted) == (1, 0, True) and note == "counted"


def test_e_exempt_cap_cover_family_untouched():
    """豁免账封面家族不回退：供给轮吃豁免上限封面（防活循环上限仍在）。"""
    from shared import MAX_TESTS_EXEMPT_ROUNDS, tests_exempt_cap_blocked_text
    cover = tests_exempt_cap_blocked_text(MAX_TESTS_EXEMPT_ROUNDS + 1)
    assert "超限" in cover
    for kw in ("authorize", "ruling", "rework", "pause"):
        assert kw in cover, kw


# ---------- F. 等待点名/红文案措辞守卫：不与保险丝刹停红判别词表相撞（gen1 打回修复，gen8 扩面） ----------

def test_f_wait_ping_copy_never_matches_fuse_mark():
    """仲裁 gen7 打回守卫用例（防回潮）：t260912-02 burst 场景以 FUSE_MARK=「保险丝」
    （integration/t260912-02/lib_lifecycle_case.py:49，assertIn 语义的反面）判别
    保险丝**刹停红真触发**；等待点名是并发争用的**常态输出**，文案共用该词根=
    判别失效假红（gen0 实锤：32/48 台用例两断言败）。守卫=AST 扫全部
    _stage_wait_ping 调用点的字符串字面量（位置参+关键字参+格式串左侧），
    断言不含「保险丝」与刹停红正文词根 SANDBAR_STAGE_MAX_STAGES——未来加等待点/
    改文案都会过这道门。正向对照：真刹停红正文仍含两词根（FUSE_MARK 判别力不
    回退）。范围注：StageError 运行时红文案面由下方 test_f2 单独守卫——本用例
    旧范围注称 StageError「真红时场景本就红、判别混淆无害」不成立（gen8 打回
    实锤：环境红共用「保险丝」词根会被 burst 场景 FUSE_MARK 断言吞成刹停红
    假红+归因污染，且 :771 红是本票新增非既有家族）。"""
    import ast as ast_mod
    src = (REPO / "integration" / "stage_docker.py").read_text("utf-8")
    tree = ast_mod.parse(src)
    calls = 0
    lits = []

    def _harvest(node):
        if isinstance(node, ast_mod.Constant) and isinstance(node.value, str):
            lits.append(node.value)
        elif isinstance(node, ast_mod.BinOp) and isinstance(node.op, ast_mod.Mod):
            _harvest(node.left)

    for node in ast_mod.walk(tree):
        if isinstance(node, ast_mod.Call) \
                and isinstance(node.func, ast_mod.Name) \
                and node.func.id == "_stage_wait_ping":
            calls += 1
            for a in node.args:
                _harvest(a)
            for kw in node.keywords:
                _harvest(kw.value)
    assert calls >= 5, "等待点名调用点应 ≥5（ensure/booting/心跳/capacity/daemon），见 %d" % calls
    assert len(lits) >= 10, "点名文案字面量采集过少，AST 规则失效？见 %r" % lits
    for s in lits:
        assert "保险丝" not in s, "点名文案撞保险丝刹停判别词根（FUSE_MARK）：%r" % s
        assert "SANDBAR_STAGE_MAX_STAGES" not in s, "点名文案撞刹停红正文词根：%r" % s
    trip_red = "起台保险丝（SANDBAR_STAGE_MAX_STAGES=12）触发：活租约 12 已达上限"
    assert "保险丝" in trip_red and "SANDBAR_STAGE_MAX_STAGES" in trip_red


def test_f2_stage_error_copy_fuse_word_must_anchor_trip_red():
    """仲裁 gen8 打回扩面用例（防回潮）：F 节点名扫描只覆盖 _stage_wait_ping，
    StageError 运行时红文案不在范围——gen8 同族全量排查实锤 ：771 锁超预算
    ENV_FAIL（本票新增）含「保险丝」裸词：锁被残留进程长期持有时收环境红
    （kind=env），文案进 burst 场景 subprocess stderr 被 FUSE_MARK 断言吞成
    「刹停红触发」假红+归因污染（环境红误叙为产品红=t260904-12 纪律反例）。
    守卫判据（宁窄勿宽）：AST 扫全部 StageError 调用的字符串字面量（位置参+
    %格式串左侧），含「保险丝」者必含 SANDBAR_STAGE_MAX_STAGES——刹停红家族
    （capacity 刹停红 ：792 / fuse_precheck 预检红 ：1920，场景正向断言锚）
    合法保留，其余运行时输出一律不许共用该词根。正向对照：含「保险丝」的红
    文案应 ≥2 且全含刹停正文词根（FUSE_MARK 判别力不回退）。边界注：message
    为变量拼接（非字面量、非 %格式串字面量）的调用点静态采不到，不在守卫
    范围——判据只对可静态采集的字面量生效，与「判据宁窄勿宽」纪律一致。"""
    import ast as ast_mod
    src = (REPO / "integration" / "stage_docker.py").read_text("utf-8")
    tree = ast_mod.parse(src)
    calls = 0
    all_lits = []

    def _harvest(node):
        if isinstance(node, ast_mod.Constant) and isinstance(node.value, str):
            all_lits.append(node.value)
        elif isinstance(node, ast_mod.BinOp) and isinstance(node.op, ast_mod.Mod):
            _harvest(node.left)

    for node in ast_mod.walk(tree):
        if isinstance(node, ast_mod.Call) \
                and isinstance(node.func, ast_mod.Name) \
                and node.func.id == "StageError":
            calls += 1
            for a in node.args:
                _harvest(a)
            for kw in node.keywords:
                _harvest(kw.value)
    assert calls >= 40, "StageError 调用点应 ≥40（现约 68 处），AST 规则失效？见 %d" % calls
    assert len(all_lits) >= 60, "红文案字面量采集过少，AST 规则失效？见 %d" % len(all_lits)
    fuse_lits = [s for s in all_lits if "保险丝" in s]
    for s in fuse_lits:
        assert "SANDBAR_STAGE_MAX_STAGES" in s, \
            "红文案含「保险丝」但缺刹停正文词根=撞 FUSE_MARK 判别" \
            "（环境红会被吞成刹停红假红）：%r" % s
    assert len(fuse_lits) >= 2, \
        "含「保险丝」的刹停红家族应 ≥2（capacity 刹停红 + fuse_precheck 预检红），" \
        "FUSE_MARK 判别力回退？见 %r" % fuse_lits
