#!/usr/bin/env python3
"""t260915-08 场景③：巡检人门签字链路真签收口（灰盒 L3，隔离台真票，exclusive）。

用户场景（工单正文④+验收①「签字链路真签一张沙箱巡检票收口」）：巡检票报到人审门后，
宿主在操作面签字必须真能收口——通道=工作台同款（node.ts op=sign 即 client.py
`ticket op=sign` → Temporal sign 信号），gate 必须对（inspection-close），agent 不得
自签；收口后 decision/human_gate 落票面、落账在（审计链不断）。

断言面（五子用例）：
  ① 常态子用例：票到 close/awaiting-human 时 face **无 human_gate 键**（签字前常态缺席，
     待签判定走 stage_state——review 打回4 的行为面）；
  ② 拒收子用例·错 gate：用错 gate 签 → workflow 拒收（gate_error 可读、票仍 awaiting-human
     不终态）——「gate 不匹配拒收」契约的注入回归；
  ③ 拒收子用例·agent 自签：who=agent 角色名 + 对的 gate → 仍拒收（自签禁令契约）；
  ④ 收口子用例：对 gate 真签 → status=closed、decision=approve、face.human_gate 落面、
     落账文件在（out/inspection/<票号>.json）；
  ⑤ 板面收录子用例：收口票进 ticket-list{kind:"inspection"} 板面（完整巡检形+白名单回执，
      SANDBAR_INSPECTION_DECL 注入声明，规格① 真台端到端）。
  附带：签字前 ticket-query 读回（坑A 活体半边）——engine 标记非空 + ticket 面带
  gate_id/instance_id/period/report_path（详情下钻数据源在真台可读）。

依据三支：①工单验收「签字链路真签一张沙箱巡检票收口」+④「不许旁路」；②KI 家族——
KI-003/008（查询显式降级，poll 面遵守）、ki051 教训（--decl-path/--repo-root 夹具注入，
真树零写入）；③契约=validate_close_signature（gate 不匹配拒收/agent 自签拒收）+
inspection_trigger.py sign 同义通道承诺。

镜 t260905-03/sc_inspection_period_journey + lib_inspection（取舍见方案 §3.5 镜C）：
带夹具声明通道/人门真拦两拍口径/exclusive 隔离与私有队列；不带入其双实例去重断言与
发现落面全链（t260905-03 已守，intent 不重复）——本票只守「签字通道把票签收口」。
与场景①（离线行面）分工：彼守板面收录与降级，本条守真台签字链路终态。

环境语义：temporalio/共享测试台（17233）缺席=ENV_FAIL exit 2 点名，不假红不假绿；
实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。登记 exclusive：往共享
台写真票，防与兄弟场景互染判定面。

跑法：python3 -B integration/t260915-08/sc_inspection_sign_journey.py
"""
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "t260905-03"))
import lib_inspection as lib  # noqa: E402

# 实例 id 带进程戳：共享台上与 decl-gate/journey 的 integration-tests 同实例同日会撞
# 去重回执（每期一票按 实例+期号 去重）——唯一实例 id 让本旅程每次拿到自己的新票。
_STAMP = os.getpid() % 100000
INSTANCE = "integration-tests-%05d" % _STAMP
DECL = """schema: v1
instances:
  - id: %s
    enabled: true
    project_key: sandbar
    schedule:
      kind: cron
      cron: 30 7 * * *
    workflow: InspectionPeriodicWorkflow
    template: inspection-lite
""" % INSTANCE

SIGN_WHO = "human-scenario"        # 非 agent 角色名（agent 不得自签）
POLL_OPEN = 90                     # 等开票+票面就绪
POLL_GATE = 20                     # 未签不终态观察窗（假门在此现形）
POLL_ERR = 20                      # 错 gate 拒收后 gate_error 显形窗
POLL_CLOSE = 180                   # 对 gate 签后等收口
TERMINAL = "closed"


