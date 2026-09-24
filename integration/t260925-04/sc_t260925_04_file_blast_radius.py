#!/usr/bin/env python3
"""文件级爆炸半径端到端契约（t260925-04，registry: t260925-04-file-blast-radius）。

意图（灰盒 L3，ro 池，真实 tmp git 泳道仓 + 真实 git 子进程，秒级零 docker）：
工单用户需求＝「引擎票（写集含 server/engine/ 等粗前缀、恒被判共享）的定点复跑
口径改按**实际改动文件**算」。本场景在**真仓**上驱动引擎公开契约面：
`agent_activities.changed_files`（diff∪status 计算面）×
`shared.targeted_rerun_plan(changed_files=…)`（决策面），逐子用例断言用户可感知行为：

- A 引擎票解禁：写集含 server/engine/、实际只改 app/ 文件（已提交）→ 定点面＝
  上轮红名名单（不再恒全量）——本票的经济性主张本体；
- B 共享面命中恒全量（安全轨①）：实际改动含场景执行器（integration/run_scenarios.py）
  → 全量（空定点面）；C：逐族扫过声明表代表面（verify.yaml / 台账机器
  integration/scenario_ledger.py / 引擎内核 server/engine/ / 闸工具 server/tools/）
  全部全量；
- D 未提交脏面不窄判：工作区未提交改动也进改动清单——脏共享文件（verify.yaml）
  → 全量；仅脏非共享文件 → 仍定点；
- E fail-closed：merge-base 算不出（仓无 main）→ error 非空、清单空 → 恒全量，
  绝不窄判；
- F 未跟踪目录折叠形态（porcelain `?? dir/`）：折叠条目命中共享前缀 → 全量；
  折叠条目在票目录面 → 仍定点；
- G 旧签名逐字兼容：不传 changed_files 的旧调用，引擎写集照旧全量（回放/老票
  零行为变化）。

intent 分工（防重复核对过 SCENARIOS 全清单）：t260924-09 守执行器 --only 入口、
t260922-12 守结果台账定点复跑、t260913-03 守池排除旋钮——均与本条「爆炸半径
判据从写集前缀换成实际文件」不同 intent；developer L1 守纯函数真值矩阵（不碰
真 git 子进程）——本条守真仓上 activity×决策的组件契约链，互不替代。
git 不可用 = ENV_FAIL exit 2。实现落地前红属预期（TDD 信号），arbitrate/merge
期必须绿。
"""
import pathlib
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from lib_env import env_fail  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
ENGINE_SRC = REPO / "server" / "engine"
sys.path.insert(0, str(ENGINE_SRC))

ENGINE_WRITE_SET = ["server/engine/", "integration/", "verify.yaml"]


def _git(repo, *args):
    p = subprocess.run(["git", "-C", str(repo)] + list(args),
                       capture_output=True, text=True, timeout=30)
    if p.returncode != 0:
        return p.returncode, p.stdout, p.stderr
    return 0, p.stdout, ""


_REPO_SEQ = [0]


def make_lane_repo(tmp):
    """真泳道仓形态：main 有基座提交，lane 分支自 main 分出——merge-base 语义同真泳道。
    每次 Seq 自增独立子目录，多仓用例互不串台。"""
    _REPO_SEQ[0] += 1
    repo = tmp / ("lane%d" % _REPO_SEQ[0])
    repo.mkdir()
    assert _git(repo, "init", "-b", "main")[0] == 0
    _git(repo, "config", "user.email", "integ@example.test")
    _git(repo, "config", "user.name", "integ")
    (repo / "base.txt").write_text("base\n")
    (repo / "app").mkdir()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    _git(repo, "checkout", "-b", "lane")
    return repo


def lane_commit(repo, relpath, content="change\n"):
    f = repo / relpath
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content)
    _git(repo, "add", "-A")
    assert _git(repo, "commit", "-m", "touch %s" % relpath)[0] == 0


def changed_files(repo):
    """组件契约面：调引擎 changed_files 活动（async，activity.defn）并落定协程，
    容忍属性/dict 两态回执——断言只落在契约（files: [str], error: str）上。"""
    import asyncio  # noqa: E402
    import shared
    import agent_activities as aa  # noqa: E402
    raw = asyncio.run(aa.changed_files(shared.ChangedFilesArgs(
        ticket_id="t260925-04", worktree=str(repo), branch="lane")))
    files = raw.get("files") if isinstance(raw, dict) else getattr(raw, "files", None)
    error = raw.get("error") if isinstance(raw, dict) else getattr(raw, "error", "")
    return [str(f) for f in (files or [])], str(error or "")


def plan(write_set, reds, changed=None, first_run=False):
    import shared  # noqa: E402
    kwargs = {} if changed is None else {"changed_files": changed}
    return shared.targeted_rerun_plan(write_set, reds, first_run=first_run, **kwargs)


