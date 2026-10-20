#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_terminology_l7_gate.py — 术语废止看守升闸级（t260920-03 验收③）。

intent（用户可感知契约）：行话旧称（被禁词，真源=docs/terminology.md「禁用对照」）
的看守 L7（integration/lint_tests.py::lint_terminology）此前靠 agent 自觉自跑；
本场景把它注册进跑批注册表（ro 池），升为「每条跑批必跑」的闸级面。看守判据=
按文件出现次数基线（integration/terminology-baseline.json）：新增即红、超帽红、
基线缺失/畸形 fail-closed 红、allowlist（值 -1：术语表本体/基线自身）不受限。

自证纪律（看守必须自证「漂移必红」，否则断言恒真≠守卫，KI-051 反面）：
tmp 树内字节级复制真 lint 脚本 + 同构基线，注入式电池逐态验证——
干净绿 / 新文件红（点名不在基线内）/ 超帽红（点名新增用法）/ 移除复绿 /
allowlist 增量不红 / 畸形基线红 / 基线缺失红 / 看守脚本缺席=ENV_FAIL 三态映射。

场景源码自洁：本文件零被禁字残留（需要写出该字处一律 chr(0x817F) 构词），
看守对象自身不入基线、不成为新的欠账面；自洁由 T0 子用例自证。

Hermetic：真仓面只读 + tmp 合成树自证，零网络零舞台零 3099；cwd=仓库根，秒级。
三态：lint 脚本缺席=ENV_FAIL exit 2（环境红，什么都没验证到）；
真仓 L7 红=FAIL exit 1（产品红，点名违例清单）；全绿=exit 0。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
INTEG = REPO / "integration"
LINT = INTEG / "lint_tests.py"
TERM = chr(0x817F)  # 被禁词本体只在常量构词处出现，本文件其余位置零残留
PROBE_TIMEOUT_S = 120

# 单道探针：临时树内只跑 lint_terminology（L1-L6 需引擎/工作台面，临时树无），
# 复制来的 lint_tests.py 以自身 __file__ 推 REPO/INTEG，扫的正是临时树。
_DRIVER = '''"""L7 单道探针（看守自证电池专用，随场景写入临时树）。"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lint_tests as _lt
_lt.errors.clear()
_lt.lint_terminology()
sys.exit(1 if _lt.errors else 0)
'''

# ---------- 子用例记账 ----------

_PASSES: list[str] = []
_FAILS: list[str] = []


def ok(msg: str) -> None:
    _PASSES.append(msg)
    print("  ok %s" % msg)


def bad(msg: str) -> None:
    _FAILS.append(msg)
    print("  FAIL %s" % msg)


def expect(cond: bool, ok_msg: str, bad_msg: str) -> None:
    ok(ok_msg) if cond else bad(bad_msg)


# ---------- 判定面 ----------

def probe_l7(integ_dir: Path) -> tuple[str, str]:
    """对给定 integration 面跑真 L7 单道探针，返回 (state, output)。

    state ∈ {"pass", "fail", "env_fail"}。lint 脚本缺席=env_fail（三态映射
    本身是被测面之一，由自证电池验证）；探针退出码 0/1 → pass/fail；其余
    （超时/异常退出码）一律落 fail 响亮红，绝不静默当绿。只写探针文件到
    临时树，用完即删（finally）。
    """
    lint = integ_dir / "lint_tests.py"
    if not lint.is_file():
        return "env_fail", "lint_tests.py 缺席：%s" % lint
    drv = integ_dir / "_l7gate_probe.py"
    drv.write_text(_DRIVER, encoding="utf-8")
    try:
        try:
            p = subprocess.run(
                [sys.executable, str(drv)], capture_output=True, text=True,
                timeout=PROBE_TIMEOUT_S, cwd=str(integ_dir.parent))
        except subprocess.TimeoutExpired:
            return "fail", "探针超时（>%ds）——看守卡死属产品红" % PROBE_TIMEOUT_S
    finally:
        try:
            drv.unlink()
        except OSError:
            pass
    out = (p.stdout or "") + (p.stderr or "")
    if p.returncode == 0:
        return "pass", out
    if p.returncode == 1:
        return "fail", out
    return "fail", "探针异常退出码 %s\n%s" % (p.returncode, out)