def ticket_state(tid):
    """查询回执 (result, snapshot)：离台/失败返 (None, None)——轮询面诚实降级。
    面=client.py `ticket op=query`（CLI 快照面：ticket_id/run_id/status/snapshot/pulse）。"""
    _proc, parsed = lib.run_client("ticket", {"op": "query", "ticket_id": tid})
    if not (isinstance(parsed, dict) and parsed.get("ok") is True):
        return None, None
    r = parsed.get("result") or {}
    return r, (r.get("snapshot") if isinstance(r.get("snapshot"), dict) else None)


def ticket_query_v2(tid):
    """查询回执（引擎 `ticket-query` 子命令）：engine/ticket 面所在——ticket.py
    `_v2_query` 消费的就是它（坑A 修复面）。失败返 None。"""
    _proc, parsed = lib.run_client("ticket-query", {"ticket_id": tid})
    if not (isinstance(parsed, dict) and parsed.get("ok") is True):
        return None
    res = parsed.get("result")
    return res if isinstance(res, dict) else None


def poll(fn, timeout, interval):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = fn()
        if last:
            return True, last
        time.sleep(interval)
    return False, last


def sign_via_client_channel(tid, who, gate, decision="approve", note=""):
    """工作台同款签字通道：node.ts op=sign 调的即本命令（client.py ticket op=sign →
    Temporal sign 信号）——不经过 inspection_trigger.py sign（那是对拍锚，非被测通道）。"""
    _proc, parsed = lib.run_client("ticket", {
        "op": "sign", "ticket_id": tid,
        "input": {"who": who, "gate": gate, "decision": decision, "note": note},
    })
    return parsed


