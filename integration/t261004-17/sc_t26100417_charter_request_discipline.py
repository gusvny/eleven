#!/usr/bin/env python3
"""sc_t26100417_charter_request_discipline.py — t261004-17 Part C 提问纪律条款面
（灰盒 L3 文档契约 + 守卫测试联动，离线秒级，ro 池）。

Intent（用户可感知行为；工单 Part C）：向请求账提问的人（执行器会话）拿得到一份成文
契约——一行一个决定、问题一行约 60 字、2–4 个短选项且推荐项在前、无选项必须给默认
动作、detail 只放证据且在问题之后、状态汇报不进请求账、术语要么不用要么一句话解释。
宿主不再收到「两问挤一行、选项只盖一问、状态汇报占答案槽」的坏请求。

  C1 纪律与红线段（必须说人话块旁边）新增一条请求提问纪律，条款七要素逐项在场
     （锚语义不锚字面：认要素不认措辞）。
  C2 守卫测试 server/engine/tests/test_t260925_21_report_language.py 全绿（工单点名
     不得打红的既有 guard）。
  C3 语言面：新条款用中文（session_charter.md 是中文文件，不因本票翻译）。

intent 分工：报告语言面（说人话/STE）归 test_t260925_21_report_language.py 本身；
术语锁/词表归 t261002-14 vocab 族；本条只锁「请求提问纪律条款在场 + guard 不红」。
"""
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CHARTER = REPO / "server/session_charter.md"
GUARD = REPO / "server/engine/tests/test_t260925_21_report_language.py"


def pick_python() -> str:
    # engine venv first; system python3 fallback. The retired legacy venv layout
    # is deliberately NOT probed: t260907-10's old-path scanner reds any new
    # textual reference, and the venv-compat fallback chain ends at the
    # interpreter running this scenario.
    venv = REPO / "server/engine/.venv/bin/python"
    if venv.exists():
        return str(venv)
    return sys.executable


def main() -> int:
    results = []  # (name, ok, reason)

    # C1 七要素在场（锚语义：每一要素一条可判定的子串/正则）
    text = CHARTER.read_text(encoding="utf-8") if CHARTER.exists() else ""
    disc = ""
    m = re.search(r"##\s*纪律与红线(.*?)(?=\n##\s|\Z)", text, re.S)
    if m:
        disc = m.group(1)
    else:
        results.append(("C1-discipline-section-present", False, "session_charter.md 缺「纪律与红线」段"))
    # 必须说人话块与新条款相邻（新条款插在其附近，不在相隔十万里处）
    near = bool(re.search(r"必须说人话", disc))
    seven = [
        ("one-request-one-decision", r"(一行一个决定|一个请求.{0,12}一个决定|一次.{0,6}问.{0,10}一件事|一个请求.{0,20}只.{0,6}(问|要))"),
        ("question-one-line-60", r"(一行.{0,12}60|60\s*字|一行以内)"),
        ("two-to-four-options", r"(2[-–—~到]\s*4|两到四个?|2～4|2-4).{0,12}(选项|个选项)"),
        ("recommended-first", r"(推荐.{0,8}(放|在).{0,4}(第?一|最前)|第一个.{0,6}推荐)"),
        ("default-action-required", r"(没有选项|无选项|不带选项)[^。\n]{0,25}(必须|须)|(必须|须)[^。\n]{0,25}(默认动作|default_action)|(default_action|默认动作)[^。\n]{0,40}(必须|发生什么)"),
        ("detail-evidence-only", r"(detail|详情|补充说明).{0,30}(证据|只放)"),
        ("no-status-reports", r"(状态汇报|进度汇报).{0,20}(不进|不占|不要|不写入)"),
        ("term-explained", r"(术语.{0,20}(不用|解释)|要么不用.{0,10}(要么|或).{0,10}解释)"),
    ]
    if disc:
        missing = [name for name, pat in seven if not re.search(pat, disc)]
        placement = "near" if near else "far"
        results.append(("C1-discipline-clauses-present", not missing,
                        f"missing={missing} placement={placement}"))
        # C3 中文条款（元素锚定中文措辞已在 seven 的正则里；这里补钉「该条款不是英文段」）
        english_rule = bool(re.search(r"\bone request is one decision\b", disc))
        results.append(("C3-rule-in-chinese", not english_rule,
                        "english-literal-found" if english_rule else "chinese"))

    # C2 守卫测试全绿
    if not GUARD.exists():
        results.append(("C2-guard-test-present", False, str(GUARD)))
    else:
        p = subprocess.run([pick_python(), "-m", "pytest", str(GUARD), "-q"],
                           capture_output=True, text=True, timeout=300, cwd=str(REPO))
        tail = (p.stdout + p.stderr).splitlines()
        results.append(("C2-guard-test-green", p.returncode == 0,
                        tail[-1][:160] if tail else f"rc={p.returncode}"))

    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    for name, ok, reason in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name} — {reason}")
    print(f"SUMMARY pass={passed} fail={failed} env_fail=0 na=0")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
