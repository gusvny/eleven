#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260915-18 场景③：attempt→台名映射回执可查（灰盒 L3，工单「怎么算好②」+
「怎么算好③」容量可见半边的机械入口，integration 岗 design_integration_tests 段）。

intent（登记于 run_scenarios.py SCENARIOS，本文件为其执行体）：

- `stage_docker.py inventory` 回执是一份**机器可读+人可核对**的舞台清单：
  capacity 计数面（containers/projects/leases/orphans/max_stages）+ stages
  逐台条目（project/services/age_s/owner_workdir/lease{ticket,...}）；
- 起台时挂票号（SANDBAR_STAGE_TICKET=<票>-<代号>）→ 租约 holder.ticket 带
  票号 → inventory 条目里 **ticket→project→容器** 一眼可对——人工排障不再
  猜哈希台名（260915 排障为此耗掉大量时间=本票病灶四的用户面）；
- 未挂票号的台 ticket 落缺省值 unknown（不编造归属——报错精确纪律）；
- 台拆掉后条目随之消失（清单跟随真实容器面，不是租约账本的一面之词——
  当日「锁根 1 份租约 vs 38 只容器」的失明形态在回执层不可再现）。

与既有场景 intent 分工：t260912-02 系锚起台/清扫/网段的行为面；本条锚
**可见性回执**（inventory 只读、零 docker 变更动作）；工单③热台复用属
可选项且缺省关，其行为面归 developer L1+编排层 UT，本票场景不锚（缺省关
时无用户可感知行为变化）。与 t260910-12 租约四象限 L1 不同层。

注入面声明：票号经既有 env（SANDBAR_STAGE_TICKET，stage_docker 头注声明的
索租方身份面）注入。docker 缺席=ENV_FAIL exit 2。
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)

from lib_case import (  # noqa: E402
    ENV_STAGE_TICKET,
    check,
    docker_present,
    envfail,
    finish,
    guarded_down,
    inventory,
    iso_root18,
    rm_rf,
    stage_tag,
    up_ok,
    up_stage,
)

CAPACITY_KEYS = {"containers", "projects", "leases", "orphans", "max_stages"}


def _stage_entry(rpt, project):
    for st in ((rpt or {}).get("stages") or []):
        if isinstance(st, dict) and st.get("project") == project:
            return st
    return None


def main():
    if not docker_present():
        envfail("docker 不可用（docker info 失败）——测试台一律走 docker，"
                "启动 Docker/OrbStack 后重试")
        finish()
    tag = "%d" % (int(time.time()) % 100000)
    root = iso_root18("inventory-" + tag)
    ticket = "t260915-18-sc3-" + tag
    p1 = stage_tag("t26091518-inv-a-" + tag)   # 挂票号台
    p2 = stage_tag("t26091518-inv-b-" + tag)   # 未挂票号台
    try:
        proc, _ = up_stage(root, p1, env_extra={ENV_STAGE_TICKET: ticket})
        if not up_ok(proc, "挂票号台起台"):
            return
        proc, _ = up_stage(root, p2)
        if not up_ok(proc, "未挂票号台起台"):
            return

        # ---- 回执形状（机器可读面）----
        iproc, rpt = inventory(root)
        check(iproc.returncode == 0,
              "inventory rc=0（映射回执可查的唯一公开入口）｜rc=%s stderr=%s"
              % (iproc.returncode, " ".join((iproc.stderr or "").split())[:160]))
        check(isinstance(rpt, dict),
              "inventory 末行为 JSON 回执（脚本/人工两用，不假绿）")
        if not isinstance(rpt, dict):
            return
        cap = rpt.get("capacity")
        check(isinstance(cap, dict) and CAPACITY_KEYS.issubset(cap),
              "capacity 计数面六键齐（containers/projects/leases/orphans/"
              "max_stages）｜实得=%s" % sorted(cap or {}))
        check(isinstance(cap or {}, dict) and isinstance(
            (cap or {}).get("max_stages"), int)
            and (cap or {}).get("max_stages", 0) > 0,
            "capacity.max_stages=上限真值（容量可见=数与上限同面呈现）")

        # ---- 映射面：ticket→project→容器 一眼可对（工单②核心）----
        # 回执字段名以实现落地的公开形状为准（holder_ticket/working_dir/
        # age_s——与租约 JSON 字段名一致的扁平形状，260915 实现段在飞对齐）。
        s1 = _stage_entry(rpt, p1)
        check(s1 is not None, "挂票号台在 stages 清单中（台名不再是不可查哈希）")
        check((s1 or {}).get("holder_ticket") == ticket,
              "ticket→project 映射：回执 holder_ticket=起台挂的票号（%s）"
              % ticket)
        check(bool((s1 or {}).get("working_dir")),
              "working_dir 在场（台属于哪个泳道/目录可核对）")
        check(isinstance((s1 or {}).get("age_s"), (int, float))
              and (s1 or {}).get("age_s", -1) >= 0,
              "age_s 在场且非负（台龄可见）")
        check((s1 or {}).get("containers", 0) > 0,
              "containers 计数在场且>0（条目跟随真实容器面）")
        s2 = _stage_entry(rpt, p2)
        check(s2 is not None and (s2 or {}).get("holder_ticket") == "unknown",
              "未挂票号台 holder_ticket=unknown 缺省（不编造归属——报错精确纪律）")

        # ---- 清单跟随真实容器面（失明形态在回执层不可再现）----
        guarded_down([p1, p2], root)
        iproc2, rpt2 = inventory(root)
        gone = _stage_entry(rpt2, p1) is None and _stage_entry(rpt2, p2) is None
        check(iproc2.returncode == 0 and gone,
              "拆台后条目消失（清单跟随真实容器面，不是账本一面之词）")
    finally:
        guarded_down([p1, p2], root)
        rm_rf(root)
    finish()


if __name__ == "__main__":
    main()
