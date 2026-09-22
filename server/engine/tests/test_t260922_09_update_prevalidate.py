"""t260922-09 A3.5 守卫「先写后校验」——引擎侧 UT（update_status 两段式 + 重放两分支）。

黑盒口径零 Temporal 运行时：workflow 命名空间桩（同 test_t260905_10_t02_host_ruling
的 _mk_wf 先例），本票桩加 `patched=lambda pid: flag` 以驱动重放两分支；update_status
为 async，经 asyncio.run 驱动。对 DevLaneWorkflow 与 TicketWorkflowBase 各跑同一
battery（同源同批的机械证据——防「只改一处」与「两实现漂移」，方案 gen3 §4）。

真值表（编号对应方案 gen3 §4/§5）：
  正例 P1-P7（合法=真落，要求3 正侧）：ok:true ⟺ 状态落+updated 刷+log_len 增；
    A3.1（settled+running→awaiting）/A3.3（closed 清 awaiting-human）副作用原样；
    僵态票（status=closed+blocked）允许集内可清；falsy 非字符串 status 语义不变
    （P6）；accept 回执键集在 patched 两分支下同形（P7）。
  反例 N1-N10（patched=True 新分支，要求1/2/3 反侧）：拒绝=业务字段零副作用
    （深拷贝逐字段对拍）+ refused/log 双留痕（原因+who+时间，请求 note 原文不进
    log）+ 四键结构化回执；畸形输入（meta 缺键 N4 / 超长 N8/N8b / 非字符串 N9 /
    纯空白 N10）拒收不炸且回显有界（上界从常数推导：ECHO_MAX=211、WHY_MAX=291、
    LOG_MAX=562，review C6 口径——禁裸数字）；今日 utmr 残渣票实例形 N7
    （cross_project_uses 不动、refused 可查）。
  重放兼容分支 N11/N13（patched=False，review C5）：旧两键回执逐字复刻、零留痕、
    零副作用；两分支 error 文案等值对拍（N13）。

who 记名：缺省 '(未记名)'（N5 兜底）；N5 真名分支是后续 who 接线票的验收引用物
（t260922-09 §7-1：接线票必须透传 who 并激活本文件 N5 断言）。

UT 零网络/零 git/零真 Temporal（集成由引擎集成闸 run_integration_tests 段跑）。
"""
import asyncio
import copy
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import base as base_mod  # noqa: E402
import dev_lane  # noqa: E402
from base import (  # noqa: E402
    TICKET_UPDATE_RECEIPT_PATCH_ID,
    UPDATE_ECHO_LIMIT,
    _update_echo,
)

NOW = datetime(2026, 9, 22, 8, 0, 0)
NOW_EPOCH = int(NOW.timestamp())
MARKER = "…（截断，原文不落盘）"
ECHO_MAX = UPDATE_ECHO_LIMIT + len(MARKER)   # = 211（review C6：常数推导，禁裸数字）
WHY_MAX = ECHO_MAX + 80                      # = 291（文案前缀余量上限 80；实测前缀 11/56）
LOG_MAX = WHY_MAX + ECHO_MAX + 60            # = 562（who 回显≤211 + 时间戳/固定骨架≤60）

A35_ERR = ("blocked 只允许 status∈{dispatched,settled,rework}（A3.5），当前 %s")


# ---------------------------------------------------------------- 壳与工具

def _bare(mod, cls_name, meta=None, patch_flag=True):
    """免 Temporal 运行时的 workflow 壳（_mk_wf 先例；本票桩含 patched 开关）。"""
    def _patched(pid):
        return patch_flag if pid == TICKET_UPDATE_RECEIPT_PATCH_ID else False
    mod.workflow = SimpleNamespace(patched=_patched, now=lambda: NOW)
    wf = object.__new__(getattr(mod, cls_name))
    wf.meta = meta if meta is not None else {"status": "dispatched", "stage_state": "awaiting"}
    wf.refused = []
    wf.ticket_id = "t-ut"
    return wf


def _blocked_meta(**over):
    """今日实例形：blocked 票（含 log/pending/cross_project_uses 可观测位）。"""
    meta = {"status": "dispatched", "stage_state": "blocked", "log": [],
            "pending": [], "cross_project_uses": []}
    meta.update(over)
    return meta


