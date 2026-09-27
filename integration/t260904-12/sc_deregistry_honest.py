#!/usr/bin/env python3
"""ticket-lifecycle 移册合规守卫（t260904-12 乙段，定稿「真跑不进闸」通道）。

intent：ticket-lifecycle 按定稿 §7.3「真跑不进闸」条款移出 SCENARIOS（乙段
gen4 方案 #6 裁定=分支-2），移册必须诚实缩围而非三种腐化中的任何一种——
  T1  套件无该条目（移册生效；ran 计数如实缩围，非旧词式「在册恒过」放行）；
  T2  README 移册登记在案：定稿条款引用 + 主库人工清单承接真实覆盖 +
      t260831-04 登记裁定的逆转依据（C-c：该条目历史上 t260831-03 不登记→
      t260831-04 翻回，本次再翻转须有据可查，防口径反复）；
  T3  场景文件仍在树内且非空（覆盖蒸发防线：移册≠删除，顶层人工跑通道保持）；
  T4  文件语义未被静默 neuter：嵌套护栏的 env_fail 语义仍在（设计性环境红
      标记不因移册被改成恒过）；
  T5  契约 v2.1 变更记录含移册依据（定稿条款引用）——追加型历史，pin 不 rot。
断言锚公开面（清单登记/文档记录/文件在场），不锚内部实现。零环境依赖、秒级。
"""
import importlib.util
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

pass_n = fail_n = 0


def ok(cond, label):
    global pass_n, fail_n
    if cond:
        pass_n += 1
        print("  ok " + label)
    else:
        fail_n += 1
        print("  FAIL " + label)


# ---- T1 套件无 ticket-lifecycle 系条目 ----
spec = importlib.util.spec_from_file_location("rs", REPO / "integration" / "run_scenarios.py")
rs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rs)
hits = [e[0] for e in rs.SCENARIOS if "ticket-lifecycle" in str(e[0])]
ok(not hits, "T1 SCENARIOS 无 ticket-lifecycle 条目（移册生效，非在册恒过）")
if hits:
    print("    残留: %s" % hits)

# ---- T2 README 移册登记：定稿条款 + 人工清单承接 + t260831-04 逆转依据 ----
readme = (REPO / "integration" / "README.md").read_text()
block = ""
for chunk in readme.split("\n- "):
    if "ticket-lifecycle" in chunk and ("移册" in chunk or "真跑不进闸" in chunk):
        block = chunk
        break
ok(bool(block), "T2 README 有 ticket-lifecycle 移册登记段")
if block:
    ok("真跑不进闸" in block or "定稿" in block, "T2b 登记引定稿条款（移册有明文通道，非裁量私断）")
    ok("人工" in block or "主库" in block, "T2c 真实覆盖承接在案（主库人工清单，非无人接盘）")
    ok("t260831-04" in block or "t260831-03" in block, "T2d 记录 t260831-04 登记裁定的逆转依据（C-c 防口径反复）")

# ---- T3 场景文件仍在树内且非空 ----
sc = REPO / "integration" / "baselines" / "sc_ticket_lifecycle.mjs"
ok(sc.is_file() and sc.stat().st_size > 0, "T3 场景文件仍在树内（移册≠删除，顶层人工跑通道保持）")

# ---- T4 护栏语义未被静默 neuter（env_fail 标记仍在） ----
if sc.is_file():
    text = sc.read_text()
    ok("env_fail" in text and "SUMMARY" in text,
       "T4 嵌套护栏 env_fail 语义仍在（设计性环境红标记未被改成恒过）")

# ---- T5 契约 v2.1 变更记录含移册依据 ----
contract = (REPO / "docs" / "design" / "sandbar-project-onboarding-contract-v1.md").read_text()
ok(re.search(r"v2\.1.*(?:真跑不进闸|移册|ticket-lifecycle)", contract) is not None
   or ("v2.1" in contract and "ticket-lifecycle" in contract),
   "T5 契约 v2.1 变更记录含移册依据（定稿条款引用，追加型历史 pin）")

print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (pass_n, fail_n))
sys.exit(1 if fail_n > 0 else 0)
