#!/usr/bin/env python3
"""t260921-09 场景二：多仓票 merge_check **真聚合链**回执契约（灰盒 L3，ro）。

intent（验证什么）——与兄弟场景 sc_multirepo_zero_commit_gate.py 的分工：
  彼条（L2）直调判定项 + 桩聚合，守判定口径与纯函数哨兵；本条走**不打桩的真聚合**
  （真 worktree + 真清单 + 真 KI-009 自愈前置 + 真逐仓名前缀 + 真保险丝B 共存），
  守「拼起来通不通」的组合面，任何一层各自对了拼错仍然会红：
    ① 真回执点名可见：某仓零改动 → amber（green=True + reason_code=no_changes_no_diff）
       落真回执且带 [仓名] 前缀（前缀在聚合层加，桩测守不到）；
    ① 真链整票推进：amber 不拖垮整票（green=True），保险丝B 绿项共存、rehearsal
       恒 checks[-1]（KI-047 位次契约在真项序下成立）；
    ② 真自愈交互：写集外脏文件**不自愈**（KI-009 既有语义）→ 未提交面差异在真链
       存活为红（reason_code=no_commits「实现未落盘」+互指「工作区干净」），且其他仓
       不被拖红（红项可见性：票面读得出「哪个仓坏了」）；
    ② 分支位点异常在真链分叉（泳道分支落后 base：0 commit 但树≠base →「位点异常」）；
    查询失败（清单 base_ref 坏引用）→ 真链 fail-closed 红（commit_query_failed），
       不断言「未落盘」、不触发「整票零 commit」全局文案（C1 哨兵纪律）。

三态契约：exit 0=全过；1=有 FAIL（产品红）；2=ENV_FAIL（git/引擎 venv 缺失）。
verify_lane 语义非本票对象：夹具仓 main 预提交最小 verify 工具替身（恒绿 JSON），
替身在 base 提交里——零泳道提交、零未提交面，只稳定前提。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lib_lane_fixture as FX  # noqa: E402


def lane_commits_items(res):
    return [c for c in res.checks if c.get("id") == "lane_commits"]


def by_repo(res, tag):
    return next((c for c in lane_commits_items(res) if "[%s]" % tag in str(c.get("item"))), None)


def item_text(item):
    return "".join(str(item.get(k, "")) for k in ("item", "detail", "next_action")) if item else ""


def main():
    FX.ensure_engine_runtime()  # 缺 temporalio → re-exec 引擎 venv；venv 缺席 → exit 2
    shared, aa = FX.load_engine()
    L = FX.Legs("multirepo-zero-commit-receipt")
    projs = []
    try:
        # ---- 形态 A：repo_a 泳道有提交、repo_b 全程零改动 → 真链整票推进 ----
        pa = FX.TempProject()
        projs.append(pa)
        ra = pa.init_repo("repo_a", {"src/a.py": "base\n"})
        pa.second_commit(ra, "src/keep.txt", "k\n")
        pa.init_repo("repo_b", {"lib/b.py": "base\n"})
        lane_a = pa.build_lane(
            "t26092109r1",
            {"repo_a": {"commit": ("src/a.py", "work\n")}, "repo_b": {}},
            write_set=["repo_a/src/a.py", "repo_b/lib/b.py"])
        res_a = pa.merge_check(aa, "t26092109r1", lane_a)

        L.check("① 真链整票推进不红（green=True）且非冲突类",
                res_a.green is True and res_a.conflict is False,
                json.dumps([c for c in res_a.checks if not c.get("green")], ensure_ascii=False)[:300])
        L.check("第0条 真链仓粒度：lane_commits 项恰=仓数（2），无逐条目拆分",
                len(lane_commits_items(res_a)) == 2)
        rb = by_repo(res_a, "repo_b")
        L.check("① 零改动仓 amber 落真回执且带 [repo_b] 前缀（聚合层点名，不静默）",
                rb is not None and rb.get("green") is True
                and rb.get("reason_code") == "no_changes_no_diff"
                and str(rb.get("item", "")).startswith("[repo_b]"),
                json.dumps(rb, ensure_ascii=False)[:200] if rb else "repo_b 项缺失")
        L.check("① amber 文案给「确实无需改动」定性（与「实现未落盘」互斥）",
                rb is not None and "zero-change confirmed" in item_text(rb))
        ra_i = by_repo(res_a, "repo_a")
        L.check("① 有改动仓照旧绿（detail 带 commit 计数，旧路径零回归）",
                ra_i is not None and ra_i.get("green") is True
                and "1 commit(s)" in str(ra_i.get("detail", "")))
        fuse = [c for c in res_a.checks if c.get("id") == "fuse_b_materialize"]
        L.check("① 多仓物化闸绿项共存（全绿也不静默的既有契约）",
                len(fuse) == 1 and fuse[0].get("green") is True)
        L.check("① 位次契约：rehearsal 恒 checks[-1]、amber/物化项均在 checks[:-1]",
                aa.MERGE_REHEARSAL_ITEM in str(res_a.checks[-1].get("item", ""))
                and all(res_a.checks.index(c) < len(res_a.checks) - 1
                        for c in [rb, ra_i, fuse[0]] if c is not None))
        L.check("① 有仓 commit → 全局闸不触发",
                not any(c.get("id") == "all_repos_zero_commits" for c in res_a.checks))

        # ---- 形态 B：repo_b 写集外脏文件（不自愈）→ 真链红且不拖垮他仓可见性 ----
        pb = FX.TempProject()
        projs.append(pb)
        pb.init_repo("repo_a", {"src/a.py": "base\n"})
        pb.init_repo("repo_b", {"lib/b.py": "base\n"})
        lane_b = pb.build_lane(
            "t26092109r2",
            {"repo_a": {"commit": ("src/a.py", "work\n")}, "repo_b": {"out_dirty": "scratch.md"}},
            write_set=["repo_a/src/a.py", "repo_b/lib/b.py"])
        res_b = pb.merge_check(aa, "t26092109b", lane_b)
        rb_b = by_repo(res_b, "repo_b")
        txt_b = item_text(rb_b)
        L.check("② 写集外脏文件不自愈：未提交面差异真链存活为红（no_commits）",
                rb_b is not None and rb_b.get("green") is False
                and rb_b.get("reason_code") == "no_commits",
                json.dumps(rb_b, ensure_ascii=False)[:240] if rb_b else "repo_b 项缺失")
        L.check("② 文案=「实现未落盘」+互指「工作区干净」项（越界脏文件出路可达）",
                "未落盘" in txt_b and "工作区干净" in txt_b)
        ra_b = by_repo(res_b, "repo_a")
        L.check("② 红项不拖垮他仓：repo_a 项仍绿（票面读得出哪个仓坏了）",
                ra_b is not None and ra_b.get("green") is True)
        dirty = [c for c in res_b.checks if c.get("id") == "worktree_clean" and not c.get("green")]
        L.check("② 越写集改动既有职责不动：worktree_clean 红在场（验收④）",
                len(dirty) == 1 and dirty[0].get("reason_code") == "worktree_dirty")
        L.check("② 整票红、非冲突类（blocked 交人不进自动消解回路）",
                res_b.green is False and res_b.conflict is False)

        # ---- 形态 C：repo_b 泳道分支落后 base（0 commit 但树≠base）→ 位点异常分叉 ----
        pc = FX.TempProject()
        projs.append(pc)
        rc = pc.init_repo("repo_a", {"src/a.py": "base\n"})
        pc.second_commit(rc, "src/keep.txt", "k\n")
        pc.init_repo("repo_b", {"lib/b.py": "base\n"})
        pc.second_commit(pc.root / "repo_b", "lib/keep.txt", "k\n")
        lane_c = pc.build_lane(
            "t26092109r3",
            {"repo_a": {"commit": ("src/a.py", "work\n")}, "repo_b": {"behind": True}},
            write_set=["repo_a/src/a.py", "repo_b/lib/b.py"])
        res_c = pc.merge_check(aa, "t26092109r3", lane_c)
        rb_c = by_repo(res_c, "repo_b")
        txt_c = item_text(rb_c)
        L.check("② 分支位点异常真链分叉（红 no_commits + 「位点异常」文案）",
                rb_c is not None and rb_c.get("green") is False
                and rb_c.get("reason_code") == "no_commits" and "position abnormal" in txt_c,
                json.dumps(rb_c, ensure_ascii=False)[:1200] if rb_c else "repo_b 项缺失")
        L.check("② 位点异常形态整票红", res_c.green is False and res_c.conflict is False)

        # ---- 形态 D：清单 base_ref 坏引用 → 查询失败 fail-closed，报错与事实同向 ----
        pd = FX.TempProject()
        projs.append(pd)
        pd.init_repo("repo_a", {"src/a.py": "base\n"})
        pd.init_repo("repo_b", {"lib/b.py": "base\n"})
        lane_d = pd.build_lane(
            "t26092109r4",
            {"repo_a": {"commit": ("src/a.py", "work\n")}, "repo_b": {"base_ref": FX.BAD_REF}},
            write_set=["repo_a/src/a.py", "repo_b/lib/b.py"])
        res_d = pd.merge_check(aa, "t26092109r4", lane_d)
        rb_d = by_repo(res_d, "repo_b")
        txt_d = item_text(rb_d)
        L.check("④查询失败 fail-closed 红（commit_query_failed）",
                rb_d is not None and rb_d.get("green") is False
                and rb_d.get("reason_code") == "commit_query_failed",
                json.dumps(rb_d, ensure_ascii=False)[:1200] if rb_d else "repo_b 项缺失")
        L.check("④查询失败报错与事实同向：点名真实原因（查询失败）、无「实现未落盘（…」断言形态",
                rb_d is not None and "fatal:" in txt_d
                and "implementation not persisted" not in txt_d,
                json.dumps(rb_d, ensure_ascii=False)[:1200] if rb_d else "repo_b 项缺失")
        L.check("④查询失败仓不触发「整票零 commit」全局文案（-1 不可当 0 计，C1）",
                not any(c.get("id") == "all_repos_zero_commits" for c in res_d.checks))
        L.check("④ 整票红方向保持（fail-closed 不假绿）",
                res_d.green is False and res_d.conflict is False)

        # ---- ⑥ 真链 reason_code 族互斥可机读 ----
        codes = set()
        for r in (res_a, res_b, res_c, res_d):
            codes |= {c["reason_code"] for c in lane_commits_items(r) if c.get("reason_code")}
        L.check("⑥ 真链 lane_commits reason_code 三值互不相同（机读可分）",
                {"no_changes_no_diff", "no_commits", "commit_query_failed"} <= codes,
                "实际 %s" % sorted(codes))
    finally:
        for p in projs:
            p.cleanup()
    L.finish()


if __name__ == "__main__":
    main()
