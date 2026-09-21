#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_discipline_receipt_journey.py — developer 段集成禁跑的回执执法旅程（t260921-04）。

intent（守护的用户可感知契约，宿主令 260921 要求②③+验收①②③④的引擎接线面）：
夹具泳道的真 zstd 会话档（真 dsh 帧形：type+data、tool/call 的 arguments=JSON 串）
经**真 agent 活动入口**（幂等缓存挂点，零 spawn 零 Temporal 零网络）执法——
  A. 构造子用例：developer 会话含集成入口执行（integration/run_scenarios.py）+ 同回合
     只读提及（grep）→ 回执红、summary 点名完整命令、结果文件回写
     integration_violations 恰 1 条（只读提及不计）、既有字段形状逐字保留（验收④）、
     重入幂等不双写（summary 逐字节不变）；
  B. 允许面（要求③）：受影响面 pytest、integration/lint_tests.py、只读
     grep/sed/cat/git → 零红零点名，且结果文件逐字节不动（无命中不回写）；
  C. P1 并行防误伤（KI-093 同族）：并行 integration 角色档（双代名
     session.v3.jsonl.zstd）mtime 更新且含集成执行 → developer 回执不背红；
  D. P2 防漏判：developer 档真违规 + integration 档更新 → 红不丢，点名命令来自
     developer 档；
  E. 角色门：同形态 integration 角色段不执法（宿主令只限 developer）；
  F. -c 嵌套串（review K1 条件的两合法解）：递归判一条（bash -c 内执行入口红、
     只读 ls 不红）或边界声明不执法（声明=执法；naive 子串粗匹配会误伤只读，
     两边都不占=红）。

锚回执 JSON 契约与票面 summary 语义，不锚引擎内部函数结构；与 developer L1
（方案 §5 函数级夹具/挂点单测）intent 不同面：本场景守真活动入口 × 真 zstd 档 ×
结果文件落盘 × 角色钉档（role 钉 <ticket>-developer 目录，绝不全树 mtime 选档）
的全链。实现段落地前红属预期（TDD 信号），run_integration_tests 期必须绿。

Hermetic：全部写面在 tempfile 泳道，零真仓零端口零网络；cwd=仓库根；秒级。
退出契约：stdout 末行 SUMMARY pass=N fail=K；exit 1 iff fail>0；
zstd 缺席 / 引擎模块不可导入 = ENV_FAIL exit 2 点名。
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
    if os.environ.get("_T260921_04_REEXEC") == "1":
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
                env["_T260921_04_REEXEC"] = "1"
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

TICKET = "t260921-04-scene"
VIOLATING = "python3 integration/run_scenarios.py -k scene_x"
ALLOWED = [
    "pytest server/engine/tests/test_t260921_04_integration_discipline.py -q",
    "python3 integration/lint_tests.py",
    "grep -rn run_scenarios server/engine",
    "sed -n '1,50p' integration/run_scenarios.py",
    "cat integration/README.md",
]

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


def write_session(role_dir: Path, filename: str, frames) -> Path:
    role_dir.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(json.dumps(f, ensure_ascii=False) for f in frames) + "\n"
    out = role_dir / filename
    with open(out, "wb") as fh:
        proc = subprocess.run(["zstd", "-z", "-c"], input=payload.encode("utf-8"),
                              stdout=fh, stderr=subprocess.DEVNULL)
    if proc.returncode != 0:
        print("ENV_FAIL: zstd 压缩失败（rc=%d）" % proc.returncode)
        sys.exit(2)
    return out


def make_lane(root: Path):
    sessions = root / ".dsh" / "sessions" / "fixture-slug"  # slug 中间层刻意非常规形
    return sessions / (TICKET + "-developer"), sessions / (TICKET + "-integration")


def write_receipt(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"status": "ok", "summary": "[stub] 场景夹具回执", "report": "夹具",
            "deliverables": [], "files_changed": [], "files_changed_shape": "ok",
            "evidence": "fixture", "prompt": "fixture prompt"}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", "utf-8")
    return data


