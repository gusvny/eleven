# -*- coding: utf-8 -*-
"""t260902-02 集成测试集共享 fixture（黑盒视角，integration/t260902-02/lib）。

职责：
- temporalio 模块级桩：agent_activities 顶层 `from temporalio import activity`，
  本机顶层 python3 无 SDK 时也能直测纯函数/activity（同 t260901-21 制式）；
- Sandbox：SANDBAR_PROJECTS_DIR/HOME 指向 mkdtemp，绝不触真 ~/.sandbar；
- make_lane：按契约 ①c 造「带 .suyou/.dsh 的 fixture 泳道」，含排除项诱饵；
- invoke_*：对 activity 入参 dataclass 名做候选适配（只桥接命名，不碰语义），
  断言全部落在文件系统/CLI 行为上；
- Ledger：stdout 末行 SUMMARY pass/skip/fail（integration/README.md 执行契约）。
"""
import dataclasses
import inspect
import json
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
VENV_PY = POC / ".venv" / "bin" / "python"
CLIENT_PY = POC / "client.py"


# ---------------------------------------------------------------- env / 模块桩
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


def load_module(name):
    stub_temporalio()
    if str(POC) not in sys.path:
        sys.path.insert(0, str(POC))
    import importlib
    return importlib.import_module(name)


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
            print("  FAIL %s%s" % (label, (" | " + detail) if detail else ""))

    def skip1(self, label, reason):
        self.s += 1
        print("  skip %s | %s" % (label, reason))

    def finish(self):
        print("SUMMARY pass=%d skip=%d fail=%d" % (self.p, self.s, self.f))
        return 1 if self.f else 0


class Sandbox:
    """tmp env 桩：SANDBAR_PROJECTS_DIR/HOME 指向临时目录。"""

    KEYS = ("SANDBAR_PROJECTS_DIR", "HOME")

    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="integ-t260902-02-"))
        self.root = self.tmp / "projects"   # = SANDBAR_PROJECTS_DIR
        self.home = self.tmp / "home"
        for d in (self.root, self.home):
            d.mkdir(parents=True, exist_ok=True)
        self._saved = {}

    def __enter__(self):
        for k, v in [( "SANDBAR_PROJECTS_DIR", str(self.root)), ("HOME", str(self.home))]:
            self._saved[k] = os.environ.get(k)
            os.environ[k] = v
        return self

    def __exit__(self, *a):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def archive_dir(self, key, ticket):
        return self.root / key / "data" / "tickets" / ticket

    def manifest(self, key, ticket):
        p = self.archive_dir(key, ticket) / "archive.json"
        return json.loads(p.read_text("utf-8")) if p.is_file() else None

    def files_under(self, d):
        d = Path(d)
        return sorted(str(p.relative_to(d)) for p in d.rglob("*") if p.is_file())


def make_lane(sb, lane_name="lane1", with_sessions=True, with_shots=True,
              bad_stage=False, no_stage=False):
    """造 fixture 泳道（结构对齐本仓真实泳道：.suyou/ + .dsh/）。

    排除项诱饵（agent_*.log / model_patch_*.yml / resume_patch_*.yml /
    .dsh/.credentials.yaml）照放——契约要求它们绝不入档，测试据此断言。
    """
    lane = sb.tmp / lane_name
    su = lane / ".suyou"
    su.mkdir(parents=True)
    if not no_stage:
        (su / "stage_create_plan_gen0.json").write_text(
            json.dumps({"status": "ok", "summary": "fixture"}, ensure_ascii=False), "utf-8")
        (su / "stage_review_plan_gen0.json").write_text(
            json.dumps({"status": "ok"}, ensure_ascii=False), "utf-8")
    if bad_stage:
        (su / "stage_implement_gen0.json").write_text('{"broken": ', "utf-8")
    if with_shots:
        sh = su / "screenshots"
        sh.mkdir(exist_ok=True)
        (sh / "shot-1.png").write_bytes(b"\x89PNG\r\n\x1a\nfixture-png-bytes")
    # —— 排除项诱饵 ——
    (su / "agent_create_plan_gen0.log").write_text("worker log line\n", "utf-8")
    (su / "model_patch_create_plan_gen0.yml").write_text("patch: x\n", "utf-8")
    (su / "resume_patch_create_plan_gen0.yml").write_text("resume: y\n", "utf-8")
    dsh = lane / ".dsh"
    dsh.mkdir(parents=True, exist_ok=True)
    if with_sessions:
        sess = dsh / "sessions" / "--Users-user-repo-slug--"
        sess.mkdir(parents=True)
        (sess / "events.jsonl").write_text('{"e":1}\n', "utf-8")
    (dsh / ".credentials.yaml").write_text("token: secret-do-not-archive\n", "utf-8")
    (dsh / "settings.yaml").write_text("editor: x\n", "utf-8")
    return lane


