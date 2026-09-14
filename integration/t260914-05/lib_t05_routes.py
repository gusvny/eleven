#!/usr/bin/env python3
"""t260914-05 共享夹具（非 sc_ 前缀 = 共享代码，不入 SCENARIOS 清单，lint L5 视其为共享面）。

职责只含前置/基础步骤（各场景自持断言；步骤级复用不构成 intent 重复）：
  ① 路径与解释器解析；② 临时注册表（SANDBAR_PROJECTS_DIR）+ 路由表桩；
  ③ spawn 缝隙直调 + 告警捕获（引擎单点告警与消费方点名同缝捕获）；
  ④ 三态出口（PASS/FAIL 计数、ENV_FAIL 退 2、N/A 只留给系统状态腿）。

为何自持而不复用 integration/t260903-03/paths_fixture.py：本票 implement 段要重写那份夹具
（PatchedRoutesFile 随 MODEL_ROUTES_FILE 常量退场），契约网不能被夹具重构带倒——灰盒纪律
要求断言只落公开可感行为，不落他票夹具的内部形状。

零真环境写：注册表/项目树/表桩全在 tmp；不碰 3099/7233；不写仓库任何文件。
"""
from __future__ import annotations

import contextlib
import io
import logging
import os
import pathlib
import shutil
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[2]
POC = REPO / "server" / "engine"
SCENARIO = "t260914-05"

_SEQ = iter(range(100000))


def engine_python() -> str:
    """引擎 venv 优先（PyYAML/temporalio 齐全），缺席回落当前解释器。"""
    p = POC / ".venv" / "bin" / "python"
    return str(p) if p.exists() else sys.executable


def import_shared():
    if str(POC) not in sys.path:
        sys.path.insert(0, str(POC))
    import shared  # noqa: E402
    return shared


def import_engine():
    """agent_activities（spawn 缝隙；需 temporalio）——ImportError 由调用方转 ENV_FAIL 退 2。"""
    if str(POC) not in sys.path:
        sys.path.insert(0, str(POC))
    import agent_activities  # noqa: E402
    return agent_activities


class Registry:
    """SANDBAR_PROJECTS_DIR 指向 tmp 根（绝对路径），退出还原并清理。"""

    def __enter__(self):
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="t26091405-reg-"))
        self._old = os.environ.get("SANDBAR_PROJECTS_DIR")
        os.environ["SANDBAR_PROJECTS_DIR"] = str(self.root)
        return self

    def __exit__(self, *exc):
        if self._old is None:
            os.environ.pop("SANDBAR_PROJECTS_DIR", None)
        else:
            os.environ["SANDBAR_PROJECTS_DIR"] = self._old
        shutil.rmtree(self.root, ignore_errors=True)
        return False

    def entry(self, key, dirs, paths_lines=None, raw=None):
        """手写 per-key 条目（契约①a 形状 + 可选 paths 节）。"""
        d = self.root / key
        d.mkdir(parents=True, exist_ok=True)
        if raw is not None:
            text = raw
        else:
            text = "schema: v1\nproject:\n  - key: %s\n    name: %s\n    dirs:\n" % (key, key)
            text += "".join("      - %s\n" % x for x in dirs)
            if paths_lines:
                text += "paths:\n" + "".join("  %s: %s\n" % kv for kv in paths_lines)
        p = d / "project.yaml"
        p.write_text(text, encoding="utf-8")
        return p


def mk_ws(prefix="t26091405-ws-"):
    return pathlib.Path(tempfile.mkdtemp(prefix=prefix))


def write_table(path, provider, model, role="developer", extra_roles=None, default=True):
    """表桩：roles.<role>（+可选他角色）+ default（两处同值，命中链任一支都指向同值）。"""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "roles:\n  %s:\n    provider: %s\n    model: %s\n" % (role, provider, model)
    for r, (pv, md) in (extra_roles or {}).items():
        text += "  %s:\n    provider: %s\n    model: %s\n" % (r, pv, md)
    if default:
        text += "default:\n  provider: %s\n  model: %s\n" % (provider, model)
    path.write_text(text, encoding="utf-8")
    return path


