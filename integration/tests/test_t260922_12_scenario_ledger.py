#!/usr/bin/env python3
"""t260922-12 场景结果台账库机械自证（integration/scenario_ledger.py）。

覆盖（票据①②验收的机械面）：
- 十字段封闭校验：缺键/多键/类型错/verdict 非法/键字段（commit/env_fp/
  conc_width/scenario）缺损/超行宽 → 逐条拒写带 reason（脏记录比无记录更坏）；
- append：合法批次落盘可读；全拒批次零落盘（不建文件）；返回 written/rejected；
- 读取面：文件缺席=空账非错误；畸形行/非对象行计 bad 点名（不静默吞）；
- query：全键过滤 + ts 新→旧 + 无记录显式文案（声明 90 天窗与月卷，不冒充
  「从未跑过」，不得静默回绿）；CLI 子进程形态（--json / 缺参 rc=2）；
- 保留（rollup）：>90 天行按月卷出（同键保最新）、主账原子重写、重跑幂等；
  .last-rollup 标记 >24h 才机会性触发；
- 并发：多进程并发 append（flock 序列化）零丢行；
- 体积口径：真实行形实测 327 B/行 → 271 行 <128KB 预算（票面「≈55KB」估算被
  实测推翻，锚改实测，单行仍受 MAX_ROW_BYTES 硬帽）。

全程 SANDBAR_SCENARIO_LEDGER_DIR 指临时目录，零真实 ~/.sandbar 接触；零 docker
零网络；并发子用例用 8 个子进程直跑库面（flock 序列化，秒级）。
"""
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MOD = REPO / "integration" / "scenario_ledger.py"

_spec = importlib.util.spec_from_file_location("sl_t92212_under_test", MOD)
sl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sl)

NOW = 1_800_000_000.0
COMMIT = "ab" * 20
FP = "cd" * 32


@pytest.fixture(autouse=True)
def ledger_home(tmp_path, monkeypatch):
    """隔离台账目录：本文件所有用例绝不触碰真实 ~/.sandbar。目录真建——卷标
    （.last-rollup）测试在首次 append 之前就要往目录里写文件；生产形里 append
    先建目录、卷标永在已存在目录内（夹具缺陷修复：原不 mkdir，两个 rollup
    用例 FileNotFoundError，与被测行为无关）。"""
    d = tmp_path / "ledger"
    d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv(sl.LEDGER_DIR_ENV, str(d))
    return d


def mk_row(**over):
    # t261009-11: rows gain `run` (the run record's id). Readers still tolerate
    # rows without it (legacy) — pinned by test_t261009_11_run_records.py.
    row = {"ts": "2026-09-21T08:00:00+00:00", "commit": COMMIT, "env_fp": FP,
           "conc_width": 4, "pool": "main", "scenario": "s1",
           "verdict": "pass", "wall_s": 1.0, "source": "inspection",
           "ticket": "", "run": "run-" + "A" * 26}
    row.update(over)
    return row


def iso(epoch):
    import datetime as dt
    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).isoformat()


# ---------------- 校验（键任一缺失 → 拒写） ----------------

def test_validate_ok_row_roundtrip():
    clean, why = sl.validate_row(mk_row())
    assert clean is not None and why is None


@pytest.mark.parametrize("over,frag", [
    ({"commit": None}, "commit"),
    ({"commit": "xyz"}, "commit"),
    ({"commit": "AB" * 20}, "commit"),          # 大写不收
    ({"env_fp": "cd" * 31}, "env_fp"),
    ({"conc_width": 0}, "conc_width"),
    ({"conc_width": True}, "conc_width"),
    ({"conc_width": "4"}, "conc_width"),
    ({"scenario": ""}, "scenario"),
    ({"scenario": None}, "scenario"),
    ({"verdict": "green"}, "verdict"),
    ({"wall_s": True}, "wall_s"),
    ({"wall_s": "1.0"}, "wall_s"),
    ({"source": "manual"}, "source"),
    ({"source": "lane:"}, "source"),
    ({"ticket": 3}, "ticket"),
    ({"ts": "2026-09-21T08:00:00"}, "ts"),      # naive 拒
    ({"ts": 123}, "ts"),
])
def test_validate_rejects_dirty_rows(over, frag):
    clean, why = sl.validate_row(mk_row(**over))
    assert clean is None and frag in why, why


