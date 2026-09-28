#!/usr/bin/env python3
"""sc_naming_residue_fulltext.py —— 命名迁移②收口：旧命名 token 全量残留清点（t260907-05，灰盒 L3）。

intent（守护的用户可感知契约 / 工单验收①的独立机器重演）：
- 宿主令 260907 命名表插件面落地后，全仓受控面不再以「suyou-*」指称插件与工单台——
  读者在代码、脚本、场景、锁文件里看到的插件名只有 sandbar-* 一种真源；旧名残留
  =文档/脚本指向一个已死的名字（用户按残留走必 404），且意味着替换有漏网面。
- 不动面守卫：非本票面的既有标识（/sandbar-admin/ 前缀、project-registry.ts、
  dsh-profile-suyou 包名）必须原样在位——机械替换最常见的对抗事故是「顺手多改」，
  把后续票的面提前污染。按 doc-guard G6 先例钉现状语义：后续票落地时随其语义同步改本子用例。
- docs/ 定稿库已知漂移清单封口：本票不改 docs/（写集外），但 docs 命中必须 ⊆ 已声明
  的遗留票清单（ticket-workflow-console-design.md / knowledge-base-design.md / README.md / build_index.py）——
  清单外新命中=替换面外溢或新写文件带病，红。

与既有资产 intent 区别（防 intent 级重复）：
- t260903-12/sc_merge_checks_pairs 守 bundle 新鲜度护栏的配置对齐；本条守命名真源
  唯一性（迁移收口），与配置护栏不同面。
- workbench/tests 的 L1 用例（developer 面）守单插件行为；本条守全仓文本面收口，
  developer 替换脚本漏一个目录本条即红。

high-level steps：
  1. os.walk 全仓 server/ + integration/ 纯文本扫描七个旧 token（六包名+suyou-tools），
     无 include 白名单（v1 方案白名单漏 tsx/py/cjs 的教训——全后缀扫描）；豁免列名：
     integration/t260903-12/acceptance-walkthrough-gen0.md（历史验收记录）；
  2. docs/ 扫描同 token 集，命中文件 ⊆ 已声明遗留票清单；
  3. 正名在位：六个插件 package.json name 全部 sandbar-*；五份 package-lock.json
     顶层与 packages[""] 两处 name 同步；
  4. 不动面原样在位：/sandbar-admin/ 仍在 ui/node.ts、project-registry.ts 文件在、
     两 profile 包名仍 dsh-profile-suyou*。

Hermetic：纯文件读，零端口零网络零 spawn，不碰 3099。cwd=仓库根；秒级。
三态契约：无环境依赖（stdlib 文件读）——不设 ENV_FAIL 路径；末行 SUMMARY pass=N fail=N；
exit 1 iff fail>0。实现段落地前红属预期；arbitrate/merge 期必须绿。
"""
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 七个旧 token：六个插件包名 + suyou-tools（文件名/内部标识）。全字面扫描，
# 不带 --include 白名单——ts/tsx/js/cjs/mjs/py/md/yml/json 一律过目。
TOKENS = [
    "suyou-workbench", "suyou-admin-ui", "suyou-knowledge",
    "suyou-providers", "suyou-temporal-tools", "suyou-ui-check", "suyou-tools",
]
# server/integration 范围内的历史材料豁免（列名制——活文档不豁免）。
# t260907-05 守卫场景族自身也在列：它们是「旧名必不存在」断言的针脚载体
# （TOKENS/前缀字面量写在断言里），非产品面——不豁免则本场景自指永红。
# server/admin.log 为追加式运行审计流水（run_id 审计真源，不可改写）：闸口回执会
# 逐字引用开票 write_set 字面（含已认定笔误的旧目录名）——历史记录非活指针，豁免；
# 活文档（代码/README/docs）一律不豁免。
EXEMPT_SERVER_INTEG = {
    "integration/t260903-12/acceptance-walkthrough-gen0.md",
    "integration/t260907-05/sc_naming_residue_fulltext.py",
    "integration/t260907-05/sc_profile_farm_sandbar_links.py",
    "integration/t260907-05/sc_workbench_route_renamed_serves.mjs",
    # t260907-04 守卫自身（断言载体：PLUGIN_REF_RE 定义的不动面 token 即被测对象；
    # 与上三行同族——04/05 两票并行落地后才在 main 汇合互见，-05 出闸时未见此文件，
    # 跨票盲区补账，t260907-10 arbitrate gen4）
    "integration/t260907-04/sc_naming_grep_assert.py",
    "server/admin.log",
}
# 运行产物根（git 忽略目录：server/engine/.gitignore 忽略 data/、根 .gitignore 忽略 out/）
# ——里面是每轮运行新增的日志与巡检输出，历史记录非活指针，与 server/admin.log 同族。
# **按目录根判定、不逐文件列名**：列名制必被下一轮新文件名打穿（260922 实证：命中
# worker-t2609*.log 与 out/inspection/*.json，文件天天新增）。边界：仅此两个运行产物根；
# 受跟踪面（含泳道新写文件、活文档）一律不豁免——收口口径未放宽，只把「运行产物」与
# 「仓库内容」分开。改这条锚点要来 main 侧（共享守卫期望值纪律）。
EXEMPT_RUNTIME_ROOTS = (
    "server/engine/data/",
    "server/engine/out/",
)


def _exempt(rel):
    """豁免判定单点：历史材料列名 + 运行产物根。"""
    return rel in EXEMPT_SERVER_INTEG or any(
        rel.startswith(r) for r in EXEMPT_RUNTIME_ROOTS)
