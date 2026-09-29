#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_engine_layout.py — 宿主令 v6 五层结构守卫＋全仓旧路径残留清零（t260907-10 验收①③）。

intent（用户可感知契约）：宿主裁定 v6 结构定稿——引擎住 server/engine（不叫 temporal），
server/dsh 包装层退场，插件/装配配方/角色声明五层上移齐整。读者按 CLAUDE.md/接入契约
指的路径找引擎与插件必须命中真身；残留的旧路径（连写或段式杂糅如 "server"/"dsh"/"engine"）
=代码指向一个不存在的位置，一用即炸或静默造出新数据目录（data 红线邻接面）。

high-level steps：
  A. 五层逐项在位（锚目标树清单：目录＋哨兵文件，不锚数字——review gen1 条件①）：
     engine＋哨兵（client/worker/shared/agent_activities/base/dev_lane）；
     plugins 五插件（cordis 农场实挂：ui/workbench/knowledge/providers/temporal-tools）各
     package.json；profile／profile-headless 装配配方两变体（headless 的 patch 仍为软链）；
     roles 三 persona；model-routes.yaml；ui-check；tools 四件；平移件（sandbar-tools.ts、
     project-registry.ts 只平移不改名〔review gen0 B1 裁定〕、headless-resume、workflows）。
  B. server/dsh 目录不存在（包装层退场）。
  C. 全仓旧路径零残留（连写 server/dsh／temporal-poc＋段式杂糅两型），全后缀扫描
     （沿 t260907-05 取舍清单「带」项：无 include 白名单），豁免逐处归类（列名制）：
       - 文件级：server/admin.log（追加式审计流水不可改写）；CLAUDE.md（写集外宿主
         merge 债，review gen0 A1 申报在案——其目录节由宿主/main 侧更新）；
       - 前缀级：notes/（历史票快照与账本，非活指针）；integration/t260907-10/
         （本场景族自身＋fixture 面，沿 t260907-04 先例）；
       - 行级（回落链行三形态，工单⑤切法一；摘除票落地后归零）：engine-venv-compat
         marker（单边旧路径行须补此标记）、票号锚 t260907-10（回落注释）、探测对同行
         （新旧两路径同在=probe 循环/双认谓词的结构特征）；
       - docs/ 内含「退役」账行豁免（沿 t260907-04 README 退役账先例）。
     命中按域归类计数落输出，清单外新病灶即红。
  D. 扫描器自证红绿（连写样本/段式杂糅样本/marker 豁免/合法面不误报：docker 服务名
     dsh、DSH_HOME 型 ~／.dsh 路径、dsh CLI spawn 均不触发）。

与既有资产 intent 区别（防 intent 级重复）：t260907-05 sc_profile_farm_sandbar_links 守
装载链三方一致（软链指向），t260907-04 sc_naming_grep_assert 守 suyou 旧名 token——本条
守 v6 目录结构齐整与路径残留，不同面。Hermetic：纯文件读，零端口零 spawn，cwd=仓库根，
秒级。**implement 落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。**
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
INTEG = os.path.dirname(HERE)
REPO = os.path.dirname(INTEG)
sys.path.insert(0, INTEG)
sys.path.insert(0, os.path.join(INTEG, "t260907-04"))  # 共享 helper：lib_naming.Rec
import lib_naming  # noqa: E402

# ── token 集 ──────────────────────────────────────────────────────────────
# 连写型：server/dsh（包装层旧路径）、temporal-poc（引擎旧名，宿主令「不能叫temporal」）
RE_PLAIN = re.compile(r"server/dsh|temporal-poc")
# 段式杂糅型一：dsh 段后接 v6 层名（"dsh" / "engine" / 'dsh' / 'workflows' 等）——
# 机械替换把 temporal-poc→engine 打进旧串留下的嵌合体，连写 grep 抓不到（实测漏网型）。
RE_SEG_FWD = re.compile(
    r"""["']dsh["']\s*(?:/\s*["']?|,\s*["'])"""
    r"""(?:engine|plugins|profile|profile-headless|headless-resume|headless|roles|"""
    r"""ui-check|workflows|workbench|knowledge|providers|temporal-tools|ui\b|"""
    r"""model-routes|projects\.yaml|merge-checks|sandbar-tools|session_charter)""")
# 段式杂糅型二：server 段在前接 dsh 段（pathlib.Path("server") / "dsh"）
RE_SEG_REV = re.compile(r"""["']server["']\s*/\s*["']dsh["']""")

SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__", ".sandbar",
             ".dsh", "out", "data", "bin",
             ".suyou", ".lane", ".worktrees", ".pytest_cache"}  # naming-compat：运行时/泳道档案：resume_patch 与
