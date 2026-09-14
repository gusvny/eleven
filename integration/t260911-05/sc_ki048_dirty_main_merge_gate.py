#!/usr/bin/env python3
"""sc_ki048_dirty_main_merge_gate.py — KI-048 脏 main 合并门全链（t260911-05，灰盒 L2/L3）。

Intent（黑盒用户视角）：合并被 main 工作区未提交改动挡住时——
  A. 合并检查**提前**红灯点名文件（合并前脏检查项），不冒充冲突（conflict=False、
     conflict_files 空），绝不进自动消解回路（验收 a/c）；
  B. merge 回执按原因分类：脏工作区拒绝 = action="dirty" + 协议 reason 码（非空不变
     式）+ 点名文件清单 + 人话文案（git 本地改动保护，非冲突）；真冲突仍 action=
     "conflict"（脏 ≠ 冲突 ≠ 其它，验收 ①）；干净 main 上正常收口 ok=True action=
     "merged"（处置后可放行的对照面，验收 b 的闸侧形态）；
  C. 红线：全部失败路径前后 main 工作区字节不变（文件哈希表逐文件相等）、HEAD 不变
     （无 auto-commit）、stash 条目数不变（无 auto-stash）、porcelain 不变（验收 f，
     260908 auto-stash 事故红线）；
  D. 工作流分流契约（dev_lane 源码结构锁，t260910-03 G 系/t05 同族——dev_lane 全工作
     流行为腿需 docker 台，池内以源码契约锁承接口）：dirty/failed 分流到
     _blocked("merge",…) 且写 blocked_detail{reason_code,files,next_action}（文件来自
     merge 回执——R3 回填回归守卫），conflict 才走 _auto_rework("merge_check")。

分工（防 intent 级重复）：developer L1（server/engine/tests/test_ki048_merge_classify.
py，白盒纯函数六形态电池随实现重写）之下、t260910-03 G7/G7b（保险丝B：清单缺失×成员
仓写集红灯，conflict=False）不同故障面、sc_check_auto_rework_trace（_auto_rework 统一
入口结构锁）不同对象、t260901-16 t05（检查项位次锁）不同面——本场景守「真 git 临时仓
上脏 main × 真实 merge_check/merge activity 接缝」的跨组件行为与红线。实现落地前红属
预期（TDD 信号），arbitrate/merge 期必须绿；temporalio 缺失=行为腿 ENV_FAIL 点名
（exit 2），stdlib 腿（夹具自检+源码契约锁）恒跑。

执行契约（t260910-13 三态）：stdout 末行 SUMMARY pass=N fail=K env_fail=E na=0；
fail>0 → exit 1；env_fail>0 → exit 2。cwd=仓库根，stdlib+temporalio（venv），零端口，
红线：本场景自身对仓库工作区零写入（一切 git 写在 tempfile 临时仓）。
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
POC = REPO / "server" / "engine"

# 红线：先于一切引擎模块 import 钉死 Temporal 地址桩（shared.py 模块级读 env），
# merge_check 的 _fetch_ticket_project 软降级也绝不触生产端口（t260910-03 同款）。
os.environ["SANDBAR_TARGET_HOST"] = "127.0.0.1:9"
os.environ.pop("SANDBAR_NAMESPACE", None)

passed = 0
failed = 0
env_fail_n = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print("ok    " + name)
    else:
        failed += 1
        print("FAIL  " + name + (("：" + detail) if detail else ""))


def env_fail(reason):
    global env_fail_n
    env_fail_n += 1
    print("ENV_FAIL " + reason, flush=True)


def summary():
    print("SUMMARY pass=%d fail=%d env_fail=%d na=0" % (passed, failed, env_fail_n))
    return 1 if failed else (2 if env_fail_n else 0)


def git(*args, cwd):
    p = subprocess.run(["git", "-c", "core.quotepath=false"] + list(args), cwd=str(cwd),
                       capture_output=True, text=True)
    assert p.returncode == 0, "git %s 失败: %s" % (" ".join(args), (p.stderr or "")[-300:])
    return p.stdout


def git_rc(*args, cwd):
    p = subprocess.run(["git", "-c", "core.quotepath=false"] + list(args), cwd=str(cwd),
                       capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


# ---------------------------------------------------------------- 夹具

BASE_TXT = "line=base\nshared=untouched\n"


def _commit_all(repo, msg):
    git("add", "-A", cwd=repo)
    git("commit", "-m", msg, cwd=repo)


def build_fixture(root: Path, lane_touches_new_file: bool = False):
    """main 仓 + lane worktree：lane 领先一改 app/feat.py（可选再加 app/new.py）。

    泳道 worktree 必须落在 <repo>/.lane/<id>——引擎跨项目锚定约定（t260903-10
    _lane_repo_root），其它路径回落 REPO_ROOT 会把脏检查指到引擎仓（本场景首跑实锤）。
    .lane/ 进 .gitignore：泳道 checkout 是无主未跟踪目录，不遮未跟踪相撞形态的判定。
    """
    repo = root / "main-repo"
    repo.mkdir(parents=True)
    git("init", "-b", "main", cwd=repo)
    git("config", "user.email", "sc@example.com", cwd=repo)
    git("config", "user.name", "sc", cwd=repo)
    (repo / "app").mkdir()
    (repo / "app" / "feat.py").write_text(BASE_TXT, encoding="utf-8")
    (repo / ".gitignore").write_text(".lane/\n", encoding="utf-8")
    _commit_all(repo, "base")
    git("checkout", "-b", "lane/t", cwd=repo)
    (repo / "app" / "feat.py").write_text("line=lane\nshared=untouched\n", encoding="utf-8")
    if lane_touches_new_file:
        (repo / "app" / "new.py").write_text("new=1\n", encoding="utf-8")
    _commit_all(repo, "lane change")
    git("checkout", "main", cwd=repo)
    lane_wt = repo / ".lane" / TICKET
    git("worktree", "add", str(lane_wt), "lane/t", cwd=repo)
    return repo, lane_wt


def main_state(repo: Path):
    """红线快照：HEAD / stash 数 / porcelain / 全部工作区文件字节哈希（.git 除外）。"""
    head = git("rev-parse", "HEAD", cwd=repo).strip()
    stash = len(git("stash", "list", cwd=repo).strip().splitlines()) if git(
        "stash", "list", cwd=repo).strip() else 0
    _, por, _ = git_rc("status", "--porcelain", cwd=repo)
    files = {}
    for p in sorted(repo.rglob("*")):
        rel = p.relative_to(repo)
        if ".git" in rel.parts or ".lane" in rel.parts or not p.is_file():
            continue
        files[str(rel)] = hashlib.sha256(p.read_bytes()).hexdigest()
    return {"head": head, "stash": stash, "por": por, "files": files}


def state_diff(label, before, after):
    if before == after:
        return None
    parts = []
    if before["head"] != after["head"]:
        parts.append("HEAD 变动 %s→%s（auto-commit?）" % (before["head"][:8], after["head"][:8]))
    if before["stash"] != after["stash"]:
        parts.append("stash 条目 %d→%d（auto-stash?）" % (before["stash"], after["stash"]))
    if before["por"] != after["por"]:
        parts.append("porcelain 变动")
    drift = {k for k in before["files"] if before["files"][k] != after["files"].get(k)}
    drift |= {k for k in after["files"] if k not in before["files"]}
    if drift:
        parts.append("文件字节漂移：%s" % "、".join(sorted(drift)[:5]))
    return "%s：%s" % (label, "；".join(parts) or "状态字典不等")


# ---------------------------------------------------------------- 场景主体

TICKET = "t26091105s"


def behavior_legs():
    import dataclasses

    sys.path.insert(0, str(POC))
    import shared  # noqa: E402
    import agent_activities as aa  # noqa: E402

    def make_merge_check_args(**kw):
        fields = {f.name for f in dataclasses.fields(shared.MergeCheckArgs)}
        return shared.MergeCheckArgs(**{k: v for k, v in kw.items() if k in fields})

    def run_merge_check(repo, lane_wt):
        return aa.merge_check(make_merge_check_args(
            ticket_id=TICKET, worktree=str(lane_wt), branch="lane/t",
            base_ref="main", write_set=["app/"]))

    def dirty_items(mc):
        return [c for c in (mc.checks or [])
                if "合并前" in str(c.get("item", "")) and "未提交" in str(c.get("item", ""))]

    with tempfile.TemporaryDirectory(prefix="ki048-gate-") as td:
        root = Path(td)
        # lane 含新增文件 app/new.py——验收c 的未跟踪相撞形态需要一个「lane 会写、
        # main 侧有同路径无主未跟踪文件」的收口路径
        repo, lane_wt = build_fixture(root, lane_touches_new_file=True)

        # G0 夹具自检
        check("G0 夹具自检：lane 领先 main 且 main 干净",
              git_rc("rev-parse", "main", cwd=repo)[0] == 0
              and not git("status", "--porcelain", cwd=repo).strip()
              and git("log", "--oneline", "main..lane/t", cwd=repo).strip())

        import asyncio
        mc0 = asyncio.run(run_merge_check(repo, lane_wt))
        base_items = dirty_items(mc0)
        check("G0b 干净基线：脏检查项在场且绿（对照腿，不误伤）",
              len(base_items) == 1 and base_items[0].get("green") is True,
              "items=%r" % (base_items,))

        # G1 验收a：main 未提交 tracked 改动（与收口路径相交）→ 提前红灯点名文件、非冲突类
        # （红线快照拍在造脏之后：宿主自己的未提交改动属现场，引擎不得使其漂移）
        (repo / "app" / "feat.py").write_text("line=host-edit\n", encoding="utf-8")
        st0 = main_state(repo)
        mc1 = asyncio.run(run_merge_check(repo, lane_wt))
        items1 = dirty_items(mc1)
        d1 = str(items1[0].get("detail", "")) if items1 else ""
        check("G1a 脏 main：合并检查整体红灯", mc1.green is False, "green=%r" % (mc1.green,))
        check("G1b 脏检查项红且点名文件+带处置建议（验收a）",
              len(items1) == 1 and items1[0].get("green") is False
              and "app/feat.py" in d1 and ("提交" in d1 or "暂存" in d1),
              "item=%r detail=%r" % (items1, d1[:200]))
        check("G1c 不冒充冲突：conflict=False 且 conflict_files 空（不进自动消解回路）",
              getattr(mc1, "conflict", None) is False and not (getattr(mc1, "conflict_files", None) or []),
              "conflict=%r files=%r" % (getattr(mc1, "conflict", None),
                                        getattr(mc1, "conflict_files", None)))
        check("G1d 红线：merge_check 全程 main 字节不变（验收f）",
              main_state(repo) == st0 or state_diff("G1", st0, main_state(repo)) is None,
              state_diff("G1", st0, main_state(repo)) or "")

        # G2 验收c：未跟踪文件与会并路径相撞 → 点名；移除后该项转绿（验收b 闸侧形态）
        git("checkout", "--", "app/feat.py", cwd=repo)
        (repo / "app" / "new.py").write_text("host-untracked\n", encoding="utf-8")
        mc2 = asyncio.run(run_merge_check(repo, lane_wt))
        items2 = dirty_items(mc2)
        d2 = str(items2[0].get("detail", "")) if items2 else ""
        check("G2a 未跟踪相撞：脏检查项红点名 app/new.py（验收c）",
              len(items2) == 1 and items2[0].get("green") is False and "app/new.py" in d2,
              "detail=%r" % (d2[:200],))
        check("G2b 未跟踪相撞同样非冲突类", getattr(mc2, "conflict", None) is False,
              "conflict=%r" % (getattr(mc2, "conflict", None),))
        (repo / "app" / "new.py").unlink()
        mc3 = asyncio.run(run_merge_check(repo, lane_wt))
        items3 = dirty_items(mc3)
        check("G2c 处置（移除相撞文件）后脏检查项转绿（验收b 闸侧形态）",
              len(items3) == 1 and items3[0].get("green") is True,
              "items=%r" % (items3,))

        # G3 暂存形态：staged 改动 → 红（main_staged 面：任何写前就拦）
        (repo / "app" / "feat.py").write_text("line=staged-edit\n", encoding="utf-8")
        git("add", "app/feat.py", cwd=repo)
        mc4 = asyncio.run(run_merge_check(repo, lane_wt))
        items4 = dirty_items(mc4)
        d4 = str(items4[0].get("detail", "")) if items4 else ""
        check("G3a 暂存改动：脏检查项红点名文件（暂存先于一切写被拦）",
              len(items4) == 1 and items4[0].get("green") is False and "app/feat.py" in d4,
              "detail=%r" % (d4[:200],))
        git("reset", "-q", cwd=repo)
        git("checkout", "--", "app/feat.py", cwd=repo)

        # G4 验收①：merge 回执分类——脏工作区拒绝 = dirty + reason 码 + 点名 + 非冲突
        (repo / "app" / "feat.py").write_text("line=host-edit-2\n", encoding="utf-8")
        st1 = main_state(repo)
        mr1 = aa._squash_merge(repo, lane_wt, "lane/t", TICKET)
        check("G4a merge 回执：ok=False action=dirty（不再冒充 conflict，验收①）",
              mr1.ok is False and mr1.action == "dirty",
              "action=%r ok=%r" % (mr1.action, mr1.ok))
        check("G4b reason 协议码非空且在词表（main_dirty，非空不变式）",
              getattr(mr1, "reason", "") == "main_dirty",
              "reason=%r" % (getattr(mr1, "reason", ""),))
        check("G4c 点名文件清单含挡事文件",
              "app/feat.py" in (getattr(mr1, "files", None) or []),
              "files=%r" % (getattr(mr1, "files", None),))
        check("G4d 人话文案：说明 git 本地保护非冲突",
              "非冲突" in (mr1.error or ""),
              "error=%r" % ((mr1.error or "")[:160],))
        check("G4e 红线：merge 拒绝路径 main 字节不变+HEAD 不变+无 stash（验收f）",
              main_state(repo) == st1, state_diff("G4", st1, main_state(repo)) or "")
        git("checkout", "--", "app/feat.py", cwd=repo)

        # G5 验收①对照：真冲突（main 已提交的相撞改动，工作区干净）仍 action=conflict
        (repo / "app" / "feat.py").write_text("line=main-side\n", encoding="utf-8")
        _commit_all(repo, "main conflicting edit")
        st2 = main_state(repo)
        mr2 = aa._squash_merge(repo, lane_wt, "lane/t", TICKET)
        check("G5a 真冲突维持 action=conflict（脏≠冲突，两类不互吞）",
              mr2.ok is False and mr2.action == "conflict",
              "action=%r ok=%r error=%r" % (mr2.action, mr2.ok, (mr2.error or "")[:120]))
        _, lsu, _ = git_rc("ls-files", "-u", cwd=repo)
        check("G5b 冲突现场清理收敛（ls-files -u 空，保险丝 d 幂等承诺在兑现）",
              not lsu.strip(), "ls-files -u=%r" % (lsu[:120],))
        check("G5c 红线：冲突失败路径不 auto-commit（HEAD 不变）",
              main_state(repo)["head"] == st2["head"]
              and main_state(repo)["stash"] == st2["stash"],
              state_diff("G5", st2, main_state(repo)) or "")

        # G6 验收b对照：干净 main 上同一 lane 正常收口（处置后可放行的回执面）
        repo2, lane_wt2 = build_fixture(root / "clean", lane_touches_new_file=True)
        mr3 = aa._squash_merge(repo2, lane_wt2, "lane/t", TICKET)
        check("G6 干净 main：收口 ok=True action=merged（处置后放行的对照面，验收b）",
              mr3.ok is True and mr3.action == "merged" and bool(mr3.merge_commit),
              "action=%r ok=%r commit=%r" % (mr3.action, mr3.ok, mr3.merge_commit[:10]))


def source_lock_legs():
    """dev_lane 源码契约锁（stdlib 恒跑）：工作流分流面在 docker 台之外的可守部分。"""
    src = (REPO / "server" / "engine" / "dev_lane.py").read_text("utf-8")
    pos_blocked = src.find('self._blocked("merge"')
    pos_rework = src.find('_auto_rework("merge_check"')
    check("L1 分流锁：dirty/failed → _blocked(\"merge\") 在位且先于 conflict 自动打回分支",
          pos_blocked != -1 and pos_rework != -1 and pos_blocked < pos_rework,
          "blocked@%d rework@%d" % (pos_blocked, pos_rework))
    check("L2 分类分流在位：merge 失败分支按 action 分出 dirty/failed（不再无差别打回）",
          'mr.action in ("dirty", "failed")' in src,
          "未找到 dirty/failed 分流条件")
    check("L3 blocked_detail 结构三键在位（reason_code/files/next_action——UI 状态卡消费契约）",
          all(k in src for k in ('"reason_code"', '"files"', '"next_action"')),
          "blocked_detail 键缺失")
    check("L4 R3 回填锁：dict 态回执重建回填 reason/files（票面点名不半路丢失）",
          'raw.get("reason")' in src and 'raw.get("files")' in src,
          "回执重建未回填新字段")
    check("L5 conflict 唯一自动打回：_auto_rework(\"merge_check\") 恰 1 处（只吃真冲突）",
          src.count('_auto_rework("merge_check"') == 1,
          "count=%d" % src.count('_auto_rework("merge_check"'))


def main():
    source_lock_legs()
    try:
        import temporalio  # noqa: F401
        has_temp = True
    except Exception:
        has_temp = False
    if has_temp:
        try:
            behavior_legs()
        except Exception as e:
            check("行为腿整体（异常即红不崩场）", False,
                  "%s: %s" % (type(e).__name__, str(e)[:200]))
    else:
        env_fail("temporalio 不可导入——merge_check/_squash_merge 行为腿 ENV_FAIL 点名"
                 "（KI-036 同族依赖面）；stdlib 夹具/源码锁腿已照跑")
    sys.exit(summary())


if __name__ == "__main__":
    main()
