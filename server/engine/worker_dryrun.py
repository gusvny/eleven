"""worker_dryrun —— 中央工人「可启动」注册面 dry-run（KI-121，t260925-16）。

为什么存在：260925 实案——项目外置模板（t260924-04 加载口）的段 id 与引擎退役段
活动同名，worker 注册期裸 ValueError，中央工人起不来，且合并期 pytest 测不到。
本入口把「工人能起来吗」变成秒级机械探针：按 worker.py 同源路径导入注册表（含项目
外置模板合并），断言
  ① 活动名唯一（temporalio 注册定义名口径，撞名=点名双方来源）；
  ② 工作流定义名唯一；
  ③ 外置模板模块装载单例（module-identity 去重面：每个装载名恰一个模块对象）。
不连 server、不 Client.connect、不起任何进程外资源——纯导入＋注册表断言，可进
合并闸（verify code 道的 pytest 用例即包本入口）与运维重启前预检。

用法：
  server/engine/.venv/bin/python server/engine/worker_dryrun.py
绿=exit 0，stdout 一行 JSON 摘要；红=exit 1，stdout 纯文本点名冲突（不产 JSON 摘要行，
stderr/JSON 点名冲突。环境变量 SANDBAR_PROJECTS_DIR 可注入注册根（测试自持面）。
"""

from __future__ import annotations

import json
import os
import sys
import pathlib

_ENGINE_DIR = pathlib.Path(__file__).resolve().parent
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))


def _workflow_registered_name(cls) -> str:
    d = getattr(cls, "__temporal_workflow_definition", None)
    return getattr(d, "name", None) or getattr(cls, "__name__", repr(cls))


def run_dryrun() -> dict:
    """跑全套注册面断言。绿=返回摘要 dict；红=raise ValueError（点名冲突）。
    断言实现单源在 worker.compose_worker_activities（与真实 worker 启动同一条路径，
    不另造一份判据——闸面测的就是工人在跑的代码）。"""
    import worker  # 同源导入：worker.py 已拉起 activities/agent_activities/workflows(_v2)

    acts = worker.compose_worker_activities(worker.PROJECT_TEMPLATE_STAGE_IDS)

    # ② 工作流定义名唯一（同口径防线：撞名模板类同样会让注册期崩）
    seen_wf = {}
    for cls in list(worker.ALL_WORKFLOWS) + list(worker.ALL_WORKFLOWS_V2):
        n = _workflow_registered_name(cls)
        src = getattr(cls, "__module__", "?")
        if n in seen_wf:
            raise ValueError("工作流定义名撞车（dry-run）：%s 已由 %s 注册，再来件 %s"
                             % (n, seen_wf[n], src))
        seen_wf[n] = src

    # ③ 外置模板模块装载单例：装载名在 sys.modules 恰一个对象，且模板类归属它
    ext = {}
    import workflows_v2 as _wv
    for tid, mod_name in sorted(_wv.PROJECT_TEMPLATE_MODULE_NAMES.items()):
        mod = sys.modules.get(mod_name)
        if mod is None:
            raise ValueError("外置模板模块未装载（dry-run）：%s（模板 %s）" % (mod_name, tid))
        cls = _wv.TEMPLATE_CLASSES.get(tid)
        cls_mod = sys.modules.get(getattr(cls, "__module__", ""))
        if cls_mod is not mod:
            raise ValueError("外置模板类与装载模块身份分裂（dry-run）：模板 %s 类在 %s，"
                             "装载名 %s 指向另一对象" % (tid, getattr(cls, "__module__", "?"), mod_name))
        ext[tid] = mod_name

    from shared import PROJECT_TEMPLATE_REJECTIONS, project_template_rejection_note
    # 加载口拒收在场=dry-run 红（fail-loud 点名）：模板级拒收虽不炸工人，但「声明了
    # 却跑不了」必须显性可见，不得静默当绿——闸据此把这类缺陷挡在合并前。
    if PROJECT_TEMPLATE_REJECTIONS:
        raise ValueError("加载口拒收在场（dry-run 红，不静默）："
                         + project_template_rejection_note())
    return {
        "ok": True,
        "activities": len(acts),
        "workflows": len(seen_wf),
        "external_templates": ext,
        "task_queues": "unchecked (dry-run does not touch the network)",
        "loader_rejections": 0,
    }


def main() -> int:
    try:
        summary = run_dryrun()
    except Exception as e:
        # 红态不产 JSON 摘要行（绿态 { 行=机器判定面；红态只留点名文案＋exit 1，
        # 机器按退出码判红，混读面不被污染——场景 A2 契约）
        print("worker-dryrun: FAIL %s: %s" % (type(e).__name__, e))
        return 1
    print(json.dumps(summary, ensure_ascii=False).encode("utf-8", "backslashreplace").decode("utf-8"))
    return 0


if __name__ == "__main__":
    # 注册根注入点：SANDBAR_PROJECTS_DIR 每次现读（shared.registry_root 同款语义），
    # 测试桩根/隔离台同路可用，不读死路径。
    _ = os.environ.get("SANDBAR_PROJECTS_DIR")
    sys.exit(main())
