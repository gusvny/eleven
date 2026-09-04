# -*- coding: utf-8 -*-
"""t260902-09 集成测试集共享 fixture（黑盒视角；制式沿 t260902-02/lib）。

职责：
- stub_temporalio：模块级桩，本机无 temporal SDK 也能直测 activity 函数路径；
- Sandbox：SANDBAR_PROJECTS_DIR / DSH_HOME / HOME 三个 env 全指 mkdtemp，
  绝不触真 ~/.sandbar、真 ~/.dsh、真凭据（测试安全红线）；
- Ledger：stdout 末行 SUMMARY pass/skip/fail（integration/README.md 执行契约）；
- ensure_yaml：PyYAML 缺失时优先 re-exec 进 temporal-poc venv（ensure_sdk 同款
  制式）；仍无则返回 False，调用方对依赖 yaml 的用例干净 SKIP（依赖缺失=skip）；
- creds_text / insertion_only：真实嵌套格式凭据夹具构造与「仅追加」断言件
  （格式载体见本票 plan.md「格式载体」节：version + refs 嵌套，非扁平）。
"""
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
SUITE = HERE.parent
REPO = SUITE.parent.parent
POC = REPO / "server" / "dsh" / "temporal-poc"
# venv 回落链（同 manifest PY 链口径）：worktree 常无 .venv，经
# `git rev-parse --git-common-dir` 解析主 checkout 再找（README 既有定式）；
# 再无则由调用方干净 SKIP。
VENV_PY = POC / ".venv" / "bin" / "python"
REEXEC_GUARD = "_T26090209_YAML_REEXEC"


def _git_common_dir_venv():
    """主 checkout 的 temporal-poc venv python（worktree 场景）；解析失败 → None。"""
    try:
        r = subprocess.run(["git", "rev-parse", "--git-common-dir"],
                           cwd=str(REPO), capture_output=True, text=True, timeout=5)
    except Exception:
        return None
    if r.returncode != 0 or not r.stdout.strip():
        return None
    d = Path(r.stdout.strip())
    if not d.is_absolute():
        d = (REPO / d).resolve()
    return d.parent / "server" / "dsh" / "temporal-poc" / ".venv" / "bin" / "python"


# ---------------------------------------------------------------- 模块桩
def stub_temporalio():
    """幂等安装 temporalio 桩（只挡模块级依赖，不碰被测函数语义）。"""
    if "temporalio" in sys.modules:
        mod = sys.modules.get("temporalio")
        if getattr(mod, "__file__", None):  # 真 SDK 已在（e2e 重跑）——不动
            return
    tmod = types.ModuleType("temporalio")
    amod = types.ModuleType("temporalio.activity")

    class _ActivityStub:
        logger = logging.getLogger("temporalio-stub")

        def defn(self, fn=None, **kw):
            return (lambda f: f) if fn is None else fn

        def heartbeat(self, *a, **kw):
            pass

    amod.activity = _ActivityStub()
    tmod.activity = _ActivityStub()
    sys.modules["temporalio"] = tmod
    sys.modules["temporalio.activity"] = amod


def load_agent_activities():
    stub_temporalio()
    if str(POC) not in sys.path:
        sys.path.insert(0, str(POC))
    import agent_activities
    return agent_activities


# ---------------------------------------------------------------- 执行契约
class Ledger:
    def __init__(self):
        self.p = self.s = self.f = 0

    def ok(self, cond, label, detail=""):
        if cond:
            self.p += 1
            print("  ok  " + label)
        else:
            self.f += 1
            print("  FAIL %s%s" % (label, (" | " + str(detail)) if detail else ""))

    def skip1(self, label, reason):
        self.s += 1
        print("  skip %s | %s" % (label, reason))

    def finish(self):
        print("SUMMARY pass=%d skip=%d fail=%d" % (self.p, self.s, self.f))
        return 1 if self.f else 0


# ---------------------------------------------------------------- yaml 探测
def have_yaml():
    try:
        import yaml  # noqa: F401
        return True
    except ImportError:
        return False


