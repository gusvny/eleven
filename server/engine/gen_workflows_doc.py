#!/usr/bin/env python3
"""gen_workflows_doc — generate the workflows/*.yaml reference snapshots from
the STAGES of the template workflow classes.

M11 v2 (t260822-m11, templates as code): the source of truth for a template is
CODE (the <Class>.STAGES class attribute in engine/<module>.py). The
workflows/*.yaml files are downgraded to human-readable reference documents
generated from the class definitions. To change a template, edit the class and
re-run this generator. Do NOT hand-edit the yaml files (a re-run overwrites
them).

Usage (from the engine directory):
    .venv/bin/python gen_workflows_doc.py            # full generation + read-back check
    .venv/bin/python gen_workflows_doc.py --check    # check only: yaml matches code (drift = red)

The yaml files still feed the read-only template list/show in
server/tools/workflow.py (lane diagrams / create derivation). The schema aligns
with its yaml-subset parser; this generator carries a read-back check to catch
drift.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List

POC = Path(__file__).resolve().parent
REPO = POC.parents[1]
OUT_DIR = REPO / "server" / "workflows"

from workflows_v2 import TEMPLATE_CLASSES  # noqa: E402
from shared import PART_KINDS  # noqa: E402

HEADER = (
    "# ⚠️ 真源=代码，勿手改 —— M11 v2 模版即代码（t260822-m11）。\n"
    "# 本文件由 server/engine/gen_workflows_doc.py 从 {module}.py 的\n"
    "# {cls}.STAGES 生成；改模版=改类定义并重跑生成器（重跑即覆盖手改）。\n"
)


def _q(s: str) -> str:
    """Quote every string scalar with double quotes (the workflow.py subset
    parser supports this; it avoids ambiguity from ':' or ' #' inside values)."""
    if '"' in s:
        raise ValueError("值内不允许双引号（子集解析器限制）: %r" % s)
    return '"%s"' % s


def render(tid: str) -> str:
    cls = TEMPLATE_CLASSES[tid]
    module = cls.__module__
    lines: List[str] = [
        HEADER.format(module=module, cls=cls.__name__).rstrip("\n"),
        "id: %s" % tid,
        "name: %s" % _q(cls.TEMPLATE_NAME),
        "lane: %s" % cls.TEMPLATE_LANE,
    ]
    if cls.TEMPLATE_WORKSPACE_DIR:
        lines.append("workspace: dir")
    lines.append("description: %s" % _q(cls.TEMPLATE_DESC))
    lines.append("stages:")
    for st in cls.STAGES:
        lines.append("  - id: %s" % st.id)
        lines.append("    role: %s" % st.role)
        lines.append("    name: %s" % _q(st.name))
        if st.desc:
            lines.append("    desc: %s" % _q(st.desc))
        if st.exit:
            lines.append("    exit: %s" % st.exit)
        if st.fanout:
            lines.append("    fanout: %d" % st.fanout)
        if st.revision_to:
            lines.append("    revision_to: %s" % st.revision_to)
        if st.next:
            lines.append("    next: %s" % st.next)
        # Executor-part declaration (t260828-01), enforced here: any stage
        # missing parts or using a value outside the enum fails the render.
        # "Every stage declares parts" is checked mechanically by this
        # generator, not by human discipline.
        if not st.parts:
            raise ValueError("%s.%s 缺 parts 执行主体声明（agent/script/human 可组合）"
                             % (cls.__name__, st.id))
        bad = [p for p in st.parts if p not in PART_KINDS]
        if bad:
            raise ValueError("%s.%s parts 含非法值 %r（可用: %s）"
                             % (cls.__name__, st.id, bad, "/".join(PART_KINDS)))
        lines.append("    parts:")
        for p in st.parts:
            lines.append("      - %s" % p)
        if st.gate is not None:
            import json as _json
            lines.append("    # 脚本门（代码内 Stage.gate，仅注释展示）: %s %s"
                         % (st.gate.tool, _json.dumps(st.gate.args, ensure_ascii=False)))
        if not st.agent:
            lines.append("    # 纯脚本门段（agent=False：无 agent 活动，只跑门）")
        if st.acceptance:
            lines.append("    acceptance:")
            for it in st.acceptance:
                lines.append("      - %s" % _q(it))
    return "\n".join(lines) + "\n"


def _roundtrip_check() -> List[str]:
    """Read-back check: the generated yaml must pass the subset parse and the
    structural validation of server/tools/workflow.py."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_wf_tool", REPO / "server" / "tools" / "workflow.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    errors: List[str] = []
    for tid in TEMPLATE_CLASSES:
        try:
            mod.load(OUT_DIR / (tid + ".yaml"))
        except Exception as e:
            errors.append("%s: %s" % (tid, e))
    return errors


def main() -> int:
    ap = argparse.ArgumentParser(description="从模版类生成 workflows/*.yaml 参考快照")
    ap.add_argument("--check", action="store_true", help="只校验 yaml 与代码一致（漂移=红）")
    a = ap.parse_args()

    if a.check:
        drift = []
        for tid in TEMPLATE_CLASSES:
            p = OUT_DIR / (tid + ".yaml")
            want = render(tid)
            have = p.read_text("utf-8") if p.is_file() else ""
            if have != want:
                drift.append(tid)
        if drift:
            print("漂移（yaml ≠ 代码生成物）：%s——重跑 gen_workflows_doc.py" % "、".join(drift))
            return 1
        errs = _roundtrip_check()
        if errs:
            print("回读校验红：%s" % "；".join(errs))
            return 1
        print("check 绿：yaml 与代码一致且过 workflow.py 校验")
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for tid in TEMPLATE_CLASSES:
        p = OUT_DIR / (tid + ".yaml")
        p.write_text(render(tid), "utf-8")
        print("生成 %s（%s）" % (p, TEMPLATE_CLASSES[tid].__name__))
    errs = _roundtrip_check()
    if errs:
        print("回读校验红：%s" % "；".join(errs))
        return 1
    print("回读校验绿（均过 server/tools/workflow.py 子集解析+结构校验）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
