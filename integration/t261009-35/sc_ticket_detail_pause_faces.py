#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261009-35 场景：暂停二态必须同时活在两张脸——列表行与详情面（detail face）。

intent（守护的用户可感知行为，工单 t261009-35 宿主报障「ui 上 pause 了 31，
没法 resume，按钮还是 pause」）：
- 真暂停（引擎 pause 操作驱动，绝不手工构造状态）后，列表脸（ticket-list 行）
  与详情脸（server/tools/ticket.py op=show 的顶层 meta）**同一时刻**都携带
  paused=true / paused_phase=at_gate——用户在详情面看到的按钮推导数据源与列表
  徽标同源（snapshot 顶层键，TicketPauseMixin 产物）。
- 缺席不造谣：暂停前（snapshot 无 paused 键的常态票）详情脸 paused=False、
  paused_phase=''——布尔与字符串归一，绝不 absent/'unknown'/从 stage_state 推导。
- 恢复后两脸同归 False/''——置位清干净，按钮回到 Pause。
- 派生契约接缝：show 顶层两键类型恒 bool/str（控制台 detail 的 availableOps
  → pauseOpOf 消费的正是这两个键；类型漂移=按钮恒 Pause 病灶复发）。

intent 分工（防重复，对照在册场景清单）：
- t260908-01-sc_ticket_pause_gate 锁暂停**机制**（在飞粒度/幂等拒收/观察窗冻结/
  pause×rework/模板通用性）+ 列表行 paused 徽标数据源——本条不重复这些，暂停
  只作为驱动手段（前置共享 helpers 复用，岗位纪律允许）。
- 本条独占面=**详情脸携带暂停二态**（ticket.py _v2_query 顶层投影）+ 两脸一致
  （同一 snapshot 真源同时反映在 list 行与 show 顶层）+ 缺席键归一。
- availableOps/pauseOpOf 纯函数真值表与 TicketDetail 类型声明=workbench
  developer L1（本票 tests/t261009-35-detail-paused.mjs）——本场景不跑 TS、
  不锚 UI 文案字面。

灰盒声明：断言只落公开契约面——client.py ticket-list 行键、ticket.py show
顶层键与类型。不 import 引擎内部、不读 workflow 私有结构。

预算注记：engine 池 900s/条；桩脑 + stub delay 下主旅程分钟级（t260908-01
同台实测）。实现落地前红属预期（TDD 信号：D3 子用例红=_v2_query 未投影两键
=本票病灶复现），arbitrate/merge 期必须绿；docker/镜像/舞台缺件=ENV_FAIL
exit 2 点名（三态契约，无 SKIP）。
KI 相邻面：KI-068（列表脸不透传 paused=同族前科，t260910-04 修复；本票=详情
脸同族复发面，教训「同路径推断会在不算实证」——详情脸必须活体断言）。
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
INTEG = os.path.dirname(HERE)
REPO = os.path.dirname(INTEG)
sys.path.insert(0, INTEG)
sys.path.insert(0, os.path.join(INTEG, "t260904-02"))  # lib_gate 共享夹具库（先例场景同仓复用）
sys.path.insert(0, os.path.join(INTEG, "t260908-01"))  # 共享暂停旅程 helpers（先例同仓复用）

from lib_gate import (Fail, cleanup, parse_out_json, poc_python, port_listening,  # noqa: E402
                      require_bench, require_stage, stage_down)
import stage_docker  # noqa: E402
import sc_ticket_pause_gate as P  # noqa: E402  共享夹具/worker/信号 helpers（零拓扑新面）