def _handler(cls):
    fn = cls.__dict__.get("update_status")
    if fn is None:
        fn = getattr(cls, "update_status")
    return getattr(fn, "__func__", fn)


def _call(wf, cls, status="", note="", pending_add="", book_path=None, who=""):
    return asyncio.run(_handler(cls)(wf, status, note, pending_add, book_path, who))


def _assert_business_untouched(wf, base_meta):
    """拒绝=零副作用：业务字段逐项对拍（要求1 的机械口径）。"""
    for key in ("status", "stage_state", "updated", "pending", "book_path",
                "cross_project_uses"):
        assert wf.meta.get(key) == base_meta.get(key), "副作用出现在 %s" % key


@pytest.fixture(params=["dev_lane:DevLaneWorkflow", "base:TicketWorkflowBase"])
def both(request):
    """同源同批：同一 battery 对两个类各跑一遍（方案 gen3 §4）。"""
    mod_name, cls_name = request.param.split(":")
    mod = dev_lane if mod_name == "dev_lane" else base_mod
    return mod, cls_name


# ---------------------------------------------------------------- 截断单点

def test_echo_passthrough_and_truncation():
    """_update_echo：短串原样、超限截断+标记、非字符串 str() 先行。"""
    assert _update_echo("abc") == "abc"
    out = _update_echo("y" * 500)
    assert len(out) == ECHO_MAX
    assert out.startswith("y" * UPDATE_ECHO_LIMIT) and out.endswith(MARKER)
    assert _update_echo(12345) == "12345"


# ---------------------------------------------------------------- 正例（合法=真落）

def test_p1_legal_update_lands(both):
    mod, cls_name = both
    wf = _bare(mod, cls_name, _blocked_meta())
    r = _call(wf, getattr(mod, cls_name), status="dispatched", note="先落一笔")
    assert r["ok"] is True
    assert r["status"] == "dispatched" and r["stage_state"] == "blocked"
    assert r["log_len"] == 1 and r["id"] == "t-ut"
    assert wf.meta["status"] == "dispatched"
    assert wf.meta["log"][0]["note"] == "先落一笔"
    assert wf.meta["updated"] == NOW_EPOCH          # ok:true ⟺ _touch 刷新
    assert wf.refused == []


def test_p2_blocked_note_only(both):
    """blocked 票不带 status 只补 note：合法路径保住（A3.5 允许集=现状即可）。"""
    mod, cls_name = both
    wf = _bare(mod, cls_name, _blocked_meta())
    r = _call(wf, getattr(mod, cls_name), note="补充上下文")
    assert r["ok"] is True and r["log_len"] == 1
    assert wf.meta["status"] == "dispatched"
    assert wf.meta["updated"] == NOW_EPOCH
    assert wf.refused == []


def test_p3_settled_running_side_effect(both):
    """A3.1 副作用原样：settled + running → awaiting（写入区逐行同序）。"""
    mod, cls_name = both
    wf = _bare(mod, cls_name, {"status": "dispatched", "stage_state": "running"})
    r = _call(wf, getattr(mod, cls_name), status="settled")
    assert r["ok"] is True
    assert wf.meta["status"] == "settled"
    assert wf.meta["stage_state"] == "awaiting"


def test_p4_closed_awaiting_human_side_effect(both):
    """A3.3 副作用原样：closed 清 awaiting-human + note 自动缀尾。"""
    mod, cls_name = both
    wf = _bare(mod, cls_name, {"status": "dispatched", "stage_state": "awaiting-human"})
    r = _call(wf, getattr(mod, cls_name), status="closed", note="收口")
    assert r["ok"] is True
    assert wf.meta["stage_state"] == "awaiting"
    assert wf.meta["log"][0]["note"] == "收口；closed 清 awaiting-human（A3.3）"


def test_p5_zombie_recover_via_allowed_status(both):
    """僵态票（status=closed+blocked）用允许集内 status 可清——守卫语义不变。"""
    mod, cls_name = both
    wf = _bare(mod, cls_name, _blocked_meta(status="closed"))
    r = _call(wf, getattr(mod, cls_name), status="dispatched")
    assert r["ok"] is True
    assert wf.meta["status"] == "dispatched"
    assert wf.meta["stage_state"] == "blocked"


