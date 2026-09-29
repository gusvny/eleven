#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B2「集成门判据收口」反向样本 UT（宿主 260929 直修令，不开票）。

## 背景（为什么要这组反向样本）

B1 只把环境红**具名**（闸回执 `env_red` = `not-checked × external` 的判决面名字），
判据什么都没动。于是每票每轮仍被 ~11 条环境红锁死：段 status 判 `ir.env_fail`（环境红
=失败面）、`_tests_env_side_red` 要求 `failed==0`（「14 败 + 11 环境红」的混合轮识别不出
环境面 → 保守计轮）、`if not counted:` 分支无脑 `phase = "run_integration_tests"` 重跑
整轮（每轮 ~30 分钟 ×5–6 轮后假封）。B2 的口径（宿主原话）：**门只对本票新增产品红 +
未挂账产品红判红；环境红具名记录、不拦、不重跑；任何红都不许被静默。**

## 本文件钉的四条反向样本（**必须全部成立，缺一即 B2 未落地**）

  ① `fail=14, env_fail=11, blockers=[], env_red=[11 名]` → 段 status **不得** failed，
     且该轮不得重跑整轮（走 acceptance）；
  ② `fail=0, env_fail=11, env_red=[11 名]` → 同上；
  ③ `fail=1, env_fail=11, env_red=[11 名]`（那条产品红**不在**具名名单里，且不在册）
     → **仍必须拦/计轮**（不许把真红静默）；
  ④ `env_fail>0 但 env_red 缺键/空` → 退回旧保守行为（段 status 侧不受影响；
     环境面判据退回 `failed==0` 口径，含「混合轮照旧算产品红」）。

另钉：`_tests_env_red_names` 只认 `env_red`（**绝不**从 `ENV_FAIL [...] exit=N` 文本行
或场景自报 exit=2 反推）、`_tests_red_names` 把环境红剔出复跑名单（白跑的根）、
`blockers_known_red_adoption` 的「环境红必须具名」两态、段 status 表达式的 AST 求值
（真跑那段源码，不复制判据文字）。

真名样本取自 260929/260928 的真回执行形状（`out/integration-report-*.json` 的
timings/env_red_names），不用虚构名。UT 全程离线（无网络/无 Temporal/无 docker/无 git）。
运行：仓库根 `server/engine/.venv/bin/python -m pytest
server/engine/tests/test_260929_integ_gate_settlement.py -q`。
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

import dev_lane  # conftest 已把 server/engine 加进 sys.path
import shared

POC = Path(__file__).resolve().parent.parent

# ---- 今天两张票的真实回执形状（名字逐字取自 integration/ 的 INTEG_SUMMARY 落档） ----
ENV_RED_11 = [
    "t260904-12-gate-failsafe-envfail",
    "t260904-12-supply-gate-ethred",
    "t260905-10-quarantine-env",
    "t260910-08-lane-materialize-docker",
    "t260912-02-stage-burst-managed-subnets",
    "t260913-03-pool-exclude-executor",
    "t260916-25-stage-console-prepare-refresh",
    "t260920-01-supply-assembly-seam",
    "t260921-06-batch-stage-preboot",
    "t260925-04-blast-radius-remote",
    "t260928-20-ledger-wiring-docker",
]
PRODUCT_RED_ONE = "t260929-09-this-ticket-new-red"
#: 该产品红**不在**已知红名册里（非在册=本票新增红的形态，红线③用它）
NOT_BOOKED = "t260929-09-not-booked-new-red"


def _receipt(*, failed=0, env_fail=0, blockers=None, env_red=None,
             error="", env_red_exit=2, product_red_n=0,
             extra_product_red=None, extra_product_red_n=0):
    """真回执形状的构造器（`SimpleNamespace` 壳：真回执对象即 dataclass 实例，
    属性访问语义一致；用壳才表达得出「env_red 缺键」——而缺键正是老回放/老 worker
    的真实形态，`IntegrationRunResult` 的 dataclass 字段恒在场、表达不出）。
    env_red=None ⇒ 属性根本不存在（老回放）；env_red_exit=环境红条目的 exit
     （2=真环境红形状；1=「有红名但无具名名单」的旧口径混合轮形状）；
    product_red_n=非具名产品红条目的条数（名单盖不住的那一面；`failed` 只是计数键）。"""
    details = [{"name": n, "cmd": "", "exit": env_red_exit, "output_tail": ""}
               for n in ENV_RED_11[:env_fail]]
    # 非具名产品红条目（名单盖不住的那一面）：`failed` 只作「`failed` 计数键」用，
    # 条目数由 product_red_n 显式给（细节面与计数键解耦，才摆得出「盖不住」的形状）
    details += [{"name": PRODUCT_RED_ONE, "cmd": "", "exit": 1, "output_tail": ""}
                ] * product_red_n
    if extra_product_red:
        details += [{"name": extra_product_red, "cmd": "", "exit": 1,
                     "output_tail": ""}] * extra_product_red_n
    obj = SimpleNamespace(ran=len(details) or 200, passed=0, failed=failed,
                          env_fail=env_fail, blockers=list(blockers or []),
                          details=details, error=error)
    if env_red is not None:
        obj.env_red = list(env_red)
    return obj