def run_stage(lane: Path, role: str, rfile: Path):
    """真活动入口（缓存挂点）：预置回执→幂等缓存分支，零 spawn。"""
    args = AgentStageArgs(
        ticket_id=TICKET, stage_id=("implement" if role == "developer" else "arbitrate"),
        role=role, prompt="场景夹具派活",
        workspace={"type": "dir", "path": str(lane)},
        result_file=str(rfile), log_file="", gen=0,
        workflow_id="dev-lane", skip_settle=True)
    return asyncio.run(agent_activities._run_agent_stage_impl(args))


def main():
    tmpdirs = []
    try:
        # ---- A 构造子用例：集成执行红 + 同回合只读不计 + 回写 + 形状保留 + 幂等 ----
        print("== A 构造子用例（验收①）：集成执行→红+点名+回写；同回合只读不计；幂等")
        lane = Path(tempfile.mkdtemp(prefix="t26092104-a-"))
        tmpdirs.append(lane)
        dev_dir, _ = make_lane(lane)
        write_session(dev_dir, "session.jsonl.zstd",
                      [user_frame("本步契约夹具"), tool_frame(1, VIOLATING),
                       tool_frame(2, "grep -rn run_scenarios server/engine")])
        rfile = lane / "results" / "implement_gen0.json"
        write_receipt(rfile)
        res = run_stage(lane, "developer", rfile)
        disk = json.loads(rfile.read_text("utf-8"))
        check(res.status == "failed", "A1 回执红（实得 %s）" % res.status)
        check(VIOLATING in res.summary, "A2 summary 点名完整命令")
        viols = disk.get("integration_violations")
        check(isinstance(viols, list) and len(viols) == 1,
              "A3 结果文件回写恰 1 条（同回合只读提及不计，实得 %s）"
              % (len(viols) if isinstance(viols, list) else viols))
        check(bool(viols) and VIOLATING in str(viols[0].get("cmd", "")),
              "A4 违规条目载完整命令")
        check(disk.get("files_changed") == [] and disk.get("deliverables") == [],
              "A5 既有字段形状逐字保留（验收④）")
        res2 = run_stage(lane, "developer", rfile)
        disk2 = json.loads(rfile.read_text("utf-8"))
        check(res2.status == "failed" and disk2.get("summary") == disk.get("summary")
              and len(disk2.get("integration_violations") or []) == 1,
              "A6 重入幂等：summary 逐字节不变、违规不双写")

        # ---- B 允许面（验收②③）：全绿零点名，结果文件逐字节不动 ----
        print("== B 允许面（验收②③）：受影响面单测/lint/只读全放行，零回写")
        lane = Path(tempfile.mkdtemp(prefix="t26092104-b-"))
        tmpdirs.append(lane)
        dev_dir, _ = make_lane(lane)
        write_session(dev_dir, "session.jsonl.zstd",
                      [user_frame("本步契约夹具")]
                      + [tool_frame(i + 1, c) for i, c in enumerate(ALLOWED)])
        rfile = lane / "results" / "implement_gen0.json"
        write_receipt(rfile)
        before = rfile.read_bytes()
        res = run_stage(lane, "developer", rfile)
        after = rfile.read_bytes()
        check(res.status == "ok", "B1 允许面零红（实得 %s）" % res.status)
        check(not (json.loads(after.decode("utf-8")).get("integration_violations")),
              "B2 零违规记录")
        check("红线" not in res.summary and "run_scenarios" not in res.summary,
              "B3 summary 零点名")
        check(before == after, "B4 绿不回写：结果文件逐字节不动")

        # ---- C P1 并行防误伤（KI-093 同族）：integration 档新而脏→developer 不背红 ----
        print("== C P1 并行防误伤：integration 档（双代名）更新且含集成执行→developer 绿")
        lane = Path(tempfile.mkdtemp(prefix="t26092104-c-"))
        tmpdirs.append(lane)
        dev_dir, int_dir = make_lane(lane)
        dev_f = write_session(dev_dir, "session.jsonl.zstd",
                              [user_frame("本步契约夹具"), tool_frame(1, ALLOWED[0])])
        int_f = write_session(int_dir, "session.v3.jsonl.zstd",
                              [user_frame("设计集成测试段夹具"), tool_frame(1, VIOLATING)])
        now = dev_f.stat().st_mtime
        os.utime(dev_f, (now - 100, now - 100))
        os.utime(int_f, (now + 100, now + 100))
        rfile = lane / "results" / "implement_gen0.json"
        write_receipt(rfile)
        res = run_stage(lane, "developer", rfile)
        check(res.status == "ok", "C1 developer 不背并行 integration 段的红（实得 %s）"
              % res.status)
        check(not res.integration_violations, "C2 developer 回执零违规")

        # ---- D P2 防漏判：developer 档真违规 + integration 档更新→红不丢 ----
        print("== D P2 防漏判：developer 档违规+integration 档更新→红且点名来自 developer 档")
        lane = Path(tempfile.mkdtemp(prefix="t26092104-d-"))
        tmpdirs.append(lane)
        dev_dir, int_dir = make_lane(lane)
        dev_f = write_session(dev_dir, "session.jsonl.zstd",
                              [user_frame("本步契约夹具"), tool_frame(1, VIOLATING)])
        int_f = write_session(int_dir, "session.v3.jsonl.zstd",
                              [user_frame("设计集成测试段夹具"), tool_frame(1, ALLOWED[1])])
        now = dev_f.stat().st_mtime
        os.utime(dev_f, (now - 100, now - 100))
        os.utime(int_f, (now + 100, now + 100))
        rfile = lane / "results" / "implement_gen0.json"
        write_receipt(rfile)
        res = run_stage(lane, "developer", rfile)
        disk = json.loads(rfile.read_text("utf-8"))
        viols = disk.get("integration_violations") or []
        check(res.status == "failed", "D1 红不丢（实得 %s）" % res.status)
        check(len(viols) == 1 and VIOLATING in str(viols[0].get("cmd", "")),
              "D2 点名命令来自 developer 档（恰 1 条，实得 %d）" % len(viols))

        # ---- E 角色门：同形态 integration 角色段不执法 ----
        print("== E 角色门：integration 角色同形态不执法（宿主令只限 developer）")
        lane = Path(tempfile.mkdtemp(prefix="t26092104-e-"))
        tmpdirs.append(lane)
        dev_dir, _ = make_lane(lane)
        write_session(dev_dir, "session.jsonl.zstd",
                      [user_frame("本步契约夹具"), tool_frame(1, VIOLATING)])
        rfile = lane / "results" / "arbitrate_gen0.json"
        write_receipt(rfile)
        before = rfile.read_bytes()
        res = run_stage(lane, "integration", rfile)
        check(res.status == "ok", "E1 integration 角色零红（实得 %s）" % res.status)
        check(before == rfile.read_bytes(), "E2 非 developer 段结果文件零改动")

        # ---- F -c 嵌套串（review K1 条件的两合法解：递归判 或 声明不执法） ----
        print("== F -c 嵌套串：递归判一条 或 边界声明不执法（naive 子串误伤=红）")
        lane = Path(tempfile.mkdtemp(prefix="t26092104-f-"))
        tmpdirs.append(lane)
        dev_dir, _ = make_lane(lane)
        write_session(dev_dir, "session.jsonl.zstd",
                      [user_frame("本步契约夹具"),
                       tool_frame(1, 'bash -c "python3 integration/run_scenarios.py -k x"'),
                       tool_frame(2, 'bash -c "ls integration/baselines"')])
        rfile = lane / "results" / "implement_gen0.json"
        write_receipt(rfile)
        res = run_stage(lane, "developer", rfile)
        hits = len(res.integration_violations or [])
        declared = False
        try:
            import integration_discipline  # noqa: E402  （声明=执法：边界声明面）
            declared = "-c" in (integration_discipline.__doc__ or "")
        except Exception:
            declared = False
        check(hits == 1 or (hits == 0 and declared),
              "F1 bash -c 内执行入口判一条（递归解）或 -c 边界已声明（声明解）；"
              "实得 hits=%d declared=%s（hits≥2=只读 ls 被误伤）" % (hits, declared))
    finally:
        for d in tmpdirs:
            shutil.rmtree(d, ignore_errors=True)

    print("SUMMARY pass=%d fail=%d" % (passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
