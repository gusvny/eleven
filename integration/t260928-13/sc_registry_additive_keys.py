#!/usr/bin/env python3
"""sc_registry_additive_keys.py — integration scenario for the t260928-13 event
ledger's DECLARATION face (the outage found right after the merge).

Grey-box L2, offline, seconds-scale, zero docker, zero Temporal, zero console.

Run (cwd = repo root):
  PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3
  PYTHONPYCACHEPREFIX=out/pycache "$PY" -B integration/t260928-13/sc_registry_additive_keys.py

Three-exit contract: PASS=0 / FAIL=1 / ENV_FAIL=2 (no SKIP).

WHY THIS EXISTS (host-reported, 260928): the ledger's switch is a machine-level
declaration (`~/.sandbar/projects/<key>/project.yaml` top-level `event_ledger:`).
The moment that key was actually written, the registry loader's top-level
whitelist (schema:/project:/paths:/admin_log:) rejected the entry, the whole
`sandbar` entry got quarantined, and the project group vanished from the
console's left column (a red "registry entry quarantined" row stood in its
place). The merge itself was green everywhere — because the failure needs the
DECLARATION to exist, and the declaration lives outside every write set and
every test fixture. So the missing lock is a cross-module one: **every top-level
section that an engine config reader consumes must be tolerated by the one
registry loader**. That is A2 below, and it is derived automatically, so the
next new key cannot silently repeat this outage.

Precedent: this is the SECOND occurrence (admin_log: had to teach the loader the
same lesson in t260916-21). Hence a scenario, not a one-off test.

Intent locked here (user-perceivable contract):
- a project.yaml in the engine's real declaration shape (schema:/project:/
  paths:/event_ledger:) loads: the project stays visible/usable, quarantine empty;
- the loader tolerates every top-level section any engine reader reads
  (derived from the readers' own source) — the anti-outage lock;
- a genuinely broken entry is still refused LOUDLY and precisely (file:line +
  the allowed set) while the other projects keep loading, and the quarantine
  data source the console renders (dir + error) is present — partial breakage is
  never a silent "the project just isn't there";
- the real machine registry (read-only) does not quarantine the engine-owner
  entry — the exact symptom the host hit.

Out of scope (deliberately): making the loader tolerant of ANY unknown key.
The whitelist is intentional (typos must be caught); what must not happen is a
key the ENGINE ITSELF declares falling outside it. If a future ruling wants
blanket tolerance, leg A3's wording changes with the design - not silently.
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
ENGINE = ROOT / "server/engine"

PASS = 0
FAIL = 0
NA = 0
TOTAL_LEGS = 4

#: 注册表顶层段的「读者」惯用形：audit.py 的 admin_log: / event_ledger.py 的
#: event_ledger:——本锁从读者源码自动派生，新增第三个读者无需改本文件。
READER_KEY_RE = re.compile(r"in_block\s*=\s*\(\s*\w+\s*==\s*'([a-z_]+):'\s*\)")
#: 派生面（读者模块白名单；新增「读 project.yaml 顶层段」的模块要加进来）
READER_MODULES = ("audit.py", "event_ledger.py")


def ok(cond, label: str) -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✓ %s" % label)
    else:
        FAIL += 1
        print("  ✗ %s" % label)


def section(title: str) -> None:
    print("\n%s" % title)


def na(reason: str) -> None:
    global NA
    NA += 1
    print("N/A: %s" % reason)


def _main_checkout_root(tree_root: Path) -> Path:
    """本仓「主 checkout」根——身份解析用，与场景跑在哪棵树无关。

    基线探针会把本场景放进 /tmp 下的临时 detached worktree 跑（verify_lane 的
    _run_baseline，只软链依赖不保路径）。原先拿当前树路径认「引擎所属条目」，
    临时树永远落在所有项目 dirs 之外 → 该子用例在基线通道 100% 假红（主干明明绿），
    既有 flaky 统计失真，也污染红绿归属（把主干绿记成主干红）。git 共享目录
    （.git 是目录即主树；worktree 形态 .git 是文件，gitdir: 指到
    <主根>/.git/worktrees/<name>）的父目录=主 checkout 根：主树 / 泳道
    worktree / 基线临时树三种跑法同一答案。解析失败=回退当前树（旧口径），
    不猜。"""
    dot = tree_root / ".git"
    try:
        if dot.is_dir():
            return tree_root
        if dot.is_file():
            raw = dot.read_text().strip()
            if ":" in raw:
                gd = Path(raw.split(":", 1)[1].strip())
                if not gd.is_absolute():
                    gd = tree_root / gd
                if gd.parent.name == "worktrees" and gd.parent.parent.name == ".git":
                    return gd.parent.parent.parent
    except Exception:                            # noqa: BLE001
        pass
    return tree_root


def _load_shared():
    """装载引擎注册表单一真源（shared.py 只依赖 stdlib，可独立加载）。"""
    spec = importlib.util.spec_from_file_location("sc_reg_shared",
                                                 ENGINE / "shared.py")
    if spec is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["sc_reg_shared"] = mod      # py3.9 dataclass 反查 sys.modules
    spec.loader.exec_module(mod)
    return mod


def _decl_text(key: str, name: str, dirs: str, extra: str = "") -> str:
    """引擎真形声明（schema v1 + project 条目 + paths 段 [+ 待验顶层段]）。

    paths 段按 ①d 真形写（两空格缩进的 key: value，不是列表——260928 自证踩过：列表形态
    被 ①d 正当拒收，与本次要验的「additive 段容忍」无关，属夹具造错）。
    extra 里的段按真形态给（例如 event_ledger: 下带 enabled/keep_days/max_mb 缩进块）
    ——缩进块的形状属于该段的读者，装载器只容忍其存在。"""
    return ("schema: v1\n"
            "project:\n  - key: %s\n    name: %s\n    dirs:\n      - %s\n"
            "paths:\n  dsh_bin: /bin/sh\n%s" % (key, name, dirs, extra))


def _scan(tmp_root: Path, shared_mod):
    """走唯一装载器扫一个临时注册根（env 隔离，语义同真机）。"""
    old = os.environ.get("SANDBAR_PROJECTS_DIR")
    os.environ["SANDBAR_PROJECTS_DIR"] = str(tmp_root)
    try:
        return shared_mod.load_projects_registry()
    finally:
        if old is None:
            os.environ.pop("SANDBAR_PROJECTS_DIR", None)
        else:
            os.environ["SANDBAR_PROJECTS_DIR"] = old


def _derived_reader_keys() -> list:
    keys = []
    for name in READER_MODULES:
        p = ENGINE / name
        if not p.exists():
            continue
        for m in READER_KEY_RE.finditer(p.read_text("utf-8")):
            k = m.group(1)
            if k not in keys:
                keys.append(k)
    return keys


shared = _load_shared()
if shared is None:
    print("ENV_FAIL: 装载器缺席 server/engine/shared.py（无法验证注册契约）")
    sys.exit(2)

section("A1 引擎真形声明端到端可装载（用户可感知：项目还在左栏）")
with tempfile.TemporaryDirectory() as td:
    root = Path(td) / "projects"
    entry = root / "probe-owner"
    entry.mkdir(parents=True)
    (entry / "project.yaml").write_text(
        _decl_text("probe-owner", "probe-owner", str(ROOT),
                   "event_ledger:\n  enabled: true\n  keep_days: 14\n  max_mb: 512\n"),
        "utf-8")
    projects, quarantined = _scan(root, shared)
    keys = [p.get("key") for p in projects]
    ok(keys == ["probe-owner"], "真形声明条目被注册（可用=%s）" % keys)
    ok(not quarantined, "零隔离（隔离=%s）" % [q.get("error") for q in quarantined])

section("A2 一致性锁：引擎读者认的每个顶层段都必须被**每个条目读面**容忍（反停机锁）")
reader_keys = _derived_reader_keys()
ok(bool(reader_keys), "从读者源码派生出顶层段清单（空=闸空转，防假绿）：%s" % reader_keys)


def _face_loader(root, key):
    """读面 ①：注册表装载器（控制台/正式入口的数据源）。"""
    projects, quarantined = _scan(root, shared)
    if quarantined:
        return False, "装载器隔离：%s" % str(quarantined[0].get("error"))[:90]
    return [p.get("key") for p in projects] == [key], "装载器可用=%s" % [p.get("key") for p in projects]


def _face_paths(root, key):
    """读面 ②：契约 ①d 的 paths 解析器（project_paths → dsh_bin/roles/routes 全族；
    它红=该项目 agent 一律 spawn 不出来——260928 实案：票 t260928-20 一开就 blocked）。"""
    old = os.environ.get("SANDBAR_PROJECTS_DIR")
    os.environ["SANDBAR_PROJECTS_DIR"] = str(root)
    try:
        shared.project_paths(key)
    except Exception as exc:                                    # noqa: BLE001
        return False, "①d 抛错：%r" % (exc,)
    finally:
        if old is None:
            os.environ.pop("SANDBAR_PROJECTS_DIR", None)
        else:
            os.environ["SANDBAR_PROJECTS_DIR"] = old
    return True, "①d 解析 OK"


# 读面条目表：新增读面（含 TS 镜像那类）必须加进来——本表就是「同契约有几份读面」的台账。
# TS 侧（server/project-registry.ts）另有自己的派生式锁：workbench/tests/registry-loader.mjs 第 11 段。
FACES = (("装载器", _face_loader), ("①d paths 解析器", _face_paths))

for key in reader_keys:
    for face_name, face in FACES:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "projects"
            # 目录名/key 必须过 key 白名单（小写/数字/中划线）——段名带下划线，故条目
            # 用中性名，被验的是「该段在不在每个读面的容忍面里」，不是条目命名。
            entry = root / "probe-entry"
            entry.mkdir(parents=True)
            (entry / "project.yaml").write_text(
                _decl_text("probe-entry", "probe-entry", str(ROOT),
                           "%s:\n  enabled: true\n  keep_days: 14\n" % key), "utf-8")
            good, detail = face(root, "probe-entry")
            ok(good, "读者段 %s × 读面 %s：容忍（引擎自己声明的键不放倒自己的注册条目）%s"
               % (key, face_name, "" if good else "—— " + detail))

section("A3 真坏条目仍被精确拒收 + 隔离面取数（不静默消失）")
with tempfile.TemporaryDirectory() as td:
    root = Path(td) / "projects"
    good = root / "probe-good"
    bad = root / "probe-bad"
    good.mkdir(parents=True)
    bad.mkdir(parents=True)
    (good / "project.yaml").write_text(
        _decl_text("probe-good", "probe-good", str(ROOT)), "utf-8")
    (bad / "project.yaml").write_text(
        _decl_text("probe-bad", "probe-bad", str(ROOT), "no_such_section:\n  x: 1\n"),
        "utf-8")
    projects, quarantined = _scan(root, shared)
    ok([p.get("key") for p in projects] == ["probe-good"],
       "坏条目不影响好条目（部分隔离 fail-soft）")
    ok(len(quarantined) == 1, "坏条目进隔离清单（隔离面在场，控制台红行有源）")
    if quarantined:
        err = str(quarantined[0].get("error") or "")
        ok("project.yaml:" in err and "顶层只认" in err,
           "隔离原因点名 file:line 与允许集（报错精确，可自修）：%s" % err[:110])
        ok(str(quarantined[0].get("dir") or "").endswith("probe-bad"),
           "隔离条目带 dir（渲染锚在场）")

section("A4 真机面（只读）：引擎所属条目不得被隔离")
real_root = Path(os.environ.get("SANDBAR_PROJECTS_DIR")
                 or (Path.home() / ".sandbar" / "projects"))
if not real_root.is_dir():
    na("真注册表根不可读：%s（系统状态面，非环境缺失）" % real_root)
else:
    try:
        projects, quarantined = _scan(real_root, shared)
    except Exception as exc:                        # noqa: BLE001
        ok(False, "真机注册表扫描抛错：%r" % (exc,))
    else:
        keys = [p.get("key") for p in projects]
        ok(bool(keys), "真机注册表有可用条目（%s）" % keys)
        q_dirs = [str(q.get("dir") or "") for q in quarantined]
        ok(not q_dirs, "真机零隔离（隔离=%s）" % q_dirs)
        # 身份根=主 checkout（见 _main_checkout_root）：基线临时树里的跑法也认得
        # 出自己是哪个项目的引擎，该子用例只对产品事实红（条目真被隔离/真消失）。
        id_root = _main_checkout_root(ROOT)
        owners = [p.get("key") for p in projects
                  if any(str(d).rstrip("/") == str(id_root) or str(id_root).startswith(str(d).rstrip("/") + "/")
                         for d in (p.get("dirs") or []))]
        ok(bool(owners), "引擎所属条目在可用清单里（宿主症状「sandbar 不显示」的机器级回归锁；命中=%s，身份根=%s）"
           % (owners, id_root))

print("\n==== summary: PASS=%d FAIL=%d NA=%d" % (PASS, FAIL, NA))
if NA >= TOTAL_LEGS:
    print("FAIL: 全部子用例 N/A——场景无可验对象（设计/覆盖问题，修场景而非补环境）")
    sys.exit(1)
sys.exit(1 if FAIL else 0)
