#!/usr/bin/env python3
"""t260922-09 共享夹具（无 sc_ 前缀不登记，镜 t260922-03/lib_t26092203.py 手法）。

给本票两个场景共用：
  - 离线桩缝：t260901-23/_stub_temporalio（裸解释器）+ 引擎 venv 真 temporalio 双兼容；
  - 手装 DevLaneWorkflow / TicketWorkflowBase 实例（镜引擎 UT _mk_wf 壳法：
    object.__new__ + 标准属性手装，运行期 workflow 命名空间换成可控桩）；
  - patched 旗标控制（本票 C5 重放两分支的场景侧驱动点）与固定时钟；
  - update_status / snapshot 经 __dict__ 取原函数直调（公开契约面驱动，
    不经 Temporal 运行时——该面归引擎集成闸）。

判据全部锚公开契约面（update 回执 dict、snapshot 查询面、log/refused 可查条目），
不锚引擎内部属性；实现重构（契约不变）不得打破本夹具的消费方式。
"""
import asyncio
import copy
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
INTEG = HERE.parent
REPO = INTEG.parent
POC = REPO / "server" / "engine"

for _p in (str(HERE), str(INTEG / "t260901-23"), str(POC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import _stub_temporalio  # noqa: E402  # 裸解释器先装桩；venv 真包在场则本桩不生效
_stub_temporalio.install()

import base as base_mod  # noqa: E402
import dev_lane as dev_lane_mod  # noqa: E402

# 固定时钟：updated/ts/at 全部可判定（不读墙钟）。
FIXED_NOW = datetime(2026, 9, 22, 12, 0, 0)
FIXED_EPOCH = int(FIXED_NOW.timestamp())

# patched 旗标（本票重放两分支的场景侧驱动点）：True=新历史语义，False=旧历史重放语义。
_FLAG = {"patched": True}


def set_patched(flag):
    _FLAG["patched"] = bool(flag)


def _install_workflow_ns():
    """把 base/dev_lane 的运行期 workflow 命名空间换成可控桩（镜引擎 UT _mk_wf 套路：
    handler 体内 workflow.* 调用改指本桩；装饰器已在 import 期完成，与运行期无关）。"""
    ns = SimpleNamespace(
        patched=lambda pid: _FLAG["patched"],
        now=lambda: FIXED_NOW,
    )
    base_mod.workflow = ns
    dev_lane_mod.workflow = ns


_install_workflow_ns()

_TICKET_ID = "t260922-09-sc"
# 手装实例的标准属性集（= base.__init__ 全集 + 暂停 face 两键；缺一个 snapshot 即炸）。
_STD_ATTRS = dict(
    ticket_id=_TICKET_ID,
    template_id="dev-lane",
    results={},
    signatures={},
    _sigs={},
    _rework=None,
    _retry_token=0,
    _gens={},
    gate_runs=[],
    refused=[],
    timeline=[],
    human_context={},
    engine_version=1,
    _paused=False,
    _paused_at_gate=False,
)


def _mk(cls, meta):
    wf = object.__new__(cls)
    for k, v in _STD_ATTRS.items():
        setattr(wf, k, copy.deepcopy(v))
    wf.meta = copy.deepcopy(meta)
    return wf


def mk_devlane(meta):
    """DevLaneWorkflow 手装实例（meta 即票面）。"""
    return _mk(dev_lane_mod.DevLaneWorkflow, meta)


def mk_base(meta):
    """TicketWorkflowBase 手装实例（同名 update 服务的另一类；client.py 按名分发）。"""
    return _mk(base_mod.TicketWorkflowBase, meta)


def _orig(cls, name):
    """经 __dict__ 取未绑定原函数（镜引擎 UT：getattr(fn, '__func__', fn) 兼容真包包装）。"""
    fn = cls.__dict__[name]
    return getattr(fn, "__func__", fn)


def call_update(wf, *args, **kwargs):
    """驱动 update_status（async）；参数形状=client.py 现行 wire（四位置实参）或加 who。"""
    return asyncio.run(_orig(type(wf), "update_status")(wf, *args, **kwargs))


def snapshot_of(wf):
    """驱动 snapshot 查询面（工单台/巡检的数据源，用户可感知审计面）。"""
    return _orig(type(wf), "snapshot")(wf)


def blocked_meta(status="dispatched", **extra):
    """blocked 票标准票面（今日实案形：blocked + dispatched + 既有留痕面为空）。"""
    meta = {
        "stage": "arbitrate",
        "stage_state": "blocked",
        "status": status,
        "log": [],
        "pending": [],
        "book_path": None,
        "cross_project_uses": [],
        "updated": 1,
    }
    meta.update(extra)
    return meta


# 拒绝留痕的宽容机械上界（灰盒口径：钉「有界」承诺的数量级，不复制 developer 验收常数）：
# 留痕为数百字符级；畸形载荷（10 万字符级）绝不原样进事件面/查询面。
WHY_BOUND = 1024
LOG_BOUND = 2048
