#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_discipline_read_not_run.py — developer 段「读不算跑」执法旅程回归
（t261009-36，事故 t261008-47）。

intent（用户可感知契约）：developer 段只**读**集成文件绝不停摆工单（宿主令
260921 红线禁的是「跑」，读取在放行清单内）；事故 261009：t261008-47 因
`bash -lc "sed -n 70p integration/baselines/lane-stages-chain.mjs"` 被
integration_discipline 执法器误判为跑集成（bash `-lc` 组合短旗时嵌套命令串
从 flag 分支跌落到裸 token 入口匹配，接收该路径的只读程序从未被查询），工单
被红打回。本场景锁全链旅程级行为：真 zstd 会话档 × 真 agent 活动入口（幂等
缓存挂点，零 spawn 零 Temporal 零网络）× 结果文件落盘——

  R 读放行（事故回归）：
    R1 事故原文逐字（bash -lc "sed -n 70p integration/baselines/…"）→ 段绿、
       summary 零红线点名、结果文件逐字节不动；
    R2 只读巡检器族×baselines token（sed/grep/cat/head/tail/wc/diff）+包装器
       包只读程序（timeout 5 sed）+ git grep → 全绿零回写；
    R3 管道下游仍只读（sed | grep）→ 绿；
  X 红线不松（窄化不许开漏）：
    X1 裸跑 run_scenarios.py → 红+点名+恰 1 条 integration_violations（既有
       执法零回归锚）；
    X2 bash -lc 组合旗内跑（-c 串 python3 -m integration.run_scenarios）→
       红（同跌落路径的反向面：修复前=漏判绿，修复后必须红）；
    X3 xargs 二段式（… | xargs python3 integration/baselines/x.py）→ 红
       （工单规格④点名；修复前=已知漏判）；
    X4 heredoc 正文喂 bash 跑 baselines 脚本 → 红（组级分流不因窄化松动）；
  M 畸形输入：bash -lc 空串/引号不平衡 → 不抛、段不被误红（执法器畸形输入
    契约在旅程级成立：坏命令不停好工单）。

判定锚公开回执面（status / summary / integration_violations 键语义），不锚
执法器内部函数；与 developer L1（matcher 纯函数真值表，
test_t260921_04_integration_discipline.py）intent 不同面：本条守真活动入口×
真档×结果文件落盘的旅程级行为；与 t260921-04-discipline-receipt-journey
intent 不同面（彼守回执执法链固有面：并行档防误伤/角色门/既有 -c 面——彼成
票时 `-lc` 组合旗跌落这一事故形态尚未在册），本条只守「读不算跑」事故回归
与同路径反向漏判面。修复前 R1–R3 红、X2/X3 绿属预期（TDD 信号）；
run_integration_tests 期必须全绿。环境缺 zstd / 引擎模块不可导入 = ENV_FAIL
exit 2 点名。
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _ensure_venv_python() -> None:
    """agent_activities 模块级 import temporalio——系统 python3 缺依赖时回落引擎
    venv（verify.yaml test check 同款回落链；已在 venv 内则原样继续）。"""
    if os.environ.get("_T261009_36_REEXEC") == "1":
        return
    for cand in (REPO / "server/engine/.venv/bin/python",
                 REPO / "server/dsh/temporal-poc/.venv/bin/python"):  # engine-venv-compat（t260907-10 旧路径一轮回落，摘除票删；与 verify.yaml test check 同款）
        if cand.is_file():
            try:
                same = Path(sys.executable).resolve() == cand.resolve()
            except OSError:
                same = False
            if not same:
                env = dict(os.environ)
                env["_T261009_36_REEXEC"] = "1"
                os.execve(str(cand), [str(cand), "-B", os.path.abspath(__file__)], env)
            return


_ensure_venv_python()
sys.path.insert(0, str(REPO / "integration"))
sys.path.insert(0, str(REPO / "server" / "engine"))
try:
    from shared import AgentStageArgs  # noqa: E402
    import agent_activities  # noqa: E402
    from lib_env import clean_narrowing_env  # noqa: E402  (L12: zstd fixture spawn runs a cleaned env)
