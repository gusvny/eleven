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

纯离线零 docker；对树的写入仅限：server/engine/tests/ 下唯一名注入文件 +
integration/test_anchors.json 的暂态改写（字节级备份、finally 恢复）。manifest
缺席=FAIL 点名（L16 未落地，TDD 期红属预期；arbitrate/merge 期必须绿）。
"""
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from lib_result import ScenarioCheck  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
LINT = ["python3", "integration/lint_tests.py"]
MANIFEST = REPO / "integration" / "test_anchors.json"
PLANTED = REPO / "server" / "engine" / "tests" / "test_zz_t26100420_planted_anchor_case.py"
NAME = "t261004-20-test-anchor-brakes"

_ck = ScenarioCheck(detail_cap=800, flush=True)
ok, finish = _ck.ok, _ck.finish


def run_lint():
    r = subprocess.run(LINT, cwd=str(REPO), capture_output=True, text=True, timeout=300)
    return r.returncode, r.stdout + r.stderr


HOME_LINE = 'BAD = "/Users/user/Documents/sandbar/inspection.yaml"\n'
HOME_LINE_POSIX = 'BAD = "/home/user/Documents/sandbar/inspection.yaml"\n'
MARKER_NOSYNC = ("import pytest\n\n\n"
                 "@pytest.mark.production_snapshot\n"
                 "def test_zz_planted_snapshot_without_sync():\n"
                 "    assert True\n")
MARKER_SYNC = ("import pytest\n\n\n"
               '@pytest.mark.production_snapshot(sync="integration/test_anchors.json")\n'
               "def test_zz_planted_declared_snapshot():\n"
               "    assert True\n")


def write_planted(text):
    PLANTED.write_text(text, encoding="utf-8")


def main():
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
                MANIFEST.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
                rc, out = run_lint()
                ok(rc != 0, "B4 L16 manifest coverage: unknown label refused",
                   "lint exited %d on bogus anchor label (expected red)" % rc)
                # restore, then drop a scenario entry (coverage must not shrink silently)
                MANIFEST.write_bytes(manifest_bak)
                data = json.loads(manifest_bak.decode("utf-8"))
                del data["scenarios"][sorted(data["scenarios"])[0]]
                MANIFEST.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
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
            MANIFEST.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                encoding="utf-8")
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
