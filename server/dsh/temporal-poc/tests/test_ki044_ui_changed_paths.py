"""KI-044 根修（t260904-13）：UI 票判定换 diff 源——共享谓词 ui_changed_paths。

覆盖（零 Temporal server / 零模型 / 零网络，临时 git 仓自足）：
  纯函数：match_ui_paths 前缀命中/精确文件/去重/未命中/畸形输入；is_ui_write_set 委托等价。
  diff 源：_ui_diff_paths 真跑 git——t260904-05 复现（粗目录声明 + 实际改 lib 产物 →
          旧口径漏、新谓词命中）；纯引擎改动 → 空；坏基线 fail-closed。
  activity：ui_changed_paths 真跑（merge-base + diff 命中 / 不存在分支 fail-closed）。
  装配级：merge_check 3.6——diff 命中 UI 且无 png → 该项红；有 png → 绿；
          纯引擎票 → 不出截图项（不误伤）；detail 带「按 diff 判定」与命中路径。

消费外部输入的畸形用例（岗位纪律）：非列表/None/非字符串元素/绝对路径/../尾斜杠/
坏 ref/不存在的分支，全部桩内复现，不靠真外部源。
"""
import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path

POC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC))

import agent_activities  # noqa: E402
from shared import (  # noqa: E402
    UI_EVIDENCE_DIR,
    MergeCheckArgs,
    UiChangedPathsArgs,
    is_ui_write_set,
    match_ui_paths,
)

STUB_ADMIN = """#!/usr/bin/env python3
\"\"\"测试桩：verify_lane 恒绿（本票只验 UI 闸装配；verify_lane 语义另有专测）。\"\"\"
import json
import sys
sys.stdout.write(json.dumps(
    {"ok": True, "result": {"green": True, "exit_code": 0, "red_count": 0}}))
"""


def _git(*args, cwd):
    p = subprocess.run(["git", "-c", "core.quotepath=false"] + list(args),
                       cwd=str(cwd), capture_output=True, text=True)
    assert p.returncode == 0, "git %s 失败: %s" % (" ".join(args), p.stderr)
    return p.stdout.strip()


def build_lane_repo(prefix="t260904-13-ut-"):
    """临时仓（生产布局：<tmp> 是仓根，<tmp>/.lane/t1 是 `git worktree add` 出来的
    泳道检出 → _lane_repo_root 自锚 <tmp>，diff 路径仓相对=泳道相对）。

    返回 (repo, wt, g)：repo=仓库根（main）；wt=泳道 worktree（已检出 lane 分支，
    兼作 merge_check 的 worktree 入参与脏检查 pathspec 根）；g(*args, cwd=wt)=断言式
    git 快捷方式。已就绪：main 初始 commit（base.txt）。用完 shutil.rmtree。"""
    import shutil
    tmp = Path(tempfile.mkdtemp(prefix=prefix))
    _git("init", "-b", "main", cwd=tmp)
    _git("config", "user.email", "ut@example.com", cwd=tmp)
    _git("config", "user.name", "ut", cwd=tmp)
    (tmp / "base.txt").write_text("base\n", encoding="utf-8")
    _git("add", "-A", cwd=tmp)
    _git("commit", "-m", "base", cwd=tmp)
    _git("worktree", "add", ".lane/t1", "-b", "lane", cwd=tmp)
    wt = tmp / ".lane" / "t1"

    def g(*args, cwd=None):
        return _git(*args, cwd=cwd or wt)
    g.rmtree = shutil.rmtree  # type: ignore[attr-defined]
    return tmp, wt, g


def lane_commit(wt, g, relpath, content):
    """在 lane 分支上落一个文件的改动并 commit（调用方负责先 checkout lane）。"""
    f = wt / relpath
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")
    g("add", "-A")
    g("commit", "-m", "lane: %s" % relpath)


def ui_items(checks):
    """从 merge_check 回执里挑出 UI 截图证据项。"""
    return [c for c in checks if c.get("item", "").startswith("UI 截图证据")]


def declare_ui_evidence(wt, g, dirs=("server/dsh/workbench/lib/",),
                        raw=None):
    """泳道 verify.yaml 写 ui_evidence 声明并 commit（merge_check 工作区干净闸要求
    声明已提交；schema: v1 必带——verify_lane 读到 verify.yaml 会整卷结构校验，
    缺 schema=版本不支持整道红，会污染被测项）。raw 非 None 时原样写入（畸形态用）。"""
    f = wt / "verify.yaml"
    if raw is not None:
        f.write_text(raw, encoding="utf-8")
    else:
        lines = ["schema: v1", "ui_evidence:", "  dirs:"]
        lines += ["    - %s" % d for d in dirs]
        f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    g("add", "-A")
    g("commit", "-m", "lane: ui_evidence 声明")