except Exception as e:  # pragma: no cover
    print("ENV_FAIL: engine modules unimportable (temporalio missing?): %s: %s"
          % (type(e).__name__, e))
    sys.exit(2)

if not shutil.which("zstd"):
    print("ENV_FAIL: zstd missing (session-archive fixture needs it)")
    sys.exit(2)

TICKET = "t261009-36-scene"

# 事故原文（t261008-47 验收证据逐字）。
LIVE_FP = 'bash -lc "sed -n 70p integration/baselines/lane-stages-chain.mjs"'
READS = [
    LIVE_FP,
    "sed -n '70p' integration/baselines/lane-stages-chain.mjs",
    "grep -n verify_lane integration/baselines/lane-stages-chain.mjs",
    "cat integration/baselines/lane-stages-chain.mjs",
    "head -20 integration/baselines/lane-yaml-chain.mjs",
    "tail -5 integration/baselines/ticket-lifecycle-scenes.mjs",
    "wc -l integration/baselines/lane-readme-sync.mjs",
    "diff integration/baselines/lane-stages-chain.mjs integration/baselines/lane-yaml-chain.mjs",
    "timeout 5 sed -n 70p integration/baselines/lane-stages-chain.mjs",
    "git grep -n baselines -- integration/baselines",
    "sed -n 1p integration/baselines/lane-stages-chain.mjs | grep baselines",
]
VIOLATING_PLAIN = "python3 integration/run_scenarios.py -k scene_x"
VIOLATING_LC = 'bash -lc "python3 -m integration.run_scenarios"'
VIOLATING_XARGS = "cat list.txt | xargs python3 integration/baselines/x.py"
VIOLATING_HEREDOC = ("bash <<'EOF'\npython3 integration/baselines/x.py\nEOF")
MALFORMED = ['bash -lc ""', 'bash -lc "unbalanced quote']

passed, failed = 0, 0


def check(cond, label):
    global passed, failed
    if cond:
        passed += 1
        print("  ok %s" % label)
    else:
        failed += 1
        print("  FAIL %s" % label)
    return cond


def user_frame(text):
    return {"type": "user/message", "data": {"content": [{"type": "text", "text": text}]}}


def tool_frame(seq, cmd):
    return {"type": "tool/call", "seq": seq,
            "data": {"name": "bash", "arguments": json.dumps({"command": cmd})}}


def write_session(role_dir: Path, frames) -> Path:
    role_dir.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(json.dumps(f, ensure_ascii=False) for f in frames) + "\n"
    out = role_dir / "session.jsonl.zstd"
    with open(out, "wb") as fh:
        proc = subprocess.run(["zstd", "-z", "-c"], input=payload.encode("utf-8"),
                              stdout=fh, stderr=subprocess.DEVNULL,
                              env=clean_narrowing_env())
    if proc.returncode != 0:
        print("ENV_FAIL: zstd compress failed (rc=%d)" % proc.returncode)
        sys.exit(2)
    return out


def make_lane(root: Path):
    sessions = root / ".dsh" / "sessions" / "fixture-slug"
    return sessions / (TICKET + "-developer")


def write_receipt(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"status": "ok", "summary": "[stub] fixture receipt", "report": "fixture",
            "deliverables": [], "files_changed": [], "evidence": "fixture",
            "prompt": "fixture prompt"}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", "utf-8")
    return data


def run_stage(lane: Path, rfile: Path):
    """Real activity entry (idempotent-cache seam): preset receipt, zero spawn."""
    args = AgentStageArgs(
        ticket_id=TICKET, stage_id="implement", role="developer",
        prompt="scenario fixture prompt",
        workspace={"type": "dir", "path": str(lane)},
        result_file=str(rfile), log_file="", gen=0,
        workflow_id="dev-lane", skip_settle=True)
    return asyncio.run(agent_activities._run_agent_stage_impl(args))


