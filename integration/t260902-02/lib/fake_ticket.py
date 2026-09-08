# -*- coding: utf-8 -*-
"""假 DevLaneWorkflow（t260902-02 e2e 族造票用）。

为什么单独一个文件：Temporal 的 workflow 沙箱会复导入定义 workflow 的模块，
场景脚本作为 __main__ 会被整文件重跑一遍——模块级的 shared/fixture 加载
（含沙箱禁用的 pathlib.Path.resolve、subprocess）会在复导入时炸掉校验。
把这个类放进干净的独立模块，沙箱只复导入本文件（只有 temporalio import
和类定义，无副作用），场景脚本重跑不再发生。

类载荷由场景注入（fixture 模式），保持两个场景各自不同的行为：
  - t05 prune：简单直返，mode 忽略；
  - t06 archive-legacy：mode="hang" 时挂起（模拟 running 票），等场景置
    _stop 收场。
"""
from temporalio import workflow

__all__ = ["FakeTicket"]


@workflow.defn(name="DevLaneWorkflow")
class FakeTicket:
    def __init__(self):
        self._stop = False

    @workflow.run
    async def run(self, req: dict) -> dict:
        # req = {"mode": ..., "payload": ...}；1.18 SDK 的 start_workflow 只收单个
        # 位置参数，合成一个 dict 传
        if (req or {}).get("mode") == "hang":
            try:
                await workflow.wait_condition(lambda: self._stop, timeout=600)
            except Exception:
                pass
        return (req or {}).get("payload") or {}
