#!/usr/bin/env python3
"""t260910-09 场景②：新巡检实例声明门——mechanism-face/simplify-face 的声明位与门数据面
（灰盒 L2，离线可验）。

依据：①工单规格「inspection.yaml 声明新实例（face=mechanism/simplify，enabled 按宿主
节奏）」+场景必含「零发现时心跳票语义不变」的声明半边——enabled=false 占位=不进调度
规格（不调度不触发）；②方案 D6/D7 承诺：decl 零改动（face 自由标量）、新实例走既有
build_schedule_specs 门；③声明是机器消费的契约（引擎解析器逐期读取），故对仓内
inspection.yaml 的实例位做契约守卫合法（非快照型文档 pin）。

全部离线腿（trigger decl 子命令=离线声明视图，纯标准库零网络）闸内即验；唯一 server
腿（enabled 新实例过门真触发）缺 temporalio/共享台=ENV_FAIL 点名不假红（沿票①
decl-gate 三态分级先例）。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
intent 分工：与 t260905-03-decl-gate 不同面——彼守门行为本身（畸形/未接线 kind/占位/
未知四类拒绝+test-face 放行，新实例同门不重测，防 intent 级重复）；本条守**新实例的
声明位在场**（仓内 yaml 两占位 enabled=false）与**新面经门透传的数据面**（enabled 新
实例进 specs 且 face 原样透传）。与 developer L1（decl 纯函数真值表）不同层。
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib_inspection_ms as lib  # noqa: E402 — 先入本票 lib（其内部补 t260905-03 路径）
import lib_inspection as base  # noqa: E402

REPO_DECL = os.path.join(base.TP_DIR, "inspection.yaml")

NEW_FACES = (("mechanism-face", "mechanism"), ("simplify-face", "simplify"))

FIXTURE_DECL = """schema: v1
instances:
  - id: test-face
    face: test
    enabled: true
    schedule:
      kind: cron
      cron: 0 6 * * 1
    workflow: InspectionPeriodicWorkflow
    template: inspection-lite
  - id: mechanism-face
    face: mechanism
    enabled: true
    schedule:
      kind: cron
      cron: 0 7 * * 1
    workflow: InspectionPeriodicWorkflow
    template: inspection-lite
  - id: simplify-face
    face: simplify
    enabled: false
    schedule:
      kind: cron
      cron: 0 8 * * 1
    workflow: InspectionPeriodicWorkflow
    template: inspection-lite