def test_validate_rejects_extra_and_missing_fields():
    clean, why = sl.validate_row(mk_row(extra="x"))
    assert clean is None and why.startswith("unknown_fields")
    row = mk_row()
    row.pop("env_fp")
    clean, why = sl.validate_row(row)
    assert clean is None and why.startswith("missing_fields")


def test_validate_non_dict():
    clean, why = sl.validate_row("nope")
    assert clean is None and why == "row_not_dict"


# ---------------- append / read ----------------

def test_append_writes_valid_and_reports_rejected(ledger_home):
    rcpt = sl.append_records([mk_row(), mk_row(scenario="s2", verdict="fail",
                                               source="lane:t1", ticket="t1"),
                              mk_row(verdict="green")])
    assert rcpt["written"] == 2
    assert rcpt["rejected"] == [{"index": 2, "reason": "verdict_invalid:green"}]
    rows, bad = sl.read_rows()
    assert len(rows) == 2 and bad == []
    assert {r["scenario"] for r in rows} == {"s1", "s2"}


def test_append_all_rejected_writes_nothing(ledger_home):
    rcpt = sl.append_records([mk_row(commit="short")])
    assert rcpt["written"] == 0 and len(rcpt["rejected"]) == 1
    assert not (ledger_home / sl.MAIN_NAME).exists(), "全拒批次零落盘"


def test_append_row_too_big_rejected(ledger_home):
    rcpt = sl.append_records([mk_row(pool="p" * 4096)])
    assert rcpt["written"] == 0
    assert rcpt["rejected"][0]["reason"] == "row_too_big"


def test_read_rows_missing_file_is_empty_not_error(ledger_home):
    rows, bad = sl.read_rows()
    assert rows == [] and bad == []


def test_read_rows_surfaces_malformed_lines(ledger_home):
    sl.append_records([mk_row()])
    with open(str(sl.ledger_path()), "a", encoding="utf-8") as fh:
        fh.write("not-json-at-all\n")
        fh.write("[1,2,3]\n")  # 合法 JSON 但非对象 → 同为不可信行
    rows, bad = sl.read_rows()
    assert len(rows) == 1 and len(bad) == 2
    assert bad[0].startswith("not-json")


# ---------------- query ----------------

def test_query_filters_and_orders_newest_first(ledger_home):
    sl.append_records([
        mk_row(verdict="fail", ts=iso(NOW - 5000), source="inspection"),
        mk_row(verdict="pass", ts=iso(NOW - 100), source="inspection"),
        mk_row(verdict="pass", scenario="s2"),
    ])
    hits, bad = sl.query_rows(COMMIT, "s1")
    assert len(hits) == 2 and bad == []
    assert hits[0]["verdict"] == "pass" and hits[1]["verdict"] == "fail"
    hits_other, _ = sl.query_rows("ff" * 20, "s1")
    assert hits_other == []


def test_cli_query_explicit_no_record(tmp_path, ledger_home):
    """票据②红线：无记录必须显式回「无记录」并声明 90 天窗，不得静默回绿。"""
    p = subprocess.run(
        [sys.executable, str(MOD), "query", "--commit", COMMIT,
         "--scenario", "s1", "--json"],
        capture_output=True, text=True, timeout=60,
        env=dict(os.environ, **{sl.LEDGER_DIR_ENV: str(ledger_home)}))
    assert p.returncode == 0, p.stderr
    doc = json.loads(p.stdout)
    assert doc["answer"] == "无记录" and doc["records"] == []
    assert doc["window_days"] == sl.DEFAULT_KEEP_DAYS