def main():
    if shutil.which("git") is None:
        env_fail("git 可执行缺失（本场景需真 git 子进程驱动 diff/status/merge-base）")
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="t26092504-"))
    legs = []

    def check(name, ok, detail=""):
        legs.append(bool(ok))
        print("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                             ("：%s" % detail) if detail else ""))

    try:
        repo = make_lane_repo(tmp)

        # ---- A 引擎票解禁：只改 app/（非共享面）→ 定点面＝上轮红名 ----
        lane_commit(repo, "app/feature.py")
        files, err = changed_files(repo)
        check("A1 改动清单恰含实际改动文件且零 error",
              err == "" and files == ["app/feature.py"], "files=%r err=%r" % (files, err))
        got = plan(ENGINE_WRITE_SET, ["sc_red_a", "sc_red_b"], changed=files)
        check("A2 引擎票（写集含 server/engine/）实际只改非共享面 → 定点面=上轮红名",
              got == ["sc_red_a", "sc_red_b"],
              "got=%r（恒空=写集前缀旧病灶复燃）" % (got,))

        # ---- B 共享面（场景执行器）命中 → 全量 ----
        lane_commit(repo, "integration/run_scenarios.py")
        files, err = changed_files(repo)
        got = plan(ENGINE_WRITE_SET, ["sc_red_a"], changed=files)
        check("B 改动含场景执行器 run_scenarios.py → 恒全量（安全轨①）",
              err == "" and got == [], "files=%r got=%r" % (files, got))

        # ---- C 共享面逐族代表 → 全量 ----
        for rel in ("verify.yaml", "integration/scenario_ledger.py",
                    "server/engine/shared.py", "server/tools/verify_lane.py"):
            repo2 = make_lane_repo(tmp)
            lane_commit(repo2, rel)
            files2, err2 = changed_files(repo2)
            got2 = plan(ENGINE_WRITE_SET, ["sc_red_c"], changed=files2)
            check("C 改动含共享面 %s → 恒全量" % rel,
                  err2 == "" and got2 == [], "files=%r got=%r" % (files2, got2))

        # ---- D 未提交脏面（diff∪status 并集）----
        repo3 = make_lane_repo(tmp)
        lane_commit(repo3, "app/kept.py")
        (repo3 / "app" / "dirty.py").write_text("dirty\n")  # 未跟踪=脏
        files3, err3 = changed_files(repo3)
        got3 = plan(ENGINE_WRITE_SET, ["sc_red_d"], changed=files3)
        check("D1 仅脏非共享文件（未提交）→ 仍定点（清单含脏面）",
              err3 == "" and "app/dirty.py" in files3 and got3 == ["sc_red_d"],
              "files=%r got=%r" % (files3, got3))
        (repo3 / "verify.yaml").write_text("dirty-shared\n")  # 脏共享面
        files3b, err3b = changed_files(repo3)
        got3b = plan(ENGINE_WRITE_SET, ["sc_red_d"], changed=files3b)
        check("D2 脏共享文件（verify.yaml 未提交）→ 恒全量",
              err3b == "" and got3b == [], "files=%r got=%r" % (files3b, got3b))

        # ---- E fail-closed：merge-base 算不出 ----
        repo4 = make_lane_repo(tmp)
        _git(repo4, "branch", "-D", "main")  # 泳道仓锚定的 merge-base(main, lane) 无从算起
        lane_commit(repo4, "app/feature.py")
        files4, err4 = changed_files(repo4)
        got4 = plan(ENGINE_WRITE_SET, ["sc_red_e"], changed=files4)
        check("E merge-base 失败 → error 点名 + 清单空 → 恒全量（fail-closed）",
              err4 != "" and got4 == [], "err=%r got=%r" % (err4[:120], got4))

        # ---- F 未跟踪目录折叠（porcelain ?? dir/ 形态）----
        repo5 = make_lane_repo(tmp)
        d = repo5 / "integration" / "tests" / "newstuff"
        d.mkdir(parents=True)
        (d / "x.py").write_text("x\n")
        files5, err5 = changed_files(repo5)
        got5 = plan(ENGINE_WRITE_SET, ["sc_red_f"], changed=files5)
        check("F1 未跟踪目录折叠命中共享前缀（integration/tests/）→ 全量",
              err5 == "" and got5 == [], "files=%r got=%r" % (files5, got5))
        repo6 = make_lane_repo(tmp)
        d6 = repo6 / "tickets" / "t260925-04"
        d6.mkdir(parents=True)
        (d6 / "note.md").write_text("n\n")
        files6, err6 = changed_files(repo6)
        got6 = plan(ENGINE_WRITE_SET, ["sc_red_f"], changed=files6)
        check("F2 未跟踪目录在票目录面 → 仍定点",
              err6 == "" and got6 == ["sc_red_f"], "files=%r got=%r" % (files6, got6))

        # ---- G 旧签名逐字兼容（不传 changed_files）----
        got7 = plan(ENGINE_WRITE_SET, ["sc_red_g"])
        check("G1 旧调用（引擎写集、无 changed_files）→ 照旧全量",
              got7 == [], "got=%r" % (got7,))
        got8 = plan(["app/", "tickets/"], ["sc_red_g"])
        check("G2 旧调用（局部写集）→ 照旧定点",
              got8 == ["sc_red_g"], "got=%r" % (got8,))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    n_fail = legs.count(False)
    print("SUMMARY pass=%d fail=%d env_fail=0 na=0"
          % (len(legs) - n_fail, n_fail))
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
