#!/usr/bin/env python3
"""t261004-20 场景：测试锚三层刹车（anchor manifest / home-path / snapshot declaration）。

用户场景（工单正文，宿主 261004 实问「集成测试是不是写死的检查」）：两天内两条
production-snapshot 断言在合法改动下把 main 打红、堵住所有到闸票的合并检查——
根因是断言锚错了对象（锚生产文件当前值而非不变式）且没有任何机械层拦住这类锚
回潮。本票给测试面装三层刹车（L16 anchor manifest 覆盖 / L17 绝对 home 路径 /
L18 production-snapshot 声明制），本场景从**用户可感知契约**（刹车真会咬）做
错误注入端到端验证：往被测树里真种一棵病灶，看 lint 真红并点名病灶文件；种一棵
合规声明，看 lint 真绿；撤除后树恢复基线绿。developer 的 L1 钉 lint 函数真值
分支（白盒），本条锁「种病灶→lint 红→点名→清场→回绿」的全链行为面，不互替。

契约（工单交付物 A/C/D 的机械半边；灰盒断言只落在 lint 的退出码与病灶点名上，
不锚 lint 内部实现形状，也**不锚刹车编号**——编号是实现侧标注，落地编号可能
与方案草拟号不同）：
  B1 基线：lint 机械健康（跑到 summary 行）；基线绿绿与否只记录不断言——
     树内与本票无关的存量债不得永久打红本场景（刹车断言全部相对基线做 delta）。
  B2 home-path 咬合：树内任一 engine test 文件出现绝对 /Users/<name>/ 路径字面量 →
     lint 红且输出点名该文件（报错精确：说得清哪个文件）。
  B3 词表泛化：/home/<name>/ 同形字面量同样红（按方案声明泛化；实现只查
     /Users 期红属预期，arbitrate/merge 期必须绿）。
  B4 manifest 覆盖：anchor manifest 里出现词表外 label（bogus）→ lint 红；
      manifest 丢失一个在册文件条目 → lint 红（覆盖不静默缩水）。
  B5 拒收：production-snapshot 标注的测试文件不带 sync 声明 → lint 红点名
      （「新增快照断言必须声明同步路径」的拒收半边）。
  B6 放行：同一病灶补上 sync 声明 + manifest 里 production-snapshot 条目 →
      lint 不再点名该文件（声明制是出路，不是一刀切禁令）。
  B7 清场不变式：全部注入撤除后 lint 回到基线判定（场景零残留——扫描器自己也是
      「绝不吃树」契约的消费者，KISS：注入文件用唯一名，finally 恒撤）。
  B8 (t261009-52) 中断可清场：finally 不够（SIGINT/SIGTERM 不走 finally）——
      reclaim 例程自足、挂 SIGINT/SIGTERM/atexit，收尾后按默认处置重投信号
      （吞掉中断=假绿）；开场 pre-flight 查漏（上轮残留具名报告后清掉）；
      自检 fixture 注册表（漂移=拒绝面失守，响亮失败）。

纯离线零 docker；对树的写入仅限：server/engine/tests/ 下唯一名注入文件 +
integration/test_anchors.json 的暂态改写（字节级备份、finally 恢复；改写走
lib_registry.write_registry 规范序列化）+ .sandbar/ 下的排他锁文件。manifest
缺席=FAIL 点名（L16 未落地，TDD 期红属预期；arbitrate/merge 期必须绿）。
B9 (t261009-52 验收返工) 同树互斥：并发第二跑=具名拒收（flock 运行期持有；
实测并发碰撞：绿撤后病灶复活、同输入 lint 判定不稳）。
"""
import os
import pathlib
import signal
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from lib_result import ScenarioCheck  # noqa: E402
import lib_fault_injection  # noqa: E402  (t261009-52: the ONE fixture registry)
import lib_registry  # noqa: E402  (t261009-51: canonical registry serialization)

REPO = pathlib.Path(__file__).resolve().parents[2]
# t261011-22 (host refinement): this scenario tests the LINT MECHANISM —
# "plant a lesion -> the rule goes red and names the file -> clean tree back
# to baseline" — so it invokes only the three rules the plant bites (L16
# anchor manifest, L17 home-path, L18 snapshot discipline) via the --rules
# subset selector, never the full ~20-rule battery (~100 s per run; the
# round's 180 s item was this scenario buying its evidence with full lint
# runs). The full battery keeps being covered by ordinary rounds.
# NOTE (t261011-22, spec §5 tradeoff, deliberate): the plant stays in the
# REAL delivered tree and this entry stays in the exclusive pool — the
# mechanism under proof is "a leaked fixture on the DELIVERED tree is named
# and reclaimed" (KI-222's leak entered a ticket lane from the real tree), so
# a temporary tree copy would no longer prove it. The cost that motivated the
# exclusive pool is removed by the scoped lint + the explicit PLANTED:
# handshake instead.
LINT = ["python3", "integration/lint_tests.py",
        "--rules=L16,L17,L18"]
MANIFEST = REPO / "integration" / "test_anchors.json"
PLANTED = REPO / "server" / "engine" / "tests" / "test_zz_t26100420_planted_anchor_case.py"
NAME = "t261004-20-test-anchor-brakes"

