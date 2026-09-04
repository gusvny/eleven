#!/usr/bin/env python3
"""t260901-23 集成测试 t04：yaml 快照与 workflow 代码真源一致（t260901-05 漂移债收口）。

用户场景：工单台泳道图（源=server/dsh/workflows/*.yaml，经 server/tools/workflow.py
只读消费）展示的阶段链，就是用户对「工单怎么跑」的心智模型。yaml 与模版类 STAGES
代码漂移时，用户看到的链序与 workflow 实际执行顺序不一致（t260901-05 实证：
dev-lane 把 ui_evidence 画在 design_integration_tests 之前，实际执行相反）。
断言：
  A. gen_workflows_doc.py --check 绿（生成器逐张渲染比对 + 回读校验，退出码 0）。
  B. dev-lane.yaml 里 design_integration_tests 紧跟 implement、ui_evidence 紧跟
     design_integration_tests（可读断言，不依赖生成器内部）。
跑法：python3 -B integration/t260901-23/t04_yaml_chain_truth.py
（优先 venv 解释器——生成器导入 TEMPLATE_CLASSES 需 temporalio；缺 venv 且回落
解释器也无 temporalio 时 A 段显式 SKIP 带原因、B 段恒真跑，不静默绿。）
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
POC = REPO / "server" / "dsh" / "temporal-poc"
GEN = POC / "gen_workflows_doc.py"
VENV_PY = POC / ".venv" / "bin" / "python"
YAML = REPO / "server" / "dsh" / "workflows" / "dev-lane.yaml"

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


def _sdk_available(py):
    """选定解释器能否 import temporalio（生成器导入 TEMPLATE_CLASSES 的前提）。"""
    try:
        r = subprocess.run([py, "-c", "import temporalio"],
                           capture_output=True, text=True, timeout=30)
        return r.returncode == 0
    except OSError:
        return False


def main():
    print("t04 yaml 快照与代码真源一致")
    py = str(VENV_PY) if VENV_PY.is_file() else sys.executable

    skipped = 0
    if not _sdk_available(py):
        # 依赖缺失干净 SKIP（integration/README.md 执行契约）：worktree/沙箱常态
        # 无 .venv，生成器 --check 两项如实跳过；B 段 yaml 可读断言不依赖 SDK 照跑。
        # （生成器在模块顶层 import TEMPLATE_CLASSES——workflows_v2→cleanup→temporalio，
        # 缺 SDK 时 import 必崩，这不是漂移红，是环境缺依赖；docstring 承诺的
        # 「显式报 skip 原因不静默绿」在这里兑现。合并消解 t260902-02：两侧同语义，
        # 取泳道侧实现——SUMMARY 的 skip 计数由它承载。）
        skipped += 2
        print("  skip 生成器 --check 两项 | temporalio SDK 不可用（%s），"
              "生成器需导入 TEMPLATE_CLASSES；有 SDK 环境重跑即恢复覆盖" % py)
    else:
        # A. 生成器 --check 绿（漂移/回读校验任一红都算失败）
        r = subprocess.run([py, str(GEN), "--check"], cwd=str(REPO),
                           capture_output=True, text=True, timeout=120)
        ok(r.returncode == 0, "--check 退出码 0（%s）"
           % (r.stdout.strip() or r.stderr.strip())[:120])
        ok("check 绿" in r.stdout, "--check 输出 check 绿：%s" % r.stdout.strip()[:80])

    # B. dev-lane.yaml 链序可读断言
    ids = [ln.strip().split(":", 1)[1].strip()
           for ln in YAML.read_text("utf-8").splitlines()
           if ln.strip().startswith("- id:")]
    ok(len(ids) > 0, "dev-lane.yaml 解析出 %d 个 stage id" % len(ids))
    for a, b in (("implement", "design_integration_tests"),
                 ("design_integration_tests", "ui_evidence"),
                 ("ui_evidence", "run_integration_tests")):
        ok(ids.index(b) == ids.index(a) + 1 if a in ids and b in ids else False,
           "%s 紧跟 %s（链=%s）" % (b, a, "→".join(ids)))

    print("t04 结果：pass=%d skip=%d fail=%d" % (PASS, skipped, FAIL))
    print("SUMMARY pass=%d skip=%d fail=%d" % (PASS, skipped, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
