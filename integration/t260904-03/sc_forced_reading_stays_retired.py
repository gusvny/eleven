#!/usr/bin/env python3
"""sc_forced_reading_stays_retired.py — 必读映射表退役反向守护（t260904-03 / KI-035）。

intent（验收 E 的机械化，merge 关卡可跑）：server/**/*.py 与活文档 docs/README.md
对 WORKFLOW_CONTEXT / TITLE_CONTEXT_RULES / context_docs **零残留**——防旧映射表
从旧代码或旧文档被抄回（「照搬带回旧债」故障面的静态守护）。

豁免口径（写明防误判）：
  - notes/（KI 册 KI-034/KI-035 行、epic 沿革）——退役审计记录本体，非活引用；
  - .suyou/（段结果快照）——工单过程产物（本扫描根本不进这两处）；  # naming-compat
  - server/engine/tests/*.py——L1 回归测试的**负断言源码**必须写出
    token 字样才能断言「不含」（断言面≠消费面）；
  - 本场景文件自身——守卫要能说出自己在守什么。
真正被守护的活引用面=引擎代码（server/ 其余全部 *.py）+ 活文档 docs/README.md。
扫描器自证红绿（合成样本注入即红）。

Hermetic：只读扫描，零端口零网络，不触 3099；cwd=仓库根；秒级。
退出契约：stdout 末行 SUMMARY pass=N fail=K；exit 1 iff fail>0。

**t260904-03 implement 段落地前红属预期（两表尚在树），arbitrate/merge 期必须绿。**
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lib_dispatch_prompt as lib  # noqa: E402

TOKENS = ("WORKFLOW_CONTEXT", "TITLE_CONTEXT_RULES", "context_docs")
TOKEN_RE = re.compile(r"WORKFLOW_CONTEXT|TITLE_CONTEXT_RULES|context_docs")

# 断言面豁免（≠消费面）：L1 负断言源码与本守卫自身需要写出 token 字样
SELF_EXEMPT = re.compile(
    r"(?:^|/)(?:server/engine/tests/[^/]+\.py|"
    r"integration/t260904-03/sc_forced_reading_stays_retired\.py)$")

passed, failed = 0, 0


def check(cond, label):
    global passed, failed
    if cond:
        passed += 1
        print("  ok %s" % label)
    else:
        failed += 1
        print("  FAIL %s" % label)
    return cond


def scan_text(text):
    return sorted(set(TOKEN_RE.findall(text)))


def main():
    targets = [p for p in (lib.REPO / "server").rglob("*.py")]
    readme = lib.REPO / "docs" / "README.md"
    if readme.exists():
        targets.append(readme)

    print("== A 代码与活文档零残留（server/**/*.py + docs/README.md，%d 个目标）" % len(targets))
    hits = []
    for f in targets:
        rel = f.relative_to(lib.REPO).as_posix()
        if SELF_EXEMPT.search(rel):
            continue
        try:
            found = scan_text(f.read_text("utf-8"))
        except (OSError, UnicodeDecodeError) as e:
            hits.append("%s（不可读：%s）" % (rel, str(e)[:80]))
            continue
        if found:
            hits.append("%s → %s" % (rel, ",".join(found)))
    check(not hits, "零活引用残留%s" % (("；残留：" + "; ".join(hits[:6])) if hits else ""))

    print("== B 扫描器自证红绿（合成样本注入即红）")
    check(scan_text("WORKFLOW_CONTEXT = {}\nctx = context_docs(w, t)")
          == ["WORKFLOW_CONTEXT", "context_docs"], "合成样本两 token 全捕获（守卫自身有效）")
    check(scan_text("正常文本，无残留。") == [], "干净样本零误报")

    print("== C 豁免面在位（防误判口径自证）")
    check(SELF_EXEMPT.search("integration/t260904-03/sc_forced_reading_stays_retired.py")
          is not None, "守卫自身在豁免表（断言面可写 token 字样）")
    check(SELF_EXEMPT.search("server/engine/tests/test_any.py") is not None,
          "L1 负断言测试源码在豁免表（断言面≠消费面）")
    check(SELF_EXEMPT.search("server/engine/shared.py") is None,
          "引擎代码不豁免（消费面必查）")

    print("SUMMARY pass=%d fail=%d" % (passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