# ---------- 纯函数：match_ui_paths / is_ui_write_set ----------

def test_match_ui_paths_hits():
    assert match_ui_paths(["server/dsh/workbench/src/client/App.tsx"]) == \
        ["server/dsh/workbench/src/client/App.tsx"]
    assert match_ui_paths(["server/dsh/workbench/lib/workbench.js"]) == \
        ["server/dsh/workbench/lib/workbench.js"]
    assert match_ui_paths(["server/dsh/providers/src/client/a.ts"]) == \
        ["server/dsh/providers/src/client/a.ts"]
    assert match_ui_paths(["app/src/main.ts"]) == ["app/src/main.ts"]
    assert match_ui_paths(["app/index.html"]) == ["app/index.html"]
    assert match_ui_paths(["app/src"]) == ["app/src"]          # 目录前缀本身
    assert match_ui_paths(["app/src/"]) == ["app/src/"]        # 尾斜杠形态（diff 不会产出，容错不误杀）
    assert match_ui_paths(["server/dsh/workbench/src/client/a.tsx",
                           "server/dsh/workbench/lib/b.js"]) == [
        "server/dsh/workbench/src/client/a.tsx", "server/dsh/workbench/lib/b.js"]


def test_match_ui_paths_miss_and_dedupe():
    assert match_ui_paths(["server/dsh/workbench/src/server/main.py"]) == []  # workbench 服务端
    assert match_ui_paths(["server/dsh/temporal-poc/shared.py"]) == []        # 纯引擎
    assert match_ui_paths(["app/docs/readme.md"]) == []                       # app/ 非 src 前缀
    # 精确文件条目走字符串 startswith 语义（历史行为保留：子路径后缀也算命中）；
    # 收紧成路径边界匹配属口径变更，随 UI_WRITE_PREFIXES 专门票处置
    assert match_ui_paths(["app/index.html.bak"]) == ["app/index.html.bak"]
    # 命中保序去重
    assert match_ui_paths(["app/src/b.ts", "app/src/a.ts", "app/src/b.ts"]) == \
        ["app/src/b.ts", "app/src/a.ts"]


def test_match_ui_paths_malformed_inputs():
    assert match_ui_paths(None) == []
    assert match_ui_paths("") == []
    assert match_ui_paths(42) == []
    assert match_ui_paths("app/src/main.ts") == []          # 字符串非列表 → 空清单
    assert match_ui_paths([None, 123, True, ""]) == []      # 非字符串元素全忽略
    assert match_ui_paths(["/abs/app/src/main.ts"]) == []   # 绝对路径不吃前缀
    assert match_ui_paths(["../app/src/main.ts"]) == []     # 越界路径不吃前缀
    assert match_ui_paths(["  app/src/main.ts  "]) == ["app/src/main.ts"]  # strip 后命中
    assert match_ui_paths([]) == []


def test_is_ui_write_set_delegates_and_keeps_declaration_semantics():
    # 委托等价：细粒度 UI 文件命中
    assert is_ui_write_set(["server/dsh/workbench/lib/x.js"]) is True
    assert is_ui_write_set(["  app/src/main.ts  "]) is True
    assert is_ui_write_set([]) is False
    assert is_ui_write_set(None) is False
    assert is_ui_write_set([None, 123]) is False
    # KI-044 实锤口径保留：粗目录声明不命中（这正是本票把判定换 diff 源的原因）
    assert is_ui_write_set(["server/dsh/workbench/"]) is False
    assert is_ui_write_set(["app/"]) is False


# ---------- diff 源：_ui_diff_paths 真跑 ----------

def test_ui_diff_paths_t26090405_scenario():
    """t260904-05 复现：写集只声明父目录（旧口径漏），实际改 lib 产物（新谓词命中）。"""
    tmp, wt, g = build_lane_repo()
    try:
        lane_commit(wt, g, "server/dsh/workbench/lib/workbench.js", "bundle()\n")
        lane_repo = agent_activities._lane_repo_root(wt)
        wl_base, err = agent_activities._merge_base_ref("lane", lane_repo)
        assert wl_base and not err
        ui_paths, diff_err = agent_activities._ui_diff_paths(lane_repo, wl_base, "lane")
        assert diff_err == ""
        assert ui_paths == ["server/dsh/workbench/lib/workbench.js"]
        # 同一场景下旧判定（声明口径）漏判——根因对照
        assert is_ui_write_set(["server/dsh/workbench/"]) is False
    finally:
        g.rmtree(tmp, ignore_errors=True)