"""


def decl_view(decl_path):
    return base.run_trigger(["decl", "--decl-path", decl_path])


def spec_ids(parsed):
    """decl 回执里的 (id, face, in_specs) 三元组集；形状异常返回 None。"""
    res = (parsed or {}).get("result") or {}
    instances = res.get("instances")
    specs = res.get("schedule_specs")
    if not isinstance(instances, list) or not isinstance(specs, list):
        return None
    inst = {str(i.get("id")): i for i in instances if isinstance(i, dict)}
    spec = {str(s.get("instance_id")): s for s in specs if isinstance(s, dict)}
    return inst, spec


def main() -> int:
    base.require_entry(base.TRIGGER, "巡检触发入口")
    failures = []

    # ── 腿a：仓内 inspection.yaml 声明位契约——两新实例在场（face 对、enabled=false）、
    #     不进 schedule_specs（enabled=false 不调度=数据面，工单「enabled 按宿主节奏」
    #     的兑现面；声明是机器消费契约，守卫合法）──
    proc, parsed = decl_view(REPO_DECL)
    if not isinstance(parsed, dict) or parsed.get("ok") is not True:
        failures.append("腿a 仓内 decl 视图异常：%r | stderr=%s"
                        % (str(parsed)[:160], (proc.stderr or "")[:200]))
    else:
        got = spec_ids(parsed)
        if got is None:
            failures.append("腿a decl 回执缺 instances/schedule_specs 列表：%r"
                            % (str(parsed.get("result"))[:200],))
        else:
            inst, spec = got
            for iid, face in NEW_FACES:
                it = inst.get(iid)
                if it is None:
                    failures.append("腿a 仓内声明缺新实例 %s（工单声明位验收）：%r"
                                    % (iid, sorted(inst)))
                    continue
                if it.get("face") != face:
                    failures.append("腿a %s face 声明错（期 %r）：%r" % (iid, face, it.get("face")))
                if it.get("enabled") is not False:
                    failures.append("腿a %s 应 enabled=false 占位（启用按宿主节奏）：%r"
                                    % (iid, it.get("enabled")))
                if iid in spec:
                    failures.append("腿a 占位实例 %s 进了 schedule_specs（不调度承诺破）：%r"
                                    % (iid, sorted(spec)))

    # ── 腿b：夹具声明——enabled 新实例进 specs 且 face 原样透传；enabled=false 不进
    #     （门的数据面：改声明改行为，decl 零改动承诺）──
    workdir = tempfile.mkdtemp(prefix="sandbar-insp-ms-decl-")
    try:
        fixture = os.path.join(workdir, "fixture.yaml")
        with open(fixture, "w", encoding="utf-8") as f:
            f.write(FIXTURE_DECL)
        proc, parsed = decl_view(fixture)
        got = spec_ids(parsed) if isinstance(parsed, dict) and parsed.get("ok") is True else None
        if got is None:
            failures.append("腿b 夹具 decl 视图异常（解析应零改动支持新面标量）：%r | stderr=%s"
                            % (str(parsed)[:160], (proc.stderr or "")[:200]))
        else:
            inst, spec = got
            if "mechanism-face" not in spec:
                failures.append("腿b enabled mechanism-face 未进 schedule_specs（应调度）：%r"
                                % (sorted(spec),))
            elif spec["mechanism-face"].get("face") != "mechanism":
                failures.append("腿b specs 未透传 face=mechanism：%r" % (spec["mechanism-face"],))
            if "simplify-face" in spec:
                failures.append("腿b disabled simplify-face 进了 specs（不调度破）：%r"
                                % (sorted(spec),))
            if inst.get("simplify-face", {}).get("face") != "simplify":
                failures.append("腿b instances 未透传 face=simplify 标量：%r"
                                % (inst.get("simplify-face"),))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    if failures:
        for m in failures:
            print("FAIL_REASON: " + m, flush=True)
        return 1
    print("离线腿全过：仓内 yaml 两新实例占位 enabled=false 且不进调度规格；"
          "enabled 新实例进 specs 且 face 原样透传（decl 零改动）", flush=True)

    # ── 腿c（server 腿）：enabled mechanism-face 过声明门真触发——缺 temporalio/
    #     共享台=ENV_FAIL 点名（离线腿已过如实陈述，不假红不假绿）──
    def stage_up() -> bool:
        try:
            _proc, p = base.run_client("schedule-list", {})
        except Exception:
            return False
        return bool(isinstance(p, dict) and p.get("ok") is True)

    if not stage_up():
        base.die_env("腿c 不可验：temporalio 缺席或共享测试台不可达（schedule-list 未 ok）"
                     "——离线腿已全过；enabled 新实例放行腿需 temporalio+共享台，不假红不假绿")
    workdir = tempfile.mkdtemp(prefix="sandbar-insp-ms-decl2-")
    try:
        fixture = os.path.join(workdir, "fixture.yaml")
        with open(fixture, "w", encoding="utf-8") as f:
            f.write(FIXTURE_DECL)
        proc, parsed = base.run_trigger(["trigger", "--instance", "mechanism-face",
                                         "--decl-path", fixture])
        if not isinstance(parsed, dict):
            failures.append("腿c 触发回执非单行 JSON：%r | stderr=%s"
                            % ((proc.stdout or "")[:160], (proc.stderr or "")[:200]))
        elif parsed.get("ok") is not True:
            err = str(parsed.get("error") or "")
            if "声明" in err:
                failures.append("腿c enabled 新实例被声明门误拒（应放行，报错错向）：%r" % err[:240])
            else:
                failures.append("腿c enabled mechanism-face 触发放行失败（非声明门理由）：%r"
                                % err[:240])
        else:
            tid = str(((parsed.get("result") or {}).get("ticket_id")) or "")
            if not tid:
                failures.append("腿c 放行回执未带 ticket_id：%r" % (parsed.get("result"),))
            else:
                print("腿c 放行回执带票号 %s（新 face 过声明门）" % tid, flush=True)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    if failures:
        for m in failures:
            print("FAIL_REASON: " + m, flush=True)
        return 1
    print("PASS: 仓内 yaml 两新实例占位不调度；enabled 新实例进规格+face 透传+真触发过门",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