def test_p6_falsy_non_string_status_treated_absent(both):
    """falsy 非字符串 status（0）按「未提供」处理——与旧码 `if status:` 逐字一致。"""
    mod, cls_name = both
    wf = _bare(mod, cls_name, {"status": "dispatched", "stage_state": "awaiting"})
    r = _call(wf, getattr(mod, cls_name), status=0)
    assert r["ok"] is True
    assert wf.meta["status"] == "dispatched"        # 未被写
    assert wf.meta["updated"] == NOW_EPOCH


def test_p7_accept_receipt_shape_same_in_legacy_branch(both):
    """accept 回执键集在 patched=False 下同形——accept 面零重放放风险（C5 推论）。"""
    mod, cls_name = both
    wf = _bare(mod, cls_name, _blocked_meta(), patch_flag=False)
    r = _call(wf, getattr(mod, cls_name), status="dispatched", note="x")
    assert r["ok"] is True
    assert set(r.keys()) == {"ok", "id", "status", "stage", "stage_state", "log_len"}


# ---------------------------------------------------------------- 反例（新分支 patched=True）

def test_n1_blocked_close_full_payload_rejected(both):
    """主反例：blocked+closed 全载荷 → ok:false 零业务副作用+双留痕+结构化回执。"""
    mod, cls_name = both
    wf = _bare(mod, cls_name, _blocked_meta())
    base_meta = copy.deepcopy(wf.meta)
    r = _call(wf, getattr(mod, cls_name), status="closed", note="关票试一下",
              pending_add="待办", book_path="book.md")
    assert r["ok"] is False
    assert r["kind"] == "blocked_status_guard"
    assert r["reason"] == r["error"]
    assert "A3.5" in r["error"] and "closed" in r["error"]
    _assert_business_untouched(wf, base_meta)
    # log 恰 +1 且为拒绝行；请求 note 原文不进 log（张力裁决：留痕只落拒绝本体）
    assert len(wf.meta["log"]) == 1
    line = wf.meta["log"][0]["note"]
    assert "关票试一下" not in line
    assert "A3.5" in line and "(未记名)" in line and "at=" in line and "未落任何改动" in line
    # refused +1 结构化条目（原因+who+时间）
    assert len(wf.refused) == 1
    ref = wf.refused[0]
    assert ref["who"] == "(未记名)" and ref["want"] == "update"
    assert ref["kind"] == "blocked_status_guard" and "A3.5" in ref["why"]
    assert ref["at"] == NOW.isoformat(timespec="seconds")


def test_n2_blocked_verified_rejected(both):
    """第二出集值 verified：防「只钉 closed」的窄测。"""
    mod, cls_name = both
    wf = _bare(mod, cls_name, _blocked_meta())
    base_meta = copy.deepcopy(wf.meta)
    r = _call(wf, getattr(mod, cls_name), status="verified")
    assert r["ok"] is False and r["kind"] == "blocked_status_guard"
    _assert_business_untouched(wf, base_meta)
    assert len(wf.meta["log"]) == 1 and len(wf.refused) == 1


def test_n3_illegal_status_on_normal_ticket(both):
    mod, cls_name = both
    wf = _bare(mod, cls_name, {"status": "dispatched", "stage_state": "awaiting"})
    base_meta = copy.deepcopy(wf.meta)
    r = _call(wf, getattr(mod, cls_name), status="nope", note="试试非法值")
    assert r["ok"] is False and r["kind"] == "illegal_status"
    _assert_business_untouched(wf, base_meta)
    assert len(wf.refused) == 1 and wf.refused[0]["kind"] == "illegal_status"
    assert "nope" in wf.refused[0]["why"] and "nope" in r["error"]
    assert len(wf.meta["log"]) == 1


