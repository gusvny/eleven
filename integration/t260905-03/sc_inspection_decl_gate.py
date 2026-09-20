#!/usr/bin/env python3
"""t260905-03 场景③：声明门——触发面尊重 inspection.yaml（验收③行为级证据）。

依据三支：①工单验收③「声明文件驱动（改声明改行为，不改引擎码）」——M1 裁定验收③
只认行为级：enabled=false 的实例触发面不跑，disabled/unknown/unwired 的触发请求被
精确拒绝；②方案 fail-closed 口径（M2）：启用实例声明未接线 kind=显式报错并点名已接线
kind 清单，不许解析通过后运行时静默不触发；③报错精确纪律：声明错报成「连不上」=把
诊断引向错误方向（KI-051「环境红捂真红」同族的反向教训）——交付触发面的校验先于任何
网络动作，拒绝理由点名 decl/kind/instance 本身。

三态分级：拒绝子用例（畸形声明/未接线 kind/占位实例/未知实例）走交付触发面的离线校验
（--decl-path，纯标准库、零网络零依赖）——闸内即可验；放行子用例（enabled 实例真触发+
同期一票）需要 temporalio+共享台，缺供=ENV_FAIL exit 2 点名（拒绝子用例已验部分如实
陈述，不假红不假绿）。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
与 developer L1（decl 纯函数解析真值表）不同层：本条黑盒锁触发面的门行为；与场景④
不同面：④守全链旅程质量，本条守「谁能跑、谁被拒、同期只一票」。声明方言按交付
（schema v1，cron 裸值五字段；--decl-path 注入隔离声明）。
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib_inspection as lib

NORMAL_DECL = """schema: v1
instances:
  - id: integration-tests
    enabled: true
    project_key: sandbar
    schedule:
      kind: cron
      cron: 0 6 * * 1
    workflow: InspectionPeriodicWorkflow
    template: inspection-lite
  - id: docs-sync
    enabled: false
    project_key: sandbar
    schedule:
      kind: cron
      cron: 0 7 * * 1
    workflow: InspectionPeriodicWorkflow
    template: inspection-lite
"""

# t260911-02 更新：every-n-tickets/race-first 已接线，「未接线 kind」负例迁移到
# 「启用计数 kind 缺 source」（仍 fail-closed 点名；未接线词表面由缺失字段报错承担）
UNWIRED_DECL = """schema: v1
instances:
  - id: integration-tests
    enabled: true
    schedule:
      kind: every-n-tickets
      n: 20
    workflow: InspectionPeriodicWorkflow
    template: inspection-lite