# docs/ 已声明遗留票清单（本票不改 docs，命中封口在此清单内）。
LEGACY_DOCS_ALLOW = {
    "docs/design/ticket-workflow-console-design.md",
    "docs/design/knowledge-base-design.md",
    "docs/README.md",
    "docs/scripts/build_index.py",
    # t260907-05 消解轮随 main 带入：50 行「/suyou-workbench/ 前缀＝发布前置债，随专门
    # 专门迁移票处置」的债描述＋223 行 sandbar-*/suyou-* 迁移对照表——均为债陈述/沿革
    # 语境非现行调用契约；docs/ 写集外不改，追加进 docs 遗留票清单（清单外新命中仍红）。
    "docs/design/sandbar-distribution-v1.md",
}
PLUGINS = ["workbench", "ui", "knowledge", "providers", "temporal-tools", "ui-check"]
EXPECTED_NAME = {p: "sandbar-" + n for p, n in [
    ("workbench", "workbench"), ("ui", "admin-ui"), ("knowledge", "knowledge"),
    ("providers", "providers"), ("temporal-tools", "temporal-tools"),
    ("ui-check", "ui-check"),
]}
LOCKS = ["workbench", "ui", "knowledge", "providers", "ui-check"]  # temporal-tools 无 lock（实测无 dev deps 亦有 lock？按在场者断言）

passed, failed = 0, 0


def check(cond, label):
    global passed, failed
    if cond:
        passed += 1
        print("  ok   %s" % label)
    else:
        failed += 1
        print("  FAIL %s" % label)


def scan_tokens(rel_root):
    """返回 {relpath: set(token)}——文本可解码文件里的旧 token 命中面。"""
    hits = {}
    root = os.path.join(REPO, rel_root)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, REPO)
            if _exempt(rel):
                continue
            try:
                with open(full, "rb") as f:
                    text = f.read().decode("utf-8")
            except (UnicodeDecodeError, OSError):
                continue  # 二进制/不可读（截图等）不在文本收口面
            found = {t for t in TOKENS if t in text}
            if found:
                hits[rel] = found
    return hits


def main():
    print("== 1. server/ + integration/ 旧 token 零残留（全后缀，豁免列名 %d 件 + 运行产物根 %d 个）"
          % (len(EXEMPT_SERVER_INTEG), len(EXEMPT_RUNTIME_ROOTS)))
    hits = {}
    hits.update(scan_tokens("server"))
    hits.update(scan_tokens("integration"))
    check(not hits, "server/integration 零旧 token 残留" + ("" if not hits
          else "——命中: " + "; ".join("%s{%s}" % (r, ",".join(sorted(t))) for r, t in sorted(hits.items())[:8])))

    print("== 2. docs/ 命中封口在已声明遗留票清单内")
    docs_hits = scan_tokens("docs")
    stray = sorted(set(docs_hits) - LEGACY_DOCS_ALLOW)
    check(not stray, "docs 命中 ⊆ 遗留清单{%s}" % ", ".join(sorted(LEGACY_DOCS_ALLOW))
          + ("" if not stray else "——清单外: %s" % stray))

    print("== 3. 六插件 package.json 正名在位")
    PLUG_LAYER = {"ui-check": ""}  # ui-check 在 server/ 直下（v6 未入 plugins 层）
    for plug, want in EXPECTED_NAME.items():
        pj = os.path.join(REPO, "server", PLUG_LAYER.get(plug, "plugins"), plug,
                          "package.json")
        try:
            with open(pj, "r", encoding="utf-8") as f:
                name = json.load(f).get("name")
        except (OSError, ValueError):
            name = None
        check(name == want, "%s name=%s" % (plug, want))

    print("== 4. package-lock name 双处同步（在场者）")
    for plug in LOCKS:
        lock_path = os.path.join(REPO, "server", PLUG_LAYER.get(plug, "plugins"),
                                 plug, "package-lock.json")
        if not os.path.isfile(lock_path):
            check(False, "%s package-lock.json 在场" % plug)
            continue
        try:
            with open(lock_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            top = data.get("name")
            inner = (data.get("packages") or {}).get("", {}).get("name")
        except (OSError, ValueError):
            top = inner = None
        want = EXPECTED_NAME[plug]
        check(top == want and inner == want,
              "%s lock name 顶=%s/内=%s 均 %s" % (plug, top, inner, want))

    print("== 5. 不动面原样在位（现状语义钉死，后续票随其语义同步改本子用例）")
    ui_node = os.path.join(REPO, "server", "plugins", "ui", "node.ts")
    try:
        with open(ui_node, "r", encoding="utf-8") as f:
            ui_text = f.read()
        check("/sandbar-admin/" in ui_text, "/sandbar-admin/ 前缀仍在 ui/node.ts（非本票面）")
    except OSError:
        check(False, "ui/node.ts 可读")
    check(os.path.isfile(os.path.join(REPO, "server", "project-registry.ts")),
          "server/project-registry.ts 仍在（非本票面）")
    for prof in ("profile", "profile-headless"):
        pj = os.path.join(REPO, "server", prof, "package.json")
        try:
            with open(pj, "r", encoding="utf-8") as f:
                name = json.load(f).get("name", "")
        except (OSError, ValueError):
            name = ""
        check(name.startswith("dsh-profile-suyou"),
              "%s 包名仍 %s（非本票面）" % (prof, name or "<缺>"))

    print("SUMMARY pass=%d fail=%d" % (passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
