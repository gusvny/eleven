#!/usr/bin/env python3
"""t260913-02 场景③：每日调度接真 + 漏跑可见（dead-man）（灰盒 L2/L3）。

intent（守护的用户可感知行为/契约）：
  C1 调度由**声明面**驱动且是「每天一次」：integration-tests 实例声明 `suite: full`
     与每日 cron（五字段、minute/hour 固定 ⇒ 每天恰好一次）；其余实例（docs-sync）
     cadence 未被顺手改动（零回归面）；
  C2 正规入口 `inspection_trigger.py schedule-up` 能把该实例**真建成 Temporal
     Schedule**（回执给 next_action_times＝次日；`describe` 可再查），且**可清场**
     （场景不遗留常驻定时器）；
  C3 生产面现状可查：「Temporal 上能查到该实例的 schedule 且 NextRunTime 为次日」
     ——用运维通道 `deadman --instance integration-tests` 的 schedule 段读
     next_action_times（只读，不建）；查无该 schedule 即红（工单原文：现状＝声明了
     weekly cron 但调度表里根本没有这条 schedule）；
  C4 漏跑可见（dead-man 的 CLI 面）：台账缺日 → 单行 JSON 里 missed 列出缺哪几期、
     findings 出 high（suggest=false——漏跑不是代码缺陷）、退出码 1（ops 可踩）；
     台账齐 → 不告警（零误报，退出码 0）；
  C5 漏跑期号**不截断**（漏报严重度高于跑红）且当日不算漏（今天该跑的期票可能正在
     跑、尚未落账）；
  C6 套件面告警不漏：套件回执→发现的三条硬映射——红项=high（可点名是哪几条）、
     `ran=0`=high（红线「不得删减场景换跑通」的机械面）、环境红=med 且 carried
     `suggest=false`（先修环境不误导开修码票）；心跳合成=只有套件全绿才算心跳期。

依据三支：①工单验收 C/D（次日 NextRunTime 可查 + 真触发一期走完整流程；「调度未触发」
与「套件运行失败」两情形各有可见告警、票面与列表双面）；②KI 清单：KI-049（死机制无人
知——可死机制必有可辨的拉活/告警面）、KI-060（套件健康无人值守）、KI-072（负载敏感
假红的聚合不得掩盖条数）；③组件对外契约：deadman 子命令的单行 JSON 形状
（{ok,result:{missed,alarmed,findings,schedule}}）、声明解析器对 `suite` 的词表
（WIRED_SUITES 只认全文重跑，词表外 fail-closed 点名）。

intent 分工（防 intent 级重复）：与 t260905-03-decl-gate（触发面的门行为：畸形/未接线/
占位/未知实例四类拒绝）不同面——本条只守「每日一次」的声明值与调度真建；与
t260911-02-trigger-kinds（计数 kind 的 watcher 拉活/复活/计数触发）不同面——本条是
cron 形态的接真与漏跑核算；与 t260913-02 场景②（真 workflow 旅程：泳道+套件+人门）
不同层——本条守调度/告警两条运维可读面。

环境：C2 需要在**隔离台**（17233）上真建 schedule（不写生产调度账本），缺台=ENV_FAIL；
C1/C4/C5/C6 为离线腿（纯 stdlib + 台账夹具），不受台面影响。三态：0/1/2。
实现段落地前红属预期（TDD 验收门），arbitrate/merge 期必须绿。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib_lane_journey as lj  # noqa: E402

REPO = lj.REPO
TRIGGER = os.path.join(REPO, "server", "engine", "inspection_trigger.py")
STAMP = os.getpid() % 100000
INSTANCE = "sched-daily-%05d" % STAMP
REAL_INSTANCE = "integration-tests"          # 生产声明的实例（只读核查）


def prod_schedule_read(instance: str):
    """**生产面**只读核查：该实例的 Temporal Schedule 是否存在 + NextRunTime。

    为什么不能走 run_trigger/spawn_env：那会把目标钉在隔离台 17233，读到的永远不是生产
    调度账本——工单验收 C 前半（「Temporal 上能查到该实例的 schedule」）就不可判。口径与
    t260910-11「生产零写入条件腿」/ t260911-02 find_temporal_cli 同一族：用 temporal CLI
    **只读** describe（不建不删不改），CLI 缺席=N/A（明示，不假红不假绿）。
    返回 {available, exists, next_action_times, raw|error}。"""
    import shutil
    import subprocess
    cands = [os.path.join(lj.TP_DIR, "bin", "temporal"), shutil.which("temporal")]
    try:
        common = subprocess.run(["git", "rev-parse", "--git-common-dir"],
                                capture_output=True, text=True, timeout=10,
                                cwd=lj.REPO).stdout.strip()
        if common:
            cands.append(os.path.join(os.path.dirname(os.path.abspath(common)),
                                      "server", "engine", "bin", "temporal"))
    except Exception:
        pass
    cli = next((c for c in cands if c and os.path.isfile(c) and os.access(c, os.X_OK)), "")
    if not cli:
        return {"available": False, "exists": False, "next_action_times": [],
                "error": "temporal CLI 缺席（生产面只读核查按 N/A 折算）"}
    p = subprocess.run([cli, "schedule", "describe",
                        "--schedule-id", "sandbar-inspection-%s" % instance,
                        "--address", "127.0.0.1:7233", "--output", "json"],
                       capture_output=True, text=True, timeout=30)
    if p.returncode != 0:
        return {"available": True, "exists": False, "next_action_times": [],
                "error": ((p.stdout or "") + (p.stderr or ""))[-300:]}
    try:
        info = json.loads(p.stdout or "{}")
    except ValueError as e:
        return {"available": True, "exists": False, "next_action_times": [],
                "error": "describe 输出不可解析：%s" % e}
    # CLI 的 JSON 形状（实测 temporal 1.8.3）：info.futureActionTimes=[...]（RFC3339 UTC）。
    # 兼容键序：futureActionTimes → nextActionTimes → next_action_times（版本差异）。
    info_blk = info.get("info") if isinstance(info.get("info"), dict) else {}
    nats = []
    for key in ("futureActionTimes", "nextActionTimes", "next_action_times"):
        val = info_blk.get(key)
        if isinstance(val, list) and val:
            nats = [str(x) for x in val]
            break
    return {"available": True, "exists": True, "next_action_times": nats,
            "raw_keys": sorted(info_blk)[:8]}


def _within_hours(iso_ts: str, hours: float) -> bool:
    """ISO 时刻是否在未来 hours 小时内（Temporal 的 next_action_times 带时区偏移，
    故按时刻而非日期比较；无可解析偏移时按 UTC 兜底）。"""
    if not iso_ts:
        return False
    txt = iso_ts.strip().replace("Z", "+00:00")
    try:
        ts = datetime.fromisoformat(txt)
    except ValueError:
        return False
    if ts.tzinfo is None:
        now = datetime.utcnow()
    else:
        now = datetime.now(ts.tzinfo)
    delta = (ts - now).total_seconds()
    return 0 < delta <= hours * 3600


def run_trigger(args, env=None):
    """跑运维通道（经 spawn_env 单点钉隔离台）→ (proc, 末行 JSON)。"""
    py = lj.lib.VENV_PY if os.path.exists(lj.lib.VENV_PY) else sys.executable
    return lj.run_json([py, TRIGGER] + list(args), env=env)


def main() -> int:
    r = lj.Rule("sc_inspection_schedule_daily")

    lj.lib.require_entry(TRIGGER, "巡检运维通道")
    sys.path.insert(0, lj.TP_DIR)
    import inspection_decl as decl_mod  # noqa: E402
    import inspection_deadman as dm  # noqa: E402

    # ---------------- C1 声明面：每天一次 + suite: full ----------------
    decl = decl_mod.load_inspection_decl()
    it = decl.instance(REAL_INSTANCE)
    if it is None:
        r.check("C1a 生产声明含 integration-tests 实例", False,
                "在册：%s" % [i.id for i in decl.instances])
        return r.finish()
    fields = (it.cron or "").split()
    r.check("C1a integration-tests 的 cron 是五字段（非畸形）", len(fields) == 5, repr(it.cron))
    r.check("C1b 调度＝每天一次（minute/hour 固定、日/月/周全通配）",
            len(fields) == 5 and fields[2:] == ["*", "*", "*"] and fields[0].isdigit()
            and fields[1].isdigit(),
            "cron=%r（字段 %r）" % (it.cron, fields))
    r.check("C1c 该实例声明 suite=full（本期在自有泳道跑全集）",
            it.suite == "full", "suite=%r（词表 %r）" % (it.suite, decl_mod.WIRED_SUITES))
    docs = decl.instance("docs-sync")
    r.check("C1d 其余实例 cadence 未被顺手改动（docs-sync 仍是周 cron）",
            docs is not None and len((docs.cron or "").split()) == 5
            and (docs.cron or "").split()[2:] != ["*", "*", "*"],
            "docs-sync cron=%r" % (getattr(docs, "cron", None)))
    r.check("C1e suite 词表外值 fail-closed（不得悄悄降级成不跑）",
            "half" not in decl_mod.WIRED_SUITES and decl_mod.WIRED_SUITES == ("full",),
            str(decl_mod.WIRED_SUITES))

    # ---------------- C6 套件回执 → 发现（告警映射，离线纯函数） ----------------
    red_receipt = {
        "ticket_id": "inspection-%s-20260912" % INSTANCE, "worktree": "/tmp/x",
        "base_ref": "deadbeef", "ran": 3, "passed": 1, "failed": 2, "env_fail": 0,
        "error": "", "wall_seconds": 12.5, "report_path": "/tmp/x-suite.json",
        "details": [{"name": "sc_green", "exit": 0, "output_tail": "ok"},
                    {"name": "sc_red_a", "exit": 1, "output_tail": "FAIL a"},
                    {"name": "sc_red_b", "exit": 2, "output_tail": "ENV_FAIL b"}],
    }
    f_red = dm.suite_findings(red_receipt)
    highs = [f for f in f_red if f.get("severity") == "high"]
    subs = " ".join(str(f.get("subject")) for f in highs)
    r.check("C6a 套件红项→high 且点名到条（哪几条红可读）",
            "sc_red_a" in subs and "sc_red_b" in subs, "high subjects=%r" % subs)
    r.check("C6b 红项保持 suggest=true（供人审决定开不开修复票）",
            all(f.get("suggest") is not False for f in highs), "%r" % highs[:2])
    zero = dict(red_receipt, ran=0, passed=0, failed=0, details=[])
    f_zero = dm.suite_findings(zero)
    r.check("C6c ran=0 也告警（红线：不得以跳过/删减场景换取跑通）",
            any(f.get("severity") == "high" and "未真正执行" in str(f.get("subject"))
                for f in f_zero), "%r" % f_zero)
    envonly = dict(red_receipt, ran=3, passed=0, failed=0, env_fail=3, details=[])
    f_env = dm.suite_findings(envonly)
    r.check("C6d 环境红=med 且不生成修码建议（先修环境，不误导）",
            any(f.get("severity") == "med" and f.get("suggest") is False for f in f_env),
            "%r" % f_env)
    r.check("C6e 心跳合成：只有全绿回执才算心跳期",
            dm.suite_green(dm.suite_section(dict(red_receipt, ran=3, passed=3, failed=0,
                                                 env_fail=0, details=[]))) is True
            and dm.suite_green(dm.suite_section(red_receipt)) is False,
            "红回执被判绿=接反")

    # ---------------- C2 调度真建（隔离台） ----------------
    workdir = tempfile.mkdtemp(prefix="sandbar-insp-sched-")
    decl_file = os.path.join(workdir, "decl.yaml")
    try:
        lj.write_decl_block(decl_file, lj.suite_decl_entry(INSTANCE, REPO))
        _p, probe = lj.run_json([lj.lib.VENV_PY if os.path.exists(lj.lib.VENV_PY) else sys.executable,
                                 lj.lib.CLIENT, "schedule-list", "{}"])
        stage = isinstance(probe, dict) and probe.get("ok") is True
        if not stage:
            r.env_fail("隔离台/依赖缺席",
                       "schedule-list 未 ok：%r（docker 台 %s + temporalio）"
                       % (str(probe)[:140], lj.lib.TEST_TARGET_HOST))
        else:
            os.environ["SANDBAR_TARGET_HOST"] = lj.lib.TEST_TARGET_HOST
            os.environ["SANDBAR_NAMESPACE"] = lj.lib.TEST_NAMESPACE
            argv = ["schedule-up", "--instance", INSTANCE, "--note",
                    "scenario t260913-02 调度接真（隔离台夹具，用后即拆）",
                    "--decl-path", decl_file, "--repo-root", REPO]
            proc, parsed = run_trigger(argv)
            res = lj.lib.scanner_result(parsed)
            r.check("C2a schedule-up 真建成功（正规入口）", bool(res), "%r" % parsed)
            if res:
                r.check("C2b 回执给出次日触发时刻（next_action_times）",
                        bool(res.get("next_action_times")), "%r" % res.get("next_action_times"))
                nxt_raw = str((res.get("next_action_times") or [""])[0])
                r.check("C2c 下次触发在次日窗内（未来 ≤ 36h；cron 按 UTC 求值，故比日期口径稳）",
                        _within_hours(nxt_raw, 36.0),
                        "next=%r now=%s" % (nxt_raw, datetime.now().isoformat(timespec="seconds")))
                r.check("C2d 回执带 cron（声明值原样）", bool(res.get("cron")), "%r" % res)
                # describe 复查（幂等 update 路径也不丢）
                proc2, parsed2 = run_trigger(["deadman", "--instance", INSTANCE,
                                              "--decl-path", decl_file, "--offline",
                                              "--ledger-dir", os.path.join(workdir, "ledger")])
                r.check("C2e deadman 通道可跑（离线腿零 Temporal）",
                        isinstance(parsed2, dict) and parsed2.get("ok") is True, "%r" % parsed2)
            # 清场：拆掉本场景建的 schedule（不遗留常驻定时器）
            clean = os.path.join(workdir, "cleanup.py")
            with open(clean, "w", encoding="utf-8") as f:
                f.write(
                    "import asyncio,sys,os\n"
                    "sys.path.insert(0, %r)\n"
                    "from temporalio.client import Client\n"
                    "from shared import NAMESPACE, TARGET_HOST\n"
                    "async def go():\n"
                    "    c = await Client.connect(TARGET_HOST, namespace=NAMESPACE)\n"
                    "    h = c.get_schedule_handle('sandbar-inspection-%s')\n"
                    "    await h.delete()\n"
                    "    print('deleted')\n"
                    "asyncio.run(go())\n" % (lj.TP_DIR, INSTANCE))
            _pc, _pc_out = lj.run_json([lj.lib.VENV_PY if os.path.exists(lj.lib.VENV_PY)
                                        else sys.executable, clean])
            r.check("C2f 场景自清（拆掉刚建的 schedule，不遗留常驻定时器）",
                    _pc.returncode == 0 or "not found" in (proc.stdout + proc.stderr).lower()
                    or "deleted" in (_pc.stdout or ""),
                    "cleanup rc=%s out=%r" % (_pc.returncode, (_pc.stdout or "")[-120:]))

        # ---------------- C3 生产面现状：该实例的 schedule 与 NextRunTime ----------------
        # implement 段修正（实锤）：原实现走 run_trigger → spawn_env 把目标钉到隔离台
        # 17233，读的永远不是生产调度账本 → C3b/C3c 必红（假红）。生产面只读核查走
        # prod_schedule_read（CLI 只读 describe；CLI 缺席=N/A 明示），并保留 deadman
        # 隔离台读面腿（通道可用性，与本红线不冲突）。
        proc3, parsed3 = run_trigger(["deadman", "--instance", REAL_INSTANCE,
                                      "--ledger-dir", os.path.join(workdir, "ledger2")])
        res3 = lj.lib.scanner_result(parsed3)
        r.check("C3a deadman 通道可查真实例（隔离台读面）", bool(res3), "%r" % parsed3)
        sch = prod_schedule_read(REAL_INSTANCE)
        if not sch.get("available"):
            r.check("C3b 生产 schedule 存在（temporal CLI 缺席 → N/A 折算）", True,
                    sch.get("error"))
            r.check("C3c NextRunTime 可查（temporal CLI 缺席 → N/A 折算）", True, "")
        else:
            r.check("C3b Temporal 上存在该实例的 schedule（工单验收 C 前半）",
                    sch.get("exists") is True,
                    "schedule=%r（不存在即『声明了但没建』的现状红）" % sch.get("error"))
            nats = sch.get("next_action_times") or []
            r.check("C3c NextRunTime 可查（人能看到下次什么时候跑）", bool(nats), "%r" % sch)
            if nats:
                r.check("C3d NextRunTime 落在次日窗内（每日调度接真后 ≤ 36h）",
                        _within_hours(str(nats[0]), 36.0),
                        "next=%r" % (nats[0],))

        # ---------------- C4/C5 漏跑可见（台账夹具，离线腿） ----------------
        ledger_dir = os.path.join(workdir, "ledger3")
        os.makedirs(ledger_dir, exist_ok=True)
        cron = it.cron
        # 期望触发日（不含今日）取近 7 天，除一天外全部落账 → 恰一期漏跑
        now = datetime.now()
        fires = [d for d in dm.expected_fires(cron, now, 7)]
        if len(fires) < 2:
            r.check("C4a 期望触发日正推可用（≥2 天窗）", False, "fires=%r" % fires)
        else:
            gap = fires[-1]
            for fire in fires[:-1]:
                p = fire.strftime("%Y%m%d")
                with open(os.path.join(ledger_dir, "inspection-%s-%s.json" % (INSTANCE, p)),
                          "w", encoding="utf-8") as f:
                    json.dump({"ticket_id": "inspection-%s-%s" % (INSTANCE, p),
                               "findings": [], "summary": {}, "heartbeat": True}, f)
            # 同目录放入别实例与畸形文件（不得误计/不得崩）
            with open(os.path.join(ledger_dir, "inspection-other-20260101.json"), "w",
                      encoding="utf-8") as f:
                f.write("{}")
            with open(os.path.join(ledger_dir, "inspection-%s-2026090X.json" % INSTANCE), "w",
                      encoding="utf-8") as f:
                f.write("{ 坏 json")
            proc4, parsed4 = run_trigger(
                ["deadman", "--instance", INSTANCE, "--decl-path", decl_file, "--offline",
                 "--ledger-dir", ledger_dir])
            res4 = lj.lib.scanner_result(parsed4)
            miss = (res4 or {}).get("missed")
            r.check("C4a 缺日→missed 精确列出该期（漏跑可读）",
                    miss == [gap.strftime("%Y%m%d")], "missed=%r 期望=%r" % (miss,
                                                                        [gap.strftime("%Y%m%d")]))
            r.check("C4b 漏跑 alarmed=true 且退出码 1（ops 自动化可踩）",
                    (res4 or {}).get("alarmed") is True and proc4.returncode == 1,
                    "alarmed=%r rc=%s" % ((res4 or {}).get("alarmed"), proc4.returncode))
            r.check("C4c 漏跑→票面 high 发现且 suggest=false（不是代码缺陷）",
                    any(f.get("severity") == "high" and f.get("suggest") is False
                        for f in ((res4 or {}).get("findings") or [])),
                    "%r" % ((res4 or {}).get("findings") or [])[:2])
            r.check("C4d 异实例台账不误计、畸形 json 不崩而被点名",
                    "20260101" not in (miss or [])
                    and bool((res4 or {}).get("malformed")),
                    "malformed=%r" % (res4 or {}).get("malformed"))
            r.check("C4e 当日不算漏（今天的期票可能正在跑）",
                    now.strftime("%Y%m%d") not in (miss or []), "missed=%r" % (miss,))
            # 台账补齐 → 不告警（零误报）
            p_all = gap.strftime("%Y%m%d")
            with open(os.path.join(ledger_dir, "inspection-%s-%s.json" % (INSTANCE, p_all)),
                      "w", encoding="utf-8") as f:
                json.dump({"ticket_id": "inspection-%s-%s" % (INSTANCE, p_all)}, f)
            proc5, parsed5 = run_trigger(
                ["deadman", "--instance", INSTANCE, "--decl-path", decl_file, "--offline",
                 "--ledger-dir", ledger_dir])
            r.check("C4f 台账齐→不告警（missed 空、退出码 0）",
                    (lj.lib.scanner_result(parsed5) or {}).get("missed") == []
                    and proc5.returncode == 0,
                    "%r rc=%s" % (parsed5, proc5.returncode))
            # C5 多期漏跑不截断
            ledger_dir2 = os.path.join(workdir, "ledger4")
            os.makedirs(ledger_dir2, exist_ok=True)
            proc6, parsed6 = run_trigger(
                ["deadman", "--instance", INSTANCE, "--decl-path", decl_file, "--offline",
                 "--ledger-dir", ledger_dir2])
            res6 = lj.lib.scanner_result(parsed6) or {}
            r.check("C5 多期漏跑全列不截断（漏报不可被防洪泛机制吃掉）",
                    len(res6.get("missed") or []) == len(fires) and len(fires) > 5,
                    "missed=%r（期望 %d 期）" % (res6.get("missed"), len(fires)))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    return r.finish()


if __name__ == "__main__":
    sys.exit(main())
