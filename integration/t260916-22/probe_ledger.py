#!/usr/bin/env python3
"""诊断探针（临时，不入册）：复现 journey 混合腿的最小链，落账目录保留现场。"""
import json
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib_inspect as lib  # noqa: E402

STAMP = os.getpid() % 100000
INST = "probe-mixed-%05d" % STAMP
SIGN_WHO = "human-scenario"


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


def main() -> int:
    _proc, parsed = lib.run_client("schedule-list", {})
    if not (isinstance(parsed, dict) and parsed.get("ok") is True):
        print("ENV: 测试台不可达 %r" % (str(parsed)[:120],))
        return 2
    workdir = tempfile.mkdtemp(prefix="sandbar-probe-work-")
    ledger_dir = tempfile.mkdtemp(prefix="sandbar-probe-ledger-")
    os.environ["SANDBAR_INSPECTION_DIR"] = ledger_dir
    decl = os.path.join(workdir, "p.yaml")
    with open(decl, "w", encoding="utf-8") as f:
        f.write("""schema: v1
instances:
  - id: %s
    enabled: true
    project_key: sandbar
    schedule:
      kind: cron
      cron: 0 6 * * 1
    workflow: InspectionPeriodicWorkflow
    template: inspection-lite
""" % INST)
    stub = os.path.join(workdir, "stub.txt")
    tree = lib.evidence_tree("probe")
    l2 = tree.line_text(lib.GUARD_REL, 2)
    with open(stub, "w", encoding="utf-8") as f:
        f.write(lib.fenced_message([
            lib.finding("探锚高危", lib.GUARD_REL, 2, l2, severity="high", confidence=0.9),
        ]))
    queue = "sandbar-probe-%05d" % STAMP
    # 泳道队列泄漏防线：stage-admin 环境会 ambient 注入 SANDBAR_TASK_QUEUE=
    # sandbar-ticket-<本票号>（无人消费即挂死）——探针与场景一样必须显式钉私有队列
    os.environ["SANDBAR_TASK_QUEUE"] = queue
    tid = ""
    try:
        with lib.StageWorker(queue, extra_env={
                "SANDBAR_INSPECT_STUB": "1",
                "SANDBAR_INSPECT_STUB_FILE": stub}):
            proc, parsed = lib.run_trigger(["trigger", "--instance", INST, "--period", "20260916",
                                            "--decl-path", decl, "--repo-root", tree.root])
            res = (parsed or {}).get("result") or {}
            tid = str(res.get("ticket_id") or "")
            print("trigger ok=%s tid=%s" % ((parsed or {}).get("ok"), tid), flush=True)

            def face_ready():
                r = ticket_query(tid)
                if not (r and isinstance(r.get("snapshot"), dict)):
                    return None
                fa = r["snapshot"].get("face")
                if isinstance(fa, dict) and isinstance(fa.get("findings"), list) and fa.get("findings"):
                    return r
                return None
            got, r = poll(face_ready, 120, 3)
            print("face_ready=%s" % got, flush=True)
            if got:
                fa = (r.get("snapshot") or {}).get("face") or {}
                print("face keys=%s findings=%d" % (sorted(fa), len(fa.get("findings") or [])), flush=True)
            proc, parsed = lib.run_trigger(["sign", "--instance", INST, "--period", "20260916",
                                            "--who", SIGN_WHO, "--decision", "approve",
                                            "--decl-path", decl])
            print("sign ok=%s %s" % ((parsed or {}).get("ok"), str((parsed or {}).get("error"))[:120]), flush=True)

            def closed():
                r = ticket_query(tid)
                return bool(r and r.get("status") == "COMPLETED")
            got, _ = poll(closed, 240, 3)
            print("closed=%s" % got, flush=True)
            # 收口后宽窗读账（≤30s），逐秒现场
            deadline = time.time() + 30
            led = None
            while time.time() < deadline:
                led = lib.inspection_ledger(tid)
                if isinstance(led, dict):
                    break
                time.sleep(2)
            print("ledger_is_dict=%s" % isinstance(led, dict), flush=True)
            if isinstance(led, dict):
                print("ledger keys=%s" % sorted(led), flush=True)
        print("== ledger_dir 现场：%s" % ledger_dir, flush=True)
        for name in sorted(os.listdir(ledger_dir)):
            p = os.path.join(ledger_dir, name)
            print("  %s (%d bytes)%s" % (name, os.path.getsize(p),
                  " [dir: %s]" % os.listdir(p)[:4] if os.path.isdir(p) else ""), flush=True)
        # 兜底：按票号全盘找
        print("query 终态=%s" % (ticket_query(tid) or {}).get("status"), flush=True)
        return 0
    finally:
        tree.cleanup()
        shutil.rmtree(workdir, ignore_errors=True)
        print("LEDGER_DIR_PRESERVED=%s" % ledger_dir, flush=True)


if __name__ == "__main__":
    sys.exit(main())