# ---------------------------------------------------------------- activity 调用适配
def _find_input_cls(mod, candidates):
    for n in candidates:
        c = getattr(mod, n, None)
        if c is not None and hasattr(c, "__dataclass_fields__"):
            return c
    return None


def _build(cls, superset):
    if cls is None:
        return None
    fields = cls.__dataclass_fields__
    kw = {k: v for k, v in superset.items() if k in fields}
    missing = [f for f, d in fields.items()
               if f not in kw
               and d.default is dataclasses.MISSING
               and d.default_factory is dataclasses.MISSING]
    if missing:
        raise TypeError("入参 %s 缺必填字段 %s（适配器 superset 不够）" % (cls.__name__, missing))
    return cls(**kw)


def call_maybe_async(res):
    if inspect.isawaitable(res):
        import asyncio
        return asyncio.get_event_loop().run_until_complete(res)
    return res


def invoke_archive(aa, *, ticket_id, project_key, worktree, meta):
    """archive_ticket activity：dataclass 名候选 + kwargs 回落。"""
    sup = dict(ticket_id=ticket_id, project_key=project_key,
               worktree=str(worktree), lane=str(worktree), meta=meta, base_ref="")
    cls = _find_input_cls(aa, ("ArchiveTicketArgs", "ArchiveArgs", "ArchiveInput",
                               "ArchiveTicketInput", "TicketArchiveArgs"))
    arg = _build(cls, sup) if cls else None
    return call_maybe_async(aa.archive_ticket(arg) if arg is not None else aa.archive_ticket(**sup))


def invoke_squash_merge(aa, repo, wt, branch, ticket_id, defer):
    """_squash_merge：兼容「纯函数位参」与「args 对象」两种签名（defer=None=模拟存量旧输入）。"""
    fn = aa._squash_merge
    params = list(inspect.signature(fn).parameters)
    cls = _find_input_cls(aa, ("MergeArgs",))
    if cls is not None and params and params[0] in ("args", "merge_args"):
        sup = dict(ticket_id=ticket_id, worktree=str(wt), branch=branch,
                   base_ref="", defer_teardown=bool(defer))
        return fn(_build(cls, sup))
    kwargs = {}
    if "defer_teardown" in params:
        kwargs["defer_teardown"] = bool(defer)
    return fn(Path(repo), Path(wt), branch, ticket_id, **kwargs)


def invoke_teardown(aa, repo, wt, branch, ticket_id):
    """teardown_lane activity：找不到即 AttributeError（实现未落，测试如实红）。"""
    fn = getattr(aa, "teardown_lane", None) or getattr(aa, "_teardown_lane", None)
    if fn is None:
        raise AttributeError("teardown_lane 不存在（implement 未落？）")
    sup = dict(ticket_id=ticket_id, worktree=str(wt), branch=branch,
               repo=str(repo), base_ref="")
    cls = _find_input_cls(aa, ("TeardownLaneArgs", "LaneTeardownArgs",
                               "TeardownArgs", "TeardownInput", "MergeArgs"))
    if cls is not None:
        return call_maybe_async(fn(_build(cls, sup)))
    try:
        return call_maybe_async(fn(str(repo), str(wt), branch, ticket_id))
    except TypeError:
        return call_maybe_async(fn(str(wt), branch))


# ---------------------------------------------------------------- e2e 公共件
def ensure_sdk():
    """保证当前解释器有 temporalio：顶层没有则 re-exec 进 temporal-poc venv。

    返回 (python_executable, error)；error 非空 = 无 SDK 可用，调用方应 SKIP。
    """
    try:
        import temporalio  # noqa: F401
        return sys.executable, ""
    except ImportError:
        pass
    if VENV_PY.is_file():
        if os.environ.get("_T26090202_REEXEC") != "1":
            os.environ["_T26090202_REEXEC"] = "1"
            os.execv(str(VENV_PY), [str(VENV_PY), os.path.abspath(__file__)] + sys.argv[1:])
        return str(VENV_PY), ""
    return None, "temporalio SDK 不可用（顶层 python3 与 %s 均无）" % VENV_PY


def test_env_guard():
    """测试环境红线（integration/README.md）：必须显式指向非生产 Temporal。"""
    host = (os.environ.get("SUYOU_TARGET_HOST") or "").strip()
    if not host:
        return "SUYOU_TARGET_HOST 未显式设置（生产缺省 127.0.0.1:7233 拒绝连）"
    if host == "127.0.0.1:7233":
        return "SUYOU_TARGET_HOST=127.0.0.1:7233 是生产缺省，拒绝执行"
    return ""


def run_client(args, env_extra):
    """以子进程跑 client.py（真 CLI 黑盒），返回 CompletedProcess。"""
    env = dict(os.environ)
    env.update(env_extra)
    py = sys.executable
    return subprocess.run([py, str(CLIENT_PY)] + args, cwd=str(REPO),
                          env=env, capture_output=True, text=True, timeout=180)
