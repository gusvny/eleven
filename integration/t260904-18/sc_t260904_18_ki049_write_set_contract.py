#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260904-18 场景②：files_changed 回执形状 × 写集刷新缝上契约 + 机制活性巡检
（门②，KI-049 修复面②③④，灰盒 L2）。

intent（守护的用户可感知行为/合同）：
- KI-049 加重记录的实践性死亡：refresh_write_set 依赖 create_plan 回执 files_changed，
  生产 agent 两代方案都交空数组 → 并集静默 no-op → 越界红 → 整链重跑。本条以
  **真实 agent 回执形状**喂解析→刷新链，断言缝契约（mock 恰当填字段掩盖过的缝）：
  · 字符串回执（「叙述里写了补列、字段没填」的姊妹形态）不得在解析层毁形成单字符
    列表——毁形强转退役后，畸形在解析层被拒形（shape=malformed）；
  · 畸形（字符串/数字/含非串元素/缺字段）与空数组在消费点=可见红
    （meta.write_set_refresh_fault）+ 告警日志 + **不调 refresh（写集零污染）**，
    且不得再出「写集已随方案定稿刷新」中性行冒充刷新成功（报错必须精确）；
  · None（旧票无字段）维持跳过语义（selfcheck_write_lifecycle 在场锁共存）；
  · no_file_changes 在案票豁免（声明在案≠漏填）；
- 机制活性巡检（dead-man's switch，KI-049 修复面④）：合法非空回执 → 「授权扩展」
  日志非零——「授权扩展」日志全史 0 条的机制死亡形态从此有断言网；
- 解析点三处（agent_activities/_read_result、base.py、dev_lane.py）毁形强转退役=
  源码负锁；StageResult 形状字段贯通 results dict（消费点读形）。

