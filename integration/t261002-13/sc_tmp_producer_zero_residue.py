#!/usr/bin/env python3
"""sc_tmp_producer_zero_residue — 夹具生产者全终态零残留（t261002-13，灰盒 L3）。

被测出口：本票点名的最大泄漏家族生产者 server/engine/tests/
test_t260904_02_registry_anchor.py（ticket 直方图 #1：t260904-02-* 15,640 个存量、
~437 个/24h——每日巡检重跑此文件即持续增生），真子进程 pytest 驱动、隔离 TMPDIR
沙盒，零碰宿主真 temp。intent（工单交付物 1：终态回收——每个终态
pass/fail/env-fail/cancel 都必须回收；本场景黑盒锁其中两个可独立到达的终态，
fail/env-fail 与 pass 同走解释器退出+atexit 同一条回收路，由 developer L1 的
helper 终态矩阵钉住，此处不重复）：
  A pass 终态：pytest 全绿退出后，隔离 TMPDIR 里 t260904-02-* 残留 = 0
    （用户可感知契约：每日巡检重跑不再累积夹具目录）；
  B cancel 终态：运行中向 pytest 进程发 SIGINT，等它走完收口退出后残留 = 0
    （中断不是豁免口——正是 261001 载体风暴里「finally 没跑就漏」的对面）。
  C 生产者迁移钉：生产者文件里不再有裸 tempfile.mkdtemp( 调用点（revert 即红，
    工单验收口径 1；与 integration/lint_tests.py L8 的 baseline 语义互补——L8 管
    全仓「新债」，本条钉本票点名的具体文件）。
intent 分工：_tmp_reclaim helper 的注册/幂等 reap/atexit 终态矩阵归 developer L1
（server/engine/tests/ 白盒）；t260908-02-ut / t260901-14 等其余家族的迁移面由
同一 helper 同一机制覆盖，不逐家族重复本场景（intent 级重复禁令）。
实现未落地段红属预期（TDD 信号），arbitrate/merge 期必须绿。
三态：pytest 运行器缺席=ENV_FAIL exit 2；残留>0/断言败=FAIL exit 1；全过=exit 0。

Run directly: python3 integration/t261002-13/sc_tmp_producer_zero_residue.py（cwd=仓根）。
"""
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PRODUCER = ROOT / "server" / "engine" / "tests" / "test_t260904_02_registry_anchor.py"
PREFIX = "t260904-02-"

PASS, FAIL = 0, 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✓ %s" % label)
    else:
        FAIL += 1
        print("  ✗ %s" % label)


def pick_python():
    # 引擎 venv 唯一活源（t260907-10 迁仓后旧位置的 venv 是已退役死路径——
    # engine-layout 陈旧路径守卫点名的那处残留，字面路径不落本文件，守卫才认零）。
    # 回落链与 verify.yaml test 道同口径：[ -x venv ] || python3。
    cand = ROOT / "server/engine/.venv/bin/python"
    if cand.is_file():
        return str(cand)
    return sys.executable  # stdlib 回落（verify.yaml test 道同链末端）


def residue(box):
    return [n for n in os.listdir(box) if n.startswith(PREFIX)]


def main():
    if not PRODUCER.is_file():
        print("ENV_FAIL: producer file missing: %s" % PRODUCER, file=sys.stderr)
        sys.exit(2)
    py = pick_python()
    if shutil.which(py) is None and not Path(py).is_file():
        print("ENV_FAIL: no runnable python for pytest: %s" % py, file=sys.stderr)
        sys.exit(2)

    sys.path.insert(0, str(ROOT / "integration"))
    import lib_tmp_reclaim as lr

    box = tempfile.mkdtemp(prefix="t261002-13-s3-box-")
    lr.register_tmp_path(Path(box), "sc_tmp_producer_zero_residue sandbox")
    env = dict(os.environ, TMPDIR=box, TMP=box, PYTHONPYCACHEPREFIX=os.path.join(box, "pyc"))

    try:
        # ---- C 生产者迁移钉（离线源码断言，先于慢子进程） ----
        text = PRODUCER.read_text(encoding="utf-8")
        ok("mkdtemp_reclaimed" in text,
           "C1 producer mints fixture dirs via the reclaimed helper")
        ok("tempfile.mkdtemp(" not in text,
           "C2 zero raw tempfile.mkdtemp( call sites left in the producer (revert re-reds)")

        # ---- A pass 终态 ----
        t0 = time.monotonic()
        r = subprocess.run([py, "-m", "pytest", str(PRODUCER), "-q", "-x",
                            "-p", "no:cacheprovider"],
                           cwd=str(ROOT), env=env, capture_output=True,
                           text=True, timeout=300)
        dt = time.monotonic() - t0
        if "No module named pytest" in (r.stdout + r.stderr):
            print("ENV_FAIL: pytest unavailable in %s" % py, file=sys.stderr)
            sys.exit(2)
        ok(r.returncode == 0,
           "A1 producer suite passes in isolation (exit 0, %.0fs)" % dt)
        ok(residue(box) == [],
           "A2 pass terminal state leaves zero %s* dirs in TMPDIR (found %d: %s)"
           % (PREFIX, len(residue(box)), residue(box)[:3]))

        # ---- B cancel 终态（SIGINT 运行中打点） ----
        for f in os.listdir(box):
            shutil.rmtree(os.path.join(box, f), ignore_errors=True)
        p = subprocess.Popen([py, "-m", "pytest", str(PRODUCER), "-q",
                              "-p", "no:cacheprovider"],
                             cwd=str(ROOT), env=env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        interrupted = False
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if p.poll() is not None:
                break
            if residue(box):
                p.send_signal(signal.SIGINT)
                interrupted = True
                break
            time.sleep(0.01)
        try:
            p.wait(timeout=120)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
            interrupted = False
        ok(interrupted, "B1 run reached a minted fixture dir and was SIGINT-interrupted mid-run")
        ok(p.returncode != 0, "B2 interrupted run exits non-zero (not a fake pass)")
        ok(residue(box) == [],
           "B3 cancel terminal state leaves zero %s* dirs (found %d: %s)"
           % (PREFIX, len(residue(box)), residue(box)[:3]))
    finally:
        shutil.rmtree(box, ignore_errors=True)
        lr.reclaim_registered()

    print("PASS=%d FAIL=%d" % (PASS, FAIL))
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
