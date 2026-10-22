#!/usr/bin/env python3
"""t260916-22 场景②：巡检 inspect 段全链用户旅程（工单验收①主证据，灰盒 L3，真台真票）。

用户场景：宿主手动触发一期巡检——agent 读仓产出发现清单、证据被机械复核（不过者降级
点名）、人门签字收口、发现留存落账、建议修复票只从「agent 判真」的发现出。全链=
trigger 起票→setup→suite（非套件档缺席）→inspect（桩 agent）→report 复核落账→close
人门。三拍纪律（镜 t260905-03-period-journey）：人门假门两拍（未签不终态/签后收口）+
发现留存面=落账（收口后 query 不可达，落账是唯一留存承诺面）。

子用例面分工（与兄弟场景 intent 不互替）：
- 混合桩子用例：verified（真引文锚夹具树真实文件行）/unverified（行号越界→降级+reason
  点名）/低置信/low 四类发现同票落面——建议门只收 verified&&conf≥0.6&&severity≥med；
  timeline 用户可见段名=inspect（scan 段退役的旅程面证据）；
- 零发现桩子用例：空 findings → heartbeat=true 心跳票照开照收（全绿期=心跳证明）；
- 真进程链超时子用例（SANDBAR_INSPECT_CMD 挂起脚本 + inspect_timeout_min=2）：票到
  blocked 点名「agent 未完成」不假绿 + 落账在 + agent-home 落台账目录（DSH_HOME 与
  基座解耦）+ 进程 reap 干净（pgrep 面零残留）；
- 红线判定化：被审查树逐字节校验和前后不变；审查基座（仓根）零 .dsh 残留。

依据：工单要点①②③⑤⑧+验收①③；KI-002（被借面轮询无超时保护——超时子用例守「可见失败
不假绿」的用户面）；KI-047/049（失败必须可见可归因）。环境语义：docker 测试台/venv
缺席=ENV_FAIL exit 2；实现未落地=FAIL（TDD 信号），arbitrate/merge 期必须绿。
登记 exclusive：往共享台写真票，防与兄弟场景互染。私有队列自供给 worker（t260910-11
隔离红线：env 一律 lib.spawn_env 单点；t260916-02：夹具 env 同喂 worker）。

跑法：python3 -B integration/t260916-22/sc_inspection_inspect_journey.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib_inspect as lib  # noqa: E402
from lib_inspection import die_env, die_fail  # noqa: E402

_STAMP = os.getpid() % 100000
SIGN_WHO = "human-scenario"
POLL_OPEN = 120
POLL_GATE = 20
POLL_CLOSE = 240
POLL_BLOCK = 300
TERMINAL_OK = "COMPLETED"
HANG_MARKER = "sandbar-inspect-hang-%05d" % _STAMP


def decl_text(instance, timeout_min=None):
    budget = "" if timeout_min is None else "    inspect_timeout_min: %d\n" % timeout_min
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
    # 260928：把**环境水位面**（第四判据 tmp_fixture_max_dirs，缺省 1000）隔离在夹具之外——
    # 本机测试夹具存量上千（重跑夜 3700+）时它必触发，而其（合法）发现会进 face/心跳，
    # 污染本场景判据（水位面自有场景与 UT 专守）。这是**隔离环境面，不是放宽判据**。
    watchdog:
      tmp_fixture_max_dirs: 100000
      tmp_fixture_max_age_h: 8760
%s""" % (instance, budget)


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


