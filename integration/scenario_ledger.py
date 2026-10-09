#!/usr/bin/env python3
"""scenario_ledger —— 集成门结果台账（t260922-12）：按提交记账 + 查询 + 保留。

真源（唯一）：~/.sandbar/projects/sandbar/ledger/scenario-results.jsonl
（机器级、仓外——不进泳道工作区（撞 merge_check「工作区干净」判据，t260922-02
实例）、不入库（并发写=冲突=返工）、不被夹具复制（408GB 事故的乘法）。目录可被
SANDBAR_SCENARIO_LEDGER_DIR 整体覆盖（测试隔离缝，同 SANDBAR_INSPECTION_DIR 先例）。

格式：append-only JSONL，行=一次场景判定，十一字段封闭 schema：
  ts(ISO8601 带时区) commit(40hex) env_fp(64hex) conc_width(int>=1)
  pool(场景所属池) scenario(非空) verdict(pass|fail|env_fail|skip)
  wall_s(number|null) source(lane:<票>|inspection|baseline) ticket(str)
  run(run-<ULID>，t261009-11：行所属的那次套件跑；存量行无此键=legacy 照读)
键=(commit, env_fp, conc_width, scenario)：任一缺失/畸形/多字段/超行宽 → 拒写
（脏记录比无记录更坏）；全拒的批次零落盘（不建文件）。

run 记录（t261009-11）：每次套件跑收口一行 header，落同目录 runs.jsonl
（同锁），字段见 RUN_HEADER_FIELDS（v=run-ledger-v1；verdict=counts 的机械
roll-up；写前按主账重数该 run 的行，counts 对不上或行零在=响亮拒写；
line 字段暂缺=具名欠账——树里尚无 line 身份可填）。

写入面（单写者纪律）：唯一写者=闸（server/tools/verify_lane.py）——lane/巡检/
基线三路都经 lane=integ 收口。本模块提供被闸按文件位装载的库面与本 CLI（查询/
维护），自身不做第二写者入口。

判定消费纪律：本模块只存取不判定——采信边界（指纹相等+commit 祖先或相同+
<=7 天+width 一致）全在引擎纯函数面（failure_protocol.ledger_trust）；读取面
不可信（畸形行）时逐行点名不静默，闸侧回退实跑（fail-closed，无「查不到当绿」）。

保留：>90 天的行按月卷出（scenario-results-<YYYYMM>.jsonl，同键保最新），主账
原子重写（tmp+os.replace）；append 路径按 .last-rollup 标记机会性触发（>24h 一次）；
并发：主账 append 与 rollup 全程 flock（<dir>/.lock）序列化，append 批内一次持锁。

CLI（cwd 任意）：
  python3 integration/scenario_ledger.py query --commit <sha> --scenario <名>
        [--limit 20] [--json] [--ledger P]
  python3 integration/scenario_ledger.py rollup [--keep-days 90] [--ledger P]
  python3 integration/scenario_ledger.py path
  python3 integration/scenario_ledger.py stats
查询只查主账（90 天窗）——更老的行已月卷外移，「无记录」文案显式声明这一点
（不冒充「从未跑过」；查月卷走 stats/直接读月文件）。
"""
import datetime as _dt
import fcntl  # 无 fcntl 的平台不在本仓支持面（无锁 append=并发撕裂，宁拒不写）
import json
import os
import secrets
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
# 本文件在 <仓根>/integration/ 一级深度：仓根=HERE.parent。P2（仲裁 gen1）：原
# parent.parent 错跳一级落仓外 .lane/，独立 CLI 与 standalone import 的
# failure_protocol 装载全炸（闸进程内侥幸靠 sys.modules 命中不显）。
REPO = HERE.parent

LEDGER_DIR_ENV = "SANDBAR_SCENARIO_LEDGER_DIR"
MAIN_NAME = "scenario-results.jsonl"
LOCK_NAME = ".lock"
ROLLUP_MARK = ".last-rollup"
ROLLUP_MIN_INTERVAL_S = 24 * 3600
DEFAULT_KEEP_DAYS = 90
MAX_ROW_BYTES = 2048
ROW_FIELDS = ("ts", "commit", "env_fp", "conc_width", "pool", "scenario",
              "verdict", "wall_s", "source", "ticket", "run")
