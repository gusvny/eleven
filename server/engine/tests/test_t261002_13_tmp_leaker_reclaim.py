#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261002-13 测试夹具临时目录泄漏收口的定点回归（三交付物各一钉）。

背景：`$TMPDIR` 顶层实测 t* 直方图 8.8 万条（t260904-02-* 1.56 万 / t260901-21-* 1.3 万
/ t26092404-* 1.0 万 / t26092523-* 4.6 千 / t260901-14-* 3.5 千 / t260908-02-* 2.0 千）
——全部是各测试面 `tempfile.mkdtemp` 出来、终态从不回收的夹具族。本文件钉三件事：

  D1（生产者回收）：六族生产者文件里**零裸 `tempfile.mkdtemp(`**，且都走回收 helper
     （引擎侧 `_tmp_reclaim` / 集成侧 `lib_tmp_reclaim`——注册表 + atexit 兜底，
     pass/fail/env-fail/cancel 全终态走解释器退出路径即回收；SIGKILL 类由清扫器+水位判据接管）。
  D2（白名单缺口闸）：本票增补的三个前缀（`t26092523-` / `t260901-14-` / `t260908-02-`）
     必须同场在清扫器与引擎判据两份白名单里（详细的单源/覆盖面锁在
     test_t260927_tmp_fixture_family.py，本条只钉「本票缺口确实补上了」）。
  D3（回执点名）：水位发现的 evidence 带 `top leakers`（前缀 x 命中数 + owner），
     白名单外的名字（别的程序的/dsh spill）绝不进 top 表；owner 查不到显式 `unknown`；
     畸形条目逐条降级点名，绝不静默吞。

跑法：仓库根 `server/engine/.venv/bin/python -m pytest
server/engine/tests/test_t261002_13_tmp_leaker_reclaim.py -q`（零网络/零真 Temporal）。
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parent.parent
REPO = POC.parent.parent
INTEG = REPO / "integration"
SWEEP = INTEG / "tools" / "sweep_tmp_fixtures.py"
sys.path.insert(0, str(POC))
sys.path.insert(0, str(INTEG))                # integration/lib_tmp_reclaim

import inspection_lane_watchdog as lw  # noqa: E402


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sw = _load(SWEEP, "sweep_probe_t26100213")


# =====================================================================================
# D1 生产者回收：六族生产者零裸 mkdtemp、逐文件走回收 helper
# =====================================================================================

PRODUCERS = (
    "server/engine/tests/test_t260904_02_registry_anchor.py",
    "server/engine/tests/test_t260904_02_worker_meta.py",
    "server/engine/tests/test_t260901_14_registry_loader.py",
    "server/engine/tests/test_t260908_02_payload_roundtrip.py",
    "integration/t260901-21/t01_read_side_resolution.py",
    "integration/t260901-21/sc_i01_parity_py_vs_mjs.py",
    "integration/t260901-21/t02_copy_creds.py",
    "integration/t260924-04/sc_project_template_gate.py",
    "integration/t260924-04/sc_project_template_ticket_journey.py",
    "integration/t260925-23/tests/sc_template_pathgate_load_contract.py",
    "integration/t260925-23/tests/sc_template_pathgate_faces.py",
    "server/engine/tests/test_t260924_04_project_templates.py",
    "integration/t260902-02/sc_t02_archive_ticket.py",
    "integration/t260902-02/sc_t03_merge_teardown.py",
    "integration/t260902-02/sc_t04_prune_archive_legacy.py",
    "integration/t260902-02/t01_archive_paths.py",
    "integration/t260901-25/t03_reap_process_group.py",
)


@pytest.mark.parametrize("rel", PRODUCERS)
def test_d1_producer_has_zero_raw_mkdtemp_and_uses_the_registry(rel):
    """生产者文件零裸 `tempfile.mkdtemp(`——回退到裸调用即红（终态回收面回归锁）。"""
    src = (REPO / rel).read_text(encoding="utf-8")
    assert "tempfile.mkdtemp(" not in src, "%s regressed to raw mkdtemp" % rel
    assert "mkdtemp_reclaimed(" in src, "%s lost the reclaimed helper" % rel
    helper = "_tmp_reclaim" if rel.startswith("server/engine/") else "lib_tmp_reclaim"
    assert helper in src, "%s must import %s" % (rel, helper)


def test_d1_reclaimed_helper_reaps_every_registered_dir():
    """helper 终态语义抽查：注册 → 回收 → 出册（幂等），重复回收不算失败。"""
    import lib_tmp_reclaim as tr
    before = len(tr.REGISTERED)
    p = tr.mkdtemp_reclaimed("t26100213-ut-")
    assert p.exists() and len(tr.REGISTERED) == before + 1
    res = tr.reclaim_registered()
    assert len(res.get("removed") or []) >= 1 and not p.exists()
    assert tr.reclaim_registered()["removed"] == []          # 幂等：第二次零条
    assert tr.REAP_FAILURES == 0


