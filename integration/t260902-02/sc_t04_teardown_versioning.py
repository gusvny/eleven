# -*- coding: utf-8 -*-
"""t260902-02 t04 —— 收口三段化与 defer_teardown 版本化契约。

用户故事（升级安全）：本单把「merge 落账+顺手拆泳道」改为「merge → 归档 → 拆泳道」。
部署新代码时，存量停在 merge 人审门的工单用的是**旧输入**（没有 defer_teardown
字段）——签字后必须走旧的「内联拆泳道」语义正常收口，绝不能因升级留下没人拆的
僵尸泳道；新票走 defer=True，归档完成才由 teardown_lane 拆，且 teardown 幂等。

黑盒手法：tmp git 仓库 + worktree 直调 _squash_merge / teardown_lane，
断言全部落在 git/文件系统状态上。零 Temporal 依赖（defer=None 模拟旧 payload）。

跑法：python3 integration/t260902-02/t04_teardown_versioning.py（cwd=泳道根）
"""
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import fixture as fx  # noqa: E402

L = fx.Ledger()


def git(repo, *args):
    p = subprocess.run(["git", "-C", str(repo)] + list(args),
                       capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        raise RuntimeError("git %s 失败：%s" % (" ".join(args), p.stderr.strip()[:200]))
    return p.stdout


def make_repo_with_lane(base, name):
    repo = base / (name + "-repo")
    lane = base / (name + "-lane")
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True, timeout=60)
    git(repo, "config", "user.email", "integ@suyou.test")
    git(repo, "config", "user.name", "integ")
    git(repo, "checkout", "-q", "-b", "main")
    (repo / "f.txt").write_text("base\n", "utf-8")
    git(repo, "add", "f.txt")
    git(repo, "commit", "-q", "-m", "base")
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", str(lane), "-b", "lane/t-integ"],
                   check=True, timeout=60)
    (lane / "f.txt").write_text("base\nlane change\n", "utf-8")
    git(lane, "config", "user.email", "integ@suyou.test")
    git(lane, "config", "user.name", "integ")
    git(lane, "add", "f.txt")
    git(lane, "commit", "-q", "-m", "lane change")
    return repo, lane


def branches(repo):
    return [b.strip() for b in git(repo, "branch", "--format=%(refname:short)").splitlines()]


def main():
    if not shutil.which("git"):
        L.skip1("全部用例", "git 不可用")
        return L.finish()
    aa = fx.load_module("agent_activities")
    if not hasattr(aa, "_squash_merge"):
        L.ok(False, "_squash_merge 存在")
        return L.finish()

    with fx.Sandbox() as sb:
        # —— 旧语义（defer 缺省/None，模拟存量工单旧输入）：收口后内联拆泳道 ——
        repo, lane = make_repo_with_lane(sb.tmp, "old")
        res = fx.invoke_squash_merge(aa, repo, lane, "lane/t-integ", "t-integ-old", defer=None)
        L.ok(getattr(res, "ok", False) is True, "旧输入收口成功（ok=True）")
        L.ok(not (lane / "f.txt").exists(), "旧语义：worktree 已拆（升级后存量票照常清理）")
        L.ok("lane/t-integ" not in branches(repo), "旧语义：分支已删")
        head_msg = git(repo, "log", "-1", "--format=%B")
        L.ok("t-integ-old" in head_msg, "收口提交点名工单 id（%s）" % head_msg.strip().splitlines()[0])
        L.ok("lane change" in (repo / "f.txt").read_text("utf-8"), "泳道改动落进 main")

        # —— 新语义（defer=True）：merge 只落账不拆，归档窗口泳道仍在 ——
        repo2, lane2 = make_repo_with_lane(sb.tmp, "new")
        res2 = fx.invoke_squash_merge(aa, repo2, lane2, "lane/t-integ", "t-integ-new", defer=True)
        L.ok(getattr(res2, "ok", False) is True, "defer=True 收口成功（落账不拆）")
        L.ok((lane2 / "f.txt").is_file(), "defer=True：归档窗口内泳道原样保留（报告可扫）")
        L.ok("lane/t-integ" in branches(repo2), "defer=True：分支保留待 teardown")

        # —— teardown_lane：回执契约（warn 不抛、点名环节、幂等）——
        # 覆盖诚实声明：teardown_lane 与 merge activity 同款硬绑 REPO_ROOT（单仓架构
        # 一致假设），tmp 仓库隔离测不了「真拆」真身；此处用不存在路径验回执语义
        # （零副作用：worktree remove/branch -D 对不存在目标在真仓里全是 no-op 报错），
        # 真拆路径由 dev-lane 全链 e2e（真测试环境整机跑票）覆盖。
        if not hasattr(aa, "teardown_lane") and not hasattr(aa, "_teardown_lane"):
            L.ok(False, "teardown_lane 存在（方案 Step 3 契约）")
        else:
            ghost = sb.tmp / "ghost-lane"
            t1 = fx.invoke_teardown(aa, repo2, ghost, "lane/does-not-exist", "t-integ-new")
            L.ok(getattr(t1, "ok", False) is True, "teardown_lane 拆失败不抛（回执 ok=true，warn 制）")
            # 260928 修（本断言在 main 上长红的真因）：260924 宿主直修令把「重拆已拆泳道」的
            # 两形态（git rc=128 的 not-a-working-tree / branch-not-found）定为**目标态已达成**
            # ——静默通过、**不谎报警**（teardown_lane docstring「这两形态是『目标态已达成』不是
            # 失败，静默通过不谎报警；真失败才点名」）。本用例的 ghost 输入（不存在路径+不存在
            # 分支）恰是该形态 ⇒ 回执 error 为空是新契约的**正确行为**，旧断言「error 必须点名
            # worktree 环节」对这条输入已失效（它测的是旧语义下的另一分支）。
            # 改法保住原意图（不静默、真失败必点名）而不放松：①这条输入断言「静默但不谎报」
            # （ok=True + action=teardown + error 空）；②「真失败必点名环节」改为**源码级回归锁**
            # （本仓单仓架构下夹具造不出真 git 清理失败——见上方覆盖诚实声明，真拆路径归
            # dev-lane 全链 e2e）。
            L.ok((getattr(t1, "error", "") or "") == ""
                 and getattr(t1, "action", "") == "teardown",
                 "已达成形态静默通过且不谎报（ok=True/action=teardown/error 空）：%r"
                 % (getattr(t1, "error", "") or "")[:120])
            _aa_src = (fx.REPO / "server" / "engine" / "agent_activities.py").read_text(encoding="utf-8")
            L.ok("worktree remove 失败" in _aa_src and "目录壳残留" in _aa_src
                 and "仓目录不存在" in _aa_src,
                 "真失败路径仍逐仓点名环节（源码级锁：worktree remove 失败 / 目录壳残留 / 仓目录不存在）")
            err = ""
            try:
                t2 = fx.invoke_teardown(aa, repo2, ghost, "lane/does-not-exist", "t-integ-new")
            except Exception as e:
                err = str(e)
            L.ok(not err, "teardown_lane 幂等重跑不抛错（Temporal 重试安全）")

    return L.finish()


def _guarded():
    try:
        return main()
    except Exception as e:
        L.ok(False, "异常逃逸：%s: %s" % (type(e).__name__, str(e)[:300]))
        return L.finish()


if __name__ == "__main__":
    sys.exit(_guarded())
