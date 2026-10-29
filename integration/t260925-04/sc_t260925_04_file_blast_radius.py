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
- E fail-closed：merge-base 算不出（仓无 main）→ error 点名、清单空 → 恒全量，
  绝不窄判；
- F 未跟踪目录折叠形态（porcelain `?? dir/`）：折叠条目命中共享前缀 → 全量；
  折叠条目在票目录面 → 仍定点；
- G 旧签名逐字兼容：不传 changed_files 的旧调用，引擎写集照旧全量（回放/老票
  零行为变化）。

基线上下文自建（t261029-41，KI-413）：本用例**不依赖「跑它的检出是哪一支」**。
每个子用例在 tmp 下自建真泳道形态：项目根 `<tmp>/pN`（分支 main 的基座提交）＋
`git worktree add` 真挂载的泳道工作树 `<tmp>/pN/.lane/laneN`（分支
`lane/t260925-04`）。`<repo>/.lane/<id>` 正是引擎认的泳道路径约定，所以引擎把 git
命令锚在夹具仓上——在普通检出、detached clone（线轮环境）、以及任何「按路径约定
定位仓根」的实现下都一样成立。基线 ref（merge-base(main, 泳道分支)）由夹具自己的
git 先探针算出，再交给引擎公开入参（worktree=泳道工作树、branch=分支名）。换句话说：
本用例绿不绿，不取决于「仓根解析启发式」（`_lane_repo_root` 一族）修没修——传入的
工作树与路径约定解出的仓根落在同一个夹具仓上，两条锚定路径都成立。

三态口径（KI-413 的教训：上下文缺失绝不是内容红）：
- 夹具探不到基线（分支/merge-base 建不出来）→ `ENV_FAIL: changed-file baseline
  missing (probed …)` exit 2；
- 引擎回执点名「改动清单不可得／基线分支不可解析」而夹具探针解得开 → 同上 ENV_FAIL
  （缺的是上下文握手，不是被测内容——旧口径在此处退化成 11 条内容假红并冻住轮次）；
- 引擎交出非空清单之后的判定照旧是内容断言：真爆炸半径回归仍然红（见 C/D 子用例与
  产品单写者 shared.changed_files_blast_radius）。
E 子用例是**构造性**的基线缺失（故意删掉 main），属于被测故障面，照旧内容断言，不走
ENV_FAIL。

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

#: 夹具自建的泳道分支名（真泳道形态 `lane/<ticket>`；不用裸 `lane`，免得看起来像
#: 某个检出上的环境分支）。
LANE_BRANCH = "lane/t260925-04"
#: 基线的对侧分支（引擎 merge-base 的另一端）。
BASE_BRANCH = "main"
#: 引擎「改动清单不可得」的文案族（两代口径都在册：main 的 `merge-base 解析失败`、
#: develop 线的 `changed-file list unavailable … not resolvable`）。命中且夹具探针
#: 解得开 = 上下文握手缺失 = ENV_FAIL，绝不落成内容红（KI-413）。
BASELINE_UNAVAILABLE_MARKS = (
    "changed-file list unavailable",
    "merge-base",
    "not resolvable",
    "lane manifest",
    "branch 缺失",
)


def _git(repo, *args, what=""):
    """真 git 子进程（有界超时）。what 非空=这一步是**夹具自建上下文**：失败即
    ENV_FAIL（`ENV_FAIL: <缺什么> missing (<探了什么>)` exit 2），绝不退化成内容红
    ——夹具建不出泳道/基线是环境不在，不是被测内容红（KI-413 的三态口径）。"""
    p = subprocess.run(["git", "-C", str(repo)] + list(args),
                       capture_output=True, text=True, timeout=30)
    if what and p.returncode != 0:
        env_fail("%s missing (probed `git -C %s %s` rc=%s: %s)"
                 % (what, repo, " ".join(str(a) for a in args), p.returncode,
                    ((p.stderr or p.stdout or "").strip() or "no output")[-300:]))
    if p.returncode != 0:
        return p.returncode, p.stdout, p.stderr
    return 0, p.stdout, ""