_HEX = "0123456789abcdef"

# ---- run records (t261009-11): one header per suite run, cited by its rows ----
#: The runs file lives beside the main ledger, under the same lock. Headers are
#: few (one per executed run), so they have no rollup of their own.
RUNS_NAME = "scenario-runs.jsonl"
#: Shape version carried by every header (record-models convention: a record
#: carries the version of its own shape).
RUN_HEADER_V = "run-ledger-v1"
#: Mechanical roll-up: green iff ran > 0 and nothing failed. `ran: 0` is never
#: a proof (ledger-record-models-v1 §A).
RUN_HEADER_VERDICTS = ("green", "red")
#: Suite vocabulary from the design; a narrowed/diagnostic round writes no
#: header at all rather than wearing a suite it did not run.
RUN_SUITES = ("full", "fast-set")
#: `line` is deliberately absent from the schema (named debt, not an oversight):
#: no line identity exists anywhere in the tree today, so no driver could fill
#: it without inventing a value. Adding it later is a v bump (RUN_HEADER_V).
RUN_HEADER_FIELDS = ("v", "id", "repos", "suite", "source", "env_fp",
                     "conc_width", "pool", "started_at", "duration_s",
                     "cases", "verdict")
RUN_CASE_FIELDS = ("ran", "passed", "failed", "env_failed")


def ledger_dir():
    """台账目录：SANDBAR_SCENARIO_LEDGER_DIR 覆盖 > ~/.sandbar/projects/sandbar/ledger
    （票据①写死的项目位；覆盖缝仅供测试/多项目未来，不接注册表——越界不做的）。"""
    env = os.environ.get(LEDGER_DIR_ENV)
    if env:
        return Path(env)
    return Path.home() / ".sandbar" / "projects" / "sandbar" / "ledger"


def ledger_path():
    """主账文件路径。"""
    return ledger_dir() / MAIN_NAME


def _fp_mod():
    """引擎协议库懒装载（verdict 词表单一真源）。本模块只在本仓树内被装载
    （闸按泳道树文件位装载、CLI 在仓内跑），协议库必在；缺席=ImportError 响亮。"""
    engine = str(REPO / "server" / "engine")
    if engine not in sys.path:
        sys.path.insert(0, engine)
    import failure_protocol
    return failure_protocol


def _ts_epoch(value):
    """ISO8601（须带时区）→ epoch 秒；判不了 → None（不猜时区）。"""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        d = _dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        return None
    return d.timestamp()


def validate_row(row):
    """十字段封闭校验。返回 (clean_row, None) 或 (None, reason)。
    缺键/多键/类型错/verdict 非法/键字段（commit/env_fp/conc_width/scenario）缺
    损/超行宽 → 拒（调用方逐条点名）。"""
    if not isinstance(row, dict):
        return None, "row_not_dict"
    extra = sorted(set(row) - set(ROW_FIELDS))
    if extra:
        return None, "unknown_fields:%s" % ",".join(extra)
    missing = [f for f in ROW_FIELDS if f not in row]
    if missing:
        return None, "missing_fields:%s" % ",".join(missing)
    if _ts_epoch(row["ts"]) is None:
        return None, "ts_not_iso8601_with_tz"
    c = row["commit"]
    if not isinstance(c, str) or len(c) != 40 or any(ch not in _HEX for ch in c):
        return None, "commit_not_sha1"
    e = row["env_fp"]
    if not isinstance(e, str) or len(e) != 64 or any(ch not in _HEX for ch in e):
        return None, "env_fp_not_sha256"
    w = row["conc_width"]
    if isinstance(w, bool) or not isinstance(w, int) or w < 1:
        return None, "conc_width_not_positive_int"
    if not isinstance(row["pool"], str):
        return None, "pool_not_str"
    if not isinstance(row["scenario"], str) or not row["scenario"].strip():
        return None, "scenario_empty"
    if row["verdict"] not in _fp_mod().LEDGER_VERDICTS:
        return None, "verdict_invalid:%s" % (row["verdict"],)
    ws = row["wall_s"]
    if ws is not None and (isinstance(ws, bool) or not isinstance(ws, (int, float))):
        return None, "wall_s_not_number"
    src = row["source"]
    src_ok = (src == "baseline" or src == "inspection"
              or (isinstance(src, str) and src.startswith("lane:") and len(src) > 5))
    if not src_ok:
        return None, "source_invalid:%s" % (src,)
    if not isinstance(row["ticket"], str):
        return None, "ticket_not_str"
    # t261009-11: every new row names its run. Write-side requires it; readers
    # keep tolerating its absence (rows already on disk are legacy and stay
    # readable — never rewritten).
    run = row["run"]
    if not isinstance(run, str) or not run.startswith("run-") or len(run) < 5:
        return None, "run_not_run_id"
    return dict(row), None