def ensure_yaml():
    """保证当前解释器有 PyYAML：没有则 re-exec 进 temporal-poc venv（worktree
    优先，经 git-common-dir 回落主 checkout，同 manifest PY 链口径）后不再返回；
    两处皆无 → False，调用方对依赖 yaml 的用例干净 SKIP（勿 FAIL）。"""
    if have_yaml():
        return True
    fallback = _git_common_dir_venv()
    for venv_py in (VENV_PY, fallback):
        if venv_py and venv_py.is_file() and os.environ.get(REEXEC_GUARD) != "1":
            os.environ[REEXEC_GUARD] = "1"
            os.execv(str(venv_py),
                     [str(venv_py), os.path.abspath(sys.argv[0])] + sys.argv[1:])
    return False


def yaml_load(text):
    import yaml
    return yaml.safe_load(text)


# ---------------------------------------------------------------- 夹具构造
def creds_text(leaves, version="1", top_extra=""):
    """真实嵌套格式凭据文本：version 标量 + refs 块（叶子按给定顺序）。
    leaves = [(KEY, value), ...]；top_extra = 追加在 version 行后的顶层原文（可空）。"""
    lines = ["version: %s\n" % version]
    if top_extra:
        lines.append(top_extra)
    lines.append("refs:\n")
    for k, v in leaves:
        lines.append("  %s: %s\n" % (k, v))
    return "".join(lines)


def insertion_only(orig_text, new_text):
    """断言件：new_text = orig_text 仅做「整行插入」的结果
    （原行全部按原相对顺序保留，无改写、无删除——合并写回的口径）。"""
    old = orig_text.splitlines(keepends=True)
    new = new_text.splitlines(keepends=True)
    i = 0
    for ln in new:
        if i < len(old) and ln == old[i]:
            i += 1
    return i == len(old)


class Sandbox:
    """tmp env 桩：SANDBAR_PROJECTS_DIR/DSH_HOME/HOME 全指临时目录；
    泳道、per-key 源、legacy 源都在 tmp 里，退出时恢复 env 并清 tmp。"""

    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="integ-t260902-09-"))
        self.root = self.tmp / "projects"   # = SANDBAR_PROJECTS_DIR（per-key 源根）
        self.dsh = self.tmp / "dsh"         # = DSH_HOME（legacy 源 + profile/settings 源）
        self.home = self.tmp / "home"
        self.lane = self.tmp / "lane"       # fixture 泳道（= 被测 spawn 的 cwd）
        for d in (self.root, self.dsh, self.home, self.lane):
            d.mkdir(parents=True, exist_ok=True)
        # 泳道本地 .dsh：真实流程由 spawn 准备先 mkdir 再拷凭据，直调被测函数同款前置
        (self.lane / ".dsh").mkdir(parents=True, exist_ok=True)
        self._saved = {}

    def __enter__(self):
        for k, attr in (("SANDBAR_PROJECTS_DIR", "root"), ("DSH_HOME", "dsh"),
                        ("HOME", "home")):
            self._saved[k] = os.environ.get(k)
            os.environ[k] = str(getattr(self, attr))
        return self

    def __exit__(self, *a):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- 夹具写位 ----
    def perkey(self, key="suyou", text="", mode=None):
        d = self.root / key
        d.mkdir(parents=True, exist_ok=True)
        p = d / "credentials.yaml"
        p.write_text(text, "utf-8")
        if mode is not None:
            os.chmod(p, mode)
        return p

    def legacy(self, text="", mode=None):
        p = self.dsh / ".credentials.yaml"
        p.write_text(text, "utf-8")
        if mode is not None:
            os.chmod(p, mode)
        return p

    def dst(self):
        """泳道暂存快照路径（<lane>/.dsh/.credentials.yaml）。"""
        return self.lane / ".dsh" / ".credentials.yaml"

    def write_dst(self, text, mode=None):
        self.dst().parent.mkdir(parents=True, exist_ok=True)
        self.dst().write_text(text, "utf-8")
        if mode is not None:
            os.chmod(self.dst(), mode)
        return self.dst()
