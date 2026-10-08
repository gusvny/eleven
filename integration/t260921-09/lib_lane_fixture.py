#!/usr/bin/env python3
"""t260921-09 集成场景共享夹具（多仓/单仓泳道 + merge_check 直调 + 三态记账）。

被同目录 sc_ 场景导入（非 sc_ 前缀=L5 孤儿规则豁免的共享代码）。职责只到
「搭真 git 夹具、驱动真 activity、记账」；判定断言全部在场景文件里。

夹具立场（灰盒，绑定浅）：
  - 一切 git 态用真 git 子进程构造（worktree/commit/reset），不 mock git；
  - 每个夹具仓的 main 预提交一个最小 verify 工具替身（server/admin.py 恒绿 JSON）：
    merge_check 第 3 项跑「泳道自己的 admin.py」，verify_lane 语义不是本票测试对象，
    替身只稳定「verify 绿」这一前提，替身文件在 base 提交里（不产生泳道提交、不产生
    未提交面）；
  - 泳道分支与清单（repo_worktrees.json）按引擎同款形态落盘（清单经
    agent_activities.MULTI_MANIFEST_REL 单一真源常量定位）；
  - 运行时引导：普通 python3 缺 temporalio 时 re-exec 引擎 venv；venv 缺席=ENV_FAIL
    （exit 2，直调 activity 无 stdlib 替代，沿 t260913-05 同款立场）。
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ENGINE_DIR = REPO_ROOT / "server" / "engine"
VENV_PY = ENGINE_DIR / ".venv" / "bin" / "python"

# verify 工具替身：夹具仓 main 预提交（base 内容，零泳道提交零脏面）
STUB_ADMIN = (
    "#!/usr/bin/env python3\n"
    '"""场景夹具用最小 verify 工具替身：merge_check 第 3 项吃「泳道自己的 admin.py」，\n'
    "本票 intent 不含 verify_lane 语义，替身恒绿只稳定前提（t260921-09）。\"\"\"\n"
    "import json, sys\n"
    'sys.stdout.write(json.dumps({"ok": True, "result": {"green": True, '
    '"exit_code": 0, "red_count": 0, "checks": []}}))\n'
)

BAD_REF = "no-such-ref-t26092109"  # 查询失败形态的坏引用


def ensure_engine_runtime():
    """普通 python3 缺 temporalio → re-exec 引擎 venv；venv 缺席=ENV_FAIL exit 2。"""
    try:
        import temporalio  # noqa: F401
    except ImportError:
        if not VENV_PY.is_file():
            print("ENV_FAIL: 引擎 venv 缺失：%s（merge_check 直调无 stdlib 替代）" % VENV_PY)
            sys.exit(2)
        os.execv(str(VENV_PY), [str(VENV_PY), str(Path(__file__).resolve()), *sys.argv[1:]])


def load_engine():
    """venv 内导入引擎模块（sys.path 注入，与 engine tests 同款）。"""
    if str(ENGINE_DIR) not in sys.path:
        sys.path.insert(0, str(ENGINE_DIR))
    import agent_activities  # noqa: F401
    import shared
    return shared, sys.modules["agent_activities"]


def git(*args, cwd):
    """真 git 子进程；返回 CompletedProcess（断言留给调用方）。"""
    return subprocess.run(["git"] + list(args), cwd=str(cwd),
                          capture_output=True, text=True)


def git_ok(*args, cwd):
    p = git(*args, cwd=cwd)
    if p.returncode != 0:
        raise RuntimeError("git %s 失败: %s" % (" ".join(args), p.stderr.strip()[:300]))
    return p.stdout.strip()