def _check_source(value):
    """Shared source-vocabulary check (case rows and run headers use one set)."""
    return (value == "baseline" or value == "inspection"
            or (isinstance(value, str) and value.startswith("lane:")
                and len(value) > 5))


def _acquire_lock(target):
    target.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(target.parent / LOCK_NAME), os.O_RDWR | os.O_CREAT, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX)
    return fd


def _release_lock(fd):
    if fd is None:
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _dumps(row):
    return json.dumps(row, ensure_ascii=False, separators=(",", ":"))


def append_records(rows, path=None, now=None):
    """校验+成批追加（单次 write + fsync，flock 序列化——多泳道闸并发写安全）。
    返回 {"written": n, "rejected": [{"index","reason"}...]}。全部被拒 → 零落盘
    （不建文件）；至少一条合法才动主账。写完按 .last-rollup 标记机会性触发保留。"""
    target = Path(path) if path else ledger_path()
    clean, rejected = [], []
    for i, r in enumerate(rows or []):
        c, why = validate_row(r)
        if c is None:
            rejected.append({"index": i, "reason": why})
            continue
        blob = _dumps(c)
        if len(blob.encode("utf-8")) > MAX_ROW_BYTES:
            rejected.append({"index": i, "reason": "row_too_big"})
            continue
        clean.append(blob)
    receipt = {"written": 0, "rejected": rejected}
    if not clean:
        return receipt
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = ("\n".join(clean) + "\n").encode("utf-8")
    lock = _acquire_lock(target)
    try:
        fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)
        receipt["written"] = len(clean)
    finally:
        _release_lock(lock)
    _maybe_rollup(target, now=now)
    return receipt


def read_rows(path=None):
    """读主账 → (rows, bad 样本[:10])。文件缺席=空账（新机器，非错误）；
    单行畸形/非对象 → 计入 bad（读取面不可信必须可观测，不静默吞）。"""
    target = Path(path) if path else ledger_path()
    rows, bad = [], []
    try:
        with open(str(target), encoding="utf-8") as fh:
            for ln in fh:
                s = ln.strip()
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                except ValueError:
                    bad.append(s[:160])
                    continue
                if isinstance(obj, dict):
                    rows.append(obj)
                else:
                    bad.append(s[:160])
    except FileNotFoundError:
        return [], []
    except IsADirectoryError:
        bad.append("主账路径是目录：%s" % target)
        return [], bad
    return rows, bad[:10]


def query_rows(commit, scenario, path=None):
    """commit+scenario 全键匹配行，ts 新→旧。畸形行照 read_rows 口径点名。"""
    rows, bad = read_rows(path)
    hits = [r for r in rows
            if r.get("commit") == commit and r.get("scenario") == scenario]
    hits.sort(key=lambda r: (_ts_epoch(r.get("ts")) or 0.0), reverse=True)
    return hits, bad


def plan_retention(rows, now_epoch, keep_days=DEFAULT_KEEP_DAYS):
    """纯函数：>keep_days 的行按月（ts 本地年月）分组。ts 判不了的行**保留**
    （不销毁判不了账期的数据——宁可多留不可误删）。"""
    cutoff = float(now_epoch) - int(keep_days) * 86400
    retire, keep = {}, []
    for r in rows:
        ts = _ts_epoch(r.get("ts"))
        if ts is None or ts > cutoff:
            keep.append(r)
            continue
        month = _dt.datetime.fromtimestamp(ts).strftime("%Y%m")
        retire.setdefault(month, []).append(r)
    return {"keep": keep, "retire": retire}


