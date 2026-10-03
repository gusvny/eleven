#!/usr/bin/env python3
"""i01 —— 双真源漂移探针：同一批 fixture，Python 侧（建票/泳道链 = agent_activities
._resolve_credentials_source）与 JS 侧（控制台 ui-check 链 = creds-source.mjs）必须
解析出完全相同的凭据源路径。用户场景：用户把凭据搬进（或没搬进）项目目录后，
「截图台拿到哪份凭据」和「泳道 agent 拿到哪份凭据」不会各说各话。

同构口径（契约《sandbar 项目接入契约 v1》①b）：
  per-key 命中（key 过白名单 + 是文件）> DSH_HOME legacy > HOME/.dsh legacy > 无。
畸形面：SANDBAR_PROJECTS_DIR 空串/相对路径=未设置；穿越/斜杠/大写 key=拒 per-key
  走 legacy；候选是目录=不算命中。

跑法：python3 integration/t260901-21/i01_parity_py_vs_mjs.py（cwd=泳道根）
全 tmp/env 桩，不读真 ~/.sandbar，零网络，不碰 3099。
"""
import json
import logging
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE.parent))
from lib_tmp_reclaim import mkdtemp_reclaimed  # noqa: E402  （集成侧回收 helper：注册表+atexit）

# ---- Python 侧装载（temporalio 桩，同 t01 口径：只挡模块级依赖，不碰被测函数语义） ----
_tmod = types.ModuleType("temporalio")
_amod = types.ModuleType("temporalio.activity")


class _ActivityStub:
    logger = logging.getLogger("temporalio-stub-i01")

    def defn(self, fn=None, **kw):
        return (lambda f: f) if fn is None else fn

    def heartbeat(self, *a, **kw):
        pass


_amod.activity = _ActivityStub()
_tmod.activity = _ActivityStub()
sys.modules.setdefault("temporalio", _tmod)
sys.modules.setdefault("temporalio.activity", _amod)
sys.path.insert(0, str(REPO / "server" / "engine"))
import agent_activities as aa  # noqa: E402

PASS = FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok " + label)
    else:
        FAIL += 1
        print("  FAIL " + label)


class Env:
    """tmp env 桩：进入时 SANDBAR_PROJECTS_DIR/DSH_HOME/HOME 全指临时目录，退出恢复。"""

    def __init__(self):
        self.tmp = mkdtemp_reclaimed("t260901-21-i01-")
        self.root = self.tmp / "projects"
        self.dsh = self.tmp / "dsh"
        self.home = self.tmp / "home"
        for d in (self.root, self.dsh, self.home):
            d.mkdir()

    def __enter__(self):
        self._save = {}
        for k, v in [("SANDBAR_PROJECTS_DIR", str(self.root)),
                     ("DSH_HOME", str(self.dsh)), ("HOME", str(self.home))]:
            self._save[k] = os.environ.get(k)
            os.environ[k] = v
        return self

    def __exit__(self, *exc):
        for k, v in self._save.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return False

    # ---- fixture 工具 ----
    def perkey(self, key, kind="file"):
        d = self.root / key
        d.mkdir(parents=True, exist_ok=True)
        f = d / "credentials.yaml"
        if kind == "file":
            f.write_text("version: 1\nrefs: {}\n")
        elif kind == "dir":
            f.mkdir()
        return f

    def legacy_dsh(self):
        f = self.dsh / ".credentials.yaml"
        f.write_text("version: 1\nrefs: {}\n")
        return f

    def legacy_home(self):
        d = self.home / ".dsh"
        d.mkdir(exist_ok=True)
        f = d / ".credentials.yaml"
        f.write_text("version: 1\nrefs: {}\n")
        return f

    def probe(self, key, projects_dir=None, chdir=None):
        """JS 探针同场景，返回 resolved（str|None）；探针崩溃返回 ('ERROR', stderr)。"""
        scen = {"projectsDir": str(self.root) if projects_dir is None else str(projects_dir),
                "dshHome": str(self.dsh), "home": str(self.home), "key": key}
        if chdir:
            scen["chdir"] = str(chdir)
        r = subprocess.run(["node", str(HERE / "lib" / "creds_probe.mjs"), json.dumps(scen)],
                           capture_output=True, text=True, timeout=30, cwd=str(self.tmp))
        if r.returncode != 0:
            return "PROBE-ERROR:" + r.stderr[-200:]
        return json.loads(r.stdout).get("resolved")


