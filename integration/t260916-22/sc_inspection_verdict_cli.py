#!/usr/bin/env python3
"""t260916-22 场景③：发现级裁定（verdict）落账与假报跨期压制（验收④主证据，灰盒 L3，真台真票）。

用户场景：宿主对 agent 巡检发现逐条裁定「假报/待修/存疑」——签字时或签后经运维通道
（inspection_trigger.py verdict 子命令，工单要点⑥明文签名）逐条标、落台账；**假报跨期
不再重复计数**（裁定④⑤：下期同内容发现被压制点名，不进 summary、不占预算、不破心跳）。

子用例面：
- who 闸（错 gate/agent 自签同族语义，镜 sign）：空 who/agent 角色名/超长 who → 拒收
  且点名失败的检查项；词表外 verdict → 拒收点名；
- 在途 signal 子用例：票 awaiting-human 时 verdict → 信号落 face+timeline（回执带 ticket_id），
  签字收口后落账 face 带裁定；
- 收口直改子用例：已收口票 verdict → 台账直改 + verdicts 文件 append（entries 全留痕，
  同 finding 重复裁定 face 取最新）；
- 跨期压制子用例：P1 裁假报 → P2 同内容发现（同机械 id）被压制点名、summary 零计、
  heartbeat 不破——「假报跨期不再重复计数」的行为证据；
- deadman 词法子用例：-verdicts.json 不进漏跑/畸形清单（--offline 纯查声明+台账）。

依据：工单要点⑥+宿主裁定⑤；KI-030 家族反面教训（静默降级不可有——本条守显式点名）。
环境语义：docker 测试台缺席=ENV_FAIL exit 2；实现未落地=FAIL（TDD 信号），
arbitrate/merge 期必须绿。登记 exclusive（真台真票）。

跑法：python3 -B integration/t260916-22/sc_inspection_verdict_cli.py
"""
import json
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib_inspect as lib  # noqa: E402
from lib_inspection import die_env  # noqa: E402

_STAMP = os.getpid() % 100000
SIGN_WHO = "human-scenario"
P1, P2 = "20260907", "20260914"   # 近两个周一（cron 0 6 * * 1 的期望期），deadman 窗内
POLL_OPEN = 120
POLL_CLOSE = 240


def decl_text(instance):
    return """schema: v1
instances:
  - id: %s
    enabled: true
    project_key: sandbar
    schedule:
      kind: cron
      cron: 0 6 * * 1
    workflow: InspectionPeriodicWorkflow
    template: inspection-lite
""" % instance


def ledger_of(period):
    """读引擎单源名台账（inspection-<实例>-<期>.json，=write_inspection_report 落名）；
    SANDBAR_INSPECTION_DIR=场景 tmp 台账目录。缺文件/坏 JSON → None（由断言点名）。"""
    base = os.environ.get("SANDBAR_INSPECTION_DIR") or ""
    path = os.path.join(base, lib.ledger_name(INST, period))
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def ticket_query(tid):
    _proc, parsed = lib.run_client("ticket", {"op": "query", "ticket_id": tid})
    if isinstance(parsed, dict) and parsed.get("ok") is True:
        return (parsed.get("result") or {})
    return None


def poll(fn, timeout, interval):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = fn()
        if last:
            return True, last
        time.sleep(interval)
    return False, last


def run_verdict(*args):
    """verdict 子命令驱动；返回 (proc, parsed)。"""
    return lib.run_trigger(["verdict", "--instance", INST, "--decl-path", DECL] + list(args))


def verdict_rejected(label, *args):
    proc, parsed = run_verdict(*args)
    ok_shape = isinstance(parsed, dict) and parsed.get("ok") is False
    rc_red = proc.returncode not in (0,)
    if not (ok_shape or rc_red):
        return "%s 应拒收（实得 ok=%r rc=%s）" % (label, (parsed or {}).get("ok"), proc.returncode)
    blob = (parsed and json.dumps(parsed, ensure_ascii=False)) or (proc.stderr or "")
    if not any(t in blob for t in ("who", "裁定", "verdict", "词表", "角色")):
        return "%s 拒收未点名原因（%r）" % (label, blob[:120])
    return None


