#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260917-02 集成场景一：旧调度 action 自愈重定向（真 docker 台，exclusive）。

intent（登记于 run_scenarios.py，名 t260917-02-legacy-fire-redirect）：
  调度路径（旧 action 直发形态）的用户可感知契约——线上 260917 实况的压缩复刻：
  ①重定向子用例：直发「旧 action 形」壳（非 t 形 id、payload 无 project_key——线上原始
    字节逐字复刻）→ 壳秒级终（不扫描、不落账、不进人门）→ 真票承接：票号 t 形
    ^t\\d{6}-\\d{2,}$、SA 三件套齐且 **ProjectKey==声明实例级身份**（payload 缺
    project_key 时身份回退链闭合——验收①「或复用已有票且三件套齐」+ R2c 假绿防波堤：
    夹具若按 payload 齐全构造，单测全绿而生产红）；
  ②未跳子用例（验收④主证据，review R4/C2）：真票挂人门（长挂等价物=interval ~10s 步长，
    OverlapPolicy=SKIP 只判上一 action 是否 Running，与墙钟时长无关）→ 连续多次 fire 照常发生：
    num_actions 递增 **且 num_actions_skipped_overlap 保持基线不变**（skip 以服务端
    计数直接断言，不由行为反推）+ 同期仍恰好一张 t 票（壳 deduped 复用）；
  ③dedup-closed 子用例（验收①「或复用已有票」半边）：真票收口（cancel→闭合）后再来一枚
    旧壳 → deduped：不起第二张 t 票、（实例,期) 计数不增、台账不增；
  ④deadman 回执子用例（review C1）：漏跑核查回执并 skip_count/running_actions 两键
    （additive；「此刻就在跳火」每天可见）——missed 空时 ok=true。

分工（防 intent 级重复）：
  · t260905-03-period-journey 守手动触发全链旅程与人门审计链——本条守「调度路（旧
    action 形）自愈重定向」，触发面不同；
  · t260916-02-relocation-realchain 守聚合声明+新票链路（起票侧 happy 形）——本条守
    旧壳重定向+身份回退链+未跳，不同面；
  · t260916-02-board-legacy-three-state 守板面三态降级读面——本条守起票链写面；
  · dedup 细粒度真值表（指针三态/撞号让位/grace 窗）归 developer L1 与既有场景
    （t260916-02 ⑦子用例），本条只守「同期已关票 → deduped 不起第二张」的调度路承接；
  · 台账归档留史归 t260917-02-ledger-archive-regression，本条只断言「壳不落账」
    （台账计数不增）。

资源回收（t260916-02 同款纪律）：自建调度退出即删（delete_schedule_best_effort）+
STARTED_TICKETS 账本退出 cancel（StageWorker __exit__ 自带）+夹具树/夹具台账目录拆除；
docker 测试台/CLI/venv 缺件=ENV_FAIL exit 2 点名。
实现未落地=产品红（红属预期：TDD 信号），arbitrate/merge 期必须绿。

跑法（cwd=仓根）：
  PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; \\
    "$PY" -B integration/t260917-02/sc_inspection_legacy_fire_redirect.py
"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "integration"))
sys.path.insert(0, os.path.join(REPO, "integration", "t260905-03"))
sys.path.insert(0, os.path.join(REPO, "integration", "t260916-02"))

import lib_relocation as lr  # noqa: E402
import lib_t260917 as lb  # noqa: E402
from lib_inspection import (  # noqa: E402
    RepoTree, StageWorker, cleanup_tickets, die_env, die_fail, run_trigger,
)

try:
    import temporalio  # noqa: F401——SDK 直发需要；缺席=环境红
except Exception:  # noqa: BLE001
    die_env("temporalio SDK 缺席（server/engine/.venv 不可用）——真链路子用例无法执行")

STATS = {"pass": 0, "fail": 0}
FAILS = []
PID = os.getpid()
KEY_A = "lfr%d" % PID
INST_A = "lfr-ins-%d" % PID
ENV = {}


def check(name, cond, detail=""):
    if cond:
        STATS["pass"] += 1
        print("PASS %s" % name, flush=True)
    else:
        STATS["fail"] += 1
        FAILS.append("%s%s" % (name, ("：" + detail) if detail else ""))
        print("FAIL %s%s" % (name, ("：" + detail) if detail else ""), flush=True)


def find_t_ticket(instance: str, exclude=()):
    """实例 SA 名下最新一枚 t 形票 id（重定向承接的真票；排除显式列表）。"""
    ids = lb.list_ids_by_instance(instance)
    for wid in reversed(ids):        # 新 run 在后（列表时序面）
        if lb.T_SHAPE_RE.match(wid) and wid not in exclude:
            return wid
    return None