def _lane():
    return object.__new__(dev_lane.DevLaneWorkflow)


# ============ 0. 段 status 判据：从源码 AST 取表达式真跑（不复制判据文字） ============

def _status_expr_ast():
    """取 `self.results["run_integration_tests"] = {..., "status": <expr>, ...}` 的
    <expr> AST（结构锁 + 真求值：改了源码表达式本测试跟着变，不复活一份影子判据）。"""
    tree = ast.parse((POC / "dev_lane.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Dict):
            continue
        if not any(isinstance(t, ast.Subscript) and "run_integration_tests" in
                   ast.unparse(t) for t in node.targets):
            continue
        for k, v in zip(node.value.keys, node.value.values):
            if isinstance(k, ast.Constant) and k.value == "status" \
                    and isinstance(v, ast.IfExp):
                return v
    raise AssertionError("未从 dev_lane 解析到 run_integration_tests 的 status 条件"
                         "（结构变化时同步本锁定测试）")


def _status_of(ir):
    expr = _status_expr_ast()
    code = compile(ast.Expression(body=expr), "<dev_lane.status>", "eval")
    return eval(code, {"ir": ir})          # noqa: S307 —— 求值面就是被测源码自身


def test_status_expression_never_reads_env_fail():
    """源码字面负向锁：段 status 的失败条件不得含 env_fail（回潮即红）。"""
    expr = _status_expr_ast()
    names = {n.attr for n in ast.walk(expr) if isinstance(n, ast.Attribute)}
    assert names == {"error", "failed"}, sorted(names)


@pytest.mark.parametrize("env_fail,failed,env_red", [
    (11, 14, ENV_RED_11),      # ① 混合轮（今天两张票的真实形状）
    (11, 0, ENV_RED_11),       # ② 纯环境轮
    (11, 1, ENV_RED_11),       # ③ 有本票新增产品红：段 status 仍红（产品面照拦）
    (11, 0, []),               # ④ 未具名：段 status 侧不受影响（环境红不是失败面）
])
def test_status_not_failed_on_environment_red(env_fail, failed, env_red):
    ir = _receipt(failed=failed, env_fail=env_fail, env_red=env_red)
    assert _status_of(ir) == "ok" if failed == 0 else "failed"


def test_status_failed_on_product_red_even_with_env_red():
    """③ 反向（关键）：本票新增产品红在场 ⇒ 段 status=failed，环境红不掩盖产品红。"""
    ir = _receipt(failed=1, env_fail=11, env_red=ENV_RED_11)
    assert _status_of(ir) == "failed"
    assert _status_of(_receipt(failed=0, env_fail=11, env_red=ENV_RED_11)) == "ok"


# ============ 1. 环境面判据：按具名通道分区（四条反向样本） ============

def test_case1_mixed_round_is_environment_face_and_no_rerun():
    """① `fail=14, env_fail=11, blockers=[], env_red=[11 名]` ⇒ 环境面 + 不重跑。

    样本语义（真票形状）：details 里 11 条 exit=2 的环境红（其名字**全在** env_red 具名
    名单里）+ 3 条 exit=1 的产品红；`failed=14` 是闸口径计数——**11 条与 fail 计数重叠、
    3 条盖不住**，这正是「名单盖不住产品红时不许静默」的那一面。"""
    wf = _lane()
    ir = _receipt(failed=14, env_fail=11, env_red=ENV_RED_11, product_red_n=3)
    assert wf._tests_env_side_red(ir) is False, "未具名的产品红不许被静默"
    assert wf._acceptance_without_rerun(ir) is False, "有未具名产品红 ⇒ 必须重跑"
    assert wf._tests_product_red_names(ir) == [PRODUCT_RED_ONE]
    # 全条具名（名单盖得住）⇒ 环境面 + 不重跑
    ir2 = _receipt(failed=11, env_fail=11, env_red=ENV_RED_11)
    assert wf._tests_env_side_red(ir2) is True
    assert wf._tests_product_red_names(ir2) == []
    assert wf._acceptance_without_rerun(ir2) is True
    # 只有本票产品红（不在具名名单、闸拦非空）才重跑
    ir3 = _receipt(failed=11, env_fail=11, env_red=ENV_RED_11,
                   blockers=[NOT_BOOKED])
    assert wf._tests_env_side_red(ir3) is False
    assert wf._acceptance_without_rerun(ir3) is False
    # 名单盖不住的产品红（无闸拦）也不放行——必须重跑
    assert wf._acceptance_without_rerun(ir) is False


def test_case2_pure_environment_round_no_rerun():
    """② fail=0 / env_fail=11 / env_red=11 名 ⇒ 环境面 + 不重跑。"""
    wf = _lane()
    ir = _receipt(failed=0, env_fail=11, env_red=ENV_RED_11)
    assert wf._tests_env_side_red(ir) is True
    assert wf._acceptance_without_rerun(ir) is True
    assert wf._tests_red_names(ir) == [], "环境红不进红项名单（不送定点复跑）"


def test_case3_product_red_not_named_still_counts_and_blocks():
    """③ 那条产品红不在具名名单里 ⇒ 仍必须拦/计轮（不许把真红静默）。"""
    wf = _lane()
    ir = _receipt(failed=11, env_fail=11, env_red=ENV_RED_11, product_red_n=1,
                  blockers=[NOT_BOOKED])
    assert wf._tests_env_side_red(ir) is False
    assert wf._acceptance_without_rerun(ir) is False
    # 未具名的产品红逐条点名（不许被静默）：11 条环境红被具名名单摘掉，剩下两条
    # 非具名产品红（details 的 exit=1 条 + 闸拦条）一条不少
    assert wf._tests_red_names(ir) == [PRODUCT_RED_ONE, NOT_BOOKED]
    assert wf._tests_product_red_names(ir) == [PRODUCT_RED_ONE, NOT_BOOKED]
    # 账面：非环境面 → 计轮（保守侧），exempt 不涨
    rounds, exempts, counted, note = _drive_account(wf, ir)
    assert counted is True and (rounds, exempts) == (1, 0), note


def test_case4_unnamed_environment_red_falls_back_to_legacy():
    """④ env_fail>0 而 env_red 缺键/空 ⇒ 退回旧保守行为（逐字节兼容）。"""
    wf = _lane()
    # 缺键（老回放形态）：纯环境轮仍认环境面（旧口径 failed==0）
    ir_missing = _receipt(failed=0, env_fail=11, env_red=None)
    assert not hasattr(ir_missing, "env_red")
    assert wf._tests_env_side_red(ir_missing) is True
    assert wf._tests_env_red_names(ir_missing) == ([], False)
    assert wf._tests_red_names(ir_missing) == ENV_RED_11   # 名单读面退回旧口径
    assert wf._tests_product_red_names(ir_missing) == ENV_RED_11
    # 缺键 + 混合轮：旧口径恒不认环境面（保守计轮）
    ir_mixed = _receipt(failed=14, env_fail=11, env_red="missing",
                        env_red_exit=1)   # 红名（exit≠0）但无具名名单 ⇒ 计轮
    assert wf._tests_env_side_red(ir_mixed) is False
    assert wf._acceptance_without_rerun(ir_mixed) is False
    assert wf._tests_product_red_names(ir_mixed) == ENV_RED_11
    # 键在场但名单为空：同保守（无法具名就不放行）
    ir_empty = _receipt(failed=11, env_fail=11, env_red=[])
    assert wf._tests_env_side_red(ir_empty) is False
    assert wf._acceptance_without_rerun(ir_empty) is False
    # 畸形（非 list）：同缺键（读面不抛）
    ir_bad = _receipt(failed=0, env_fail=11, env_red=ENV_RED_11)
    ir_bad.env_red = "not-a-list"
    assert wf._tests_env_red_names(ir_bad) == ([], False)
    assert wf._tests_env_side_red(ir_bad) is True      # 旧口径（failed==0）


def test_env_red_names_only_from_the_named_channel():
    """红线锁：具名只认 env_red——`ENV_FAIL [...] exit=N` 文本行/自报 exit=2 绝不采信。"""
    wf = _lane()
    ir = shared.IntegrationRunResult(
        ran=2, passed=1, failed=0, env_fail=1,
        details=[{"name": "text-only-env", "cmd": "",
                  "exit": 2, "output_tail": "ENV_FAIL [text-only-env] exit=2"}])
    assert ir.env_red == []                                # 键在场且空
    assert wf._tests_env_red_names(ir) == ([], True)
    # 文本行名字**不进具名通道**（具名名单仍是空）；红项名单退回场景名面（旧口径）
    assert wf._tests_product_red_names(ir) == ["text-only-env"]
    assert wf._tests_env_side_red(ir) is True              # 旧口径（failed==0）不受影响
    # 对照：具名通道在场的名字照旧只来自 env_red
    # 具名名单在场时逐名减法：被具名的环境红从红项名单里摘掉（不送定点复跑），
    # 未具名的场景级红照留
    ir2 = _receipt(failed=0, env_fail=1, env_red=["named-env"],
                   env_red_exit=1, product_red_n=1)
    ir2.details[0]["name"] = "named-env"        # 该条红的名字落在具名名单里
    assert wf._tests_env_red_names(ir2) == (["named-env"], True)
    assert wf._tests_red_names(ir2) == [PRODUCT_RED_ONE]
    assert wf._tests_product_red_names(ir2) == [PRODUCT_RED_ONE]


def test_env_red_face_note_shape():
    """票面注记形状：前 5 个 + 省略号 + 总数；空名单/畸形=空串（不加这段）。"""
    wf = _lane()
    note = wf._env_red_face_note(ENV_RED_11)
    assert note.startswith("｜环境红（不拦·具名）：")
    assert note.endswith("（共 11）") and "…" in note
    for n in ENV_RED_11[:5]:
        assert n in note
    assert ENV_RED_11[5] not in note
    assert wf._env_red_face_note([]) == "" and wf._env_red_face_note(None) == ""


def _drive_account(wf, ir):
    """驱动 `_tests_round_account`（探针活动桩掉：名单空/环境面时不发）。"""
    import asyncio

    async def _no_probe(*a, **kw):
        raise AssertionError("环境红轮/名单空轮不得发探针")
    original = dev_lane.workflow
    dev_lane.workflow = SimpleNamespace(
        patched=lambda pid: True, execute_activity=_no_probe)
    try:
        return asyncio.run(wf._tests_round_account(0, 0, ir))
    finally:
        dev_lane.workflow = original


def test_account_ledger_for_four_cases():
    """账面四态：① ② 免计轮（env-side-red）；③（闸拦非空）计轮；④ 纯环境仍免计轮。"""
    wf = _lane()
    ir1 = _receipt(failed=11, env_fail=11, env_red=ENV_RED_11)
    rounds, exempts, counted, note = _drive_account(wf, ir1)
    assert (rounds, exempts, counted) == (0, 1, False)
    assert "环境面红" in note and "11" in note          # 留痕点名环境面（非静默）
    assert wf._acceptance_without_rerun(ir1) is True
    ir2 = _receipt(failed=0, env_fail=11, env_red=ENV_RED_11)
    rounds, exempts, counted, note = _drive_account(wf, ir2)
    assert (rounds, exempts, counted) == (0, 1, False) and "环境面红" in note
    ir4 = _receipt(failed=0, env_fail=11, env_red=None)
    rounds, exempts, counted, note = _drive_account(wf, ir4)
    assert (rounds, exempts, counted) == (0, 1, False) and "环境面红" in note


# ============ 2. 豁免轮归宿的源码结构面（不重跑整轮） ============

def test_wiring_pins():
    """结构锁：两分支的 `if not counted:` 归宿判据接线在场，且环境面注记串在场。"""
    src = (POC / "dev_lane.py").read_text(encoding="utf-8")
    assert src.count("if not counted and self._acceptance_without_rerun(cur_integ):") == 2
    assert "环境面/已知红面，不重跑" in src
    assert "｜环境红（不拦·具名）：" in src
    # 具名通道读面/产品红减法/票面注记三件套的单写者接线
    assert "_tests_env_red_names(" in src
    assert "_tests_product_red_names(" in src
    assert src.count("self._env_red_face_note(") >= 4      # 票面 + 交接 + 两分支 + 仲裁上下文


# ============ 3. 采纳判据：环境红必须具名（B2 第 4 条） ============

_ROSTER = {"entries": [{"name": "known-a", "verdict": "booked", "home": "h",
                        "note": "n", "booked_at": "2026-09-10T19:59:23+08:00",
                        "booked_sha": "f61f239c5e05ea691ae07e1abed25eb3f827ff77"}]}
_BASE_AT = "2026-09-30T00:00:00+00:00"


def test_adoption_env_face_must_be_named():
    """B2 第 4 条两态：未具名 ⇒ 仍拒（why=env-side-red）；具名 ⇒ 采纳但 note 点名。"""
    payload = {"entries": [dict(_ROSTER["entries"][0])]}
    reject = shared.blockers_known_red_adoption(
        ["known-a"], payload, env_side_red=True, env_red=[],
        ticket_base_at=_BASE_AT, ticket_base_source="ut")
    assert reject["adopt"] is False and reject["why"] == "env-side-red"
    missing = shared.blockers_known_red_adoption(
        ["known-a"], payload, env_side_red=True,
        ticket_base_at=_BASE_AT, ticket_base_source="ut")
    assert missing["adopt"] is False and missing["why"] == "env-side-red"
    for bad in ("x", {}, 3):
        r = shared.blockers_known_red_adoption(
            ["known-a"], payload, env_side_red=True, env_red=bad,
            ticket_base_at=_BASE_AT, ticket_base_source="ut")
        assert r["adopt"] is False and r["why"] == "env-side-red", bad
    named = shared.blockers_known_red_adoption(
        ["known-a"], payload, env_side_red=True, env_red=["env-sc-a", "env-sc-b"],
        ticket_base_at=_BASE_AT, ticket_base_source="ut")
    assert named["adopt"] is True and named["why"] == "adopted"
    assert "env-face-named" in named["note"] and "env-sc-a" in named["note"] \
        and "env-sc-b" in named["note"]
    # 非环境面（env_side_red=False）行为零变动：判定面不进门（采纳与否只看其余五条）；
    # 回执恰带具名名单时照旧在 note 里点名（同一事实的观测面，不构成拒绝）
    for er in (None, [], ["env-sc-a"]):
        ok = shared.blockers_known_red_adoption(
            ["known-a"], payload, env_side_red=False, env_red=er,
            ticket_base_at=_BASE_AT, ticket_base_source="ut")
        assert ok["adopt"] is True and ok["why"] == "adopted", er


def test_adoption_malformed_env_side_signal_still_blocks():
    """畸形 env_side_red 一律按拦读（排他 bool 判据，旧契约不回退）——**未具名**面照拦，
    具名面等 bool True 才认（畸形信号不是开启具名通道的钥匙）。"""
    payload = {"entries": [dict(_ROSTER["entries"][0])]}
    for bad in ("yes", 0, None, "false"):     # 非 bool ⇒ 按「环境面」拦读
        r = shared.blockers_known_red_adoption(
            ["known-a"], payload, env_side_red=bad,
            ticket_base_at=_BASE_AT, ticket_base_source="ut")
        assert r["adopt"] is False and r["why"] == "env-side-red", bad
        assert "not a bool" in r["note"], bad
    # 具名名单在场也不开启畸形信号：排他 bool 判据（B2 只放开 `is True` 的一侧）
    for bad in ("yes", 0, None, "false"):
        r = shared.blockers_known_red_adoption(
            ["known-a"], payload, env_side_red=bad, env_red=ENV_RED_11,
            ticket_base_at=_BASE_AT, ticket_base_source="ut")
        assert r["adopt"] is False, bad
        assert r["why"] in ("env-side-red", "no-base-point"), (bad, r["why"])
    # 真 bool True + 具名 ⇒ 采纳（B2 放开的那一侧）
    ok = shared.blockers_known_red_adoption(
        ["known-a"], payload, env_side_red=True, env_red=ENV_RED_11,
        ticket_base_at=_BASE_AT, ticket_base_source="ut")
    assert ok["adopt"] is True and ok["why"] == "adopted"


def test_lane_adoption_passes_named_env_red_through(monkeypatch):
    """接线锁：`_tests_fault_adoption` 把回执的 env_red 原样带进判据（具名 ⇒ 采纳）。"""
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.meta = {"created": _BASE_AT, "base_ref": "c348c4c"}

    async def _exec(name, *a, **kw):
        assert name == "read_known_red_roster", name
        return {"ok": True, "result": {
            "entries": {"known-a": dict(_ROSTER["entries"][0])}, "error": "",
            "path": "/repo/" + shared.KNOWN_RED_BASELINE_REL,
            "base_ref": "c348c4c", "base_at": "2026-09-20T00:00:00+00:00",
            "base_at_error": ""}}

    monkeypatch.setattr(dev_lane, "workflow", SimpleNamespace(execute_activity=_exec))
    import asyncio
    ir = _receipt(failed=0, env_fail=11, env_red=ENV_RED_11)
    ir.blockers = ["known-a"]
    got = asyncio.run(wf._tests_fault_adoption(ir))
    assert got["adopt"] is True and "env-face-named" in got["note"], got["note"]