_ck = ScenarioCheck(detail_cap=800, flush=True)
ok, finish = _ck.ok, _ck.finish


def run_lint():
    # SANCTIONED-WAIT: hard kill ceiling on a child lint subprocess, never slept to.
    r = subprocess.run(LINT, cwd=str(REPO), capture_output=True, text=True, timeout=120)
    return r.returncode, r.stdout + r.stderr


HOME_LINE = 'BAD = "/Users/xingu/Documents/sandbar/inspection.yaml"\n'
HOME_LINE_POSIX = 'BAD = "/home/xingu/Documents/sandbar/inspection.yaml"\n'
MARKER_NOSYNC = ("import pytest\n\n\n"
                 "@pytest.mark.production_snapshot\n"
                 "def test_zz_planted_snapshot_without_sync():\n"
                 "    assert True\n")
MARKER_SYNC = ("import pytest\n\n\n"
               '@pytest.mark.production_snapshot(sync="integration/test_anchors.json")\n'
               "def test_zz_planted_declared_snapshot():\n"
               "    assert True\n")


def write_planted(text):
    # Explicit plant handshake (t261011-22 spec §5): the file exists on disk
    # BEFORE the line is printed, and the line is flushed immediately — a
    # parent acting on "PLANTED:" can never observe a half-written file, and
    # it never has to poll the tree for the fixture's appearance.
    PLANTED.write_text(text, encoding="utf-8")
    print("PLANTED: %s" % PLANTED.relative_to(REPO), flush=True)


# ---- t261009-52: interruption-proof cleanup --------------------------------
# Failure record (KI-222): a bare `finally` does not run on SIGINT/SIGTERM, so
# an interrupted run left the fixture on the tree and an add-everything settle
# later committed it into a ticket's lane. The reclaim routine below is
# SELF-CONTAINED (reads only module-level state captured at plant time — review
# condition 2: a signal handler must not rely on locals mutated later) and is
# wired to SIGINT, SIGTERM and atexit, so normal exit, error, Ctrl-C and `kill`
# all reach the same reclaim. After reclaiming, the handler restores the
# DEFAULT disposition and re-delivers the signal to self, so the harness still
# sees the interrupt (a swallowed SIGINT would turn an interrupt into a
# fake-green exit).

_RECLAIM_STATE = {"manifest_bak": None}


def _reclaim():
    """Idempotent tree reclaim: restore the manifest byte-backup, unlink the
    fixture. Safe to call from a handler, atexit, finally, or twice."""
    bak = _RECLAIM_STATE["manifest_bak"]
    if bak is not None:
        try:
            MANIFEST.write_bytes(bak)
        except OSError:
            pass
    PLANTED.unlink(missing_ok=True)


def _reclaim_and_reraise(signum, _frame):
    _reclaim()
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)


def install_reclaim_guards():
    import atexit
    atexit.register(_reclaim)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _reclaim_and_reraise)


def check_registry_self():
    """The scenario self-checks its own fixture against the shared registry
    (t261009-52): registry drift would silently disarm the settle-side refusal,
    so it fails the scenario loudly instead."""
    registered = lib_fault_injection.fixture_scenario(
        "server/engine/tests/" + PLANTED.name)
    if registered != NAME:
        raise SystemExit(
            "fixture registry drift: lib_fault_injection.FIXTURES must map "
            "server/engine/tests/%s to %r (got %r) — the settle refusal is "
            "disarmed until this is fixed" % (PLANTED.name, NAME, registered))


def preflight_leak_check():
    """Named report at start when the previous run leaked (t261009-52 §4):
    SIGKILL cannot be handled, so the NEXT run reports the leak by name and
    cleans it instead of silently proceeding with a dirty tree."""
    if PLANTED.exists():
        print("  note pre-flight: the previous run of %s leaked %s — removed "
              "before starting" % (NAME, PLANTED), flush=True)
        PLANTED.unlink(missing_ok=True)


# ---- t261009-52 acceptance rework: exclusive same-tree planting -------------
# (the lock itself lives in lib_fault_injection.acquire_planting_lock — ONE
#  declaration shared with the two L3 cases' manual-plant windows)
# Measured 261010 (acceptance walkthrough): two concurrent brake runs in one
# tree collide — each transiently rewrites the anchor manifest while the other's
# lint reads it (lint verdict instability 0 vs 4 errors over identical input)
# and the fixture RESURRECTS after one run's green reclaim while the other is
# still mid-run — spec §(3) violated in its own words. Fix (option (a), the
# smaller one): an exclusive lock file held for the run's lifetime; a second
# concurrent run is refused BY NAME instead of colliding. The lock lives under
# the repo's own .sandbar evidence area (gitignored — the guard must not dirty
# the very tree it protects).

