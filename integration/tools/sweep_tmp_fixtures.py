#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sweep_tmp_fixtures — 一次性、可复核的「测试夹具临时目录」清扫器（宿主令 260926）。

背景：`$TMPDIR` 顶层实测 407,294 个目录，其中 401,578 个 >6 小时未动（98.6%）。
大头是各测试面 `mkdtemp` 出来的夹具（`integ-e2e-fixture-*` 1086 个 / ~391GB、
`t260907-06-ut-*` 1.7 万、`sandbar-agent-presets-*` 2 万……）。生产者侧已逐个修
（见同日各票：注册表 + exit 钩子 + 拆台回收），本脚本是**存量止血**与
「SIGKILL 类终态」的兜底网。

判据（两条同时满足才删，缺一不删）：
  ① 顶层条目名以**白名单前缀**开头（TMP_FIXTURE_PREFIXES；白名单之外一律不碰——
     宿主 temp 目录里可能有别的程序的东西）；
  ② 该目录 `mtime` 距今 ≥ `--max-age-h`（缺省 6 小时；年龄不足的一律不碰，可能在跑）。
另：只处理**真目录**（`is_dir(follow_symlinks=False)`）——符号链接、文件、别的类型一律跳过
（`rmtree` 跟符号链接会删错东西）。

安全：默认 dry-run（只报数不删），`--apply` 才删；`--apply` 的年龄闸有 1 小时硬地板
（拒绝更激进的取值）。日志一行一动作，失败逐条点名。

用法（cwd=仓库根）：
  python3 integration/tools/sweep_tmp_fixtures.py                  # dry-run：各前缀命中数 + 占用估算
  python3 integration/tools/sweep_tmp_fixtures.py --json           # 机器可读
  nohup python3 integration/tools/sweep_tmp_fixtures.py --apply \
        > /tmp/sweep-tmp-fixtures.log 2>&1 &                       # 真删（宿主已明确要清）

摘要行（两种模式同形，dry-run 带 DRY-RUN 前缀）：
  swept N dirs (>=6h) | kept M live | failed F | freed≈X
其中 `freed≈X` 是**采样估算**（每前缀最多 `--sample` 个目录实测平均 × 命中数），逐前缀行
标注采样数；命中数为 0 的前缀不估。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time

#: 已知测试夹具前缀白名单（真源之一；另一份在 server/engine/inspection_lane_watchdog.py
#: 的 TMP_FIXTURE_PREFIXES——两处一致性由机械漂移锁钉住
#: server/engine/tests/test_t260926_tmp_fixture_water.py::test_e1_prefix_whitelist_single_source）。
#: 本脚本**不 import 引擎包**：清扫器要在引擎装不上/被改坏的机器上也能跑（止血优先）。
TMP_FIXTURE_PREFIXES = (
    "integ-e2e-fixture-",     # integration 场景夹具（ticket-lifecycle-scenes.mjs）
    "lint-pyc-",              # integration/lint_tests.py 的 pyc 暂存
    "fix10-", "fix14-", "fix17-",   # integration/t26* 各票 .mjs 夹具
    "pathgate-",              # t260911-03 pathgate 场景夹具
    "t260907-06-ut-",         # server/engine/tests/test_multirepo_anchor.py
    "t260907-12-ut",          # 同上 + test_multirepo_root_activity.py（前缀不加连字符，含 -single/-ch 等变体）
    "sandbar-agent-presets-",  # integration/stage_docker.py 起的台（agent preset 物化）
    "t26092212-", "t260906-", "lease-ut-", "t260904-02-", "t260901-21-",
    "t02-lane", "venv-compat-root", "t26090704-lane",
    "wb-",
)