def main() -> int:
    global INST, DECL
    lib.require_entry(lib.TRIGGER, "巡检触发入口")
    lib.require_entry(lib.CLIENT, "client 工单面")
    _proc, parsed = lib.run_client("schedule-list", {})
    if not (isinstance(parsed, dict) and parsed.get("ok") is True):
        die_env("共享测试台不可达（schedule-list 未 ok：%r）——裁定旅程需要真台真票" % (str(parsed)[:160]))

    failures = []
    INST = "verdict-cli-%05d" % _STAMP
    workdir = tempfile.mkdtemp(prefix="sandbar-verdict-work-")
    ledger_dir = tempfile.mkdtemp(prefix="sandbar-verdict-ledger-")
    os.environ["SANDBAR_INSPECTION_DIR"] = ledger_dir
    DECL = os.path.join(workdir, "v.yaml")
    with open(DECL, "w", encoding="utf-8") as f:
        f.write(decl_text(INST))
    stub = os.path.join(workdir, "stub-message.txt")

    tree = lib.evidence_tree("verdict-cli")
    anchor = tree.line_text(lib.GUARD_REL, 3)
    # 260928 修：叙述字段（subject）原为中文 ⇒ 报告面语言闸（463a8f7）把它判 unverified 并**追加一条
    # 聚合发现**（`N agent finding(s) are not written in English`，severity=high）⇒ P2 的 summary 被这条
    # 聚合条计入（high=1）、新发现≠0 于是 heartbeat=false——两红同源，且与本场景被测面（裁定/压制
    # 语义）无关。按 lib.finding 既有口径改英文（quote/path 数据面不译）。
    the_finding = lib.finding("Verdict anchor finding: guard anchor drift", lib.GUARD_REL, 3, anchor,
                              severity="med", confidence=0.9)
    with open(stub, "w", encoding="utf-8") as f:
        f.write(lib.fenced_message([the_finding]))

    def trigger_period(period):
        proc, parsed = lib.run_trigger(
            ["trigger", "--instance", INST, "--period", period,
             "--decl-path", DECL, "--repo-root", tree.root])
        if not (isinstance(parsed, dict) and parsed.get("ok") is True):
            failures.append("P%s 触发未放行：%r | stderr=%s"
                            % (period, parsed, (proc.stderr or "")[:200]))
            return None
        tid = str((parsed.get("result") or {}).get("ticket_id") or "")
        if not tid:
            failures.append("P%s 回执未带 ticket_id：%r" % (period, parsed.get("result")))
        return tid

    def face_findings(tid):
        r = ticket_query(tid)
        if not (r and isinstance(r.get("snapshot"), dict)):
            return None
        f = (r.get("snapshot") or {}).get("face")
        if isinstance(f, dict) and isinstance(f.get("findings"), list) and f.get("findings"):
            return f
        return None

    vpath = None
    queue = "sandbar-verdict-%05d" % _STAMP
    os.environ["SANDBAR_TASK_QUEUE"] = queue   # lib 子进程（trigger/verdict）经 os.environ 继承（t260905-03 journey 同款）
    try:
        with lib.StageWorker(queue, extra_env={
                "SANDBAR_INSPECT_STUB": "1",
                "SANDBAR_INSPECT_STUB_FILE": stub}):
            # ── P1：起票→发现落面→在途裁定（signal 子用例）→人门→收口→落账带裁定
            tid1 = trigger_period(P1)
            if not tid1:
                _finish(failures, tree, workdir, ledger_dir)
                return 1
            got, r = poll(lambda: face_findings(tid1), POLL_OPEN, 3)
            if not got:
                failures.append("P1 票 %ds 发现未落（status=%r）" % (POLL_OPEN, (r or {}).get("status")))
                _finish(failures, tree, workdir, ledger_dir)
                return 1
            face = face_findings(tid1) or {}
            first = (face.get("findings") or [{}])[0]
            fid = str(first.get("id") or "") if isinstance(first, dict) else ""
            if not fid:
                failures.append("P1 发现缺机械 id（face=%r）" % str(face)[:160])
                _finish(failures, tree, workdir, ledger_dir)
                return 1

            # who 闸/词表闸（fail-closed 拒收子用例，在途票上即可验）
            for label, args in (
                ("空 who", ["--period", P1, "--finding-id", fid, "--verdict", "假报", "--who", ""]),
                ("agent 角色名 who", ["--period", P1, "--finding-id", fid, "--verdict", "假报",
                                      "--who", "developer"]),
                ("超长 who", ["--period", P1, "--finding-id", fid, "--verdict", "假报",
                              "--who", "x" * 80]),
                ("词表外 verdict", ["--period", P1, "--finding-id", fid, "--verdict", "说不清",
                                    "--who", SIGN_WHO]),
                ("查无此 finding", ["--period", P1, "--finding-id", "ffffffff",
                                    "--verdict", "假报", "--who", SIGN_WHO]),
            ):
                err = verdict_rejected(label, *args)
                if err:
                    failures.append(err)

            # 在途 signal 子用例：中文别名「假报」→ signal 落 face，回执带 ticket_id
            proc, parsed = run_verdict("--period", P1, "--finding-id", fid,
                                       "--verdict", "假报", "--who", SIGN_WHO,
                                       "--note", "复核为误报（在途 signal 子用例）")
            res = (parsed or {}).get("result") or {}
            if not (isinstance(parsed, dict) and parsed.get("ok") is True):
                failures.append("在途裁定被拒：%r | stderr=%s" % (parsed, (proc.stderr or "")[:200]))
            elif str(res.get("ticket_id") or "") != tid1:
                failures.append("在途裁定回执未带 ticket_id（%r）——signal 通道面破" % (res,))
            got, r = poll(lambda: (lambda f: f and lib.finding_state(
                (f.get("findings") or [{}])[0]) in ("false-positive", "suppressed", "doubt", "to-fix")
                and f)(face_findings(tid1)), 60, 3)
            if not got:
                failures.append("signal 裁定未落 face（%r）——finding_verdict 信号面破"
                                % str((face_findings(tid1) or {}))[:200])

            # 人门两拍+收口
            def is_terminal():
                rr = ticket_query(tid1)
                return bool(rr and rr.get("status") == "COMPLETED")
            proc, parsed = lib.run_trigger(["sign", "--instance", INST, "--period", P1,
                                            "--who", SIGN_WHO, "--decision", "approve",
                                            "--decl-path", DECL])
            if not (isinstance(parsed, dict) and parsed.get("ok") is True):
                failures.append("P1 签字被拒：%r" % (parsed,))
            else:
                got, _ = poll(is_terminal, POLL_CLOSE, 3)
                if not got:
                    failures.append("P1 签字后未收口（status=%r）" % (ticket_query(tid1) or {}).get("status"))
            ledger = ledger_of(P1)
            if not isinstance(ledger, dict):
                failures.append("P1 落账缺席")
            else:
                lf = (ledger.get("findings") or [{}])[0]
                if str(lf.get("verdict") or "") not in ("false-positive", "假报"):
                    failures.append("P1 落账 face 未带裁定（verdict=%r）——裁定落账面破" % lf.get("verdict"))

            # 收口直改子用例：再裁「存疑」→ verdicts append（entries=2）+ 台账 face 取最新
            proc, parsed = run_verdict("--period", P1, "--finding-id", fid,
                                       "--verdict", "存疑", "--who", SIGN_WHO,
                                       "--note", "复核改口（收口直改子用例）")
            if not (isinstance(parsed, dict) and parsed.get("ok") is True):
                failures.append("收口裁定被拒：%r | stderr=%s" % (parsed, (proc.stderr or "")[:200]))
            vpath = os.path.join(ledger_dir, lib.ledger_name(INST, P1, lib.VERDICTS_SUFFIX))
            try:
                with open(vpath, "r", encoding="utf-8") as f:
                    vdata = json.load(f)
                entries = vdata.get("entries") or []
                if len(entries) < 2:
                    failures.append("verdicts entries 未全留痕（%d 条）" % len(entries))
                if entries and str((entries[-1] or {}).get("verdict") or "") not in ("doubt", "存疑"):
                    failures.append("verdicts 最新条非存疑（%r）——取最新面破" % entries[-1])
            except (OSError, ValueError) as e:
                failures.append("verdicts 文件缺席/坏（%s：%s）——裁定台账面破" % (vpath, e))
            ledger = lib.inspection_ledger(tid1)
            if isinstance(ledger, dict):
                lf = (ledger.get("findings") or [{}])[0]
                if str(lf.get("verdict") or "") not in ("doubt", "存疑"):
                    failures.append("收口直改后台账 face 未取最新裁定（%r）" % lf.get("verdict"))

            # ── P2：同内容发现（同机械 id）→ 假报/存疑裁定跨期压制
            tid2 = trigger_period(P2)
            if tid2:
                got, r = poll(lambda: face_findings(tid2), POLL_OPEN, 3)
                if not got:
                    failures.append("P2 票 %ds 发现未落（status=%r）" % (POLL_OPEN, (r or {}).get("status")))
                else:
                    face2 = face_findings(tid2) or {}
                    fs2 = face2.get("findings") or []
                    same = [f for f in fs2 if isinstance(f, dict) and str(f.get("id") or "") == fid]
                    if not same:
                        failures.append("P2 未按内容哈希对上 P1 id（%r vs %s）——跨期去重键破"
                                        % ([f.get("id") for f in fs2 if isinstance(f, dict)], fid))
                    else:
                        st = lib.finding_state(same[0])
                        if st not in ("suppressed", "false-positive"):
                            failures.append("P2 假报未压制（state=%r）——「假报跨期不再重复计数」破" % st)
                    summary = face2.get("summary")
                    if isinstance(summary, dict) and any(summary.get(k) for k in ("high", "med", "low", "total")):
                        # 260928：失败面补证据——列出 P2 每条发现的 (id, state, severity)，
                        # 否则「summary 计入了谁」看不出来（本红一度被环境聚合条污染）。
                        _diag = [((f.get("id") or "")[:14], lib.finding_state(f), f.get("severity"),
                                  str(f.get("subject") or "")[:26]) for f in fs2]
                        failures.append("P2 summary 计入了被压制发现（%r）——不重复计数破；P2 发现=%s（对上 P1 的=%s）"
                                        % (summary, _diag, [f.get("id") for f in same]))
                    if face2.get("heartbeat") is not True:
                        failures.append("P2 全压制票 heartbeat 非 true（%r）——压制可见不破心跳口径破"
                                        % face2.get("heartbeat"))
                    ledger2 = None
                    def closed2():
                        nonlocal ledger2
                        rr = ticket_query(tid2)
                        if rr and rr.get("status") == "COMPLETED":
                            ledger2 = lib.inspection_ledger(tid2)
                            return rr
                        return None
                    proc, parsed = lib.run_trigger(["sign", "--instance", INST, "--period", P2,
                                                    "--who", SIGN_WHO, "--decision", "approve",
                                                    "--decl-path", DECL])
                    if isinstance(parsed, dict) and parsed.get("ok") is True:
                        poll(closed2, POLL_CLOSE, 3)
                        if isinstance(ledger2, dict) and ledger2.get("heartbeat") is True \
                                and (ledger2.get("findings") in ([], None)):
                            pass  # 收口落账的心跳面与 journey 零发现子用例同口径（此处压制票不另断）
            # ── deadman 词法子用例：-verdicts.json 不进漏跑/畸形清单
            proc, parsed = lib.run_trigger(
                ["deadman", "--instance", INST, "--ledger-dir", ledger_dir, "--offline",
                 "--decl-path", DECL, "--lookback-days", "14", "--grace-days", "2"])
            blob = json.dumps(parsed, ensure_ascii=False) if isinstance(parsed, dict) else (proc.stderr or "")
            if "verdicts" in blob:
                failures.append("deadman 词法把 -verdicts.json 当台账/畸形（%r）——非台账件排除面破"
                                % blob[:200])
    finally:
        tree.cleanup()
        shutil.rmtree(workdir, ignore_errors=True)
        shutil.rmtree(ledger_dir, ignore_errors=True)

    _finish(failures, None, None, None)


def _finish(failures, tree, workdir, ledger_dir):
    if tree is not None:
        tree.cleanup()
    if workdir is not None:
        shutil.rmtree(workdir, ignore_errors=True)
    if ledger_dir is not None:
        shutil.rmtree(ledger_dir, ignore_errors=True)
    if failures:
        for m in failures:
            print("FAIL_REASON: " + m, flush=True)
        sys.exit(1)
    print("PASS: 发现级裁定——who 闸/词表闸 fail-closed 拒收点名；在途 signal 落 face（回执带"
          " ticket_id）；收口直改台账+verdicts append 全留痕取最新；P1 假报 → P2 同 id 发现压制"
          "点名不计数不破心跳；deadman 词法不吞 -verdicts.json", flush=True)
    sys.exit(0)


if __name__ == "__main__":
    sys.exit(main())
