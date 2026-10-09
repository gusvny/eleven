#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_run_record_store.py —— t261009-11 run 记录的账本契约面（灰盒 L2，离线秒级）。

intent（用户可感知行为；真源=票面 + docs/reference/ledger-record-models-v1.md §A
「certification has to cite one run and read its counts from that record」）：
  锁账本公开面上的 run 记录契约——用户（闸、裁审、任何读账的消费者）从此可以
  「引用一次 run，并从那份记录里读计数」：
    A. 身份铸造无协调：`run-` + ULID 形状；同进程两次铸造必不同；同一毫秒内
       铸造保持单调（字典序即时间序）；不同毫秒铸造按时序排列。
    B. 一轮一份头记录：行带 run 盖章后，头记录落盘且可读回；
       rows_for_run 返回该 run 的行、头与状态（headered）。
    C. 计数必须可从行推导并对得上：头里计数与行重数不符（和数合法、重数不符
       这一形）→ 按名拒写，两个账文件逐字节不动（脏记录比无记录更坏）。
    D. run id 不得重复：同 id 第二份头按名拒。
    E. verdict 是计数的机械卷积：ran=0 的红头在写面按名拒（ran:0 永非证明，
       §A）；verdict 与计数矛盾的头在校验面按名拒。
    F. 畸形输入按名拒，绝不猜：非对象头/缺字段/env_fp 非 64hex/负计数/
       started_at 非整数毫秒/conc_width 非 ≥1 整数/verdict 非词表。
    G. 旧行（无 run）保持可读：混账里 query 照常命中；derive/rows_for_run
       把 legacy 计数显式交出、绝不静默并入；**消费者要 run 而账里没有 →
       按名响亮报错，绝不猜**（票面原文「fail loudly rather than guess」）。
    H. 中断态可见：有行有 run、无头 = 中断的一轮——rows_for_run 报 state=
       interrupted、header=None，require_run_rows 对它按名拒（§A「a state to
       see rather than a summary to invent」）。
    I. 保留窗卷出不丢 run：>90 天的行卷进月卷后 run 字段逐字保留；主账留存
       行的 run 原样。
    J. 查询 CLI：`runs --json` 面能读回头记录（维护/查询对等）。

分层与 intent 分工（防重复）：
  · 头/行的白盒真值表、ULID 单元细节 → developer L1（integration/tests/
    test_t261009_11_run_records.py，随实现交付），本场景不重测；
  · 采信边界（指纹相等+commit 祖先+≤7 天+宽一致）→ failure_protocol.ledger_trust
    与 t260922-12 家族，本条不触碰（run id 与采信判据正交）；
  · 台账绿行复用 → t260930-01-ledger-reuse-round（判据四键），本条只锁 run
    身份面，复用路径不需要 run id（legacy 行继续可用）正是 G 的断言之一；
  · 双驱动旅程（runner 顶驱 / 闸-owned 抑制 / 闸头记录）→ 同票
    sc_run_record_drivers.py（L3），本条只锁库与 CLI 面。

安全红线：账目录经 SANDBAR_SCENARIO_LEDGER_DIR 与 path= 双路投到本场景私有
临时目录（真账零写入）；零 docker、零 Temporal、零端口、零控制台（永不接触
3099）；临时目录 finally+atexit 双路回收。纯 stdlib 恒可跑。
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
NAME = "t261009-11-run-record-store"

sys.path.insert(0, str(REPO / "integration"))
import scenario_ledger as sl  # noqa: E402

from lib_result import ScenarioCheck  # noqa: E402

_ck = ScenarioCheck(detail_cap=600, flush=True)
ok = _ck.ok
finish = _ck.finish
env_fail = _ck.env_fail

_TMP = None
RUNS_FILE = None
_RECLAIMED = False


def _cleanup():
    global _RECLAIMED
    if _RECLAIMED:
        return
    _RECLAIMED = True
    if _TMP is not None:
        shutil.rmtree(str(_TMP), ignore_errors=True)


atexit.register(_cleanup)


# ---------------------------------------------------------------- 夹具

_C = "a" * 40
_FP = "b" * 64


def _row(run=None, scenario="s1", verdict="pass", ts=None):
    r = {
        "ts": ts or "2026-10-09T00:00:00+00:00",
        "commit": _C, "env_fp": _FP, "conc_width": 1,
        "pool": "ro", "scenario": scenario, "verdict": verdict,
        "wall_s": 0.01, "source": "baseline", "ticket": "",
    }
    if run is not None:
        r["run"] = run
    return r


