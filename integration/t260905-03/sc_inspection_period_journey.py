#!/usr/bin/env python3
"""t260905-03 场景④：手动一期全链用户旅程（验收①主证据，灰盒 L3，真台真票）。

依据三支：①工单验收①「手动触发一期跑通全链（开票→扫描→清单→人门→收口）」+
「全绿期=零发现票作心跳证明」+「发现清单落票面（分严重度带证据）」+「修复票引用巡检
票号」；②方案 M3：人门复用既有审批门真拦——绑定浅的两拍口径：未签字不终态（假门=
自动放行，必红）→签字（运维通道 sign，who 注入非 agent 名）后到终态；③KI-051 教训：
发现面用 --decl-path + --repo-root 注入夹具隔离（真仓是干净的，不种漂移测不到发现
落面；真树零写入）。

票面承诺（交付绑定）：snapshot.face.{findings,summary,heartbeat,red_line,
suggested_fix_tickets}——high/med 发现逐条带 source_inspection=<本巡检票号>（修复票
溯源面）。环境语义：temporalio/共享台缺席=ENV_FAIL exit 2 点名，不假绿不静默。
实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。登记 exclusive：往共享台
写真票，防与兄弟场景互染判定面。与场景③不同面：③守声明门（谁能跑/同期一票），本条
守链路质量（发现落面、人门真拦、心跳照开、修复溯源、审计链不断）。
"""
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib_inspection as lib
# t260916-22：scan 段退役 → inspect 段（桩 agent）。真链旅程的发现注入走桩缝
# （SANDBAR_INSPECT_STUB=1+STUB_FILE，方案 §3 缝名）；伪造器单点在 t260916-22/lib_inspect。
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "t260916-22"))
import lib_inspect as inspect_lib  # noqa: E402

# 实例 id 带进程级唯一戳：每期一票按「实例 id+期号」去重——共享台上重跑旅程/与
# decl-gate 的 integration-tests 同实例同日会撞去重回执（拿到已收口旧票=假门误报），
# 唯一实例 id 让旅程每次拿到自己的新票（期号仍取当日，两实例票号互异断言不变）。
_STAMP = os.getpid() % 100000
TWO_INSTANCE_DECL = """schema: v1
instances:
  - id: integration-tests-%05d
    enabled: true
    project_key: sandbar
    schedule:
      kind: cron
      cron: 0 6 * * 1
    workflow: InspectionPeriodicWorkflow
    template: inspection-lite
  - id: docs-sync-%05d
    enabled: true
    project_key: sandbar
    schedule:
      kind: cron
      cron: 0 7 * * 1
    workflow: InspectionPeriodicWorkflow
    template: inspection-lite
""" % (_STAMP, _STAMP)

SIGN_WHO = "human-scenario"       # 非 agent 角色名（agent 不得自签）
POLL_OPEN = 60                    # 等开票可见
POLL_GATE = 20                    # 未签不终态的观察窗（假门在此现形）
POLL_CLOSE = 180                  # 签字后等收口
TERMINAL_OK = "COMPLETED"


def ticket_query(tid):
    _proc, parsed = lib.run_client("ticket", {"op": "query", "ticket_id": tid})
    if isinstance(parsed, dict) and parsed.get("ok") is True:
        return (parsed.get("result") or {})
    return None


def poll(fn, timeout, interval):
    """轮询至 fn 返回真值或超时；返回 (ok, last)。"""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = fn()
        if last:
            return True, last
        time.sleep(interval)
    return False, last