_REPO_SEQ = [0]


def make_lane_fixture(tmp):
    """真泳道形态夹具：项目根 `<tmp>/pN`（main 上的基座提交）＋真挂载泳道工作树
    `<tmp>/pN/.lane/laneN`（分支 `lane/t260925-04`）。返回 (项目根, 泳道工作树)。

    泳道工作树是 `git worktree add` 真挂载的：分支、merge-base、diff、status 在
    两条路径上语义一致（工作树与仓库共用对象库/ref），引擎无论把 git 命令锚在
    「传入的工作树」还是「按 `<repo>/.lane/<id>` 约定解出的仓根」都落在夹具上。
    每次 Seq 自增独立子目录，多仓用例互不串台。"""
    _REPO_SEQ[0] += 1
    root = tmp / ("p%d" % _REPO_SEQ[0])
    root.mkdir()
    _git(root, "init", "-b", BASE_BRANCH, what="fixture repo (git init -b %s)" % BASE_BRANCH)
    _git(root, "config", "user.email", "integ@example.test",
         what="fixture repo identity (git config user.email)")
    _git(root, "config", "user.name", "integ",
         what="fixture repo identity (git config user.name)")
    # 引擎仓自己的 .gitignore 立场（.lane/ .worktrees/ .sandbar/ .suyou/ 永不入库）：
    # 基座提交带上同一份，泳道工作树与协调目录才不会以未跟踪面目污染 status 面。
    (root / ".gitignore").write_text(".lane/\n.worktrees/\n.sandbar/\n.suyou/\n")
    (root / "base.txt").write_text("base\n")
    (root / "app").mkdir()
    _git(root, "add", "-A",
         what="fixture base commit (git add -A)")
    _git(root, "commit", "-m", "base", what="fixture base commit (git commit)")
    lane = root / ".lane" / ("lane%d" % _REPO_SEQ[0])
    _git(root, "worktree", "add", "-b", LANE_BRANCH, str(lane),
         what="lane worktree on branch %r (git worktree add -b)" % LANE_BRANCH)
    return root, lane


def lane_commit(lane, relpath, content="change\n"):
    """在泳道工作树上提交一个改动（走得是泳道分支的 diff 面）。"""
    f = lane / relpath
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content)
    _git(lane, "add", "-A", what="fixture lane change (%s) staged" % relpath)
    _git(lane, "commit", "-m", "touch %s" % relpath,
         what="fixture lane commit (%s)" % relpath)


def drop_base_branch(root):
    """E 子用例专用：拆掉基线对侧分支，让 merge-base(main, 泳道) 无从算起。
    项目根自己的工作树正占着 main，先 detach 才删得掉。"""
    _git(root, "checkout", "--detach", what="fixture detach of the project root")
    _git(root, "branch", "-D", BASE_BRANCH,
         what="removal of the baseline branch %r (E sub-case)" % BASE_BRANCH)


def lane_baseline(lane):
    """夹具自证基线：泳道分支可解析 ＋ merge-base(main, 泳道) 可算出。
    返回 (基线 sha, 探针文案)；sha 空=本用例需要的上下文确实不在。"""
    rc, out, err = _git(lane, "rev-parse", "--verify", "--quiet",
                        "%s^{commit}" % LANE_BRANCH)
    if rc != 0 or not (out or "").strip():
        return "", ("rev-parse --verify --quiet %r^{commit} in %s rc=%s: %s"
                    % (LANE_BRANCH, lane, rc,
                       ((err or out or "").strip() or "no output")[-200:]))
    rc, out, err = _git(lane, "merge-base", BASE_BRANCH, LANE_BRANCH)
    if rc != 0 or not (out or "").strip():
        return "", ("merge-base %s %s in %s rc=%s: %s"
                    % (BASE_BRANCH, LANE_BRANCH, lane, rc,
                       ((err or out or "").strip() or "no output")[-200:]))
    return out.strip().splitlines()[0].strip(), ""


