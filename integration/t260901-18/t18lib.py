#!/usr/bin/env python3
"""t260901-18 集成测试公共库（t01-t04 共用）。

黑盒视角：复刻 KI-010 用户可感知场景（泳道并入他单文件被合并闸误判越界），
验证修复后的口径行为。所有假仓建在 tempfile，跑完即弃，不碰真仓。
"""
import json
import logging
import shutil
import subprocess
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib_env import clean_narrowing_env, no_narrowing_env  # noqa: E402
import tempfile
import types
from pathlib import Path

PASS = 0
FAIL = 0
FAILURES = []


def ok(cond: bool, label: str) -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok %s" % label)
    else:
        FAIL += 1
        FAILURES.append(label)
        print("  FAIL %s" % label)


def finish() -> int:
    print("PASS=%d FAIL=%d" % (PASS, FAIL))
    for f in FAILURES:
        print("  - %s" % f)
    return 0 if FAIL == 0 else 1


def lane_root() -> Path:
    """泳道根（cwd=泳道根约定；scripts 在 integration/t260901-18/ 下）。"""
    return Path(__file__).resolve().parents[2]


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git"] + list(args), cwd=str(repo),
                          capture_output=True, text=True, timeout=60)


def make_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir(parents=True)
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "it@t260901-18")
    git(repo, "config", "user.name", "it-t18")
    return repo


def commit(repo: Path, msg: str) -> str:
    git(repo, "add", "-A")
    assert git(repo, "commit", "-qm", msg).returncode == 0, "commit 失败: %s" % msg
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def write_verify_yaml(repo: Path) -> None:
    """最小合法 verify.yaml（schema v1 + 非空 write_allow——校验器要求非空列表；
    判据仍走调用方 write_set，write_allow 只是声明位占位）。"""
    (repo / "verify.yaml").write_text(
        "schema: v1\n"
        "lanes:\n"
        "  code:\n"
        "    write_allow:\n"
        "      - allow-fallback.txt\n",
        "utf-8")


def verify_lane_code(repo: Path, base: str, write_set, base_other: str = None):
    """真跑 verify_lane code 道（lane=code 白名单判定的真实现），返回 run() 结果 dict。
    base_other (261012 caliber): the other side's merge-base. When passed, the
    whitelist judges the intersection of the two three-dot diffs ("this ticket's
    own write" = files that differ from both sides). Absent/None = the old
    caliber, byte for byte unchanged."""
    sys.path.insert(0, str(lane_root() / "server" / "tools"))
    import verify_lane
    # 260930：进程内调闸同样吃继承旋钮——剥完再跑
    payload = {"lane": "code", "path": str(repo), "base": base,
               "require_base": True, "write_set": list(write_set),
               "skip_slow": True}
    if base_other:
        payload["base_other"] = base_other
    with no_narrowing_env():
        return verify_lane.run(payload)


def whitelist_items(result):
    for c in result.get("checks", []):
        if c.get("check") == "写集白名单":
            return c.get("items", [])
    return None


def mkdtemp() -> Path:
    return Path(tempfile.mkdtemp(prefix="t18-it-"))


def tree_snapshot(repo: Path) -> str:
    """One canonical string for 'the tree is byte-identical' judgments
    (t261016-11 ①): HEAD sha + `git status --porcelain` output. Any commit,
    deletion or untracked artifact left behind changes the snapshot."""
    head = git(repo, "rev-parse", "HEAD")
    st = git(repo, "status", "--porcelain")
    return "HEAD=%s\nSTATUS:\n%s" % (head.stdout.strip(), st.stdout)


def assert_tree_untouched(before: str, after: str, label: str) -> None:
    """t261016-11 ①: a case that drives the real merge_check face must never
    write to the tree under test. A changed snapshot = the case committed,
    deleted or dirtied something — red, never tolerated."""
    ok(before == after, "%s: the tree under test is byte-identical after the "
                        "run (no commit, no deletion, no dirtying)" % label)


