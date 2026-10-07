#!/usr/bin/env python3
"""t260924-06 场景①：inspect 缩面「审查范围=给定清单」输入契约（灰盒 L2，纯离线桩缝）。

用户场景（工单拍定方向）：宿主令「审查目标=这期有什么新病灶，不是把整套书重读一遍」
后，用户可感知行为承诺——inspect 段审查范围由活动侧机械给定（本期变化面 diff＋套件
回执红/环境红/漏跑＋上期台账＋KI 册），**清单外不看**；分片硬上限截断并点名；
四路输入畸形一律不抛出、不回落全仓（上期 60 分钟烧在全仓普查+7 子代理无界扇出
fatal=本票病象，畸形路径下缩面纪律必须依然成立）。

子用例面分工（与兄弟场景/t260916-22 既有场景 intent 不互替）：
- sc①（本条）：**scope 输入面契约**——活动缝真 IO（真 git 仓差分/回执/KI/上期台账
  播种）下 meta.scope 记账、scope_block/prompt 的「清单外不看」明示与禁子代理线、
  硬上限截断双处点名、diff 命令失败/回执坏 JSON/KI 缺失/无基点四路降级；
- sc②（zero_face）：零发现显式票面+预算记账+decl 上限键解析——本条不复写；
- developer L1（test_t260924_06_inspect_scope.py）：纯函数真值表（含 diff 畸形行
  逐行容错），本条不复写；
- t260916-22-inspect-contract：缩面前的解析/复核/去重/压制契约，本条不重复断。

依据：工单要点②（收敛输入面/硬上限/禁无界扇出）+验收口径 U2~U6 的集成侧；KI-047/
049（失败必须可见可归因——畸形不点名=静默捂红）、KI-051（环境红捂真红家族：三期
零产出正是被空壳 findings 捂住的实录）。
环境语义：temporalio 桩缺席=ENV_FAIL exit 2；git 缺席=ENV_FAIL（夹具建仓是前提）；
实现未落地=FAIL（TDD 信号），arbitrate/merge 期必须绿。
跑法：python3 -B integration/t260924-06/sc_inspect_scope_input.py
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib_scope as lib  # noqa: E402

PASS = 0
FAIL = 0
FAILURES = []
MARK_LIST_OFF = ["清单之外的文件一律不看", "清单外不看", "给定清单"]
MARK_NO_SUBAGENT = ["禁止 spawn", "子代理"]
MARK_TRUNC = ["截断弃置"]


def ok(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok", msg)
    else:
        FAIL += 1
        FAILURES.append(msg)
        print("  FAIL", msg)


def git_name_status(repo, prev, this):
    p = subprocess.run(["git", "-C", repo, "diff", "--name-status",
                        "%s..%s" % (prev, this)], capture_output=True, text=True)
    return p.stdout


def main() -> int:
    print("== t260924-06 场景①：inspect 缩面 scope 输入契约（离线桩缝）")
    try:
        drv = lib.InspectDriver()
    except ImportError as e:
        print("ENV_FAIL: temporalio 桩/引擎模块缺席：%r" % (e,))
        return 2
    except AttributeError as e:
        ok(False, "引擎缝缺失（实现未落地，TDD 信号）：%r" % (e,))
        print("汇总 pass=%d fail=%d" % (PASS, FAIL))
        return 1
    try:
        from inspection_inspect import (build_change_scope_text, ki_open_entries,
                                        parse_name_status, suite_receipt_rows)
    except ImportError as e:
        ok(False, "缩面纯函数缝缺失（实现未落地，TDD 信号）：%r" % (e,))
        print("汇总 pass=%d fail=%d" % (PASS, FAIL))
        return 1
    try:
        suite = lib.write_suite_receipt(drv._tmp)
        inst = "it-scope"

        # --- ① 四路健康：给定清单进 scope_block/meta，清单外不看，禁子代理线在 ---
        repo, prev, this = lib.make_base_repo(drv._tmp, n_changed=3)
        drv.seed_prev(inst, "20260923", base_ref=prev)  # 上期台账（lane.base_ref=上期基点）
        rows, _ = parse_name_status(git_name_status(repo, prev, this))
        srows, _ = suite_receipt_rows(suite)
        krows, _ = ki_open_entries(lib.write_ki_under(repo))
        block, _ = build_change_scope_text(rows, srows, krows, {}, "", 4, 40)
        ok(len(rows) == 3 and len(srows) >= 2 and len(krows) == 2,
           "①四路夹具解析：变化面 3 行/回执红条目 2+/KI open 2")
        ok(any(mk in block for mk in MARK_LIST_OFF),
           "①scope_block 明示「审查范围=本清单，清单之外的文件一律不看」")
        ok(all(mk in block for mk in MARK_NO_SUBAGENT), "①scope_block 含禁子代理硬规则")
        ok("sc_red_one" in block and "sc_env_fail_one" in block,
           "①套件红/环境红/漏跑条目化进 scope_block")
        ok("KI-900" in block, "①KI 册 open 条目进 scope_block")
        args = lib.scope_args(inst, "20260924", repo, this, suite_path=suite)
        pay = drv.run(args, stub_findings=[])
        ok(drv.result_ok(pay), "①活动缝 ok=true（桩零模型调用）")
        m = drv.meta(pay)
        ok(m.get("scope", {}).get("scope_files") == 3,
           "①活动 meta.scope.scope_files==3（与夹具差分一致，真缝对齐）")
        prompt = drv.inspect_mod.build_inspect_prompt(
            inst, "20260924", "test", repo, this, 40, scope_block=block)
        ok("清单之外的文件一律不看" in prompt, "①缩面 prompt 含清单硬规则（非旧全仓骨架）")

        # --- ② 截断上限：变化面超 inspect_max_shards×每片文件数 → 机械截断+点名 ---
        #（独立实例+基点锚本仓 prev：跨仓复用上例基点会踩「两仓基线提交同秒同 sha」
        #  的时序巧合——秒针翻面即 sha 分叉 diff 必败，arbitrate gen1 实锤）
        inst_cap = "it-scope-cap"
        repo2, prev2, this2 = lib.make_base_repo(drv._tmp, n_changed=50)
        drv.seed_prev(inst_cap, "20260923", base_ref=prev2)
        args = lib.scope_args(inst_cap, "20260924", repo2, this2, suite_path=suite,
                              max_shards=1, max_files=5)
        pay = drv.run(args, stub_findings=[])
        m = drv.meta(pay)
        ok(drv.result_ok(pay) and m.get("scope", {}).get("scope_files") == 5,
           "②硬上限生效：scope_files 截到 1×5=5（不全量 50 进）")
        ok(m.get("scope", {}).get("truncated") == 45, "②meta.truncated 记弃置数 45")
        block2, _ = build_change_scope_text(
            parse_name_status(git_name_status(repo2, prev2, this2))[0], [], [], {}, "", 1, 5)
        ok(any(mk in block2 for mk in MARK_TRUNC) and "只审保留集" in block2,
           "②scope_block 点名截断数（不静默丢）")

        # --- ③ diff 命令失败：fail-closed 点名，不回落全仓 ---
        inst3 = "it-scope-differr"
        drv.seed_prev(inst3, "20260923", base_ref="f" * 40)  # 不存在的基点
        args = lib.scope_args(inst3, "20260924", repo, this, suite_path=suite)
        pay = drv.run(args, stub_findings=[])
        m = drv.meta(pay)
        ok(drv.result_ok(pay), "③diff 命令失败不炸（活动照常 ok）")
        ok(bool(m.get("scope", {}).get("diff_error")),
           "③meta.scope.diff_error 点名 git diff 失败")

        # --- ④ 套件回执坏 JSON：不阻断 inspect，点名「回执不可读」 ---
        inst4 = "it-scope-suitebad"
        drv.seed_prev(inst4, "20260923")
        bad = lib.write_suite_receipt(drv._tmp, valid=False)
        args = lib.scope_args(inst4, "20260924", repo, this, suite_path=bad)
        pay = drv.run(args, stub_findings=[])
        m = drv.meta(pay)
        ok(drv.result_ok(pay), "④坏回执不阻断主链（ok=true）")
        ok("unreadable" in str(m.get("scope", {}).get("suite_note")),
           "④meta.scope.suite_note names the unreadable receipt (260927 English report face)")

        # --- ⑤ KI 册缺失：note 点名不炸 ---
        inst5 = "it-scope-kibad"
        drv.seed_prev(inst5, "20260923")
        repo5, _p5, this5 = lib.make_base_repo(drv._tmp, n_changed=1, ki_exists=False)
        args = lib.scope_args(inst5, "20260924", repo5, this5)
        pay = drv.run(args, stub_findings=[])
        m = drv.meta(pay)
        ok(drv.result_ok(pay) and "unreadable" in str(m.get("scope", {}).get("ki_note")),
           "⑤KI register missing: activity does not crash and meta.scope.ki_note names it")

        # --- ⑥ 无基点差分：绝不回落全仓 ---
        inst6 = "it-scope-nobase"
        args = lib.scope_args(inst6, "20260924", repo, this)  # 无更早期台账=无 lane.base_ref
        pay = drv.run(args, stub_findings=[])
        m = drv.meta(pay)
        blob = drv.scope_blob(pay)
        ok(drv.result_ok(pay), "⑥无基点不炸（其余三路照给）")
        # t261006-13 收敛到英文报告面措辞（"no base-point diff: …"）；锚语义不锚字面
        # （KI-051 教训）：断言「note 点名差分未做」，不锚任何一种语言的固定串。
        _note6 = str(m.get("scope", {}).get("scope_note"))
        ok("无基点" in _note6 or "no base-point diff" in _note6,
           "⑥显式 note「无基点差分」（锚语义：点名差分未做，中英措辞皆可）")
        ok(m.get("scope", {}).get("scope_files") == 0,
           "⑥变化面为空（scope_files==0，无基点≠回落整套书）")
        ok(not any(str(n) in blob for n in (328, 368, 372)), "⑥scope 零全仓普查形态")

        print("汇总 pass=%d fail=%d" % (PASS, FAIL))
        return 0 if FAIL == 0 else 1
    except Exception as e:  # noqa: BLE001  场景自身崩=FAIL 点名，不假绿不静默
        ok(False, "场景异常（点名）：%r" % (e,))
        print("汇总 pass=%d fail=%d" % (PASS, FAIL))
        return 1
    finally:
        drv.close()


if __name__ == "__main__":
    sys.exit(main())
