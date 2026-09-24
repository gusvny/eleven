#!/usr/bin/env python3
"""闸段分相计时·回执拼装与老回执兼容契约（t260925-12，registry: t260925-12-stage-record-timings）。

意图（灰盒 L2，ro 池，真引擎模块导入，离线秒级零 docker）：
工单验收④的引擎侧半边：activity 回执自报耗时（Temporal workflow 确定性纪律
禁 workflow 取时钟），dev_lane 段尾拼 `gate_phase_timings`（含 residual
`unattributed_s`，review_plan 条件②定的 owner）上 stage record。本场景守
公开回执/记录契约的三条用户可感知行为：

- A 老回执零破坏：`IntegrationRunResult` / `ConflictPrepResult` 不因新增计时
  字段出现必填参——老事件回放/老 dict 重建点（t260922-18 补键先例的兼容面）
  不抛、不假造 0 归因；
- B residual 归账：拼装入口吃全套相位回执 → 各相位在案且
  `unattributed_s = 段墙钟 − Σ相位`（负值钳 0 并点名），invariant 保持；
- C 畸形回执不炸闸：缺 timings 的老回执 → 相位不假造、unattributed==全墙钟；
  负数/非数值/NaN/未知键 → 不抛、不把垃圾计入归因（或响亮哨兵值），绝不让
  gate entry 因计时数据畸形而翻红。

intent 分工（核对过 SCENARIOS 全清单）：执行器回执面归
t260925-12-executor-timings-receipt，developer L1 守纯函数真值矩阵——本条守
引擎模块「老回执兼容 × residual 归账 × 畸形不炸」组件契约链，不互替。
实现落地前 B/C 的拼装入口缺席=产品红点名缺契约（TDD 信号）。引擎模块不可
导入=ENV_FAIL exit 2。
"""
import inspect
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from lib_env import env_fail  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "server" / "engine"))

try:
    import shared  # noqa: E402
    import dev_lane  # noqa: E402
except Exception as e:  # ImportError 及导入期副作用异常一律环境红
    env_fail("引擎模块不可导入：%r" % (e,))

cases = []


def _required_params(cls):
    sig = inspect.signature(cls.__init__)
    out = []
    for name, p in list(sig.parameters.items())[1:]:
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        if p.default is inspect.Parameter.empty:
            out.append(name)
    return out


# ---- A 老回执零破坏：新计时字段不得是必填参（老回放形态可空手重建） ----
for cls in (shared.IntegrationRunResult, shared.ConflictPrepResult):
    req = _required_params(cls)
    bad = [n for n in req if "wall" in n or "timing" in n or "_s" in n]
    cases.append(("A1 %s 无计时类必填参（老回执零破坏，冲突=%s）"
                  % (cls.__name__, bad or "无"), not bad))

# ---- 定位拼装入口（公开契约=stage record 键 gate_phase_timings/__gate_timings__）----
builder = None
for mod in (dev_lane, shared):
    for nm in dir(mod):
        if "gate_phase_timing" in nm or "gate_timing" in nm:
            obj = getattr(mod, nm)
            if callable(obj):
                builder = obj
                break
    if builder is not None:
        break

cases.append(("B0 拼装入口在案（缺席=实现未接线，TDD 红）", builder is not None))


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) \
        and math.isfinite(v) and v >= 0


if builder is not None:
    WALL = 600.0
    full = {"pre_check_s": 1.0, "main_sync_s": 10.0, "changed_files_s": 2.0,
            "suite_s": 500.0, "handover_s": 7.0}
    # B1 全套回执：相位在案 + residual = 墙钟 − Σ相位
    try:
        g = builder(dict(full), WALL)
        phases = {k: v for k, v in g.items()
                  if k != "unattributed_s" and _num(v)}
        un = g.get("unattributed_s")
        cases.append(("B1 全套回执→相位在案且 residual 归账正确",
                      len(phases) == len(full)
                      and _num(un)
                      and abs(un - (WALL - sum(phases.values()))) < 0.05))
    except Exception as e:
        cases.append(("B1 全套回执→相位在案且 residual 归账正确（抛 %r）" % (e,), False))
    # C1 老 receipt 无 timings：不假造相位、unattributed==全墙钟
    try:
        g = builder({}, WALL)
        fake = [k for k, v in g.items()
                if k != "unattributed_s" and isinstance(v, (int, float))
                and not isinstance(v, bool) and v == 0]
        cases.append(("C1 老回执→不假造 0 相位、unattributed==全墙钟",
                      not fake and g.get("unattributed_s") == WALL))
    except Exception as e:
        cases.append(("C1 老回执→不假造 0 相位（抛 %r）" % (e,), False))
    # C2 畸形值（负数/字符串/NaN/None）不炸、垃圾不入归因
    malformed = {"suite_s": -5.0, "main_sync_s": "12s", "handover_s": float("nan"),
                 "changed_files_s": None, "ghost_phase_s": 3.0}
    try:
        g = builder(dict(malformed), WALL)
        bad_attr = [k for k, v in g.items()
                    if k != "unattributed_s" and isinstance(v, (int, float))
                    and not isinstance(v, bool) and (not math.isfinite(v) or v < 0)]
        un = g.get("unattributed_s")
        honest = (un is None) or (_num(un) and un <= WALL * 1.05)
        cases.append(("C2 畸形回执不炸闸、垃圾不入归因（坏相=%s）" % (bad_attr,),
                      not bad_attr and honest))
    except Exception as e:
        cases.append(("C2 畸形回执不炸闸（抛 %r=允许响亮哨兵语义，判红待定）" % (e,), False))
    # C3 未知键不计入归因（ghost 相位不进 Σ）
    try:
        g = builder({"suite_s": 100.0, "ghost_phase_s": 999.0}, WALL)
        un = g.get("unattributed_s")
        cases.append(("C3 未知键不进 Σ（residual 按 500−100 口径）",
                      _num(un) and abs(un - (WALL - 100.0)) < 0.05))
    except Exception as e:
        cases.append(("C3 未知键不进 Σ（抛 %r）" % (e,), False))

failed = [(n, ok) for n, ok in cases if not ok]
for n, ok in cases:
    print("%s %s" % ("PASS" if ok else "FAIL", n))
print("SUMMARY pass=%d fail=%d env_fail=0 na=0"
      % (len(cases) - len(failed), len(failed)))
sys.exit(1 if failed else 0)
