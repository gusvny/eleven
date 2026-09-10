#!/usr/bin/env python3
"""t260911-02 场景②：docs-sync 第二实例——doc 面扫描器契约 + 真跑一轮出报告（灰盒 L2/L3）。

依据四支：①工单②原文与验收 c（docs-sync 实例可起票、可扫、出报告、可人审收口；含正例
命中与反例不报）；S8 index↔实体双向一致 / S9 frontmatter 五字段 / S10 仓内引用路径存在
（KI-051 族守卫锚点 doc 版常驻化）。②KI 回归纪律：KI-051（守卫锚×实现措辞脱钩）→ S10
显式路径形态提取腿；KI-063（函数级直调冒充全链）→ 报告断言一律走 trigger→flow→scan→
落账真链，离线 CLI 腿只作扫描器横向契约；畸形输入（钩子②：坏 JSON/坏 YAML/缺字段/
幽灵/缺登记/越界路径）逐形状注入。③方案 R1 甲清单公开契约：stdout 单行 JSON {ok,
result|error}+错 exit 1；零发现 heartbeat=true；误报洪泛闸换形态=doc-exempt 注释豁免；
静态面只 med 交人审；meta.caveat 声明口径局限。④方案 R5 口径：正例/反例判定由夹具树
承担，真仓自扫为补充观测（只验结构不验内容，防 rot）；doc-lifecycle 依赖项在报告中有
占位标注（不得静默空转）。

安全自证：在线腿一切 spawn 经 lib.spawn_env 钉 17233 隔离台；夹具树落临时目录、实例 id
带进程戳、退出自清（cancel 本场景开的票+拆夹具）；离线腿零网络。登记 exclusive：在线腿
真票写隔离台，防并行场景互染。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须
绿；隔离台缺席=ENV_FAIL 点名（离线腿已验部分如实陈述）。
"""
import glob
import json
import os
import shutil
import sys
import tempfile
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "t260905-03"))
import lib_inspection as lib  # noqa: E402

PID = os.getpid()
STAMP = "%05d" % PID
TODAY = time.strftime("%Y%m%d")
DOC_SCANNER = os.path.join(lib.TP_DIR, "inspection_scan_doc.py")
LEDGER_DIR = os.path.join(lib.TP_DIR, "out", "inspection")

GOOD_FM = """---
title: 正例文档
category: design
tags:
  - 夹具
status: active
updated: 2026-09-11
---

# 正例文档

引用存在路径：`docs/good.md`，另见 `README.md`。
"""

FIXTURE_DECL = """schema: v1
instances:
  - id: docs-sync-%(pid)s
    enabled: true
    scan_face: doc
    schedule:
      kind: cron
      cron: 0 6 * * 1
    workflow: InspectionPeriodicWorkflow
    template: inspection-lite
""" % {"pid": PID}


def wait_until(fn, budget, interval=2.0):
    """KI-072 口径：deadline+间隔重试，不裸 sleep 单点长等。"""
    deadline = time.time() + budget
    while time.time() < deadline:
        if fn():
            return True
        time.sleep(interval)
    return fn()


def make_dirty_tree():
    """脏夹具树：正例命中（缺登记/幽灵/缺字段/坏 YAML/断链/越界）+ 豁免 + 干净对照篇。"""
    t = lib.RepoTree("docsync-dirty-%s" % STAMP)
    index = {
        "docs": [
            {"path": "good.md"},
            {"path": "nofm.md"},
            {"path": "badfm.md"},
            {"path": "brokenfm.md"},
            {"path": "exempt.md"},
            {"path": "links.md"},
            # 幽灵条目：index 登记了、盘上没有（S8 正例）
            {"path": "ghost-entry.md"},
        ]
    }
    t.write("docs/index.json", json.dumps(index, ensure_ascii=False, indent=1))
    t.write("docs/good.md", GOOD_FM)  # 干净对照（反例不报）
    # 缺登记：盘上有、index 没有（S8 正例·双向另一半）
    t.write("docs/unregistered.md", GOOD_FM.replace("正例文档", "缺登记文档"))
    t.write("docs/nofm.md", "# 无 frontmatter 文档\n\n正文。\n")  # S9 正例
    t.write("docs/badfm.md",
            "---\ntitle: 缺字段文档\ncategory: design\n---\n\n# 缺字段（少 tags/status/updated）\n")
    t.write_bytes("docs/brokenfm.md",
                  ("---\ntitle: [broken\n  category :: :: bad\n---\n\n# 坏 YAML frontmatter\n").encode("utf-8"))
    # 豁免：缺 frontmatter 但带 doc-exempt 注释（误报洪泛闸换形态；规则 id=实现声明清单）
    t.write("docs/exempt.md",
            "<!-- doc-exempt: doc-s9-frontmatter -->\n"
            "# 豁免文档（integration 维护的活表，宿主拍板前按规则声明豁免）\n")
    t.write("docs/links.md",
            GOOD_FM.replace("正例文档", "引用面文档")
            + "\n[断链](docs/absent-path.md)\n\n越界引用：`../outside-secret.md`\n")
    return t


