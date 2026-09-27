#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""KI-143 反向锁：回放器必须能**校验通过**整份 workflow 集合（含项目外置模板）。

实案（260927，integration 岗登记）：`replay_check` 对所有票一律 `ok=false`，错误文案是
temporalio SDK 的掩码句 `UnboundLocalError: local variable 'pusher' referenced before
assignment`（SDK `_replayer.py:334` 的 `finally: pusher.close()`）——真因被吞掉，实际是：

    RuntimeError: Failed validating workflow ContentStudioWorkflow
      ← ModuleNotFoundError: No module named 'sandbar_ext_nusuyou_content_studio'

外置模板类是**运行期按名 importlib 装载**的（`project_templates.py` 生成别名
`sandbar_ext_<key>_<stem>`），生产 worker 靠 `SandboxedWorkflowRunner(
restrictions=...with_passthrough_modules(*PROJECT_TEMPLATE_PASSTHROUGH_MODULES))` 让
sandbox 按名解析；而 `Replayer` 的 `workflow_runner` **缺省就是 SandboxedWorkflowRunner**
（旧注释「unsandboxed default」是错的），回放侧没注入 passthrough ⇒ 校验必失败 ⇒
整份回放全红，且文案把人引向 SDK 缺陷。

本锁用「空 history 回放」这一最小动作把**校验阶段**单独钉住：空 history 走到 core 后
必然以别的异常（如缺少 workflow_id）收场，因此
  · 见到 `UnboundLocalError ... 'pusher'` ⇒ 校验失败（本缺陷回归）；
  · 见到任何其它异常 ⇒ 回放 worker 已构造成功（校验过了）=通过。
外加一条源码锚：passthrough 必须取自 `workflows_v2.PROJECT_TEMPLATE_PASSTHROUGH_MODULES`
这个**单点**（不许另造第二份清单，也不许退回 SDK 缺省 runner）。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
POC = REPO / "server" / "engine"
if str(POC) not in sys.path:
    sys.path.insert(0, str(POC))

REPLAY_CHECK = POC / "replay_check.py"


def _load_replay_check():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_replay_check_under_test", REPLAY_CHECK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)          # 顶层只做 import + 解释器探测，无网络/无连接
    return mod


def test_replayer_validates_whole_workflow_set():
    """核心锁：回放器构造（=workflow 校验）必须通过——被掩码的 UnboundLocalError 不许出现。"""
    rc = _load_replay_check()
    from temporalio.api.history.v1 import History

    async def _run():
        r = rc._replayer()
        try:
            await r.replay_workflow(History())
        except UnboundLocalError as e:     # SDK 掩码句：真因=校验失败
            return "unbound", str(e)
        except Exception as e:             # 空 history 的预期收场：说明 worker 已建起来
            return "ok", "%s: %s" % (type(e).__name__, str(e)[:120])
        return "ok", "replay 正常返回"

    kind, detail = asyncio.run(_run())
    assert kind == "ok", ("回放器校验失败（KI-143 回归）：%s\n"
                          "真因方向=外置模板模块在回放沙箱不可导入（passthrough 未注入）" % detail)


def test_passthrough_single_source_and_wired():
    """源码锚：passthrough 取自 workflows_v2 的单点真源，且真的传给了 Replayer。"""
    src = REPLAY_CHECK.read_text(encoding="utf-8")
    assert "PROJECT_TEMPLATE_PASSTHROUGH_MODULES" in src, \
        "回放器必须复用 worker 的同一个 passthrough 真源（不许另造清单）"
    assert "with_passthrough_modules" in src, "必须真的注入 sandbox passthrough"
    assert "workflow_runner" in src, "必须显式给 Replayer 传 runner（SDK 缺省=sandboxed）"
    # 旧错注释不许复活（「Replayer default = unsandboxed」是事实错误，正是它让缺失的
    # passthrough 显得不必写）
    assert "UnsandboxedWorkflowRunner (Replayer default)" not in src


def test_masked_error_text_names_the_real_direction():
    """对外文案：SDK 掩码句必须附带「真因方向」提示，不许把 SDK 缺陷当结论。"""
    src = REPLAY_CHECK.read_text(encoding="utf-8")
    assert "unbound" in src.lower() or "掩码" in src, "掩码句要在源码里被点名"
    assert "pusher" in src, "掩码特征串要在源码里被识别"


if __name__ == "__main__":                 # 允许单文件直跑（诊断面）
    sys.exit(pytest.main([__file__, "-q"]))
