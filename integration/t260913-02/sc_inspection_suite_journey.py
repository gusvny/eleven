#!/usr/bin/env python3
"""t260913-02 场景②：巡检「搭泳道 → 跑全集 → 拆泳道 → 落票面」全链旅程
（灰盒 L3，真 Temporal 私有队列真工作流；suite 腿用快夹具，免 10 分钟套件拖死）。

intent（守护的用户可感知行为/契约）：
  B1 巡检票自带「跑全集」阶段且顺序为 setup → suite → inspect → report → close
     （宿主令「巡检要有自己的工作流程」的机械面：阶段机不得套用 dev-lane 序列）；
  B2 跑套件发生在**巡检自己的 worktree** 里：票面证据给出 worktree 路径（巡检
     命名空间）与基点 sha，两者真落盘可交叉验证（`git -C <worktree> rev-parse
     HEAD` == 票面基点）；
  B3 套件结果进票面可读：ran/passed/failed/env_fail 与逐场景红绿、墙钟、报告
     文件路径（有红项时点得出是哪几条）；
  B4 红项＝high 发现 + 开票建议（source_inspection=本巡检票号）——「红项供人审
     决定开不开修复票」；
  B5 跑完全集才进人门：泳道在人门前已拆干净（worktree 与分支都无）——人审看到
     的票面不再依赖一个活着的泳道（同时收敛「泳道残留」风险）；
  B6 「ran=0 也告警」的机械面：**一个都没真跑**（空场景集/套件跑不起来）不得当
     心跳——套件未真正执行须报 high（红线「不得以跳过或删减场景换取跑通」）；
  B7 泳道搭不起来（仓库不可用）→ 票面 blocked 且**落账可见**（漏跑不得静默的
     in-workflow 面）；
  B8 跑套件对**主工作树零改动**：tracked 内容逐字节一致、HEAD 不动、主树工作区
     干净（套件只在 lane 里跑）。

依据三支：①工单验收 A/B/E（自有 worktree+基点+拆干净+主树零改动；票面逐场景红绿/
墙钟/报告路径；人门与既有扫描面零改）与红线；②KI 清单本票触及项：KI-060（套件健康
无人值守——本票正解对象）、KI-063（动输入契约必带全链场景——故本条走真 workflow 而
非只调函数）、KI-072（负载敏感假红——套件红项聚合不得掩盖条数）；③组件对外契约：
`prepare_workspace` / `run_integration_tests`（IntegrationRunArgs/IntegrationRunResult
字段 ran/passed/failed/env_fail/details）/ `teardown_lane` 的公开回执形状，以及
InspectionPeriodicWorkflow 的 snapshot 读面（stage/stage_state/status/face/timeline）。

intent 分工（防 intent 级重复）：与 t260905-03-period-journey（手动一期全链：开票→
扫描→清单→人门→收口；无泳道、不跑套件）不同面——本条只增「泳道+套件」两阶段与
其票面证据，扫描/人门两拍不复测；与 t260911-02-trigger-kinds（计数 kind 拉活 watcher）
不同面；与 t260913-02 场景①（泳道生命周期纯机械面）不同层：①离线直调活动，本条走
真 workflow 编排（阶段机/票面/时序只有真链路可见）。

环境：真 docker 隔离台（17233）+ 私有队列自供给 worker；缺台/缺 temporalio=ENV_FAIL
exit 2 点名（不假绿不静默）。suite 腿走**夹具仓**（integration.cmd 恒红一行）——
真链编排与票面证据面全验，10 分钟真套件由场景③在真仓上跑（同 intent 两腿分家：
本条验编排，③验「真全集」）。
实现段落地前红属预期（TDD 验收门），arbitrate/merge 期必须绿。
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib_lane_journey as lj  # noqa: E402

STAMP = os.getpid() % 100000
INSTANCE = "suite-journey-%05d" % STAMP
PERIOD = "20260913"
SIGN_WHO = "human-scenario"          # 非 agent 角色名（agent 不得自签）

POLL_FACE = 180                      # 等票面成形（含套件腿）
POLL_GATE = 20                       # 未签不终态的观察窗（人门真拦）
POLL_CLOSE = 180                     # 签字后等收口
TERMINAL = "COMPLETED"
DONE_STATES = ("COMPLETED", "FAILED", "TERMINATED", "CANCELED", "CLOSED")

# 夹具套件的场景集：一条恒绿 + 一条产品红（红项→high 发现的判定面）。
# 输出走**集成道现行协议行**（verify_lane._integ 解析：`PASS [name]` / `FAIL [name]
# exit=N` / `ENV_FAIL [name] exit=2`，缩进行进 output_tail）——旧的 `SUMMARY pass=…`
# 文本协议早已退役，夹具若还按旧协议印字，集成道会如实报 ran=0（本票 B6「ran=0 也告警」
# 的机械面正是这么被触发的：夹具协议错 → 0 场景 → high 发现，而不是假绿）。
FIXTURE_SUITE_CMDS = {
    "integration/sc_suite_green.py": (
        "#!/usr/bin/env python3\n"
        "print('PASS [fixture-green]')\n"
        "raise SystemExit(0)\n"),
    "integration/sc_suite_red.py": (
        "#!/usr/bin/env python3\n"
        "print('FAIL [fixture-red] exit=1')\n"
        "print('    fixture-red 明细：夹具里恒红的一条场景（产品红）')\n"
        "raise SystemExit(1)\n"),
}


def build_fixture_repo() -> str:
    """建夹具仓：两条夹具场景 + 恒红的 integration.cmd（suite 腿跑得快且必红）。"""
    root = os.path.realpath(lj.fixture_repo("suite"))
    for rel, text in FIXTURE_SUITE_CMDS.items():
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
    vp = os.path.join(root, "verify.yaml")
    with open(vp, "w", encoding="utf-8") as f:
        f.write("schema: v1\n"
                "lanes:\n"
                "  code:\n"
                "    write_allow:\n"
                "      - server/\n"
                "      - integration/\n"
                "    checks:\n"
                "      - id: trivial\n"
                "        cmd: 'true'\n"
                "integration:\n"
                "  cmd: python3 integration/sc_suite_green.py; python3 integration/sc_suite_red.py; true\n")
    with open(os.path.join(root, "integration", "run_scenarios.py"), "w", encoding="utf-8") as f:
        f.write("SCENARIOS = [\n"
                "    ('fixture-green', '夹具绿场景（编排腿）', 'python3 integration/sc_suite_green.py', 'exclusive'),\n"
                "    ('fixture-red', '夹具红场景（红项→发现腿）', 'python3 integration/sc_suite_red.py', 'exclusive'),\n"
                "]\n")
    # 夹具仓在 fixture_repo 的「init」提交之后重写文件——再落一个提交把它收进 HEAD，
    # 使「基点=开跑时 main HEAD」与工作区干净两条断言同源（不制造部署后脏工作区）。
    lj.commit_all(root, "fixture suite")
    return root


def ticket_snapshot(tid: str, live: bool = False):
    """票面/状态读面。

    - live=False：读巡检落账（`out/inspection/<票号>.json`）——本票的「列表可读面」
      本体，毫秒级；写点=report 段与人门后收口（故 stage/stage_state 实时性有限，
      但 face 与 findings/suite 齐备）。
    - live=True：走 CLI ticket-query（真 workflow snapshot：stage/stage_state 实时）；
      收口后 workflow 关闭、query 不可达 → 回落落账（不把「已收口」误报成产品红）。
    """
    py = lj.lib.VENV_PY if os.path.exists(lj.lib.VENV_PY) else sys.executable
    if live:
        _proc, parsed = lj.run_json([py, lj.lib.CLIENT, "ticket",
                                     json.dumps({"op": "query", "ticket_id": tid},
                                                ensure_ascii=False)])
        if isinstance(parsed, dict) and parsed.get("ok") is True:
            res = parsed.get("result") or {}
            snap = res.get("snapshot") or {}
            snap.setdefault("status", res.get("status") or "")
            return snap
    led = lj.ledger(tid)
    if isinstance(led, dict) and led:
        closed = bool(led.get("human_gate"))
        return {"status": "CLOSED" if closed else "RUNNING",
                "stage": "close" if closed else "",
                "stage_state": "done" if closed else "",
                "face": led, "timeline": led.get("timeline") or []}
    if not live:
        _proc, parsed = lj.run_json([py, lj.lib.CLIENT, "ticket",
                                     json.dumps({"op": "query", "ticket_id": tid},
                                                ensure_ascii=False)])
        if isinstance(parsed, dict) and parsed.get("ok") is True:
            res = parsed.get("result") or {}
            snap = res.get("snapshot") or {}
            snap.setdefault("status", res.get("status") or "")
            return snap
    return None


def poll(fn, timeout, interval=2.0):
    import time
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = fn()
        if last:
            return True, last
        time.sleep(interval)
    return False, last


def main() -> int:
    r = lj.Rule("sc_inspection_suite_journey")

    lib = lj.lib
    lib.require_entry(lib.TRIGGER, "巡检触发入口")
    lib.require_entry(lib.CLIENT, "client 工单面")
    # 隔离台探活（真链路腿无 stdlib 替代）
    _p, parsed = lib.run_client("schedule-list", {})
    if not (isinstance(parsed, dict) and parsed.get("ok") is True):
        r.env_fail("隔离台/依赖缺席", "schedule-list 未 ok：%r（docker 台 %s + temporalio；"
                                     "sh server/docker-compose.test.yml up -d）"
                   % (str(parsed)[:160], lib.TEST_TARGET_HOST))
        return r.finish()

    os.environ["SANDBAR_TARGET_HOST"] = lib.TEST_TARGET_HOST
    os.environ["SANDBAR_NAMESPACE"] = lib.TEST_NAMESPACE
    queue = "sandbar-insp-suite-%05d" % STAMP
    os.environ["SANDBAR_TASK_QUEUE"] = queue
    # t260913-02 implement 段接线：套件开关由 **workflow 运行期读声明**（resolve_inspection_plan
    # 活动）判定，不进调度/触发 payload——所以声明文件必须让自供给 worker 也看得见：经
    # SANDBAR_INSPECTION_DECL（lib_inspection 已登记的绑定名；spawn_env 透传非红线 env）
    # 注入，与 --decl-path 同源同文件（两处读的必须是同一份声明，否则「在册/停用」判定分家）。
    workdir = tempfile.mkdtemp(prefix="sandbar-insp-suite-")
    fixture = ""
    outdir = os.path.join(workdir, "ledger")
    os.environ["SANDBAR_INSPECTION_DIR"] = outdir
    decl = os.path.join(workdir, "decl.yaml")
    try:
        fixture = build_fixture_repo()
        base = lj.head_sha(fixture)
        # 声明：本实例走「套装实例」形态（suite 键由实现段声明面接线）
        lj.write_decl_block(decl, lj.suite_decl_entry(INSTANCE, fixture))
        # workflow 体不携带声明路径（开关不进 payload）：运行期声明决议活动读
        # SANDBAR_INSPECTION_DECL（default_decl_path 的 env 单点）——worker 子进程必须
        # 继承同一声明，否则 resolve_inspection_plan 按仓内真声明查不到夹具实例而 blocked
        # （声明漂移语义正确，但不是本场景要测的面）。
        os.environ["SANDBAR_INSPECTION_DECL"] = decl

        os.environ["SANDBAR_INSPECTION_DECL"] = decl   # worker 与 trigger 读同一份声明
        with lib.StageWorker(queue):
            proc, parsed = lib.run_trigger(
                ["trigger", "--instance", INSTANCE, "--period", PERIOD,
                 "--decl-path", decl, "--repo-root", fixture])
            res = lib.scanner_result(parsed)
            if not res or not res.get("ticket_id"):
                r.check("B0 真工作流开票成功", False,
                        "%r | stderr=%s" % (parsed, (proc.stderr or "")[:200]))
                return r.finish()
            tid = str(res["ticket_id"])
            lib.note_started_ticket(tid)

            # ---- B1 阶段机 + B2/B3/B4 票面证据 ----
            # 等待面：票面成形（含套件段）或已到人门/终态——不以「可查询」当就绪，
            # 也不为等一段不存在的阶段空烧观察窗（红跑要快、真红要准）。
            def face_ready():
                snap = ticket_snapshot(tid)
                if not isinstance(snap, dict):
                    return None
                face = snap.get("face") or {}
                if isinstance(face.get("suite"), dict) and face["suite"].get("report_path"):
                    return snap
                if snap.get("stage") in ("report", "close") or snap.get("status") in DONE_STATES:
                    return snap
                return None

            _ok, snap = poll(face_ready, POLL_FACE)
            snap = snap or {}
            face = snap.get("face") or {}
            # 阶段序列读「真 workflow snapshot 的 timeline」（落账面无 timeline；此刻票
            # 应停在人门，workflow 仍在，query 可达）
            live_snap = ticket_snapshot(tid, live=True) or {}
            stages = lj.stage_names(live_snap if live_snap.get("timeline") else snap)
            r.check("B1a 阶段机含巡检自有阶段（setup/suite/inspect）",
                    all(s in stages for s in ("setup", "suite", "inspect")),
                    "实得阶段序列：%s（状态 %r）" % (stages, snap.get("status")))
            r.check("B1b 阶段顺序 setup → suite → inspect → report → close",
                    stages[:5] == ["setup", "suite", "inspect", "report", "close"],
                    "实得：%s" % stages)
            r.check("B1c 未套用 dev-lane 阶段序列（无 plan/implement/arbitrate/merge 段）",
                    not [s for s in stages if s in ("create_plan", "review_plan", "implement",
                                                    "integ_join", "arbitrate", "merge")],
                    "实得：%s" % stages)

            suite = face.get("suite") if isinstance(face.get("suite"), dict) else {}
            r.check("B2a 票面给出套件 worktree 路径（巡检命名空间）",
                    bool(suite.get("worktree")), "suite=%r" % (suite or face.get("suite_error")))
            wt = str(suite.get("worktree") or "")
            rel = os.path.relpath(wt, fixture).replace(os.sep, "/") if wt else ""
            r.check("B2b 套件确在巡检命名空间的 worktree 里跑",
                    bool(lj.LANE_RE.match(rel)) and INSTANCE in rel, "%r ↦ %r" % (wt, rel))
            r.check("B2c 票面基点 sha = 开跑时 main HEAD（夹具仓可交叉验证）",
                    str(suite.get("base_ref") or "") == base,
                    "票面=%s 期望=%s" % (str(suite.get("base_ref") or "")[:8], base[:8]))

            r.check("B3a 票面套件摘要给出 ran/passed/failed（全集跑没跑判得出）",
                    all(k in suite for k in ("ran", "passed", "failed")),
                    "suite keys=%s" % sorted(suite))
            r.check("B3b 逐场景红绿可读（cases 逐条带名与 exit）",
                    isinstance(suite.get("cases"), list) and len(suite.get("cases") or []) >= 2
                    and all("name" in c for c in (suite.get("cases") or [])),
                    "cases=%r" % (suite.get("cases"),))
            r.check("B3c 整轮墙钟可得（wall_seconds>0）",
                    isinstance(suite.get("wall_seconds"), (int, float))
                    and float(suite.get("wall_seconds") or 0) > 0,
                    "%r" % suite.get("wall_seconds"))
            r.check("B3d 套件回执/报告文件路径可读且真存在",
                    bool(suite.get("report_path")) and os.path.exists(str(suite.get("report_path"))),
                    "%r" % suite.get("report_path"))
            red = [c for c in (suite.get("cases") or []) if int(c.get("exit") or 0) != 0]
            r.check("B3e 红的是哪几条可点名（夹具红场景在内）",
                    any("fixture-red" in str(c.get("name")) for c in red), "红项：%r" % red)

            highs = [f for f in (face.get("findings") or [])
                     if isinstance(f, dict) and f.get("severity") == "high"]
            r.check("B4a 套件红项进发现清单且判 high", bool(highs), "high=%r" % highs[:3])
            srcs = {str(s.get("source_inspection") or "") for s in (face.get("suggested_fix_tickets") or [])}
            r.check("B4b 红项生成开票建议并溯源本巡检票号", tid in srcs, "sources=%r" % srcs)
            r.check("B4c 心跳不被套件红污染（有红期不得报心跳/全绿）",
                    face.get("heartbeat") is not True, "heartbeat=%r" % face.get("heartbeat"))

            # ---- B5 人门两拍（泳道已在人门前拆干净）----
            def at_gate_or_terminal():
                snap0 = ticket_snapshot(tid, live=True)
                if not snap0:
                    return None
                return snap0 if (str(snap0.get("status")) in DONE_STATES
                                 or snap0.get("stage_state") == "awaiting-human") else None
            reached, _ = poll(at_gate_or_terminal, POLL_FACE)
            st_now = ticket_snapshot(tid, live=True) or {}
            r.check("B5a 人门真拦：未签字停在 awaiting-human（不得直接终态）",
                    bool(reached) and st_now.get("stage_state") == "awaiting-human"
                    and str(st_now.get("status")) not in DONE_STATES,
                    "status=%r stage=%r/%r" % (st_now.get("status"), st_now.get("stage"),
                                               st_now.get("stage_state")))
            r.check("B5b 人门前泳道已拆干净（worktree 与分支都无）",
                    not lj.lane_worktrees(fixture, INSTANCE)
                    and not [b for b in lj.branches(fixture) if b.startswith("inspection/")],
                    "%s / %s" % (lj.lane_worktrees(fixture, INSTANCE),
                                 [b for b in lj.branches(fixture) if b.startswith("inspection/")]))
            proc, parsed = lib.run_trigger(["sign", "--instance", INSTANCE, "--period", PERIOD,
                                            "--who", SIGN_WHO, "--decision", "approve",
                                            "--decl-path", decl])
            r.check("B5c 签字被放行（人门语义未改）",
                    bool(lib.scanner_result(parsed)), "%r" % parsed)

            def terminal():
                # 收口后 workflow 关闭（query 不可达）——终态判据=落账里出现人门签字记录
                led = lj.ledger(tid)
                return bool(isinstance(led, dict) and led.get("human_gate"))
            closed, _ = poll(terminal, POLL_CLOSE, 3.0)
            led_now = lj.ledger(tid)
            r.check("B5d 签字后收口（人门签字记录落账，收口终态）", closed,
                    "ledger human_gate=%r" % (led_now or {}).get("human_gate"))
            ledger = lj.ledger(tid)
            r.check("B5e 收口后落账在位（列表可读面）", isinstance(ledger, dict),
                    "ledger 缺：%s" % os.path.join(outdir, tid + ".json"))
            r.check("B5f 落账保留套件证据（收口不丢证据）",
                    isinstance(ledger, dict) and isinstance(ledger.get("suite"),
                                                             (dict, type(None))),
                    "ledger keys=%s" % (sorted(ledger) if isinstance(ledger, dict) else None))

        # ---- B7 泳道搭不起来 → blocked 且落账可见 ----
        bad_decl = os.path.join(workdir, "bad.yaml")
        bad_root = os.path.join(workdir, "not-a-repo")     # 非 git 仓：worktree add 必失败
        os.makedirs(bad_root, exist_ok=True)
        bad_instance = "suite-badlane-%05d" % STAMP
        lj.write_decl_block(bad_decl, lj.suite_decl_entry(bad_instance, bad_root))
        os.environ["SANDBAR_INSPECTION_DECL"] = bad_decl   # B7 腿同样：两处同源
        with lib.StageWorker(queue + "-b"):
            # implement 段实锤（探针 out/probe_badlane.py）：worker 起在 queue+"-b"，
            # 而 trigger 子进程继承 ambient 的 SANDBAR_TASK_QUEUE=queue（上一腿的队列，
            # worker 已退出）→ 票起在无人服务的队列上 → 查询超时 → B7 假红（票面与落账
            # 其实都对，探针实测 blocked+blocked_reason 齐备）。两处必须同队列。
            os.environ["SANDBAR_TASK_QUEUE"] = queue + "-b"
            _p2, p2 = lib.run_trigger(["trigger", "--instance", bad_instance, "--period", PERIOD,
                                       "--decl-path", bad_decl, "--repo-root", bad_root])
            res2 = lib.scanner_result(p2)
            if not res2 or not res2.get("ticket_id"):
                r.check("B7 泳道搭不起的实例可开票（票面须承载失败）", False, "%r" % p2)
            else:
                tid2 = str(res2["ticket_id"])
                lib.note_started_ticket(tid2)

                def blocked():
                    r0 = ticket_snapshot(tid2, live=True)
                    return r0 if (r0 and (r0.get("status") == "blocked"
                                          or str(r0.get("status")) in DONE_STATES)) else None
                ok2, snap2 = poll(blocked, POLL_FACE, 3.0)
                r.check("B7a 泳道搭不起来 → 票面 blocked（不假绿继续跑）",
                        bool(ok2) and (snap2 or {}).get("status") == "blocked",
                        "status=%r" % (ticket_snapshot(tid2, live=True) or {}).get("status"))
                led2 = lj.ledger(tid2)
                r.check("B7b blocked 终态落账可见（漏跑不静默的列表面）",
                        isinstance(led2, dict) and bool(led2.get("blocked_reason")),
                        "ledger=%r" % (sorted(led2) if isinstance(led2, dict) else None))
                if isinstance(led2, dict):
                    r.check("B7c blocked 票面点明失败原因（报错精确：哪个检查失败）",
                            "setup" == str(led2.get("stage")) and bool(led2.get("blocked_reason")),
                            "stage=%r blocked_reason=%r" % (led2.get("stage"),
                                                            led2.get("blocked_reason")))
                    r.check("B7d blocked 落账带时间线（阶段机证据可读）",
                            isinstance(led2.get("timeline"), list) and bool(led2.get("timeline")),
                            "timeline=%r" % (led2.get("timeline") or [])[:2])

        # ---- B8 主树零改动（真链路全程）----
        st = lj.tracked_status(fixture)
        r.check("B8 全链跑完夹具主工作树零改动（tracked 无改动 + 工作区干净）",
                st["diff_head"] == "" and st["status"] == [], "%r" % st)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
        if fixture:
            lj.cleanup_paths(fixture)

    return r.finish()


if __name__ == "__main__":
    sys.exit(main())