def _merge_month_file(mpath, group):
    """月卷文件合并（同键保最新；group 按主账 ts 序遍历=后写覆盖即最新）。
    返回 (合并后行数, 本批卷入条数)。"""
    merged = {}
    if mpath.exists():
        with open(str(mpath), encoding="utf-8") as fh:
            for ln in fh:
                s = ln.strip()
                if not s:
                    continue
                try:
                    r = json.loads(s)
                except ValueError:
                    continue
                if isinstance(r, dict):
                    merged[(r.get("commit"), r.get("env_fp"),
                            r.get("conc_width"), r.get("scenario"))] = r
    moved = 0
    for r in group:
        merged[(r.get("commit"), r.get("env_fp"),
                r.get("conc_width"), r.get("scenario"))] = r
        moved += 1
    tmp = mpath.with_name(mpath.name + ".tmp")
    with open(str(tmp), "w", encoding="utf-8") as fh:
        for r in merged.values():
            fh.write(_dumps(r) + "\n")
    os.replace(str(tmp), str(mpath))
    return len(merged), moved


def rollup(now=None, keep_days=DEFAULT_KEEP_DAYS, path=None):
    """保留窗执行（票据①）：>keep_days 行按月卷出、主账原子重写。flock 全程
    持锁（与 append 互斥）。返回 {"rolled_up","months","kept"}。"""
    target = Path(path) if path else ledger_path()
    now = float(now) if now is not None else time.time()
    lock = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        lock = _acquire_lock(target)
        rows, _bad = read_rows(target)
        plan = plan_retention(rows, now, keep_days)
        moved, months = 0, {}
        for month, group in sorted(plan["retire"].items()):
            mpath = target.parent / ("scenario-results-%s.jsonl" % month)
            n_in_file, n_moved = _merge_month_file(mpath, group)
            months[month] = n_in_file
            moved += n_moved
        if moved:
            tmp = target.with_name(target.name + ".tmp")
            with open(str(tmp), "w", encoding="utf-8") as fh:
                for r in plan["keep"]:
                    fh.write(_dumps(r) + "\n")
            os.replace(str(tmp), str(target))
        return {"rolled_up": moved, "months": months,
                "kept": len(plan["keep"])}
    finally:
        _release_lock(lock)


def _maybe_rollup(target, now=None):
    """机会性触发（>24h 一次，append 收尾调用）：维护面失败响亮留痕不抬手
    ——最坏=主账变肥，窗口由下次触发或人工 rollup 补，不影响主账正确性。"""
    mark = target.parent / ROLLUP_MARK
    now = float(now) if now is not None else time.time()
    try:
        if mark.exists() and now - mark.stat().st_mtime < ROLLUP_MIN_INTERVAL_S:
            return None
    except OSError:
        pass
    try:
        out = rollup(now=now, path=target)
        with open(str(mark), "w", encoding="utf-8") as fh:
            fh.write("%d\n" % int(now))
        os.utime(str(mark), (now, now))
        return out
    except Exception as e:  # noqa: BLE001 —— 维护面失败响亮不抬手
        sys.stderr.write(
            "SCENARIO_LEDGER_WARN rollup 失败（%s: %s）——主账照常，保留窗待下次触发"
            "或人工 rollup\n" % (type(e).__name__, e))
        return None


# ---------------- run records (t261009-11) ----------------

class RunRecordError(Exception):
    """A consumer that needs a run id (or a run header) and does not find one.
    Raised, never guessed around: the missing identity is the answer."""


_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_LAST_MINT = {"ms": -1, "tail": 0}


def _ulid_tail_increment(tail):
    """Monotonic-mode step within one process: same millisecond increments the
    80-bit tail instead of re-randomising (two ids from one process cannot tie).
    Overflow (practically unreachable) falls back to the next millisecond."""
    tail += 1
    if tail >= (1 << 80):
        return None
    return tail


def _b32_80(tail):
    chars = []
    for shift in range(75, -1, -5):
        chars.append(_CROCKFORD[(tail >> shift) & 0x1F])
    return "".join(chars)