#: **未启用**的第二批候选前缀（只登记，不参与删除）：宿主给的白名单之外，实测还有
#: 126,586 个目录 / 22,058 个文件属于**同族**测试夹具（同一个泄漏形态，只是前缀不在
#: 授权清单内）。按「前缀白名单之外一律不碰」的边界，这里只登记证据，等宿主授权后再并入
#: TMP_FIXTURE_PREFIXES（并入时同步 engine 侧 TMP_FIXTURE_PREFIXES，漂移锁会红）。
#: 逐条证据=260926 清扫后的只读普查（前缀 / 顶层条目数 / 最老年龄 / 生产者出处）：
CANDIDATE_PREFIXES_BATCH2 = (
    # 前缀                     实测条目数  最老   生产者（file:line，260926 grep 定位）
    "t260907-12-act-",        #  4,251  258h  server/engine/tests/test_multirepo_root_activity.py（本批已修，存量未清）
    "t260907-12-ch",          #  2,136  258h  同上（whitelist 的 t260907-12-ut 盖不住这两个变体）
    "sandbar-admin-log-",     #  5,396  255h  integration/stage_docker.py（**文件**，本批已在拆台回收；存量需人工/脚本清）
    "sandbar-credentials-",   #  5,384  255h  同上（凭据副本留在 $TMPDIR 属卫生面欠账）
    "sandbar-integ-run-",     #  4,076  287h  integration/run_scenarios.py:3038（每 key 一把 tmp 锁文件，从不回收）
    "nusuyou-integ-run-",     #  4,824   96h  同款锁面（另一项目的 runner 跑同一套件）
    "venv-compat-",           #  4,749  335h  integration/t260907-10/sc_engine_venv_compat.py:57-58（root 在册、home 不在册）
    "t26092114-",             #  4,504  121h  integration/t260921-14/lib_t26092114.py 族
    "t26090704-lock",         #  3,236  255h  integration 场景族（whitelist 只有 t26090704-lane）
    "t260904-18-mg",          #  3,242  255h  integration/t260904-18/ 夹具族
    "t260910-10-",            #  4,835  335h  integration/t260910-10/ 夹具族（uifxa-/fixb-）
    "t260908-02-ut",          #  2,099  257h  integration/t260908-01/ 夹具族
    "dsh-subprocess-",        #  2,024  336h  dsh 子进程探针族（server/ui-check、probe_*）
    "t090506-",               #  3,230  335h  integration/t090506-* 夹具族（entry-/read-fixture）
    "t260904-13-itest",       #  1,896  255h  integration/t260904-13/ 夹具族
    "sandbar-t26091202-",     #  2,406  311h  integration/t260912-02/sc_stage_sweep_owner_gone.py:114
    "detailred-e2e-",         #  1,559  281h  integration/t260915-01/tests/sc_detail_red_refusal_receipt.py:76
    "sandbar-reg-",           #  1,529  294h  integration 注册表夹具族
    "t260915-10-",            #  1,468  275h  integration/t260915-10/ 夹具族
    "t26092404-",             #  1,772   54h  integration/t260924-04/ 夹具族
    "t260923-", "t260925-", "t260922-", "t260921-", "t260916-", "t260917-", "t260918-",
    "t260919-", "t260920-",   # 各期场景自建夹具族（前缀形态，逐期清点后再授权）
    # **明确不在候选内**（别程序的/别项目的，永远不碰）：com.google.Chrome.*（4,380）、
    # 其它非 t26*/sandbar-*/fix*- 前缀的宿主条目（共 148,685 条里的大多数）
)

#: 摘要/日志里的 「未被触碰」分类（观测用，绝不参与删除）
DEFAULT_MAX_AGE_H = 6.0
DEFAULT_SAMPLE = 10
DEFAULT_SAMPLE_BUDGET_S = 8.0
#: --apply 的年龄硬地板（小时）：比这更激进的取值一律拒（正在跑的夹具必须活着）
APPLY_MIN_AGE_H = 1.0


def human(n: float) -> str:
    """字节 → 人读（B/K/M/G/T，一位小数）。"""
    v = float(n)
    for unit in ("B", "K", "M", "G", "T", "P"):
        if v < 1024 or unit == "P":
            return ("%dB" % int(v)) if unit == "B" else ("%.1f%s" % (v, unit))
        v /= 1024.0
    return "%.1fP" % v


def age_h(now: float, mtime: float) -> float:
    return max(0.0, (now - mtime) / 3600.0)


def scan(root: str, prefixes, max_age_h: float, now: float = None):
    """扫 `root` 顶层一次（唯一一次遍历）：命中白名单前缀的真目录按年龄分桶。

    返回 dict：stale/live 各为 [(name, mtime)]（name 排序，**删除顺序可复核**），
    外加计数：entries（顶层条目总数）、untouched（白名单外）、skipped（非常规目录/
    符号链接/stat 失败——逐条点名在 skipped_named）。
    """
    now = time.time() if now is None else now
    stale, live, skipped_named = [], [], []
    entries = untouched = 0
    locked = 0                       # stat 失败的（点名，绝不当 stale 删）
    with os.scandir(root) as it:
        for ent in it:
            entries += 1
            name = ent.name
            if not any(name.startswith(p) for p in prefixes):
                untouched += 1
                continue
            try:
                if not ent.is_dir(follow_symlinks=False):
                    # 符号链接/文件/别的类型：不碰（rmtree 跟链接会删到链接目标）
                    skipped_named.append("%s (not a real directory)" % name)
                    continue
                mtime = ent.stat(follow_symlinks=False).st_mtime
            except OSError as e:
                locked += 1
                skipped_named.append("%s (stat failed: %s)" % (name, e))
                continue
            (stale if age_h(now, mtime) >= max_age_h else live).append((name, mtime))
    stale.sort()
    live.sort()
    return {"entries": entries, "untouched": untouched, "stale": stale, "live": live,
            "skipped_named": skipped_named, "skipped": locked}


