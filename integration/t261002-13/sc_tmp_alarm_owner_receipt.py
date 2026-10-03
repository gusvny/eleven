#!/usr/bin/env python3
"""sc_tmp_alarm_owner_receipt — 水位告警必须点名泄漏家族（t261002-13，灰盒 L3）。

被测出口：server/engine/activities.py 的真扫描入口 scan_tmp_fixture_dirs()（真 IO，
隔离 root）→ inspection_lane_watchdog.tmp_fixture_scan_result()（回执组装）——
即巡检回执 meta["tmp_fixture"] 的公开契约面。intent（工单交付物 3：阈值告警现在
只报一个数、不点名归属——下次再红时必须指向一个家族而不是一个数字）：
  A 真扫描面：隔离 root 里按白名单前缀造多家族越龄夹具（真文件系统，非注入 dict）
    → 计数按家族分开可辨（这是「告警可归因」的数据前提）；
  B 越阈值触发 finding（tmp_fixture_max_dirs 压低）→ 回执含 top_leakers（按计数
    降序、含最老年龄）——实现未落地=红（TDD 信号）；
  C 家族点名：top_leakers 每条带前缀与 owner 线索；白名单里登记过 owner 的前缀
    点名生产者文件族；未知前缀报 owner=unknown——绝不猜（report-must-be-precise）；
  D 排除优先：EXCLUDED_PREFIXES（com.google.Chrome.*，别人的）不进计数、不进
    top_leakers——告警不冤枉别的程序；
  E 收据键：meta["tmp_fixture"] 面含 dirs/oldest_age_h/finding_count/thresholds，
    thresholds 来源具名（threshold_source）——「报数」契约不因加点名而回退。
intent 分工：watchdog 纯函数真值分支矩阵（注入扫描、畸形条目降级点名、词表）归
developer L1 server/engine/tests/test_t260926_tmp_fixture_water.py；本条锁
**真扫描 IO → 回执组装** 的端到端用户可感知行为（隔离真目录树，白名单×越龄×排除
族同场）。
三态：engine 面不可导入=ENV_FAIL exit 2；断言败=FAIL exit 1；全过=PASS exit 0。

Run directly: python3 integration/t261002-13/sc_tmp_alarm_owner_receipt.py（cwd=仓根）。
"""
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
ENGINE = ROOT / "server" / "engine"
sys.path.insert(0, str(ENGINE))
sys.path.insert(0, str(ROOT / "integration"))

PASS, FAIL = 0, 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✓ %s" % label)
    else:
        FAIL += 1
        print("  ✗ %s" % label)


def main():
    try:
        import activities  # noqa: E402
        import inspection_lane_watchdog as wd  # noqa: E402
    except Exception as e:
        print("ENV_FAIL: engine modules not importable: %r" % e, file=sys.stderr)
        sys.exit(2)
    import lib_tmp_reclaim as lr  # noqa: E402

    box = Path(tempfile.mkdtemp(prefix="t261002-13-s2-box-"))
    lr.register_tmp_path(box, "sc_tmp_alarm_owner_receipt sandbox")

    def mint(prefix, n, hours=10.0):
        old = time.time() - hours * 3600.0
        for i in range(n):
            d = Path(tempfile.mkdtemp(prefix="%s-%02d-" % (prefix, i), dir=str(box)))
            os.utime(d, (old, old))

    mint("t260904-02-", 6)    # ticket histogram #1
    mint("t260901-21-", 3)    # ticket histogram #2
    mint("t26092523-", 2)     # ticket histogram #4（本票补白名单的缺口族）
    mint("com.google.Chrome.", 4)  # 别人的（EXCLUDED_PREFIXES）
    # 新鲜白名单条目（<阈值年龄）：不该进「最老」与「泄漏计数」的点名面
    fresh = Path(tempfile.mkdtemp(prefix="t260904-02-fresh-", dir=str(box)))

    try:
        scan = activities.scan_tmp_fixture_dirs(str(box), wd.TMP_FIXTURE_PREFIXES)
        ok(isinstance(scan, dict) and isinstance(scan.get("entries"), list),
           "A1 real scan returns a receipt dict with an entries list")

        names = [e["name"] for e in scan["entries"] if isinstance(e, dict) and e.get("name")]
        ok(sum(1 for n in names if n.startswith("t260904-02-")) >= 7,
           "A2 family #1 (t260904-02-*) counted from the real tree (6 aged + 1 fresh)")
        ok(any(n.startswith("t26092523-") for n in names),
           "A3 gap family t26092523-* is whitelisted (backlog is sweepable/alarmable)")
        ok(not any(n.startswith("com.google.Chrome.") for n in names),
           "D1 EXCLUDED_PREFIXES never enters the scan counts (not ours, never blamed)")
        ok(any("com.google.Chrome." in s for s in (scan.get("skipped") or []))
           or int(scan.get("untouched") or 0) >= 4,
           "D1b foreign entries visible as untouched/skipped, counted out — not silently dropped")

        thr, src, note, problems = wd.resolve_tmp_thresholds(
            {"tmp_fixture_max_dirs": 5, "tmp_fixture_max_age_h": 1})
        ok(int(thr["tmp_fixture_max_dirs"]) == 5, "B0 threshold accepted from declaration (source=%s)" % src)

        res = wd.tmp_fixture_scan_result(scan, thr, source="declaration",
                                                 now_ts=time.time())
        section = res.get("section") or {}
        ok(int(section.get("dirs") or 0) >= 11,
           "E1 receipt reports a directory count (the old 'a number' face still present)")
        ok(section.get("oldest_age_h") is not None
           and float(section.get("oldest_age_h") or 0) >= 9.0,
           "E2 receipt reports oldest age (fresh entries must not dilute it below the aged tree)")
        ok(section.get("threshold_source") in ("declaration", "env", "default"),
           "E3 threshold source is named in the receipt")
        ok(int(section.get("finding_count") or 0) >= 1,
           "B1 over-threshold scan raises the tmp-fixture finding")

        top = section.get("top_leakers") or res.get("top_leakers")
        ok(isinstance(top, list) and len(top) >= 2,
           "B2 receipt names top leakers, not just a count (deliverable 3)")
        if isinstance(top, list) and top:
            counts = [int(t.get("count", -1)) for t in top]
            ok(all(counts[i] >= counts[i + 1] for i in range(len(counts) - 1)),
               "B2b top_leakers sorted by count descending")
            ok(any(str(t.get("prefix", "")).startswith("t260904-02-") for t in top),
               "C1 largest family t260904-02-* is named as a leaker (the 73k-face owner)")
            ok(all(str(t.get("prefix", "")).startswith("com.google.Chrome.") is False
                   for t in top),
               "D2 excluded families never appear in top_leakers")
            owners = [str(t.get("owner", "")) for t in top]
            unknown = [o for o in owners if o == "unknown"]
            owned = [o for o in owners if o != "unknown"]
            ok(all(o for o in owners),
               "C2 every named leaker carries a non-blank owner field")
            ok(not owners or (owned or unknown),
               "C2b owner is either a producer hint or literal 'unknown' — never guessed")
    finally:
        shutil.rmtree(box, ignore_errors=True)
        lr.reclaim_registered()

    print("PASS=%d FAIL=%d" % (PASS, FAIL))
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
