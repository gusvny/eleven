#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_discipline_quoted_segment_incident.py — 执法分段器引号感知的事故回归旅程（t260922-14）。

intent（守护的用户可感知契约，工单 t260922-14 验收②③+宿主令追加⑦的旅程级事故回归，
灰盒 L3 离线秒级，真 zstd 会话档 × 真活动入口缓存挂点零 spawn）：
现场误红两族形态（**现场原文，非构造形**）经真执法链（developer 段会话扫描→回执）
必须放行，同时新格式真跑在旅程级仍判红（防线不松）——
  A. 第二类误红事故回归（t260922-12 现场逐字大命令：echo/grep/ls/sed、引号内 \\|、
     grep -E 交替含入口名、续行拼接；加最小同形）→ developer 段零红零点名、
     结果文件逐字节不动（无命中不回写）——「只读侦察不再停摆工单」；
  B. 第三类误红事故回归：python3-heredoc 探针（正文=python 代码，含列举示例命令的
     字符串行）→ 零红（heredoc 正文=数据，宿主令⑦正主旅程级）；
  C. 防线不松·管道形：`ls | python3 …run_scenarios.py` 真跑 → 红回执+点名+
     violations 恰 1，同回合只读 grep -E 交替不计（判跑不判读立场不因新格式松动）；
  D. 防线不松·heredoc 分流：bash-heredoc 正文真跑 → 红；同回合 cat-heredoc
     数据组不计（组级分流的旅程级证据，violations 恰 1 只点名 bash 组）。

intent 分工（防重复）：与 t260921-04-discipline-receipt-journey 不同面——彼守构造
简单形的红绿旅程+并行 P1/P2+角色门+-c 面（其允许面只有朴素只读命令，当时引号交替/
heredoc 两族误红形态尚未成为已知问题）；本条守**现场事故原文**的回归与新格式防线，
数据=票面现场命令。与 developer L1（本票纯函数形态矩阵 T1-T10/H/HA-HD/DM）不同层：
彼守 matcher 函数级形态矩阵，本条守真活动入口×真 zstd 档×结果文件落盘全链在现场
原文上的行为（纯函数过≠执法链在旅程级不误停工单）。声明=执法同批（验收④）由
developer L1 的源级断言锁，本场景不重复。

Hermetic：全部写面在 tempfile 泳道，零真仓零端口零网络；cwd=仓库根；秒级。
退出契约：stdout 末行 SUMMARY pass=N fail=K；exit 1 iff fail>0；
zstd 缺席 / 引擎模块不可导入 = ENV_FAIL exit 2 点名。

**实现段落地前 A/B/C1/C2/D2 红属预期（TDD 信号：误红尚未消失）；落地后全绿，
run_integration_tests 期必须保持绿。**
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
    if os.environ.get("_T260922_14_REEXEC") == "1":
        return
    for cand in (REPO / "server/engine/.venv/bin/python",
                 REPO / "server/dsh/temporal-poc/.venv/bin/python"):  # engine-venv-compat（t260907-10 同款回落；旧回落路径随摘除票删除）
        if cand.is_file():
            try:
                same = Path(sys.executable).resolve() == cand.resolve()
            except OSError:
                same = False
            if not same:
                env = dict(os.environ)
                env["_T260922_14_REEXEC"] = "1"
                os.execve(str(cand), [str(cand), "-B", os.path.abspath(__file__)], env)
            return


_ensure_venv_python()
sys.path.insert(0, str(REPO / "server" / "engine"))
try:
    from shared import AgentStageArgs  # noqa: E402
    import agent_activities  # noqa: E402
except Exception as e:  # pragma: no cover - 环境缺依赖路径
    print("ENV_FAIL: 引擎模块不可导入（temporalio 缺失？）：%s: %s" % (type(e).__name__, e))
    sys.exit(2)

if not shutil.which("zstd"):
    print("ENV_FAIL: zstd 缺席（会话档夹具压缩需要，本机自建或安装 zstd）")
    sys.exit(2)

TICKET = "t260922-14-scene"

# ---- 现场原文（票面数据，非构造形） ----
# t260922-12 implement 段被判红、票停摆的那条只读侦察命令（票面逐字：引号内 \|
# grep 交替、grep -E 交替含入口名、续行拼接多段）。
FIELD_12 = (
    'echo "== REPO 用途 ==" && grep -n "REPO" integration/scenario_ledger.py && \\\n'
    'echo "== t260922-12 夹具 monkeypatch/_run_baseline ==" && '
    'grep -rn "monkeypatch\\|_run_baseline" integration/t260922-12/*.py | head && \\\n'
    'echo "== 受影响面其它电池 ==" && '
    'ls integration/tests/ | grep -E "t260910_13|verify_lane|failure_protocol|ledger" && \\\n'
    'echo "== 电池 import verify_lane 方式 ==" && '
    "sed -n '1,60p' integration/tests/test_t260922_12_gate_ledger.py"
)
# 第二类误红最小同形（切出的裸片段恰为入口名）。
FIELD_MIN = ('ls integration/tests/ | grep -E '
             '"t260910_13|verify_lane|failure_protocol|ledger"')
# 第三类误红载体（gen0 现场同形：python3-heredoc 探针，正文=python 代码，
# 内含列举示例命令的字符串行——执法器不解析 python，正文按数据放行）。
HEREDOC_PROBE = (
    "python3 - <<'PYEOF'\n"
    "import json\n"
    "rows = []\n"
    "rows.append('反例组：ls | python3 integration/run_scenarios.py "
    "&& echo hi && sc_foo.py 共 16 形')\n"
    "print(json.dumps(rows, ensure_ascii=False))\n"
    "PYEOF\n"
)
# 防线不松的真跑形（票面验收③点名形态的旅程级）。
PIPE_RUN = "ls | python3 integration/run_scenarios.py"
BASH_HEREDOC_RUN = "bash <<'EOF'\npython3 integration/run_scenarios.py\nEOF"
CAT_HEREDOC_DATA = ("cat <<'EOF'\n"
                    "ls | python3 integration/run_scenarios.py && echo done\n"
                    "EOF\n")

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


