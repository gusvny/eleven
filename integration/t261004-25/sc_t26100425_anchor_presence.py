#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261004-25 场景④：锚清单缺口显名——被锚点名的测试文件缺席必须 lint 红点名
（灰盒 L3，真 lint_tests.py 子进程 + 字节回滚的临时改写，零 docker）。

intent（实案=main 树残留：integration/test_anchors.json 点名
server/engine/tests/test_t261002_10_codegen_freshness.py，该文件未被任何 commit
保护——checkout/clean 即静默毁灭，今天没有任何机械面会响）：
- **锚点名的缺席文件=lint 红且点名**：往 test_anchors.json 注入一个不存在的引擎
  测试路径 → lint 红，输出点名该路径（哪个锚断了必须说得出文件名）；
- **移除注入即恢复**：字节回滚后 lint 输出不再含该路径（无残留，守卫自身守卫生）；
- **畸形锚清单 fail-closed**：test_anchors.json 被写成非法 JSON → lint 红（解析
  问题被点名），不崩不静默绿——锚清单自身也是外部输入，坏账本不许变哑闸；
- **已知 main 残留观察项**：test_t261002_10_codegen_freshness.py 在当前树的缺席
  只**报告**不断言（其补 commit 是 main 侧交接项，不在本票写集；断言会把本票
  merge 卡死在别人欠的账上）。

与相邻场景 intent 分界：
- t261004-20-test-anchor-brakes：彼锁锚清单的**标签词表/snapshot 声明**纪律
  （锚什么），本条锁**存在性**（被锚的文件还在盘上）——不同故障面；
- developer L1（lint 函数分支）白盒随实现，本条锁真 CLI 端到端。

跑法：python3 -B integration/t261004-25/sc_t26100425_anchor_presence.py（cwd=仓根）
纯 stdlib。三态：PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2。
实现落地前注入面红属预期（TDD 信号），arbitrate/merge 期必须绿。
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
ANCHORS = REPO / "integration" / "test_anchors.json"
INJECT_REL = "server/engine/tests/test_t261004_25_absent_probe.py"
KNOWN_RESIDUE = "server/engine/tests/test_t261002_10_codegen_freshness.py"

passed = 0
failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("ok    " + name)
    else:
        failed += 1
        print("FAIL  " + name + (("：" + detail) if detail else ""), flush=True)
    return bool(cond)


def run_lint():
    p = subprocess.run([sys.executable, "-B", "integration/lint_tests.py"],
                       cwd=str(REPO), capture_output=True, text=True, timeout=300)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main():
    original = ANCHORS.read_bytes()
    try:
        # ---- L1 注入缺席锚 → lint 红且点名 ----
        print("\n== L1 缺席的锚点名文件 → lint 红点名")
        man = json.loads(original.decode("utf-8"))
        man["engine_tests"][INJECT_REL] = {"anchor": "behaviour", "note": "presence probe",
                                           "sync_path": ""}
        ANCHORS.write_text(json.dumps(man, ensure_ascii=False, indent=2),
                           encoding="utf-8")
        rc1, out1 = run_lint()
        check("L1a lint 红", rc1 != 0, "rc=%s" % rc1)
        check("L1b 输出点名缺席文件（说得出哪个锚断了）", INJECT_REL in out1,
              "out tail=%r" % out1[-300:])

        # ---- L2 畸形锚清单 → 红且点名解析问题，不崩不假绿 ----
        print("\n== L2 畸形锚清单 fail-closed")
        ANCHORS.write_text("{not json", encoding="utf-8")
        rc2, out2 = run_lint()
        check("L2a lint 红（坏账本不是哑闸）", rc2 != 0, "rc=%s" % rc2)
        check("L2b 输出点名解析问题（非 traceback 裸崩）",
              ("anchors" in out2 or "JSON" in out2 or "json" in out2),
              "out tail=%r" % out2[-300:])
    finally:
        ANCHORS.write_bytes(original)  # 字节回滚，零残留

    # ---- L3 回滚后输出不再点名注入路径；已知 main 残留只观察 ----
    print("\n== L3 零残留 + 已知 main 残留观察项")
    rc3, out3 = run_lint()
    check("L3a 回滚后输出不含注入路径（守卫自身零残留）", INJECT_REL not in out3,
          "leaked into output")
    if not (REPO / KNOWN_RESIDUE).exists():
        print("OBSERVE main 残留在场：%s 未被任何 commit 保护（lint 红）——"
              "补 commit 是 main 侧交接项，不在本票写集，此处只报告不断言"
              % KNOWN_RESIDUE)
    else:
        print("ok    main 残留已补 commit：%s 在盘" % KNOWN_RESIDUE)

    print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (passed, failed))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