def _b32_48(ms):
    chars = []
    for shift in range(45, -1, -5):
        chars.append(_CROCKFORD[(ms >> shift) & 0x1F])
    return "".join(chars)


def mint_run_id(at_ms=None):
    """Mint `run-<ULID>`: 48-bit millisecond timestamp + 80 random bits,
    Crockford base32 — the ULID shape self-implemented from stdlib primitives
    (time + secrets; no third-party dependency). Time ids need no coordination:
    uniqueness rides on the random tail, ordering on the timestamp. Monotonic
    within this process: when the millisecond repeats (or a caller passes an
    older instant than the last mint — the clock-skew floor), the tail
    increments instead of re-randomising, so two ids from one process never
    tie and never order backwards."""
    ms = int(at_ms) if at_ms is not None else int(time.time() * 1000)
    if ms <= _LAST_MINT["ms"]:
        ms = _LAST_MINT["ms"]
        tail = _ulid_tail_increment(_LAST_MINT["tail"])
        if tail is None:
            ms += 1
            tail = int.from_bytes(secrets.token_bytes(10), "big")
    else:
        tail = int.from_bytes(secrets.token_bytes(10), "big")
    _LAST_MINT["ms"] = ms
    _LAST_MINT["tail"] = tail
    return "run-%s%s" % (_b32_48(ms), _b32_80(tail))


def runs_path(path=None):
    """The runs file path (same directory as the main ledger, same lock)."""
    if path:
        return Path(path)
    return ledger_dir() / RUNS_NAME


def run_verdict(counts):
    """The mechanical roll-up, computed — never stored by hand: green iff
    ran > 0 and failed == 0 and env_failed == 0 (`ran: 0` is never a proof)."""
    return "green" if (counts.get("ran", 0) > 0
                       and counts.get("failed", 0) == 0
                       and counts.get("env_failed", 0) == 0) else "red"


def derive_counts(rows, run_id):
    """Pure: recount the rows carrying `run_id`. Legacy rows (no `run`) are
    never folded in — they are counted as `legacy` and stay out of the proof.
    Returns (counts dict, legacy_count)."""
    counts = {k: 0 for k in RUN_CASE_FIELDS}
    legacy = 0
    for r in rows or ():
        if not isinstance(r, dict):
            continue
        if not r.get("run"):
            legacy += 1
            continue
        if r.get("run") != run_id:
            continue
        v = r.get("verdict")
        if v == "pass":
            counts["ran"] += 1
            counts["passed"] += 1
        elif v == "fail":
            counts["ran"] += 1
            counts["failed"] += 1
        elif v == "env_fail":
            counts["ran"] += 1
            counts["env_failed"] += 1
        # any other verdict (defensive: skip) ran nothing — not counted
    return counts, legacy


