#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260910-12 场景：起台保险丝刹停点名不假红（灰盒 L3，工单验收③）。

语义迁移（t260912-02 ①，断言强度等价非放宽）：原「满员诚实排队等待释放」随
名额排队闸一并退役——排队闸是全机共用名额，实测只制造假拥堵（上限 12 时 12 台
并发 3 台卡满 150s；改 30 即 12/12 共 5.3s）。闸的职责收敛为防呆保险丝，本场景
改锚新契约：
- 注入 SANDBAR_STAGE_MAX_STAGES=1（env 旋钮=方案注入口，只影响本场景子进程）
  做最小可观测形态；
- 先到者 A 占满唯一额度后正常起台、全程可服务（**先到者不受扰**——原场景
  「A 不受扰」子用例保留）；
- 后到者 B 在 A 持有期内发起 ensure **立即刹停退出**（原「排队不退出」子用例按新
  语义翻转）：rc=2、stderr 点名「起台保险丝」并附活租约清单（holder pid/票号/
  lease id）、期间零容器（不硬挤不假红）、红行**不含「满员」字样**（瞬态白名单
  按字样自动重试，失控红不得被重试放大）；
- A down 释放额度后 C 预算内成功入位且端口可服务（**释放准入**子用例保留）；
- 终态零残留、持有子用例收割。docker 缺席=ENV_FAIL exit 2。

intent（登记于 run_scenarios.py SCENARIOS，本文件为其执行体；原排队语义退役
已在注册行注明）。
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
CLI = os.path.join(REPO, "integration", "stage_docker.py")
sys.path.insert(0, HERE)
from lib_herd_case import (  # noqa: E402
    bench_gate,
    check,
    cli,
    env_guard,
    envfail,
    finish,
    guarded_down,
    stage_tag,
    tcp_open,
)

TAG = stage_tag("t26091012-cap")  # 泳道唯一化（跨泳道同项目名互拆根治）
# 隔离锁根（arbitrate gen1 修正沿袭，非弱化）：保险丝计数=锁根内全部活租约，
# 生产锁根全机共享——并行泳道的活动台会被计入「我的额度」，注入 MAX_STAGES=1
# 必然自卡死（gen0 全量跑两次 600s 超时实锤）。隔离根上 MAX_STAGES=1 语义纯净：
# A/B/C 判定互斥（capacity flock + ensure flock + 租约状态机）全部真实同根执行，
# 被测面=保险丝判定语义本身；跨泳道竞争不属于本条 intent（生产由缺省值 100 承担）。
ISO_ROOT = "/tmp/sandbar-cap-t26091012"
ENV = {"SANDBAR_STAGE_MAX_STAGES": "1", "SANDBAR_STAGE_LOCK_DIR": ISO_ROOT}
PROJ_A = "%s-a" % TAG
PROJ_B = "%s-b" % TAG
PROJ_C = "%s-c" % TAG


def last_json(proc):
    try:
        return json.loads((proc.stdout or "").strip().split("\n")[-1])
    except (ValueError, IndexError):
        return {}