def stage_with_cmds(cmds, tmp_prefix):
    lane_root = Path(tempfile.mkdtemp(prefix=tmp_prefix))
    dev_dir = make_lane(lane_root)
    write_session(dev_dir, [user_frame("fixture turn")]
                  + [tool_frame(i + 1, c) for i, c in enumerate(cmds)])
    rfile = lane_root / "results" / "implement_gen0.json"
    write_receipt(rfile)
    res = run_stage(lane_root, rfile)
    return res, rfile


def main():
    tmpdirs = []
    try:
        # ---- R 读放行：事故原文 + 只读巡检器族 + 包装器 + 管道 → 段绿零回写 ----
        print("== R reads never stop a developer stage (t261008-47 regression)")
        before_receipt = None
        res, rfile = stage_with_cmds(READS, "t26100936-r-")
        tmpdirs.append(rfile.parents[1])
        disk = json.loads(rfile.read_text("utf-8"))
        check(res.status == "ok", "R1 stage settles green on the live-incident read (got %s)"
              % res.status)
        check("红线" not in res.summary and "run_scenarios" not in res.summary,
              "R2 summary names no red line for reads")
        check(not disk.get("integration_violations"),
              "R3 no violation rows written")
        check(res.integration_violations in (None, [],),
              "R4 receipt carries zero violations")
        # 绿不回写：结果文件逐字节不动（读者侧证据=盘上结果文件，非内存回执）
        before_receipt = write_receipt(rfile)
        blob = rfile.read_bytes()
        res, rfile = stage_with_cmds(READS, "t26100936-r2-")
        tmpdirs.append(rfile.parents[1])
        check(res.status == "ok" and rfile.read_bytes() == blob,
              "R5 green never rewrites the result file (byte-identical)")

        # ---- X 红线不松：窄化不许开出新跑法 ----
        print("== X the red line stays: executions must still be caught")
        res, rfile = stage_with_cmds([VIOLATING_PLAIN], "t26100936-x1-")
        tmpdirs.append(rfile.parents[1])
        disk = json.loads(rfile.read_text("utf-8"))
        viols = disk.get("integration_violations") or []
        check(res.status == "failed", "X1 plain suite run still red (got %s)" % res.status)
        check(len(viols) == 1 and VIOLATING_PLAIN in str(viols[0].get("cmd", "")),
              "X2 exactly one violation naming the full command (got %d)" % len(viols))

        res, rfile = stage_with_cmds([VIOLATING_LC], "t26100936-x2-")
        tmpdirs.append(rfile.parents[1])
        check(res.status == "failed",
              "X3 run inside bash -lc combined-flag string still red (was a silent miss)")
        check("run_scenarios" in res.summary,
              "X4 summary names the run_scenarios entry (receipt may quote the nested segment)")

        res, rfile = stage_with_cmds([VIOLATING_XARGS], "t26100936-x3-")
        tmpdirs.append(rfile.parents[1])
        check(res.status == "failed",
              "X5 xargs-fed baselines execution still red (spec evidence item)")
        check("baselines" in res.summary or "x.py" in res.summary,
              "X6 summary names the baselines entry")

        res, rfile = stage_with_cmds([VIOLATING_HEREDOC], "t26100936-x4-")
        tmpdirs.append(rfile.parents[1])
        check(res.status == "failed",
              "X7 heredoc body fed to bash running baselines script still red")

        # ---- M 畸形输入：坏命令不停好工单 ----
        print("== M malformed -lc payloads must not fail the stage nor crash")
        res, rfile = stage_with_cmds(MALFORMED, "t26100936-m-")
        tmpdirs.append(rfile.parents[1])
        disk = json.loads(rfile.read_text("utf-8"))
        check(res.status == "ok", "M1 stage settles green on malformed -lc payloads (got %s)"
              % res.status)
        check(not disk.get("integration_violations"), "M2 zero violation rows on malformed input")
    finally:
        for d in tmpdirs:
            shutil.rmtree(d, ignore_errors=True)
    print("SUMMARY pass=%d fail=%d" % (passed, failed))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