def validate_run_header(hdr):
    """Closed-schema check over RUN_HEADER_FIELDS. Returns (clean, None) or
    (None, reason); malformed input is refused by name, never guessed."""
    if not isinstance(hdr, dict):
        return None, "header_not_dict"
    extra = sorted(set(hdr) - set(RUN_HEADER_FIELDS))
    if extra:
        return None, "unknown_fields:%s" % ",".join(extra)
    missing = [f for f in RUN_HEADER_FIELDS if f not in hdr]
    if missing:
        return None, "missing_fields:%s" % ",".join(missing)
    if hdr["v"] != RUN_HEADER_V:
        return None, "v_invalid:%s" % (hdr["v"],)
    rid = hdr["id"]
    if not isinstance(rid, str) or not rid.startswith("run-") or len(rid) < 5:
        return None, "id_not_run_id"
    repos = hdr["repos"]
    if not isinstance(repos, list) or not repos:
        return None, "repos_not_nonempty_list"
    for r in repos:
        if (not isinstance(r, dict) or set(r) != {"repo", "revision"}
                or not isinstance(r.get("repo"), str) or not r["repo"].strip()
                or not isinstance(r.get("revision"), str)
                or not r["revision"].strip()):
            return None, "repos_entry_invalid"
    if hdr["suite"] not in RUN_SUITES:
        return None, "suite_invalid:%s" % (hdr["suite"],)
    if not _check_source(hdr["source"]):
        return None, "source_invalid:%s" % (hdr["source"],)
    e = hdr["env_fp"]
    if not isinstance(e, str) or len(e) != 64 or any(ch not in _HEX for ch in e):
        return None, "env_fp_not_sha256"
    w = hdr["conc_width"]
    if isinstance(w, bool) or not isinstance(w, int) or w < 1:
        return None, "conc_width_not_positive_int"
    if not isinstance(hdr["pool"], str):
        return None, "pool_not_str"
    st = hdr["started_at"]
    if isinstance(st, bool) or not isinstance(st, int) or st <= 0:
        return None, "started_at_not_positive_int_ms"
    d = hdr["duration_s"]
    if isinstance(d, bool) or not isinstance(d, (int, float)) or d < 0:
        return None, "duration_s_not_nonnegative_number"
    cases = hdr["cases"]
    if not isinstance(cases, dict) or set(cases) != set(RUN_CASE_FIELDS):
        return None, "cases_not_exact_counts"
    for k in RUN_CASE_FIELDS:
        v = cases[k]
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            return None, "cases_%s_not_nonnegative_int" % k
    if cases["ran"] != cases["passed"] + cases["failed"] + cases["env_failed"]:
        return None, "cases_ran_not_sum_of_outcomes"
    want = run_verdict(cases)
    if hdr["verdict"] != want:
        return None, "verdict_not_rollup:%s!=%s" % (hdr["verdict"], want)
    return dict(hdr,
                cases=dict(cases),
                repos=[dict(r) for r in repos]), None


def _check_header_counts_writable(clean):
    """Proof-shape guard on a validated header: a run that ran nothing is never
    a proof (§A), so a zero-row header is refused at the write face — the
    mechanical verdict already calls it red, but writing it would let a reader
    mistake a red row count of 0 for 'nothing happened here'."""
    if clean["cases"]["ran"] == 0:
        return "ran_zero_no_rows_never_a_proof"
    return None


def read_runs(path=None):
    """Read the runs file -> (headers, bad sample[:10]). Missing file = empty
    (new ledger, not an error); a malformed line is named, never swallowed."""
    target = runs_path(path)
    headers, bad = [], []
    try:
        with open(str(target), encoding="utf-8") as fh:
            for ln in fh:
                s = ln.strip()
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                except ValueError:
                    bad.append(s[:160])
                    continue
                if isinstance(obj, dict):
                    headers.append(obj)
                else:
                    bad.append(s[:160])
    except FileNotFoundError:
        return [], []
    except IsADirectoryError:
        bad.append("runs 路径是目录：%s" % target)
        return [], bad
    return headers, bad[:10]


def append_run_header(header, path=None):
    """Validate, then append one header line under the same flock as the main
    ledger. The counts are checked against the rows BEFORE the header lands:
    the rows carrying header["id"] are recounted from the main ledger and any
    mismatch (or a run with zero rows) is refused loudly — a header nobody can
    re-derive from its rows is exactly the fake summary this slice removes.
    A duplicate run id is refused loudly too (in-batch duplicates cannot exist
    in a single-header call; the check is against the file, the cheap insurance
    the identity section of the design mandates).
    Returns {"written": n, "rejected": [{"reason"}...]} — all-refused = zero
    bytes written (no file created)."""
    target = runs_path(path)
    clean, why = validate_run_header(header)
    if clean is None:
        return {"written": 0, "rejected": [{"reason": why}]}
    zero = _check_header_counts_writable(clean)
    if zero:
        return {"written": 0, "rejected": [{"reason": zero}]}
    receipt = {"written": 0, "rejected": []}
    target.parent.mkdir(parents=True, exist_ok=True)
    lock = _acquire_lock(target)
    try:
        existing, _bad = read_runs(target)
        if any(h.get("id") == clean["id"] for h in existing):
            receipt["rejected"].append({"reason": "duplicate_run_id:%s"
                                        % clean["id"]})
            return receipt
        rows, _bad2 = read_rows()
        counts, _legacy = derive_counts(rows, clean["id"])
        if counts != clean["cases"]:
            receipt["rejected"].append(
                {"reason": "counts_mismatch:header=%s rows=%s"
                 % (json.dumps(clean["cases"], sort_keys=True),
                    json.dumps(counts, sort_keys=True))})
            return receipt
        payload = (_dumps(clean) + "\n").encode("utf-8")
        fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)
        receipt["written"] = 1
    finally:
        _release_lock(lock)
    return receipt


