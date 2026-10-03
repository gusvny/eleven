#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试夹具临时物料**全族**整治的定点回归（260927，承接 260926 的第一批）。

背景：260926 只修了「大产能」里点名最响的几处，260927 只读普查（$TMPDIR 顶层 145,719
条：131,940 目录 + 13,738 文件 + 41 其它）发现两件事必须一起收口：

  ① **文件族整族漏了**：上一版清扫器只碰「真目录」，而最大的几族里 `sandbar-integ-run-*.lock`
     （同泳道单飞锁档）、`sandbar-admin-log-*.log`（影子）、`sandbar-credentials-*.yaml`
     （凭据副本）、`nusuyou-integ-run-*.lock`（姊妹项目同款锁）全是**文件**——一条也删不到；  # naming-compat（姊妹项目同款前缀，非退役旧名）
  ② **「登记了但没启用」的半态**：第二批 28 个前缀只写在 `CANDIDATE_PREFIXES_BATCH2`
     常量里没进白名单，其中 `t260907-12-act-/-ch-` 两个变体被 `-ut` 前缀盖不住（存量
     6,399 个）——正是「前缀盖不住」这一类洞。

本文件钉住的六件事（每条都带**反证**：不修就该红）：
  A. 集成侧回收 helper（`integration/lib_tmp_reclaim.py`）：登记→回收→出册、幂等、
     目录与文件都管、单条失败不抛、atexit 真在、信号钩子幂等且链式不吞原处置；
  B. 三个生产者定点：`run_scenarios` 锁档（正常退出 / SIGTERM / `os._exit` 三条路径）
     与 `sc_engine_venv_compat` 的 venv 夹具——真子进程 + 私有 TMPDIR，事后零残留；
  C. 清扫器的文件族判据：目录 `rmtree` / 文件 `unlink` / 符号链接不跟 / 在用即不动
     （flock 持有的活锁档必须留下）/ 白名单外一律不碰 / 排除族永不删且计数可见；
  D. 拆台边界（`integration/stage_docker.py`）：compose down **rc!=0** 时三件 bind 物料
     **保留且具名**（既不静默也不抽活台挂载点）；
  E. 白名单单源与覆盖面：引擎判据面与清扫器同一份（既有 f1 之外的**覆盖面锁**——
     生产者字面前缀必须被白名单盖住，这条就是 260927 那类洞的机械闸）。