def ledger_files(ledger_dir: str):
    d = os.path.join(ledger_dir, "archive")
    top = sorted(f for f in os.listdir(ledger_dir) if f.endswith(".json")) \
        if os.path.isdir(ledger_dir) else []
    return top, (sorted(os.listdir(d)) if os.path.isdir(d) else [])


def main() -> int:
    lr.precheck_stage()

    tmp = tempfile.mkdtemp(prefix="sandbar-t26091702-")
    reg_root = os.path.join(tmp, "projects")
    ledger_dir = os.path.join(tmp, "out-inspection")
    repo = RepoTree("lfr-healthy")    # 扫描根=RepoTree（含 integration/run_scenarios.py——
    # test 面场景清单在场性 fail-closed，裸目录=scan blocked「场景清单缺位」，260917 实测）
    os.makedirs(reg_root, exist_ok=True)
    os.makedirs(ledger_dir, exist_ok=True)
    repo.write_scenarios([])              # 空清单=零发现心跳票（journey 干净实例口径）
    schedule_id = ""
    queue = "sandbar-ticket-lfr-%d" % PID
    try:
        # 白名单真源=聚合声明：夹具实例在册、实例级 project_key=KEY_A（身份回退链的
        # 声明侧真源；旧 payload 不带 project_key——R2 的决定性形态）。
        lr.write_registry(reg_root, KEY_A, "LegacyFireRedirect", [repo.root])
        decl_path = lr.write_file(
            os.path.join(repo.root, "inspection.yaml"),
            lr.decl_yaml([(INST_A, KEY_A, lr.RARE_CRON, "test")]))
        ENV.update(lb.tickets_env(reg_root, ledger_dir, queue))

        with StageWorker(queue, extra_env={
                "SANDBAR_PROJECTS_DIR": reg_root, "SANDBAR_INSPECTION_DIR": ledger_dir}) as w:
            del w  # worker 就绪即可；workflow/activity 全走该私有队列

            # ---- ① 重定向子用例：旧壳秒级终，真 t 票承接且三件套齐（身份回退链闭合）----
            t0 = time.time()
            shell1 = lb.start_old_action_shell(INST_A, queue, repo.root, tag="s%d" % PID)
            st1 = lb.wait_terminal(shell1, budget_s=120.0)
            elapsed = time.time() - t0
            tid = lb.poll(lambda: find_t_ticket(INST_A), budget_s=30.0) or ""
            check("R1a 旧壳秒级终态（不占 Running 位——④的结构前提）",
                  st1 == "COMPLETED" and elapsed < 120.0,
                  "终态=%r 耗时=%.0fs" % (st1, elapsed))
            check("R1b 真票承接且票号 t 形（验收①主断言）",
                  bool(tid and lb.T_SHAPE_RE.match(tid)),
                  "t_ticket=%r" % tid)
            sa = lb.sa_triple(tid) if tid else {}
            check("R1c SA 三件套齐且 ProjectKey==声明实例级身份（payload 无 project_key——"
                  "身份回退链闭合，R2c）",
                  sa.get(lr.SA_INSTANCE) == INST_A
                  and bool(sa.get(lr.SA_PERIOD))
                  and sa.get(lr.SA_PROJECT) == KEY_A,
                  "SA=%s" % json.dumps(sa, ensure_ascii=False))
            period_p = sa.get(lr.SA_PERIOD, "")
            check("R1d 票号日期段==期号日期段（t 形词法自洽：t<YYMMDD> vs YYYYMMDD[2:8]）",
                  bool(period_p) and tid[1:7] == period_p[2:8],
                  "ticket=%r period=%r" % (tid, period_p))

            # 真票挂人门（未跳子用例的前置：人门长挂形态在案）
            def hung():
                _, parsed = run_trigger(["describe", "--instance", INST_A,
                                         "--period", period_p], env=ENV)
                return "awaiting-human" in json.dumps(parsed, ensure_ascii=False)
            check("R1e 真票进人门长挂（awaiting-human 在案——④的人门形态）",
                  bool(period_p) and lb.poll(hung, budget_s=120.0) is not None,
                  "period=%r" % period_p)

            top, _arc = ledger_files(ledger_dir)
            ledger_tid = ""
            if len(top) == 1:
                try:
                    with open(os.path.join(ledger_dir, top[0]), "r", encoding="utf-8") as f:
                        ledger_tid = str(json.load(f).get("ticket_id") or "")
                except Exception:  # noqa: BLE001——不可读照常判 FAIL
                    ledger_tid = ""
            check("R1f 台账恰好一份且归属真票（旧壳不落账——无同名双账/非壳账）",
                  len(top) == 1 and bool(tid) and ledger_tid == tid,
                  "台账=%s tid=%r 账内ticket_id=%r" % (top, tid, ledger_tid))

            # ---- ② 未跳子用例：interval 调度连续 fire，skip 计数不动（R4/C2）----
            schedule_id = lb.create_interval_schedule(INST_A, queue, repo.root, every_s=10)
            base = lb.schedule_counters(schedule_id)
            grew = lb.poll(lambda: lb.schedule_counters(schedule_id)["num_actions"]
                           >= base["num_actions"] + 2, budget_s=60.0)
            after = lb.schedule_counters(schedule_id)
            check("R2a 连续 fire 照常发生（num_actions 递增）",
                  bool(grew) and after["num_actions"] >= base["num_actions"] + 2,
                  "base=%s after=%s" % (base, after))
            check("R2b 未被静默跳过（skipped_overlap 保持基线——服务端计数直接断言，C2）",
                  after["skipped_overlap"] == base["skipped_overlap"],
                  "skipped base=%s after=%s" % (base["skipped_overlap"],
                                                after["skipped_overlap"]))
            check("R2c 同期仍恰好一张 t 票（壳 deduped 复用，不造第二张）",
                  len([i for i in lb.list_ids_by_instance(INST_A)
                       if lb.T_SHAPE_RE.match(i)]) == 1,
                  "实例名下 t 票=%s" % lb.list_ids_by_instance(INST_A))
            # 壳 redirect 有一个活动往返（开票+起真票，秒级）——单点读取会撞上在跑壳
            # （t260917-02 arbitrate 实测偶发红）；断言短命性=窗口内归零，非瞬时零。
            check("R2d 调度无滞留 action（壳全部短命——OverlapPolicy=SKIP 的 Running 位窗口内空出）",
                  lb.poll(lambda: lb.schedule_counters(schedule_id)["running_actions"] == 0
                          or None, budget_s=45.0, step=2.0) is not None,
                  "窗口内 running_actions 迟终不归零（末值=%s）"
                  % lb.schedule_counters(schedule_id)["running_actions"])

            # ---- ③ dedup-closed 子用例：真票收口后，旧壳 deduped 不起第二张 ----
            lb_note = ""
            try:
                lb.run_client("cancel", {"workflow_id": tid}, env=ENV)
                st_close = lb.wait_terminal(tid, budget_s=60.0)
                lb_note = "cancel 后终态=%r" % st_close
            except Exception as e:  # noqa: BLE001
                lb_note = "cancel 异常 %s: %s" % (type(e).__name__, e)
            top_before, _ = ledger_files(ledger_dir)
            shell2 = lb.start_old_action_shell(INST_A, queue, repo.root, tag="s2-%d" % PID)
            st2 = lb.wait_terminal(shell2, budget_s=120.0)
            t_after = [i for i in lb.list_ids_by_instance(INST_A) if lb.T_SHAPE_RE.match(i)]
            top_after, _ = ledger_files(ledger_dir)
            check("R3a 同期已闭合票在案时，旧壳 deduped：不起第二张 t 票（验收①复用半边）",
                  st2 == "COMPLETED" and len(t_after) == 1 and t_after[0] == tid,
                  "壳终态=%r t票=%s (%s)" % (st2, t_after, lb_note))
            check("R3b deduped 壳不落账（台账计数不增）",
                  len(top_after) == len(top_before) == 1,
                  "前=%s 后=%s" % (top_before, top_after))

            # ---- ④ deadman 回执子用例：跳火观测两键 additive（review C1）----
            _, dm = run_trigger(["deadman", "--instance", INST_A,
                                 "--decl-path", decl_path,
                                 "--ledger-dir", ledger_dir], env=ENV)
            dm_blob = json.dumps(dm, ensure_ascii=False)
            dm_res = (dm or {}).get("result") if isinstance(dm, dict) else {}
            check("R4a deadman 回执 ok（信封 ok=true+result 可读；夹具稀有 cron 无期望漏跑）",
                  (dm or {}).get("ok") is True and isinstance(dm_res, dict),
                  dm_blob[:200])
            check("R4b deadman 回执并 skip_count/running_actions 两键（跳火可观测，C1）",
                  "skip_count" in dm_blob and "running_actions" in dm_blob,
                  dm_blob[:200])
            sc = dm_res.get("skip_count") if isinstance(dm_res, dict) else None
            check("R4c skip 计数与实测一致（本调度从未跳：==0）",
                  sc is None or (isinstance(sc, int) and sc == 0),
                  "skip_count=%r" % sc)
    finally:
        if schedule_id:
            lr.delete_schedule_best_effort(INST_A)
        try:
            cleanup_tickets()
        except Exception as e:  # noqa: BLE001——自清失败不炸退出路径
            print("WARN: 退出自清异常（%s）" % e, flush=True)
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
        repo.cleanup()

    print("SUMMARY pass=%d fail=%d env_fail=%d na=%d"
          % (STATS["pass"], STATS["fail"], 0, 0), flush=True)
    if FAILS:
        print("FAIL_REASON: %s" % "；".join(FAILS), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001——意外异常=产品红点名，不静默不假绿
        die_fail("场景异常退出：%s: %s" % (type(e).__name__, e))