# 台面记录里引用当时真实存在的旧路径（server/dsh/headless-resume 等），属历史事实
# 记录非活指针——与已排除的 .sandbar 同类（260908 终切后 C 段 3187 命中全在此，
# 无一在代码面；活指针残留仍会被扫到）
TEXT_EXT = {".py", ".md", ".mjs", ".js", ".cjs", ".sh", ".yaml", ".yml", ".json",
            ".ts", ".tsx", ".txt", ".html", ".css", ".sql", ".cfg", ".toml"}

# 文件级豁免（列名制，逐处可归因）
EXEMPT_FILES = {
    "server/admin.log",   # 追加式审计流水：回执逐字引用历史 write_set，不可改写
    "CLAUDE.md",          # 写集外宿主 merge 债（gen0 A1 申报）；内容现由宿主侧处置
    # 回落契约专属 UT（断言载体：fixture 造旧路径＋「回落命中旧路径」断言，
    # token 即被测契约内容——沿 t260907-04 UT 豁免先例）
    "server/engine/tests/test_engine_venv_fallback.py",
    # 项目仓内 server/dsh/reviews=**活约定**（workbench node.ts:852
    # join(anchor.root,'server','dsh') 的审批落点，t260907-11 KI-057 锚定）；项目仓
    # 布局与引擎仓布局是两个域，v6 摊平只动了引擎仓——这三文件引用的是活指针，
    # 豁免登记（真退役该项目侧约定时须连豁免一起动）
    "server/plugins/workbench/smoke/ki057-anchors.mjs",
    "integration/t260907-11/sc_wb_anchor_cross_project_faces.mjs",
    "integration/run_scenarios.py",  # 上条活约定的 intent 描述面（:629 引 server/dsh/reviews）
}
# 前缀级豁免（历史记录域，非活指针）
EXEMPT_PREFIXES = (
    "notes/",               # 历史票快照/账本/讨论纪要
    "integration/t260907-10/",  # 本场景族自身＋fixture 面（token 即被测对象）
)


def _exempt(rel, line):
    if rel in EXEMPT_FILES:
        return True
    if rel.startswith(EXEMPT_PREFIXES):
        return True
    # 回落链行三形态（工单⑤切法一，摘除票落地后随 marker 撤除）：
    #   ① engine-venv-compat 行级 marker（约定锚，补标记即豁免）；
    #   ② 票号锚 t260907-10（实现段回落注释自带）；
    #   ③ 探测对同行（新旧两路径同在——probe 循环/双认谓词的结构特征）。
    if "engine-venv-compat" in line or "t260907-10" in line:
        return True
    if RE_PLAIN.search(line) and "engine" in line and "temporal-poc" in line:
        return True
    if rel.startswith("docs/") and "退役" in line:
        return True
    return False


def _hit(line):
    return bool(RE_PLAIN.search(line) or RE_SEG_FWD.search(line)
                or RE_SEG_REV.search(line))


def scan():
    """返回 (真残留 [(rel, lineno, line)], 二进制跳过 [rel])。"""
    hits, binaries = [], []
    for dirpath, dirnames, filenames in os.walk(REPO):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, REPO)
            ext = os.path.splitext(fn)[1]
            if ext and ext not in TEXT_EXT:
                if not ext in (".png", ".jpg", ".ico", ".zstd", ".gif", ".woff",
                               ".woff2", ".ttf", ".pdf", ".icns"):
                    binaries.append(rel)
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for i, line in enumerate(f, 1):
                        if _hit(line) and not _exempt(rel, line):
                            hits.append((rel, i, line.strip()[:110]))
            except (OSError, UnicodeDecodeError):
                binaries.append(rel)
    return hits, binaries


