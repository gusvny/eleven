"""t260904-03（KI-035）派活上下文索引化——派活头恒定知识库规约回归锁。

锁三件事：
1. 两条组装路径（build_dispatch_prompt / build_stage_prompt）的派活头都含恒定
   知识库规约（docs/README.md 目录锚点），旧 WORKFLOW_CONTEXT/TITLE_CONTEXT_RULES
   的全部取值一个都不再出现（负断言封死回归面）；
2. 派活指令行数恒定：不随 workflow_id/title（即 docs 多寡/关键词命中）变化
   （控制变量钉死：除 workflow_id/title 外其余输入全同，title 单行）；
3. 结算审计句在位：两条路径的结算/note 要求处都含「参考 docs 清单」。

零 IO 纪律：project 留空走 DEFAULT_ROLES_DIR 回落；禁网络/真 Temporal/真 git。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared import Stage, build_dispatch_prompt, build_stage_prompt  # noqa: E402

# 旧两表全部取值（WORKFLOW_CONTEXT 2 项 + TITLE_CONTEXT_RULES 5 项，去重后 7 路径）
# ——负断言清单，一个不漏；另兜旧③行的措辞本身与裸名（防换路径前缀复活）。
RETIRED_DOC_VALUES = (
    "docs/design/deepseek_harness_and_temporal_based_multi-agent_mechanism.md",
    "docs/design/平台架构设计.md",
    "docs/design/工单工作流台设计.md",
    "docs/design/知识库设计.md",
    "docs/design/掌握模型设计.md",
    "docs/design/营造建造循环设计.md",
    "pipeline/proposals/README.md",
    "deepseek_harness_and_temporal_based",
    "推导设计文档",
)

STAGE_DEF = {"name": "实现", "role": "developer", "acceptance": ["写集内"], "exit": ""}
ST = Stage(id="implement", name="实现", role="developer", acceptance=("写集内",))
RFILE = "/tmp/t-t260904-03-r.json"


def _meta(**over):
    """基线 meta：中性标题（不含旧表任何关键词——负断言的前提）。"""
    base = {
        "title": "中性标题",
        "workflow_id": "dev-lane",
        "template_id": "dev-lane",
        "stage": "implement",
        "project": "",
        "user_request": "正文单行",
        "write_set": ["server/engine/shared.py"],
        "workspace": {"type": "dir", "path": "/tmp/t-t260904-03-ws"},
    }
    base.update(over)
    return base


def _dispatch(meta):
    return build_dispatch_prompt("t-x", meta, "worktree", STAGE_DEF)


def _stage(meta):
    return build_stage_prompt("t-x", meta, ST, [], RFILE, 1, "")


def test_dispatch_header_constant_kb_rule():
    p, parts = _dispatch(_meta())
    assert "③ 知识库：docs/ = 定稿知识库，目录=docs/README.md" in p
    # 保底两项不降级：CLAUDE.md + 岗位说明书（role_doc）
    assert "① CLAUDE.md" in p and "server/roles/developer.md" in p
    # 结算审计句（KI-035：integration merge 关卡核对文档漂移的观测点）
    assert "参考 docs 清单（读过哪些路径；空则写无）" in p
    for v in RETIRED_DOC_VALUES:
        assert v not in p, v
    # 结构化透出不再夹带推导 docs（parts.context 只剩保底两项）
    assert parts["context"] == ["CLAUDE.md", "server/roles/developer.md"]


def test_stage_header_constant_kb_rule():
    s = _stage(_meta())
    assert "② 知识库：docs/ = 定稿知识库，目录=docs/README.md" in s
    assert "① CLAUDE.md" in s
    # 块内恒定②不波及顶层编号（正文/写集序号原样）
    assert "2. 工单正文" in s and "3. 写集" in s
    # 交付契约里的结算审计句
    assert "参考 docs 清单（读过哪些路径；空则写无）" in s
    for v in RETIRED_DOC_VALUES:
        assert v not in s, v


def test_prompt_line_count_constant():
    """行数恒定（票面验收）：控制变量钉死——两组除 workflow_id/title 外全同。

    旧制下 rich 组会命中 WORKFLOW_CONTEXT(content-pipeline)+TITLE_CONTEXT_RULES
    全部 5 条规则多出必读行；新制两组逐行同构。title 保持单行。
    """
    rich = _meta(title="掌握模型营造建造知识库工单引擎 temporal 派活",
                 workflow_id="content-pipeline")
    plain = _meta(title="中性标题", workflow_id="dev-lane")
    assert _dispatch(rich)[0].count("\n") == _dispatch(plain)[0].count("\n")
    assert _stage(rich).count("\n") == _stage(plain).count("\n")
    # 两条路径的规约行去掉序号前缀后逐字相同（同一段文案，不漂移）
    dl = [ln for ln in _dispatch(plain)[0].splitlines() if "定稿知识库" in ln][0]
    sl = [ln for ln in _stage(plain).splitlines() if "定稿知识库" in ln][0]
    assert dl.split("：", 1)[1] == sl.split("：", 1)[1]


def test_degenerate_meta_still_renders():
    """畸形输入（消费外部输入纪律）：空标题/正则元字符/超长/多行——不炸且恒含目录锚点。"""
    for title in ["", "(((((掌握", "标" * 200, "多\n行\n标题"]:
        p, _ = _dispatch(_meta(title=title))
        assert "docs/README.md" in p
    m = _meta(title="")
    m.pop("workflow_id")
    m.pop("template_id")
    assert "docs/README.md" in _stage(m)