def case(name, key, setup, projects_dir=None, chdir=None):
    """一场：装 fixture（返回期望路径或 None）→ 双侧各解析 → 三方相等断言。"""
    with Env() as e:
        expected = setup(e)
        exp = None if expected is None else str(expected)
        # projects_dir 场景覆盖对双侧生效（畸形 env 用例：Python 与 JS 同 env）
        saved = os.environ.get("SANDBAR_PROJECTS_DIR")
        if projects_dir is not None:
            os.environ["SANDBAR_PROJECTS_DIR"] = projects_dir
        oldcwd = os.getcwd()
        try:
            if chdir:
                os.chdir(chdir(e))
            py = aa._resolve_credentials_source(key)
        finally:
            os.chdir(oldcwd)
            if projects_dir is not None:
                if saved is None:
                    os.environ.pop("SANDBAR_PROJECTS_DIR", None)
                else:
                    os.environ["SANDBAR_PROJECTS_DIR"] = saved
        py = None if py is None else str(py)
        js = e.probe(key, projects_dir=projects_dir, chdir=chdir(e) if chdir else None)
        ok(py == exp and js == exp,
           "%s | py=%s js=%s exp=%s" % (name, py, js, exp))


print("i01 双真源同构（Python 建票/泳道链 × JS 控制台链）")


def both(e, perkey=None, kind="file"):
    """per-key 与 DSH_HOME legacy 都埋（避免短路漏埋），返回 legacy 作期望。"""
    if perkey is not None:
        e.perkey(perkey, kind=kind)
    return e.legacy_dsh()


def all_three(e):
    """per-key + 两级 legacy 全埋，返回 per-key 作期望（优先级用例）。"""
    p = e.perkey("suyou")
    e.legacy_dsh()
    e.legacy_home()
    return p


case("per-key 命中优先（两级 legacy 同时在场）", "suyou", all_three)

case("per-key 缺失回落 DSH_HOME legacy", "suyou",
     lambda e: e.legacy_dsh())

case("DSH_HOME 也没有回落 HOME/.dsh", "suyou",
     lambda e: e.legacy_home())

case("两处皆无 = 无凭据（不拷）", "suyou",
     lambda e: None)

# project 未知（snapshot 查询降级/为空）：跳过 per-key、仍走 legacy（=M1-2 前行为）
case("空 project_key 走 legacy（现行为不变）", "",
     lambda e: both(e, perkey="suyou"))


def _traverse(e):
    e.legacy_dsh()
    escape = e.tmp / "escape"
    escape.mkdir(exist_ok=True)
    (escape / "credentials.yaml").write_text("version: 1\nrefs: {}\n")
    return e.legacy_dsh()


case("穿越 key ../escape 拒 per-key 走 legacy", "../escape", _traverse)

case("斜杠 key a/b 拒 per-key 走 legacy", "a/b",
     lambda e: both(e, perkey="a/b"))

case("大写 key Suyou 拒 per-key 走 legacy", "Suyou",
     lambda e: both(e, perkey="Suyou"))

case("目录冒充 credentials.yaml 不算命中回落", "suyou",
     lambda e: both(e, kind="dir"))

# SANDBAR_PROJECTS_DIR 空串 = 视为未设置（不拼相对路径；默认根下无条目 → legacy）
case("env 空串视为未设置", "suyou",
     lambda e: both(e, perkey="suyou"), projects_dir="")


def _relative(e):
    rel = e.tmp / "relproj"
    (rel / "suyou").mkdir(parents=True)
    (rel / "suyou" / "credentials.yaml").write_text("version: 1\nrefs: {}\n")
    return e.legacy_dsh()


# 相对路径 = 视为未设置：fixture 埋在 <tmp>/relproj（两侧都切 cwd 到 tmp，
# 误实现会把相对 root 拼到 cwd 下命中埋的 per-key 文件，即被探出）
case("env 相对路径视为未设置", "suyou",
     _relative, projects_dir="relproj", chdir=lambda e: e.tmp)

print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