def rows_for_run(run_id, path=None):
    """Read face for one run -> dict with:
    rows        — the case rows carrying this run id (main ledger window)
    legacy_rows — count of rows with no run id (legacy, not folded in)
    header      — the run header, or None (interrupted run: rows exist whose
                  header never landed — a state to see, never a summary to
                  invent)
    state       — "headered" | "interrupted" (rows but no header)
                | "unknown" (neither rows nor header: no such run in window)
    """
    if not isinstance(run_id, str) or not run_id.startswith("run-"):
        raise RunRecordError("run_id_not_run_id:%r" % (run_id,))
    rows, _bad = read_rows()
    headers, _bad2 = read_runs(path)
    mine = [r for r in rows if isinstance(r, dict) and r.get("run") == run_id]
    legacy = sum(1 for r in rows
                 if isinstance(r, dict) and not r.get("run"))
    header = next((h for h in headers if h.get("id") == run_id), None)
    if mine and header:
        state = "headered"
    elif mine:
        state = "interrupted"
    else:
        state = "unknown"
    return {"rows": mine, "legacy_rows": legacy, "header": header,
            "state": state}


def require_run_rows(run_id, path=None):
    """Consumer seam: the rows of one run, or a named refusal. Fails loudly
    (RunRecordError, never a guess) when: the id is not a run id; no row in
    the window carries it; or the header is missing (interrupted run — the
    counts cannot be certified against a header that does not exist)."""
    face = rows_for_run(run_id, path)
    if not face["rows"]:
        raise RunRecordError(
            "no_rows_with_run_id:%s (legacy rows in window: %d — a consumer "
            "needing a run id never guesses one)" % (run_id, face["legacy_rows"]))
    if face["header"] is None:
        raise RunRecordError(
            "run_header_missing:%s (interrupted run — rows without a header "
            "are a state to see, not a summary to invent)" % run_id)
    return face["rows"]


# ---------------- CLI ----------------

def _usage():
    return ("用法：scenario_ledger.py <query|runs|rollup|path|stats> …\n"
            "  query --commit <sha40> --scenario <名> [--limit 20] [--json] [--ledger P]\n"
            "  runs [--id <run-…>] [--ledger P]\n"
            "  rollup [--keep-days %d] [--ledger P]\n"
            "  path\n"
            "  stats [--ledger P]" % DEFAULT_KEEP_DAYS)


def _opt_val(argv, flag, default=None):
    if flag in argv:
        i = argv.index(flag)
        if i + 1 < len(argv):
            return argv[i + 1]
    return default


def cmd_query(rest):
    commit = _opt_val(rest, "--commit")
    scenario = _opt_val(rest, "--scenario")
    if not commit or not scenario:
        sys.stderr.write("query 需要 --commit 与 --scenario\n" + _usage() + "\n")
        return 2
    limit_raw = _opt_val(rest, "--limit", "20")
    try:
        limit = max(1, int(limit_raw))
    except (TypeError, ValueError):
        sys.stderr.write("--limit 非整数：%r\n" % (limit_raw,))
        return 2
    ledger = _opt_val(rest, "--ledger")
    as_json = "--json" in rest
    try:
        hits, bad = query_rows(commit, scenario, ledger)
    except OSError as e:
        sys.stderr.write("主账不可读（%s: %s）——不静默回绿\n"
                         % (type(e).__name__, e))
        return 2
    if bad:
        sys.stderr.write("主账含 %d 条不可解析行（样本 %s）——读取面点名，不静默\n"
                         % (len(bad), bad[0][:80]))
    if not hits:
        msg = ("无记录：commit=%s scenario=%s（主账=%s）——查询只覆盖主账 %d 天窗，"
               "更老行已按月卷外移（非「从未跑过」）；无记录不得当绿"
               % (commit, scenario, ledger or ledger_path(), DEFAULT_KEEP_DAYS))
        if as_json:
            print(json.dumps({"records": [], "answer": "无记录",
                              "commit": commit, "scenario": scenario,
                              "ledger": str(ledger or ledger_path()),
                              "window_days": DEFAULT_KEEP_DAYS,
                              "bad_lines": len(bad)}, ensure_ascii=False))
        else:
            print(msg)
        return 0
    if as_json:
        print(json.dumps({"records": hits[:limit], "answer": "命中",
                          "commit": commit, "scenario": scenario,
                          "bad_lines": len(bad)}, ensure_ascii=False))
        return 0
    print("记录 %d 条（新→旧，至多显 %d）：commit=%s scenario=%s"
          % (len(hits), limit, commit, scenario))
    for r in hits[:limit]:
        print("verdict=%s ts=%s source=%s env_fp=%s conc_width=%s pool=%s wall_s=%s"
              % (r.get("verdict"), r.get("ts"), r.get("source"),
                 r.get("env_fp"), r.get("conc_width"), r.get("pool"),
                 r.get("wall_s")))
    return 0