class TempProject:
    """tmp 多仓/单仓项目（父目录作根，仓集合=一层子仓或根本体）。"""

    def __init__(self, single=False):
        self.base = Path(tempfile.mkdtemp(prefix="t26092109-sc-"))
        self.single = single
        self.root = self.base / ("single" if single else "proj")
        self.root.mkdir(parents=True, exist_ok=True)

    # ---- 仓与泳道 ----
    def init_repo(self, rel, files):
        """建仓：files={路径: 内容} 全部落进**首个** base 提交（含 verify 替身）。"""
        repo = self.root / rel if rel else self.root
        repo.mkdir(parents=True, exist_ok=True)
        git_ok("init", "-b", "main", cwd=repo)
        git_ok("config", "user.email", "sc@example.com", cwd=repo)
        git_ok("config", "user.name", "sc", cwd=repo)
        payload = dict(files)
        payload.setdefault("server/admin.py", STUB_ADMIN)
        for fpath, content in payload.items():
            fp = repo / fpath
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content, encoding="utf-8")
        git_ok("add", "-A", cwd=repo)
        git_ok("commit", "-m", "base", cwd=repo)
        return repo

    def second_commit(self, repo, fname, content):
        """main 第二个提交（给「分支位点异常」造 HEAD~1 回退空间）。"""
        fp = repo / fname
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
        git_ok("add", "-A", cwd=repo)
        git_ok("commit", "-m", "base2", cwd=repo)

    def base_ref(self, repo):
        return git_ok("rev-parse", "main", cwd=repo)

    def build_lane(self, tid, repo_specs, write_set):
        """多仓泳道：逐仓 worktree add + 清单落盘 + 按仓施加泳道态。

        repo_specs: {仓相对路径: {"commit": 写集内改动并提交（泳道得 commit）,
                                   "out_dirty": 写集外未提交脏文件,
                                   "behind": 泳道分支 reset 到 base~1（0 commit 但树≠base）,
                                   "base_ref": 覆盖清单里的 base_ref（造查询失败形态）}}
        返回 (lane 目录, manifest 同构列表)。
        """
        lane = self.root / ".lane" / tid
        entries = []
        for rel, spec in repo_specs.items():
            repo = self.root / rel
            branch = "lane/%s-%s" % (tid, rel)
            git_ok("worktree", "add", "-b", branch, str(lane / rel), cwd=repo)
            tree = lane / rel
            if spec.get("commit"):
                fp = tree / spec["commit"][0]
                fp.parent.mkdir(parents=True, exist_ok=True)
                fp.write_text(spec["commit"][1], encoding="utf-8")
                git_ok("add", "-A", cwd=tree)
                git_ok("commit", "-m", "lane work", cwd=tree)
            if spec.get("out_dirty"):
                (tree / spec["out_dirty"]).write_text("dirty\n", encoding="utf-8")
            if spec.get("behind"):
                git_ok("reset", "--hard", "HEAD~1", cwd=tree)
            entries.append({"repo": rel, "name": rel, "branch": branch,
                            "base_ref": str(spec.get("base_ref") or self.base_ref(repo))})
        import agent_activities as _aa  # 清单路径单一真源常量
        mf = lane / _aa.MULTI_MANIFEST_REL
        mf.parent.mkdir(parents=True, exist_ok=True)
        mf.write_text(json.dumps(entries, ensure_ascii=False), "utf-8")
        self.write_set = list(write_set)
        return lane

    def build_single_lane(self, tid, spec, write_set):
        """单仓泳道：根本体仓的 worktree（无清单 → _lane_scopes 单仓回落形态）。"""
        repo = self.root
        branch = "lane/%s-single" % tid
        lane = self.root / ".lane" / tid
        git_ok("worktree", "add", "-b", branch, str(lane), cwd=repo)
        if spec.get("commit"):
            fp = lane / spec["commit"][0]
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(spec["commit"][1], encoding="utf-8")
            git_ok("add", "-A", cwd=lane)
            git_ok("commit", "-m", "lane work", cwd=lane)
        if spec.get("out_dirty"):
            (lane / spec["out_dirty"]).write_text("dirty\n", encoding="utf-8")
        if spec.get("behind"):
            git_ok("reset", "--hard", "HEAD~1", cwd=lane)
        self.write_set = list(write_set)
        return lane

    def merge_check(self, aa, tid, lane, *, no_file_changes=False, base_ref="",
                    branch="", write_set=None, green_run=False):
        """直调真 merge_check activity（红不抛，回执=对外契约）。

        green_run=True：注入本票绿跑面 last_green_run={"sha","ran":1}——t261008-24
        起 merge_check 恒带「验收场景本树至少一次绿跑」前置项（无面=红 zero_run，
        永不默认绿）；专测其它检查项的场景若不注面，会被该前置项**与本票 intent
        无关的红**污染。sha=泳道分支真 HEAD（rev-parse 于仓根，与 merge_check 的
        scopes[0] 同一身份），不是凭空绿。"""
        async def _run():
            kwargs = dict(
                ticket_id=tid, worktree=str(lane), branch=branch,
                base_ref=base_ref,
                write_set=list(self.write_set if write_set is None else write_set),
                no_file_changes=bool(no_file_changes))
            if green_run:
                kwargs["last_green_run"] = _green_run_face(aa, lane, branch)
            return await aa.merge_check(aa.MergeCheckArgs(**kwargs))
        return asyncio.run(_run())

    def cleanup(self):
        shutil.rmtree(self.base, ignore_errors=True)


