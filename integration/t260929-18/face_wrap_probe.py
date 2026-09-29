# -*- coding: utf-8 -*-
"""face_wrap_probe — t260929-18 真实包裹路探针桩模块（integration 场景专用）。

纪律（与 selfcheck_graceful_stop_probe 同款）：temporalio workflow 沙箱只重导入
defn 所属模块，所以桩独立成模块、顶层仅「imports + defn」；imports 面包在
imports_passed_through 内（shared 与生产同源）。

零 IO 零进程零模型：活动本体是内存 stub，异常经**真实 SDK worker 执行活动**抛出，
由真实 Temporal 服务端包成 ActivityError——工作流侧捕到的链就是生产链形（本票
验收明确禁止手搓 ActivityError+cause 顶替真路）。三个模式对应三个故障面：
  raise             活动 raise RuntimeError(可行动中文 detail)＝t260929-15 同形；
  empty_msg         活动 raise RuntimeError("")＝链在但零消息（不可得面）；
  worker_terminated 活动 raise ApplicationError(type=worker_terminated)＝t260916-29
                    契约的反向锁面（专用文案必须赢过链挖掘）。
"""

from datetime import timedelta

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from shared import format_agent_stage_failure  # noqa: F401

# 可行动 detail（与 t260929-15 形同：点名文件、给补救路径；措辞自造不钉原文）。
ACTIONABLE_DETAIL = ("结果文件损坏不可读：server/engine/data/result-t260929-15.json"
                     "（移开留证后发 retry_qc 重写该段）")
WORKER_TERM_MSG = "worker shutdown cancelled the in-flight activity"


@workflow.defn
class FaceProbeWorkflow:
    """最小探针工作流：跑一次 stub 活动，异常捕后走生产唯一出口
    format_agent_stage_failure（生产 catch 位同款），回传文案与外层类型。"""

    @workflow.run
    async def run(self, inp: dict) -> dict:
        try:
            await workflow.execute_activity(
                "face_probe_activity", inp["mode"],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=1))
            return {"status": "ok"}
        except Exception as e:  # noqa: BLE001 —— 探针本身就是要捕
            return {"status": "failed",
                    "exc_type": type(e).__name__,
                    "text": format_agent_stage_failure(
                        inp["ticket"], inp["stage"], e)}


@activity.defn
async def face_probe_activity(mode: str) -> dict:
    """stub 活动本体：按模式抛对应异常（真实执行路径，SDK 真包裹）。"""
    if mode == "raise":
        raise RuntimeError(ACTIONABLE_DETAIL)
    if mode == "empty_msg":
        raise RuntimeError("")
    if mode == "worker_terminated":
        raise ApplicationError(WORKER_TERM_MSG, type="worker_terminated",
                               non_retryable=True)
    return {"ok": True}