def rmtree(root: Path) -> None:
    shutil.rmtree(str(root), ignore_errors=True)


def install_temporalio_stub():
    """真 temporalio 优先；没有（裸 python3 沙箱）则打最小 stub——
    本测试只驱动 merge_check 自身逻辑（git 调用 + verify_lane 接线），
    不验 temporalio 装饰器/心跳机制（那部分由生产 worker 跑 merge 闸覆盖）。
    若 agent_activities 未来用到更多 temporalio API，此处会炸出显式
    AttributeError（红灯），不会静默假绿。"""
    try:
        import temporalio  # noqa: F401
        return
    except ImportError:
        pass
    t = types.ModuleType("temporalio")
    a = types.ModuleType("temporalio.activity")

    def defn(fn=None, **_kw):
        if fn is None:
            return lambda f: f
        return fn

    a.defn = defn
    a.logger = logging.getLogger("temporalio.activity")
    a.heartbeat = lambda *args, **kw: None
    a.in_activity = lambda: False
    t.activity = a
    sys.modules["temporalio"] = t
    sys.modules["temporalio.activity"] = a


def import_engine():
    """导入泳道内的 agent_activities + MergeCheckArgs（真代码，非替身）。"""
    install_temporalio_stub()
    poc = str(lane_root() / "server" / "engine")
    if poc not in sys.path:
        sys.path.insert(0, poc)
    import agent_activities
    from shared import MergeCheckArgs
    return agent_activities, MergeCheckArgs


class VerifyLaneCapture:
    """拦截 agent_activities 里 merge_check 对 `python3 server/admin.py call verify_lane`
    的真实子进程调用：记录真实发出的 payload，返回合成绿回执让 activity 继续。
    只拦 verify_lane 那一发，其余子进程（git 等）原样真跑。"""

    def __init__(self, agent_activities):
        self.mod = agent_activities
        self.real_run = subprocess.run
        self.payload = None

    def __enter__(self):
        def fake_run(cmd, **kw):
            if (isinstance(cmd, list) and len(cmd) >= 5
                    and cmd[0] == "python3" and cmd[1] == "server/admin.py"
                    and cmd[2] == "call" and cmd[3] == "verify_lane"):
                self.payload = json.loads(cmd[4])
                out = json.dumps({"ok": True, "result": {"green": True,
                                                          "exit_code": 0, "red_count": 0}})
                return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")
            return self.real_run(cmd, **kw)
        self.mod.subprocess.run = fake_run

        # 260904 回迁适配：merge_check 第 3 项已 async 化（t260903-09），走
        # asyncio.create_subprocess_exec（admin.py 为绝对路径）——补拦 async 形态。
        # 断言不变（接线存在 + 真实 payload），只是拦截面对齐现行调用方式。
        self.real_exec = self.mod.asyncio.create_subprocess_exec

        def _hit(s):
            return (s[0] in ("python3", "python")
                    and any(x.endswith("admin.py") for x in s)
                    and "verify_lane" in s and "call" in s)

        class _FakeProc:
            def __init__(self, out_bytes):
                self._out = out_bytes

            async def communicate(self):
                return self._out, b""

        real_exec, capture = self.real_exec, self

        async def fake_exec(*cmd, **kw):
            s = [str(x) for x in cmd]
            if _hit(s):
                i = s.index("verify_lane")
                capture.payload = json.loads(s[i + 1])
                out = json.dumps({"ok": True, "result": {"green": True,
                                                         "exit_code": 0, "red_count": 0}})
                return _FakeProc(out.encode())
            return await real_exec(*cmd, **kw)

        self.mod.asyncio.create_subprocess_exec = fake_exec
        return self

    def __exit__(self, *exc):
        self.mod.subprocess.run = self.real_run
        self.mod.asyncio.create_subprocess_exec = self.real_exec
        return False
