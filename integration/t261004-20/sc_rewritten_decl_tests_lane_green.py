#!/usr/bin/env python3
"""t261004-20 场景：两条生产声明测试改判不变式后在泳道树内真跑全绿。

用户场景（工单正文 261004 两条事故）：宿主把 doc face 改成每天跑的**合法改动**
把 test_real_decl_parses_and_existing_instances_unchanged 打红（它锚生产声明当前
cron/suite 值=production-snapshot 锚）；skip-switch 测试经硬编码机器路径
/Users/xingu/Documents/sandbar/inspection.yaml 读生产声明——在泳道 worktree 里
读的是主 checkout 的树（检错了对象）。修复后用户可感知契约：

  R1 两条测试在本泳道 worktree 真跑全绿（engine venv pytest、cwd=仓根）——
     不变式对任何合法声明成立，合法改动（改 cron/开关集合）不再打红。
  R2 cwd 无关：从无关目录（temp dir）调用 pytest 同样全绿——测试不绑调用
     位置（绑 cwd 是绑机器形态的近亲）。
  R3 事故字面量回归钉：两个点名文件内零 `/Users/xingu/Documents/sandbar` 字面量
     （事故根源=机器路径绑定；全树扫描是 L17 的面，本条只钉本票点名两文件的
     复发，KI 事故回归纪律）。
  R4 事故当前值断言回归钉：事故中的**等值断言形态**（cron == "0 10 * * 1" /
     cron == "30 9 * * *" / suite == "full"）不得回潮到这两个文件——裸字面量出现
     不判（夹具 YAML 与合成输入里的 cron 值是合法数据，同文件 deadman 夹具在册）；
     锚回潮的最小哨兵，泛化执法归 lint 机械层，不在此重复全族扫描。

纯离线零 docker；ENV_FAIL 面=engine venv python 缺席（回落链镜 verify.yaml test
道，缺席 exit 2 点名，不静默降级）。实现落地前红属预期（TDD 信号），
arbitrate/merge 期必须绿。intent 分工：L16/L17/L18 机械层归
t261004-20-test-anchor-brakes（咬合面）；本条锁**修复后的两条测试本身**在真树
里的行为面。"""
import pathlib
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from lib_result import ScenarioCheck  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
NAME = "t261004-20-rewritten-decl-tests-lane-green"
TARGETS = ["server/engine/tests/test_t260915_18_inspection_stage.py",
           "server/engine/tests/test_260929_inspection_no_change_skip.py"]
MACHINE_PATH = "/Users/xingu/Documents/sandbar"
INCIDENT_LITERALS = ['== "30 9 * * *"', '== "0 10 * * 1"', 'suite == "full"']

_ck = ScenarioCheck(detail_cap=800, flush=True)
ok, env_fail, finish = _ck.ok, _ck.env_fail, _ck.finish


def engine_python():
    """Absolute path of the engine python (absolute: the R2 subcase invokes it
    from an unrelated cwd, where a repo-relative path would not resolve)."""
    for cand in ("server/engine/.venv/bin/python",
                 "server/dsh/temporal-poc/.venv/bin/python"):  # engine-venv-compat（t260907-10：新路径优先、旧路径一轮回落，摘除票删旧回落）
        p = REPO / cand
        if p.exists():
            return str(p)
    return sys.executable  # documented last leg: bare python3


def run_pytest(cwd):
    py = engine_python()
    # absolute targets: the R2 subcase invokes from an unrelated cwd
    cmd = [py, "-m", "pytest", "-q", "-p", "no:cacheprovider"] + \
          [str(REPO / t) for t in TARGETS]
    r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                       timeout=900, env={"PATH": "/usr/bin:/bin:/usr/local/bin",
                                         "PYTHONDONTWRITEBYTECODE": "1"})
    return r.returncode, r.stdout + r.stderr


def main():
    # R3 / R4: source-level incident regression pins (stdlib, no env dependency)
    for rel in TARGETS:
        text = (REPO / rel).read_text(encoding="utf-8")
        ok(MACHINE_PATH not in text,
           "R3 %s: no machine-path literal" % pathlib.Path(rel).name,
           "file still contains %s" % MACHINE_PATH)
        hits = [lit for lit in INCIDENT_LITERALS if lit in text]
        ok(not hits,
           "R4 %s: incident value literals gone" % pathlib.Path(rel).name,
           "still contains %s" % hits)

    # R1: green in the lane tree (cwd = repo root)
    rc, out = run_pytest(REPO)
    ok(rc == 0, "R1 rewritten tests green in lane worktree",
       "pytest exit=%d tail=%s" % (rc, out[-400:]))

    # R2: cwd independence
    with tempfile.TemporaryDirectory(prefix="t26100420-cwd-") as td:
        rc2, out2 = run_pytest(pathlib.Path(td))
        ok(rc2 == 0, "R2 rewritten tests green from unrelated cwd",
           "pytest exit=%d tail=%s" % (rc2, out2[-400:]))

    finish(NAME)


if __name__ == "__main__":
    main()