def _hdr(run, ran=3, passed=2, failed=1, env_failed=0, verdict="red",
         **over):
    h = {
        "v": sl.RUN_HEADER_V,
        "id": run,
        "repos": [{"repo": "sandbar", "revision": _C}],
        "suite": "full", "source": "lane:t261009-11", "env_fp": _FP,
        "conc_width": 1, "pool": "ro",
        "started_at": 1791506200000, "duration_s": 1.5,
        "cases": {"ran": ran, "passed": passed, "failed": failed,
                  "env_failed": env_failed},
        "verdict": verdict,
    }
    h.update(over)
    return h


def _call(fn, *a, **k):
    """调 API：返回 (raised, exc, result)——红要红得点名（异常类型与文案也是
    本场景的断言对象，不许静默吞）。"""
    try:
        return (None, None, fn(*a, **k))
    except Exception as e:  # noqa: BLE001
        return (type(e).__name__, e, None)


def _append_header(hdr):
    """头写面是回执制：返回 (written, [reason…])——拒写理由点名在回执里。"""
    rec = sl.append_run_header(hdr, path=RUNS_FILE)
    return (rec.get("written", 0),
            [r.get("reason", "") for r in rec.get("rejected", ())])


# ---------------------------------------------------------------- 主程序

def main():
    global _TMP
    tmp = Path(tempfile.mkdtemp(prefix="t261009-11-store-"))
    _TMP = tmp
    led = tmp / "ledger"
    led.mkdir()
    os.environ["SANDBAR_SCENARIO_LEDGER_DIR"] = str(led)
    global RUNS_FILE
    RUNS_FILE = led / sl.RUNS_NAME
    main_path = led / "scenario-results.jsonl"
    runs_path = led / sl.RUNS_NAME

    # ---------------- A 身份铸造：无协调、带时、同毫秒单调 ----------------
    exc, e, r1 = _call(sl.mint_run_id)
    if exc:
        ok(False, "A0 mint_run_id 可用", "%s: %s" % (exc, e))
        finish(NAME)
    ok(bool(r1) and r1.startswith("run-") and len(r1) == 4 + 26
       and all(ch in "0123456789ABCDEFGHJKMNPQRSTVWXYZ" for ch in r1[4:]),
       "A1 id 形状 = run- + 26 位 Crockford base32", "got %r" % (r1,))
    r2 = sl.mint_run_id()
    ok(r1 != r2, "A2 同进程两次铸造必不同（80 随机位+单调尾）",
       "%r == %r" % (r1, r2))
    t = 1791506200000
    m1, m2 = sl.mint_run_id(at_ms=t), sl.mint_run_id(at_ms=t)
    ok(m1 < m2, "A3 同一毫秒内铸造字典序严格递增（单调尾，不靠时钟赛跑）",
       "%s !< %s" % (m1, m2))
    m3 = sl.mint_run_id(at_ms=t + 1000)
    ok(m1 < m3 and m2 < m3, "A4 后毫秒铸造排在前面之后（字典序即时间序）",
       "%s/%s vs %s" % (m1, m2, m3))

    # ---------------- B 一轮一份头：落盘、读回、按 run 取行 ----------------
    run_id = sl.mint_run_id(at_ms=t)
    rows = [_row(run=run_id, scenario="s%d" % i, verdict=v)
            for i, v in enumerate(("pass", "pass", "fail"))]
    rec = sl.append_records(rows, path=main_path)
    ok(rec.get("written") == 3, "B1 带 run 盖章的三行落账", json.dumps(rec)[:200])
    w, whys = _append_header(_hdr(run_id))
    ok(w == 1 and not whys, "B2 计数与行重数相符的头落盘",
       "written=%s rejected=%s" % (w, whys))
    ok(runs_path.is_file(), "B3 头记录文件在账目录内（%s）" % sl.RUNS_NAME)
    headers, bad_h = sl.read_runs(path=RUNS_FILE)
    ok(len(headers) == 1 and not bad_h
       and headers[0].get("id") == run_id,
       "B4 read_runs 读回恰一份头、id 对得上",
       "headers=%s bad=%s" % ([h.get("id") for h in headers], bad_h))
    face = sl.rows_for_run(run_id, path=RUNS_FILE)
    ok(exc is None and len(face.get("rows", ())) == 3
       and face.get("state") == "headered"
       and (face.get("header") or {}).get("id") == run_id,
       "B5 rows_for_run 交出该 run 的行+头+状态（headered）",
       "%s: %s" % (exc, json.dumps(face)[:200] if face else e))

    # ---------------- C 计数篡改按名拒、零落盘 ----------------
    # 和数合法（3=1+2+0）但与行重数（2 pass + 1 fail）不符——专打「重数核对」
    # 这一环，不是形状校验（形状由 F 段专打）。用另一个 id+它自己的三行，
    # 免得撞上 D 段的重复 id 拒（拒因会盖住本条要打的核对环）。
    rid_t = sl.mint_run_id(at_ms=t + 1)
    sl.append_records([_row(run=rid_t, scenario="t%d" % i, verdict=v)
                       for i, v in enumerate(("pass", "pass", "fail"))],
                      path=main_path)
    before_runs = runs_path.read_bytes()
    before_main = main_path.read_bytes()
    w, whys = _append_header(_hdr(rid_t, passed=1, failed=2,
                                  env_failed=0))
    ok(w == 0 and any("counts_mismatch" in r for r in whys),
       "C1 头计数与行重数不符 → 按名拒（counts_mismatch 族）",
       "written=%s rejected=%s" % (w, whys))
    ok(runs_path.read_bytes() == before_runs,
       "C2 被拒的头零落盘（%s 逐字节不动）" % sl.RUNS_NAME, "")
    ok(main_path.read_bytes() == before_main,
       "C3 被拒的批次零落盘（主账逐字节不动）", "")

    # ---------------- D run id 重复按名拒 ----------------
    w, whys = _append_header(_hdr(run_id))
    ok(w == 0 and any("duplicate_run_id" in r for r in whys),
       "D1 同 id 第二份头（对已存在头）按名拒",
       "written=%s rejected=%s" % (w, whys))

    # ---------------- E verdict = 计数的机械卷积 ----------------
    rid0 = sl.mint_run_id(at_ms=t + 2)
    w, whys = _append_header(_hdr(rid0, ran=0, passed=0, failed=0,
                                  verdict="red"))
    ok(w == 0 and any("ran_zero" in r for r in whys),
       "E1 ran=0 的头在写面按名拒（ran:0 永非证明，§A）",
       "written=%s rejected=%s" % (w, whys))
    # 此条专打 verdict 卷积面（校验层）：全零计数+green 的头，机械卷积是 red，
    # 报 green 即矛盾 → 校验面按名拒。
    w, whys = _append_header(
        _hdr(sl.mint_run_id(at_ms=t + 4), ran=0, passed=0, failed=0,
             verdict="green"))
    ok(w == 0 and any("verdict_not_rollup" in r for r in whys),
       "E2 verdict 与计数矛盾（全零却报 green）在校验面按名拒",
       "written=%s rejected=%s" % (w, whys))

    # ---------------- F 畸形头按名拒 ----------------
    _good = _hdr(rid0)
    bad_hdrs = [
        ("F1 非对象头", "not-a-dict"),
        ("F2 缺字段（env_fp）",
         {k: v for k, v in _good.items() if k != "env_fp"}),
        ("F3 env_fp 非 64hex", _hdr(rid0, env_fp="xyz")),
        ("F4 负计数", _hdr(rid0, ran=-1)),
        ("F5 started_at 非整数毫秒", _hdr(rid0, started_at=1.5)),
        ("F6 conc_width 非 ≥1 整数", _hdr(rid0, conc_width=0)),
        ("F7 verdict 非词表", _hdr(rid0, verdict="maybe")),
    ]
    for label, bad in bad_hdrs:
        w, whys = _append_header(bad)
        ok(w == 0 and whys, label + " → 按名拒",
           "written=%s rejected=%s" % (w, whys))

    # ---------------- G 旧行（无 run）可读；要 run 而没有 → 响亮 ----------------
    legacy = [_row(scenario="legacy-a"), _row(scenario="legacy-b",
                                              verdict="fail")]
    with open(str(main_path), "a", encoding="utf-8") as fh:
        for r in legacy:
            fh.write(json.dumps(r, ensure_ascii=False,
                                separators=(",", ":")) + "\n")
    all_rows, bad = sl.read_rows(path=main_path)
    ok(len(all_rows) >= 5 and not bad, "G1 混账读回：旧行不丢不坏",
       "rows=%d bad=%s" % (len(all_rows), bad))
    hits, bad2 = sl.query_rows(_C, "legacy-a", path=main_path)
    ok(len(hits) == 1 and not bad2,
       "G2 旧行的既有键查询照常命中（复用路径不受影响）",
       "hits=%d bad=%s" % (len(hits), bad2))
    counts, legacy_n = sl.derive_counts(all_rows, run_id)
    ok(legacy_n >= 2 and counts["ran"] == 3,
       "G3 legacy 行显式计数交出、绝不并入 run 的重数",
       "counts=%s legacy=%s" % (counts, legacy_n))
    exc, e, _ = _call(sl.require_run_rows, "run-ABSENT-NO-SUCH-LEG",
                      path=RUNS_FILE)
    ok(exc is not None and "run" in str(e).lower(),
       "G4 消费者要 run、行里没有 → 按名响亮报错，绝不猜",
       "raised=%s: %s" % (exc, e))

    # ---------------- H 中断态可见：有行无头 ----------------
    orphan = sl.mint_run_id(at_ms=t + 5)
    rec_o = sl.append_records([_row(run=orphan, scenario="interrupted")],
                              path=main_path)
    ok(rec_o.get("written") == 1, "H1 中断轮的行先落（头缺席前的真实时序）",
       json.dumps(rec_o)[:160])
    face = sl.rows_for_run(orphan, path=RUNS_FILE)
    ok(face.get("state") == "interrupted"
       and face.get("header") is None and len(face.get("rows", ())) == 1,
       "H2 中断态被读面点名为 interrupted + header=None（可见状态，"
       "不是编出来的汇总）",
       "face=%s" % json.dumps(face)[:300])
    exc, e, _ = _call(sl.require_run_rows, orphan, path=RUNS_FILE)
    ok(exc is not None and "header" in str(e).lower(),
       "H3 消费者对中断轮引用 → 按名拒（counts 无法对证于不存在的头）",
       "raised=%s: %s" % (exc, e))

    # ---------------- I 保留窗卷出不丢 run ----------------
    old_ts = time.strftime("%Y-%m-%dT00:00:00+00:00",
                           time.gmtime(time.time() - 120 * 86400))
    old_run = sl.mint_run_id(at_ms=t + 6)
    sl.append_records([_row(run=old_run, scenario="old-row", ts=old_ts)],
                      path=main_path)
    exc, e, _ = _call(sl.rollup, now=time.time(), keep_days=90,
                      path=main_path)
    ok(exc is None, "I1 rollup 照常执行", "%s: %s" % (exc, e))
    month_files = list(led.glob("scenario-results-*.jsonl"))
    moved_ok = False
    for mf in month_files:
        for ln in mf.read_text(encoding="utf-8").splitlines():
            if ln.strip() and json.loads(ln).get("scenario") == "old-row":
                moved_ok = json.loads(ln).get("run") == old_run
    ok(moved_ok, "I2 卷进月卷的行 run 字段逐字保留",
       "month_files=%s" % [m.name for m in month_files])
    kept = sl.read_rows(path=main_path)[0]
    kept_runs = {r.get("run") for r in kept if r.get("scenario") == "s1"}
    ok(run_id in kept_runs, "I3 主账留存行的 run 原样",
       "kept_runs=%s" % kept_runs)

    # ---------------- J 查询 CLI 面 ----------------
    p = subprocess.run([sys.executable, str(REPO / "integration"
                                                / "scenario_ledger.py"),
                        "runs", "--json", "--ledger", str(RUNS_FILE)],
                       capture_output=True, text=True, timeout=60)
    cli_ok = False
    if p.returncode == 0:
        try:
            cli = json.loads(p.stdout)
            lst = cli.get("runs") if isinstance(cli, dict) else cli
            cli_ok = any(h.get("id") == run_id for h in lst)
        except ValueError:
            cli_ok = False
    ok(cli_ok, "J1 CLI runs --json 读回头记录（与库面同一真源）",
       "rc=%s out=%s err=%s" % (p.returncode, p.stdout[:200], p.stderr[:200]))

    finish(NAME)


if __name__ == "__main__":
    main()
