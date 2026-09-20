#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260917-02 集成场景二：板面可见性——不可辨在跑显式降级 + 同期同注（真 docker 台，exclusive）。

intent（登记于 run_scenarios.py，名 t260917-02-board-unresolved-running）：
  巡检板面（client.py ticket-list kind=inspection）的用户可感知契约——260917 事故
  「正在等人审的巡检跑在 UI 上不存在」的回归闸：
  ①不可辨在跑显式降级可见：无实例/期 SA 且 id 非旧形词法的 RUNNING 巡检运行（今晨
    事故形态直发复刻）必须上板为显式降级行——行在场、不静默丢失、不被悄悄归入某项目
    （identity_note 以「不可辨」假设语气点名；回执 kept_unresolved 键可辨——与闭合
    dropped_unresolved 分账）；
  ②闭合不可辨维持丢弃：同形态票闭合（cancel）后不上板（僵尸纪律半边不动，本票只
    翻转「在跑」半边）且回执 dropped_unresolved 可辨；
  ③同期 closed+awaiting-human 双行并存带注：同一（实例,期) 的在跑票与已闭合票并存时，
    两行都不隐藏，在跑行带 same_period_closed=<闭合票号> 注（验收②主断言——用户能在
    板上同时看见「正在等人审」与「同期已收口」两张）；
  ④可辨但不在册实例不上板：有 SA 但实例不在册的 RUNNING 行维持丢弃（白名单纪律不因
    ①放宽）。

分工（防 intent 级重复，与 t260916-02-board-legacy-three-state 对账）：
  · 彼守「可辨但不在册 → 不上板」与旧形三代票的降级读面（legacy 查询路径）；本条守
    「不可辨但在跑 → 降级可见」的翻转半边 + 同期同注 + 两枚反用例钉死新边界（不同分支
    不矛盾）；
  · t260915-08-board-rows 守行形状契约（快照对拍/R8 闭合窗）不同面；
  · 本条 ③ 的构造=真实触发票挂人门 + SDK 直发同期 SA 票即取即闭（板面只读列表面，
    构造方式不影响被测读面契约）。

资源回收（t260916-02 同款纪律）：StageWorker __exit__ 退出 cancel STARTED_TICKETS +
夹具树/夹具台账目录拆除；docker 测试台/CLI/venv 缺件=ENV_FAIL exit 2 点名。
实现未落地=产品红（红属预期：TDD 信号），arbitrate/merge 期必须绿。

跑法（cwd=仓根）：
  PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; \\
    "$PY" -B integration/t260917-02/sc_inspection_board_unresolved_running.py
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
KEY_B = "bur%d" % PID
INST_B = "bur-ins-%d" % PID            # 在册实例（板面白名单真源=聚合声明）
INST_X = "bur-zzz-%d" % PID            # 不在册实例（僵尸纪律反用例）
UNRES_PREFIX = "inspection-%s-period-" % INST_B   # 今晨事故形态的不可辨 id 前缀
ENV = {}


def check(name, cond, detail=""):
    if cond:
        STATS["pass"] += 1
        print("PASS %s" % name, flush=True)
    else:
        STATS["fail"] += 1
        FAILS.append("%s%s" % (name, ("：" + detail) if detail else ""))
        print("FAIL %s%s" % (name, ("：" + detail) if detail else ""), flush=True)


_T_SEQ = [PID * 100]


def unresolvable_id(tag: str) -> str:
    """今晨事故形态：inspection-<实例>-period-<时间戳>——无 SA 时实例身份不可辨。"""
    return "%s%d-%s" % (UNRES_PREFIX, PID, tag)


def t_shaped_id() -> str:
    _T_SEQ[0] += 1
    return "t%s-%05d" % (time.strftime("%y%m%d"), _T_SEQ[0])


def awaiting_human(instance: str) -> bool:
    _, parsed = run_trigger(["describe", "--instance", instance], env=ENV)
    return "awaiting-human" in json.dumps(parsed, ensure_ascii=False)