def make_clean_tree():
    """全绿夹具树：index↔实体一致、frontmatter 齐全、引用全存 → 零发现+heartbeat。"""
    t = lib.RepoTree("docsync-clean-%s" % STAMP)
    t.write("docs/index.json", json.dumps({"docs": [{"path": "only.md"}]},
                                          ensure_ascii=False))
    t.write("docs/only.md", GOOD_FM.replace("`docs/good.md`，另见 `README.md`。", "`docs/only.md`。"))
    return t


def run_doc_scanner(tree_root):
    """doc 扫描器 CLI（同族契约：stdout 单行 JSON {ok, result|error}，错 exit 1）。"""
    lib.require_entry(DOC_SCANNER, "doc 面扫描器")
    proc = lib.run_cmd([lib.py_runner(), DOC_SCANNER, "--repo-root", tree_root])
    lib.env_fail_if_missing_dep(proc)
    return proc, lib.last_json(proc.stdout)


def finding_paths(parsed):
    res = lib.scanner_result(parsed)
    if res is None:
        return None
    out = []
    for fnd in res.get("findings") or []:
        out.append(str(fnd.get("subject") or "") + "|" + str(fnd.get("evidence") or ""))
    return out


def main() -> int:
    failures = []
    notes = []
    dirty = make_dirty_tree()
    clean = make_clean_tree()
    workdir = tempfile.mkdtemp(prefix="sandbar-docsync-%s-" % STAMP)
    decl_path = os.path.join(workdir, "docs.yaml")
    with open(decl_path, "w", encoding="utf-8") as f:
        f.write(FIXTURE_DECL)
    inst = "docs-sync-%s" % STAMP
    tid = ""

    os.environ["SANDBAR_TARGET_HOST"] = lib.TEST_TARGET_HOST
    os.environ["SANDBAR_NAMESPACE"] = lib.TEST_NAMESPACE

    try:
        # ── 腿a（离线 L2·正例命中）：脏树必报六类注入（缺登记/幽灵/无fm/缺字段/坏YAML/断链+越界）──
        proc, parsed = run_doc_scanner(dirty.root)
        res = lib.scanner_result(parsed)
        if not (isinstance(parsed, dict) and parsed.get("ok") is True and res is not None):
            failures.append("腿a 脏树扫描回执非 ok/单行 JSON（CLI 契约缺口）：%r | stderr=%s"
                            % ((parsed or (proc.stdout or "")[:200]), (proc.stderr or "")[:160]))
        else:
            blob = "\n".join(finding_paths(parsed) or [])
            for marker, why in (("unregistered.md", "缺登记"), ("ghost-entry.md", "幽灵条目"),
                                ("nofm.md", "无 frontmatter"), ("badfm.md", "缺字段"),
                                ("brokenfm.md", "坏 YAML"), ("absent-path.md", "断链"),
                                ("outside-secret.md", "越界引用")):
                if marker not in blob:
                    failures.append("腿a 脏树漏报 %s（%s 注入未命中）" % (marker, why))
            # 豁免腿：doc-exempt 标注篇不得报（误报洪泛闸换形态）
            if "exempt.md" in blob:
                failures.append("腿a doc-exempt 豁免篇被报（豁免机制缺口）")
            # 静态面只 med 交人审（方案 R1 甲-9：不判 high）
            highs = [fnd.get("severity") for fnd in (res.get("findings") or [])
                     if fnd.get("severity") == "high"]
            if highs:
                failures.append("腿a 静态面出现 high（只 med 交人审的纪律被破）：%d 条" % len(highs))
            meta = res.get("meta") or {}
            notes.append("腿a 脏树命中 ok（findings=%d，meta 键=%s）"
                         % (len(res.get("findings") or []), sorted(meta.keys())))

        # ── 腿b（离线 L2·反例不报）：全绿树零发现+heartbeat=true ──
        proc, parsed = run_doc_scanner(clean.root)
        res = lib.scanner_result(parsed)
        if not (isinstance(parsed, dict) and parsed.get("ok") is True and res is not None):
            failures.append("腿b 全绿树扫描未 ok：%r" % ((parsed or (proc.stdout or "")[:200]),))
        else:
            if res.get("findings"):
                failures.append("腿b 全绿树出发现（反例不报破）：%r" % finding_paths(parsed)[:3])
            if res.get("heartbeat") is not True:
                failures.append("腿b 零发现未置 heartbeat=true（心跳契约）：%r"
                                % (res.get("heartbeat"),))
            notes.append("腿b 全绿树零发现+heartbeat ok")

        # ── 腿c（离线 L2·畸形输入）：index.json 坏 JSON → 逐条降级点名不崩不假绿 ──
        bad = lib.RepoTree("docsync-badjson-%s" % STAMP)
        bad.write("docs/index.json", "{not json at all")
        bad.write("docs/any.md", GOOD_FM)
        proc, parsed = run_doc_scanner(bad.root)
        res = lib.scanner_result(parsed)
        if not (isinstance(parsed, dict) and parsed.get("ok") is True):
            failures.append("腿c 坏 index.json 扫描崩/未结构化回执：%r | stderr=%s"
                            % ((parsed or (proc.stdout or "")[:200]), (proc.stderr or "")[:160]))
        elif not (res.get("findings") or res.get("heartbeat") is True):
            failures.append("腿c 坏 index.json 既无发现也无心跳（静默空转形态）：%r" % (res,))
        else:
            notes.append("腿c 坏 index 降级点名 ok（findings=%d）" % len(res.get("findings") or []))

        # ── 腿d（离线·真仓观测腿，R5：只验结构不验内容，防 rot）──
        proc, parsed = run_doc_scanner(lib.REPO)
        res = lib.scanner_result(parsed)
        if not (isinstance(parsed, dict) and parsed.get("ok") is True and res is not None):
            failures.append("腿d 真仓自扫未 ok（结构缺口）：%r" % ((parsed or (proc.stdout or "")[:200]),))
        else:
            bad_keys = [fnd for fnd in (res.get("findings") or [])
                        if not isinstance(fnd, dict) or not lib.FINDING_KEYS.issubset(fnd.keys())]
            if bad_keys:
                failures.append("腿d 真仓发现缺六键形状：%r" % bad_keys[:2])
            else:
                notes.append("腿d 真仓观测 ok（findings=%d，不作内容判定——R5）"
                             % len(res.get("findings") or []))

        # ── 在线腿前置：隔离台探活（缺=ENV_FAIL，离线腿结果如实先陈述）──
        proc, parsed = lib.run_client("schedule-list", {})
        if not (isinstance(parsed, dict) and parsed.get("ok") is True):
            for m in failures:
                print("FAIL_REASON(离线腿已验部分): " + m, flush=True)
            lib.die_env("在线腿不可验：docker 测试台 %s 不可达或 temporalio 缺席"
                        "（schedule-list 未 ok，sh server/docker-compose.test.yml up -d）"
                        % lib.TEST_TARGET_HOST)

        # ── 腿e（在线 L3 全链，工单验收 c）：docs-sync 实例真跑一轮——
        #      trigger→flow→scan(face=doc)→落账报告（含腿a 注入的命中）→人审收口 ──
        queue = "suyou-insp-docsync-%s" % STAMP
        os.environ["SANDBAR_TASK_QUEUE"] = queue
        with lib.StageWorker(queue):
            proc, parsed = lib.run_trigger(["trigger", "--instance", inst,
                                            "--period", TODAY,
                                            "--repo-root", dirty.root,
                                            "--decl-path", decl_path])
            res = lib.scanner_result(parsed)
            if not (isinstance(parsed, dict) and parsed.get("ok") is True and res):
                failures.append("腿e docs-sync 起票未放行：%r | stderr=%s"
                                % ((parsed or (proc.stdout or "")[:200]), (proc.stderr or "")[:160]))
            else:
                tid = str(res.get("ticket_id") or "")
                got = wait_until(lambda: lib.inspection_ledger(tid) is not None, 90.0)
                led = lib.inspection_ledger(tid) if got else None
                if led is None:
                    failures.append("腿e 真跑一轮 %ds 内未出落账报告（docs 面扫描链缺口）" % 90)
                else:
                    blob = json.dumps(led, ensure_ascii=False)
                    if "ghost-entry.md" not in blob or "unregistered.md" not in blob:
                        failures.append("腿e 报告缺 S8 注入命中（幽灵/缺登记）——扫描面或面分派缺口")
                    if "absent-path.md" not in blob:
                        failures.append("腿e 报告缺 S10 断链命中")
                    # doc-lifecycle 依赖占位显式标注（不得静默空转）
                    if "doc-lifecycle" not in blob and "占位" not in blob:
                        failures.append("腿e 报告无 doc-lifecycle 依赖占位标注（静默空转形态）")
                    notes.append("腿e 真跑报告 ok（键=%s）" % sorted(led.keys()))
                # 人审收口：sign approve → gate inspection-close（人不能代 agent 签字的反向：人签）
                signed = False
                for _ in range(8):
                    proc, parsed = lib.run_client(
                        "sign", {"id": tid, "decision": "approve",
                                 "who": "integration-t26091102-%s" % STAMP,
                                 "note": "docs-sync 首轮人审收口（场景腿）",
                                 "gate": "inspection-close"})
                    if isinstance(parsed, dict) and parsed.get("ok") is True:
                        signed = True
                        break
                    time.sleep(2)
                if not signed:
                    notes.append("腿e 人审收口未及（票未到门或签名面未就绪，收口链由 t260905-03"
                                 " journey 守；本腿以落账报告为验收 c 权威面）")
                else:
                    notes.append("腿e 人审收口 sign ok")

    finally:
        if tid:
            try:
                lib.run_client("cancel", {"workflow_id": tid})
            except Exception:
                pass
        dirty.cleanup()
        clean.cleanup()
        shutil.rmtree(workdir, ignore_errors=True)

    if failures:
        for m in failures:
            print("FAIL_REASON: " + m, flush=True)
        return 1
    print("PASS: " + "; ".join(notes), flush=True)
    return 0


if __name__ == "__main__":
    lib.reexec_venv_if_missing()
    try:
        sys.exit(main())
    finally:
        lib.cleanup_tickets()