def by_prefix(items, prefixes):
    """[(name, mtime)] → {prefix: [items]}（按白名单顺序；同名多前缀取首个匹配，与 scan 同判据）。"""
    out = {p: [] for p in prefixes}
    for name, mtime in items:
        for p in prefixes:
            if name.startswith(p):
                out[p].append((name, mtime))
                break
    return out


def bounded_size(path: str, budget_s: float) -> tuple:
    """有界目录体积（不跟符号链接；预算用尽标 truncated）。返回 (bytes, truncated)。"""
    total = 0
    walked = 0
    deadline = time.monotonic() + budget_s
    stack = [path]
    truncated = False
    while stack:
        if time.monotonic() > deadline:
            truncated = True
            break
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for ent in it:
                    walked += 1
                    if walked > 200000:
                        truncated = True
                        stack = []
                        break
                    try:
                        if ent.is_symlink():
                            continue
                        if ent.is_dir(follow_symlinks=False):
                            stack.append(ent.path)
                        else:
                            total += ent.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total, truncated


def estimate(root: str, per_prefix: dict, sample: int, budget_s: float):
    """每前缀采样估占用（最多 sample 个目录实测平均 × 命中数）+ 最老年龄。

    返回 (per_prefix_rows, est_total_bytes, notes)。采样与估算是**观测**，删除判据只有
    前缀 + 年龄两条——估算值绝不参与「删不删」的决定。
    """
    rows = []
    est_total = 0.0
    notes = []
    now = time.time()
    for prefix, items in per_prefix.items():
        if not items:
            rows.append({"prefix": prefix, "count": 0, "oldest_h": 0.0,
                         "est_bytes": 0, "sampled": 0, "truncated": False})
            continue
        picks = items[:sample] if sample > 0 else []
        sizes = []
        truncated = False
        for name, _m in picks:
            b, t = bounded_size(os.path.join(root, name), budget_s)
            sizes.append(b)
            truncated = truncated or t
        if sizes:
            avg = sum(sizes) / float(len(sizes))
            est = avg * len(items)
            est_total += est
            if truncated:
                notes.append("%s: size estimate truncated by the %ss budget (underestimate)"
                             % (prefix, budget_s))
        else:
            est = 0
            notes.append("%s: no sample taken (estimate omitted)" % prefix)
        oldest = max(age_h(now, m) for _n, m in items)
        rows.append({"prefix": prefix, "count": len(items), "oldest_h": oldest,
                     "est_bytes": est, "sampled": len(sizes), "truncated": truncated})
    return rows, est_total, notes


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Sweep leaked test-fixture dirs under $TMPDIR "
                                            "(dry-run by default; --apply deletes)")
    ap.add_argument("--apply", action="store_true",
                    help="actually delete (default = dry-run, report only)")
    ap.add_argument("--root", default=None, help="temp root (default: tempfile.gettempdir())")
    ap.add_argument("--max-age-h", type=float, default=DEFAULT_MAX_AGE_H,
                    help="delete only dirs idle >= this many hours (default 6)")
    ap.add_argument("--prefix", action="append", default=None,
                    help="override the whitelist prefix (repeatable; default = built-in whitelist)")
    ap.add_argument("--sample", type=int, default=DEFAULT_SAMPLE,
                    help="dirs sampled per prefix for the size estimate (default 10)")
    ap.add_argument("--sample-budget-s", type=float, default=DEFAULT_SAMPLE_BUDGET_S,
                    help="per-dir size-walk budget in seconds (default 8)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.root or tempfile.gettempdir())
    prefixes = tuple(args.prefix) if args.prefix else TMP_FIXTURE_PREFIXES
    out = {"mode": "apply" if args.apply else "dry-run", "root": root,
           "max_age_h": args.max_age_h, "prefixes": list(prefixes)}
    log = (lambda m: print(m, file=sys.stderr, flush=True)) if args.json \
        else (lambda m: print(m, flush=True))

    def bail(msg, code=2):
        out["error"] = msg
        if args.json:
            print(json.dumps(out, ensure_ascii=False))
        else:
            print("REFUSED: " + msg)
        return code

    if not os.path.isdir(root):
        return bail("root is not a directory: %s" % root)
    if args.max_age_h <= 0:
        return bail("--max-age-h must be > 0 (a sweep without an age gate could kill a running suite)")
    if args.apply and args.max_age_h < APPLY_MIN_AGE_H:
        return bail("--apply with --max-age-h %s < hard floor %sh refused"
                    % (args.max_age_h, APPLY_MIN_AGE_H))
    if args.apply and not prefixes:
        return bail("whitelist is empty — refusing to sweep with no prefix gate")

    if not args.apply:
        log("DRY-RUN (nothing is deleted; pass --apply to delete)")
    log("root=%s max-age=%sh prefixes=%d" % (root, args.max_age_h, len(prefixes)))

    t0 = time.monotonic()
    sc = scan(root, prefixes, args.max_age_h)
    rows, est_total, notes = estimate(root, by_prefix(sc["stale"], prefixes), args.sample,
                                      args.sample_budget_s)
    live_rows = by_prefix(sc["live"], prefixes)
    log("scanned %d top-level entries in %.1fs: %d whitelisted stale (>=%sh), %d whitelisted live, "
        "%d untouched (outside whitelist), %d skipped"
        % (sc["entries"], time.monotonic() - t0, len(sc["stale"]), args.max_age_h,
           len(sc["live"]), sc["untouched"], len(sc["skipped_named"])))
    for r in rows:
        live_n = len(live_rows.get(r["prefix"], []))
        log("  %-24s stale=%-7d live=%-5d oldest=%-8s est≈%s%s"
            % (r["prefix"], r["count"], live_n,
               ("%.1fh" % r["oldest_h"]) if r["count"] else "-",
               human(r["est_bytes"]) if r["count"] else "-",
               (" (from %d sampled)" % r["sampled"]) if r["count"] else ""))
    for n in notes:
        log("  note: %s" % n)

    freed = 0.0
    failed, failed_named = 0, []
    done = 0
    if args.apply:
        # 实际释放量按「逐前缀实测平均 × 实删条数」重算（不直接抄全量估算）
        avg_by_prefix = {}
        for r in rows:
            if r["count"] and r["sampled"]:
                avg_by_prefix[r["prefix"]] = r["est_bytes"] / float(r["count"])
        log("APPLY: deleting %d dirs (>=%sh, whitelist only) ..." % (len(sc["stale"]), args.max_age_h))
        for name, _m in sc["stale"]:
            path = os.path.join(root, name)
            try:
                shutil.rmtree(path)
                done += 1
                for p in prefixes:
                    if name.startswith(p):
                        freed += avg_by_prefix.get(p, 0.0)
                        break
            except Exception as e:          # noqa: BLE001 —— 单条失败不中断全局清扫
                failed += 1
                if len(failed_named) < 40:
                    failed_named.append("%s: %s: %s" % (name, type(e).__name__, e))
                else:
                    failed_named.append("... (%d more failures suppressed)" % (failed - 40))
                log("  FAILED %s: %s: %s" % (name, type(e).__name__, e))
            if done and done % 500 == 0:
                log("  progress: %d/%d deleted, %d failed, %.1fs elapsed, freed≈%s"
                    % (done, len(sc["stale"]), failed, time.monotonic() - t0, human(freed)))
    else:
        done = len(sc["stale"])
        freed = est_total

    summary = ("%sswept %d dirs (>=%sh) | kept %d live | failed %d | freed≈%s"
               % ("" if args.apply else "DRY-RUN: ", done, args.max_age_h,
                  len(sc["live"]), failed, human(freed)))
    log(summary)
    log("done in %.1fs" % (time.monotonic() - t0))
    out.update({"entries": sc["entries"], "untouched": sc["untouched"],
                "swept": done, "kept_live": len(sc["live"]), "failed": failed,
                "failed_named": failed_named, "freed_est_bytes": freed,
                "swept_is_estimate": not args.apply,
                "per_prefix": rows,
                "live_per_prefix": {p: len(v) for p, v in live_rows.items()},
                "skipped_named": sc["skipped_named"][:40], "notes": notes,
                "summary": summary})
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
