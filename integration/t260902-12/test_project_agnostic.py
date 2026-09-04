#!/usr/bin/env python3
"""t260902-12 集成测试 C：项目无关硬约束 + 声明制在位检测（宿主令 t260902 重锚）。

覆盖：①硬约束——yml 全文与 FLOW_BRIEF 零项目专属路径（抽象落点=「项目声明的实际路径」）；
②声明制在位——verify.yaml 零 manifest 残留、integration.cmd 指向场景执行器、死清单未复活；
③登记制——spec 守卫家族在 SCENARIOS 清单在册、intent 均非空。
（旧「dev_lane integration/ 行数=基线」计数锁已退役：两次宿主令实测证明脆——
真正不变量是零项目路径，①已覆盖；行数随合法条款增减是常态不是漂移。）
失败 => 非零退出。cwd 不限，路径按脚本定位。
"""
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
YML = ROOT / "server" / "dsh" / "roles" / "integration.yml"
LANE = ROOT / "server" / "dsh" / "temporal-poc" / "dev_lane.py"
VY = ROOT / "verify.yaml"
RUNNER = ROOT / "integration" / "run_scenarios.py"
DEAD_MANIFEST = ROOT / "integration" / "manifest.json"

failures = []


def check(name, ok, detail=""):
    print(f"[t260902-12][agnostic] CHECK {name}: {'PASS' if ok else 'FAIL'}{('（' + detail + '）') if detail else ''}")
    if not ok:
        failures.append(name)


yml_text = YML.read_text(encoding="utf-8")
lane_text = LANE.read_text(encoding="utf-8")
vy_text = VY.read_text(encoding="utf-8")

# ① 硬约束：项目专属路径零命中（真正的项目无关不变量）
check("yml 全文零项目专属路径", not re.search(r"notes/|known-issues|baselines|\.worktrees/", yml_text))
check("dev_lane 零 notes/known-issues/baselines",
      not re.search(r"notes/|known-issues|baselines|\.worktrees/", lane_text))

# ② 声明制在位（manifest 退役后重锚）
check("verify.yaml 零 manifest 残留", "manifest" not in vy_text)
check("integration.cmd 指向场景执行器", "integration/run_scenarios.py" in vy_text)
check("死清单未复活（integration/manifest.json 不存在）", not DEAD_MANIFEST.exists())

# ③ 登记制：spec 守卫家族在册 + intent 均非空
spec = importlib.util.spec_from_file_location("rs", RUNNER)
rs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rs)
names = [e[0] for e in rs.SCENARIOS]
check("本票 spec 守卫家族已登记清单", "scenario-guard-spec-landed" in names)
check("登记条目 intent 均非空", all(str(e[1]).strip() for e in rs.SCENARIOS))

print(f"[t260902-12][agnostic] RESULT: {'PASS' if not failures else 'FAIL'}（失败 {len(failures)} 项）")
sys.exit(0 if not failures else 1)