def guard_baseline(lane, leg, product_err=""):
    """KI-413 守卫：基线上下文缺失 = ENV_FAIL（exit 2），绝不成片内容红。

    两条缺失路径：①夹具自证探针解不出基线（夹具建不出来/删掉了分支）；
    ②夹具解得开而引擎回执点名清单不可得（引擎没看见夹具的泳道上下文——旧口径
    在这里退化成 11 条内容假红）。文案按 `ENV_FAIL: <缺什么> missing (<探了什么>)`。"""
    ref, probe = lane_baseline(lane)
    if not ref:
        env_fail("changed-file baseline missing (probed %s; leg %s)" % (probe, leg))
    if product_err and any(m in product_err for m in BASELINE_UNAVAILABLE_MARKS):
        env_fail("changed-file baseline missing (probed %r resolves and "
                 "merge-base %s %s = %s in the fixture lane %s; leg %s: the engine "
                 "reported the changed-file list unavailable: %s)"
                 % (LANE_BRANCH, BASE_BRANCH, LANE_BRANCH, ref, lane, leg,
                    str(product_err).strip()[:300]))


def changed_files(lane):
    """组件契约面：调引擎 changed_files 活动（async，activity.defn）并落定协程，
    容忍属性/dict 两态回执——断言只落在契约（files: [str], error: str）上。
    入参是**夹具自建**的泳道上下文：worktree=泳道工作树、branch=泳道分支。"""
    import asyncio  # noqa: E402
    import shared
    import agent_activities as aa  # noqa: E402
    raw = asyncio.run(aa.changed_files(shared.ChangedFilesArgs(
        ticket_id="t260925-04", worktree=str(lane), branch=LANE_BRANCH)))
    files = raw.get("files") if isinstance(raw, dict) else getattr(raw, "files", None)
    error = raw.get("error") if isinstance(raw, dict) else getattr(raw, "error", "")
    return [str(f) for f in (files or [])], str(error or "")


def baseline_files(lane, leg):
    """改动清单（含上下文守卫）：清单不可得=上下文缺失=ENV_FAIL，见 guard_baseline。"""
    files, err = changed_files(lane)
    guard_baseline(lane, leg, err)
    return files, err


def plan(write_set, reds, changed=None, first_run=False):
    import shared  # noqa: E402
    kwargs = {} if changed is None else {"changed_files": changed}
    return shared.targeted_rerun_plan(write_set, reds, first_run=first_run, **kwargs)


def probe_engine():
    """被测面先自证可导入：引擎模块导不进来=环境红（ENV_FAIL），不是内容红
    （同族三态口径；正文断言才有资格判内容）。"""
    try:
        import shared           # noqa: F401
        import agent_activities  # noqa: F401
    except Exception as e:  # noqa: BLE001 —— 导入失败即环境缺件，如实具名
        env_fail("engine modules unimportable (probed `import shared` and `import "
                 "agent_activities` from %s: %s: %s)"
                 % (ENGINE_SRC, type(e).__name__, str(e)[:200]))