def cmd_runs(rest):
    """runs [--id X] [--ledger P] — one run's face, or the loud refusal a
    consumer owes when the run identity is missing (exit 2, named reason)."""
    rid = _opt_val(rest, "--id")
    ledger = _opt_val(rest, "--ledger")
    if rid is None:
        headers, bad = read_runs(ledger)
        if bad:
            sys.stderr.write("runs 含 %d 条不可解析行（样本 %s）——点名不静默\n"
                             % (len(bad), bad[0][:80]))
        print(json.dumps({"runs": headers, "bad_lines": len(bad)},
                         ensure_ascii=False))
        return 0
    try:
        face = rows_for_run(rid, ledger)
    except RunRecordError as e:
        sys.stderr.write("RUN_RECORD_ERROR %s\n" % e)
        return 2
    print(json.dumps({k: (v if k != "rows" else len(v))
                      for k, v in face.items()}, ensure_ascii=False))
    if face["state"] != "headered":
        # a consumer asking for a run and not finding one fails loudly, never
        # guesses: unknown = no such run in the window; interrupted = rows
        # whose header never landed
        why = ("no_rows_with_run_id:%s" % rid if face["state"] == "unknown"
               else "run_header_missing:%s (interrupted run)" % rid)
        sys.stderr.write("RUN_RECORD_ERROR %s\n" % why)
        return 2
    return 0


def cmd_rollup(rest):
    keep_raw = _opt_val(rest, "--keep-days", str(DEFAULT_KEEP_DAYS))
    try:
        keep = max(1, int(keep_raw))
    except (TypeError, ValueError):
        sys.stderr.write("--keep-days 非整数：%r\n" % (keep_raw,))
        return 2
    ledger = _opt_val(rest, "--ledger")
    print(json.dumps(rollup(keep_days=keep, path=ledger), ensure_ascii=False))
    return 0


def cmd_stats(rest):
    ledger = _opt_val(rest, "--ledger")
    rows, bad = read_rows(ledger)
    by_verdict, by_source = {}, {}
    for r in rows:
        by_verdict[r.get("verdict")] = by_verdict.get(r.get("verdict"), 0) + 1
        by_source[r.get("source")] = by_source.get(r.get("source"), 0) + 1
    target = Path(ledger) if ledger else ledger_path()
    size = target.stat().st_size if target.exists() else 0
    print(json.dumps({"rows": len(rows), "bad_lines": len(bad),
                      "by_verdict": by_verdict, "by_source": by_source,
                      "bytes": size, "ledger": str(target)},
                     ensure_ascii=False))
    return 0


def _cli(argv):
    if not argv or argv[0] in ("help", "-h", "--help"):
        print(_usage())
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "query":
        return cmd_query(rest)
    if cmd == "runs":
        return cmd_runs(rest)
    if cmd == "rollup":
        return cmd_rollup(rest)
    if cmd == "path":
        print(str(ledger_path()))
        return 0
    if cmd == "stats":
        return cmd_stats(rest)
    sys.stderr.write("未知子命令：%s\n%s\n" % (cmd, _usage()))
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
