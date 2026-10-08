#!/usr/bin/env python3
"""t260921-09 多仓 merge_check 三态判据回归场景（灰盒 L2，ro 隔离临时多仓项目）。

工单：多仓票某仓「声明了但零改动」不得判红（对齐机械复核整票级口径）——实证
nusuyou t260920-04（4 仓 macOS 收口票唯一红灯=[service] 泳道分支有 commit:
0 个 commit，独立复核零改动为真、非假红）。

用户可感知契约（本场景守跨组件持久面；纯函数矩阵/真 git 四态白盒归
server/engine/tests/test_t260921_09_lane_commit_verdict.py，两层分工）：
  第 0 条 粒度锁：多目录写集经 shared.build_repo_worktrees 最长前缀归属合并为
          仓级清单，绝不逐条目化（目录级空承诺本就安全，仓级空承诺才致命）；
  ① 多仓×某仓零改动×零 diff（提交面+未提交面均无差异）→ 推进不红，且回执点名
    可见（绿项带 reason_code=no_changes_no_diff——新形状，不静默）；
  ② 多仓×某仓零 commit×有 diff → 仍红（这才是「实现未落盘」），文案/出路与①
    严格分叉（未提交面→settle 排查+越写集互指「工作区干净」项；仅提交面→位点异常）；
  ③ 整票零 commit（排除 no_file_changes 票）→ 全局红点名各仓（宿主裁定②保住
    「什么都没提交却全绿」的原防伪需求），rehearsal 保持 checks[-1]（冲突分类
    契约：全局红恒非冲突类，blocked 交人，绝不进自动消解回路）；
  豁免 no_file_changes → 全局闸放行（与 review gate 同一豁免口径）；
  C1 查询失败哨兵 -1：全局闸遇 -1 不得产出「整票零 commit」文案（该红由逐仓
    commit_query_failed fail-closed 承担，报错必须与事实同向）。

跑法：PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; "$PY" -B
integration/t260921-09/sc_multirepo_zero_commit_gate.py（temporalio 缺席=ENV_FAIL）。
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

passes = []
fails = []


def check(name, cond, note=""):
    if cond:
        passes.append(name)
        print("PASS :: %s" % name, flush=True)
    else:
        fails.append("%s%s" % (name, ("：%s" % note) if note else ""))
        print("FAIL :: %s%s" % (name, ("：%s" % note) if note else ""), flush=True)


def load_engine():
    """引擎模块装载（真判定项+真聚合闸需 temporalio 可导入——KI-036 口径：缺环境
    点名 ENV_FAIL exit 2，环境红非产品红；跑法见文件头/注册 cmd 的 venv 回退）。"""
    if shutil.which("git") is None:
        print("ENV_FAIL: git 不可用（临时多仓项目无法构建）")
        sys.exit(2)
    try:
        import temporalio  # noqa: F401
    except Exception:
        print("ENV_FAIL: temporalio 不可导入——用 server/engine/.venv/bin/python 跑"
              "（KI-036 口径：缺环境点名，环境红非产品红）")
        sys.exit(2)
    sys.path.insert(0, str(REPO / "server" / "engine"))
    import shared
    import agent_activities
    return shared, agent_activities


def git(*args, cwd):
    p = subprocess.run(["git"] + list(args), cwd=str(cwd),
                       capture_output=True, text=True)
    assert p.returncode == 0, "git %s 失败: %s" % (" ".join(args), p.stderr)
    return p.stdout.strip()


def init_repo(path, branch="main"):
    path.mkdir(parents=True, exist_ok=True)
    git("init", "-b", branch, cwd=path)
    git("config", "user.email", "ut@example.com", cwd=path)
    git("config", "user.name", "ut", cwd=path)
    (path / "f.txt").write_text("base\n", encoding="utf-8")
    git("add", "-A", cwd=path)
    git("commit", "-qm", "base", cwd=path)
    return path


def main():
    shared, aa = load_engine()
    tmp = Path(tempfile.mkdtemp(prefix="sc-t260921-09-"))
    try:
        # ---- 第 0 条 粒度锁：多目录写集 → 最长前缀归属合并为仓级清单 ----
        proj = tmp / "proj"
        init_repo(proj / "r1")
        init_repo(proj / "r2")
        entries = shared.build_repo_worktrees(
            str(proj), ["r1/a/", "r1/b/", "r2/c/"], "tkt")
        check("粒度锁-归属合并为仓级清单",
              len(entries) == 2
              and {e["repo"] for e in entries} == {"r1", "r2"}
              and all(e["branch"].startswith("lane/tkt-") for e in entries),
              "entries=%r" % (entries,))
        # 同仓多目录落同一仓（绝不逐条目产出判定）
        owners = shared.resolve_repos_for_paths(str(proj), ["r1/a/", "r1/b/", "r1/c.txt"])
        check("粒度锁-同仓多目录单条归属",
              list(owners.keys()) == [str((proj / "r1").resolve())]
              and len(owners[str((proj / "r1").resolve())]) == 3)

        # ---- ① 多仓×某仓零改动×零 diff → 不红且点名（真 git 判定项） ----
        git("checkout", "-qb", "lane/x", cwd=proj / "r1")  # r1 同点建支=确实零改动
        item1, n1 = aa._lane_commits_check_item("main", "lane/x", proj / "r1", proj / "r1")
        git("checkout", "-qb", "lane/x", cwd=proj / "r2")
        (proj / "r2" / "f.txt").write_text("work\n", encoding="utf-8")
        git("commit", "-aqm", "r2 work", cwd=proj / "r2")  # r2 有真改动
        item2, n2 = aa._lane_commits_check_item("main", "lane/x", proj / "r2", proj / "r2")
        check("①-零改动仓不红且点名",
              item1["green"] is True and n1 == 0
              and item1.get("reason_code") == "no_changes_no_diff"
              and "zero-change confirmed" in item1["item"] and "no changes genuinely needed" in item1["detail"],
              json.dumps(item1, ensure_ascii=False)[:200])
        check("①-有改动仓仍绿（旧路径零回归）",
              item2["green"] is True and n2 == 1 and "reason_code" not in item2,
              json.dumps(item2, ensure_ascii=False)[:200])
        check("①-全局闸不触发（有仓 commit）",
              shared.multirepo_zero_commit_error({"r1": n1, "r2": n2}, False) == "")

        # ---- ② 零 commit×有 diff → 仍红，文案与①分叉（真 git） ----
        git("checkout", "-qb", "lane/y", cwd=proj / "r1")
        (proj / "r1" / "dirty.txt").write_text("late\n", encoding="utf-8")
        item3, n3 = aa._lane_commits_check_item("main", "lane/y", proj / "r1", proj / "r1")
        check("②-未提交面红=实现未落盘（C3 互指）",
              item3["green"] is False and n3 == 0
              and item3.get("reason_code") == "no_commits"
              and "实现未落盘" in item3.get("next_action", "")
              and "收回写集内" in item3.get("next_action", ""),
              json.dumps(item3, ensure_ascii=False)[:240])
        # 仅提交面差异（位点异常）用独立干净仓，避免残留脏文件混入未提交面
        init_repo(proj / "r3")
        git("checkout", "-qb", "lane/y", cwd=proj / "r3")
        git("checkout", "-q", "main", cwd=proj / "r3")
        (proj / "r3" / "f.txt").write_text("main ahead\n", encoding="utf-8")
        git("commit", "-aqm", "main ahead", cwd=proj / "r3")  # main 前进，lane/y 停旧点
        item4, n4 = aa._lane_commits_check_item("main", "lane/y", proj / "r3", proj / "r3")
        check("②-仅提交面红=位点异常（文案分叉）",
              item4["green"] is False and n4 == 0
              and item4.get("reason_code") == "no_commits"
              and "position abnormal" in item4.get("next_action", "")
              and "树与 base 有差异" in item4.get("detail", ""),
              json.dumps(item4, ensure_ascii=False)[:240])

        # ---- ③ 整票零 commit 全局闸 + 豁免 + C1（真聚合层，verify_lane 桩承载） ----
        orig = aa._merge_check_one_scope

        async def stub_zero(args, sc, lane_root, multi):
            return {"checks": [{"item": "泳道分支有 commit——零改动确认", "green": True,
                                "detail": "0 个 commit 且两差异面均无差异",
                                "id": "lane_commits", "reason_code": "no_changes_no_diff"},
                               {"item": aa.MERGE_REHEARSAL_ITEM, "green": True,
                                "detail": "无冲突", "id": "merge_rehearsal"}],
                    "rehearsal_green": True, "conflict_files": [],
                    "merge_tree_excerpt": "", "lane_commits": 0}

        async def stub_query_failed(args, sc, lane_root, multi):
            return {"checks": [{"item": "泳道分支有 commit", "green": False,
                                "detail": "git log 失败", "id": "lane_commits",
                                "reason_code": "commit_query_failed"},
                               {"item": aa.MERGE_REHEARSAL_ITEM, "green": True,
                                "detail": "无冲突", "id": "merge_rehearsal"}],
                    "rehearsal_green": True, "conflict_files": [],
                    "merge_tree_excerpt": "", "lane_commits": -1}

        lane = tmp / "proj" / ".lane" / "tkt"
        lane.mkdir(parents=True, exist_ok=True)
        # t261008-24：清单首仓分支必须真可解析（merge_check 的 _gr_sha 在 scopes[0]
        # 的 repo 上 rev-parse）——真 git 仓落 r1/r2，绿跑面才有真 sha 可锚。
        proj = tmp / "proj"
        face_sha = ""
        for rn, br in (("r1", "lane/tkt-r1"), ("r2", "lane/tkt-r2")):
            rp = proj / rn
            rp.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "-C", str(rp), "init", "-q", "-b", "main"],
                           check=True, capture_output=True)
            subprocess.run(["git", "-C", str(rp), "config", "user.name", "fx"],
                           check=True, capture_output=True)
            subprocess.run(["git", "-C", str(rp), "config", "user.email", "fx@e.c"],
                           check=True, capture_output=True)
            (rp / "f.txt").write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(rp), "add", "-A"], check=True,
                           capture_output=True)
            subprocess.run(["git", "-C", str(rp), "commit", "-qm", "base"],
                           check=True, capture_output=True)
            subprocess.run(["git", "-C", str(rp), "branch", br], check=True,
                           capture_output=True)
        _p = subprocess.run(["git", "-C", str(proj / "r1"), "rev-parse",
                             "--verify", "lane/tkt-r1"],
                            capture_output=True, text=True)
        face_sha = (_p.stdout or "").strip()
        mf = shared.multi_manifest_path(lane)
        mf.parent.mkdir(parents=True, exist_ok=True)
        mf.write_text(json.dumps([{"repo": "r1", "name": "r1", "branch": "lane/tkt-r1"},
                                  {"repo": "r2", "name": "r2", "branch": "lane/tkt-r2"}]),
                      encoding="utf-8")

        import asyncio

        from shared import MergeCheckArgs  # noqa: E402  （load_engine 已插 sys.path）

        def run_mc(stub, no_file_changes=False, green_run=True):
            # write_set 置空（no_file_changes 票的真形态）：聚合桩面专测全局闸与豁免，
            # 保险丝B 的物化判定归 test_t260910_03_fuses 白盒分工，不在本场景重复
            aa._merge_check_one_scope = stub
            try:
                kwargs = dict(
                    ticket_id="tkt", worktree=str(lane), branch="lane/tkt",
                    base_ref="basesha", write_set=[],
                    no_file_changes=no_file_changes)
                # t261008-24/KI-217 出口①：绿跑面（首仓分支真 HEAD、ran=1）——
                # 无面=新检查项恒红 zero_run（永不默认绿），本票 intent 被无关红污染。
                if green_run:
                    kwargs["last_green_run"] = {"sha": face_sha, "ran": 1}
                return asyncio.run(aa.merge_check(MergeCheckArgs(**kwargs)))
            finally:
                aa._merge_check_one_scope = orig

        res3 = run_mc(stub_zero)
        gates = [c for c in res3.checks if c.get("id") == "all_repos_zero_commits"]
        check("③-整票零commit全局红点名各仓",
              res3.green is False and res3.conflict is False and len(gates) == 1
              and "r1" in gates[0]["detail"] and "r2" in gates[0]["detail"]
              and "allow_empty_write_set" in gates[0]["next_action"],
              json.dumps(res3.checks, ensure_ascii=False)[:400])
        # t261008-24：绿跑前置项（若有）插在 rehearsal 之前（KI-047 位次契约延申面）。
        # gen10 起该项只对带写集的票签发（空写集票不签发=收窄到有验收面形态）——本子用例
        # write_set=[] 走聚合桩，两种合法槽序都要钉：有项= rehearsal < scenario_green_run
        # < all_repos；无项= rehearsal < all_repos。方向只收紧（rehearsal 恒最后）。
        _gr = [c for c in res3.checks if c.get("id") == "scenario_green_run"]
        _slot_ok = (
            res3.checks[-1]["id"] == "merge_rehearsal"
            and ((_gr and res3.checks[-2]["id"] == "scenario_green_run"
                  and res3.checks[-3]["id"] == "all_repos_zero_commits")
                 or (not _gr and res3.checks[-2]["id"] == "all_repos_zero_commits")))
        check("③-位次契约 rehearsal 保持最后（绿跑项在场=其槽紧邻 rehearsal 前；"
              "被写集闸收窄不签发=全局闸紧邻）", _slot_ok)
        res4 = run_mc(stub_zero, no_file_changes=True)
        check("③-豁免 no_file_changes 放行（与 review gate 同口径）",
              res4.green is True
              and not [c for c in res4.checks if c.get("id") == "all_repos_zero_commits"])
        res5 = run_mc(stub_query_failed)
        check("C1-含查询失败仓全局闸不出「零commit」文案",
              not [c for c in res5.checks if c.get("id") == "all_repos_zero_commits"]
              and res5.green is False
              and any(c.get("reason_code") == "commit_query_failed" for c in res5.checks))

        # ---- C1/畸形：纯函数面兜底 ----
        check("C1-哨兵语义纯函数面",
              shared.multirepo_zero_commit_error({"a": -1}, False) == ""
              and shared.multirepo_zero_commit_error({"a": 0, "b": -1}, False) == ""
              and shared.lane_commit_verdict(-1, 0, 0) == (False, "commit_query_failed")
              and shared.lane_commit_verdict(None, 0, 0) == (False, "commit_query_failed")
              and shared.lane_commit_verdict(0, None, 0) == (False, "commit_query_failed"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("SUMMARY pass=%d fail=%d env_fail=0 na=0" % (len(passes), len(fails)),
          flush=True)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