跑法：仓库根 `server/engine/.venv/bin/python -m pytest
server/engine/tests/test_t260927_tmp_fixture_family.py -q`（零网络、零 docker、零真 Temporal；
子进程用例只跑秒级脚本且 `$TMPDIR` / 锁档路径全指向私有目录）。
"""
from __future__ import annotations

import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

POC = Path(__file__).resolve().parent.parent          # server/engine
REPO = POC.parent.parent
INTEG = REPO / "integration"
SWEEP = INTEG / "tools" / "sweep_tmp_fixtures.py"
sys.path.insert(0, str(POC))
sys.path.insert(0, str(INTEG))

import lib_tmp_reclaim as tr  # noqa: E402
import stage_docker as sd  # noqa: E402


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sw = _load(SWEEP, "sweep_family_probe")
lw = _load(POC / "inspection_lane_watchdog.py", "lane_watchdog_family_probe")
activities = _load(POC / "activities.py", "activities_family_probe")


def _child(script: str, tmp_root: Path, env_extra=None, timeout=300):
    """私有 $TMPDIR 里真跑一段脚本（回收面只能靠真进程退出才看得出）。"""
    env = dict(os.environ, TMPDIR=str(tmp_root), PYTHONDONTWRITEBYTECODE="1")
    env.pop("SANDBAR_INTEG_ALLOW_CONCURRENT", None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run([sys.executable, "-c", script], cwd=str(REPO), env=env,
                          capture_output=True, text=True, timeout=timeout)


# ========================================================================================
# A. 集成侧回收 helper（注册表 + atexit + 信号 + 幂等）
# ========================================================================================

def test_a1_registry_reaps_dirs_and_files_and_is_idempotent(tmp_path):
    """目录与**文件**都管（锁档是文件——上一版只删目录就是漏在这里）；回收即出册、幂等。"""
    root = tmp_path / "reg"
    root.mkdir()
    before = len(tr.live_tmp_paths())
    d = tr.mkdtemp_reclaimed("t260927-family-ut-", root=str(root))
    f = root / "lock.lock"
    f.write_text("pid=1\n", encoding="utf-8")
    tr.register_tmp_path(f, label="integ-run-lock")
    assert len(tr.live_tmp_paths()) == before + 2
    out = tr.reclaim_registered()
    assert len(out["removed"]) == 2 and out["failed"] == []
    assert not d.exists() and not f.exists()
    assert tr.live_tmp_paths() == []
    assert tr.reclaim_registered() == {"removed": [], "failed": []}      # 幂等：第二次零条


def test_a2_externally_removed_entry_is_not_a_failure(tmp_path):
    """别人先删了（或 rmtree 竞态）→ 吞掉不抛、不计失败（清理面不把场景跑红）。"""
    root = tmp_path / "gone"
    root.mkdir()
    p = tr.mkdtemp_reclaimed("t260927-family-gone-", root=str(root))
    import shutil
    shutil.rmtree(str(p))
    fails = tr.REAP_FAILURES
    tr.reclaim_registered()
    assert tr.REAP_FAILURES == fails and not p.exists()


def test_a3_atexit_hook_and_signal_hook_are_really_installed():
    """进程级兜底**真在**（不是只写在注释里）：atexit 注册 + 信号钩子幂等且链式。"""
    src = (INTEG / "lib_tmp_reclaim.py").read_text(encoding="utf-8")
    assert "atexit.register(reclaim_registered)" in src
    assert "def install_signal_reclaim(" in src
    before = signal.getsignal(signal.SIGTERM)
    first = tr.install_signal_reclaim()
    assert set(first) >= {signal.SIGTERM, signal.SIGINT}
    assert tr._SIGNAL_PREV[signal.SIGTERM] == before      # 原处置被**保存**（链式用）
    assert callable(signal.getsignal(signal.SIGTERM))     # 钩子已就位
    assert tr.install_signal_reclaim() == first           # 幂等：不套娃包装
    assert set(tr._SIGNAL_PREV) >= {signal.SIGTERM, signal.SIGINT}


# ========================================================================================
# B. 生产者定点回归（真子进程；含反证）
# ========================================================================================

BARE_PROBE = ("import tempfile;tempfile.mkdtemp(prefix='venv-compat-root-bare-probe')")


def test_b0_counterproof_bare_mkdtemp_leaves_dirs(tmp_path):
    """**反证**：裸 `mkdtemp` 的子进程退出后确实留下目录——下面「零残留」不是恒真断言。"""
    root = tmp_path / "bare"
    root.mkdir()
    _child(BARE_PROBE, root)
    left = [n for n in os.listdir(root) if n.startswith("venv-compat-")]
    assert len(left) == 1 and left[0].startswith("venv-compat-root-bare-probe")


def test_b1_venv_compat_scenario_leaves_no_fixtures(tmp_path):
    """venv 兼容场景（每个子用例 2 个 mkdtemp）真跑一遍：私有 $TMPDIR 里零残留。"""
    root = tmp_path / "venvcompat"
    root.mkdir()
    p = _child("import runpy;runpy.run_path('integration/t260907-10/sc_engine_venv_compat.py',"
               "run_name='__main__')", root)
    assert p.returncode == 0, (p.stdout[-800:], p.stderr[-800:])
    assert "pass=6 fail=0" in p.stdout
    assert [n for n in os.listdir(root) if n.startswith("venv-compat-")] == []


LOCK_CHILD = """
import importlib.util, sys
spec = importlib.util.spec_from_file_location("rs_lock", "integration/run_scenarios.py")
rs = importlib.util.module_from_spec(spec); spec.loader.exec_module(rs)
fd = rs._acquire_run_lock()
assert isinstance(fd, int) and fd >= 0, "lock not acquired: %r" % (fd,)
open(__SENTINEL__, "w").write("acquired")
__TAIL__
"""


def _lock_child(sentinel, tail=""):
    """子进程脚本（占位符替换，不走 % 格式化：脚本自身含 %r 字面）。"""
    return LOCK_CHILD.replace("__SENTINEL__", repr(str(sentinel))).replace("__TAIL__", tail)


def _lock_env(tmp_path):
    return {"SANDBAR_INTEG_RUN_LOCK_PATH": str(tmp_path / "run.lock")}


def test_b2_run_lock_is_reclaimed_on_normal_exit(tmp_path):
    """同泳道单飞锁档：正常退出（atexit）后一把不留——这就是 4,076 + 1,836 个的来源。"""
    root = tmp_path / "lock1"
    root.mkdir()
    sentinel = root / "ready"
    p = _child(_lock_child(sentinel), root, _lock_env(root))
    assert p.returncode == 0, (p.stdout[-800:], p.stderr[-800:])
    assert sentinel.exists()
    assert not (root / "run.lock").exists()


def test_b3_run_lock_is_reclaimed_on_sigterm(tmp_path):
    """SIGTERM（执行器收口/宿主休眠唤醒后杀进程的形态）：锁档同回收，退出语义不变（信号死）。"""
    root = tmp_path / "lock2"
    root.mkdir()
    sentinel = root / "ready"
    script = _lock_child(sentinel, tail="import time;time.sleep(60)")
    env = dict(os.environ, TMPDIR=str(root), PYTHONDONTWRITEBYTECODE="1")
    env.pop("SANDBAR_INTEG_ALLOW_CONCURRENT", None)
    env.update(_lock_env(root))
    proc = subprocess.Popen([sys.executable, "-c", script], cwd=str(REPO), env=env)
    try:
        deadline = time.time() + 30
        while not sentinel.exists() and time.time() < deadline and proc.poll() is None:
            time.sleep(0.05)
        assert sentinel.exists(), "child never acquired the lock"
        assert (root / "run.lock").exists()
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=30) == -signal.SIGTERM      # 仍是被信号杀死（语义未被吞）
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)
    assert not (root / "run.lock").exists()


def test_b4_run_lock_is_reclaimed_on_os_exit_teardown_path(tmp_path):
    """`os._exit` 收口路径（预算耗尽 / 批台信号）：跳过 atexit，故必须显式回收——真跑那条路。"""
    root = tmp_path / "lock3"
    root.mkdir()
    sentinel = root / "ready"
    tail = ("import sys\n"
            "rs._batch_signal_teardown(15, None)\n"
            "print('unreachable')\n")
    p = _child(_lock_child(sentinel, tail=tail), root, _lock_env(root))
    assert p.returncode == 130, (p.returncode, p.stdout[-500:], p.stderr[-500:])
    assert "unreachable" not in p.stdout
    assert not (root / "run.lock").exists()


def test_b5_counterproof_bare_flock_leaves_the_lock_file(tmp_path):
    """**反证**：不走 `_acquire_run_lock` 的裸 flock 子进程退出后锁档留下——
    所以上面三条「不留」是在判回收，而不是恒真。"""
    root = tmp_path / "lock4"
    root.mkdir()
    lock = root / "run.lock"
    script = ("import fcntl, os;"
              "fd = os.open(%r, os.O_RDWR | os.O_CREAT, 0o644);"
              "fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)" % str(lock))
    p = _child(script, root)
    assert p.returncode == 0, (p.stdout[-500:], p.stderr[-500:])
    assert lock.exists()


def test_b6_static_locks_on_the_fixed_producers():
    """静态锁：三处生产者不得回退到裸 `mkdtemp` / 不回退到「零回收」。"""
    src = (INTEG / "t260907-10" / "sc_engine_venv_compat.py").read_text(encoding="utf-8")
    assert "tempfile.mkdtemp(" not in src and "mkdtemp_reclaimed(" in src
    assert "from lib_tmp_reclaim import mkdtemp_reclaimed" in src
    rs = (INTEG / "run_scenarios.py").read_text(encoding="utf-8")
    assert "register_tmp_path(path, label=\"integ-run-lock\")" in rs
    assert "install_signal_reclaim()" in rs
    # 两处 os._exit 都不许绕过回收（一处信号收口、一处预算耗尽）
    assert rs.count("reclaim_tmp_artifacts()") >= 3
    assert "batch_teardown()\n    reclaim_tmp_artifacts()\n    os._exit(130)" in rs
    assert "reclaim_tmp_artifacts()\n    try:\n        sys.stdout.flush()" in rs


# ========================================================================================
# C. 清扫器：文件族 + 排除族 + 在用即不动
# ========================================================================================

def _age(path: Path, hours: float):
    t = time.time() - hours * 3600
    os.utime(path, (t, t))


def _sweep(root: Path, *args):
    return subprocess.run([sys.executable, str(SWEEP), "--root", str(root)] + list(args),
                          cwd=str(REPO), capture_output=True, text=True, timeout=300)


def _sweep_json(root: Path, *args):
    p = _sweep(root, "--json", *args)
    return p, json.loads(p.stdout)


def _fixture_root(tmp_path: Path) -> Path:
    """私有临时根：目录族（stale/fresh）+ 文件族（stale/fresh）+ 符号链接 + 白名单外 + 排除族。"""
    root = tmp_path / "tmproot"
    root.mkdir()
    d = root / "t260907-12-act-stale"
    (d / "inner").mkdir(parents=True)
    (d / "inner" / "f.txt").write_text("x" * 200, encoding="utf-8")
    _age(d / "inner", 10)
    _age(d, 10)
    fresh = root / "t260907-12-act-fresh"
    fresh.mkdir()
    for name in ("sandbar-integ-run-dead.lock", "sandbar-admin-log-x.log",
                 "sandbar-credentials-x.yaml"):
        f = root / name
        f.write_text("y" * 100, encoding="utf-8")
        _age(f, 10)
    fresh_file = root / "sandbar-credentials-live.yaml"
    fresh_file.write_text("z" * 10, encoding="utf-8")
    (root / "outside-other-dir").mkdir()
    _age(root / "outside-other-dir", 10)
    for name in ("com.google.Chrome.Zzz", "dsh-subprocess-abc", "tmpABC123"):
        p = root / name
        p.mkdir()
        _age(p, 10)
    outside_target = root / "elsewhere-target"
    outside_target.write_text("keep me\n", encoding="utf-8")
    (root / "venv-compat-root-sym").symlink_to(outside_target)
    return root


def test_c1_dry_run_then_apply_sweeps_dirs_and_files_only(tmp_path):
    """dry-run 报数 → apply 只删「白名单 ∧ ≥6h ∧ (真目录|常规文件)」；符号链接与白名单外不动。"""
    root = _fixture_root(tmp_path)
    p, out = _sweep_json(root)
    assert out["mode"] == "dry-run" and out["swept"] == 4                    # 1 目录 + 3 文件
    assert (out["swept_dirs"], out["swept_files"]) == (1, 3)
    assert out["kept_live"] == 2                                            # 新鲜目录 + 新鲜文件
    assert out["excluded_by_prefix"]["com.google.Chrome."] == 1
    assert out["excluded_by_prefix"]["dsh-subprocess-"] == 1
    assert out["excluded_by_prefix"]["tmp"] == 1
    assert any("not followed" in s for s in out["not_swept_named"])            # 符号链接逐条点名
    assert (root / "t260907-12-act-stale").exists()                          # dry-run 不删

    p2 = _sweep(root, "--apply")
    assert p2.returncode == 0, p2.stderr[-800:]
    assert [l for l in p2.stdout.splitlines() if l.startswith("swept ")]
    assert not (root / "t260907-12-act-stale").exists()
    assert not (root / "sandbar-integ-run-dead.lock").exists()
    assert not (root / "sandbar-admin-log-x.log").exists()
    assert not (root / "sandbar-credentials-x.yaml").exists()
    left = sorted(os.listdir(root))
    assert left == ["com.google.Chrome.Zzz", "dsh-subprocess-abc", "elsewhere-target",
                    "outside-other-dir", "sandbar-credentials-live.yaml",
                    "t260907-12-act-fresh", "tmpABC123", "venv-compat-root-sym"]
    assert (root / "elsewhere-target").read_text(encoding="utf-8") == "keep me\n"


def test_c2_whitelisted_but_in_use_lock_is_kept_and_named(tmp_path):
    """**在用即不动**：白名单内的锁档若正被 flock 持有 → 保留并点名，绝不删活锁。"""
    import fcntl
    root = tmp_path / "inuse"
    root.mkdir()
    live = root / "sandbar-integ-run-live.lock"
    live.write_text("pid=me\n", encoding="utf-8")
    _age(live, 10)
    dead = root / "sandbar-integ-run-dead.lock"
    dead.write_text("pid=gone\n", encoding="utf-8")
    _age(dead, 10)
    fd = os.open(str(live), os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        p = _sweep(root, "--apply")
        assert p.returncode == 0
        assert "KEPT %s" % live.name in p.stdout
        assert live.exists() and not dead.exists()
        assert "locks kept 1" in p.stdout
    finally:
        os.close(fd)
    p2 = _sweep(root, "--apply")             # 释放后第二次即回收（不是永久豁免）
    assert not live.exists() and "locks kept 0" in p2.stdout


def test_c3_scan_never_touches_outside_or_excluded_prefixes(tmp_path):
    """白名单/precedence 的纯函数面：排除族**优先**于白名单、白名单外只计数、符号链接只点名。"""
    root = _fixture_root(tmp_path)
    sc = sw.scan(str(root), sw.TMP_FIXTURE_PREFIXES, 6.0)
    assert sc["entries"] == len(os.listdir(root))
    assert sc["excluded_count"] == 3 and sc["untouched"] == 2      # outside-other-dir + 链接目标
    assert all(e.kind in ("dir", "file") for e in sc["stale"])
    assert [e.name for e in sc["stale"]] == sorted(e.name for e in sc["stale"])
    # 排除判据在 scan 里**先于**白名单：排除表与白名单不得有交叠（交叠=判定歧义）
    assert sw.match_prefix("com.google.Chrome.X", sw.EXCLUDED_PREFIXES) == "com.google.Chrome."
    overlap = [(w, e) for w in sw.TMP_FIXTURE_PREFIXES for e in sw.EXCLUDED_PREFIXES
               if w.startswith(e) or e.startswith(w)]
    assert overlap == []
    # 反证：把排除族挪进白名单后，它**会**被判为 stale（说明排除判定真在起作用）
    probe = sw.scan(str(root), ("com.google.Chrome.",), 6.0, excluded=())
    assert len(probe["stale"]) == 1 and probe["stale"][0].name == "com.google.Chrome.Zzz"


def test_c4_sweeper_safety_gates_survive_the_file_family(tmp_path):
    """安全闸不回退：默认 dry-run、`--apply` 龄闸硬地板、白名单为空拒绝清扫、`--root` 必须存在。"""
    root = tmp_path / "gates"
    root.mkdir()
    p = _sweep(root, "--apply", "--max-age-h", "0.5")
    assert p.returncode == 2 and "REFUSED" in p.stdout
    assert "hard floor" in p.stdout
    p2 = _sweep(root, "--apply", "--prefix", "")
    assert p2.returncode == 2 and "whitelist is empty" in p2.stdout
    p3 = _sweep(tmp_path / "missing-root")
    assert p3.returncode == 2 and "not a directory" in p3.stdout


def test_c5_readonly_fixture_dirs_are_still_reclaimable(tmp_path):
    """只读形态的夹具（0555/0444）不许变成永久残留：补写位后删掉；白名单外的只读目录不动
    （260927 实测病灶：`t260925-15-inst-*` 的 `content/releases/v000001/` 是 dr-xr-xr-x，
    21 个目录因 `PermissionError: entries.json` 清扫失败而留在盘上）。"""
    import stat
    root = tmp_path / "ro"
    root.mkdir()
    d = root / "t260925-15-inst-probe"
    (d / "content" / "releases" / "v000001").mkdir(parents=True)
    (d / "content" / "releases" / "v000001" / "entries.json").write_text("x", encoding="utf-8")
    ro = d / "content" / "releases" / "v000001"
    os.chmod(ro, 0o555)
    _age(d, 10)
    outside = root / "other-ro"
    (outside / "sub").mkdir(parents=True)
    (outside / "sub" / "f").write_text("k", encoding="utf-8")
    os.chmod(outside / "sub", 0o555)
    _age(outside, 10)
    p = _sweep(root, "--apply")
    assert p.returncode == 0, p.stderr[-600:]
    assert "failed 0" in p.stdout and not d.exists()
    assert outside.is_dir()                       # 白名单外的只读目录原地不动
    assert stat.S_IMODE(os.stat(outside / "sub").st_mode) == 0o555    # 连 mode 都没碰


# ========================================================================================
# D. 拆台边界：compose down 失败 → 物料保留且具名（既不静默也不抽活台挂载点）
# ========================================================================================

def _stage_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(sd.tempfile, "gettempdir", lambda: str(tmp_path))
    paths = sd.stage_tmp_artifact_paths("utdemo")
    paths["presets"].mkdir(parents=True)
    paths["admin_log"].write_text("log\n", encoding="utf-8")
    paths["credentials"].write_text("secret\n", encoding="utf-8")
    return paths


def test_d1_down_rc_nonzero_keeps_artifacts_and_names_them(monkeypatch, tmp_path, capsys):
    """起台半途失败（compose down rc!=0）：三件物料是容器 bind 的宿主机侧 → 必须保留，
    但**保留必须可见**（260927 新增点名面；此前是静默 return：留下一地问号）。"""
    paths = _stage_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(sd, "compose_cmd",
                        lambda *a, **kw: SimpleNamespace(returncode=1, stdout="", stderr="boom"))
    sd._do_down("utdemo", {}, quiet=True)
    err = capsys.readouterr().err
    assert "STAGE_TMP_RECLAIM: kept admin_log, credentials, presets" in err
    assert "rc=1" in err
    assert paths["presets"].is_dir() and paths["admin_log"].exists()
    assert paths["credentials"].exists()


def test_d2_down_success_still_reclaims_all_three(monkeypatch, tmp_path):
    """对照面（rc=0，容器已归零）：三件物料照旧全回收——保留分支不是「一律不回收」。"""
    paths = _stage_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(sd, "compose_cmd",
                        lambda *a, **kw: SimpleNamespace(returncode=0, stdout="", stderr=""))
    sd._do_down("utdemo", {}, quiet=True)
    assert not paths["presets"].exists() and not paths["admin_log"].exists()
    assert not paths["credentials"].exists()


def test_d3_both_teardown_paths_are_wired_and_share_one_source():
    """两条拆台路径都接线、且物化/回收**同源**（静态锁；260926 的病灶就是「只写半边」）。"""
    src = (INTEG / "stage_docker.py").read_text(encoding="utf-8")
    assert src.count('"sandbar-agent-presets-%s"') == 1
    assert src.count('"sandbar-admin-log-%s.log"') == 1
    assert src.count('"sandbar-credentials-%s.yaml"') == 1
    do_down = src[src.index("def do_down("):src.index("def _gates(")]
    assert "reclaim_stage_tmp_artifacts(project)" in do_down
    _do_down = src[src.index("def _do_down("):src.index("def do_down(")]
    assert "reclaim_stage_tmp_artifacts(project)" in _do_down
    assert "_report_stage_tmp_kept(project" in _do_down          # rc!=0/异常两条保留分支都点名
    assert _do_down.count("_report_stage_tmp_kept(project") == 2


# ========================================================================================
# E. 白名单单源 / 覆盖面 / 水位面 skipped 上界
# ========================================================================================

#: 本族生产者的**字面前缀**（file:line 见 sweep_tmp_fixtures 的白名单注释）。
#: 这条锁就是「前缀盖不住」那类洞的机械闸：生产者新写的变体前缀必须同时进白名单。
PRODUCER_PREFIXES = (
    ("t260907-06-ut-", "server/engine/tests/test_multirepo_anchor.py"),
    ("t260907-12-ut", "server/engine/tests/test_multirepo_anchor.py"),
    ("t260907-12-act-", "server/engine/tests/test_multirepo_root_activity.py"),
    ("t260907-12-ch-", "server/engine/tests/test_multirepo_root_activity.py"),
    ("venv-compat-root-", "integration/t260907-10/sc_engine_venv_compat.py"),
    ("venv-compat-home-", "integration/t260907-10/sc_engine_venv_compat.py"),
    ("sandbar-integ-run-", "integration/run_scenarios.py"),
    ("sandbar-admin-log-", "integration/stage_docker.py"),
    ("sandbar-credentials-", "integration/stage_docker.py"),
    ("sandbar-agent-presets-", "integration/stage_docker.py"),
    ("t260908-02-ut-", "server/engine/tests/test_t260908_02_payload_roundtrip.py"),
    ("sandbar-reg-", "server/plugins/workbench/tests/registry-loader.mjs"),
    ("detailred-e2e-", "integration/t260915-01/tests/sc_detail_red_refusal_receipt.py"),
    ("t260904-13-itest-", "integration/t260904-13/lib_ki044.py"),
    ("t260904-18-mg-", "integration/t260904-18/lib_t260904_18.py"),
    ("t26092114-", "integration/t260921-14/lib_t26092114.py"),
    # ---- t261002-13 第三批：t* 直方图 top 族的缺口闸 ----
    ("t26092523-", "integration/t260925-23/tests/sc_template_pathgate_load_contract.py"),
    ("t26092523-faces-", "integration/t260925-23/tests/sc_template_pathgate_faces.py"),
    ("t260901-14-r-", "server/engine/tests/test_t260901_14_registry_loader.py"),
    ("t260908-02-sg-", "server/engine/tests/test_t260908_02_payload_roundtrip.py"),
    ("t26092404-probe-", "integration/t260924-04/sc_project_template_gate.py"),
    ("t260901-21-t01-", "integration/t260901-21/t01_read_side_resolution.py"),
)


def test_e1_producer_prefixes_are_all_covered_by_the_whitelist():
    """生产者前缀 → 白名单覆盖面锁：`t260907-12-act-/-ch-` 那类洞必须从此红在案上。"""
    uncovered = []
    for prefix, src in PRODUCER_PREFIXES:
        assert (REPO / src).exists(), src
        if not sw.match_prefix(prefix, sw.TMP_FIXTURE_PREFIXES):
            uncovered.append("%s (%s)" % (prefix, src))
        if not sw.match_prefix(prefix, lw.TMP_FIXTURE_PREFIXES):
            uncovered.append("%s (%s, engine side)" % (prefix, src))
    assert uncovered == []
    # 生产者字面**真在**（防「登记了不存在的前缀」）：三处 260927 新修的生产者逐字在场
    assert 'mkdtemp_reclaimed("t260907-12-act-")' in (
        POC / "tests" / "test_multirepo_root_activity.py").read_text(encoding="utf-8")
    assert 'mkdtemp_reclaimed("venv-compat-home-")' in (
        INTEG / "t260907-10" / "sc_engine_venv_compat.py").read_text(encoding="utf-8")
    # t261002-13 第三批生产者逐字在场（防「登记了不存在的前缀」同型复发）
    assert 'mkdtemp_reclaimed("t26092523-load-b1-")' in (
        INTEG / "t260925-23" / "tests" / "sc_template_pathgate_load_contract.py").read_text(encoding="utf-8")
    assert 'mkdtemp_reclaimed("t260901-14-r-")' in (
        POC / "tests" / "test_t260901_14_registry_loader.py").read_text(encoding="utf-8")
    assert 'mkdtemp_reclaimed("t260908-02-sg-")' in (
        POC / "tests" / "test_t260908_02_payload_roundtrip.py").read_text(encoding="utf-8")


def test_e2_batch2_prefixes_are_really_enabled_and_single_sourced():
    """第二批 28 个前缀**真已启用**（不再有「登记了但没启用」的半态），且两处同源。"""
    assert tuple(sw.TMP_FIXTURE_PREFIXES) == tuple(lw.TMP_FIXTURE_PREFIXES)
    assert set(sw.BATCH2_MERGED_PREFIXES) <= set(sw.TMP_FIXTURE_PREFIXES)
    assert len(sw.BATCH2_MERGED_PREFIXES) == 27   # t260908-02-ut 已并入更宽的 t260908-02-（t261002-13 第三批）
    assert not hasattr(sw, "CANDIDATE_PREFIXES_BATCH2")   # 半态常量已退役（只剩白名单）
    # 前缀表里不许有重复（重复=两处判据可能分叉的温床）
    assert len(set(sw.TMP_FIXTURE_PREFIXES)) == len(sw.TMP_FIXTURE_PREFIXES)
    # 排除族逐条在册且带理由（不碰也得是可复核的判定，不是「恰好没写进白名单」）
    for p in ("com.google.Chrome.", "dsh-subprocess-", "dsh-spill-", "tmp"):
        assert p in sw.EXCLUDED_PREFIXES


def test_e3_water_face_counts_dirs_only_and_caps_the_skipped_list(tmp_path):
    """水位面：**只数真目录**（文件族只进 skipped）；skipped 名单有上界但计数给全量。"""
    root = tmp_path / "water"
    root.mkdir()
    for i in range(3):
        (root / ("fix10-dir%d" % i)).mkdir()
    for i in range(120):                       # 白名单内的文件族（锁档/影子/凭据副本）
        (root / ("sandbar-integ-run-%03d.lock" % i)).write_text("x", encoding="utf-8")
    (root / "com.google.Chrome.X").mkdir()
    scan = activities.scan_tmp_fixture_dirs(str(root), lw.TMP_FIXTURE_PREFIXES)
    assert len(scan["entries"]) == 3                       # 只有真目录进水位
    assert scan["untouched"] == 1
    assert scan["skipped_count"] == 120                    # 全量计数不截断
    assert len(scan["skipped"]) == activities.TMP_SCAN_SKIPPED_CAP + 1
    assert "more skipped entries suppressed" in scan["skipped"][-1]
    facts = lw.tmp_fixture_facts(scan)
    assert facts["dirs"] == 3 and facts["skipped_count"] == 120
    sec = lw.tmp_fixture_scan_result(scan, {"tmp_fixture_max_dirs": 100,
                                            "tmp_fixture_max_age_h": 6})["section"]
    assert sec["dirs"] == 3 and sec["skipped_count"] == 120
    assert sec["by_prefix"]["fix10-"] == 3
    # 老回执（无 skipped_count 字段）逐字段兼容：回落成名单长度，绝不假装 0
    legacy = dict(scan)
    legacy.pop("skipped_count")
    assert lw.tmp_fixture_facts(legacy)["skipped_count"] == len(scan["skipped"])


def test_e4_water_face_leak_prefixes_still_end_to_end(monkeypatch, tmp_path):
    """入口级反例（水位越线仍出条）+ 白名单增长后**票级面零污染**（既有口径不回退）。"""
    root = tmp_path / "water2"
    root.mkdir()
    old = time.time() - 9 * 3600
    for i in range(5):
        d = root / ("t260907-12-act-%d" % i)
        d.mkdir()
        os.utime(d, (old, old))
    res = lw.tmp_fixture_scan_result(
        activities.scan_tmp_fixture_dirs(str(root), lw.TMP_FIXTURE_PREFIXES),
        {"tmp_fixture_max_dirs": 4, "tmp_fixture_max_age_h": 6})
    assert len(res["findings"]) == 1
    f = res["findings"][0]
    assert f["legs"] == [lw.LEG_TMP_FIXTURE] and f["scope"] == "host"
    assert "t260907-12-act-" in f["evidence"]
    assert res["section"]["finding_count"] == 1
    # 只读自证：扫描不写任何东西（活动壳里的写动词面锁仍在）
    src = (POC / "activities.py").read_text(encoding="utf-8")
    fn = src[src.index("def scan_tmp_fixture_dirs("):src.index("def _scan_tmp_fixture_cached(")]
    for forbidden in ("rmtree", "unlink", "write_text", "os.remove"):
        assert forbidden not in fn, forbidden
    assert "follow_symlinks=False" in fn


def test_e5_single_source_drift_lock_still_holds():
    """既有漂移锁（test_t260926 的 f1）在**并入 28 个前缀之后**仍然成立：两份清单逐字相同。"""
    assert tuple(sw.TMP_FIXTURE_PREFIXES) == tuple(lw.TMP_FIXTURE_PREFIXES)
    assert sw.DEFAULT_MAX_AGE_H == lw.DEFAULT_TMP_FIXTURE_MAX_AGE_H
    assert sw.APPLY_MIN_AGE_H == 1.0        # --apply 的龄闸硬地板不许被调松


T13_PRODUCERS = ("integration/t260910-13/sc_t260910_13_failure_protocol_gate.py",
                 "integration/t260910-13/sc_t260910_13_failure_protocol_pytest_source.py")


def test_e6_top_live_producer_fixed_even_though_its_prefix_is_not_whitelisted(tmp_path):
    """当期**最大活生产源**（`t26091013-*`：普查 17,254 条 / <6h 的 8,594 条）已治本，
    但它的前缀**没有**并入白名单（删除面的扩大要宿主授权，本轮不动）——这条测试把这个
    「生产者已修 / 删除面待授权」的不对称状态钉在案上，别让后来人误以为它已被清扫覆盖。
    """
    for src in T13_PRODUCERS:
        t = (REPO / src).read_text(encoding="utf-8")
        assert "tempfile.mkdtemp(" not in t and "mkdtemp_reclaimed(" in t, src
        assert "from lib_tmp_reclaim import mkdtemp_reclaimed" in t, src
    # 白名单**确实**没盖住它（现状如实断言，不是漏写）
    assert sw.match_prefix("t26091013-x", sw.TMP_FIXTURE_PREFIXES) == ""
    # 真跑一遍生产端（秒级，微型 pytest）：私有 $TMPDIR 里零残留
    root = tmp_path / "t13"
    root.mkdir()
    p = _child("import runpy;runpy.run_path('%s',run_name='__main__')" % T13_PRODUCERS[1], root)
    assert p.returncode == 0, (p.stdout[-600:], p.stderr[-600:])
    assert "0 FAIL" in p.stdout
    assert [n for n in os.listdir(root) if n.startswith("t26091013")] == []
