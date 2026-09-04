#!/usr/bin/env python3
"""lib_dispatch_prompt.py — t260904-03 场景共享夹具（非 sc_ 前缀=共享代码，不登记清单）。

两条派活组装路径的公开渲染入口电池（shared.build_dispatch_prompt /
shared.build_stage_prompt）。Hermetic：零端口零网络零写盘（workspace 缺省走
纯文本主树条款；project 留空 → project_paths 空键即返全 None，roles 回落
DEFAULT_ROLES_DIR 字符串拼接——selfcheck 同款口径，不触 3099）。

电池覆盖 KI-035 退役表全部命中面的对抗输入：标题关键词全家族（掌握/营造/
知识库·review·审校/工单引擎·temporal·dispatch·派活/全组合）+ 畸形输入
（空标题/正则元字符）× workflow 面（dev-lane/content-pipeline/proofread/缺失）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_POC = REPO / "server" / "dsh" / "temporal-poc"
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

import shared  # noqa: E402  （模块级纯常量，导入零 IO）

TITLES = [
    "升级掌握模型",
    "营造建造循环调参",
    "知识库 review 审校口径",
    "工单引擎 temporal dispatch 派活重构",
    "掌握×营造×知识库 全命中组合",
    "（正则元字符）(a*b?[c]) {1,2} ^$|.+\d",
    "",
    "与任何映射关键词无关的朴素标题",
]
WORKFLOWS = ["dev-lane", "content-pipeline", "proofread", ""]

# 知识段公开契约形态：块 1 内缩进的「①-④ 序号 + 知识库：」行（接收 agent 可感知的
# 固定栏目；容忍 ②/③/④ 前缀差异——文案重构不改契约则不红）。
KNOWLEDGE_RE = re.compile(r"^\s*[①②③④] 知识库：.*$")
# prompt 内提及的 docs/ 路径（.md/.json）——死链守护的抽取面（无后缀引用如
# docs/reviews 不入抽取面：那是条款措辞非阅读指派）。
DOCS_PATH_RE = re.compile(r"[\w./-]*docs/[\w./-]+\.(?:md|json)")


def v1_prompt(title, workflow_id="dev-lane", stage="implement", role="developer",
              write_set=None):
    """v1 dispatch 头（build_dispatch_prompt）：返回 (prompt, parts)。"""
    meta = {
        "title": title,
        "workflow_id": workflow_id,
        "stage": stage,
        "write_set": (["server/x.py"] if write_set is None else write_set),
        "workspace": None,   # 主树条款（纯文本，零 IO）
        "project": "",       # 空键 → roles 回落 DEFAULT_ROLES_DIR 字符串
    }
    stage_def = {"name": "实现", "role": role, "acceptance": ["改动落在写集内"], "exit": ""}
    return shared.build_dispatch_prompt("t-scene-1", meta, "", stage_def)


def v2_prompt(title, workflow_id="dev-lane", prev_ctx="", handoffs=None,
              body="把索引化落地。\n多行正文第二行。", spec="规格参考行。"):
    """v2 dispatch-next（build_stage_prompt）：返回 prompt。"""
    stage = shared.Stage(id="implement", name="实现", role="developer",
                         acceptance=("改动落在写集内",))
    meta = {
        "title": title,
        "workflow_id": workflow_id,
        "workspace": None,
        "user_request": body,
        "spec": spec,
        "write_set": ["server/dsh/temporal-poc/shared.py"],
    }
    return shared.build_stage_prompt("t-scene-2", meta, stage, handoffs or [],
                                     "/tmp/scene-stage.json", 0, prev_ctx)


def knowledge_lines(prompt):
    return [ln for ln in prompt.splitlines() if KNOWLEDGE_RE.match(ln)]


def docs_paths(prompt):
    return sorted(set(DOCS_PATH_RE.findall(prompt)))


def v1_battery():
    """(label, prompt) 全电池：workflow×标题 + 段/分工/写集变体。"""
    out = []
    for wid in WORKFLOWS:
        for i, t in enumerate(TITLES):
            out.append(("v1 wid=%r title#%d" % (wid, i), v1_prompt(t, workflow_id=wid)[0]))
    out.append(("v1 content-pipeline/ai-review（段专项条款+审校分工）",
                v1_prompt("知识库 review 审校口径", workflow_id="content-pipeline",
                          stage="ai-review", role="proofread")[0]))
    out.append(("v1 dev-lane/integration_review（验证分工）",
                v1_prompt("工单引擎 temporal dispatch 派活重构", workflow_id="dev-lane",
                          stage="integration_review", role="integration")[0]))
    out.append(("v1 无写集", v1_prompt("朴素标题变体", write_set=[])[0]))
    return out


def v2_battery():
    """(label, prompt) 全电池：workflow×标题 + 打回重派/前段交接变体。"""
    out = []
    for wid in WORKFLOWS:
        for i, t in enumerate(TITLES):
            out.append(("v2 wid=%r title#%d" % (wid, i), v2_prompt(t, workflow_id=wid)))
    out.append(("v2 打回重派（注入 previous_context）",
                v2_prompt("工单引擎 temporal dispatch 派活重构",
                          prev_ctx="【方案审读打回（第 1 轮）】review comments：\n1. 输入必须检查")))
    out.append(("v2 前段交接（含多行 report）",
                v2_prompt("朴素标题变体",
                          handoffs=[{"stage": "review_plan", "report": "## 做了什么\n审了方案。"},
                                    {"stage": "create_plan", "summary": "方案落定"}])))
    return out