def test_cli_query_hit_prints_five_elements(tmp_path, ledger_home):
    """票据②：输出含判定、时间、来源、指纹、并发宽度五要素。"""
    sl.append_records([mk_row(verdict="fail", source="lane:t9", ticket="t9")])
    p = subprocess.run(
        [sys.executable, str(MOD), "query", "--commit", COMMIT, "--scenario", "s1"],
        capture_output=True, text=True, timeout=60,
        env=dict(os.environ, **{sl.LEDGER_DIR_ENV: str(ledger_home)}))
    assert p.returncode == 0, p.stderr
    out = p.stdout
    for frag in ("verdict=fail", "ts=", "source=lane:t9", "env_fp=" + FP,
                 "conc_width=4"):
        assert frag in out, frag


def test_cli_query_requires_args(tmp_path, ledger_home):
    p = subprocess.run([sys.executable, str(MOD), "query", "--commit", COMMIT],
                       capture_output=True, text=True, timeout=60,
                       env=dict(os.environ, **{sl.LEDGER_DIR_ENV: str(ledger_home)}))
    assert p.returncode == 2


def test_cli_path_and_stats(tmp_path, ledger_home):
    sl.append_records([mk_row()])
    p = subprocess.run([sys.executable, str(MOD), "path"], capture_output=True,
                       text=True, timeout=60,
                       env=dict(os.environ, **{sl.LEDGER_DIR_ENV: str(ledger_home)}))
    assert p.returncode == 0 and p.stdout.strip() == str(sl.ledger_path())
    p = subprocess.run([sys.executable, str(MOD), "stats"], capture_output=True,
                       text=True, timeout=60,
                       env=dict(os.environ, **{sl.LEDGER_DIR_ENV: str(ledger_home)}))
    doc = json.loads(p.stdout)
    assert doc["rows"] == 1 and doc["bytes"] > 0


# ---------------- 保留（按月上卷 + 90 天） ----------------

def test_plan_retention_keeps_undatable_rows():
    plan = sl.plan_retention([mk_row(ts=None)], NOW)
    assert plan["keep"] and not plan["retire"]


def test_rollup_moves_aged_rows_dedupes_and_is_idempotent(ledger_home):
    # 预置新鲜标记：挡住 seed append 的机会性触发（本测试专测显式 rollup）
    mark = ledger_home / sl.ROLLUP_MARK
    mark.write_text("1\n", encoding="utf-8")
    os.utime(str(mark), (NOW - 3600, NOW - 3600))
    old_key_a = mk_row(verdict="fail", ts=iso(NOW - 100 * 86400))
    old_key_a_newer = mk_row(verdict="pass", ts=iso(NOW - 99 * 86400))
    fresh = mk_row(ts=iso(NOW - 86400))
    sl.append_records([old_key_a, old_key_a_newer, fresh], now=NOW)
    assert len(sl.read_rows()[0]) == 3, "标记新鲜：seed 完整"
    out = sl.rollup(now=NOW, path=sl.ledger_path())
    assert out["rolled_up"] == 2 and out["kept"] == 1
    rows, _ = sl.read_rows()
    assert [r["verdict"] for r in rows] == ["pass"], "主账只余窗口内行"
    month = time.strftime("%Y%m", time.localtime(NOW - 100 * 86400))
    mfile = ledger_home / ("scenario-results-%s.jsonl" % month)
    assert mfile.exists()
    merged = [json.loads(x) for x in mfile.read_text(encoding="utf-8").splitlines() if x]
    assert len(merged) == 1 and merged[0]["verdict"] == "pass", "同键保最新"
    out2 = sl.rollup(now=NOW, path=sl.ledger_path())
    assert out2["rolled_up"] == 0, "重跑幂等"