def real_gate() -> tuple[str | None, list[str]]:
    """真仓判定面：in-process 直调真 lint_terminology（票面「等价直调」口径）。

    真仓零写接触（不落探针文件）；返回 (env_fail_reason|None, failures)：
    env_fail_reason 非 None=环境红（exit 2）；否则 failures=L7 违例清单
    （空=绿）。
    """
    if not LINT.is_file():
        return "integration/lint_tests.py 缺席（%s）——看守无法判定" % LINT, []
    sys.path.insert(0, str(INTEG))
    import lint_tests as lt  # noqa: E402 —— 场景约定 sys.path=integration/
    lt.errors.clear()
    lt.lint_terminology()
    return None, list(lt.errors)


# ---------- 自证电池（tmp 同构树） ----------

def build_tree(root: Path, baseline_counts: dict, files: dict) -> Path:
    """搭同构临时树：字节级复制真 lint 脚本 + 给定基线与样本文件。

    同构关键：真基线把「基线文件自身」列 allowlist（-1）——term 字段本身
    含被禁字，不自豁免则看守开机即自红；合成基线必须复刻该形状。
    261012 修：lint_tests.py 的同族依赖（lib_*、lint_*）必须随行——此前只拷
    主脚本，lint_tests 后来新增 lib_fault_injection 顶层导入后，自测树
    ModuleNotFoundError 连挂 7 项（main 与线轮同挂，实测 261012）。随行清单
    从 lint_tests.py 自身的导入句动态解析，不手抄（手抄必再腐）。
    """
    counts = {"integration/terminology-baseline.json": -1, **baseline_counts}
    integ = root / "integration"
    integ.mkdir(parents=True)
    shutil.copy2(LINT, integ / "lint_tests.py")
    # t261012-05 修复（副本烂根，S1 干净树红实案）：lint_tests.py 的 integration 本地
    # 模块依赖必须随脚本一起进副本，否则 `import lint_tests` 在临时树内 ModuleNotFoundError
    # →探针 traceback 退出→S1/S4/S5 全部假红。来源实锚：lint_tests.py:141 模块级
    # `import lib_fault_injection`（t261009-52 落地，晚于本场景）。
    # 261012 收口：main 侧 2a23c658 批的集成直修（b3033112）与本票撞在同一病灶——
    # 并集取 main 的更宽实现（import/from 双形 + lint_* 同族 + 排除主件自身），
    # 本票的事件注记保留在案。
    _LOCAL_DEP_RE = re.compile(r"^\s*(?:import|from)\s+(lib_\w+|lint_\w+)", re.M)
    for mod in sorted(set(_LOCAL_DEP_RE.findall(LINT.read_text(encoding="utf-8")))):
        src = INTEG / (mod + ".py")
        if src.is_file() and mod != "lint_tests":
            shutil.copy2(src, integ / src.name)
    (integ / "terminology-baseline.json").write_text(
        json.dumps({"term": TERM, "counts": counts,
                    "note": "看守自证电池同构基线（临时树，用毕即焚）"},
                   ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return integ


def set_counts(root: Path, baseline_counts: dict) -> None:
    counts = {"integration/terminology-baseline.json": -1, **baseline_counts}
    (root / "integration" / "terminology-baseline.json").write_text(
        json.dumps({"term": TERM, "counts": counts},
                   ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")


def battery() -> None:
    """注入式红绿电池：一棵临时树顺序演进，逐态断言，finally 全清理。"""
    root = Path(tempfile.mkdtemp(prefix="l7gate-selftest-"))
    try:
        integ = build_tree(
            root,
            baseline_counts={"integration/sample.py": 0, "docs/glossary.md": -1},
            files={"integration/sample.py": "VALUE = 1\n",
                   "docs/glossary.md": (TERM + TERM + TERM + "\n")})
        # S1 干净树：allowlist（-1）在唱仍绿
        st, _out = probe_l7(integ)
        expect(st == "pass", "S1 干净树绿（allowlist 条目在场不受限）",
               "S1 干净树应绿，实得 %s\n%s" % (st, _out[-400:]))
        # S2 注入新文件（基线无此键）→ 红并点名「不在基线内」
        (root / "docs" / "new.md").write_text(TERM + "\n", encoding="utf-8")
        st, out = probe_l7(integ)
        expect(st == "fail" and "docs/new.md" in out and "不在基线内" in out,
               "S2 新文件注入即红且点名 docs/new.md（不在基线内）",
               "S2 注入应红并点名，实得 %s\n%s" % (st, out[-400:]))
        # S3 撤注入→既有文件超帽（帽 0）→ 红并点名「新增用法」
        (root / "docs" / "new.md").unlink()
        (root / "integration" / "sample.py").write_text(
            "VALUE = %r\n" % TERM, encoding="utf-8")
        st, out = probe_l7(integ)
        expect(st == "fail" and "integration/sample.py" in out and "新增用法" in out,
               "S3 既有文件超帽即红且点名 integration/sample.py（新增用法）",
               "S3 超帽应红并点名，实得 %s\n%s" % (st, out[-400:]))
        # S4 移除注入 → 复绿
        (root / "integration" / "sample.py").write_text("VALUE = 1\n",
                                                        encoding="utf-8")
        st, _out = probe_l7(integ)
        expect(st == "pass", "S4 移除注入复绿", "S4 移除后应绿，实得 %s\n%s"
               % (st, _out[-400:]))
        # S5 allowlist 增量不受限（-1 条目 3→6 处仍绿）
        (root / "docs" / "glossary.md").write_text(TERM * 6 + "\n",
                                                   encoding="utf-8")
        st, _out = probe_l7(integ)
        expect(st == "pass", "S5 allowlist 增量（3→6 处）不受限仍绿",
               "S5 allowlist 增量应不红，实得 %s\n%s" % (st, _out[-400:]))
        # S6 畸形基线 → fail-closed 红
        (root / "integration" / "terminology-baseline.json").write_text(
            "{oops 不是 JSON", encoding="utf-8")
        st, out = probe_l7(integ)
        expect(st == "fail" and "畸形" in out,
               "S6 畸形基线 fail-closed 红（点名畸形）",
               "S6 畸形基线应红，实得 %s\n%s" % (st, out[-400:]))
        # S7 基线缺失 → fail-closed 红
        (root / "integration" / "terminology-baseline.json").unlink()
        st, out = probe_l7(integ)
        expect(st == "fail" and "缺失" in out,
               "S7 基线缺失 fail-closed 红（点名缺失）",
               "S7 基线缺失应红，实得 %s\n%s" % (st, out[-400:]))
        # T7（映射面）看守脚本缺席 → env_fail 三态映射自证
        empty = root / "integration_bare"
        empty.mkdir()
        st, out = probe_l7(empty)
        expect(st == "env_fail",
               "T7 看守脚本缺席判 env_fail（三态映射，非产品红）",
               "T7 脚本缺席应映射 env_fail，实得 %s：%s" % (st, out[:200]))
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ---------- 主流程 ----------

def main() -> int:
    # T0 场景源码自洁：看守对象自身零被禁字（否则本文件就是新欠账面）
    src = Path(__file__).read_text(encoding="utf-8")
    expect(TERM not in src,
           "T0 场景源码自洁（被禁字零残留，全 chr 构词）",
           "T0 场景源码出现被禁字——自洁破功（须改用 chr 构词）")

    env_reason, failures = real_gate()
    if env_reason:
        print("ENV_FAIL: %s" % env_reason)
        return 2
    if failures:
        for m in failures:
            print("  FAIL 真仓 L7 红：%s" % m)
        print("\nSUMMARY pass=%d fail=%d（真仓看守红=存量违例清单）"
              % (len(_PASSES), len(failures)))
        return 1
    ok("真仓 L7 绿（无新增，存量在基线帽内随替换批次收缩）")

    battery()

    print("\nSUMMARY pass=%d fail=%d" % (len(_PASSES), len(_FAILS)))
    return 1 if _FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