def main() -> int:
    lr.precheck_stage()

    tmp = tempfile.mkdtemp(prefix="sandbar-t26091702b-")
    reg_root = os.path.join(tmp, "projects")
    ledger_dir = os.path.join(tmp, "out-inspection")
    os.makedirs(reg_root, exist_ok=True)
    os.makedirs(ledger_dir, exist_ok=True)
    repo = RepoTree("bur-healthy")    # 扫描根=RepoTree（场景清单在场——fail-closed 实测）
    repo.write_scenarios([])              # 空清单=零发现心跳票
    queue = "sandbar-ticket-bur-%d" % PID
    try:
        lr.write_registry(reg_root, KEY_B, "BoardUnresolved", [repo.root])
        lr.write_file(os.path.join(repo.root, "inspection.yaml"),
                      lr.decl_yaml([(INST_B, KEY_B, lr.RARE_CRON, "test")]))
        ENV.update(lb.tickets_env(reg_root, ledger_dir, queue))

        # ---- ① 不可辨在跑 → 显式降级行（今晨事故形态）----
        u1 = lb.start_workerless_ticket(unresolvable_id("u1"), queue, INST_B, "")
        parsed, blob = lb.board_blob(ENV)
        row1 = lb.row_of(parsed, u1)
        check("B1a 不可辨在跑行上板（不许静默丢失——260917 事故回归）",
              row1 is not None,
              "行在场=%s blob尾=%s" % (row1 is not None, blob[-160:]))
        r1 = json.dumps(row1, ensure_ascii=False) if row1 else ""
        check("B1b 降级行显式点名（不可辨/疑似 假设语气，不锚措辞字面）",
              ("不可辨" in r1) or ("疑似" in r1) or ("unresolved" in r1.lower()),
              "行=%s" % r1[:200])
        check("B1c 降级行不被悄悄归项目（project 空或行内点名不可辨）",
              (row1 is None) or str((row1 or {}).get("project") or "") == ""
              or ("不可辨" in r1),
              "project=%r" % (row1 or {}).get("project"))
        check("B1d 回执 kept_unresolved 键可辨（与闭合丢弃分账——additive 契约）",
              '"kept_unresolved"' in blob,
              "blob 含键=%s" % ('"kept_unresolved"' in blob))

        # ---- ② 闭合不可辨 → 维持丢弃（僵尸半边不动）----
        u2 = lb.start_workerless_ticket(unresolvable_id("u2"), queue, INST_B, "")
        lb.run_client("cancel", {"workflow_id": u2}, env=ENV)
        lb.wait_terminal(u2, budget_s=60.0)
        parsed2, blob2 = lb.board_blob(ENV)
        check("B2a 闭合不可辨不上板（僵尸纪律半边维持）",
              lb.row_of(parsed2, u2) is None,
              "行在场=%s" % (lb.row_of(parsed2, u2) is not None))
        check("B2b 回执 dropped_unresolved 键可辨（闭合丢弃计数在案）",
              '"dropped_unresolved"' in blob2,
              "blob 含键=%s" % ('"dropped_unresolved"' in blob2))

        # ---- ③ 同期 closed+open 双行并存带注（验收②主断言）----
        # 闭合行=真票 A 签字收口（板面词汇 closed==签字后 close 快照，blocked/CANCELED
        # 均不算——第一次跑实测修正）。open 行=worker 退出后 SDK 直发同期无主待行：
        # S4 重定向落地后一切可运行直发都会进 open_period_ticket 去重单点（同期双跑
        # 被 fail-closed 拒开——修复生效面），并存态只能以不落地的待行构造（板面读面
        # 只认列表面 (实例,期) 匹配，构造方式不进断言面）。
        tid_a = ""
        period_p = ""
        with StageWorker(queue, extra_env={
                "SANDBAR_PROJECTS_DIR": reg_root,
                "SANDBAR_INSPECTION_DIR": ledger_dir}) as w:
            del w
            _, trig = run_trigger(["trigger", "--instance", INST_B], env=ENV)
            tid_a = str(((trig or {}).get("result") or {}).get("ticket_id") or "")
            check("B3a 前置：真实触发票开出（t 形）",
                  bool(tid_a) and lb.T_SHAPE_RE.match(tid_a) is not None,
                  "ticket=%r" % tid_a)
            check("B3b 前置：真票进人门长挂（awaiting-human 在案）",
                  lb.poll(lambda: awaiting_human(INST_B), budget_s=180.0,
                          step=5.0) is not None,
                  "ticket=%r" % tid_a)
            period_p = lb.sa_triple(tid_a).get(lr.SA_PERIOD, "")
            _, sg = run_trigger(["sign", "--instance", INST_B, "--period", period_p,
                                 "--who", "human-scenario", "--decision", "approve"],
                                env=ENV)
            check("B3c 前置：真票 A 签字收口完成（closed 行的真形态）",
                  lb.poll(lambda: lb.status_of(tid_a) == "COMPLETED" or None,
                          budget_s=90.0, step=2.0) is not None,
                  "sign 回执=%s" % json.dumps(sg, ensure_ascii=False)[:160])
        # worker 已退：无主直发同期待行（无 worker 供跑 → 恒在跑，open 面）
        tid_b = t_shaped_id() + "b"
        lb.start_workerless_ticket(tid_b, queue, INST_B, period_p,
                                   sa_project=KEY_B, sa_instance=INST_B,
                                   sa_period=period_p)

        # 待行=RUNNING 且未进人门（awaiting_gate 是行恒有键，判值不判子串——子串判别
        # 对巡检行永假；行集在信封 result 层——读错层曾把在场行误判为空板，均为实测修正）
        row_b_seen = None
        _ids_seen = []
        _b3d_err = ""
        _dl = time.time() + 120.0
        while time.time() < _dl:
            try:
                _p, _ = lb.board_blob(ENV)
                _rows = [r for r in (((_p or {}).get("result") or {}).get("tickets") or [])
                         if isinstance(r, dict)]
                _ids_seen = [r.get("id") for r in _rows]
                row_b_seen = next((r for r in _rows if r.get("id") == tid_b), None)
                if row_b_seen is not None \
                        and row_b_seen.get("awaiting_gate") is not True \
                        and str(row_b_seen.get("status") or "") != "closed":
                    break
            except BaseException as e:  # noqa: BLE001——诊断面：异常进 detail 不静默
                _b3d_err = "%s: %s" % (type(e).__name__, str(e)[:200])
            time.sleep(5.0)
        check("B3d 前置：同期 open 行上板（待行降级面在场）",
              row_b_seen is not None and row_b_seen.get("awaiting_gate") is not True
              and str(row_b_seen.get("status") or "") != "closed",
              "ticket=%r row=%s ids=%s err=%s"
              % (tid_b, json.dumps(row_b_seen, ensure_ascii=False)[:300], _ids_seen, _b3d_err))
        parsed3, blob3 = lb.board_blob(ENV)
        row_a = lb.row_of(parsed3, tid_a)
        row_b = lb.row_of(parsed3, tid_b)
        check("B3e 在跑行与同期闭合行并存且都不隐藏（验收②：等审形态在 UI 上存在）",
              row_a is not None and row_b is not None
              and str((row_a or {}).get("status")) == "closed",
              "闭合行=%s(status=%r) open行=%s"
              % (row_a is not None, (row_a or {}).get("status"), row_b is not None))
        ra = json.dumps(row_b, ensure_ascii=False) if row_b else ""
        check("B3f 在跑行带 same_period_closed=<闭合票号> 注",
              (row_b or {}).get("same_period_closed") == tid_a or tid_a in ra,
              "same_period_closed=%r 行=%s"
              % ((row_b or {}).get("same_period_closed"), ra[:220]))

        # ---- ④ 可辨但不在册实例 → 不上板（白名单纪律不因 ① 放宽）----
        u4 = lb.start_workerless_ticket(
            t_shaped_id() + "x", queue, INST_X, "20260101",
            sa_project=KEY_B, sa_instance=INST_X, sa_period="20260101")
        parsed4, _blob4 = lb.board_blob(ENV)
        check("B4 可辨但不在册实例 RUNNING 仍不上板（僵尸纪律 SA 查询路径维持）",
              lb.row_of(parsed4, u4) is None,
              "行在场=%s" % (lb.row_of(parsed4, u4) is not None))
    finally:
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