def main():
    bench_gate()   # 进程台供给门（docker_present 的等价物，t261027-11 迁移）
    os.makedirs(ISO_ROOT, exist_ok=True)
    try:
        # A 占满唯一额度（超时容错转 FAIL：三态契约要求总产出 SUMMARY 行）
        try:
            proc = cli("ensure", "--project", PROJ_A, "--services", "temporal",
                       timeout=600, env_extra=ENV)
        except subprocess.TimeoutExpired:
            check(False, "A 起台 600s 超时（保险丝不应拦第一台——隔离根上不应发生）")
            finish()
        env_guard(proc.stderr, "A 起台子用例")
        if not check(proc.returncode == 0, "A 台起好（额度占满，rc=%s）"
                     % proc.returncode):
            finish()
        port_a = ((last_json(proc) or {}).get("ports") or {}).get("temporal")
        check(bool(port_a) and tcp_open(port_a),
              "A 台可服务（先到者不受扰，temporal %s）" % port_a)
        a_holder_pid = (last_json(proc) or {}).get("holder", {}).get("pid")

        # B 发车：立即刹停（不排队、不硬挤、不假红）
        t0 = time.time()
        proc_b = cli("ensure", "--project", PROJ_B, "--services", "temporal",
                     timeout=120, env_extra=ENV)
        dur_b = time.time() - t0
        check(proc_b.returncode == 2, "B 刹停红 rc=2（env 语义，实际 rc=%s）"
              % proc_b.returncode)
        check(dur_b < 60, "B 立即刹停不排队（%.1fs 内退出；旧排队语义是挂住等释放）"
              % dur_b)
        err_b = proc_b.stderr or ""
        check("起台保险丝" in err_b, "B 红行点名「起台保险丝」：%s"
              % " ".join(err_b.split())[:120])
        check("SANDBAR_STAGE_MAX_STAGES=1" in err_b, "B 红行点名注入上限")
        check(("pid=%s" % a_holder_pid) in err_b or PROJ_A in err_b,
              "B 红行附活租约清单（holder pid / 工程名可辨）")
        check("满员" not in err_b, "B 红行不含「满员」字样（瞬态白名单不得重试失控红）")
        # B 期间零新起台（t261027-11 迁移改名：容器计数面由 runner 窗口看守承接，
        # 场景内改以「B 名下无活租约」观测——不硬挤不假红的语义原样）。
        # SANCTIONED-WAIT: inventory is a read-only docker/lease query bound, not a sleep
        inv = last_json(cli("inventory", timeout=120, env_extra=ENV))
        live_b = [l for l in ((inv or {}).get("stages") or [])
                  if isinstance(l, dict) and l.get("project") == PROJ_B
                  and l.get("state") in ("up", "booting")]
        check(not live_b, "B 期间零新起台（B 名下无活租约，不硬挤起台）")

        # A down 释放 → C 预算内入位（释放准入子用例保留）
        d_proc = cli("down", "--project", PROJ_A, timeout=300, env_extra=ENV)
        env_guard(d_proc.stderr, "A 拆台子用例")
        check(d_proc.returncode == 0, "A down 释放额度（rc=%s）" % d_proc.returncode)
        t0 = time.time()
        proc_c = cli("ensure", "--project", PROJ_C, "--services", "temporal",
                     timeout=600, env_extra=ENV)
        env_guard(proc_c.stderr, "C 入位子用例")
        check(proc_c.returncode == 0, "C 释放后预算内入位（rc=%s，用时 %.0fs）"
              % (proc_c.returncode, time.time() - t0))
        port_c = ((last_json(proc_c) or {}).get("ports") or {}).get("temporal")
        check(bool(port_c) and tcp_open(port_c), "C 台可服务（temporal %s）" % port_c)
    finally:
        # env_extra 必须随行（t261027-11 arbitrate gen3 根因）：本场景的台
        # 全在隔离锁根 ISO_ROOT——不带 ENV 的 down 打在缺省根上是空操作，C 的
        # 租约在 ISO_ROOT 里活到 hold 锚回收才消（docker 台时代 compose down
        # 与锁根无关所以从未暴露；进程台的 down 依赖租约里的 bench 身份）。
        guarded_down([PROJ_A, PROJ_B, PROJ_C], env_extra=ENV)

    for proj in (PROJ_A, PROJ_B, PROJ_C):
        # 终态零残留（进程台观测面，t261027-11 迁移改名）：down 后租约消亡，
        # inventory 无在册活台——容器计数归 runner 窗口看守。
        # SANCTIONED-WAIT: inventory is a read-only docker/lease query bound, not a sleep
        inv2 = last_json(cli("inventory", timeout=120, env_extra=ENV))
        live = [l for l in ((inv2 or {}).get("stages") or [])
                if isinstance(l, dict) and l.get("project") == proj
                and l.get("state") in ("up", "booting")]
        check(not live, "%s 终态零残留（租约已释放）" % proj)
    finish()


if __name__ == "__main__":
    main()