# =====================================================================================
# D2 白名单缺口闸：本票增补的三个前缀两处同场
# =====================================================================================

@pytest.mark.parametrize("prefix", ("t26092523-", "t260901-14-", "t260908-02-",
                                    "t260924-04-", "t01-", "t02-sb-", "t03-",
                                    "t04-sb-", "t08-guard-", "t09-", "t25-t03-"))
def test_d2_batch3_prefixes_present_in_both_whitelists(prefix):
    assert prefix in sw.TMP_FIXTURE_PREFIXES, "sweep whitelist missing %s" % prefix
    assert prefix in lw.TMP_FIXTURE_PREFIXES, "watchdog whitelist missing %s" % prefix
    # 同文件历史窄条已并入宽条（盖住 -sg/-faces 变体），不许再以窄条形态复现
    assert "t260908-02-ut" not in sw.TMP_FIXTURE_PREFIXES
    assert "t260908-02-ut" not in lw.TMP_FIXTURE_PREFIXES


# =====================================================================================
# D1b 铸目窗口信号竞态（验收走查打回的间歇泄漏）：SIGINT 落在 mkdtemp→入册 之间也必收
# =====================================================================================

_CHILD = """
import os, signal, sys, tempfile
sys.path.insert(0, {helper_dir!r})
{import_line}
import {mod} as tr
_real = tempfile.mkdtemp
def _mint_then_signal(prefix, dir=None):
    p = _real(prefix=prefix, dir=dir)
    os.kill(os.getpid(), signal.SIGINT)   # 信号恰落在「已落盘、未入册」的窗口里
    return p
tempfile.mkdtemp = _mint_then_signal
try:
    mkdtemp_reclaimed("t26100213-win-")
except KeyboardInterrupt:
    pass                                   # 信号推迟到入册后才送达——语义不变
live = (tr.live_tmp_paths if hasattr(tr, "live_tmp_paths") else tr.live_tmp_dirs)()
print(live[-1])                            # 出示在册路径；进程退出 atexit 必收
"""


