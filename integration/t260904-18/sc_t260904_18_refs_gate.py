#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260904-18 场景①：建工单背景文件闸（门①，灰盒 L2/L3）。

intent（守护的用户可感知行为/合同）：
- 宿主令「没提交的 note 不让建工单」（260904）+ 知识库设计 §1 工单引用铁律
  「背景长文档全文引用路径＋必须已提交且干净（HEAD 态）；未提交/带脏改=拒建工单」：
  票面 refs 引用未提交背景文件（未跟踪 / 暂存未提交 / 工作区脏改三分类）→ 建单即拒，
  报错逐个点名文件与原因分类——「已跟踪≠已提交」（git add 暂存新文件也拒）；
- 畸形引用（绝对路径 / 含 .. / 非列表）拒收并点名，不静默清洗；
- 拒收路径零 Temporal 接触：refs 校验接线在 cmd_ticket_start 的首个 _connect() 之前
  （源码序锁）——闸在连通引擎前就拦住，老票无 refs 字段照常（存量不追溯，backlog 口径）；
- 闸函数两查行为（已提交=ls-files / 干净=status --porcelain）经真 git 夹具仓驱动，
  回执形状不锚定（布尔/元组/dict/字符串/异常皆容错解释）——锚「拒+点名+分类」行为。

与相邻场景 intent 分界：t260904-02-ticket-start-anchor 守 project 锚定硬闸（KI-032），
本条守背景文件引用闸；与 developer L1（engine/tests 纯函数白盒）不同层——
本条含 cmd_ticket_start 入口装配面与真 git HEAD 态分类。

实现落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；
temporalio 缺失=ENV_FAIL 点名（入口装配腿），stdlib 闸行为腿照跑。
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib_t260904_18 import (  # noqa: E402
    REPO, POC, check, summary, env_fail, temporalio_available,
    gate_result, call_gate, git, build_bg_refs_repo,
)

sys.path.insert(0, str(POC))
import shared  # noqa: E402  纯标准库依赖面

# ---------- 夹具：真 git 仓（HEAD 态三分类）+ 隔离项目注册表 ----------
tmp_repo = build_bg_refs_repo()
regdir = Path(tempfile.mkdtemp(prefix="t260904-18-reg-"))
(regdir / "fixproj").mkdir()
# 注册条目=契约① YAML 子集（parse_project_file 手写解析器不认 JSON）：
#   schema: v1 / project: / - key/name/dirs 列表
(regdir / "fixproj" / "project.yaml").write_text(
    "schema: v1\nproject:\n  - key: fixproj\n    name: 场景夹具项目\n    dirs:\n"
    "      - %s\n" % tmp_repo, encoding="utf-8")
# 注册表 env 覆盖（shared.projects_dir 调用时读，KI-032 同源装载器；隔离真注册表）
os.environ["SANDBAR_PROJECTS_DIR"] = str(regdir)

