"""t260921-08 场景共享夹具（无 sc_ 前缀=共享代码，不登记场景清单）。

薄夹具层（方案 Commit②）：只加「引文超长软提醒」差异面所需——超长真实行证据树、
围栏消息伪造、桩缝 env、离线活动驱动器。装桩先例=t260901-23/_stub_temporalio
（sys.path 注入共享桩，不复制桩体）；跨票不 import 兄弟票 lib，免耦合。

三态纪律（t260904-12）：exit 0=PASS / 1=FAIL（产品红点名）/ 2=ENV_FAIL（环境缺供点名）。
实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
"""
from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))            # 仓库根
_ENGINE_DIR = os.path.join(_REPO, "server", "engine")      # 引擎模块目录
_STUB_DIR = os.path.join(os.path.dirname(_HERE), "t260901-23")  # 共享 temporalio 桩

# ---------------------------------------------------------------- 超长引文样本行（证据锚=真实文件行）

#: 样本行 238 字符、无空白（机械复核的空白规范化对其恒等，匹配判定无容差干扰）
LONG_LINE = "LONGGUARD-" + "0123456789" * 22 + "-ENDTAIL"
#: 实案字数（t260922-01：findings[5].evidence[1] 引文 227 字 > 上限 200 → 旧码整份拒收）
LONG_QUOTE = LONG_LINE[:227]
LONG_LINE_NO = 1
LONG_REL = "samples/long_line.py"
NORMAL_REL = "samples/normal.py"
NORMAL_LINE = "NORMAL_SAMPLE = 1"


def build_evidence_tree(root):
    """最小证据锚树：一条 238 字真实长行 + 一条普通行（复核「真过/真不过」都有真锚）。"""
    samples = os.path.join(root, "samples")
    os.makedirs(samples, exist_ok=True)
    with open(os.path.join(root, LONG_REL), "w", encoding="utf-8") as f:
        f.write(LONG_LINE + "\n# 第二行（非证据行）\n")
    with open(os.path.join(root, NORMAL_REL), "w", encoding="utf-8") as f:
        f.write(NORMAL_LINE + "\n")
    return root


def incident_findings(empty_quote=False):
    """实案形态三条发现：超长引文条 / 合规引文对照条 / 引文不符对照条。

    三条全部 severity≥med 且 confidence≥0.6——建议门差异只由 verified 面
    决定（验收「生成路径仍只看 verified」的纯对照设计）。

    260928 修（main 红直修）：叙述字段（subject/why/suggestion）改英文。引擎 463a8f7 起装
    「报告面语言闸」（宿主令「report 用英语写」）——agent 自写的叙述字段含 CJK ⇒ 该条被判
    unverified 并追加一条聚合发现（inspection_inspect.mark_non_english）。本场景意图=引文
    超长**软提醒**（截断保前缀、复核仍 verified、建议门只看 verified），与语言闸正交；夹具
    造的是 agent 输出，必须契约内（英文叙述字段）。此前的实测红：截断条被语言闸连带判
    unverified（S3 复核语义面）+ 三条全不开建议票（S4）+ 票面多一条聚合发现（S4 三条面）。
    quote/path 是数据面不译，保持原样。"""
    quote0 = "   " if empty_quote else LONG_QUOTE
    return [
        {"subject": "overlong quote sample: samples/long_line.py:1", "severity": "med",
         "evidence": [{"path": LONG_REL, "line": LONG_LINE_NO, "quote": quote0}],
         "why": "incident shape: one borderline overlong quote must not scrap the whole round",
         "suggestion": "no fix needed; record only", "confidence": 0.9},
        {"subject": "normal quote sample: samples/normal.py:1", "severity": "high",
         "evidence": [{"path": NORMAL_REL, "line": 1, "quote": NORMAL_LINE}],
         "why": "control: a compliant quote is unaffected by the soft warning",
         "suggestion": "no fix needed; record only", "confidence": 0.9},
        {"subject": "quote mismatch sample: samples/normal.py:1", "severity": "med",
         "evidence": [{"path": NORMAL_REL, "line": 1,
                       "quote": "this line of text is not in the sample file"}],
         "why": "control: a failed recheck still degrades with a named reason, never dropped",
         "suggestion": "no fix needed; record only", "confidence": 0.9},
    ]


# ---------------------------------------------------------------- 围栏消息伪造 / 桩缝