def _green_run_face(aa, lane, branch=""):
    """绿跑面 sha 的身份单点（t261008-24 rework gen7）：多仓清单 = **清单首仓分支**
    在该成员仓里 rev-parse（与 merge_check 的 scopes[0] 同一身份——容器根本体
    HEAD 是另一棵树，gen4 的容器根解析因此被仲裁判错并回红）；无清单（单仓回落
    形态）= lane 泳道分支。任何解析失败 → 空 sha（merge_check 侧 fail-closed 红，
    绝不造假绿），本探针在任何畸形夹具上都不抛。"""
    try:
        ref = branch
        repo_dir = None
        if not ref:
            mf = Path(lane) / aa.MULTI_MANIFEST_REL
            entries = json.loads(mf.read_text(encoding="utf-8"))
            if isinstance(entries, list) and entries and isinstance(entries[0], dict):
                ref = str(entries[0].get("branch") or "")
                repo_dir = Path(lane).parent.parent / str(entries[0].get("repo") or "")
        if not ref:
            ref = "HEAD"
        cmd_repo = repo_dir if (repo_dir and repo_dir.is_dir()) else Path(lane)
        p = subprocess.run(["git", "-C", str(cmd_repo), "rev-parse", "--verify", ref],
                           capture_output=True, text=True, timeout=30)
        lines = (p.stdout or "").strip().splitlines()
        if p.returncode == 0 and lines and lines[0]:
            return {"sha": lines[0], "ran": 1}
    except Exception:  # noqa: BLE001 — 解析不出=空 sha=fail-closed，绝不抛、绝不假绿
        pass
    return {"sha": "", "ran": 1}


class Legs:
    """三态记账（integration/lib_env.py 契约：0=全过 1=有 FAIL 2=ENV_FAIL）。"""

    def __init__(self, scenario):
        self.scenario = scenario
        self.pass_n = self.fail_n = self.env_n = self.na_n = 0

    def check(self, name, cond, info=""):
        if cond:
            self.pass_n += 1
            print("PASS [%s] %s" % (self.scenario, name))
        else:
            self.fail_n += 1
            print("FAIL [%s] %s%s" % (self.scenario, name, ("（%s）" % info) if info else ""))
        return bool(cond)

    def env_fail(self, reason):
        self.env_n += 1
        print("ENV_FAIL: %s" % reason)
        print("SUMMARY pass=%d fail=%d env_fail=%d na=%d"
              % (self.pass_n, self.fail_n, self.env_n, self.na_n))
        sys.exit(2)

    def finish(self):
        print("SUMMARY pass=%d fail=%d env_fail=%d na=%d"
              % (self.pass_n, self.fail_n, self.env_n, self.na_n))
        sys.exit(1 if self.fail_n else 0)
