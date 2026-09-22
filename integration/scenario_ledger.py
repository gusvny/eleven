#!/usr/bin/env python3
"""scenario_ledger —— 集成门结果台账（t260922-12）：按提交记账 + 查询 + 保留。

真源（唯一）：~/.sandbar/projects/sandbar/ledger/scenario-results.jsonl
（机器级、仓外——不进泳道工作区（撞 merge_check「工作区干净」判据，t260922-02
实例）、不入库（并发写=冲突=返工）、不被夹具复制（408GB 事故的乘法）。目录可被
SANDBAR_SCENARIO_LEDGER_DIR 整体覆盖（测试隔离缝，同 SANDBAR_INSPECTION_DIR 先例）。

格式：append-only JSONL，行=一次场景判定，十字段封闭 schema：
  ts(ISO8601 带时区) commit(40hex) env_fp(64hex) conc_width(int>=1)
  pool(场景所属池) scenario(非空) verdict(pass|fail|env_fail|skip)
  wall_s(number|null) source(lane:<票>|inspection|baseline) ticket(str)
键=(commit, env_fp, conc_width, scenario)：任一缺失/畸形/多字段/超行宽 → 拒写
（脏记录比无记录更坏）；全拒的批次零落盘（不建文件）。

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
              "verdict", "wall_s", "source", "ticket")
_HEX = "0123456789abcdef"


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
    return dict(row), None


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


# ---------------- CLI ----------------

def _usage():
    return ("用法：scenario_ledger.py <query|rollup|path|stats> …\n"
            "  query --commit <sha40> --scenario <名> [--limit 20] [--json] [--ledger P]\n"
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