def _run_window_child(helper_dir, import_line, mod):
    import subprocess
    r = subprocess.run([sys.executable, "-c", _CHILD.format(helper_dir=helper_dir,
                                                           import_line=import_line,
                                                           mod=mod)],
                       capture_output=True, text=True, timeout=60,
                       env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    out = r.stdout.strip().splitlines()
    assert out, "child produced no path (stderr=%s)" % r.stderr[-300:]
    return out[-1]


def test_d1b_engine_sigint_in_mint_window_still_reaps(tmp_path):
    """引擎侧：信号落在铸目窗口 → KeyboardInterrupt 照抛，但目录已在册，退出即收。"""
    from pathlib import Path as _P
    p = _run_window_child(str(_P("server/engine/tests").resolve()),
                          "from _tmp_reclaim import mkdtemp_reclaimed", "_tmp_reclaim")
    assert not os.path.exists(p), "mint-window SIGINT leaked the dir (engine helper)"


def test_d1b_integration_sigint_in_mint_window_still_reaps(tmp_path):
    """集成侧（lib_tmp_reclaim 同族窗口，同修）：同上。"""
    from pathlib import Path as _P
    p = _run_window_child(str(_P("integration").resolve()),
                          "from lib_tmp_reclaim import mkdtemp_reclaimed", "lib_tmp_reclaim")
    assert not os.path.exists(p), "mint-window SIGINT leaked the dir (integration helper)"


# =====================================================================================
# D2b 活载体安全轨（仲裁 code-fault 回归）：root 未解析 vs pid cwd 已解析的路径失真
# =====================================================================================

def test_d2b_carrier_detected_through_unresolved_root(tmp_path):
    """symlink 化的 temp 根下（macOS `/var/...` vs cwd 报 `/private/var/...`），
    活载体的 cwd 落在越龄条目内必须被识别——root 与 cwd 两侧 realpath 归一后比对。
    反证即仲裁重现：修前 `live_carriers` 返回 `{}` 且条目被 sweep 删掉。"""
    import subprocess
    import time as _t
    real_root = tmp_path / "real"
    carrier = real_root / "t260904-02-carrier"
    carrier.mkdir(parents=True)
    link_root = tmp_path / "link"          # root 的符号别名 = 未解析形态
    link_root.symlink_to(real_root, target_is_directory=True)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(20)"],
                         cwd=str(carrier), env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        _t.sleep(1.0)                       # 等子进程 chdir 完成
        hits, err = sw.live_carriers(str(link_root),
                                     [sw.FixtureEntry("t260904-02-carrier",
                                                      _t.time() - 8 * 3600, "dir")])
        assert err is None
        assert hits.get("t260904-02-carrier"), \
            "carrier invisible through unresolved root (the arbitrated defect)"
    finally:
        p.terminate()
        p.wait(timeout=10)


# =====================================================================================
# D3 回执点名：top_leakers 计算面 + 发现证据 + owner 表卫生
# =====================================================================================

NOW = 1_800_000_000.0


def _scan(entries, root="/tmp/t26100213-ut"):
    return {"root": root, "entries": entries, "entries_seen": len(entries),
            "untouched": 0, "skipped": [], "skipped_count": 0,
            "scan_error": "", "scanned_at": NOW}


def test_d3_top_leakers_ranked_by_count_with_owner():
    facts = lw.tmp_fixture_facts(_scan(
        [{"name": "t260904-02-gate-a", "mtime": NOW - 3600 * 10},
         {"name": "t260904-02-reg-b", "mtime": NOW - 3600 * 9},
         {"name": "t26092523-load-b1-x", "mtime": NOW - 3600 * 8}],
        ), now_ts=NOW)
    top = lw.tmp_fixture_top_leakers(facts)
    assert top[0] == {"prefix": "t260904-02-", "dirs": 2,
                      "owner": lw.TMP_FIXTURE_OWNERS["t260904-02-"]}
    assert top[1]["prefix"] == "t26092523-" and top[1]["owner"] != "unknown"


def test_d3_unknown_owner_is_explicit_not_guessed():
    facts = lw.tmp_fixture_facts(_scan(
        [{"name": "t260918-ut-whatever", "mtime": NOW - 60}]), now_ts=NOW)
    top = lw.tmp_fixture_top_leakers(facts)
    assert top == [{"prefix": "t260918-", "dirs": 1, "owner": "unknown"}]


def test_d3_finding_evidence_names_top_leakers():
    """越线发现的 evidence 带 `top leakers`——下一轮报警直接指到族，不给光秃秃的数。"""
    entries = ([{"name": "t260904-02-gate-%d" % i, "mtime": NOW - 3600 * 30}
                for i in range(4)] +
               [{"name": "t260901-21-i01-x", "mtime": NOW - 3600 * 20}])
    res = lw.tmp_fixture_scan_result(_scan(entries),
                                     {"tmp_fixture_max_dirs": 2,
                                      "tmp_fixture_max_age_h": 6}, now_ts=NOW)
    ev = " ".join(str(f.get("evidence") or "") for f in res["findings"])
    assert "top leakers" in ev
    assert "t260904-02- x4" in ev
    assert "owner=server/engine/tests/test_t260904_02_" in ev
    # 回执段同样带 top_leakers（机器口径，供 receipt 消费）
    assert res["section"]["top_leakers"][0]["prefix"] == "t260904-02-"


def test_d3_excluded_families_never_enter_top_leakers():
    """白名单外（别的程序 / dsh spill）一律不计、不进 top 表——判据面不静默也不误计。"""
    entries = [{"name": "com.google.Chrome.profile-x", "mtime": NOW - 3600 * 99},
               {"name": "dsh-subprocess-123-spill", "mtime": NOW - 3600 * 99},
               {"name": "t260908-02-ut-y", "mtime": NOW - 3600 * 10}]
    facts = lw.tmp_fixture_facts(_scan(entries), now_ts=NOW)
    assert facts["dirs"] == 1
    assert [t["prefix"] for t in lw.tmp_fixture_top_leakers(facts)] == ["t260908-02-"]
    assert any("outside the whitelist" in m for m in facts["malformed"])


def test_d3_malformed_entries_degrade_named_not_silent():
    facts = lw.tmp_fixture_facts(_scan(
        ["not-a-dict", {"mtime": NOW}, {"name": "", "mtime": NOW},
         {"name": "t260901-14-r-x", "mtime": "garbage"},
         {"name": "t260901-14-p-y", "mtime": NOW - 60}]), now_ts=NOW)
    assert facts["dirs"] == 2                    # 两条带名前缀的照常计数（缺 mtime 的那条年龄未知但目录在场）
    assert len(facts["malformed"]) == 4          # 逐条点名：4 条畸形全在场
    assert lw.tmp_fixture_top_leakers(facts)[0]["prefix"] == "t260901-14-"


def test_d3_owner_table_keys_are_covered_by_the_whitelist():
    """owner 表的每个键都必须被白名单前缀盖住——表与白名单漂移即红。"""
    for p in lw.TMP_FIXTURE_OWNERS:
        assert sw.match_prefix(p, lw.TMP_FIXTURE_PREFIXES) != "", \
            "owner key %s is not covered by the whitelist" % p
