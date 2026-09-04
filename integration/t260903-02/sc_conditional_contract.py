#!/usr/bin/env python3
"""t260903-02 集成场景 t02：③ 审读附条件放行的对外契约锁（integration 设计，t260903-02）。

用户场景：泳道提速③——review_plan 增第三态「附条件放行」。用户可感知的契约：
  A. 机器与人的契约同源：FLOW_BRIEF 告诉 agent「summary 写 verdict=pass|conditional|reject」，
     解析函数必须认**同一词表**且带负向断言（verdict=pass-xxx 不算）——文案与解析漂移 =
     agent 照文案输出但机器不认，整段格式纠正甚至误判。
  B. 轻瑕意见不丢：附条件放行时 review comments 直通 implement（可区分的注入前缀）。
  C. 放行不计打回轮：conditional 不消耗 MAX_REVIEW_ROUNDS——全仓 plan_rounds += 1 恰一处
     （reject 路径），放行不新增计数点。
  D. 打回环回归锁：reject 路径文案与超限 blocked 文案原样保留；纯函数被真接线
     （parse_review_plan_verdict(res.status, res.summary) + review_plan_route）。

跑法：python3 -B integration/t260903-02/sc_conditional_contract.py（纯源码断言，零依赖）。
契约基线 = 方案 v3（review_plan gen2 通过）。实现段完成前运行会红。
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
POC = HERE.parents[1] / "server" / "dsh" / "temporal-poc"
DL = (POC / "dev_lane.py").read_text("utf-8")
SH = (POC / "shared.py").read_text("utf-8")

PASS = 0
FAIL = 0


def ok(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok", msg)
    else:
        FAIL += 1
        print("  FAIL", msg)


def section(t):
    print("\n== %s" % t)


def flow_brief_entry(step_id):
    """抽取 FLOW_BRIEF 里某步的契约文案（括号串接体），找不到返回 ""。"""
    i = DL.find('"%s": (' % step_id)
    if i < 0:
        return ""
    j = DL.find('"),', i)
    return DL[i:j] if j > i else ""


section("A 契约文案与解析词表同源（含负向断言）")
brief = flow_brief_entry("review_plan")
ok(bool(brief), "FLOW_BRIEF[review_plan] 可抽取")
ok(all(w in brief for w in ("verdict=pass", "conditional", "reject")),
   "brief 三态词表齐全（agent 按此输出）")
m = re.search(r"def parse_review_plan_verdict\(.*?(?=\ndef |\n@|\n[A-Z_]+ =)",
              SH, re.S)
fn = m.group(0) if m else ""
ok(bool(fn), "parse_review_plan_verdict 定义可抽取")
alt = re.search(r"verdict=\((pass\|conditional\|reject)\)", fn)
ok(alt is not None, "解析正则的合法值字面在场")
if alt:
    vals = set(alt.group(1).split("|"))
    ok(vals == {"pass", "conditional", "reject"},
       "解析词表恰为三态（实测 %s）" % sorted(vals))
ok("(?![\\w-])" in fn, "负向断言在场（verdict=pass-xxx 不误吞）")

section("B 附条件意见直通 implement（不丢）")
i_c = DL.find("【附条件放行·implement 执行项】")
ok(i_c >= 0, "意见注入前缀字面在场（与打回文案可区分）")
if i_c >= 0:
    ok("res.report" in DL[i_c:i_c + 400], "前缀拼接的是 report 分条意见（comments 不丢）")

section("C 放行不计打回轮")
ok(DL.count("plan_rounds += 1") == 1,
   "plan_rounds 计数点恰 1 处（只在 reject 路径，conditional 不新增）")

section("D 打回环回归锁 + 纯函数真接线")
ok("【方案审读打回（第 %d 轮）】" in DL, "reject 打回文案原样保留")
ok("方案审读打回 %d 轮超限" in DL, "超限 blocked 文案原样保留")
ok("parse_review_plan_verdict(res.status, res.summary)" in DL,
   "解析函数按 (status, summary) 真接线（矛盾态保守侧入口）")
ok("review_plan_route(" in DL, "路由走 shared 纯函数（与 integration_route 同风格）")

print("\nt02 结果：pass=%d fail=%d" % (PASS, FAIL))
print("SUMMARY pass=%d skip=0 fail=%d" % (PASS, FAIL))
sys.exit(0 if FAIL == 0 else 1)