def main():
    check_registry_self()
    # held for the process lifetime = the lock's lifetime (acceptance rework)
    global _LOCK_FH
    _LOCK_FH = lib_fault_injection.acquire_planting_lock(REPO)
    preflight_leak_check()
    install_reclaim_guards()
    # B1: baseline — lint mechanically healthy; greenness recorded, not asserted
    # (unrelated pre-existing debt in other files must not permanently red THIS
    # scenario; every brake assertion below is a delta against this baseline).
    rc0, out0 = run_lint()
    ok("LINT done" in out0, "B1 baseline: lint runs to a summary line",
       "no 'LINT done' summary in output; head=%s" % out0[:300])
    if rc0 != 0:
        print("  note B1: baseline lint red (pre-existing debt outside this "
              "ticket's face); brake assertions are delta-vs-baseline",
              flush=True)

    def no_new_red(rc, out, label):
        """Planted fault must not just stay at baseline red: it must add a
        finding that names the planted file."""
        ok(rc != 0 or "LINT done: 0 error" not in out,
           label + ": lint red", "lint exited %d (expected nonzero)" % rc)
        ok(PLANTED.name in out, label + ": lint names the planted file",
           "output did not mention %s" % PLANTED.name)

    # B2 / B3: home-path injection (two vocabulary shapes)
    for label, line in (("B2 home-path brake fires on /Users/<name>/", HOME_LINE),
                        ("B3 home-path brake fires on /home/<name>/", HOME_LINE_POSIX)):
        try:
            write_planted(line)
            rc, out = run_lint()
            no_new_red(rc, out, label)
        finally:
            PLANTED.unlink(missing_ok=True)

    manifest_bak = None
    if MANIFEST.exists():
        manifest_bak = MANIFEST.read_bytes()
        _RECLAIM_STATE["manifest_bak"] = manifest_bak
    try:
        # B4: manifest coverage — unknown label, then dropped entry
        if manifest_bak is None:
            ok(False, "B4 L16 manifest coverage: unknown label refused",
               "integration/test_anchors.json missing — anchor manifest (L16) not landed")
            ok(False, "B4b L16 manifest coverage: dropped entry refused",
               "integration/test_anchors.json missing — anchor manifest (L16) not landed")
        else:
            import json
            data = json.loads(manifest_bak.decode("utf-8"))
            # shape (t261004-20 implement): {"_header":..., "engine_tests": {...},
            #   "scenarios": {...}} keyed by repo-relative path
            et = data.get("engine_tests") or {}
            sc = data.get("scenarios") or {}
            if et and sc:
                k0 = sorted(et)[0]
                et[k0] = {"anchor": "bogus", "note": "injected", "sync_path": ""}
                lib_registry.write_registry(MANIFEST, data)
                rc, out = run_lint()
                ok(rc != 0, "B4 L16 manifest coverage: unknown label refused",
                   "lint exited %d on bogus anchor label (expected red)" % rc)
                # restore, then drop a scenario entry (coverage must not shrink silently)
                MANIFEST.write_bytes(manifest_bak)
                data = json.loads(manifest_bak.decode("utf-8"))
                del data["scenarios"][sorted(data["scenarios"])[0]]
                lib_registry.write_registry(MANIFEST, data)
                rc, out = run_lint()
                ok(rc != 0, "B4b L16 manifest coverage: dropped entry refused",
                   "lint exited %d with an entry removed (expected red)" % rc)
            else:
                ok(False, "B4 L16 manifest coverage: unknown label refused",
                   "manifest shape unexpected (no engine_tests/scenarios maps); cannot mutate safely")

        # B5: undeclared snapshot refused
        write_planted(MARKER_NOSYNC)
        rc, out = run_lint()
        no_new_red(rc, out, "B5 snapshot brake refuses undeclared snapshot")
        PLANTED.unlink(missing_ok=True)

        # B6: declared snapshot accepted (marker + sync + manifest entry):
        # acceptance = no NEW finding naming the planted file, and lint exits
        # no worse than baseline (unrelated baseline debt is not this face).
        if manifest_bak is None:
            ok(False, "B6 snapshot brake accepts declared snapshot",
               "integration/test_anchors.json missing — cannot declare a snapshot")
        else:
            write_planted(MARKER_SYNC)
            import json
            data = json.loads(manifest_bak.decode("utf-8"))
            entry = {"anchor": "production-snapshot",
                     "sync_path": "integration/test_anchors.json",
                     "note": "declared snapshot injection (removed in finally)"}
            data.setdefault("engine_tests", {})[
                "server/engine/tests/" + PLANTED.name] = entry
            lib_registry.write_registry(MANIFEST, data)
            rc, out = run_lint()
            ok(PLANTED.name not in out,
               "B6 snapshot brake accepts declared snapshot",
               "declared snapshot still named in lint output: %s"
               % [l for l in out.splitlines() if PLANTED.name in l][:2])
    finally:
        PLANTED.unlink(missing_ok=True)
        if manifest_bak is not None:
            MANIFEST.write_bytes(manifest_bak)

    # B7: tree restored — lint back to byte-identical baseline verdict
    rc7, out7 = run_lint()
    ok(rc7 == rc0, "B7 cleanup: lint back to baseline verdict",
       "baseline exit=%d, after cleanup exit=%d" % (rc0, rc7))

    finish(NAME)


if __name__ == "__main__":
    main()
