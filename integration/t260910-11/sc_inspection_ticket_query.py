#!/usr/bin/env python3
"""t260910-11 场景④：巡检票只读查询面（灰盒 L2/L3，隔离台真票）。

依据三支：①工单⑤「巡检票无 ticket snapshot 查询面→工单台与 CLI ticket-query 均
查不到（报 transient 超时），只能翻磁盘报告；补只读查询面（与工单详情同构：阶段/
状态/发现清单摘要）或明确降级口径」+ 260910 实证（唯一出口=翻磁盘）。②KI 回归
纪律：本条即「巡检票无查询面」事故的回归用例——用户可感知契约=运维通道 CLI 能按
实例+期次查到票，回执与工单详情同构（stage/stage_state/status/face/timeline，
flow snapshot 查询的公开形状），findings 只出摘要防刷屏。③查不到的失败必须精确
点名票号（报错精确纪律），不许笼统「连不上/transient」把诊断引向网络方向——
KI-029 同族的反面教训（查无此票≠连不上）。

安全自证：本场景一切 spawn 显式钉隔离台 17233（命名空间=TEST_NAMESPACE 存量台名；
import 后立刻钉 ambient），
绝不向生产台开票。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
登记 exclusive：自供给 worker+真票写隔离台，防并行场景互染。
"""
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "t260905-03"))
import lib_inspection as lib  # noqa: E402

TEST_HOST = "127.0.0.1:17233"

FIXTURE_DECL = """schema: v1
instances:
  - id: integration-tests-%05d
    enabled: true
    project_key: sandbar
    schedule:
      kind: cron
      cron: 0 6 * * 1
    workflow: InspectionPeriodicWorkflow
    template: inspection-lite
"""

QUERY_REQUIRED_KEYS = ("id", "stage", "stage_state", "status", "face")


def main() -> int:
    failures = []
    notes = []

    # 场景安全线：一切 spawn 钉隔离台
    os.environ["SANDBAR_TARGET_HOST"] = TEST_HOST
    os.environ["SANDBAR_NAMESPACE"] = lib.TEST_NAMESPACE  # naming-compat：存量测试台命名空间

    # 隔离台探活：缺=ENV_FAIL（本条无离线腿，整条环境红不假绿）
    proc, parsed = lib.run_client("schedule-list", {})
    if not (isinstance(parsed, dict) and parsed.get("ok") is True):
        lib.die_env("查询腿不可验：docker 测试台 %s 不可达或 temporalio 缺席"
                    "（schedule-list 未 ok，sh server/docker-compose.test.yml up -d）"
                    % TEST_HOST)

    workdir = os.path.join(lib.TP_DIR, "out", "t260910-11-query-%05d" % os.getpid())
    os.makedirs(workdir, exist_ok=True)
    decl_path = os.path.join(workdir, "query.yaml")
    with open(decl_path, "w", encoding="utf-8") as f:
        f.write(FIXTURE_DECL % os.getpid())
    instance = "integration-tests-%05d" % os.getpid()
    period = time.strftime("%Y%m%d")
    ticket_id = ""

    try:
        # 私有队列经 ambient 传给 trigger 子进程（spawn_env 单点放行队列键；目标/namespace
        # 仍由 lib 白名单钉死隔离台）——缺此行 trigger 落默认队列，隔离台无 worker 领活，
        # 票永远没有首个 workflow task，快照查询恒 NotFound（假「查不到」）
        os.environ["SANDBAR_TASK_QUEUE"] = "suyou-insp-query-%05d" % os.getpid()
        with lib.StageWorker("suyou-insp-query-%05d" % os.getpid()):
            # 开票（人门前=workflow 活着，查询面有对象）
            proc, parsed = lib.run_trigger(["trigger", "--instance", instance,
                                            "--period", period,
                                            "--decl-path", decl_path])
            if not (isinstance(parsed, dict) and parsed.get("ok") is True):
                failures.append("腿a 隔离台开票未放行（查询面前置）：%r | stderr=%s"
                                % ((parsed or (proc.stdout or "")[:200]),
                                   (proc.stderr or "")[:200]))
            else:
                opened = True
                ticket_id = str(((parsed.get("result") or {}).get("ticket_id")) or "")
                # ── 腿b：ticket 子命令可查、形状与工单详情同构（短轮询：快照查询
                # 早于 workflow 首个事件时 NotFound 属正常可见性延迟，非产品缺陷）──
                parsed = None
                for _ in range(8):
                    proc, parsed = lib.run_trigger(["ticket", "--instance", instance,
                                                    "--period", period])
                    if isinstance(parsed, dict) and parsed.get("ok") is True:
                        break
                    time.sleep(1)
                if not isinstance(parsed, dict):
                    failures.append("腿b ticket 回执非单行 JSON（子命令缺席或回执形状破）：%r | "
                                    "stderr=%s" % ((proc.stdout or "")[:200], (proc.stderr or "")[:200]))
                elif parsed.get("ok") is not True:
                    failures.append("腿b 查询存活票失败：%r" % parsed)
                else:
                    result = parsed.get("result") or {}
                    missing = [k for k in QUERY_REQUIRED_KEYS if k not in result]
                    if missing:
                        failures.append("腿b 回执缺工单详情同构键 %s（契约面 "
                                        "stage/stage_state/status/face/timeline）：%r"
                                        % (missing, sorted(result.keys())))
                    face = result.get("face")
                    if not isinstance(face, dict):
                        failures.append("腿b face 键非 dict（发现清单摘要面缺席）：%r"
                                        % (face,))
                notes.append("腿b 查询回执键=%s" % sorted(((parsed.get("result") or {}) if parsed else {}).keys()))

            # ── 腿c：查不存在→精确点名，不许笼统网络话术 ──
            ghost = "integration-tests-99999"
            proc, parsed = lib.run_trigger(["ticket", "--instance", ghost,
                                            "--period", period])
            if not isinstance(parsed, dict):
                failures.append("腿c 查不存在回执非单行 JSON：%r" % (proc.stdout or "")[:160])
            elif parsed.get("ok") is not False:
                failures.append("腿c 查不存在竟放行：%r" % parsed)
            else:
                err = str(parsed.get("error") or "")
                if ghost not in err and instance not in err:
                    failures.append("腿c 查不到的报错未点名实例/票号（笼统网络话术会把诊断"
                                    "引向错误方向）：%r" % err[:240])
    finally:
        import shutil
        # 场景卫生：pre-implement 状态下票无人收口，best-effort cancel 自己开的票，
        # 不在隔离台留僵尸（判定在此之前已完成；已收口则本调用报错即忽略）
        if ticket_id:
            try:
                lib.run_client("cancel", {"workflow_id": ticket_id})
            except Exception:
                pass
        shutil.rmtree(workdir, ignore_errors=True)

    if failures:
        for m in failures:
            print("FAIL_REASON: " + m, flush=True)
        return 1
    print("PASS: " + "; ".join(notes), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