def test_append_opportunistic_rollup_respects_marker(ledger_home):
    """标记新鲜（<24h）→ append 不触发 rollup；标记过期 → append 触发（老行卷出）。"""
    mark = ledger_home / sl.ROLLUP_MARK
    mark.write_text("1\n", encoding="utf-8")
    os.utime(str(mark), (NOW - 3600, NOW - 3600))  # 新鲜：1h 前
    sl.append_records([mk_row(verdict="fail", ts=iso(NOW - 100 * 86400))], now=NOW)
    rows, _ = sl.read_rows()
    assert len(rows) == 1, "标记新鲜：老行暂留主账"
    # s2/s3 是「应留」的窗口内行：ts 必须显式落在 NOW 的 90 天窗内（mk_row 默认
    # ts=2026-09-21，距 NOW≈116 天=超窗——原数据让 rollup 把它们当老行卷光，
    # rows==[] 与断言「3→2」自相矛盾；测试数据缺陷修复，断言语义不变）。
    sl.append_records([mk_row(scenario="s2", ts=iso(NOW - 86400))], now=NOW)
    rows, _ = sl.read_rows()
    assert len(rows) == 2, "标记仍新鲜：不触发 rollup"
    os.utime(str(mark), (NOW - 25 * 3600, NOW - 25 * 3600))  # 过期 → 触发
    sl.append_records([mk_row(scenario="s3", ts=iso(NOW - 86400))], now=NOW)
    rows, _ = sl.read_rows()
    assert len(rows) == 2, "触发后老行已卷出（3→2）"


# ---------------- 并发（flock 序列化，零丢行） ----------------

_CHILD_SCRIPT = r'''
import importlib.util, os, sys
spec = importlib.util.spec_from_file_location("sl_child", sys.argv[1])
sl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sl)
w = sys.argv[3]
for i in range(5):
    row = {"ts": "2026-09-21T08:00:00+00:00", "commit": "ab" * 20,
           "env_fp": "cd" * 32, "conc_width": 4, "pool": "main",
           "scenario": "s-%s-%d" % (w, i), "verdict": "pass", "wall_s": 1.0,
           "source": "lane:t%s" % w, "ticket": "t%s" % w,
           "run": "run-" + "A" * 26}
    rcpt = sl.append_records([row])
    assert rcpt["written"] == 1, rcpt
print("ok")
'''


def test_concurrent_append_zero_loss(ledger_home):
    """8 个并发写者 × 5 行（flock+O_APPEND）：零丢行、零坏行。"""
    procs = []
    for w in range(8):
        procs.append(subprocess.Popen(
            [sys.executable, "-c", _CHILD_SCRIPT, str(MOD),
             str(ledger_home), str(w)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            env=dict(os.environ, **{sl.LEDGER_DIR_ENV: str(ledger_home)})))
    for p in procs:
        out, err = p.communicate(timeout=60)
        assert p.returncode == 0, err[-300:]
    rows, bad = sl.read_rows()
    assert bad == [] and len(rows) == 40, "8 写者 × 5 行并发零丢零畸"


# ---------------- 体积口径（271 行/轮；预算锚实测） ----------------

def test_271_rows_size_under_budget():
    """体积口径：271 行/整轮保持小文件（按月上卷+90 天的容量前提）。
    预算锚实测（20260922 implement gen2）：真实行形（40hex commit+64hex env_fp
    +带时区秒级 ts+真实长度场景名 35 字+lane:<票> 来源+票号）validate 通过后
    实测 327 B/行 → 271 行 ≈ 86.5 KB/轮。原 64KB 预算是票面「≈55KB」估算的
    机械锚，被实测推翻（连旧用例的短名形都 74KB）——按票面「须在票面记录实测」
    改锚实测：预算 128KB ≈ 483 B/行（≈1.5× 实测最宽形，覆盖更长场景名/票号
    漂移），非无据放宽；单行仍受 MAX_ROW_BYTES 硬帽。"""
    def _row(i):
        return {"ts": "2026-09-22T14:30:00+08:00",
                "commit": "%03d" % i + "ab" * 18 + "a",   # 40hex
                "env_fp": "cd" * 32, "conc_width": 4, "pool": "content",
                "scenario": "t260916-25-stage-console-lifecycle",
                "verdict": "env_fail", "wall_s": 123.4,
                "source": "lane:t260922-12", "ticket": "t260922-12",
                "run": "run-" + "A" * 26}
    clean, why = sl.validate_row(_row(0))
    assert clean is not None and why is None, "行形必须过封闭校验（测真实形）"
    blobs = [sl._dumps(_row(i)).encode("utf-8") for i in range(271)]
    per_row = max(len(b) for b in blobs)
    total = sum(len(b) + 1 for b in blobs)
    assert per_row <= sl.MAX_ROW_BYTES, per_row
    assert total < 128 * 1024, (total, per_row)
