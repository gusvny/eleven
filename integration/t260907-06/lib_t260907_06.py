#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260907-06 集成测试共享夹具：多 repo 项目泳道挂子仓（票B：一票多 worktree 同居一 lane）。
不带 sc_ 前缀 = 共享夹具代码，不进 SCENARIOS（run_scenarios 约定）。

环境口径（三态契约，闸内环境缺失一律显式环境红）：
  stdlib 面（shared 纯函数 / git 夹具）——系统 python3 可跑，本泳道即可执行与判红绿；
  temporalio 面（prepare_workspace / settle_lane / merge_check / merge 行为腿）——
  环境缺失记 ENV_FAIL 点名并以 exit 2 收场，绝不静默略过；arbitrate/merge 期必须全绿。

夹具红线：假多仓项目只在测试 tmp 目录自建（父目录 + 两个真 git init 子仓），
不代用户建仓/搬码，不碰真实项目数据。
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]          # …/integration/t260907-06/lib.py → 仓库根
POC = REPO / "server" / "engine"

passed = 0
failed = 0
env_fail_n = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("ok    " + name)
    else:
        failed += 1
        print("FAIL  " + name + (("：" + detail) if detail else ""))


def env_fail(reason):
    global env_fail_n
    env_fail_n += 1
    print("ENV_FAIL " + reason, flush=True)


def temporalio_available():
    try:
        import temporalio  # noqa: F401
        return True
    except ImportError:
        return False


def summary():
    """套件输出约定（三态 §7.3）：fail>0→产品红 exit 1；否则 env_fail>0→exit 2；否则 0。"""
    print("SUMMARY pass=%d fail=%d env_fail=%d na=0" % (passed, failed, env_fail_n))
    if failed > 0:
        return 1
    if env_fail_n > 0:
        return 2
    return 0


def git(*args, cwd):
    p = subprocess.run(["git", "-c", "core.quotepath=false"] + list(args),
                       cwd=str(cwd), capture_output=True, text=True)
    if p.returncode != 0:
        raise AssertionError("git %s 失败: %s" % (" ".join(args), (p.stderr or "")[-300:]))
    return p.stdout


def git_ok(*args, cwd):
    """不抛版 git：返回 (rc, stdout, stderr)。"""
    p = subprocess.run(["git", "-c", "core.quotepath=false"] + list(args),
                       cwd=str(cwd), capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def _init_repo(path, message):
    path.mkdir(parents=True, exist_ok=True)
    git("init", "-b", "main", cwd=path)
    git("config", "user.email", "itest@example.com", cwd=path)
    git("config", "user.name", "itest", cwd=path)
    (path / "README.md").write_text("baseline of %s\n" % path.name, encoding="utf-8")
    # 项目声明随仓基线提交（合并闸腿要 lanes.code 在位=道开放；声明是已提交文件，
    # 不是工作区脏改——脏的写集外文件会污染白名单判定）
    (path / "verify.yaml").write_text(verify_yaml_text(), encoding="utf-8")
    git("add", "-A", cwd=path)
    git("commit", "-m", message, cwd=path)


def build_multirepo_project(prefix="t260907-06-mr-", nested=False):
    """假多仓项目夹具（tmp 自建，验收口径的「父目录 + 两个子 git 仓」）：
      <root>/repo_a/   git 仓（基线提交含 src/a.py）
      <root>/repo_b/   git 仓（基线提交含 lib/b.py）
    nested=True 时在 repo_a/nested/ 再放一个嵌套 git 仓（fail-closed 注入面用）。
    返回 (root, {"repo_a": Path, "repo_b": Path, "nested": Path|None})。"""
    root = Path(tempfile.mkdtemp(prefix=prefix))
    repos = {}
    ra = root / "repo_a"
    _init_repo(ra, "baseline: repo_a")
    (ra / "src").mkdir()
    (ra / "src" / "a.py").write_text("print('a')\n", encoding="utf-8")
    git("add", "-A", cwd=ra)
    git("commit", "-m", "repo_a: src/a.py", cwd=ra)
    repos["repo_a"] = ra
    rb = root / "repo_b"
    _init_repo(rb, "baseline: repo_b")
    (rb / "lib").mkdir()
    (rb / "lib" / "b.py").write_text("print('b')\n", encoding="utf-8")
    git("add", "-A", cwd=rb)
    git("commit", "-m", "repo_b: lib/b.py", cwd=rb)
    repos["repo_b"] = rb
    repos["nested"] = None
    if nested:
        nd = ra / "nested"
        _init_repo(nd, "baseline: nested（仓中仓，票B 口径=集合外嵌套仓）")
        (nd / "n.txt").write_text("nested\n", encoding="utf-8")
        git("add", "-A", cwd=nd)
        git("commit", "-m", "nested: n.txt", cwd=nd)
        repos["nested"] = nd
    return root, repos


def lane_dirname(ticket_id):
    """泳道目录名（引擎既有单一真源 default_lane_paths，契约面：.lane/<名>）。"""
    sys.path.insert(0, str(POC))
    import shared
    lane_rel, _branch = shared.default_lane_paths(ticket_id)
    return lane_rel.split("/", 1)[1]


def verify_yaml_text():
    """每树最小 verify.yaml（lanes.code 在场=道开放，隔离「缺失态关闭」歧义；
    write_allow 留 server/ 满足存量口径，实际白名单判据由工单 write_set 优先）。"""
    return ("schema: v1\n"
            "lanes:\n"
            "  code:\n"
            "    write_allow:\n"
            "      - server/\n")


def call_with_supported_fields(cls, **kwargs):
    """容错调参工厂：只传该 dataclass 实际支持的字段（多仓改造会扩字段——
    断言锚行为不锚通道；通道字段（如 write_set/repo_worktrees/project_root）
    未落地时被过滤，行为腿自然红（TDD 信号），不因签名漂移假绿/误报崩溃。"""
    import dataclasses
    names = {f.name for f in dataclasses.fields(cls)}
    return cls(**{k: v for k, v in kwargs.items() if k in names})


def call_prepare(container, ticket_id, write_set, project_root):
    """prepare_workspace 多仓调用（容错扩字段）。返回 WorkspacePrepResult；能力未
    落地（import 失败/签名全不符）抛 CapabilityMissing。"""
    try:
        import asyncio
        import agent_activities  # noqa: E402
    except ImportError as e:
        raise CapabilityMissing("agent_activities 不可导入: %s" % e)
    try:
        res = asyncio.run(agent_activities.prepare_workspace(
            call_with_supported_fields(
                shared_workspace_prep_cls(),
                ticket_id=ticket_id,
                workspace={"type": "worktree", "path": str(container)},
                write_set=list(write_set),
                project_root=str(project_root),
            )))
        return res
    except TypeError as e:
        raise CapabilityMissing("prepare_workspace 入参签名不符（票B 通道字段未落地？）: %s" % e)


def shared_workspace_prep_cls():
    import shared
    return shared.WorkspacePrep


class CapabilityMissing(Exception):
    """票B 能力未落地（红属 TDD 预期），与环境缺失（ENV_FAIL）区分。"""