def fenced_message(findings, *, n_blocks=1, outer_json_valid=True,
                   preamble="审查完成。"):
    """agent 最终消息文本：末尾恰 n_blocks 块 ```json 围栏。

    n_blocks=0 与 outer_json_valid=False 供硬红对照子用例（围栏缺失 / 围栏内坏 JSON）。"""
    if outer_json_valid:
        body = json.dumps({"findings": findings}, ensure_ascii=False)
    else:
        body = '{"findings": [not-json'
    parts = [preamble + "\n"]
    for _ in range(max(0, n_blocks)):
        parts.append("```json\n%s\n```\n" % body)
    return "".join(parts)


STUB_ENV_NAMES = ("SANDBAR_INSPECT_STUB", "SANDBAR_INSPECT_STUB_FILE",
                  "SANDBAR_INSPECTION_DIR")


def stub_env(stub_file_path):
    """桩模式 env（缝名单点：SANDBAR_INSPECT_STUB=1 + SANDBAR_INSPECT_STUB_FILE）。"""
    return {"SANDBAR_INSPECT_STUB": "1", "SANDBAR_INSPECT_STUB_FILE": stub_file_path}


def write_stub_file(workdir, name, text):
    path = os.path.join(workdir, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


# ---------------------------------------------------------------- 离线活动驱动（共享桩 + 引擎模块）

_STUB_READY = False


def load_engine_modules():
    """先装共享 temporalio 桩（先于一切引擎导入）再导引擎模块。

    引擎树缺失/桩目录缺失 → ImportError，由场景转 ENV_FAIL（环境缺供点名）。

    t260921-03 起 install() 改条件安装（真包可导入就不装桩，防同进程污染真包语义
    的测试）——引擎 venv 里真 temporalio 在场时本场景会跑在真包上，而引擎 inspect
    桩路径的 `activity.heartbeat(...)` 在活动上下文外必然 RuntimeError。本场景是
    **独立进程**（不存在 main 侧担心的同进程污染），故真包在场时把 heartbeat 在
    进程内显式 no-op 并点名（离线桩模式本无活动上下文，该调用是纯运行时信号；
    只动本进程，不碰引擎代码、不碰共享桩）。"""
    global _STUB_READY
    if not os.path.isdir(_STUB_DIR):
        raise ImportError("共享 temporalio 桩目录缺失：%s" % _STUB_DIR)
    if not os.path.isdir(_ENGINE_DIR):
        raise ImportError("引擎模块目录缺失：%s" % _ENGINE_DIR)
    if _STUB_DIR not in sys.path:
        sys.path.insert(0, _STUB_DIR)
    if not _STUB_READY:
        import _stub_temporalio  # noqa: E402
        _stub_temporalio.install()
        _STUB_READY = True
    if _ENGINE_DIR not in sys.path:
        sys.path.insert(0, _ENGINE_DIR)
    _tm = sys.modules.get("temporalio")
    if _tm is not None and getattr(_tm, "__file__", None):
        # 真包在场（install 按新语义跳桩）：离线桩路径的 heartbeat 无上下文可用，
        # 进程内 no-op（点名，不静默）；系统裸解释器（无真包）走桩，不进此分支。
        # 注意 activity 是懒加载子模块——必须先显式导入再补丁，引擎侧
        # `from temporalio import activity` 绑定的才是同一个已补丁的模块对象。
        print("note: 真 temporalio 在场（t260921-03 条件安装），离线桩路径 "
              "activity.heartbeat 进程内 no-op（活动上下文信号，桩模式无此上下文）")
        import importlib
        _act = importlib.import_module("temporalio.activity")
        _act.heartbeat = lambda *_a, **_k: None
    import activities  # noqa: E402
    import agent_activities  # noqa: E402
    import inspection_flow  # noqa: E402
    import inspection_inspect  # noqa: E402
    return activities, agent_activities, inspection_inspect, inspection_flow


def run_coro(coro):
    import asyncio
    return asyncio.run(coro)


# ---------------------------------------------------------------- 活动参构造

def inspect_args(instance, period, base, ledger_dir, **extra):
    """run_inspection_inspect 活动参（桩路径所需最小语义面 + 台账目录显式注入）。"""
    d = {
        "ticket_id": "t-%s-%s" % (instance, period),
        "instance_id": instance, "period": period,
        "face": "test", "inspect_profile": "",
        "base_dir": base, "base_head": "",
        "max_findings": 40, "timeout_sec": 0,
        "ledger_dir": ledger_dir,
    }
    d.update(extra)
    return d


def verify_args(instance, period, base, findings, ledger_dir):
    """verify_inspection_findings 活动参（inspect 回执的 findings 原样进复核链）。"""
    return {
        "instance_id": instance, "period": period,
        "base_dir": base, "findings": findings,
        "max_findings": 40, "ledger_dir": ledger_dir,
    }
