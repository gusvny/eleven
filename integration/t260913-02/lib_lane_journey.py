#!/usr/bin/env python3
"""t260913-02 场景共享夹具（无 sc_ 前缀＝共享子检查代码，不登记场景清单）。

守护对象（工单 t260913-02）：巡检流程自有的「搭泳道 → 跑全集 → 拆泳道」阶段 +
每日调度接真 + 漏跑可见。对外契约面（本库一切绑定只落在此）：

- 巡检工作流：`InspectionPeriodicWorkflow`，票号 `inspection-<实例>-<期>`；阶段机
  公开读面=snapshot（stage/stage_state/status/face/timeline）；人门=sign
  gate=inspection-close（who 由调用方注入，agent 角色名不得自签）。
- 巡检落账：`out/inspection/<票号>.json`（收口后再写一次终态；blocked 终态也须
  可见落账——「漏跑/失败不得静默」的列表可读面）。
- 泳道机械面：`prepare_workspace`（WorkspacePrep{workspace:{type:worktree,path},
  branch, base_ref}）/ `teardown_lane`（MergeArgs{worktree,branch,ticket_id}）/
  `run_integration_tests`（IntegrationRunArgs{ticket_id,worktree,attempt}）——
  三者皆为引擎既有通用活动，巡检复用而不新造。
- 触发/运维通道：`inspection_trigger.py` 子命令 trigger/sign/schedule-up/decl
  （+ 本票新增 deadman 子命令），stdout 单行 JSON {ok, result|error}。

命名与隔离（本票红线，场景侧可判定的部分）：
- 巡检泳道 = `<repo>/.lane/inspection-<实例>-<期>`，分支 `inspection/<实例>/<期>`；
  与开发泳道 `.lane/t<日期>-<别名>` / `lane/...` 命名空间零交集（本库
  `git_worktrees` / `git_branches` 提供 grep 面）。
- 场景一切 spawn 经 `lib_inspection.spawn_env` 单点钉隔离台 17233（t260910-11
  红线：绝不写生产 7233），并配私有队列 + 自供给 worker（生产 worker 不识新
  workflow/activity 类时会抢活打回）。

三态纪律（t260904-12）：exit 0=PASS / 1=FAIL（产品红）/ 2=ENV_FAIL（环境红，
点名缺什么，不假绿不静默）。实现段落地前红属预期（TDD 信号）。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_REPO, "integration", "t260905-03"))
import lib_inspection as lib  # noqa: E402 —— 跨票共享夹具（spawn_env/StageWorker/落账读面）

REPO = _REPO
TP_DIR = os.path.join(REPO, "server", "engine")
GITWORK = "git"

# 巡检命名空间（本票契约面，锚在用户可感知的路径/分支形状上，不锚内部函数名）
LANE_RE = re.compile(r"^\.lane/inspection-")
BRANCH_RE = re.compile(r"^inspection/")
DEV_LANE_RE = re.compile(r"^\.lane/t[0-9]{6}-")
DEV_BRANCH_RE = re.compile(r"^lane/")


# ---------------------------------------------------------------- 断言账本（三态收口）

class Rule:
    """pass/fail/env_fail 三态断言账本 + 统一收口（SUMMARY 行 + exit 码分家）。"""

    def __init__(self, suite: str):
        self.suite = suite
        self.ok = 0
        self.failed = 0
        self.env = 0
        self._started = time.time()

    def check(self, name: str, cond, detail: str = "") -> bool:
        cond = bool(cond)
        if cond:
            self.ok += 1
            print("ok    %s" % name, flush=True)
        else:
            self.failed += 1
            print("FAIL  %s%s" % (name, ("：" + str(detail)) if detail else ""), flush=True)
        return cond

    def env_fail(self, name: str, detail: str) -> None:
        self.env += 1
        print("ENV_FAIL %s：%s" % (name, detail), flush=True)

    def finish(self) -> int:
        dur = time.time() - self._started
        print("SUMMARY pass=%d fail=%d env_fail=%d na=0 (%.0fs)"
              % (self.ok, self.failed, self.env, dur), flush=True)
        if self.failed:
            return 1
        if self.env:
            return 2
        return 0


# ---------------------------------------------------------------- git 观测面

def git(args, cwd, timeout=60):
    return subprocess.run([GITWORK] + [str(a) for a in args], cwd=str(cwd),
                          capture_output=True, text=True, timeout=timeout)


def git_out(args, cwd) -> str:
    p = git(args, cwd)
    return p.stdout.strip() if p.returncode == 0 else ""


def head_sha(repo) -> str:
    return git_out(["rev-parse", "HEAD"], repo)


def is_git_repo(path) -> bool:
    return bool(git_out(["rev-parse", "--is-inside-work-tree"], path) == "true")


def worktree_entries(repo) -> list:
    """`git worktree list --porcelain` → [{"path":…, "branch":…, "sha":…, "detached":…}]。"""
    out = git_out(["worktree", "list", "--porcelain"], repo)
    entries = []
    cur = {}
    for line in out.splitlines():
        if line.startswith("worktree "):
            if cur:
                entries.append(cur)
            cur = {"path": line[len("worktree "):]}
        elif line.startswith("HEAD "):
            cur["sha"] = line[len("HEAD "):]
        elif line.startswith("branch "):
            cur["branch"] = line[len("branch "):].replace("refs/heads/", "")
        elif line == "detached":
            cur["detached"] = True
    if cur:
        entries.append(cur)
    return entries


def lane_worktrees(repo, instance: str = "") -> list:
    """本实例命名空间下的巡检 worktree（path 匹配 .lane/inspection-[<实例>-]…）。"""
    pat = LANE_RE if not instance else re.compile(r"^\.lane/inspection-%s-" % re.escape(instance))
    out = []
    for e in worktree_entries(repo):
        rel = os.path.relpath(e.get("path", ""), str(repo))
        if pat.match(rel.replace(os.sep, "/")):
            out.append(e)
    return out


def branches(repo, pat: str = "") -> list:
    rx = re.compile(pat) if pat else None
    out = []
    for ln in git_out(["branch", "--format=%(refname:short)"], repo).splitlines():
        ln = ln.strip()
        if ln and (rx is None or rx.match(ln)):
            out.append(ln)
    return out


def dev_lane_snapshot(repo) -> dict:
    """开发泳道面（worktree/branch）快照——「不得复用开发泳道命名」的反向观测点。"""
    wts = sorted(os.path.relpath(e["path"], str(repo)).replace(os.sep, "/")
                 for e in worktree_entries(repo))
    return {"dev_worktrees": [w for w in wts if DEV_LANE_RE.match(w)],
            "dev_branches": [b for b in branches(repo) if DEV_BRANCH_RE.match(b)],
            "other_worktrees": [w for w in wts if not LANE_RE.match(w) and not DEV_LANE_RE.match(w)]}


def tracked_status(repo) -> dict:
    """主工作树「零改动」观测面（三件）：
      - `git status --porcelain` 工作区条目（tracked 的 M/D 与 untracked 的 ??，
        `.lane/` 已 gitignore 故不应出现在此）；
      - `git diff --stat HEAD` 与 HEAD sha（tracked 内容零改动、HEAD 不移动）。
    返回 {status:[…], diff_head:"…", head:"…"}。"""
    st = [ln for ln in git_out(["status", "--porcelain"], repo).splitlines() if ln.strip()]
    return {"status": st,
            "diff_head": git_out(["diff", "--stat", "HEAD"], repo),
            "head": head_sha(repo)}


def tracked_files(repo) -> dict:
    """HEAD 中每个 tracked 文件的工作区内容校验和（主树被真的改写时在此现形）。"""
    out = {}
    for rel in git_out(["ls-tree", "-r", "--name-only", "HEAD"], repo).splitlines():
        rel = rel.strip()
        if not rel:
            continue
        p = os.path.join(str(repo), rel)
        try:
            with open(p, "rb") as f:
                out[rel] = hash(f.read())
        except OSError:
            out[rel] = -1
    return out


# ---------------------------------------------------------------- 真 git 夹具仓

def init_repo(path, files=None) -> str:
    """建真 git 仓（带仓内身份）并首提交；返回首提交 sha。files = {相对路径: 文本}。"""
    os.makedirs(str(path), exist_ok=True)
    for rel, text in (files or {"README.md": "# fixture\n"}).items():
        p = os.path.join(str(path), rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
    git(["init", "-q", "-b", "main"], path)
    git(["config", "user.email", "scenario@sandbar.test"], path)
    git(["config", "user.name", "scenario"], path)
    git(["add", "-A"], path)
    git(["-c", "commit.gpgsign=false", "commit", "-qm", "init"], path)
    return head_sha(path)


def commit_all(repo, message="tick") -> str:
    git(["add", "-A"], repo)
    git(["-c", "commit.gpgsign=false", "commit", "-qm", message], repo)
    return head_sha(repo)

FIXTURE_TREE = {
    # 仓形夹具：扫描面/verify 道/引擎锚一应俱全（扫描器收集口径同构，不靠 mock 缝合）
    ".gitignore": ".lane/\nout/\n.venv/\n",
    "verify.yaml": ("schema: v1\n"
                    "lanes:\n"
                    "  code:\n"
                    "    write_allow:\n"
                    "      - server/\n"
                    "      - integration/\n"
                    "    checks:\n"
                    "      - id: trivial\n"
                    "        cmd: 'true'\n"
                    "integration:\n"
                    "  cmd: python3 integration/run_scenarios.py\n"),
    "integration/run_scenarios.py": ("SCENARIOS = [\n"
                                     "    ('fixture-a', '夹具场景 A（恒绿）', 'true'),\n"
                                     "]\n"),
    "integration/sc_fixture_guard.py": ("# 夹具守卫：断言旧措辞（KI-051 形态的扫描对象）\n"
                                        "ANCHOR = \"隔离台『+ 新建会话』\"\n"),
    "server/plugins/workbench/src/client/capture.mjs": (
        "// 生产方：模板拼接（措辞已改，旧字面搜不到）\n"
        "export const label = (x) => `隔离台项目行『＋ 钮』${x}`;\n"),
    "server/engine/keep.py": "# engine anchor\n",
    "docs/README.md": "# docs anchor\n",
}


def fixture_repo(label: str) -> str:
    """仓形夹具真仓（tmp），返回仓根绝对路径。"""
    root = tempfile.mkdtemp(prefix="sandbar-insp-%s-" % label)
    init_repo(root, FIXTURE_TREE)
    return root


DECL_TMPL = """schema: v1
instances:
%s"""


def write_decl(path, instances) -> str:
    """写巡检声明（instances = [(id, {键: 值}, {schedule 键: 值})] 或原始 yaml 文本）。"""
    if isinstance(instances, str):
        with open(path, "w", encoding="utf-8") as f:
            f.write(instances)
        return path
    blocks = []
    for iid, keys, sched in instances:
        lines = ["  - id: %s" % iid]
        for k, v in keys.items():
            lines.append("    %s: %s" % (k, v))
        lines.append("    schedule:")
        for k, v in sched.items():
            lines.append("      %s: %s" % (k, v))
        blocks.append("\n".join(lines))
    with open(path, "w", encoding="utf-8") as f:
        f.write(DECL_TMPL % "\n".join(blocks) + "\n")
    return path


def write_decl_block(path, block: str) -> str:
    """写完整声明文件：根 schema/instances + 给定的实例块文本（块内以 `- id:` 起头）。"""
    with open(path, "w", encoding="utf-8") as f:
        f.write("schema: v1\ninstances:\n%s" % block)
    return path


def suite_decl_entry(instance: str, repo_root: str) -> str:
    """本票形态的声明块文本（list 项以 `- id:` 起头；suite/cron 的形状由实现段声明面接线，
    夹具只给形状与实例名——实例名带进程戳防隔夜残留撞「一票一期」去重）。"""
    return ("  - id: %s\n"
            "    enabled: true\n"
            "    suite: full\n"
            "    schedule:\n"
            "      kind: cron\n"
            "      cron: 30 7 * * *\n"
            "    workflow: InspectionPeriodicWorkflow\n"
            "    template: inspection-lite\n" % instance)


# ---------------------------------------------------------------- 落账/回执读面

def inspection_dir() -> str:
    return os.environ.get("SANDBAR_INSPECTION_DIR") or os.path.join(TP_DIR, "out", "inspection")


def ledger(ticket_id: str):
    path = os.path.join(inspection_dir(), "%s.json" % ticket_id)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def ledger_files() -> list:
    try:
        return sorted(os.listdir(inspection_dir()))
    except OSError:
        return []


def stage_names(snapshot) -> list:
    """snapshot.timeline → 阶段序列（去重保序）——阶段机命名面的公开读面。"""
    tl = (snapshot or {}).get("timeline") or []
    out = []
    for row in tl:
        st = str((row or {}).get("stage") or "")
        if st and st not in out:
            out.append(st)
    return out


def call_activity(fn, *shapes):
    """按候选入参形状直调活动函数（返回 (result, 错因)）。

    适配面：本票新活动的入参容器（dict / dataclass / 关键字）由实现段定名——场景
    不发明契约，只按「语义等价的候选形状」逐个试；全部不匹配时如实上报错因
    （不把签名不匹配伪装成产品红，也不静默跳过该腿）。
    """
    import asyncio
    import dataclasses
    last = ""
    for sh in shapes:
        try:
            if isinstance(sh, dict):
                res = asyncio.run(fn(**sh))
            elif isinstance(sh, tuple):
                res = asyncio.run(fn(*sh))
            else:
                res = asyncio.run(fn(sh))
        except TypeError as e:
            last = "TypeError: %s" % e
            continue
        except Exception as e:  # noqa: BLE001
            return None, "%s: %s" % (type(e).__name__, e)
        return res, ""
    return None, last or "无候选形状匹配"


def result_ok(res):
    if isinstance(res, dict):
        return bool(res.get("ok"))
    return bool(getattr(res, "ok", False))


def result_err(res) -> str:
    if isinstance(res, dict):
        return str(res.get("error") or "")
    return str(getattr(res, "error", "") or "")


def result_action(res) -> str:
    if isinstance(res, dict):
        return str(res.get("action") or "")
    return str(getattr(res, "action", "") or "")


def run_json(cmd, env=None, timeout=180):
    """跑引擎 CLI（经 spawn_env 单点钉隔离台），返回 (proc, 末行 JSON)。"""
    proc = lib.run_cmd(cmd, env=env, timeout=timeout)
    lib.env_fail_if_missing_dep(proc)
    return proc, lib.last_json(proc.stdout)


def cleanup_paths(*paths) -> None:
    for p in paths:
        if p:
            shutil.rmtree(str(p), ignore_errors=True)
