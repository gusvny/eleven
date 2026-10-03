#!/usr/bin/env python3
"""sc_tmp_backlog_sweep_safety — 存量夹具清扫器 CLI 的安全契约（t261002-13，灰盒 L3）。

被测出口：integration/tools/sweep_tmp_fixtures.py（真子进程、真 --root 隔离沙盒，
零碰宿主真 $TMPDIR）。intent（工单交付物 2：存量回收必须安全——只删「白名单×越龄」，
绝不动活跑；阈值告警的 t* 白名单缺口必须闭合）：
  A dry-run 只报不删（默认模式删除数=0，JSON 回执可读）；
  B --apply 判据四象限（全在隔离 root）：
     B1 白名单×越龄 真目录（含嵌套内容）→ 删；
     B2 白名单×越龄 真文件（锁档族）→ 删；
     B3 白名单×新鲜（<6h，模拟在跑 t261002-12 套件持有）→ 留；
     B4 白名单外（哪怕更老）→ 留（绝不越白名单删宿主的东西）；
     B5 EXCLUDED_PREFIXES（com.google.Chrome.*，别人的）→ 留且不进白名单计数；
     B6 符号链接 → 跳过且链接目标原样；
     B7 flock 被活进程持有的越龄白名单文件 → 留且回执点名（绝不删活锁档）；
     B8 cwd 落在越龄白名单目录里的活载体 → 留且回执点名（绝不拆活跑的台）；
  C 年龄闸不可绕：--apply --max-age-h 0 / <1h 硬地板 → 拒收非零退出（点名 REFUSED）；
  D 白名单缺口钉（本票 review 实锤）：t26092523- 与 t260901-14- 两族（ticket 直方图
    top-6 里的 4,599 + 3,477 个存量）必须在 TMP_FIXTURE_PREFIXES——缺=存量永不可扫。
intent 分工：判定函数真值分支/文件族分流归 developer L1
（server/engine/tests/test_t260927_tmp_fixture_family.py、
integration/tests/test_t261001_fixture_carriers.py，含 BATCH2 回归锁）；本条锁
真 CLI 端到端行为（真子进程×真文件系统×真 flock×真活载体）。
实现未落地段红属预期（TDD 信号），arbitrate/merge 期必须绿。
三态：工具缺席/无 fcntl=ENV_FAIL exit 2；断言败=FAIL exit 1；全过=PASS exit 0。

Run directly: python3 integration/t261002-13/sc_tmp_backlog_sweep_safety.py（cwd=仓根）。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SWEEP = ROOT / "integration" / "tools" / "sweep_tmp_fixtures.py"
PY = sys.executable

PASS, FAIL = 0, 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✓ %s" % label)
    else:
        FAIL += 1
        print("  ✗ %s" % label)


def die_env(msg):
    print("ENV_FAIL: " + msg, file=sys.stderr)
    sys.exit(2)


def backdate(p, hours=8.0):
    old = time.time() - hours * 3600.0
    os.utime(p, (old, old))


def run_tool(args, timeout=120):
    return subprocess.run([PY, str(SWEEP)] + args, cwd=str(ROOT),
                          capture_output=True, text=True, timeout=timeout)


def main():
    if not SWEEP.is_file():
        die_env("sweep tool missing: %s" % SWEEP)
    try:
        import fcntl  # noqa: F401  (B7 活锁判据依赖)
    except ImportError:
        die_env("fcntl unavailable on this platform (live-lock subcase cannot run)")

    # ---- 白名单缺口钉（D，实现面；在搭台前判，独立于沙盒） ----
    sys.path.insert(0, str(ROOT / "integration" / "tools"))
    import sweep_tmp_fixtures as sw  # noqa: E402
    ok("t26092523-" in sw.TMP_FIXTURE_PREFIXES,
       "D1 whitelist covers t26092523- (4,599 dirs backlog, ticket histogram #4)")
    ok("t260901-14-" in sw.TMP_FIXTURE_PREFIXES,
       "D2 whitelist covers t260901-14- (3,477 dirs backlog, ticket histogram #5)")

    # ---- 隔离沙盒（本场景自己的夹具，终态自回收） ----
    box = tempfile.mkdtemp(prefix="t261002-13-s1-box-")
    sys.path.insert(0, str(ROOT / "integration"))
    import lib_tmp_reclaim as lr  # noqa: E402
    lr.register_tmp_path(Path(box), "sc_tmp_backlog_sweep_safety sandbox")

    aged_wl_dir = Path(box, "t260904-02-aged")            # B1
    (aged_wl_dir / "nested").mkdir(parents=True)
    (aged_wl_dir / "nested" / "f.txt").write_text("x")
    aged_wl_file = Path(box, "lease-ut-aged.lock")        # B2 文件族
    aged_wl_file.write_text("lock")
    recent_wl = Path(box, "t260904-02-live-run-holds")    # B3 新鲜=在跑套件持有
    recent_wl.mkdir()
    foreign = Path(box, "com.google.Chrome.aged")         # B5 排除族
    foreign.mkdir()
    outsider = Path(box, "not-ours-aged")                 # B4 白名单外
    outsider.mkdir()
    link = Path(box, "t260904-02-link")                   # B6 符号链接
    os.symlink(str(aged_wl_dir), str(link))
    for p in (aged_wl_dir, aged_wl_file, foreign, outsider):
        backdate(p)  # recent_wl 有意不回溯：<6h 新鲜 = 在跑套件持有的形态

    held = Path(box, "t260904-02-held.lock")              # B7 活 flock（越龄才会进锁判据）
    held.write_text("held")
    backdate(held)
    holder = subprocess.Popen(
        [PY, "-c",
         "import fcntl,sys,time;f=open(sys.argv[1],'r+');fcntl.flock(f,fcntl.LOCK_EX);"
         "print('locked',flush=True);time.sleep(120)", str(held)],
        stdout=subprocess.PIPE, text=True)
    try:
        holder.stdout.readline()  # 等它真拿到锁

        carrier_dir = Path(box, "t260904-02-carrier")     # B8 活载体 cwd
        carrier_dir.mkdir()
        backdate(carrier_dir)
        carrier = subprocess.Popen([PY, "-c", "import time;time.sleep(120)"],
                                   cwd=str(carrier_dir))
        try:
            # ---- A dry-run ----
            r = run_tool(["--root", box, "--json"])
            ok(r.returncode == 0, "A1 dry-run exits 0")
            j = json.loads(r.stdout)
            ok(aged_wl_dir.exists() and aged_wl_file.exists(),
               "A2 dry-run deleted nothing (aged whitelisted dir+file still present)")

            # ---- C 年龄闸不可绕（先于 apply 判，不改沙盒） ----
            r0 = run_tool(["--root", box, "--apply", "--max-age-h", "0"])
            ok(r0.returncode != 0 and "REFUSED" in (r0.stdout + r0.stderr),
               "C1 --apply --max-age-h 0 refused, non-zero exit, named REFUSED")
            r1 = run_tool(["--root", box, "--apply", "--max-age-h", "0.5"])
            ok(r1.returncode != 0,
               "C2 --apply below 1h hard floor refused")

            # ---- B apply ----
            ra = run_tool(["--root", box, "--apply", "--json"])
            ok(ra.returncode == 0, "B0 --apply exits 0")
            ja = json.loads(ra.stdout)
            ok(not aged_wl_dir.exists(), "B1 aged whitelisted dir (with nested content) reclaimed")
            ok(not aged_wl_file.exists(), "B2 aged whitelisted file (lock-file family) reclaimed")
            ok(recent_wl.exists(), "B3 fresh whitelisted dir (<6h, live run holds) untouched")
            ok(outsider.exists(), "B4 non-whitelisted aged entry untouched (never deletes foreign)")
            ok(foreign.exists(), "B5 EXCLUDED_PREFIXES family untouched (Chrome etc.)")
            ok(link.is_symlink(),
               "B6 symlink entry itself skipped (never rmtree'd through the link)")
            ok(isinstance(ja.get("summary"), str) and "kept" in ja["summary"],
               "B9 machine receipt carries a summary line (kept/freed visible)")
            ok(held.exists() and any("t260904-02-held" in str(n)
                                     for n in (ja.get("locks_kept_named") or [])),
               "B7b kept live lock is named in the machine receipt (not silent)")
            ok(carrier_dir.exists(),
               "B8 dir holding a live process cwd kept")
            ok(carrier_dir.exists() and any("t260904-02-carrier" in str(n)
                                            for n in (ja.get("carriers_named") or [])),
               "B8b kept live carrier is named in the machine receipt (never kills/silently drops)")
        finally:
            carrier.terminate()
            carrier.wait(timeout=15)
    finally:
        holder.terminate()
        holder.wait(timeout=15)
        shutil.rmtree(box, ignore_errors=True)
        lr.reclaim_registered()

    print("PASS=%d FAIL=%d" % (PASS, FAIL))
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