def main() -> int:
    lib.require_entry(lib.CLIENT, "client 工单面（签字通道）")
    lib.require_entry(lib.TRIGGER, "巡检触发入口")
    # 主进程零 temporalio 依赖（client/trigger 子进程自选 venv python）；探活失败统一归因
    _proc, parsed = lib.run_client("schedule-list", {})
    if not (isinstance(parsed, dict) and parsed.get("ok") is True):
        lib.die_env("放行不可验：temporalio 缺席或共享测试台不可达（schedule-list 未 ok：%r）"
                    "——签字链路需要真台真票，不假红不假绿" % (str(parsed)[:160]))

    failures = []
    private_queue = "suyou-insp-sign-%05d" % _STAMP
    os.environ["SANDBAR_TASK_QUEUE"] = private_queue   # trigger/sign/worker 同队列（竞态消除）
    workdir = tempfile.mkdtemp(prefix="sandbar-t26091508-sign-")
    decl = os.path.join(workdir, "decl.yaml")
    with open(decl, "w", encoding="utf-8") as f:
        f.write(DECL)
    clean = lib.clean_tree("sign-journey")   # 零发现根：票面 findings=[] heartbeat=true
    tid = None
    try:
        with lib.StageWorker(private_queue):
            # 开票（--decl-path/--repo-root 注入夹具：真树零写入红线不破）
            proc, trig = lib.run_trigger(
                ["trigger", "--instance", INSTANCE, "--decl-path", decl,
                 "--repo-root", clean.root])
            if not (isinstance(trig, dict) and trig.get("ok") is True):
                failures.append("触发未放行：%r | stderr=%s"
                                % (trig, (proc.stderr or "")[:200]))
            else:
                tid = str((trig.get("result") or {}).get("ticket_id") or "")
                if not tid:
                    failures.append("放行回执未带 ticket_id：%r" % (trig.get("result"),))
            if tid:
                lib.note_started_ticket(tid)

                # ① 常态子用例：票到 close/awaiting-human 且 face 无 human_gate 键（签字前常态）
                def at_gate():
                    _r, snap = ticket_state(tid)
                    if not snap:
                        return None
                    if snap.get("stage") == "close" and snap.get("stage_state") == "awaiting-human" \
                            and isinstance(snap.get("face"), dict):
                        return snap
                    return None
                ok_gate, snap = poll(at_gate, POLL_OPEN, 2)
                if not ok_gate:
                    _r, s = ticket_state(tid)
                    failures.append("票 %s 在 %ds 内未到 close/awaiting-human（stage=%r state=%r）"
                                    "——人门段断链" % (tid, POLL_OPEN,
                                                      s and s.get("stage"), s and s.get("stage_state")))
                else:
                    face = snap.get("face") or {}
                    if "human_gate" in face:
                        failures.append("签字前 face 已带 human_gate 键（常态缺席契约破，"
                                        "待签判定若依赖它=黄行必瞎）：%r" % (face.get("human_gate"),))

                    # 附带：签字前 ticket-query 读回（坑A 活体半边 + 详情数据源）——
                    # 面=引擎 ticket-query 子命令（ticket.py _v2_query 消费的面），
                    # ticket op=query 是旧 CLI 快照面、无 engine/ticket 键，不作此断言
                    q = ticket_query_v2(tid)
                    if not q or not q.get("engine"):
                        failures.append("ticket-query 回执 engine 空（坑A 复发：巡检票被谎报"
                                        "「工单不存在」的前置数据面）：%r" % (q and sorted(q)))
                    else:
                        tk = q.get("ticket") or {}
                        miss = [k for k in ("gate_id", "instance_id", "period", "report_path", "title")
                                if not tk.get(k)]
                        if miss:
                            failures.append("ticket 面（详情下钻数据源）缺键 %r：有 %r" % (miss, sorted(tk)))

                    # 假门第①拍：未签不终态
                    def is_terminal():
                        _r, s2 = ticket_state(tid)
                        return bool(s2 and s2.get("status") == TERMINAL)
                    became, _ = poll(is_terminal, POLL_GATE, 2)
                    if became:
                        failures.append("人门假门：未签字票 %ds 内已终态（收口必须被人门真拦）" % POLL_GATE)

                    # ② 拒收子用例·错 gate
                    parsed_bad = sign_via_client_channel(tid, SIGN_WHO, "not-the-inspection-gate")
                    if not (isinstance(parsed_bad, dict) and parsed_bad.get("ok") is True):
                        failures.append("错 gate 签字在通道层即失败（通道应投递、workflow 拒收）：%r"
                                        % (parsed_bad,))
                    else:
                        def gate_err_visible():
                            _r, s3 = ticket_state(tid)
                            if not s3:
                                return None
                            err = str(s3.get("gate_error") or "")
                            return err if ("gate" in err) else None
                        ok_err, err = poll(gate_err_visible, POLL_ERR, 2)
                        if not ok_err:
                            failures.append("错 gate 签字后 %ds 内 gate_error 未显形（拒收面不可读，"
                                            "宿主看不见为什么没签上）" % POLL_ERR)
                        else:
                            _r, s4 = ticket_state(tid)
                            if s4 and s4.get("stage_state") != "awaiting-human":
                                failures.append("错 gate 被拒后票竟离门（state=%r）——拒收必须留在门内"
                                                % (s4.get("stage_state"),))

                        # ③ 拒收子用例·agent 自签（对的 gate、agent 身份）
                        parsed_agent = sign_via_client_channel(tid, "developer", "inspection-close")
                        if not (isinstance(parsed_agent, dict) and parsed_agent.get("ok") is True):
                            failures.append("agent 自签在通道层即失败（应投递、workflow 拒收）：%r"
                                            % (parsed_agent,))
                        else:
                            def agent_refused():
                                _r, s5 = ticket_state(tid)
                                if not s5:
                                    return None
                                err = str(s5.get("gate_error") or "")
                                return err if ("agent" in err or "自签" in err) else None
                            ok_ref, err2 = poll(agent_refused, POLL_ERR, 2)
                            if not ok_ref:
                                failures.append("agent 自签未被点名拒收（gate_error=%r）——自签禁令失守"
                                                % err2)

                    # ④ 收口子用例：对 gate 真签（gate 取自 ticket-query 面契约单点 gate_id）
                    q = ticket_query_v2(tid)
                    gate_id = ((q or {}).get("ticket") or {}).get("gate_id") or "inspection-close"
                    parsed_ok = sign_via_client_channel(tid, SIGN_WHO, gate_id,
                                                        note="t260915-08 场景③ 真签收口")
                    if not (isinstance(parsed_ok, dict) and parsed_ok.get("ok") is True):
                        failures.append("对 gate 签字被拒：%r" % (parsed_ok,))
                    else:
                        def closed():
                            _r, s6 = ticket_state(tid)
                            return bool(s6 and s6.get("status") == TERMINAL)
                        okc, _ = poll(closed, POLL_CLOSE, 3)
                        if not okc:
                            _r, s7 = ticket_state(tid)
                            failures.append("对 gate 签字后 %ds 未收口（status=%r）——签字链路断链"
                                            % (POLL_CLOSE, s7 and s7.get("status")))
                        else:
                            ledger = lib.inspection_ledger(tid)
                            if not isinstance(ledger, dict):
                                failures.append("收口后落账缺席（out/inspection/<票号>.json）——审计链断")
                            elif not isinstance(ledger.get("findings"), list):
                                failures.append("收口后落账缺 findings 清单：%r" % (sorted(ledger)[:8],))
                            else:
                                # 落账文档顶格=face（human_gate 直挂顶层，lib 头注契约）
                                hg = ledger.get("human_gate")
                                if not (isinstance(hg, dict) and hg.get("who") == SIGN_WHO):
                                    failures.append("收口票面 human_gate 回执缺席或 who 不符（%r）"
                                                    % (hg,))

                # ⑤ 板面收录子用例（规格① 真台端到端）：声明经 SANDBAR_INSPECTION_DECL 注入
                # client 子进程（_inspection_enabled_instances 读的是它）→
                # ticket-list{kind:"inspection"} 必须收录本收口票（窗内闭合=完整巡检形，
                # R8），行带 kind/engine/status=closed/instance_id/period/human_gate 回执，
                # 回执 inspection_filter 白名单含本实例——3099 板面黄行/收口折叠的数据源。
                os.environ["SANDBAR_INSPECTION_DECL"] = decl

                def on_board():
                    _p2, parsed2 = lib.run_client("ticket-list", {"kind": "inspection"})
                    if not (isinstance(parsed2, dict) and parsed2.get("ok") is True):
                        return None
                    for row2 in ((parsed2.get("result") or {}).get("tickets") or []):
                        if isinstance(row2, dict) and row2.get("id") == tid:
                            return (row2, (parsed2.get("result") or {}).get("inspection_filter") or {})
                    return None
                ok_board, hit = poll(on_board, 60, 3)
                if not ok_board:
                    failures.append("收口票 %s 未上巡检板面（ticket-list kind=inspection "
                                    "60s 内无行）——规格① 真台断链" % tid)
                else:
                    row, flt = hit
                    if row.get("status") != "closed" or row.get("kind") != "inspection" \
                            or row.get("engine") != "inspection":
                        failures.append("板面收口行形状不符（status=%r kind=%r engine=%r）"
                                        % (row.get("status"), row.get("kind"), row.get("engine")))
                    for k in ("instance_id", "period", "title"):
                        if not row.get(k):
                            failures.append("板面收口行缺 %s 键（行=%r）" % (k, sorted(row)))
                    hg2 = row.get("human_gate") or {}
                    if not (isinstance(hg2, dict) and hg2.get("who") == SIGN_WHO):
                        failures.append("板面收口行缺签字回执 human_gate.who=%r（窗内闭合行应带 "
                                        "result() 终态快照的回执）" % (hg2,))
                    if INSTANCE not in (flt.get("enabled_instances") or ()) or flt.get("degraded"):
                        failures.append("回执 inspection_filter 异常（白名单缺本实例或降级旗立）：%r"
                                        % (flt,))
    finally:
        clean.cleanup()
        shutil.rmtree(workdir, ignore_errors=True)
        try:
            lib.cleanup_tickets()
        except Exception:  # noqa: BLE001——清理失败不掩盖判定面（票在隔离台，随 retention 收敛）
            pass

    if failures:
        for m in failures:
            print("FAIL_REASON: " + m, flush=True)
        return 1
    print("PASS: 签字链路真签收口——常态无 human_gate 键；错 gate 拒收可读且留门内；"
          "agent 自签拒收；对 gate 真签 closed+human_gate 落面+落账在；ticket-query "
          "engine/gate_id 详情面在位；收口票上巡检板面（完整巡检形+白名单回执）", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