def tk_show(py, stage, tid, timeout=180):
    """详情脸读者侧真路径：真仓工作树 server/tools/ticket.py op=show（t260914-04
    tk_cli 同形——夹具仓 clone 自 HEAD，本票改动必须跑真仓工作树才可见）。

    返回 (ok, result_dict)：show 回执 stdout 单行 JSON 契约，result 即详情
    顶层 face（_v2_query[0] meta 原样）。"""
    payload = {"op": "show", "id": tid, "project": P.PROJECT_KEY,
               "caller_project": P.PROJECT_KEY}  # L9/L12：票入口调用点显式声明身份（call-scoped）
    env = P.env_for(stage, {"SANDBAR_ADMIN_LOG": os.path.join(P.G["tmp"], "admin-entry.log")})
    env["SANDBAR_CALLER_PROJECT"] = P.PROJECT_KEY  # 票入口身份显式钉死（夹具项目，防继承外层泳道）
    p = subprocess.run([py, os.path.join(REPO, "server", "tools", "ticket.py"),
                        json.dumps(payload, ensure_ascii=False)],
                       env=env, cwd=REPO, capture_output=True, text=True, timeout=timeout)
    body = parse_out_json((p.stdout or "") + (p.stderr or ""))
    if body.get("ok") is not True:
        return False, {"error": str(body.get("error") or body)[:200]}
    return True, body.get("result") or {}


def list_row(py, stage, tid):
    """列表脸读者侧真路径：client.py ticket-list，取本票行（无行=None）。"""
    body = P.cli(py, stage, "ticket-list", {"project": P.PROJECT_KEY})
    rows = (body.get("result") or {}).get("tickets") or []
    return next((r for r in rows if r.get("id") == tid), None)


