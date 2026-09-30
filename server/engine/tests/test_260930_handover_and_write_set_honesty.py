"""260930 批次 A + B4 单测：报告面不再失真（nusuyou E2·N⑦ / dengzhufpv E1·E6 合并修法）。

三条修法各锁一层：
  A1 **交接命令并发误判**（E2）：并发批跑完后，非零退出条目**串行复核一次**，报告以复核为准；
     原始并发结果两态留痕；真红复核后仍红。常态（全绿批）零复核成本。
  B4 **交接命令语法坏照旧放行**（N⑦）：入账前逐条 `sh -n` 自检，不过者打标；执行面**不执行**并
     三态具名（executed-ok / executed-red / syntax-bad），且语法坏照计 failed（fail-closed：
     「没执行」绝不等于「绿」）。
  A2/A3 **文案把人引偏**（E6 写集红灯 / E1 处置 runbook）：写集刷新红灯降为**提醒**并区别两态、
     明确劝止 rework；坏档处置改**两步**（先单发 retry_qc，同一文件名复现才挪档）。

运行：server/engine/.venv/bin/python -B -m pytest \
      server/engine/tests/test_260930_handover_and_write_set_honesty.py -q
"""
import asyncio
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import agent_activities as aa  # noqa: E402
import dev_lane as dl  # noqa: E402


# ---------------- A1：并发误判 → 串行复核 ----------------

@pytest.fixture()
def fake_leg(monkeypatch):
    """假执行体：按 cmd 计数——第 1 次（并发批）失败、第 2 次（复核）成功。"""
    calls = {}

    async def _fake(leg, cwd):
        # 与实案同形：**发布**首跑即绿；**校验**首跑对着发布前状态判 → 红，复核才绿
        cmd = str(leg.get("cmd"))
        calls[cmd] = calls.get(cmd, 0) + 1
        if cmd == "PUB":
            return {"name": "publish", "cmd": cmd, "exit": 0,
                    "output_tail": "发布成功（首跑即绿）"}
        first = calls[cmd] == 1
        return {"name": str(leg.get("name")), "cmd": cmd,
                "exit": 1 if first else 0,
                "output_tail": "并发首跑（旧状态）" if first else "串行复核（新状态）"}

    monkeypatch.setattr(aa, "run_handover_leg", _fake)
    return calls


def test_failed_legs_are_rechecked_serially_and_the_recheck_wins(fake_leg):
    legs = [{"name": "publish", "cmd": "PUB"}, {"name": "verify", "cmd": "VERIFY"}]
    out = asyncio.run(aa.run_handover_legs(legs, Path("/tmp")))
    assert out["ran"] == 2 and out["failed"] == 0 and out["passed"] == 2, out
    assert fake_leg["VERIFY"] == 2, "失败条目必须被串行复核一次（且只一次）"
    assert fake_leg["PUB"] == 1, "首跑绿的条目不该被复核（常态零成本）"
    detail = [d for d in out["details"] if d["cmd"] == "VERIFY"][0]
    assert "并发首跑 exit=1" in detail["output_tail"] and "串行复核 exit=0" in detail["output_tail"], \
        "原始并发结果必须两态留痕（不许静默改判）"
    assert detail["state"] == "executed-ok"


def test_a_genuinely_red_leg_stays_red_after_recheck(monkeypatch):
    async def _always_fail(leg, cwd):
        return {"name": str(leg.get("name")), "cmd": str(leg.get("cmd")),
                "exit": 2, "output_tail": "真红"}

    monkeypatch.setattr(aa, "run_handover_leg", _always_fail)
    out = asyncio.run(aa.run_handover_legs([{"name": "x", "cmd": "X"}], Path("/tmp")))
    assert out["failed"] == 1 and out["passed"] == 0
    assert "真红" in out["details"][0]["output_tail"], "复核后仍红必须如实说「真红」"


# ---------------- B4：语法自检 + 三态具名 ----------------

@pytest.mark.parametrize("cmd,ok", [
    ("echo ok", True),
    ("cd /tmp && ls -la", True),
    ("cd <lane_root> && pnpm run build", False),        # t260929-38 实案：`<` 是重定向
    ("if [ 1 -eq 1 ]; then echo x; fi", True),
    ("for i in ; do", False),
])
def test_syntax_selfcheck(cmd, ok):
    err = aa._handover_syntax_error(cmd)
    assert (err == "") is ok, "%r → %r" % (cmd, err)


def test_mark_handover_syntax_marks_without_touching_the_command():
    legs = [{"name": "a", "cmd": "echo ok"}, {"name": "b", "cmd": "cd <lane> && x"}]
    out = aa._mark_handover_syntax(legs)
    assert out[0].get("syntax_bad") is False and "syntax_note" not in out[0]
    assert out[1]["syntax_bad"] is True and out[1]["syntax_note"]
    assert out[1]["cmd"] == "cd <lane> && x", "打标不改命令内容（债表照记原样）"
    assert aa._mark_handover_syntax("不是列表") == "不是列表"


def test_syntax_bad_leg_is_not_executed_and_is_named(monkeypatch):
    called = []

    async def _should_not_be_called(leg, cwd):
        called.append(leg)
        return {"name": "x", "cmd": "x", "exit": 0, "output_tail": ""}

    monkeypatch.setattr(aa, "run_handover_leg", _should_not_be_called)
    legs = aa._mark_handover_syntax([
        {"name": "publish", "cmd": "echo ok"},
        {"name": "broken", "cmd": "cd <lane_root> && pnpm build"},
    ])
    out = asyncio.run(aa.run_handover_legs(legs, Path("/tmp")))
    assert [c["name"] for c in called] == ["publish"], "语法坏条目一律不执行"
    assert out["syntax_bad"] == 1
    assert out["failed"] == 1, "fail-closed：语法坏照计 failed（「没执行」绝不等于绿）"
    bad = [d for d in out["details"] if d["state"] == "syntax-bad"]
    assert len(bad) == 1 and "未执行" in bad[0]["output_tail"] \
        and "语法不过" in bad[0]["output_tail"], "三态具名：语法坏要点名到条"


# ---------------- A2 / A3：文案不再把人引偏 ----------------

def test_write_set_red_is_downgraded_and_rework_prescription_removed():
    src = Path(dl.__file__).read_text("utf-8")
    assert "【红灯】写集刷新被拒" not in src, "旧红灯文案必须退场"
    seg = src.split("create_plan 回执 %s（KI-049", 1)
    assert len(seg) == 2
    body = seg[1][:900]
    assert "【提醒·非阻塞】" in src.split("create_plan 回执 %s（KI-049", 1)[0][-200:]
    assert "不要为它 rework" in body, "必须明确劝止 rework（四次实案零损失）"
    assert "本段确实没改文件" in body and "没填结构化字段" in body, "必须区分两态"
    assert "rework 回 create_plan 重交结构化回执" not in body, "旧处方必须消失"


def test_bad_result_file_remedy_is_two_steps(tmp_path):
    bad = tmp_path / "stage_x_gen1.json"
    bad.write_text("{半截", encoding="utf-8")
    txt = aa._result_gone_detail("create_plan", 0, bad, "")
    assert "处置两步" in txt
    assert "先只发 retry_qc" in txt, "第一步＝先单发 retry_qc（实测自愈路径）"
    assert "同一文件名上复现" in txt, "第二步＝同名复现才挪档（能不动就不动泳道）"
    assert txt.index("先只发 retry_qc") < txt.index("同一文件名上复现"), "两步顺序不许反"
