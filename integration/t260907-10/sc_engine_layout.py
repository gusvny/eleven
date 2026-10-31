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
       - 文件级：server/admin.log（追加式审计流水不可改写）；〔CLAUDE.md 的写集外宿主
         merge 债已于 261012 清偿——宿主令更正目录节为 v6 真身，该豁免随之摘除，
         CLAUDE.md 现与全仓同判，再有残留即红〕；
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

Scope note (t261101-12). C judges the committed tree at the revision under
verification: git lists the files, and only those files are scanned. Untracked
runtime scratch (out/, .sandbar/, a temp dir, a per-lane worktree leftover, a
file that appears while the round runs) is not part of the delivered tree, so
it can not red this case. A tree with scratch only is green. If git can not
list the tree, the case reports ENV_FAIL: the tree can not be judged.

Rule ③ (probe pair) also covers a wrapped candidate list. The same fallback
tuple may break over two lines: the old path and the v6 path stay in one
candidate list, so neither line is a live pointer. A wrapped list needs both
paths; an old path alone is still a hit.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

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
    # （CLAUDE.md 豁免 261012 摘除：宿主令已把目录节更正为 v6 真身，债清、同判）
    # 回落契约专属 UT（断言载体：fixture 造旧路径＋「回落命中旧路径」断言，
    # token 即被测契约内容——沿 t260907-04 UT 豁免先例）
    "server/engine/tests/test_engine_venv_fallback.py",
    # 项目仓内 server/dsh/reviews=**活约定**（workbench node.ts:852
    # join(anchor.root,'server','dsh') 的审批落点，t260907-11 KI-057 锚定）；项目仓
    # 布局与引擎仓布局是两个域，v6 摊平只动了引擎仓——这四文件引用的是活指针，
    # 豁免登记（真退役该项目侧约定时须连豁免一起动）
    "server/plugins/workbench/smoke/ki057-anchors.mjs",
    # t261008 实报：同一活约定的第五个消费点（smoke/changes.mjs:230-231 读写
    # echo server/dsh/reviews/<工单id>.json），理由与上面三条逐字相同
    "server/plugins/workbench/smoke/changes.mjs",
    "integration/t260907-11/sc_wb_anchor_cross_project_faces.mjs",
    "integration/run_scenarios.py",  # 上条活约定的 intent 描述面（:629 引 server/dsh/reviews）
}
# 前缀级豁免（历史记录域，非活指针）
EXEMPT_PREFIXES = (
    "notes/",               # 历史票快照/账本/讨论纪要
    "integration/t260907-10/",  # 本场景族自身＋fixture 面（token 即被测对象）
    # t261008 实报：t261006-15（巡检页/期次归档那两张，已收口）的场景文件里存着迁移前的
    # 旧路径字面（server/dsh/temporal-poc/base/workflow.ts 等）。它们属本模块已声明的
    # 「历史票快照」类目、且不在活指针面上 ⇒ 按既有类目**具名归类**（不是放宽判据：
    # 活指针面仍照旧扫，前缀只覆盖这一张已收口票的资产）。
    "integration/t261006-15/",
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


# v6 target literals: the path a fallback probe reads FIRST (rule ③).
RE_V6_TARGET = re.compile(r"server/engine|[\"']server[\"']\s*/\s*[\"']engine[\"']")
# A wrapped candidate list continues while the line above ends with a comma.
_PROBE_LOOKBACK = 3


def _probe_pair_wrapped(lines, idx):
    """True when line idx sits in a candidate list that also names the v6 path.

    Rule ③ covers the one-line form. This covers the same structure wrapped
    over two or more lines:
        for cand in (REPO / "server/engine/.venv/bin/python",
                     REPO / "server/dsh/temporal-poc/.venv/bin/python"):
    The old path is a probe candidate, not a live pointer. Require an opener,
    a comma continuation above the hit, and the v6 path on ANOTHER line.
    """
    block = [lines[idx]]
    prev = idx - 1
    while prev >= 0 and idx - prev <= _PROBE_LOOKBACK:
        tail = lines[prev].rstrip()
        if not tail.endswith((",", "(", "[")):
            break
        block.insert(0, lines[prev])
        prev -= 1
        if tail.endswith(("(", "[")):
            break  # the candidate list opens on this line
    chain = block[:-1]
    if not chain:
        return False
    if not any(("(" in ln or "[" in ln) for ln in block):
        return False
    return any(RE_V6_TARGET.search(ln) for ln in chain)


def _scan_lines(rel, lines):
    """Hits in one file: [(rel, lineno, line)] after every exemption."""
    hits = []
    for i, line in enumerate(lines):
        if not _hit(line):
            continue
        if _exempt(rel, line):
            continue
        if _probe_pair_wrapped(lines, i):
            continue
        hits.append((rel, i + 1, line.strip()[:110]))
    return hits


# ---------------------------------------------------------------- scope ----
# A seconds-scale bound with a name. A local `git ls-files` read returns at
# once; the bound only stops a hung git, so the case never waits minutes.
_GIT_LIST_TIMEOUT_S = 60


def tracked_paths(root):
    """Tracked paths at the revision under verification (None = git unusable).

    The v6 layout claim is about committed content. Runtime scratch is not
    part of the tree under verification, so it can never red this case.
    """
    try:
        proc = subprocess.run(["git", "-C", root, "ls-files", "-z"],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              timeout=_GIT_LIST_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    raw = proc.stdout.decode("utf-8", "surrogateescape")
    return set(p for p in raw.split("\0") if p)


def scan(root=None, tracked=None):
    """Scan the tracked tree only.

    Returns (residue [(rel, lineno, line)], skipped binaries [rel],
    scratch [rel]). A path that is not tracked is scratch: it belongs to the
    run, not to the delivered tree, so it is counted and never scanned.
    """
    root = root or REPO
    if tracked is None:
        tracked = tracked_paths(root)
        if tracked is None:
            tracked = set()  # caller reports ENV_FAIL: no tree can be judged
    hits, binaries, scratch = [], [], []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn == ".git":
                continue  # a worktree root keeps .git as a file, not a dir
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, root)
            if rel not in tracked:
                scratch.append(rel)
                continue
            ext = os.path.splitext(fn)[1]
            if ext and ext not in TEXT_EXT:
                if not ext in (".png", ".jpg", ".ico", ".zstd", ".gif", ".woff",
                               ".woff2", ".ttf", ".pdf", ".icns"):
                    binaries.append(rel)
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    lines = f.read().splitlines()
            except (OSError, UnicodeDecodeError):
                binaries.append(rel)
                continue
            hits.extend(_scan_lines(rel, lines))
    return hits, binaries, scratch


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
    tracked = tracked_paths(REPO)
    if tracked is None:
        # The tree can not be judged: this is an environment red, not a pass.
        r.env_fail("git ls-files unusable in %s: the committed tree can not be "
                   "listed, so the layout claim can not be judged" % REPO)
        hits, binaries, scratch = [], [], []
    else:
        hits, binaries, scratch = scan(REPO, tracked)
        r.check(not hits, "C 真残留 %d 处%s" % (
            len(hits), ("；首 8：" + " | ".join("%s:%d %s" % h for h in hits[:8])) if hits else ""))
    if binaries:
        print("  INFO 二进制/跳过 %d 个（列名不吞命中）：%s%s" % (
            len(binaries), ", ".join(binaries[:5]),
            " …" if len(binaries) > 5 else ""))
    if scratch:
        print("  INFO 未跟踪/运行时暂存不在判据内 %d 个（t261101-12：判的是受控树）"
              "：%s%s" % (len(scratch), ", ".join(sorted(scratch)[:5]),
                          " …" if len(scratch) > 5 else ""))

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

    # == D3 wrapped candidate list (t261101-12): rule ③ spans two lines ──────
    # The measured red: a landed scenario file holds the fallback probe as a
    # wrapped tuple. The same structure on one line is exempt (rule ③), so the
    # wrapped form must be exempt too. An old path WITHOUT the v6 sibling in
    # one candidate list stays a hit.
    _wrapped = ["    for cand in (REPO / \"server/engine/.venv/bin/python\",",
                "                 REPO / \"server/dsh/temporal-poc/.venv/bin/python\"):"]
    r.check(_scan_lines("x.py", _wrapped) == [],
            "D3 跨行回落探测对（v6 在前、旧路径在后）豁免（绿）〔t261101-12 实测形态〕")
    _wrapped_open = ["    cands = (",
                     "        REPO / \"server/engine/bin\",",
                     "        REPO / \"server/dsh/engine/bin\",",
                     "    )"]
    r.check(_scan_lines("x.py", _wrapped_open) == [],
            "D3 跨行探测对（开括号独占一行，三行超链）豁免（绿）")
    _dangling = ['    load("server/engine/shared.py")',
                '    load("server/dsh/engine/base.py")']
    r.check(len(_scan_lines("x.py", _dangling)) == 1,
            "D3 旧路径无 v6 同候选表配对仍是残留（红）〔不因邻行有 server/engine 放行〕")
    _far = ['    load("server/engine/shared.py")',
            "",
            "",
            "",
            "",
            '    load("server/dsh/engine/base.py")']
    r.check(len(_scan_lines("x.py", _far)) == 1,
            "D3 超窗（v6 行在窗口外）仍是残留（红）")

    # == D4 scope (t261101-12): the scan judges the tracked tree only ───────
    # Runtime scratch must never red this case, and the scan must still bite on
    # a tracked file. Both legs run in a temp tree; the real tree is untouched.
    _tmp = tempfile.mkdtemp(prefix="sc_layout_scope_")
    try:
        with open(os.path.join(_tmp, "live.py"), "w", encoding="utf-8") as f:
            f.write('PY = "server/dsh/temporal-poc/.venv/bin/python"\n')
        with open(os.path.join(_tmp, "scratch.py"), "w", encoding="utf-8") as f:
            f.write('OUT = "server/dsh/temporal-poc/out"\n')
        s_hits, _s_bin, s_scratch = scan(_tmp, {"live.py"})
        r.check([h[0] for h in s_hits] == ["live.py"],
                "D4 受控文件仍被扫到（红）、未跟踪暂存不扫（绿）：hits=%s scratch=%s"
                % ([h[0] for h in s_hits], sorted(s_scratch)))
        r.check(sorted(s_scratch) == ["scratch.py"],
                "D4 未跟踪文件逐个点名计入暂存（不静默吞）")
        only_scratch = os.path.join(_tmp, "scratch_only")
        os.makedirs(only_scratch)
        with open(os.path.join(only_scratch, "leftover.py"), "w", encoding="utf-8") as f:
            f.write('LEGACY = "server/dsh/engine/base.py"\n')
        r.check(scan(only_scratch, set())[0] == [],
                "D4 只有暂存的树全绿＝不需要干净树（t261101-12 口径）")
    finally:
        shutil.rmtree(_tmp, ignore_errors=True)

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