def main():
    fail = Fail("t261009-35 详情脸暂停二态门")
    bench = require_bench(fail)
    py = poc_python(bench)
    workers = []
    stage_mod, stage = None, None
    try:
        # ---------- L0 舞台与拓扑（全复用 t260908-01 共享 helpers） ----------
        stage_mod, stage = require_stage(fail, "t26100935-dpf-%d" % os.getpid(),
                                         "stage-dpf-%d" % os.getpid())
        fe = int(stage["ports"]["temporal"])
        fail.check(port_listening(fe), "L0 舞台 temporal %d 探活" % fe)
        fail.check(fe not in stage_docker.FORBIDDEN_PORTS,
                   "L0 写守卫：舞台端口 %d ∉ 禁区（绝不回落生产 7233）" % fe)
        P.build_fixture(fail)
        # 夹具并发限额声明（bench.py 同款形状 {"version":1,"limit":N}）：引擎自
        # main-sync 后对缺席声明 fail-closed（concurrency.py load_limit）——夹具
        # 只有 project.yaml 时票在 concurrency_acquire 直接收口 FAILED（两轮实锤
        # worker 日志原文）。夹具给小上限够跑链路即可，不冒充真环境。
        decl = os.path.join(P.G["projects"], P.PROJECT_KEY, "concurrency-limit.json")
        with open(decl, "w", encoding="utf-8") as f:
            f.write(json.dumps({"version": 1, "limit": 4}) + "\n")

        # ---------- L1 scratch 票 + 桩脑 worker（真链路，非手工状态） ----------
        tid = "dpf-e2e-%x" % os.getpid()
        w = P.start_worker(py, stage, tid)
        workers.append(w)
        r = P.ticket_start(py, stage, tid, "dev-lane")
        fail.check(r.get("ok") is True,
                   "L1 dev-lane scratch 票开票 ok（实得 %s）" % str(r.get("error") or r)[:160])
        if r.get("ok") is not True:
            fail.bail("开票失败，主旅程无从谈起", 1)
        P.wait_snap(fail, py, stage, tid,
                    lambda x: bool(x.get("stage")) and x.get("stage_state") == "running",
                    "L1 首段进入 running", 240)

        # ---------- D1 缺席不造谣：暂停前详情脸归一 False/'' ----------
        ok, detail = tk_show(py, stage, tid)
        fail.check(ok, "D1 详情脸 show 回执 ok（实得 %s）" % str(detail.get("error") or "")[:160])
        if ok:
            fail.check(detail.get("paused") is False,
                       "D1 暂停前详情脸 paused=False（缺席键归一布尔，绝不 absent/"
                       "'unknown'/stage_state 推导；实得 %r）" % (detail.get("paused"),))
            fail.check(detail.get("paused_phase") == "",
                       "D1 暂停前详情脸 paused_phase=''（空串归一；实得 %r）"
                       % (detail.get("paused_phase"),))

        # ---------- D2 真暂停（引擎 pause 操作）→ 引擎态 at_gate ----------
        P.signal_pause(py, stage, tid, "e2e-host", "详情脸一致性暂停")
        P.wait_snap(fail, py, stage, tid,
                    lambda x: x.get("paused") is True and x.get("paused_phase") == "at_gate",
                    "D2 真暂停停在段间门口（paused+at_gate）", 240)

        # ---------- D3 详情脸携带暂停二态（本票修复面；改动前红=TDD 信号） ----------
        ok, detail = tk_show(py, stage, tid)
        if fail.check(ok, "D3 暂停中详情脸 show 回执 ok（实得 %s）"
                      % str(detail.get("error") or "")[:160]) and ok:
            fail.check(detail.get("paused") is True,
                       "D3 详情脸顶层 paused=True（_v2_query 顶层投影=本票病灶面；实得 %r）"
                       % (detail.get("paused"),))
            fail.check(detail.get("paused_phase") == "at_gate",
                       "D3 详情脸顶层 paused_phase='at_gate'（实得 %r）"
                       % (detail.get("paused_phase"),))
            fail.check(isinstance(detail.get("paused"), bool)
                       and isinstance(detail.get("paused_phase"), str),
                       "D3 两键类型恒 bool/str（detail 按钮推导数据源契约接缝）")

        # ---------- D4 列表脸同源一致（同一时刻两脸都报暂停） ----------
        row = list_row(py, stage, tid)
        if fail.check(row is not None, "D4 ticket-list 含本票行"):
            fail.check(row.get("paused") is True and row.get("paused_phase") == "at_gate",
                       "D4 列表行 paused/paused_phase 与详情脸同值（两脸一源；实得 "
                       "%r/%r）" % (row.get("paused"), row.get("paused_phase")))

        # ---------- D5 恢复后两脸同归 False/'' ----------
        P.signal_resume(py, stage, tid, "e2e-host", "详情脸一致性恢复")
        P.wait_snap(fail, py, stage, tid, lambda x: x.get("paused") is False,
                    "D5 引擎置位清干净", 240)
        ok, detail = tk_show(py, stage, tid)
        if fail.check(ok, "D5 恢复后详情脸 show 回执 ok") and ok:
            fail.check(detail.get("paused") is False and detail.get("paused_phase") == "",
                       "D5 恢复后详情脸 paused=False/paused_phase=''（按钮回 Pause；实得 "
                       "%r/%r）" % (detail.get("paused"), detail.get("paused_phase")))
        row = list_row(py, stage, tid)
        if row is not None:
            fail.check(row.get("paused") is False,
                       "D5 恢复后列表行 paused=False（实得 %r）" % (row.get("paused"),))
    finally:
        for proc in workers:
            P.stop_worker(fail, proc, "收尾")
        if stage_mod is not None and stage is not None:
            try:
                stage_down(stage_mod, stage)
            except Exception:
                pass
        if P.G.get("tmp") and (not fail.fails or os.environ.get("SANDBAR_DPF_KEEP_TMP")):
            cleanup(P.G["tmp"])       # 全绿（或显式保留）才清场
        else:
            # 红现场必留（worker 日志/审计账本——首因定位靠它，绝不 rmtree 毁证）
            print("[diag] 红现场保留于 %s（SANDBAR_DPF_KEEP_TMP 可显式保留）" % P.G.get("tmp"),
                  flush=True)
    fail.finish()


if __name__ == "__main__":
    main()