def main():
    if shutil.which("git") is None:
        env_fail("git 可执行缺失（本场景需真 git 子进程驱动 diff/status/merge-base）")
    probe_engine()
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="t26092504-"))
    legs = []

    def check(name, ok, detail=""):
        legs.append(bool(ok))
        print("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                             ("：%s" % detail) if detail else ""))

    try:
        repo, lane = make_lane_fixture(tmp)

        # ---- A 引擎票解禁：只改 app/（非共享面）→ 定点面＝上轮红名 ----
        lane_commit(lane, "app/feature.py")
        files, err = baseline_files(lane, "A")
        check("A1 改动清单恰含实际改动文件且零 error",
              err == "" and files == ["app/feature.py"], "files=%r err=%r" % (files, err))
        got = plan(ENGINE_WRITE_SET, ["sc_red_a", "sc_red_b"], changed=files)
        check("A2 引擎票（写集含 server/engine/）实际只改非共享面 → 定点面=上轮红名",
              got == ["sc_red_a", "sc_red_b"],
              "got=%r（恒空=写集前缀旧病灶复燃）" % (got,))

        # ---- B 共享面（场景执行器）命中 → 全量 ----
        lane_commit(lane, "integration/run_scenarios.py")
        files, err = baseline_files(lane, "B")
        got = plan(ENGINE_WRITE_SET, ["sc_red_a"], changed=files)
        check("B 改动含场景执行器 run_scenarios.py → 恒全量（安全轨①）",
              err == "" and got == [], "files=%r got=%r" % (files, got))

        # ---- C 共享面逐族代表 → 全量 ----
        for rel in ("verify.yaml", "integration/scenario_ledger.py",
                    "server/engine/shared.py", "server/tools/verify_lane.py"):
            _root2, lane2 = make_lane_fixture(tmp)
            lane_commit(lane2, rel)
            files2, err2 = baseline_files(lane2, "C/%s" % rel)
            got2 = plan(ENGINE_WRITE_SET, ["sc_red_c"], changed=files2)
            check("C 改动含共享面 %s → 恒全量" % rel,
                  err2 == "" and got2 == [], "files=%r got=%r" % (files2, got2))

        # ---- D 未提交脏面（diff∪status 并集）----
        _root3, lane3 = make_lane_fixture(tmp)
        lane_commit(lane3, "app/kept.py")
        (lane3 / "app" / "dirty.py").write_text("dirty\n")  # 未跟踪=脏
        files3, err3 = baseline_files(lane3, "D1")
        got3 = plan(ENGINE_WRITE_SET, ["sc_red_d"], changed=files3)
        check("D1 仅脏非共享文件（未提交）→ 仍定点（清单含脏面）",
              err3 == "" and "app/dirty.py" in files3 and got3 == ["sc_red_d"],
              "files=%r got=%r" % (files3, got3))
        (lane3 / "verify.yaml").write_text("dirty-shared\n")  # 脏共享面
        files3b, err3b = baseline_files(lane3, "D2")
        got3b = plan(ENGINE_WRITE_SET, ["sc_red_d"], changed=files3b)
        check("D2 脏共享文件（verify.yaml 未提交）→ 恒全量",
              err3b == "" and got3b == [], "files=%r got=%r" % (files3b, got3b))

        # ---- E fail-closed：merge-base 算不出（构造性缺基线，不走 ENV_FAIL 守卫）----
        root4, lane4 = make_lane_fixture(tmp)
        drop_base_branch(root4)  # 泳道仓锚定的 merge-base(main, 泳道) 无从算起
        lane_commit(lane4, "app/feature.py")
        files4, err4 = changed_files(lane4)
        got4 = plan(ENGINE_WRITE_SET, ["sc_red_e"], changed=files4)
        check("E merge-base 失败 → error 点名基线 + 清单空 → 恒全量（fail-closed）",
              err4 != "" and ("merge-base" in err4 or "baseline" in err4)
              and got4 == [],
              "err=%r got=%r" % (err4[:160], got4))

        # ---- F 未跟踪目录折叠（porcelain ?? dir/ 形态）----
        _root5, lane5 = make_lane_fixture(tmp)
        d = lane5 / "integration" / "tests" / "newstuff"
        d.mkdir(parents=True)
        (d / "x.py").write_text("x\n")
        files5, err5 = baseline_files(lane5, "F1")
        got5 = plan(ENGINE_WRITE_SET, ["sc_red_f"], changed=files5)
        check("F1 未跟踪目录折叠命中共享前缀（integration/tests/）→ 全量",
              err5 == "" and got5 == [], "files=%r got=%r" % (files5, got5))
        _root6, lane6 = make_lane_fixture(tmp)
        d6 = lane6 / "tickets" / "t260925-04"
        d6.mkdir(parents=True)
        (d6 / "note.md").write_text("n\n")
        files6, err6 = baseline_files(lane6, "F2")
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
