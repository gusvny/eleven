#!/usr/bin/env python3
"""sc_template_retire_no_revival.py — 模板退役防复活负扫描（宿主令 260904，t260904-08）。

intent（用户可感知行为/合同）：退役模板不得以任何活引用形式「复活」——四退役
workflow 类名与 content-pipeline 模板记号在写集五面（引擎 / tools / integration /
两篇指定 docs）零无豁免活引用。防的故障面：
  - 从 git 历史 / 旧代码抄回复活注册（重演「照搬带回旧债」形态，同 KI-035 反向
    守护的教训）；
  - 半截清除：注册行删了但 USAGE/示例/注释仍教学用户可用（误导操作面）；
  - 豁免面扩张失控：本场景同时钉住「标注面必须真带退役标注」，防整文件豁免
    沦为无标注的黑洞。

豁免口径（每条都有声明依据，全表见 lib_retire.ALLOW_FILES）：
  - 带退役标注的注释行（「已退役注释」豁免口径的机械化）；
  - v1 留存引擎样例（gen0 评审 R1 裁定：t260904-03 lib/场景测
    build_dispatch_prompt + STAGE_CLAUSES 留存面，非模板可用性）及其 docstring；
  - shared.py 留存数据表键（(模板,段) 元组，gen1 方案声明全部留存不动）；
  - 声明保留的 v1 演示面（workflows.py 步1 类 + demo_*.sh/.py，start 已断属预期）
    与退役标注面（两篇 docs、两 README）；
  - 场景注册表 intent 文本与历史对照夹具（test_t260904_03_t01 rich 组构造输入，
    gen0 评审 C1）。

与 t260904-03-forced-reading-retired 分工（防 intent 级重复）：彼守 KI-035 旧
文档映射表（WORKFLOW_CONTEXT/TITLE_CONTEXT_RULES）零活引用；本守 260904 模板族
退役零活引用——守护对象不同，不互替。词表不含裸词 proofread/regression/cleanup
（分工 kind/测试词汇/函数名撞词，取舍见 lib_retire 模块注）。

Hermetic：只读扫描 + 临时目录自证样本，零网络零端口；cwd=仓库根；秒级。
退出契约（三态 §7.3）：stdout 末行 SUMMARY pass=N fail=K env_fail=E na=0；
exit 0=PASS；exit 1=FAIL 产品红；exit 2=ENV_FAIL 环境红（本场景纯离线扫描，
无缺环境分态，env_fail 恒 0）。

**退役落地前红属预期（TDD 信号）；扫描红=列出的 file:line 即待清残留清单，
arbitrate/merge 期必须绿。**
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib_retire as lib  # noqa: E402

passed, failed, env_failed = 0, 0, 0


def check(cond, label):
    global passed, failed
    if cond:
        passed += 1
        print("  ok %s" % label)
    else:
        failed += 1
        print("  FAIL %s" % label)


def main():
    print("== A 扫描器自证红绿（纯函数，可注入样本）")
    check(not lib.allow("server/x_fake.py", "T = TEMPLATE_CLASSES['content-pipeline']"),
          "豁免判定自证红：活代码引用不豁免")
    check(lib.allow("server/x_fake.py", "# content-pipeline 已退役（260904 宿主令）"),
          "豁免判定自证绿：带退役标注的注释行豁免")
    check(lib.allow("server/x_fake.py",
                    "'description': '原 content-pipeline 专用，260904 起仅留兼容形态',"),
          "豁免判定自证绿：描述串/报错文案里的退役标记同样豁免（判红的是声称可用，"
          "不是提到退役事实）")
    check(lib.allow("server/engine/shared.py",
                    '("content-pipeline", "ai-review"): ["..."],'),
          "豁免判定自证绿：shared.py 留存数据表键豁免")
    check(lib.allow("server/engine/shared.py",
                    "# 260904 宿主令：仅存 dev-lane（content-pipeline 等已退役）"),
          "豁免判定自证绿：shared.py 带退役标记的注释豁免（表键未命中不得提前返回）")
    check(not lib.allow("server/engine/shared.py",
                        '"content-pipeline": "ContentPipelineTicketWorkflow",'),
          "豁免判定自证红：shared.py 非表键行（如真源表残行）不豁免")
    check(lib.allow("server/engine/workflows.py",
                    "class ContentPipelineTicketWorkflow:  # 假想复活"),
          "豁免判定自证绿：v1 留存面整文件豁免（声明保留）")
    hits = lib.scan_lines("server/x_fake.py",
                          ["a = 1",
                           'W = "content-pipeline"',
                           "# 已退役（260904）：content-pipeline",
                           "from proofread import ProofreadWorkflow"])
    check(len(hits) == 2 and hits[0][0] == 2 and hits[1][0] == 4,
          "行扫描自证：恰 2 处违规（行 2/4），标注行与净行不误报（实得 %r）"
          % [(h[0], h[2]) for h in hits])

    print("== B 扫描面完整性哨兵（面配置漂移=假绿，先红）")
    sentinels = (
        lib.POC / "workflows.py",
        lib.POC / "shared.py",
        lib.WORKFLOWS_DIR / "dev-lane.yaml",
        lib.TOOLS_DIR / "ticket.py",
        lib.INTEG_DIR / "run_scenarios.py",
        lib.REPO / lib.DOC_TWO[0],
        lib.REPO / lib.DOC_TWO[1],
    )
    for s in sentinels:
        check(s.exists(), "扫描面哨兵在位：%s" % lib.rel_of(s))
    n_files = sum(1 for _ in lib.iter_face_files())
    check(n_files > 100, "扫描面非空（%d 个文件；空面=扫描失效，不许静默绿）" % n_files)

    print("== C 退役标注面在位（防整文件豁免沦为无标注黑洞）")
    for rel in ("server/engine/README.md",
                "server/workflows/README.md") + lib.DOC_TWO:
        text = (lib.REPO / rel).read_text("utf-8")
        annotated = "260904" in text and "退役" in text
        if rel in lib.DOC_TWO:
            # 两篇指定 docs 按方案承诺以「已退役（260904）」标注保留上下文（非删除）
            check(annotated, "退役标注在位：%s（260904+退役字样）" % rel)
        else:
            # 两 README 按方案 R6c 允许两形态：加退役标注，或整行删除零残留
            has_tokens = any(t in text for t in lib.SCAN_TOKENS)
            check(annotated or not has_tokens,
                  "README 退役处置在位：%s（标注或删除两形态之一）" % rel)

    print("== D 全面负扫描（违规=复活残留，file:line 即清残留清单）")
    violations = lib.scan_repo()
    if violations:
        for rel, lineno, line, toks in violations:
            check(False, "复活残留 %s:%d %s | %s" % (rel, lineno, ",".join(toks),
                                                     line.strip()[:100]))
    else:
        check(True, "写集五面零无豁免退役活引用")

    print("SUMMARY pass=%d fail=%d env_fail=%d na=0" % (passed, failed, env_failed))
    return 2 if env_failed else (1 if failed else 0)


if __name__ == "__main__":
    sys.exit(main())