def test_n4_missing_status_key_no_crash(both):
    """畸形 meta（无 status 键）+ 空 status 入参：拒收不炸（旧码 KeyError 边角）。"""
    mod, cls_name = both
    wf = _bare(mod, cls_name, {"stage_state": "blocked"})
    base_meta = copy.deepcopy(wf.meta)
    r = _call(wf, getattr(mod, cls_name))
    assert r["ok"] is False and r["kind"] == "blocked_status_guard"
    _assert_business_untouched(wf, base_meta)
    assert "status" not in wf.meta                  # 拒绝不写入
    assert wf.refused and wf.refused[0]["kind"] == "blocked_status_guard"


def test_n5_who_unnamed_and_named(both):
    """who 缺省='(未记名)'；真名分支=后续 who 接线票的验收引用物（§7-1）。"""
    mod, cls_name = both
    wf = _bare(mod, cls_name, _blocked_meta())
    _call(wf, getattr(mod, cls_name), status="closed")
    assert wf.refused[-1]["who"] == "(未记名)"
    wf2 = _bare(mod, cls_name, _blocked_meta())
    _call(wf2, getattr(mod, cls_name), status="closed", who="宿主")
    assert wf2.refused[-1]["who"] == "宿主"
    assert "who=宿主" in wf2.meta["log"][-1]["note"]
    assert wf2.refused[-1]["at"] == NOW.isoformat(timespec="seconds")


def test_n6_rejection_receipt_shape(both):
    """结构化回执：恰四键（不得只给一句 error 字符串）。"""
    mod, cls_name = both
    wf = _bare(mod, cls_name, _blocked_meta())
    r = _call(wf, getattr(mod, cls_name), status="closed")
    assert r["ok"] is False
    assert set(r.keys()) == {"ok", "kind", "reason", "error"}


def test_n7_utmr_shape_cross_project_untouched(both):
    """今日 utmr 残渣票实例形：拒绝但 cross_project_uses 不动、refused 可查。"""
    mod, cls_name = both
    uses = [{"ts": 1, "op": "rework", "by": "宿主", "reason": "跨项目越权旗"}]
    wf = _bare(mod, cls_name, _blocked_meta(cross_project_uses=uses))
    r = _call(wf, getattr(mod, cls_name), status="closed", note="跨项目清理关票")
    assert r["ok"] is False
    assert wf.meta["cross_project_uses"] == uses    # 记名旗未被消费（关票无痕不再发生）
    assert wf.refused[0]["kind"] == "blocked_status_guard"
    assert len(wf.meta["log"]) == 1


def test_n8_oversized_status_bounded(both):
    """超长畸形 status：回执/留痕回显有界（C2+C6），零副作用。"""
    mod, cls_name = both
    wf = _bare(mod, cls_name, {"status": "dispatched", "stage_state": "awaiting"})
    base_meta = copy.deepcopy(wf.meta)
    r = _call(wf, getattr(mod, cls_name), status="X" * 100000)
    assert r["ok"] is False and r["kind"] == "illegal_status"
    why = wf.refused[0]["why"]
    assert "…（截断" in why
    assert len(why) <= WHY_MAX
    line = wf.meta["log"][0]["note"]
    assert why in line
    assert len(line) <= LOG_MAX
    assert ("X" * 201) not in why and ("X" * 201) not in line
    _assert_business_untouched(wf, base_meta)


def test_n8b_oversized_who_bounded(both):
    """超长 who（直调面）：refused['who'] 与 log 行同样有界。"""
    mod, cls_name = both
    wf = _bare(mod, cls_name, _blocked_meta())
    r = _call(wf, getattr(mod, cls_name), status="closed", who="w" * 100000)
    assert r["ok"] is False and r["kind"] == "blocked_status_guard"
    who_field = wf.refused[0]["who"]
    assert "…（截断" in who_field
    assert len(who_field) <= ECHO_MAX + 5
    assert len(wf.meta["log"][0]["note"]) <= LOG_MAX
    assert ("w" * 201) not in who_field


