"""t260929-04 复核（integration 岗 main 侧直修）——结果文件「在场却读不出」必须与「未写」分开说。

来历（260929 真票实案）：t260929-04 的 implement 段结果文件被**撕裂**
（`stage_implement_gen1.json` 的 evidence 字符串写到一半就断），引擎的退出诊断却说
「未写结果文件」——与事实相反，把排查引向「agent 没干活」；同时 agent 的幂等判据是
「结果文件在场=本段已完成」，于是它拒绝重写 ⇒ 引擎读不出 / agent 不重写，三次尝试
全败、票 blocked 在重试环里。本条钉的是**报错精确**（不改判定，只把话说对），
以及处置指引（挪走留证 + retry_qc）。

真值表（四态）：missing→「未写」；torn/坏 JSON→「在场却读不出」+ 处置指引；
合法回执→'ok'（正常路径不走到本判定）；空文件→「在场却读不出」（不是「未写」）。
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agent_activities as aa  # noqa: E402


def _ok_result(**over):
    body = {"status": "ok", "stage": "implement", "gen": 1, "report": "做完了",
            "files_changed": ["server/plugins/x.ts"]}
    body.update(over)
    return json.dumps(body, ensure_ascii=False)


def test_state_missing(tmp_path):
    assert aa._result_file_state(tmp_path / "nope.json") == "missing"


def test_state_ok(tmp_path):
    f = tmp_path / "stage_implement_gen1.json"
    f.write_text(_ok_result(), encoding="utf-8")
    assert aa._result_file_state(f) == "ok"


def test_state_torn_is_unreadable_not_missing(tmp_path):
    """撕裂档（260929 实案形态：长字段写到一半就断）⇒ unreadable，绝不报 missing。"""
    f = tmp_path / "stage_implement_gen1.json"
    f.write_text('{\n  "status": "ok",\n  "evidence": "F1 HARNESS PROTOCOL (写到一半\n  ]\n}\n',
                 encoding="utf-8")
    assert aa._result_file_state(f) == "unreadable"


def test_state_empty_file_is_unreadable(tmp_path):
    f = tmp_path / "stage_implement_gen1.json"
    f.write_text("", encoding="utf-8")
    assert aa._result_file_state(f) == "unreadable"


def test_detail_words_missing_as_missing(tmp_path):
    msg = aa._result_gone_detail("headless", 0, tmp_path / "nope.json", "/tmp/a.log")
    assert "未写结果文件" in msg and "在场却读不出" not in msg


def test_detail_words_torn_as_unreadable_with_way_out(tmp_path):
    """本条的精确回归锁：坏档在场时**不得**出现「未写结果文件」，且必须给处置指引。"""
    f = tmp_path / "stage_implement_gen1.json"
    f.write_text('{\n  "status": "ok",\n  "evidence": "断在这里\n  ]\n}\n', encoding="utf-8")
    msg = aa._result_gone_detail("headless", 0, f, "/tmp/a.log")
    assert "在场却读不出" in msg
    assert "未写结果文件" not in msg, "坏档在场却说「未写」=把诊断引向错误方向（本条要杀的形态）"
    assert "retry_qc" in msg and "挪走留证" in msg, "必须给可执行处置，否则人无处下手"


def test_three_sites_share_one_source(tmp_path):
    """三处 raise（headless/arbitrate/acceptance）共用同一真源——不许各写一份文案。

    t261001-03：三站轮询循环合一（_wait_for_agent_result）后，「调用 3」收敛为
    helper 内调用 1——三站经由共享 helper 间接共用同一真源，锁语义不变。"""
    src = (Path(aa.__file__)).read_text("utf-8")
    assert src.count("_result_gone_detail(") == 2, "定义 1 + helper 调用 1"
    assert src.count("await _wait_for_agent_result(") == 3, \
        "三站都必须改走共享 helper（否则即有站外泄自己的失败文案）"
    assert "但未写结果文件 %s（日志 %s）\"\n                          % (rc, rfile, args.log_file)" not in src