"""

MALFORMED_DECL = "instances: [ {id: broken"


def stage_up() -> bool:
    """共享供给台探活（只读 schedule-list）：连不上=False。缺 temporalio 亦 False 由调用方分路。"""
    try:
        _proc, parsed = lib.run_client("schedule-list", {})
    except Exception:
        return False
    return bool(isinstance(parsed, dict) and parsed.get("ok") is True)


def main() -> int:
    lib.require_entry(lib.TRIGGER, "巡检触发入口")

    failures = []
    workdir = tempfile.mkdtemp(prefix="sandbar-insp-decl-")
    normal = os.path.join(workdir, "normal.yaml")
    unwired = os.path.join(workdir, "unwired.yaml")
    malformed = os.path.join(workdir, "malformed.yaml")
    with open(normal, "w", encoding="utf-8") as f:
        f.write(NORMAL_DECL)
    with open(unwired, "w", encoding="utf-8") as f:
        f.write(UNWIRED_DECL)
    with open(malformed, "w", encoding="utf-8") as f:
        f.write(MALFORMED_DECL)

    def expect_refuse(tag, decl_path, instance, must_mention):
        proc, parsed = lib.run_trigger(["trigger", "--instance", instance,
                                        "--decl-path", decl_path])
        if not isinstance(parsed, dict):
            failures.append("%s 触发面回执非单行 JSON：%r | stderr=%s"
                            % (tag, (proc.stdout or "")[:160], (proc.stderr or "")[:160]))
            return False
        if parsed.get("ok") is not False:
            failures.append("%s 应拒绝却放行：%r" % (tag, parsed))
            return False
        err = str(parsed.get("error") or "")
        for token in must_mention:
            if token not in err:
                failures.append("%s 拒绝理由未点名 %r（报错必须精确）：%r"
                                % (tag, token, err[:240]))
                return False
        return True

    try:
        # ── 离线拒绝子用例（纯标准库可验，闸内即跑）──
        # 子用例a：畸形声明——拒绝且理由指向声明本身，不指向连接/命名空间
        ok_a = expect_refuse("子用例a(畸形声明)", malformed, "integration-tests", ["声明"])
        # 子用例b（t260911-02 更新）：启用计数 kind 缺 source——拒绝并点名 source 与已接线
        # 计数源清单（fail-closed 语义不随接线扩大而松动；未接线 kind 词表负例已随
        # 三 kind 全接线迁移至源词表）
        ok_b = expect_refuse("子用例b(计数缺source)", unwired, "integration-tests", ["source", "archive-dir"])
        # 子用例c：enabled=false 实例——拒绝并点名实例（声明门行为级核心）
        ok_c = expect_refuse("子用例c(占位实例)", normal, "docs-sync", ["docs-sync"])
        # 子用例d：未知实例——拒绝并点名实例
        ok_d = expect_refuse("子用例d(未知实例)", normal, "nope", ["nope"])

        refusal_ok = ok_a and ok_b and ok_c and ok_d
        if failures:
            for m in failures:
                print("FAIL_REASON: " + m, flush=True)
            return 1
        print("离线拒绝子用例 4/4 通过（畸形声明/计数缺source/占位实例/未知实例）", flush=True)

        # ── 放行子用例（server 子用例）：缺 temporalio/共享台=ENV_FAIL，拒绝子用例已验部分如实陈述 ──
        # （主进程零 temporalio 依赖：client/trigger 子进程自选 venv python；探活失败
        #  统一归因「依赖或台缺席」，不猜不谎报）
        if not stage_up():
            lib.die_env("放行子用例不可验：temporalio 缺席或共享测试台不可达（schedule-list 未 ok）"
                        "——拒绝子用例四类已全过；放行子用例需 temporalio+共享台，不假红不假绿")

        # 私有队列+自供给 worker（与 journey 同理由，arbitrate 实证）：本票 workflow
        # 未合并前生产 worker 不认识它（抢活即打回 not-registered），私有队列消除竞态、
        # 也不给共享台留毒票；trigger 子进程经 os.environ 继承同一队列。
        private_queue = "suyou-insp-decl-%05d" % os.getpid()
        os.environ["SANDBAR_TASK_QUEUE"] = private_queue
        with lib.StageWorker(private_queue):
            proc, parsed = lib.run_trigger(["trigger", "--instance", "integration-tests",
                                            "--decl-path", normal])
            if not isinstance(parsed, dict) or parsed.get("ok") is not True:
                failures.append("子用例e enabled 实例触发未放行：%r | stderr=%s"
                                % (parsed, (proc.stderr or "")[:200]))
            else:
                result = parsed.get("result") or {}
                tid = str(result.get("ticket_id") or "")
                if not tid:
                    failures.append("子用例e 放行回执未带 ticket_id（场景侧裁定 result.ticket_id）：%r"
                                    % (result,))
                else:
                    # 子用例f：同期重复触发——每期一票：回执仍指同一张票，不得开出第二张
                    proc2, parsed2 = lib.run_trigger(["trigger", "--instance", "integration-tests",
                                                      "--decl-path", normal])
                    r2 = (parsed2 or {}).get("result") or {}
                    tid2 = str(r2.get("ticket_id") or "")
                    merged = tid2 == tid or bool(r2.get("deduped")) or bool(r2.get("merged"))
                    if not ((parsed2 or {}).get("ok") is True and merged):
                        failures.append("子用例f 同期重复触发开出新票（每期一票破）：首=%r 次=%r"
                                        % (tid, parsed2))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    if failures:
        for m in failures:
            print("FAIL_REASON: " + m, flush=True)
        return 1
    print("PASS: 畸形声明/计数缺source/占位实例/未知实例四类拒绝精确点名（离线）；"
          "enabled 实例放行带票号；同期重复触发仍一票（每期一票）", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
