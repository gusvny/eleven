# -*- coding: utf-8 -*-
"""L2 回归（261001 自递归风暴的机械网）：**越龄夹具里的活载体**必须被认出来、被保留、被点名。

风暴事实（261001 实测，见 notes/debts/known-issues.md KI-170）：
  - 场景 `t260910-04` 被 900s 执行器帽杀 → `finally` 里的 `rmSync` 没跑 → 夹具树留着；
  - 树里的**台内后代进程**（lane worker 及其 supervisor）也留着（组杀打偏）；
  - 2.5h 后那片**冻结代码**（克隆自修前的 main，三层 KI-170 护栏一条都不在）重跑闸 →
    自递归风暴（实测族内 156→266 个进程、19 台批台）。
  - 收口失败的关键不是「杀不干净」，而是**判据打偏**：那些进程的命令行是相对路径
    （`integration/run_scenarios.py --only …`），按名字杀三轮都还剩一大片；
    按 **cwd** 判才认得出「这条夹具里还有谁在跑」。

本文件的锁（都是行为锁，不锁实现）：①按 cwd 认载体；②有载体的条目**不删**（缺省）；
③`--kill-carriers` 才先收进程再删；④探测面缺席时**具名留痕**且不假装「没有载体」。
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

INTEG = Path(__file__).resolve().parents[1]
SWEEP_PATH = INTEG / "tools" / "sweep_tmp_fixtures.py"
#: 白名单里的真实前缀（载体扫描只对白名单条目生效，用真前缀才能证明覆盖面）
PREFIX = "t26091004-sc-"


def _load(name="sweep_probe"):
    spec = importlib.util.spec_from_file_location(name, str(SWEEP_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _aged_dir(root: Path, name: str, age_h: float = 8.0) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "keep.txt").write_text("x", encoding="utf-8")
    old = time.time() - age_h * 3600
    os.utime(d, (old, old))
    return d


def _spawn_inside(d: Path) -> subprocess.Popen:
    """在夹具目录里起一个**长命**子进程（cwd 落在夹具内 = 载体签名）。"""
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], cwd=str(d))


def _entry(mod, root: Path, name: str):
    sc = mod.scan(str(root), (PREFIX,), 6.0)
    rows = [e for e in sc["stale"] if e.name == name]
    assert rows, "aged entry %s not seen as stale (test setup broken)" % name
    return sc["stale"]


def _run_json(argv):
    """跑 CLI 并取 JSON（stdout 上只有 JSON；人类可读行走 stderr）。"""
    r = subprocess.run([sys.executable, str(SWEEP_PATH)] + argv,
                       capture_output=True, text=True)
    assert r.returncode in (0, 1), r.stderr[-2000:]
    return json.loads(r.stdout), r.stderr


def test_c1_carriers_are_found_by_cwd_not_by_command_line(tmp_path):
    """①按 cwd 认载体：目录里有活进程 = 载体；空目录 = 不是。"""
    mod = _load()
    with_carrier = _aged_dir(tmp_path, PREFIX + "carrier")
    without = _aged_dir(tmp_path, PREFIX + "empty")
    child = _spawn_inside(with_carrier)
    try:
        entries = _entry(mod, tmp_path, with_carrier.name)
        hits, err = mod.live_carriers(str(tmp_path), entries)
        assert err is None
        assert with_carrier.name in hits, hits
        assert child.pid in hits[with_carrier.name], hits
        assert without.name not in hits, hits
    finally:
        child.terminate()
        child.wait(timeout=20)


def test_c2_dry_run_reports_carrier_and_leaves_the_entry_out_of_the_delete_set(tmp_path):
    """②dry-run 就报载体，且**候选集里不含**它（报的要删数=真会删的数）。"""
    mod = _load()
    d = _aged_dir(tmp_path, PREFIX + "dry")
    child = _spawn_inside(d)
    try:
        out, err = _run_json(["--root", str(tmp_path), "--prefix", PREFIX, "--json"])
        assert out["carriers_entries"] == 1 and out["carriers_count"] >= 1
        assert out["swept"] == 0, out["swept"]
        assert d.name in out["carriers"]
        assert "LIVE CARRIERS" in err
    finally:
        child.terminate()
        child.wait(timeout=20)


def test_c3_apply_without_kill_keeps_entry_and_process(tmp_path):
    """③缺省 apply **不杀**载体、也不删它的树（删树不杀进程=更脏的半态）。"""
    mod = _load()
    d = _aged_dir(tmp_path, PREFIX + "keep")
    child = _spawn_inside(d)
    try:
        out, _ = _run_json(["--root", str(tmp_path), "--prefix", PREFIX,
                            "--max-age-h", "2", "--apply", "--json"])
        assert d.exists(), "entry with a live carrier must not be swept by default"
        assert child.poll() is None, "default apply must not kill carriers"
        assert out["carriers_kept"] == 1 and out["carriers_reaped"] == 0
        assert out["swept"] == 0
    finally:
        child.terminate()
        child.wait(timeout=20)


def test_c4_kill_carriers_reaps_then_sweeps(tmp_path):
    """④`--kill-carriers` 才真收进程；收完条目才进删除面（先收后删，不留半态）。"""
    mod = _load()
    d = _aged_dir(tmp_path, PREFIX + "reap")
    child = _spawn_inside(d)
    try:
        out, err = _run_json(["--root", str(tmp_path), "--prefix", PREFIX,
                              "--max-age-h", "2", "--apply", "--kill-carriers", "--json"])
        assert out["carriers_reaped"] >= 1, out
        assert "REAPED" in err
        deadline = time.time() + 10
        while child.poll() is None and time.time() < deadline:
            time.sleep(0.2)
        assert child.poll() is not None, "carrier survived --kill-carriers"
        assert not d.exists(), "entry should be swept once its carriers are reaped"
    finally:
        if child.poll() is None:
            child.kill()


def test_c5_unavailable_scan_is_named_and_never_means_no_carriers(tmp_path, monkeypatch):
    """⑤探测面缺席 = **不知道**：报告里具名，且目录族不删（「扫不到」≠「没有」）。"""
    mod = _load()
    d = _aged_dir(tmp_path, PREFIX + "unverifiable")
    entries = _entry(mod, tmp_path, d.name)
    monkeypatch.setattr(mod, "_all_pids", lambda: (None, "pgrep unavailable: probe"))
    hits, err = mod.live_carriers(str(tmp_path), entries)
    assert hits == {} and err and "pgrep unavailable" in err
    # 同一条纪律走 CLI：不可用 → 不删目录
    monkeypatch.setattr(mod.sys, "argv", ["sweep", "--root", str(tmp_path), "--prefix", PREFIX,
                                          "--max-age-h", "2", "--apply", "--json"])
    monkeypatch.setattr(mod, "live_carriers",
                        lambda root, ents: ({}, "pgrep unavailable: probe"))
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mod.run(["--root", str(tmp_path), "--prefix", PREFIX, "--max-age-h", "2",
                      "--apply", "--json"])
    assert rc == 0
    payload = json.loads(buf.getvalue())
    assert payload["carriers_scan_error"], payload
    assert payload["carriers_unverified_kept"] == 1
    assert payload["swept"] == 0 and d.exists(), "unverifiable dir entries must be kept"