def journey_one(tag, instance, scan_root, workdir, failures, expect_findings,
                expect_unverified=False):
    """单实例全链：trigger(--decl-path/--repo-root 注入)→开票→清单落票面→人门两拍→收口。"""
    decl = os.path.join(workdir, "two.yaml")
    proc, parsed = lib.run_trigger(
        ["trigger", "--instance", instance, "--decl-path", decl, "--repo-root", scan_root])
    if not isinstance(parsed, dict) or parsed.get("ok") is not True:
        failures.append("%s 触发未放行：%r | stderr=%s"
                        % (tag, parsed, (proc.stderr or "")[:200]))
        return None
    tid = str((parsed.get("result") or {}).get("ticket_id") or "")
    if not tid:
        failures.append("%s 放行回执未带 ticket_id：%r" % (tag, parsed.get("result")))
        return None

    # 开票可见且票面就绪：**在 face 内容上轮询**（findings 成形=report 段已过），
    # 不在「可查询」上轮询——可查询时 workflow 可能仍在 scan 段、face 尚空（竞态教训）
    def face_ready():
        r = ticket_query(tid)
        if not (r and isinstance(r.get("snapshot"), dict)):
            return None
        f = r["snapshot"].get("face")
        if not (isinstance(f, dict) and isinstance(f.get("findings"), list)):
            return None
        return r
    ok, res = poll(face_ready, POLL_OPEN, 2)
    if not ok:
        r = ticket_query(tid)
        failures.append("%s 票 %s 开出后 %ds 票面未就绪（status=%r）——收口前断链"
                        % (tag, tid, POLL_OPEN, (r or {}).get("status")))
        return None

    # 发现清单落票面（snapshot.face 承诺结构）
    snap = res.get("snapshot") or {}
    face = snap.get("face") or {}
    findings = face.get("findings")
    if not isinstance(findings, list):
        failures.append("%s 票面 snapshot.face 缺 findings 清单（交付票面承诺）：%r"
                        % (tag, sorted(face) if isinstance(face, dict) else face))
    elif expect_findings:
        highs = [f for f in findings if isinstance(f, dict) and f.get("severity") == "high"]
        if not highs:
            failures.append("%s 种漂移夹具但票面无 high 发现：%r" % (tag, findings))
        fixes = face.get("suggested_fix_tickets") or []
        src = {str(s.get("source_inspection") or "") for s in fixes if isinstance(s, dict)}
        if not fixes:
            failures.append("%s 有 high/med 发现但零开票建议（建议面缺席）" % tag)
        elif tid not in src:
            failures.append("%s 开票建议未引用本巡检票号（source_inspection 溯源面破）：%r"
                            % (tag, src))
    else:
        if findings != []:
            failures.append("%s 干净扫描根应零发现心跳票，实际：%r" % (tag, findings))
        if face.get("heartbeat") is not True:
            failures.append("%s 零发现票 heartbeat 非 true（心跳证明面破）：%r"
                            % (tag, face.get("heartbeat")))

    # t260916-22：用户可见段名=inspect（scan 段退役面）；坏证据发现降级 unverified+点名
    stages = [str(e.get("stage") or "") for e in (snap.get("timeline") or [])
              if isinstance(e, dict)]
    if stages and "inspect" not in stages:
        failures.append("%s timeline 无 inspect 段（scan 退役后段名可见面破）：%r" % (tag, stages))
    if expect_unverified:
        unv = [f for f in (findings or []) if isinstance(f, dict)
               and inspect_lib.finding_state(f) == "unverified"]
        if not unv:
            failures.append("%s 混合桩的坏证据发现未降级 unverified（证据复核面缺席）：%r"
                            % (tag, [f.get("subject") for f in findings if isinstance(f, dict)]))
        elif not any(inspect_lib.entry_reason(f) for f in unv):
            failures.append("%s unverified 条目零 reason（逐项点名面缺席，静默丢）" % tag)

    # 人门两拍·第①拍：未签字不终态（假门=自动放行在此现形）
    def is_terminal():
        r = ticket_query(tid)
        return bool(r and r.get("status") == TERMINAL_OK)
    became_terminal, _ = poll(is_terminal, POLL_GATE, 2)
    if became_terminal:
        failures.append("%s 人门假门：未签字票 %ds 内已到终态（收口必须被人门真拦）"
                        % (tag, POLL_GATE))

    # 签字（运维通道 sign：who 注入非 agent 名；gate 由 workflow 侧校验 inspection-close）
    proc, parsed = lib.run_trigger(["sign", "--instance", instance,
                                    "--who", SIGN_WHO, "--decision", "approve",
                                    "--decl-path", decl])
    if not isinstance(parsed, dict) or parsed.get("ok") is not True:
        failures.append("%s 签字被拒：%r | stderr=%s"
                        % (tag, parsed, (proc.stderr or "")[:200]))
        return tid

    # 人门两拍·第②拍：签字后到终态，且发现清单留存**落账**（审计链不断）。
    # 留存面=落账 JSON 而非 workflow query——收口后 workflow 已关闭，query 随之不可达
    # （对已关 workflow 发 query=自造红灯，arbitrate 教训）；write_inspection_report
    # 在收口时再写一次终态（同票覆盖），落账即承诺的「发现留存票面」持久面。
    def closed():
        r = ticket_query(tid)
        return bool(r and r.get("status") == TERMINAL_OK)
    ok, _ = poll(closed, POLL_CLOSE, 3)
    if not ok:
        r = ticket_query(tid)
        failures.append("%s 签字后 %ds 未收口（status=%r）——收口段断链"
                        % (tag, POLL_CLOSE, (r or {}).get("status")))
    else:
        ledger = lib.inspection_ledger(tid)
        if not isinstance(ledger, dict):
            failures.append("%s 收口后落账缺席（out/inspection/<票号>.json）——发现留存面断"
                            % tag)
        elif not isinstance(ledger.get("findings"), list):
            failures.append("%s 收口后落账缺 findings 清单（发现/处置审计链断）：%r"
                            % (tag, sorted(ledger)[:8]))
    return tid