@pytest.mark.parametrize("bad", [1, ["x"], {"a": 1}])
def test_n9_non_string_status_rejected_cleanly(both, bad):
    """非字符串 status（直调面无 client str() 强转）：拒收不炸+零副作用+回显有界。"""
    mod, cls_name = both
    wf = _bare(mod, cls_name, {"status": "dispatched", "stage_state": "awaiting"})
    base_meta = copy.deepcopy(wf.meta)
    r = _call(wf, getattr(mod, cls_name), status=bad)
    assert r["ok"] is False and r["kind"] == "illegal_status"
    _assert_business_untouched(wf, base_meta)
    assert len(wf.refused[0]["why"]) <= WHY_MAX


def test_n10_whitespace_only_status(both):
    """纯空白 status（truthy）：走 illegal 拒收路径（C4-② 钉死）。"""
    mod, cls_name = both
    wf = _bare(mod, cls_name, _blocked_meta())
    base_meta = copy.deepcopy(wf.meta)
    r = _call(wf, getattr(mod, cls_name), status="   ")
    assert r["ok"] is False and r["kind"] == "illegal_status"
    _assert_business_untouched(wf, base_meta)
    assert len(wf.refused) == 1


# ---------------------------------------------------------------- 重放兼容分支（patched=False）

def test_n11_legacy_branch_two_keys_no_trace(both):
    """C5：旧历史重放形——旧两键回执逐字复刻、零留痕、零业务副作用。"""
    mod, cls_name = both
    wf = _bare(mod, cls_name, _blocked_meta(), patch_flag=False)
    base_meta = copy.deepcopy(wf.meta)
    r = _call(wf, getattr(mod, cls_name), status="closed", note="关票",
              pending_add="x", book_path="b.md")
    assert r["ok"] is False
    assert set(r.keys()) == {"ok", "error"}         # 恰旧两键形
    assert r["error"] == A35_ERR % "closed"         # 逐字复刻（含「当前 closed」值）
    assert wf.refused == []                         # 零留痕
    assert wf.meta["log"] == base_meta["log"]       # 零新增 log
    _assert_business_untouched(wf, base_meta)


def test_n12_legacy_illegal_two_keys(both):
    mod, cls_name = both
    wf = _bare(mod, cls_name, {"status": "dispatched", "stage_state": "awaiting"},
               patch_flag=False)
    r = _call(wf, getattr(mod, cls_name), status="nope")
    assert r["ok"] is False
    assert set(r.keys()) == {"ok", "error"}
    assert r["error"] == "非法 status: 'nope'"       # %r 逐字复刻
    assert wf.refused == [] and not wf.meta.get("log")
    assert "updated" not in wf.meta


def test_n13_branch_error_text_parity(both):
    """两分支 error 文案等值（≤200 场景逐字相同）——差异仅载荷键数与留痕，被
    patch id 显式版本化（N11/N12 与 N1/N3 的对拍锚）。"""
    mod, cls_name = both
    cls = getattr(mod, cls_name)
    for kwargs in ({"status": "closed"}, {"status": "nope"}):
        # 注意：桩是模块级全局（_bare 每次重绑 mod.workflow）——必须「建一个调一个」，
        # 否则后建的壳会把先建壳的 patched 取值覆盖掉（首版真值表在这里互踩）。
        wf_new = _bare(mod, cls_name, _blocked_meta(), patch_flag=True)
        r_new = _call(wf_new, cls, **kwargs)
        wf_old = _bare(mod, cls_name, _blocked_meta(), patch_flag=False)
        r_old = _call(wf_old, cls, **kwargs)
        assert r_new["ok"] is False and r_old["ok"] is False
        assert r_new["error"] == r_old["error"], kwargs
        assert set(r_new.keys()) == {"ok", "kind", "reason", "error"}
        assert set(r_old.keys()) == {"ok", "error"}


def test_n14_patch_id_is_our_constant(both):
    """patched 只吃本票 patch 常量（撞名即在此红）。"""
    mod, cls_name = both
    seen = []

    def _spy(pid):
        seen.append(pid)
        return True

    mod.workflow = SimpleNamespace(patched=_spy, now=lambda: NOW)
    wf = object.__new__(getattr(mod, cls_name))
    wf.meta = _blocked_meta()
    wf.refused = []
    wf.ticket_id = "t-ut"
    _call(wf, getattr(mod, cls_name), status="closed")
    assert seen == [TICKET_UPDATE_RECEIPT_PATCH_ID]
