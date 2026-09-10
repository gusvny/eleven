#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260910-12 场景：满员诚实排队等待释放，不硬挤不假红（灰盒 L3，工单验收③）。

intent（登记于 run_scenarios.py SCENARIOS，本文件为其执行体）：
- 注入 SANDBAR_STAGE_MAX_STAGES=1（env 旋钮=方案注入口，只影响本场景子进程）
  做最小可观测形态；
- 先到者 A 占满唯一名额后，后到者 B 在 A 持有期内发起 ensure：**排队不退出
  不假红**（进程存活、无 STAGE_ENV 红行）；
- A down 释放名额后 B 预算内成功入位且端口可服务，全程无满员超时红；
- 排队成功腿为主断言面；超时文案腿归 developer L1（注入成本考量，intent
  不重复）；
- 终态零残留、持有腿收割。docker 缺席=ENV_FAIL exit 2。
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
CLI = os.path.join(REPO, "integration", "stage_docker.py")
sys.path.insert(0, HERE)
from lib_herd_case import (  # noqa: E402
    check,
    cli,
    compose_containers,
    docker_present,
    env_guard,
    envfail,
    finish,
    guarded_down,
    stage_tag,
    tcp_open,
)

TAG = stage_tag("t26091012-cap")  # 泳道唯一化（跨泳道同项目名互拆根治）
# 隔离锁根（arbitrate gen1 修正，非弱化）：容量闸计数=锁根内全部活租约，生产
# 锁根（/tmp/sandbar-test-stages）全机共享——并行泳道的活动台会被计入「我的
# 容量」，注入 MAX_STAGES=1 必然自卡死（gen0 全量跑两次 600s 超时实锤）。隔离
# 根上 MAX_STAGES=1 语义纯净：A/B 排队互斥（capacity flock + ensure flock +
# 租约状态机）全部真实同根执行，被测面=满员闸排队语义本身；跨泳道容量竞争
# 不属于本条 intent（生产由全局缺省值 12 承担）。
ISO_ROOT = "/tmp/sandbar-cap-t26091012"
ENV = {"SANDBAR_STAGE_MAX_STAGES": "1", "SANDBAR_STAGE_LOCK_DIR": ISO_ROOT}
PROJ_A, PROJ_B = "%s-a" % TAG, "%s-b" % TAG


def spawn_ensure(project, timeout_arg):
    """并发/排队发车：ensure 子进程（不等待；共享缺省锁根纪律）。"""
    env = dict(os.environ)
    env.update(ENV)
    return subprocess.Popen(
        [sys.executable, CLI, "ensure", "--project", project,
         "--services", "temporal", "--timeout", str(timeout_arg)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        cwd=REPO, env=env)


def main():
    if not docker_present():
        envfail("docker 缺席——满员排队面不可验（启动 Docker/OrbStack 后重试）")
        finish()
    os.makedirs(ISO_ROOT, exist_ok=True)
    try:
        # A 占满唯一名额（超时容错转 FAIL：三态契约要求总产出 SUMMARY 行）
        try:
            proc = cli("ensure", "--project", PROJ_A, "--services", "temporal",
                       timeout=600, env_extra=ENV)
        except subprocess.TimeoutExpired:
            check(False, "A 起台 600s 超时（容量闸排队未入位——隔离根上不应发生）")
            finish()
        env_guard(proc.stderr, "A 起台腿")
        if not check(proc.returncode == 0, "A 台起好（名额占满，rc=%s）"
                     % proc.returncode):
            finish()

        # B 发车：排队（存活、不硬挤）
        b_proc = spawn_ensure(PROJ_B, 300)
        time.sleep(8)
        check(b_proc.poll() is None, "B 排队中（8s 未退出=不硬挤不假红）")
        check(not compose_containers(PROJ_B), "B 排队期间零容器（没硬挤起台）")

        # A down 释放 → B 预算内入位
        d_proc = cli("down", "--project", PROJ_A, timeout=300, env_extra=ENV)
        env_guard(d_proc.stderr, "A 拆台腿")
        check(d_proc.returncode == 0, "A down 释放名额（rc=%s）" % d_proc.returncode)
        t0 = time.time()
        out_b, err_b = b_proc.communicate(timeout=300)
        env_guard(err_b, "B 入位腿")
        check(b_proc.returncode == 0, "B 在预算内入位双绿（rc=%s，用时 %.0fs）"
              % (b_proc.returncode, time.time() - t0))
        try:
            st_b = __import__("json").loads((out_b or "").strip().split("\n")[-1])
        except (ValueError, IndexError):
            st_b = None
        port_b = (st_b or {}).get("ports", {}).get("temporal")
        check(bool(port_b) and tcp_open(port_b), "B 台可服务（temporal %s）" % port_b)
        check("STAGE_ENV" not in (err_b or ""), "B 全程无 STAGE_ENV 红行（不假红）")
    finally:
        guarded_down([PROJ_A, PROJ_B])

    check(not compose_containers(PROJ_A), "A 终态零残留")
    check(not compose_containers(PROJ_B), "B 终态零残留")
    finish()


if __name__ == "__main__":
    main()