def main() -> int:
    lib.require_entry(lib.TRIGGER, "巡检触发入口")
    lib.require_entry(lib.CLIENT, "client 工单面")
    # 主进程零 temporalio 依赖（client/trigger 子进程自选 venv python）；探活失败统一归因
    _proc, parsed = lib.run_client("schedule-list", {})
    if not (isinstance(parsed, dict) and parsed.get("ok") is True):
        lib.die_env("放行不可验：temporalio 缺席或共享测试台不可达（schedule-list 未 ok：%r）"
                    "——全链旅程需要真台真票，不假红不假绿" % (str(parsed)[:160]))

    failures = []
    # 私有队列（tests-fault 供给隔离）：trigger 子进程与 StageWorker 同队列——
    # activities 跟随 workflow 启动队列，生产 worker（对本票 workflow/activity 类
    # 未注册，抢活即打回 not-registered）永不在私有队列上，竞态消除（arbitrate 实证：
    # 共队列时同套件两子用例一成一败=非确定）。
    private_queue = "suyou-insp-journey-%05d" % _STAMP
    os.environ["SANDBAR_TASK_QUEUE"] = private_queue   # lib 子进程（trigger/sign）经 os.environ 继承
    workdir = tempfile.mkdtemp(prefix="sandbar-insp-journey-")
    with open(os.path.join(workdir, "two.yaml"), "w", encoding="utf-8") as f:
        f.write(TWO_INSTANCE_DECL)
    drift = lib.ki051_high_tree("journey-drift")
    clean = lib.clean_tree("journey-clean")
    # t260916-22：inspect 段发现注入=桩消息文件（内容在每子用例触发前重写——inspect 活动
    # 在 spawn 时刻读取）；证据锚=夹具树内真实文件行（复核才有真过/真不过两子用例）。
    stub_path = inspect_lib.write_stub_file(workdir, "stub-message.txt",
                                            inspect_lib.fenced_message([]))
    _ANCHOR_REL = "integration/sc_inspect_anchor.mjs"
    _ANCHOR_L2 = "const guardLabel = await page.locator('.session-create').innerText();"
    drift.write(_ANCHOR_REL,
                "// 巡检证据锚夹具（t260916-22）\n" + _ANCHOR_L2 + "\n")
    inspect_stub_env = {"SANDBAR_INSPECT_STUB": "1",
                        "SANDBAR_INSPECT_STUB_FILE": stub_path}
    try:
        # 自供给 worker（tests-fault 供给缺口自补）：本票 workflow 未合并前台上常驻
        # worker 不认识它——票开得出但 query/收口无人执行；仓内先例=ticket-lifecycle
        # 起 worker 起票。__exit__ 必回收（TERM→KILL）。合并后主仓 worker 承接，仍兼容。
        with lib.StageWorker(private_queue, extra_env=inspect_stub_env):
            # 全链·种漂移实例：开票→发现落面（high+溯源建议）→人门两拍→收口→发现留存
            with open(stub_path, "w", encoding="utf-8") as f:
                f.write(inspect_lib.fenced_message([
                    inspect_lib.finding("锚漂移高危（建议合格）", _ANCHOR_REL, 2, _ANCHOR_L2,
                                        severity="high", confidence=0.9),
                    inspect_lib.finding("低置信观察（不建议）", _ANCHOR_REL, 2, "const guardLabel",
                                        severity="med", confidence=0.3),
                    inspect_lib.finding("越界行号（复核必降级）", _ANCHOR_REL, 9999, "x",
                                        severity="high", confidence=0.9),
                ]))
            tid_a = journey_one("journey[integration-tests]", "integration-tests-%05d" % _STAMP, drift.root,
                                workdir, failures, expect_findings=True, expect_unverified=True)
            # 全链·干净实例：零发现心跳票照开照收（全绿期=心跳证明）
            with open(stub_path, "w", encoding="utf-8") as f:
                f.write(inspect_lib.fenced_message([]))
            tid_b = journey_one("journey[docs-sync]", "docs-sync-%05d" % _STAMP, clean.root,
                                workdir, failures, expect_findings=False)
            if tid_a and tid_b and tid_a == tid_b:
                failures.append("两实例开出同一票号（实例维度串票）：%r" % tid_a)
    finally:
        drift.cleanup()
        clean.cleanup()
        shutil.rmtree(workdir, ignore_errors=True)

    if failures:
        for m in failures:
            print("FAIL_REASON: " + m, flush=True)
        return 1
    print("PASS: 双实例全链——发现清单落票面（high 带证据+suggested_fix_tickets 溯源"
          "source_inspection）；人门真拦两拍（未签不终态/签后收口且发现留存）；"
          "零发现心跳票照开照收；实例维度不串票", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