def test_ui_diff_paths_engine_only_and_mixed():
    tmp, wt, g = build_lane_repo()
    try:
        lane_commit(wt, g, "server/dsh/temporal-poc/shared.py", "# engine\n")
        lane_repo = agent_activities._lane_repo_root(wt)
        wl_base, _ = agent_activities._merge_base_ref("lane", lane_repo)
        ui_paths, diff_err = agent_activities._ui_diff_paths(lane_repo, wl_base, "lane")
        assert (ui_paths, diff_err) == ([], "")
        # 混合 diff：只回 UI 子集
        lane_commit(wt, g, "app/src/main.ts", "export {};\n")
        ui_paths, diff_err = agent_activities._ui_diff_paths(lane_repo, wl_base, "lane")
        assert diff_err == "" and ui_paths == ["app/src/main.ts"]
    finally:
        g.rmtree(tmp, ignore_errors=True)


def test_ui_diff_paths_fail_closed_on_bad_base():
    tmp, wt, g = build_lane_repo()
    try:
        lane_commit(wt, g, "app/src/main.ts", "x\n")
        lane_repo = agent_activities._lane_repo_root(wt)
        # 坏基线：git diff 失败 → 空清单 + 错误留痕（不抛、不静默）
        ui_paths, diff_err = agent_activities._ui_diff_paths(lane_repo, "deadbeef", "lane")
        assert ui_paths == [] and "失败" in diff_err
        # 基线/分支缺失：直接 fail-closed 文案
        ui_paths, diff_err = agent_activities._ui_diff_paths(lane_repo, "", "lane")
        assert ui_paths == [] and "fail-closed" in diff_err
        ui_paths, diff_err = agent_activities._ui_diff_paths(lane_repo, "deadbeef", "")
        assert ui_paths == [] and "fail-closed" in diff_err
    finally:
        g.rmtree(tmp, ignore_errors=True)


# ---------- activity：ui_changed_paths ----------

def test_ui_changed_paths_activity_hit_and_fail_closed():
    tmp, wt, g = build_lane_repo()
    try:
        lane_commit(wt, g, "server/dsh/workbench/lib/workbench.js", "bundle()\n")
        # t260904-18 KI-050 声明制：判定口径=泳道 verify.yaml 声明（无声明=零口径不命中）
        declare_ui_evidence(wt, g)
        res = asyncio.run(agent_activities.ui_changed_paths(UiChangedPathsArgs(
            ticket_id="t-ut", worktree=str(wt), branch="lane", base_ref="main")))
        assert res.ui_paths == ["server/dsh/workbench/lib/workbench.js"]
        assert "按 diff 判定" in res.detail
        # 不存在的分支：merge-base 失败 → fail-closed 回执不抛
        res2 = asyncio.run(agent_activities.ui_changed_paths(UiChangedPathsArgs(
            ticket_id="t-ut", worktree=str(wt), branch="ghost", base_ref="main")))
        assert res2.ui_paths == [] and "fail-closed" in res2.detail
    finally:
        g.rmtree(tmp, ignore_errors=True)


# ---------- 装配级：merge_check 3.6 证据闸 ----------

def _run_merge_check(wt, write_set):
    res = asyncio.run(agent_activities.merge_check(MergeCheckArgs(
        ticket_id="t-ut", worktree=str(wt), branch="lane", base_ref="main",
        write_set=list(write_set))))
    return res


def test_merge_check_ui_gate_red_without_png():
    """diff 命中 UI + 无 png → 闸红，detail 带 diff 判定与命中路径（gate 记录可检索）。
    t260904-18 KI-050 声明制：判定口径吃泳道 verify.yaml 声明（fixture 显式声明）。"""
    tmp, wt, g = build_lane_repo()
    try:
        lane_commit(wt, g, "server/dsh/workbench/lib/workbench.js", "bundle()\n")
        declare_ui_evidence(wt, g)
        (wt / "server" / "admin.py").parent.mkdir(parents=True, exist_ok=True)
        (wt / "server" / "admin.py").write_text(STUB_ADMIN, encoding="utf-8")
        g("add", "-A")
        g("commit", "-m", "lane: 桩 admin")
        res = _run_merge_check(wt, ["server/dsh/workbench/"])  # 粗目录声明（旧口径判非 UI）
        items = ui_items(res.checks)
        assert len(items) == 1, res.checks
        assert items[0]["green"] is False
        assert "按 diff 判定" in items[0]["detail"]
        assert "workbench.js" in items[0]["detail"]
        assert "capture.mjs" in items[0]["detail"]  # 处置指引保留
    finally:
        g.rmtree(tmp, ignore_errors=True)