try:
    src_client = (POC / "client.py").read_text(encoding="utf-8")

    # ---------- 源码契约锁（处处可跑） ----------
    check("S1 闸函数单点在 shared（validate_background_refs 在场）",
          "def validate_background_refs(" in (POC / "shared.py").read_text(encoding="utf-8"))
    i_def = src_client.find("async def cmd_ticket_start")
    i_val = src_client.find("validate_background_refs", i_def if i_def >= 0 else 0)
    i_conn0 = src_client.find("await _connect()", i_def if i_def >= 0 else 0)
    check("S2 refs 校验接线在 cmd_ticket_start 内、先于首个 _connect（拒收路径零 Temporal 接触）",
          i_def >= 0 and i_val >= 0 and i_conn0 >= 0 and i_val < i_conn0,
          "i_def=%d i_val=%d i_conn=%d" % (i_def, i_val, i_conn0))
    check("S3 建单入口带 refs 参数（cmd_ticket_start 取 args refs）",
          i_val >= 0 and 'args.get("refs")' in src_client[i_def:i_conn0])

    # ---------- 闸函数行为腿（真 git HEAD 态；stdlib 处处可跑） ----------
    vb = getattr(shared, "validate_background_refs", None)
    check("P0 被测承诺面在场（shared.validate_background_refs）", vb is not None)
    if vb is not None:
        ok, msg = call_gate(vb, ["notes/bg.md"], str(tmp_repo))
        check("P1 合法引用（已提交且干净）→ 放行", ok is True, msg)
        ok, msg = call_gate(vb, ["docs/other.md"], str(tmp_repo))
        check("P2 工作区脏改 → 拒且点名 docs/other.md",
              ok is False and "docs/other.md" in msg, "msg=%r" % msg[:200])
        ok, msg = call_gate(vb, ["notes/staged.md"], str(tmp_repo))
        check("P3 暂存未提交（已跟踪≠已提交）→ 拒且点名 notes/staged.md",
              ok is False and "notes/staged.md" in msg, "msg=%r" % msg[:200])
        ok, msg = call_gate(vb, ["notes/missing.md"], str(tmp_repo))
        check("P4 不存在文件 → 拒且点名", ok is False and "notes/missing.md" in msg,
              "msg=%r" % msg[:200])
        ok, msg = call_gate(vb, ["notes/bg.md", "docs/other.md"], str(tmp_repo))
        check("P5 混合清单拒时合法件也一并点名原因（拒收文案点名文件）",
              ok is False and "docs/other.md" in msg, "msg=%r" % msg[:200])
        ok, msg = call_gate(vb, ["/abs/bg.md"], str(tmp_repo))
        check("P6 绝对路径 → 拒", ok is False, "msg=%r" % msg[:200])
        ok, msg = call_gate(vb, ["../escape.md"], str(tmp_repo))
        check("P7 含 .. 越界形态 → 拒", ok is False, "msg=%r" % msg[:200])
        ok, msg = call_gate(vb, "notes/bg.md", str(tmp_repo))
        check("P8 非列表（字符串会被迭代成假护栏）→ 拒", ok is False, "msg=%r" % msg[:200])

    # ---------- 入口装配腿（temporalio 面） ----------
    if not temporalio_available():
        env_fail("temporalio 不可用（本泳道无 venv）：cmd_ticket_start 入口装配腿不可执行"
                 "——stdlib 闸行为腿与源码序锁已在本场跑完；arbitrate/merge 期 venv 环境必须全绿")
    else:
        import client  # noqa: E402  temporalio 依赖面
        # 保险丝：入口腿一律指向死端口——即使实现把校验错接到 _connect 之后，
        # 也绝无真 Temporal 接触/真工单落引擎（对抗面自保护）
        client.TARGET_HOST = "127.0.0.1:1"
        HAVE_GATE = ("validate_background_refs" in src_client)

        async def start_with(refs):
            args = {"ticket_id": "t26090418scgate", "template_id": "dev-lane",
                    "project": "fixproj", "title": "场景夹具票（闸面验证，不落引擎）",
                    "write_set": ["notes/bg.md"]}
            if refs is not None:
                args["refs"] = refs
            return await client.cmd_ticket_start(args)

        if HAVE_GATE:
            res = asyncio.run(start_with(["docs/other.md", "notes/staged.md"]))
            err = str(res.get("error") or "")
            check("L1 未提交引用（脏改+暂存）建单被拒且逐个点名",
                  res.get("ok") is False and "docs/other.md" in err and "notes/staged.md" in err,
                  "res=%r" % ({"ok": res.get("ok"), "error": err[:200]},))
            res = asyncio.run(start_with("/abs/x.md"))
            err = str(res.get("error") or "")
            check("L2 非列表 refs 建单被拒（入口即拒，不透传畸形）",
                  res.get("ok") is False and "/abs/x.md" in err, "err=%r" % err[:200])
            res = asyncio.run(start_with(["../escape.md"]))
            err = str(res.get("error") or "")
            check("L3 越界引用建单被拒且点名", res.get("ok") is False and "escape.md" in err,
                  "err=%r" % err[:200])
        else:
            check("L0 被测承诺面在场（client refs 闸接线）→ 入口腿可跑", False,
                  "client.py 未接 validate_background_refs（TDD 红属预期）")

    # 缺省不追溯（存量在飞票无 refs 照常）不设独立拒收腿：无 refs 时流程越过闸继续，
    # 行为在真票面验证——本场景不为此制造真工单（对抗面不落引擎副作用）。
finally:
    shutil.rmtree(tmp_repo, ignore_errors=True)
    shutil.rmtree(regdir, ignore_errors=True)

sys.exit(summary())