# ---- 会话档夹具（真 dsh 帧形：type+data；tool/call 的 arguments=JSON 串） ----

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
                              stdout=fh, stderr=subprocess.DEVNULL)
    if proc.returncode != 0:
        print("ENV_FAIL: zstd 压缩失败（rc=%d）" % proc.returncode)
        sys.exit(2)
    return out


def make_lane(root: Path) -> Path:
    return root / ".dsh" / "sessions" / "fixture-slug" / (TICKET + "-developer")


def write_receipt(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"status": "ok", "summary": "[stub] 场景夹具回执", "report": "夹具",
            "deliverables": [], "files_changed": [], "files_changed_shape": "ok",
            "evidence": "fixture", "prompt": "fixture prompt"}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", "utf-8")
    return data


def run_stage(lane: Path, rfile: Path):
    """真活动入口（缓存挂点）：预置回执→幂等缓存分支，零 spawn。"""
    args = AgentStageArgs(
        ticket_id=TICKET, stage_id="implement", role="developer",
        prompt="场景夹具派活",
        workspace={"type": "dir", "path": str(lane)},
        result_file=str(rfile), log_file="", gen=0,
        workflow_id="dev-lane", skip_settle=True)
    return asyncio.run(agent_activities._run_agent_stage_impl(args))


def run_faces(frames, prefix):
    """夹具泳道 → 真执法链 → (res, rfile, before_bytes, lane)。"""
    lane = Path(tempfile.mkdtemp(prefix=prefix))
    dev_dir = make_lane(lane)
    write_session(dev_dir, frames)
    rfile = lane / "results" / "implement_gen0.json"
    write_receipt(rfile)
    before = rfile.read_bytes()
    return run_stage(lane, rfile), rfile, before, lane


def main():
    tmpdirs = []
    try:
        # ---- A 第二类误红事故回归：现场大命令+最小同形 → 零红零回写 ----
        print("== A 第二类误红（t260922-12 现场逐字）：只读侦察零红零点名零回写")
        res, rfile, before, lane = run_faces(
            [user_frame("只读侦察夹具"), tool_frame(1, FIELD_12),
             tool_frame(2, FIELD_MIN)], "t26092214-a-")
        tmpdirs.append(lane)
        after = rfile.read_bytes()
        check(res.status == "ok", "A1 现场大命令不再判红（实得 %s）" % res.status)
        check(not (res.integration_violations or []), "A2 零违规记录")
        check("verify_lane" not in res.summary and "红线" not in res.summary,
              "A3 summary 零点名")
        check(before == after, "A4 绿不回写：结果文件逐字节不动")

        # ---- B 第三类误红事故回归：python3-heredoc 探针 → 零红（正文=数据） ----
        print("== B 第三类误红（heredoc 正文=数据）：python3 探针零红零回写")
        res, rfile, before, lane = run_faces(
            [user_frame("探针夹具"), tool_frame(1, HEREDOC_PROBE)], "t26092214-b-")
        tmpdirs.append(lane)
        check(res.status == "ok", "B1 heredoc 探针不再判红（实得 %s）" % res.status)
        check(not (res.integration_violations or []),
              "B2 正文数据行不计违规（宿主令⑦）")
        check(before == rfile.read_bytes(), "B3 绿不回写：结果文件逐字节不动")

        # ---- C 防线不松·管道形真跑：红+点名，同回合只读交替不稀释 ----
        print("== C 防线不松（管道形）：真跑红+恰 1 条；同回合只读 grep -E 交替不计")
        res, rfile, before, lane = run_faces(
            [user_frame("混合夹具"), tool_frame(1, PIPE_RUN),
             tool_frame(2, FIELD_MIN)], "t26092214-c-")
        tmpdirs.append(lane)
        viols = res.integration_violations or []
        check(res.status == "failed", "C1 管道真跑仍判红（实得 %s）" % res.status)
        check(len(viols) == 1, "C2 违规恰 1 条（只读交替被新格式放行，实得 %d）"
              % len(viols))
        check(bool(viols) and PIPE_RUN in str(viols[0].get("cmd", "")),
              "C3 点名完整真跑命令")
        check(bool(viols) and "verify_lane" not in str(viols[0].get("entry", "")),
              "C4 计入的是执行入口而非引号交替词（判跑不判读）")

        # ---- D 防线不松·heredoc 分流：bash 组红，cat 组数据不计 ----
        print("== D 防线不松（heredoc 分流）：bash 正文真跑红；同回合 cat 正文数据不计")
        res, rfile, before, lane = run_faces(
            [user_frame("heredoc 混合夹具"), tool_frame(1, BASH_HEREDOC_RUN),
             tool_frame(2, CAT_HEREDOC_DATA)], "t26092214-d-")
        tmpdirs.append(lane)
        viols = res.integration_violations or []
        check(res.status == "failed", "D1 bash-heredoc 正文真跑仍判红（实得 %s）"
              % res.status)
        check(len(viols) == 1, "D2 违规恰 1 条（cat 组正文=数据不计，实得 %d）"
              % len(viols))
        check(bool(viols) and BASH_HEREDOC_RUN.splitlines()[0] in str(viols[0].get("cmd", "")),
              "D3 点名来自 bash 组那条")
    finally:
        for d in tmpdirs:
            shutil.rmtree(d, ignore_errors=True)

    print("SUMMARY pass=%d fail=%d" % (passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
