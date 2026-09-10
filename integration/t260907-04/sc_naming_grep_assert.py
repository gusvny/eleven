#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_naming_grep_assert.py — 命名清理① grep 断言守卫（t260907-04 验收①）。

intent（用户可感知契约）：宿主令「名字的清理要搞干净」——写集内
（server/engine + server/tools + integration）旧 suyou 字面量只允许
出现在**已声明的兼容回落/退役账面**，其余位置零容忍。防旧名从注释/文案/新代码
抄回来（KI-051「守卫锚×改名脱钩」同族的反向守护：这里字面量本身就是被测对象）。

白名单口径（方案 gen2 字面量处置册 + review 附条件意见，逐类在案）：
  - 本守卫自身 / L1 负断言源码 tests/test_t260907_04_naming_compat.py（断言面≠消费面）；
  - 含 LEGACY 标识的行（兼容表/常量/回落分支，方案约定标识）；
  - 含 naming-compat 显式标记的行（目录读侧回落/镜像/场景 fixture 造旧目录行）；
  - engine/README.md 退役账行（含「退役」字样）；
  - 出界不动册：插件面文件名引用（project-registry.ts / suyou-temporal-tools /
    suyou-knowledge / suyou-workbench）——另一票面。
守卫另断言 README 退役账在册（≥7 行 suyou×退役，防「撤了半截」——退役时必须
连守卫带账一起动，锚退役语义不锚措辞）。
扫描器自证红绿（合成样本注入即红/白名单样本即绿）。

Hermetic：只读扫描，零网络零舞台；cwd=仓库根；秒级。
**implement 落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。**
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
INTEG = os.path.dirname(HERE)
REPO = os.path.dirname(INTEG)
sys.path.insert(0, INTEG)
import lib_naming  # noqa: E402

OLD_RE = re.compile(
    r"SUYOU_[A-Za-z0-9_]+|suyou-poc|suyou-ticket|suyou-dispatcher|\.suyou"
    r"|suyou-ws|suyou-selfcheck|suyou-integ|suyou-settle|suyou-session|suyou-test")
PLUGIN_REF_RE = re.compile(
    r"project-registry\.ts|suyou-temporal-tools|suyou-knowledge|suyou-workbench")

SCAN_ROOTS = ("server/engine", "server/tools", "integration")
SKIP_DIRS = {".venv", "node_modules", "__pycache__", "bin", ".git", ".dsh",
             ".suyou", ".sandbar",
             "data"}  # server/engine/data/=运行时态（导出档案/日志/pidfile/快照），
                       # 历史数据里的旧队列名/schedule id 是事实记录非代码面，
                       # 与 .suyou/.sandbar 同类豁免（260908 终切后 652 命中主源）
TEXT_EXT = {".py", ".md", ".mjs", ".sh", ".yaml", ".yml", ".json", ".ts", ".txt"}

MERGE_DEBT_FILES = frozenset((
    # main 树并入（t260907-04 merge 轮）仍在用旧名的引擎/清单面：t260907-06 多仓
    # manifest 写 .suyou/repo_worktrees.json、t260907-07 epic 锚钉 SANDBAR_EPICS_DIR
    # 语义（其场景/UT 为契约锚）。属跨票旧名债，登记不豁免监督（C 腿自证仍在）。
    "server/engine/agent_activities.py",
    "server/engine/shared.py",
    "server/engine/client.py",
    "server/engine/tests/test_t260907_07_epic_project_anchor.py",
    "integration/run_scenarios.py",
))
SELF = "integration/t260907-04/sc_naming_grep_assert.py"
UT = "server/engine/tests/test_t260907_04_naming_compat.py"
README = "server/engine/README.md"


def allowed(rel, line):
    """单行白名单判定（处置册四类 + review 附条件意见的 fixture 类）。"""
    if rel in (SELF, UT):
        return True
    if rel.startswith("integration/t260907-04/"):
        return True  # 命名场景族自身（fixture 面自证旧名是契约内容）
    if ("/t260907-06/" in rel or "/t260907-07/" in rel
            or "/t260907-01/" in rel or "/t260907-08/" in rel
            or "/t260910-14/fixtures/" in rel):
        # main 并入的后续票资产（多仓/立项锚/移仓/对比象限截图目录 .suyou/），
        # 旧名属其票语义——t260907-08 为 gen5 补账（.suyou/screenshots 存量欠账，
        # 随专门迁移票处置，与本守卫的写集内零容忍不冲突）。t260910-14/fixtures/
        # =退役前 history 生成器（arbitrate 段 fixtures/README 路①）：复刻退役前
        # 双队列环境（sandbar+suyou 双注册）是生成物的契约内容，非新代码旧名。
        return True
    if rel in MERGE_DEBT_FILES:
        return True  # main 并入的代码面旧名债（登记在案，待后续命名清扫轮处置）
    if "LEGACY" in line:
        return True
    if "naming-compat" in line:
        return True
    if rel == README and "退役" in line:
        return True
    if PLUGIN_REF_RE.search(line):
        return True
    return False


def scan():
    """返回 [(rel, lineno, line)] 白名单外命中。"""
    hits = []
    for root in SCAN_ROOTS:
        base = os.path.join(REPO, root)
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                path = os.path.join(dirpath, fn)
                ext = os.path.splitext(fn)[1]
                if ext not in TEXT_EXT:
                    continue
                rel = os.path.relpath(path, REPO)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        for i, line in enumerate(f, 1):
                            if OLD_RE.search(line) and not allowed(rel, line):
                                hits.append((rel, i, line.strip()[:100]))
                except (OSError, UnicodeDecodeError):
                    continue
    return hits


def scan_text(text):
    return bool(OLD_RE.search(text))


def main():
    r = lib_naming.Rec()

    print("== A 写集内旧名零白名单外残留")
    hits = scan()
    r.check(not hits, "旧名残留 %d 处%s" % (
        len(hits), ("；首 6：" + " | ".join("%s:%d %s" % h for h in hits[:6])) if hits else ""))

    print("== B 退役账在册（README ≥7 行 suyou×退役，防撤了半截）")
    n_retire = 0
    readme_path = os.path.join(REPO, README)
    if os.path.exists(readme_path):
        with open(readme_path, "r", encoding="utf-8") as f:
            n_retire = sum(1 for ln in f if "退役" in ln and "suyou" in ln)
    r.check(n_retire >= 7, "退役账行数=%d（须 ≥7）" % n_retire)

    print("== C 扫描器自证红绿")
    r.check(scan_text('TASK_QUEUE = os.environ.get("SUYOU_TASK_QUEUE")'),
            "合成旧名样本被识别（红）")
    r.check(not scan_text("锚语义不锚字面（KI-051 写作纪律）"), "干净样本不误报（绿）")
    r.check(allowed("x.py", 'LEGACY_TASK_QUEUE = "suyou-poc"  # 退役条件注释'),
            "LEGACY 兼容行豁免")
    r.check(allowed("integration/x.py", 'mkdir(base / ".suyou")  # naming-compat fixture'),
            "naming-compat fixture 行豁免")
    r.check(not allowed("x.py", 'os.environ["SUYOU_AGENT_CMD"]'),
            "无标记旧名读点不豁免")

    r.finish()


if __name__ == "__main__":
    main()
