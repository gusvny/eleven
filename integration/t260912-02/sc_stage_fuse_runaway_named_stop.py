#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260912-02 场景：失控起台循环被保险丝刹停并逐条点名（灰盒 L3，工单验收 E
的机械入口，integration 岗 design_integration_tests 段）。

intent（登记于 run_scenarios.py SCENARIOS，本文件为其执行体）：
- 注入小保险丝（SANDBAR_STAGE_MAX_STAGES=4，隔离锁根——生产缺省 100 的
  「不触闸」面由 burst 场景与 L1 缺省值断言承担，此处不重复）+ 一口气 200 路
  并发 up（失控循环样本）：恰 ≤4 路入位、其余全部被刹停且每路红行点名保险丝
  并附活租约清单（holder pid/票号/lease 可核对——「点名」是硬断言不是措辞
  偏好）、刹停红一律环境档 rc=2（不放大不重试）；
- 损害有界：全程在跑容器 ≤4 台规模、风暴结束后无孤儿持有腿进程残留
  （pgrep 公开观测面）、清理后零容器残留——「不得无声吃满机器」的机械面；
- 全程零地址池报错（失控样本也不得撞池）。

与既有场景 intent 分工：t260910-12-full-capacity-queue 是闸语义的迁移面
（小闸后到者被刹停点名——2 路最小形态，随 developer 实现段迁移）；本条锚
**风暴规模（200 路）下的损害有界与逐条点名**，是验收 E 的本体强度，2 路形态
替代不了。docker/测试镜像缺席=ENV_FAIL exit 2（全部 ENV_FAIL 零保险丝红时
按环境红收口，不诬产品）。实现段落地前红属预期（TDD 信号），arbitrate/merge
期必须绿。
"""
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib_lifecycle_case import (  # noqa: E402
    FORBIDDEN_PORTS,
    FUSE_MARK,
    PROD_PORTS,
    check,
    cli_async,
    compose_containers,
    docker_present,
    envfail,
    finish,
    guarded_down,
    hold_pids_prefix,
    iso_root,
    stage_tag,
)

TAG = stage_tag("t26091202-runaway")
ROOT = iso_root("runaway")
N_TOTAL = 200
FUSE_LIMIT = 4
FUSE_ENV = {"SANDBAR_STAGE_MAX_STAGES": str(FUSE_LIMIT)}
STORM = ["%s-s%03d" % (TAG, i) for i in range(N_TOTAL)]
WORKERS = 16   # 失控循环的并发形态（16 路循环 200 次，非 200 进程齐发）


def main():
    if not docker_present():
        envfail("docker 缺席——保险丝刹停面不可验（启动 Docker/OrbStack 后重试）")
        finish()

    t0 = time.time()
    results = []

    def _one(proj):
        proc = cli_async(ROOT, "up", "--project", proj, "--services",
                         "temporal", "--timeout", "240", env_extra=FUSE_ENV)
        try:
            out, err = proc.communicate(timeout=360)
            return (proj, proc.returncode, out or "", err or "")
        except Exception as exc:   # 执行器杀死等：按产品红记录，不吞
            return (proj, -1, "", "异常 %r" % (exc,))

    try:
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            results = list(ex.map(_one, STORM))
        wall = time.time() - t0

        oks = [(p, rc, o, e) for p, rc, o, e in results if rc == 0]
        fuse = [(p, rc, o, e) for p, rc, o, e in results
                if rc == 2 and FUSE_MARK in e]
        other = [(p, rc, (e or "")[-140:]) for p, rc, o, e in results
                 if rc != 0 and not (rc == 2 and FUSE_MARK in e)]

        if not oks and not fuse and results:
            # 全军覆没且无保险丝红=供给面缺席（镜像/daemon），按环境红收口
            envfail("200 路全部非保险丝红（无入位无刹停——供给面缺席样本：%s）"
                    % other[:2])
            finish()

        check(len(oks) >= 1, "至少 1 路入位（实得 %d）" % len(oks))
        check(len(oks) <= FUSE_LIMIT,
              "入位 ≤ 保险丝档 %d（实得 %d——原子不超售）" % (FUSE_LIMIT, len(oks)))
        check(len(fuse) == N_TOTAL - len(oks),
              "其余 %d 路全部被保险丝刹停（实得 %d）"
              % (N_TOTAL - len(oks), len(fuse)))
        check(not other, "刹停面之外零杂红（违例 %s）" % other[:3])

        # 点名面：每路刹停红都带保险丝字样与活租约清单（可核对 pid/lease）
        unnamed = [p for p, _rc, _o, e in fuse
                   if FUSE_MARK not in e or "lease=" not in e
                   or "pid=" not in e]
        check(not unnamed, "%d 路刹停全部点名保险丝+附活租约清单（缺 %s）"
              % (len(fuse), unnamed[:3]))
        check("STAGE_ENV" in "\n".join(e for _p, _r, _o, e in fuse),
              "刹停红走环境档（STAGE_ENV，不放大不重试）")

        # 损害有界
        all_err = "\n".join(e for _p, _r, _o, e in results)
        all_out = "\n".join(o for _p, _r, o, _e in results)
        check("fully subnetted" not in (all_err + all_out),
              "失控样本零地址池报错")
        live_containers = sum(len(compose_containers(p)) for p in STORM)
        check(live_containers <= FUSE_LIMIT,
              "在跑容器 ≤%d（实得 %d——不得无声吃满机器）"
              % (FUSE_LIMIT, live_containers))
        check(wall <= 420, "风暴墙钟有界（%.0fs，无排队挂死）" % wall)

        # 端口面（入位者）
        ports = []
        for _p, _rc, o, _e in oks:
            try:
                st = __import__("json").loads((o or "").strip().split("\n")[-1])
            except (ValueError, IndexError):
                st = {}
            for v in (st.get("ports") or {}).values():
                try:
                    ports.append(int(v))
                except (TypeError, ValueError):
                    pass
        check(len(ports) == len(set(ports)), "入位者端口两两互异")
        check(not (set(ports) & (PROD_PORTS | FORBIDDEN_PORTS)),
              "入位者端口 ∉ 生产/禁区面")

        # 清场 + 孤儿持有腿清点
        downs = guarded_down([p for p, _rc, _o, _e in oks], ROOT)
        check(all(rc == 0 for rc in downs.values()), "入位台终态拆台全 rc=0")
        residue = [p for p in STORM if compose_containers(p)]
        check(not residue, "风暴终态零容器残留（残留 %s）" % residue[:3])
        orphans = hold_pids_prefix(TAG)
        check(not orphans, "无孤儿持有腿残留（pgrep 命中 %s）" % orphans[:5])
    finally:
        guarded_down(STORM, ROOT)
    finish()


if __name__ == "__main__":
    main()