def main():
    r = lib_naming.Rec()

    print("== A 五层逐项在位（锚目标树清单）")
    def has(rel, must_dir=False):
        p = os.path.join(REPO, rel)
        return os.path.isdir(p) if must_dir else os.path.exists(p)
    for rel in ("server/engine", "server/engine/client.py", "server/engine/worker.py",
                "server/engine/shared.py", "server/engine/agent_activities.py",
                "server/engine/base.py", "server/engine/dev_lane.py",
                "server/engine/tests"):
        r.check(has(rel, rel.endswith(("engine", "tests"))), "A 引擎层 %s" % rel)
    for name in ("ui", "workbench", "knowledge", "providers", "temporal-tools"):
        r.check(has("server/plugins/%s/package.json" % name),
                "A 插件层 server/plugins/%s（package.json）" % name)
    r.check(has("server/profile/cordis.yml"), "A 装配方 server/profile/cordis.yml")
    r.check(has("server/profile-headless", True), "A 装配方 server/profile-headless/")
    headless_patch = os.path.join(REPO, "server/profile-headless/cordis.patch.yml")
    r.check(os.path.islink(headless_patch)
            and os.path.realpath(headless_patch).endswith("server/profile/cordis.patch.yml"),
            "A headless patch 仍为指向 profile 真身的软链（两份同源机制锚）")
    for name in ("developer", "integration", "product-operation"):
        r.check(has("server/roles/%s.yml" % name), "A 角色层 server/roles/%s.yml" % name)
    for rel in ("server/model-routes.yaml", "server/ui-check", "server/tools/ticket.py",
                "server/tools/workflow.py", "server/tools/verify_lane.py",
                "server/tools/dispatcher_loop.py", "server/sandbar-tools.ts",
                "server/project-registry.ts", "server/headless-resume/node.ts",
                "server/workflows/dev-lane.yaml"):
        r.check(has(rel, rel == "server/ui-check"), "A 平移件/声明 %s" % rel)

    print("== B server/dsh 包装层退场")
    r.check(not os.path.exists(os.path.join(REPO, "server/dsh")),
            "B server/dsh 目录不存在")

    print("== C 全仓旧路径零残留（连写＋段式杂糅，列名豁免逐处归类）")
    hits, binaries = scan()
    r.check(not hits, "C 真残留 %d 处%s" % (
        len(hits), ("；首 8：" + " | ".join("%s:%d %s" % h for h in hits[:8])) if hits else ""))
    if binaries:
        print("  INFO 二进制/跳过 %d 个（列名不吞命中）：%s%s" % (
            len(binaries), ", ".join(binaries[:5]),
            " …" if len(binaries) > 5 else ""))

    print("== D 扫描器自证红绿")
    r.check(_hit('cmd: PY=server/dsh/temporal-poc/.venv/bin/python'),
            "D 连写旧路径样本被识别（红）")
    r.check(_hit('self.poc_dir = self.root / "server" / "dsh" / "engine"'),
            "D 段式杂糅样本被识别（红）〔实测漏网型〕")
    r.check(_hit("DIR = HERE.parent / 'dsh' / 'workflows'"),
            "D 段式杂糅样本·单引号被识别（红）")
    r.check(_exempt("x.py", 'LEGACY 旧路径  # engine-venv-compat 回落探测行'),
            "D marker 行豁免判定（engine-venv-compat→走豁免分支）")
    r.check(not _exempt("x.py", '旧路径读点无 marker 不豁免'),
            "D 无 marker 旧路径读点不豁免")
    # L10-allow: 本行是**反向样本字面量**（证明布局扫描器认得出「不带 --no-open 的 dsh 启动」），
    # 不是真启动点——故带标记豁免 L10。
    r.check(not RE_SEG_FWD.search('spawn("dsh", ["--profile", "suyou"])'),  # L10-allow: 反向样本字面量
            "D dsh CLI spawn（合法外部工具名）不误报（绿）")
    r.check(not _hit('fixtures 用 self.tmp / "dsh" 作 DSH_HOME（隔离目录名）'),
            "D DSH_HOME 型隔离目录名不误报（绿）")
    r.check(not _hit('docker services ["dsh", "temporal"]'),
            "D docker 服务名 dsh 不误报（绿）")

    # == D2 L10 --no-open 启动面闸机制自证（t260929-09：字面量盲区翻车）────────
    # 260929 宿主实报浏览器弹窗：真凶 bench 用变量二进制（dshCmd）＋ argv 带
    # --profile 且缺 --no-open，旧 L10 只认字面量二进制＝绿灯盲区。本节沿本文件反向样本
    # 惯例，证明机制化闸对**事故同形状**必红、对合规/非 dsh 面不误报。
    import lint_tests  # noqa: E402
    _gate = getattr(lint_tests, "_l10_launch_sites", None)
    if not callable(_gate):
        r.check(False, "D2 机制缝 lint_tests._l10_launch_sites 缺席（闸降级=盲区回潮面）")
    else:
        r.check(any("--no-open" not in argv for _ln, argv, _why in
                    _gate("spawn(dshCmd, ['--profile', 'x', '--port', '1'])")),  # L10-allow: 反向样本字面量
                "D2 变量二进制+argv --profile 缺 --no-open 被识别（红）〔260929 事故同形状〕")
        r.check(any("--no-open" not in argv for _ln, argv, _why in
                    _gate("spawn(binDsh, ['web', '--port', '1'])")),  # L10-allow: 反向样本字面量
                "D2 dsh 命名变量（无 --profile）缺 --no-open 被识别（红）")
        r.check(all("--no-open" in argv for _ln, argv, _why in
                    _gate("spawn(dshCmd, ['--profile', 'x', '--no-open'])")),  # L10-allow: 反向样本字面量
                "D2 同形状带 --no-open 不报（绿）")
        r.check(_gate("spawn('docker', ['logs', '-f', 'x'])") == [],  # L10-allow: 反向样本字面量
                "D2 非 dsh 二进制不误报（绿）")

    r.finish()


if __name__ == "__main__":
    main()