def test_merge_check_ui_gate_green_with_png():
    tmp, wt, g = build_lane_repo()
    try:
        lane_commit(wt, g, "server/dsh/workbench/lib/workbench.js", "bundle()\n")
        declare_ui_evidence(wt, g)
        (wt / "server" / "admin.py").parent.mkdir(parents=True, exist_ok=True)
        (wt / "server" / "admin.py").write_text(STUB_ADMIN, encoding="utf-8")
        shots = wt / UI_EVIDENCE_DIR
        shots.mkdir(parents=True)
        (shots / "console-default.png").write_bytes(b"png")
        g("add", "-A")
        g("commit", "-m", "lane: 桩 admin（协调目录不进结算口径，仅占位证据目录）")
        res = _run_merge_check(wt, ["server/dsh/workbench/"])
        items = ui_items(res.checks)
        assert len(items) == 1, res.checks
        assert items[0]["green"] is True
        assert "按 diff 判定" in items[0]["detail"]
    finally:
        g.rmtree(tmp, ignore_errors=True)


def test_merge_check_no_ui_item_for_engine_ticket():
    """纯引擎票（diff 无 UI 路径）→ 不出截图项，不误伤。"""
    tmp, wt, g = build_lane_repo()
    try:
        lane_commit(wt, g, "server/dsh/temporal-poc/shared.py", "# engine\n")
        declare_ui_evidence(wt, g)
        (wt / "server" / "admin.py").parent.mkdir(parents=True, exist_ok=True)
        (wt / "server" / "admin.py").write_text(STUB_ADMIN, encoding="utf-8")
        g("add", "-A")
        g("commit", "-m", "lane: 桩 admin")
        res = _run_merge_check(wt, ["server/dsh/temporal-poc/"])
        assert ui_items(res.checks) == [], res.checks
    finally:
        g.rmtree(tmp, ignore_errors=True)


# ---------- KI-050 声明制（t260904-18 门③）：merge_check 3.6 声明三态 ----------

def test_merge_check_no_declaration_green_note():
    """声明缺省 + diff 健康 → 出项 green+可见 note（行为可见非静默，验收③）。"""
    tmp, wt, g = build_lane_repo()
    try:
        lane_commit(wt, g, "server/dsh/workbench/lib/workbench.js", "bundle()\n")
        # 不写 verify.yaml（声明缺省态）
        (wt / "server" / "admin.py").parent.mkdir(parents=True, exist_ok=True)
        (wt / "server" / "admin.py").write_text(STUB_ADMIN, encoding="utf-8")
        g("add", "-A")
        g("commit", "-m", "lane: 桩 admin")
        res = _run_merge_check(wt, [])
        items = ui_items(res.checks)
        assert len(items) == 1, res.checks
        assert items[0]["green"] is True
        assert "未声明" in items[0]["detail"] and "缺席" in items[0]["detail"]
    finally:
        g.rmtree(tmp, ignore_errors=True)


def test_merge_check_malformed_declaration_red():
    """声明畸形（dirs 缺失）→ 红点名（畸形 ≠ 缺省，fail-closed）。"""
    tmp, wt, g = build_lane_repo()
    try:
        lane_commit(wt, g, "server/dsh/temporal-poc/shared.py", "# engine\n")
        declare_ui_evidence(wt, g, raw="schema: v1\nui_evidence:\n  supply: x\n")
        (wt / "server" / "admin.py").parent.mkdir(parents=True, exist_ok=True)
        (wt / "server" / "admin.py").write_text(STUB_ADMIN, encoding="utf-8")
        g("add", "-A")
        g("commit", "-m", "lane: 桩 admin")
        res = _run_merge_check(wt, [])
        items = ui_items(res.checks)
        assert len(items) == 1, res.checks
        assert items[0]["green"] is False
        assert "dirs" in items[0]["detail"]
    finally:
        g.rmtree(tmp, ignore_errors=True)


def test_match_ui_paths_prefixes_param():
    """match_ui_paths 声明参：显式 dirs 生效、空 dirs=零命中、None 回落兼容表。"""
    assert match_ui_paths(["web/src/a.tsx"], ["web/src/"]) == ["web/src/a.tsx"]
    assert match_ui_paths(["web/src/a.tsx"], []) == []            # 声明空=闸无口径
    assert match_ui_paths(["app/src/main.ts"], ["web/src/"]) == []
    assert match_ui_paths(["app/src/main.ts"]) == ["app/src/main.ts"]  # None 回落（仅兼容）
    assert is_ui_write_set(["web/src/a.tsx"], ["web/src/"]) is True
    assert is_ui_write_set(["web/src/a.tsx"], []) is False