def spawn(ws, *, project="", role="developer", kind="", tag="s", artifacts=None):
    """spawn 缝隙唯一入口：_prepare_agent_spawn → (cmd, env, artifacts_dir)。

    每次独立 artifacts 子目录（防跨调用遗留 patch 互相污染观测）。"""
    aa = import_engine()
    art = pathlib.Path(artifacts) if artifacts else \
        (pathlib.Path(ws) / ".artifacts" / ("%s-%d" % (tag, next(_SEQ))))
    art.mkdir(parents=True, exist_ok=True)
    cmd, env = aa._prepare_agent_spawn(
        cwd=pathlib.Path(ws), role=role, kind=kind, ticket_id=SCENARIO,
        artifacts_dir=art, tag=tag, project=project)
    return cmd, env, art


def patch_paths(cmd):
    return [cmd[i + 1] for i, a in enumerate(cmd) if a == "--patch"]


def model_patch_files(art):
    return sorted(pathlib.Path(art).glob("model_patch_*.yml"))


def model_patch_text(art):
    fs = model_patch_files(art)
    return fs[0].read_text(encoding="utf-8") if fs else ""


class _RecHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, rec):
        try:
            self.lines.append(self.format(rec))
        except Exception:  # noqa: BLE001 — 观测面自身绝不抛
            pass


def _force_debug():
    """把现存 logger 全压到 DEBUG（捕获与级别无关；本场景只做文本判定）。

    返回还原表：[(logger, level)]。"""
    saved = []
    root = logging.getLogger()
    saved.append((root, root.level))
    root.setLevel(logging.DEBUG)
    for _name, lg in list(logging.root.manager.loggerDict.items()):
        if isinstance(lg, logging.Logger):
            saved.append((lg, lg.level))
            lg.setLevel(logging.DEBUG)
    return saved


def capture(fn):
    """捕获 fn() 期间的全部日志记录 + stdout/stderr 文本；返回 (result, text)。

    只用公开观测面（logging 传播 + 标准流），不 monkeypatch 引擎内部。"""
    h = _RecHandler()
    h.setLevel(logging.DEBUG)
    h.setFormatter(logging.Formatter("%(name)s %(message)s"))
    buf = io.StringIO()
    root = logging.getLogger()
    saved = _force_debug()
    root.addHandler(h)
    old_disable = logging.root.manager.disable
    logging.disable(logging.NOTSET)
    try:
        with contextlib.redirect_stderr(buf), contextlib.redirect_stdout(buf):
            res = fn()
    finally:
        root.removeHandler(h)
        logging.disable(old_disable)
        for lg, lvl in saved:
            lg.setLevel(lvl)
    return res, ("\n".join(h.lines) + "\n" + buf.getvalue())


class Checks:
    """三态出口：fail 优先（产品红不被环境红稀释）、env 退 2、na 仅系统状态腿。"""

    def __init__(self, name):
        self.name = name
        self.pass_n = 0
        self.fail_n = 0
        self.env_n = 0
        self.na_n = 0
        self.failures = []

    def ok(self, cond, label):
        if cond:
            self.pass_n += 1
            print("  PASS %s" % label, flush=True)
        else:
            self.fail_n += 1
            self.failures.append(label)
            print("  FAIL %s" % label, flush=True)

    def section(self, title):
        print("\n== %s ==" % title, flush=True)

    def env_fail(self, msg):
        self.env_n += 1
        print("ENV_FAIL: %s" % msg, flush=True)

    def finish(self):
        print("SC %s pass=%d fail=%d env_fail=%d na=%d"
              % (self.name, self.pass_n, self.fail_n, self.env_n, self.na_n), flush=True)
        if self.fail_n:
            return 1
        if self.env_n:
            return 2
        return 0
