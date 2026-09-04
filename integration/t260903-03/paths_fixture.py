# t260903-03 共享夹具（非 sc_ 前缀 = 共享/子检查代码，不入 SCENARIOS 清单）。
# 供 sc_paths_spawn_seam.py / sc_paths_failclosed_red.py 复用：tmp 注册表（SANDBAR_PROJECTS_DIR）、
# 条目 project.yaml 手写桩、spawn 缝隙调用、cmd --patch 观测。只用标准库。
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
POC = REPO / "server" / "dsh" / "temporal-poc"
DOC_CONTRACT = REPO / "docs" / "design" / "sandbar项目接入契约v1.md"
ROLE = "reviewer"


def poc_sys_path():
    if str(POC) not in sys.path:
        sys.path.insert(0, str(POC))


def import_engine():
    """import agent_activities（需 temporalio SDK，venv 里有）。ImportError 由调用方转 SKIP。"""
    poc_sys_path()
    import agent_activities  # noqa: F401
    return agent_activities


def import_shared():
    poc_sys_path()
    import shared
    return shared


class Registry:
    """SANDBAR_PROJECTS_DIR 指向 tmp 根（绝对路径，perkey_projects_root 只认绝对）；
    退出还原 env 并清 tmp。"""

    def __enter__(self):
        self.root = Path(tempfile.mkdtemp(prefix="t26090303-reg-"))
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

    def write_entry(self, key, dirs, paths_lines=None, raw=None):
        """手写 per-key 条目（契约①a 形状 + 可选 paths 节）。raw 非 None 时原样写入（坏文件桩）。"""
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


def mk_ws():
    return Path(tempfile.mkdtemp(prefix="t26090303-ws-"))


def mk_legacy_roles(ws, role=ROLE):
    """现行约定位置放角色 preset（回落态/对抗对照用）。"""
    d = ws / "server" / "dsh" / "roles"
    d.mkdir(parents=True, exist_ok=True)
    f = d / (role + ".yml")
    f.write_text("persona: legacy-roles-marker\n", encoding="utf-8")
    return f


def write_routes_table(path, provider, model, role=ROLE):
    """model-routes.yaml 形状桩（roles.<role> 命中链，见 shared.model_route_for 消费口径）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "roles:\n  %s:\n    provider: %s\n    model: %s\n"
        "default:\n  provider: %s\n  model: %s\n" % (role, provider, model, provider, model),
        encoding="utf-8")
    return path


def write_empty_routes_table(path):
    """roles 与 default 皆空 → 任何 role 查不到 → None（软语义桩）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("roles: {}\ndefault: {}\n", encoding="utf-8")
    return path


class PatchedRoutesFile:
    """把回落单源常量 MODEL_ROUTES_FILE 指 tmp 桩（观测回落读的是常量这一件事）；退出还原。"""

    def __init__(self, path):
        self.path = Path(path)

    def __enter__(self):
        shared = import_shared()
        self._mod = shared
        self._old = shared.MODEL_ROUTES_FILE
        shared.MODEL_ROUTES_FILE = self.path
        return self

    def __exit__(self, *exc):
        self._mod.MODEL_ROUTES_FILE = self._old
        return False


_SPAWN_SEQ = iter(range(10000))


def spawn(ws, role=ROLE, kind="", project="", tag="sc"):
    """spawn 缝隙唯一入口：_prepare_agent_spawn(cwd=ws, ...) → (cmd, env)，artifacts 落 ws 内。
    每次调用独立 artifacts 子目录——防跨调用遗留 patch 文件互相污染观测。"""
    aa = import_engine()
    art = ws / ".artifacts" / ("%s-%d" % (tag, next(_SPAWN_SEQ)))
    art.mkdir(parents=True, exist_ok=True)
    cmd, env = aa._prepare_agent_spawn(
        cwd=ws, role=role, kind=kind, ticket_id="t260903-03",
        artifacts_dir=art, tag=tag, project=project)
    return cmd, env, art


def patch_paths(cmd):
    return [cmd[i + 1] for i, a in enumerate(cmd) if a == "--patch"]


def patches_ending(cmd, suffix):
    return [p for p in patch_paths(cmd) if p.endswith(suffix)]


def model_patch_files(art):
    return sorted(art.glob("model_patch_*.yml"))


def model_patch_text(art):
    fs = model_patch_files(art)
    return fs[0].read_text(encoding="utf-8") if fs else ""