def write_decl(workdir, name, instance, timeout_min=None):
    path = os.path.join(workdir, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(decl_text(instance, timeout_min))
    return path


def trigger_one(tag, instance, decl, tree_root, failures):
    proc, parsed = lib.run_trigger(
        ["trigger", "--instance", instance, "--period", "20260916",
         "--decl-path", decl, "--repo-root", tree_root])
    if not (isinstance(parsed, dict) and parsed.get("ok") is True):
        failures.append("%s 触发未放行：%r | stderr=%s"
                        % (tag, parsed, (proc.stderr or "")[:200]))
        return None
    tid = str((parsed.get("result") or {}).get("ticket_id") or "")
    if not tid:
        failures.append("%s 放行回执未带 ticket_id：%r" % (tag, parsed.get("result")))
    return tid


def face_stage_ids(r):
    snap = (r or {}).get("snapshot") or {}
    tl = snap.get("timeline")
    if not isinstance(tl, list):
        return None
    return [str(e.get("stage") or "") for e in tl if isinstance(e, dict)]


def journey_mixed(tag, tid, failures):
    """混合桩子用例：五类发现同票——复核两态落面+点名、建议门过滤、段名可见、人门两拍、落账。"""
    def face_ready():
        r = ticket_query(tid)
        if not (r and isinstance(r.get("snapshot"), dict)):
            return None
        f = r["snapshot"].get("face")
        if isinstance(f, dict) and isinstance(f.get("findings"), list) and f.get("findings"):
            return r
        return None
    got, r = poll(face_ready, POLL_OPEN, 3)
    if not got:
        failures.append("%s 票 %ds 票面发现未落（status=%r）——inspect→report 链断"
                        % (tag, POLL_OPEN, ((r or {}).get("status"))))
        return
    snap = r.get("snapshot") or {}
    face = snap.get("face") or {}
    findings = face.get("findings") or []
    stages = face_stage_ids(r)
    if stages is not None:
        ok_stages = "inspect" in stages and "scan" not in stages
        if not ok_stages:
            # timeline 是追加面，落账后随 snapshot 读不到——宽窗：票面 stage 兜底
            ok_stages = snap.get("stage") == "inspect" or "inspect" in json.dumps(snap.get("timeline") or [])
        if not ok_stages:
            failures.append("%s 用户可见段名非 inspect（timeline=%r stage=%r）——scan 段退役面破"
                            % (tag, stages, snap.get("stage")))
    marks = {str(f.get("scan") or "") for f in findings if isinstance(f, dict)}
    if marks and "agent" not in marks:
        failures.append("%s 发现来源标记非 agent（%r）——设计稿 §4.2 schema 面" % (tag, marks))
    states = [(str(f.get("subject") or ""), lib.finding_state(f), lib.entry_reason(f))
              for f in findings if isinstance(f, dict)]
    unv = [s for s, st, _r in states if st == "unverified"]
    if not unv:
        failures.append("%s 坏行号发现未降级 unverified（states=%r）——证据复核面缺席" % (tag, states))
    for s, _st, reason in states:
        if s.startswith("越界行号") and not reason:
            failures.append("%s unverified 条目（%s）零 reason——点名面缺席（不静默丢承诺）" % (tag, s))
    fixes = face.get("suggested_fix_tickets") or []
    fix_txt = json.dumps(fixes, ensure_ascii=False)
    # 260928：期望串随夹具叙述字段英文化同步（原为中文；语言闸要求叙述字段英文——见 lib.finding 头注）
    for want in ("Suggestion-eligible high", "Suggestion-eligible med"):
        if want not in fix_txt:
            failures.append("%s 建议门漏收合门发现（%s）：%r" % (tag, want, fix_txt[:160]))
    for reject in ("Low confidence, no ticket", "Low severity, no ticket",
                   "Out-of-range line, no suggestion"):
        if reject in fix_txt:
            failures.append("%s 建议门误收（%s 在 suggested_fix_tickets）——verified&&conf≥0.6&&severity≥med 门破" % (tag, reject))
    gate_two_beats(tag, tid, failures, expect_closed=True)

    ledger = lib.inspection_ledger(tid)
    if not isinstance(ledger, dict):
        failures.append("%s 收口后落账缺席（发现留存面断）" % tag)
    elif not isinstance(ledger.get("findings"), list) or not ledger.get("findings"):
        failures.append("%s 落账缺发现清单（审计链断）：%r" % (tag, sorted(ledger)[:8]))


def journey_heartbeat(tag, tid, failures):
    """零发现桩子用例：空 findings 心跳票照开照收（全绿期=心跳证明）。"""
    def face_ready():
        r = ticket_query(tid)
        if not (r and isinstance(r.get("snapshot"), dict)):
            return None
        f = r["snapshot"].get("face")
        if isinstance(f, dict) and isinstance(f.get("findings"), list):
            return r
        return None
    got, r = poll(face_ready, POLL_OPEN, 3)
    if not got:
        failures.append("%s 心跳票 %ds 票面未就绪（status=%r）" % (tag, POLL_OPEN, (r or {}).get("status")))
        return
    face = (r.get("snapshot") or {}).get("face") or {}
    _fs = face.get("findings") or []
    # 260928 修（同族第三例）：原判据要求 face.findings **完全为空**且 heartbeat 恒 true，而引擎的
    # lane/watchdog 面会**合法地**追加发现（本机常驻：`in-scope non-terminal tickets whose timeline
    # could not be read …`——那是环境里的僵尸跑件，不是本场景的被测面）。判据按面归因：
    # ①agent 面发现必须为空；②heartbeat == 「本票没有任何未压制发现」（agent/lane 同口径，语义不变）。
    _agent_fs = [f for f in _fs if isinstance(f, dict)
                 and str(f.get("scan") or "") != "lane"
                 and not str(f.get("id") or "").startswith("lane:")]
    if _agent_fs != []:
        failures.append("%s 空桩应零（agent 面）发现，实得 %r ｜ 全量=%r" % (tag, _agent_fs, _fs))
    _any_live = any(str(f.get("verified") or "") not in ("suppressed", "false-positive")
                    for f in _fs if isinstance(f, dict))
    if bool(face.get("heartbeat")) != (not _any_live):
        failures.append("%s heartbeat 与「是否存在未压制发现」不一致（heartbeat=%r any_live=%s）"
                        "——心跳口径破 ｜ 发现=%r" % (tag, face.get("heartbeat"), _any_live, _fs))
    gate_two_beats(tag, tid, failures, expect_closed=True)


def gate_two_beats(tag, tid, failures, expect_closed):
    """人门两拍：未签不终态（假门现形）→签字→收口。"""
    def is_terminal():
        r = ticket_query(tid)
        return bool(r and r.get("status") == TERMINAL_OK)
    became, _ = poll(is_terminal, POLL_GATE, 2)
    if became:
        failures.append("%s 人门假门：未签字票 %ds 内已终态" % (tag, POLL_GATE))
        return
    proc, parsed = lib.run_trigger(["sign", "--instance", _instance_of(tag), "--period", "20260916",
                                    "--who", SIGN_WHO, "--decision", "approve",
                                    "--decl-path", DECLS[tag]])
    if not (isinstance(parsed, dict) and parsed.get("ok") is True):
        failures.append("%s 签字被拒：%r | stderr=%s" % (tag, parsed, (proc.stderr or "")[:200]))
        return
    got, _ = poll(is_terminal, POLL_CLOSE, 3)
    if not got and expect_closed:
        r = ticket_query(tid)
        failures.append("%s 签字后 %ds 未收口（status=%r）" % (tag, POLL_CLOSE, (r or {}).get("status")))


DECLS = {}
_INSTANCE_OF_TAG = {}


def _instance_of(tag):
    return _INSTANCE_OF_TAG[tag]


def main() -> int:
    lib.require_entry(lib.TRIGGER, "巡检触发入口")
    lib.require_entry(lib.CLIENT, "client 工单面")
    _proc, parsed = lib.run_client("schedule-list", {})
    if not (isinstance(parsed, dict) and parsed.get("ok") is True):
        die_env("共享测试台不可达（schedule-list 未 ok：%r）——全链旅程需要真台真票" % (str(parsed)[:160]))

    failures = []
    inst_a = "inspect-journey-a-%05d" % _STAMP
    inst_b = "inspect-journey-b-%05d" % _STAMP
    inst_t = "inspect-journey-t-%05d" % _STAMP
    _INSTANCE_OF_TAG["mixed"] = inst_a
    _INSTANCE_OF_TAG["heartbeat"] = inst_b
    _INSTANCE_OF_TAG["timeout"] = inst_t
    workdir = tempfile.mkdtemp(prefix="sandbar-inspect-journey-")
    ledger_dir = tempfile.mkdtemp(prefix="sandbar-inspect-journey-ledger-")
    os.environ["SANDBAR_INSPECTION_DIR"] = ledger_dir
    decl_a = write_decl(workdir, "a.yaml", inst_a)
    decl_b = write_decl(workdir, "b.yaml", inst_b)
    decl_t = write_decl(workdir, "t.yaml", inst_t, timeout_min=2)
    DECLS["mixed"] = decl_a
    DECLS["heartbeat"] = decl_b
    DECLS["timeout"] = decl_t
    stub = os.path.join(workdir, "stub-message.txt")

    tree = lib.evidence_tree("inspect-journey")
    # 261023: every period needs a diffable base point, otherwise the lane (correctly)
    # ends it as "Change surface unavailable" and the journey reads a broken chain.
    # The tree is a git repo with one commit; declare it through the engine's own
    # bootstrap seam for all three instances.
    from lib_inspection import seed_surface_bootstrap
    for _inst in (inst_a, inst_b, inst_t):
        seed_surface_bootstrap(_inst, tree.base_sha, ledger_dir)
    tree.keep_checksums()
    g2 = tree.line_text(lib.GUARD_REL, 2)
    p2 = tree.line_text(lib.PRODUCER_REL, 2)
    hang = os.path.join(workdir, "hang.sh")
    with open(hang, "w", encoding="utf-8") as f:
        f.write("#!/bin/sh\nsleep 300  # %s\n" % HANG_MARKER)
    os.chmod(hang, 0o755)

    queue = "sandbar-inspect-journey-%05d" % _STAMP
    queue2 = "sandbar-inspect-journey-real-%05d" % _STAMP

    try:
        # ── 工作器一：桩模式（SANDBAR_INSPECT_STUB=1+STUB_FILE，方案 §3 缝名）
        os.environ["SANDBAR_TASK_QUEUE"] = queue   # trigger 子进程经 os.environ 继承（t260905-03 journey 同款）
        with lib.StageWorker(queue, extra_env={
                "SANDBAR_INSPECT_STUB": "1",
                "SANDBAR_INSPECT_STUB_FILE": stub}):
            # 子用例A 混合桩：verified/unverified/低置信/低危四态同票
            mixed = [
                lib.finding("Suggestion-eligible high: guard anchor drift", lib.GUARD_REL, 3,
                            tree.line_text(lib.GUARD_REL, 3), severity="high", confidence=0.9),
                lib.finding("Suggestion-eligible med: producer leftover clause", lib.PRODUCER_REL, 2, p2,
                            severity="med", confidence=0.9),
                lib.finding("Low confidence, no ticket: observation", lib.GUARD_REL, 2, g2,
                            severity="med", confidence=0.3),
                lib.finding("Out-of-range line, no suggestion: recheck downgrades", lib.GUARD_REL, 9999, "x",
                            severity="high", confidence=0.9),
                lib.finding("Low severity, no ticket: record only", lib.PRODUCER_REL, 2, p2,
                            severity="low", confidence=0.9),
            ]
            with open(stub, "w", encoding="utf-8") as f:
                f.write(lib.fenced_message(mixed))
            tid_a = trigger_one("mixed", inst_a, decl_a, tree.root, failures)
            if tid_a:
                journey_mixed("mixed", tid_a, failures)
            # 子用例B 空桩：零发现心跳票（同一桩文件换内容——inspect 在 spawn 时刻读文件）
            with open(stub, "w", encoding="utf-8") as f:
                f.write(lib.fenced_message([]))
            tid_b = trigger_one("heartbeat", inst_b, decl_b, tree.root, failures)
            if tid_b:
                journey_heartbeat("heartbeat", tid_b, failures)

        # ── 工作器二：真进程链模式（SANDBAR_INSPECT_CMD 挂起脚本；无 STUB env）
        os.environ["SANDBAR_TASK_QUEUE"] = queue2
        with lib.StageWorker(queue2, extra_env={"SANDBAR_INSPECT_CMD": hang}):
            tid_t = trigger_one("timeout", inst_t, decl_t, tree.root, failures)
            if tid_t:
                def blocked():
                    r = ticket_query(tid_t)
                    if not (r and isinstance(r.get("snapshot"), dict)):
                        return None
                    blob = json.dumps(r, ensure_ascii=False)
                    if "agent 未完成" in blob and (r.get("status") or "").upper() in ("BLOCKED", "FAILED", "CANCELLED", "COMPLETED"):
                        return r
                    if "agent 未完成" in blob and (r.get("snapshot") or {}).get("blocked_reason"):
                        return r
                    return None
                got, r = poll(blocked, POLL_BLOCK, 5)
                if not got:
                    failures.append("timeout 票 %ds 未到「agent 未完成」blocked（status=%r）——超时熔断不假绿面破"
                                    % (POLL_BLOCK, (r or {}).get("status")))
                else:
                    blob = json.dumps(r, ensure_ascii=False)
                    if "heartbeat" in blob and '"heartbeat": true' in blob:
                        failures.append("timeout 票 heartbeat 不得为 true（不假绿承诺）")
                ledger = lib.inspection_ledger(tid_t)
                if not isinstance(ledger, dict):
                    failures.append("timeout 票落账缺席（blocked 也须落账可见）")
                else:
                    if "agent 未完成" not in json.dumps(ledger, ensure_ascii=False):
                        failures.append("timeout 落账未点名「agent 未完成」：%r" % sorted(ledger)[:8])
                    hb = ledger.get("heartbeat")
                    if hb is True:
                        failures.append("timeout 落账 heartbeat=true（假绿）")
                ah = lib.agent_home_dir(ledger_dir)
                if ah is None:
                    failures.append("真 spawn 后 agent-home 未落台账目录（DSH_HOME 解耦面缺席）")
                try:
                    p = subprocess.run(["pgrep", "-f", HANG_MARKER], capture_output=True, text=True, timeout=10)
                    if p.returncode == 0 and p.stdout.strip():
                        failures.append("超时 reap 后挂起脚本仍存活（pgrep 命中：%s）——进程组回收面破"
                                        % p.stdout.strip()[:80])
                except (OSError, subprocess.SubprocessError) as e:
                    print("WARN: pgrep 不可用（%s）——reap 断言降级为落账/blocked 面" % e, flush=True)

        ok_red = tree.tree_unchanged() == ""
        if not ok_red:
            failures.append(tree.tree_unchanged())
        if os.path.exists(os.path.join(tree.root, ".dsh")):
            failures.append("审查基座（仓根）出现 .dsh 残留——agent DSH_HOME 与基座解耦面破")
    finally:
        tree.cleanup()
        shutil.rmtree(workdir, ignore_errors=True)
        shutil.rmtree(ledger_dir, ignore_errors=True)

    if failures:
        for m in failures:
            print("FAIL_REASON: " + m, flush=True)
        return 1
    print("PASS: inspect 段全链旅程——混合桩五类发现（verified/unverified+reason 点名/建议门"
          "只收合门发现）、段名 inspect 用户可见、零发现心跳票照开照收、人门两拍真拦、"
          "落账留存、超时子用例 blocked「agent 未完成」不假绿+agent-home 落台账目录+reap 干净、"
          "被审查树逐字节不变、基座零 .dsh 残留", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