与 developer L1（engine/tests 纯函数白盒）不同层：本条驱动真实解析函数与
真实消费点方法（monkeypatch temporalio 上下文门），L1 不覆盖缝契约。
实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；
temporalio 缺失=ENV_FAIL 点名（解析/消费点行为腿），stdlib 链腿与源码锁照跑。
"""
import json
import shutil
import sys
import tempfile
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib_t260904_18 import (  # noqa: E402
    REPO, POC, check, summary, env_fail, temporalio_available,
)

sys.path.insert(0, str(POC))
import shared  # noqa: E402  纯标准库依赖面

DL_SRC = (POC / "dev_lane.py").read_text(encoding="utf-8")
BASE_SRC = (POC / "base.py").read_text(encoding="utf-8")
AA_SRC = (POC / "agent_activities.py").read_text(encoding="utf-8")

# ---------- 源码契约锁（处处可跑；t260904-13 t05 同族落地形态） ----------
COERCE = '[str(x) for x in (raw.get("files_changed") or [])]'
check("R1 消费点读形（dev_lane 引用 files_changed_shape——形状贯通 results dict）",
      "files_changed_shape" in DL_SRC)
check("R2 base.py 解析点读形（files_changed_shape 贯通）", "files_changed_shape" in BASE_SRC)
check("R3 可见红注记字段（meta write_set_refresh_fault 在场）",
      "write_set_refresh_fault" in DL_SRC)
check("R4 放行路径调用位保持（self._refresh_write_set_after_plan()）",
      "self._refresh_write_set_after_plan()" in DL_SRC)
check("R5 解析点毁形强转退役（agent_activities）", COERCE not in AA_SRC)
check("R6 解析点毁形强转退役（base.py）", COERCE not in BASE_SRC)
check("R7 解析点毁形强转退役（dev_lane.py）", COERCE not in DL_SRC)

# ---------- 解析层 normalize（stdlib 行为腿；真实回执 JSON 值直喂） ----------
norm = getattr(shared, "normalize_files_changed", None)
check("N0 被测承诺面在场（shared.normalize_files_changed）", norm is not None)
if norm is not None:
    cases = [
        ("字符串回执（单字符毁形源形态）", "server/a.py", ([], "malformed")),
        ("数字回执", 42, ([], "malformed")),
        ("含非字符串元素", ["a.py", 7], ([], "malformed")),
        ("缺字段/None（旧票）", None, ([], "absent")),
        ("合法数组", ["a.py", "b.py"], (["a.py", "b.py"], "ok")),
        ("空数组（合法形状的空）", [], ([], "ok")),
    ]
    for label, raw, expect in cases:
        try:
            got = norm(raw)
            check("N %s" % label, tuple(got) == expect if isinstance(got, tuple) else got == expect,
                  "got=%r expect=%r" % (got, expect))
        except Exception as e:
            check("N %s" % label, False, "%s: %s" % (type(e).__name__, e))
    # 零污染链腿（stdlib 可跑）：畸形形状根本不该产出可并集条目——
    # normalize 输出空清单 ⇒ 即便误调 refresh_write_set 也并不进任何路径
    for label, raw in [("字符串", "server/a.py"), ("数字", 42), ("含非串元素", ["a.py", None])]:
        try:
            files, shape = norm(raw)
            merged, added = shared.refresh_write_set(["init/x.py"], list(files))[:2]
            check("C 零污染链：%s 形状回执不向写集注入任何条目" % label,
                  shape == "malformed" and merged == ["init/x.py"] and added == [],
                  "files=%r shape=%r merged=%r" % (files, shape, merged))
        except Exception as e:
            check("C 零污染链：%s" % label, False, "%s: %s" % (type(e).__name__, e))

# ---------- 行为腿（temporalio 面）：真解析函数 + 真消费点方法 ----------
if not temporalio_available():
    env_fail("temporalio 不可用（本泳道无 venv）：_read_result 解析缝与消费点四分支行为腿"
             "不可执行——stdlib normalize/零污染链腿与源码锁已在本场跑完；"
             "arbitrate/merge 期 venv 环境必须全绿")
else:
    import dev_lane          # noqa: E402
    import agent_activities  # noqa: E402

    # —— 解析缝：真实 _read_result 吃真实结果文件 JSON ——
    def read_result_of(raw_obj):
        d = Path(tempfile.mkdtemp(prefix="t260904-18-res-"))
        try:
            f = d / "result.json"
            f.write_text(json.dumps(raw_obj, ensure_ascii=False), encoding="utf-8")
            return agent_activities._read_result(f)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    r = read_result_of({"status": "ok", "files_changed": "server/a.py"})
    check("J1 真解析缝：字符串回执不变单字符列表（毁形死刑）",
          r is not None and r.files_changed == [], "files_changed=%r" % (getattr(r, "files_changed", None),))
    check("J2 真解析缝：字符串回执 shape=malformed",
          r is not None and getattr(r, "files_changed_shape", "") == "malformed")
    r = read_result_of({"status": "ok", "files_changed": ["server/a.py"]})
    check("J3 真解析缝：合法数组保真+shape=ok",
          r is not None and r.files_changed == ["server/a.py"]
          and getattr(r, "files_changed_shape", "") == "ok")
    r = read_result_of({"status": "ok"})
    check("J4 真解析缝：缺字段 shape=absent（旧票回放兼容）",
          r is not None and r.files_changed == []
          and getattr(r, "files_changed_shape", "") == "absent")

    # —— 消费点四分支：真方法 + 真 refresh_write_set（monkeypatch 上下文门） ——
    class FakeLane:
        """最小 workflow self：meta/results 真字典、_log 真收集——断言全落可观察状态。
        _now_epoch 桩：dev_lane 零 wall-clock 纪律下引擎方法走 workflow.now()，
        本桩脱离 Temporal 运行时，给固定值（可见红 flag 的 ts 字段消费）。"""

        def __init__(self, receipt, no_file_changes=False):
            self.meta = {"write_set": ["init/x.py"], "no_file_changes": no_file_changes}
            self.results = {"create_plan": receipt}
            self.logs = []

        def _now_epoch(self):
            return 0

        def _log(self, note, status=None):
            self.logs.append(str(note))

    fake_wf = types.SimpleNamespace(patched=lambda _pid: True)
    real_wf = dev_lane.workflow
    dev_lane.workflow = fake_wf
    try:

        def run_receipt(receipt, no_file_changes=False):
            fake = FakeLane(receipt, no_file_changes)
            dev_lane.DevLaneWorkflow._refresh_write_set_after_plan(fake)
            return fake

        # 活性巡检（dead-man's switch，KI-049 修复面④）：「授权扩展」日志非零
        fake = run_receipt({"files_changed": ["feat/a.py"], "files_changed_shape": "ok"})
        extended = [ln for ln in fake.logs if ln.startswith("授权扩展：")]
        check("B1 活性巡检（dead-man）：合法非空回执 → 「授权扩展」日志非零",
              len(extended) >= 1, "logs=%r" % fake.logs)
        check("B2 合法回执 → 写集真并集（init 保留+新增在列）",
              fake.meta.get("write_set") == ["init/x.py", "feat/a.py"],
              "write_set=%r" % (fake.meta.get("write_set"),))
        check("B3 合法回执 → 不误挂可见红 flag",
              not fake.meta.get("write_set_refresh_fault"))

        fake = run_receipt({"files_changed": [], "files_changed_shape": "ok"})
        check("B4 空数组回执 → 可见红 flag（工单台可读字段）",
              bool(fake.meta.get("write_set_refresh_fault")), "meta=%r" % fake.meta)
        check("B5 空数组回执 → 写集零污染", fake.meta.get("write_set") == ["init/x.py"])
        check("B6 空数组回执 → 不再出「写集已随方案定稿刷新」中性行冒充成功",
              not any("写集已随方案定稿刷新" in ln for ln in fake.logs), "logs=%r" % fake.logs)
        check("B7 空数组回执 → 告警日志点名空数组",
              any("空数组" in ln or "空" in ln for ln in fake.logs), "logs=%r" % fake.logs)

        fake = run_receipt({"files_changed": [], "files_changed_shape": "malformed"})
        check("B8 畸形回执 → 可见红 flag + 写集零污染",
              bool(fake.meta.get("write_set_refresh_fault"))
              and fake.meta.get("write_set") == ["init/x.py"], "meta=%r" % fake.meta)
        check("B9 畸形回执 → 不出中性行冒充成功",
              not any("写集已随方案定稿刷新" in ln for ln in fake.logs), "logs=%r" % fake.logs)

        fake = run_receipt({"files_changed_shape": "absent"})
        check("B10 缺字段（旧票）→ 跳过语义留痕、零 flag",
              any("写集刷新跳过" in ln for ln in fake.logs)
              and not fake.meta.get("write_set_refresh_fault"), "logs=%r" % fake.logs)

        fake = run_receipt({"files_changed": [], "files_changed_shape": "ok"},
                           no_file_changes=True)
        check("B11 no_file_changes 在案豁免（声明在案≠漏填）→ 零 flag",
              not fake.meta.get("write_set_refresh_fault"), "logs=%r" % fake.logs)
    finally:
        dev_lane.workflow = real_wf

sys.exit(summary())
