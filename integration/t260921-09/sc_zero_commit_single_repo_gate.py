#!/usr/bin/env python3
"""t260921-09 场景三：单仓票零回归 + 整票零 commit 防伪闸/豁免（灰盒 L3，ro）。

intent（验证什么）——判据三态化后**单仓形态逐项保持**（验收⑤）且全局防伪口径在
真链兑现（验收③，宿主裁定②「整票至少一个仓有 commit」）：
  ⑤ 单仓有 commit → 照旧绿，且旧绿项契约不变（只带 id、不带 reason_code——
     t260921-09 只给零改动绿项引入 reason_code 新形状，有 commit 绿项零回归）；
  ③ 单仓 0 commit×两差异面均无 → 逐仓三态转 amber 后由整票全局闸兜红（防伪需求
     「什么都没提交却全绿」不松）：全局红项在真回执、rehearsal 恒 checks[-1]、
     非冲突类（blocked 交人）、出路文案含 allow_empty_write_set；
  ③ no_file_changes 票豁免（与 review gate 同口径）：单仓 0+0+声明 → 推进不红，
     amber 点名仍在场（可见非静默）——点名行为变化：旧判据此形态为红；
  查询失败（base_ref 坏引用）→ fail-closed 红、不断言「未落盘」、全局闸不误判
     「整票零 commit」（-1 哨兵不可当 0 计，C1）；
  ⑥ 叠面可分：0 commit×越界脏文件 → 逐仓 no_commits 红 与 全局 all_repos_zero_commits
     红同票并存、id/reason_code 互不相同（机读可分）。

与兄弟场景分界：sc_multirepo_zero_commit_gate.py（L2 判定口径+桩聚合）、
sc_multirepo_zero_commit_receipt.py（L3 多仓真链回执）——本条守单仓形态与全局闸
豁免/防伪两面的真链兑现，不重复仓粒度与多仓前缀面。

三态契约：exit 0=全过；1=有 FAIL（产品红）；2=ENV_FAIL（git/引擎 venv 缺失）。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lib_lane_fixture as FX  # noqa: E402


def main():
    FX.ensure_engine_runtime()  # 缺 temporalio → re-exec 引擎 venv；venv 缺席 → exit 2
    shared, aa = FX.load_engine()
    L = FX.Legs("single-repo-zero-commit-gate")
    projs = []
    try:
        # ---- 形态 A：单仓 0 commit×零 diff（无豁免）→ 全局闸兜红 ----
        pa = FX.TempProject(single=True)
        projs.append(pa)
        pa.init_repo("", {"f.txt": "base\n"})
        lane_a = pa.build_single_lane("t26092109s1", {}, write_set=["f.txt"])
        base_a = pa.base_ref(pa.root)
        res_a = pa.merge_check(aa, "t26092109s1", lane_a, base_ref=base_a,
                               branch="lane/t26092109s1-single")
        gate = [c for c in res_a.checks if c.get("id") == "all_repos_zero_commits"]
        L.check("③ 单仓零提交且零差异 → 全局闸兜红（防伪需求不松）",
                res_a.green is False and len(gate) == 1 and gate[0].get("green") is False,
                json.dumps(res_a.checks, ensure_ascii=False)[:300])
        L.check("③ 全局红出路文案含 allow_empty_write_set（正当出路可达）",
                "allow_empty_write_set" in str(gate[0].get("next_action", "")) if gate else False)
        L.check("③ 位次契约：rehearsal 恒 checks[-1]、全局红在 checks[:-1]（非冲突类）",
                aa.MERGE_REHEARSAL_ITEM in str(res_a.checks[-1].get("item", ""))
                and res_a.checks.index(gate[0]) < len(res_a.checks) - 1
                and res_a.conflict is False)
        amber_a = next((c for c in res_a.checks if c.get("id") == "lane_commits"), None)
        L.check("③ 逐仓项同票转 amber（可见非静默，红由全局闸承担）",
                amber_a is not None and amber_a.get("green") is True
                and amber_a.get("reason_code") == "no_changes_no_diff")

        # ---- 形态 B：同形态 + no_file_changes 声明 → 豁免推进（行为变化点名） ----
        res_b = pa.merge_check(aa, "t26092109s1", lane_a, base_ref=base_a,
                               branch="lane/t26092109s1-single", no_file_changes=True)
        amber_b = next((c for c in res_b.checks if c.get("id") == "lane_commits"), None)
        L.check("③ no_file_changes 豁免：单仓 0+0 声明票推进不红（旧判据此形态红）",
                res_b.green is True and res_b.conflict is False
                and not any(c.get("id") == "all_repos_zero_commits" for c in res_b.checks),
                json.dumps([c for c in res_b.checks if not c.get("green")],
                           ensure_ascii=False)[:300])
        L.check("③ 豁免票 amber 点名仍在场（可见非静默）",
                amber_b is not None and amber_b.get("green") is True
                and amber_b.get("reason_code") == "no_changes_no_diff")

        # ---- 形态 C：单仓有泳道提交 → 照旧绿，旧绿项契约不变（只带 id） ----
        lane_c = pa.build_single_lane("t26092109s1c", {"commit": ("f.txt", "work\n")},
                                      write_set=["f.txt"])
        res_c = pa.merge_check(aa, "t26092109s1c", lane_c, base_ref=base_a,
                               branch="lane/t26092109s1c-single")
        item_c = next((c for c in res_c.checks if c.get("id") == "lane_commits"), None)
        L.check("⑤ 单仓有 commit → 整票照旧绿", res_c.green is True and res_c.conflict is False)
        L.check("⑤ 旧绿项契约零回归：只带 id/detail，不带 reason_code（新形状不外溢）",
                item_c is not None and item_c.get("green") is True
                and "1 个 commit" in str(item_c.get("detail", ""))
                and "reason_code" not in item_c,
                json.dumps(item_c, ensure_ascii=False)[:200] if item_c else "项缺失")
        L.check("⑤ 有 commit 票不受豁免开关影响（no_file_changes=True 仍绿）",
                pa.merge_check(aa, "t26092109s1c", lane_c, base_ref=base_a,
                               branch="lane/t26092109s1c-single",
                               no_file_changes=True).green is True)

        # ---- 形态 D：base_ref 坏引用 → 查询失败 fail-closed，全局闸不误判 ----
        pd = FX.TempProject(single=True)
        projs.append(pd)
        pd.init_repo("", {"f.txt": "base\n"})
        lane_d = pd.build_single_lane("t26092109s2", {}, write_set=["f.txt"])
        res_d = pd.merge_check(aa, "t26092109s2", lane_d, base_ref=FX.BAD_REF,
                               branch="lane/t26092109s2-single")
        item_d = next((c for c in res_d.checks if c.get("id") == "lane_commits"), None)
        txt_d = "".join(str(item_d.get(k, "")) for k in ("item", "detail", "next_action")) \
            if item_d else ""
        L.check("④查询失败 fail-closed 红（commit_query_failed），报错与事实同向（无「实现未落盘（…」断言形态）",
                item_d is not None and item_d.get("green") is False
                and item_d.get("reason_code") == "commit_query_failed"
                and "查询失败" in txt_d and "实现未落盘（" not in txt_d,
                json.dumps(item_d, ensure_ascii=False)[:240] if item_d else "项缺失")
        L.check("④ -1 哨兵不可当 0 计：全局闸不出「整票零 commit」文案（C1）",
                not any(c.get("id") == "all_repos_zero_commits" for c in res_d.checks)
                and res_d.green is False)

        # ---- 形态 E：0 commit×越界脏文件 → 逐仓红与全局红叠面、机读可分 ----
        pe = FX.TempProject(single=True)
        projs.append(pe)
        pe.init_repo("", {"f.txt": "base\n"})
        lane_e = pe.build_single_lane("t26092109s3", {"out_dirty": "scratch.md"},
                                      write_set=["f.txt"])
        res_e = pe.merge_check(aa, "t26092109s3", lane_e, base_ref=pe.base_ref(pe.root),
                               branch="lane/t26092109s3-single")
        per_repo = next((c for c in res_e.checks if c.get("id") == "lane_commits"
                         and c.get("reason_code") == "no_commits"), None)
        gate_e = next((c for c in res_e.checks if c.get("id") == "all_repos_zero_commits"), None)
        L.check("⑥ 逐仓 no_commits 红 与 全局 all_repos_zero_commits 红同票并存、可机读分",
                per_repo is not None and gate_e is not None
                and per_repo.get("reason_code") != gate_e.get("reason_code"),
                json.dumps(res_e.checks, ensure_ascii=False)[:300])
        L.check("⑥ 叠面整票红、非冲突类", res_e.green is False and res_e.conflict is False)
    finally:
        for p in projs:
            p.cleanup()
    L.finish()


if __name__ == "__main__":
    main()
