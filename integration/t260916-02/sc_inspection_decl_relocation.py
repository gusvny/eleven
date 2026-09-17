#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260916-02 集成场景（真链路主场景）：声明落位迁移后的多项目巡检用户旅程契约面（真 docker 台）。

intent（登记于 run_scenarios.py，名 t260916-02-relocation-realchain）：
  声明落进各项目仓根（引擎仓零声明、零 env 覆盖层、零 --decl-path，聚合遍历注册项目
  读各自声明）之后，双项目用户的可感知契约：
  ① 票号形状：trigger 起的巡检票号==工单号形式 ^t\\d{6}-\\d{2,}$，且日期段==期号日期段；
  ② 显式去重：同期重复 trigger → triggered:false/deduped:true、票号=既有、(实例,期) 的
    workflow 计数不增、退出码 0；
  ③ SA==票面：ProjectKey/InspectionInstance/InspectionPeriod 与回执票面同值；按实例查
    历史期（SA 查询）恰好命中该票；
  ④ 扫对仓：两票发现各自命中本仓独特漂移锚、绝不串对方仓；被扫树逐字节不变；
  ⑤ 板面聚合：白名单=各项目 enabled 实例并集（零 env 覆盖层下聚合可得=迁移题眼），
    行 instance/period==SA 值，新票行零旧形前缀，板面项目过滤各归各；
  ⑥ 分项目降级：注册表里混入一个坏声明项目 → 好项目行照常上板（不再「一份坏文件全板
    降级」）且回执 degraded_projects 点名坏项目；
  ⑦ 指针三态（真实链注入）：陈旧指针（指向不存在票、超 grace 龄）与畸形指针（半截
    字节、超 grace 龄）都不得谎报 deduped——自动清可观测（回执 stale_pointer_cleared
    点名路径）后照常开票；指针目录走 SANDBAR_INSPECTION_DIR 覆盖链；
  ⑧ 指针不污染 deadman：台账目录里的 .ticket 指针不进漏跑核查的畸形清单；
  ⑨ 跨族票号互见：ticket-list id_prefix 全前缀扫描能看到巡检票（巡检与 dev-lane 共用
    一个票号空间，防撞号的用户面承接）；
  ⑩ 聚合调度：schedule-up 不带 --decl-path 按各自项目声明接线，A/B 各自 cron 各归各；
    调度 action 指向 spawner（起票时刻铸 t 形号的承接面）。

分工（防 intent 级重复）：
  · t260915-20-project-identity-realchain 守「声明住引擎仓（B 方案）+ --decl-path 注入」
    时代的项目身份链路；本条守「声明落各项目仓根（A 迁移）」后的聚合解析链——彼条的
    --decl-path/env 注入面正是本票迁移掉的声明来源，不同面；
  · t260905-03-period-journey 守单期全链旅程质量（人门/收口审计链），本条不重测；
  · t260915-08-board-rows 守巡检行形状契约（快照注入对拍），本条守聚合白名单与三态
    可见性，行形状真值表归彼；
  · t260913-02-schedule-daily-deadman 守 deadman 期号推导与告警语义核心，本条只守
    「声明来源改聚合」接线与指针不污染，不重测期号语义；
  · 陈旧/畸形指针的细粒度真值表（grace 窗内/窗外、SA 不一致不自动清）归 developer L1；
  · t260916-02-decl-gate-aggregate（ro）守聚合声明门 fail-closed（缺失/坏形/指路/
    跨项目重复/覆盖层优先级）；本条从起票面开始。

三态：PASS exit 0 / FAIL exit 1（产品红，缺什么点名什么）/ ENV_FAIL exit 2
（docker 测试台/temporal CLI/temporalio 缺件=环境红点名，不假红不假绿）。
实现未落地=产品红（红属预期：TDD 信号），arbitrate/merge 期必须绿。

跑法（cwd=仓根）：
  PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; \
    "$PY" -B integration/t260916-02/sc_inspection_decl_relocation.py
"""
import asyncio
import base64
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "integration"))
sys.path.insert(0, os.path.join(REPO, "integration", "t260905-03"))
sys.path.insert(0, os.path.join(REPO, "integration", "t260916-02"))
sys.path.insert(0, os.path.join(REPO, "server", "engine"))

import lib_relocation as lr  # noqa: E402
# t260916-22：scan 段退役 → inspect 段（桩 agent）；发现注入走桩缝（方案 §3），
# 伪造器/复核态访问器单点在 t260916-22/lib_inspect。
sys.path.insert(0, os.path.join(REPO, "integration", "t260916-22"))
import lib_inspect as inspect_lib  # noqa: E402
from lib_inspection import (  # noqa: E402
    RepoTree, StageWorker, cleanup_tickets, die_env, die_fail, note_started_ticket,
    run_client, run_trigger,
)

try:
    import temporalio  # noqa: F401——SDK 直发/查询腿需要；缺席=环境红
except Exception:  # noqa: BLE001
    die_env("temporalio SDK 缺席（server/engine/.venv 不可用）——真链路腿无法执行")

PRODUCER_REL = "server/plugins/workbench/src/client/capture.mjs"
STATS = {"pass": 0, "fail": 0}
FAILS = []

PID = os.getpid()
KEY_A = "rla%d" % PID
KEY_B = "rlb%d" % PID
KEY_D = "rld%d" % PID          # 坏声明项目（分项目降级腿）
INST_A = "rla-ins-%d" % PID
INST_B1 = "rlb-one-%d" % PID
INST_B2 = "rlb-two-%d" % PID
PERIOD = datetime.datetime.now().strftime("%Y%m%d")
P2 = "19990102"                # 陈旧指针腿用过去期号（无在先票，SA 查询必空）
P3 = "19990103"                # 畸形指针腿用另一过去期号
TICKET_RE = re.compile(r"^t\d{6}-\d{2,}$")
TOKEN_A = "『甲仓落位迁移锚%d』" % PID
TOKEN_B = "『乙仓落位迁移锚%d』" % PID
# token 形注（arbitrate gen2 T4 根因②）：扫描器锚判据 is_anchor_literal 的「纯选择器/
# 路径」排除正则 ^[\w\-./: ]+$ 里 \w 含 CJK——全词形 token（甲仓锚NNN）会被整只吞掉，
# 锚清单空=零发现。带全角装饰 『』 才是「UI 文案字面」形态（与真仓锚『+ 新建』同形），
# 且不含括号内嵌 ascii 的排除形——断言锚必须过判据，发现证据才带得上本仓独特 token。
# 互异且年年命中（1/31 07:00、3/30 08:30）——远离测试窗保隔离；2/31 形永伪 cron
# 已被 deadman 守卫拒收（arbitrate gen2 调整），聚合调度腿按结构化日历断言各归各。
CRON_A = "0 7 31 1 *"
CRON_B = "30 8 30 3 *"
TRIGGER_ENV = {}


def check(name, cond, detail=""):
    if cond:
        STATS["pass"] += 1
        print("PASS %s" % name, flush=True)
    else:
        STATS["fail"] += 1
        FAILS.append("%s%s" % (name, ("：" + detail) if detail else ""))
        print("FAIL %s%s" % (name, ("：" + detail) if detail else ""), flush=True)


def trg(args):
    """触发面 CLI 统一出口：注册表缝+私有队列+夹具台账目录（spawn_env 白名单单点）。"""
    return run_trigger(args, env=dict(TRIGGER_ENV))


def ticket_date_ok(tid: str, period: str) -> bool:
    """t<YYMMDD>-<NN> 且日期段==期号日期段（期号含桶段取日期段的承接）。"""
    m = TICKET_RE.match(str(tid or ""))
    return bool(m) and str(tid).startswith("t" + str(period)[2:8])


# ---------------------------------------------------------------- 夹具

def drifty_tree(label: str, token: str) -> RepoTree:
    """仓形漂移夹具：守卫断言锚字面、生产方纯重写不含锚（KI-051 high 形态，必产发现
    且证据带本仓独特 token）。与 t260915-20 同款手法，token 本票自铸防跨票串锚。"""
    t = RepoTree(label)
    t.write_scenarios([("t-rl-guard", "落位迁移夹具守卫（%s）" % label, "true")])
    t.write("integration/sc_rl_guard.mjs",
            "// 守卫：落位迁移夹具锚（t260916-02 场景夹具，capture-chat 形态）\n"
            "// 守卫对象生产方: %s\n"
            "const label = await page.locator('.session-create').innerText();\n"
            'assert(label.includes("%s"), "守卫锚缺失");\n' % (PRODUCER_REL, token))
    t.write(PRODUCER_REL,
            'const section = "项目行";\n'
            'const label = section + "『+ 钮』";\n'
            "export function buttonLabel() { return label; }\n")
    t.keep_checksums()
    return t


def findings_text(snap):
    face = (snap or {}).get("face") if isinstance(snap, dict) else {}
    fs = (face or {}).get("findings") if isinstance(face, dict) else None
    parts = []
    for f in fs if isinstance(fs, list) else []:
        if isinstance(f, dict):
            parts.append("%s %s" % (f.get("subject") or "", f.get("evidence") or ""))
    return "\n".join(parts)


def fetch_snapshot(inst, period):
    _, parsed = trg(["describe", "--instance", inst, "--period", period])
    res = (parsed or {}).get("result") if isinstance(parsed, dict) else None
    snap = (res or {}).get("snapshot") if isinstance(res, dict) else None
    return snap if isinstance(snap, dict) else None


def poll_snapshot(inst, period, timeout_s, want_findings):
    deadline = time.time() + timeout_s
    snap = None
    while time.time() < deadline:
        snap = fetch_snapshot(inst, period)
        if isinstance(snap, dict):
            if not want_findings:
                return snap
            face = snap.get("face") if isinstance(snap.get("face"), dict) else {}
            if isinstance(face.get("findings"), list) and face.get("findings"):
                return snap
        time.sleep(3.0)
    return snap


def list_rows(project_key=""):
    """client.py ticket-list（kind=inspection）——**零 env 覆盖层**，白名单走聚合
    （迁移题眼：进程缺省声明来源=注册表聚合而非引擎仓/env 单文件）。"""
    args = {"kind": "inspection"}
    if project_key:
        args["project"] = project_key
    proc, parsed = run_client("ticket-list", args, env=dict(TRIGGER_ENV))
    res = (parsed or {}).get("result") if isinstance(parsed, dict) else None
    rows = (res or {}).get("tickets") if isinstance(res, dict) else None
    return rows if isinstance(rows, list) else None, parsed


def row_of(rows, tid):
    return next((r for r in (rows or []) if isinstance(r, dict) and r.get("id") == tid), {})


# ---------------------------------------------------------------- 腿

GUARD_REL = "integration/sc_rl_guard.mjs"
GUARD_ANCHOR_LINE = 5   # assert(label.includes("<token>"), "守卫锚缺失")


def guard_anchor_line(token: str) -> str:
    """守卫文件第 5 行原文（inspect 桩发现的 evidence 引文锚：只可能在本仓对上）。"""
    return 'assert(label.includes("%s"), "守卫锚缺失");' % token


def write_stub_anchor(stub_path: str, token: str):
    """按仓写桩消息（A/B 时序隔离：inspect 在 spawn 时刻读桩文件）。token 空串=空发现桩。"""
    fs = [] if not token else [inspect_lib.finding(
        "%s 仓独特锚漂移" % ("A" if token == TOKEN_A else "B"), GUARD_REL,
        GUARD_ANCHOR_LINE, guard_anchor_line(token), severity="high", confidence=0.9)]
    with open(stub_path, "w", encoding="utf-8") as f:
        f.write(inspect_lib.fenced_message(fs))


def t1_open_one(inst: str, period: str) -> str:
    """T1 起票（单实例）：t 形号 + 日期段==期号日期段（票号形状腿）。"""
    proc, parsed = trg(["trigger", "--instance", inst, "--period", period])
    res = (parsed or {}).get("result") if isinstance(parsed, dict) else {}
    tid = str((res or {}).get("ticket_id") or "")
    check("T1-%s trigger 放行且票号 t 形（日期段=期号段）" % inst,
          (parsed or {}).get("ok") is True and ticket_date_ok(tid, period),
          "ok=%r ticket_id=%r out=%s"
          % ((parsed or {}).get("ok"), tid, (proc.stdout or "")[-160:]))
    note_started_ticket(tid)
    return tid


def t2_dedup():
    """T2 显式去重：同期重复 trigger → deduped 回执同票号、计数不增、退出码 0。"""
    async def _count():
        from temporalio.client import Client
        client = await Client.connect(lr.TEST_TARGET_HOST, namespace=lr.TEST_NAMESPACE)
        q = ('WorkflowType="InspectionPeriodicWorkflow" AND %s="%s" AND %s="%s"'
             % (lr.SA_INSTANCE, INST_A, lr.SA_PERIOD, PERIOD))
        n = 0
        async for _ in client.list_workflows(q):
            n += 1
        return n

    proc, parsed = trg(["trigger", "--instance", INST_A, "--period", PERIOD])
    res = (parsed or {}).get("result") if isinstance(parsed, dict) else {}
    check("T2a 同期重复 trigger→deduped 同票号退出码 0",
          proc.returncode == 0 and (parsed or {}).get("ok") is True
          and (res or {}).get("triggered") is False
          and (res or {}).get("deduped") is True,
          "rc=%s ok=%r result=%s" % (proc.returncode, (parsed or {}).get("ok"),
                                     json.dumps(res, ensure_ascii=False)[:160]))
    n = asyncio.run(_count())
    check("T2b (实例,期) workflow 计数==1（不新建）", n == 1, "count=%r" % n)


def t3_sa_payload():
    """T3 SA==票面：describe 的 typed SA 与回执/快照票面同值；按实例查历史期命中。"""
    async def _sa_and_query():
        from temporalio.client import Client
        client = await Client.connect(lr.TEST_TARGET_HOST, namespace=lr.TEST_NAMESPACE)
        async for wf in client.list_workflows(
                'WorkflowType="InspectionPeriodicWorkflow" AND %s="%s" AND %s="%s"'
                % (lr.SA_INSTANCE, INST_A, lr.SA_PERIOD, PERIOD)):
            # list_workflows 产出 WorkflowExecution（无 describe）——describe 走 id 句柄
            info = await client.get_workflow_handle(wf.id).describe()
            sa = {}
            raw = getattr(info, "search_attributes", None)
            if isinstance(raw, dict):
                sa = {k: (v[0] if isinstance(v, list) and v else v)
                      for k, v in raw.items()}
            return sa
        return None

    sa = asyncio.run(_sa_and_query())
    check("T3a 票盖 ProjectKey/Instance/Period 三 SA 且与票面同值",
          isinstance(sa, dict) and str(sa.get(lr.SA_PROJECT) or "") == KEY_A
          and str(sa.get(lr.SA_INSTANCE) or "") == INST_A
          and str(sa.get(lr.SA_PERIOD) or "") == PERIOD,
          "sa=%s" % json.dumps(sa, ensure_ascii=False, default=str)[:200])
    # 按实例查历史期（口径②建议项）：只按实例 SA 查，恰好命中本票
    async def _by_instance():
        from temporalio.client import Client
        client = await Client.connect(lr.TEST_TARGET_HOST, namespace=lr.TEST_NAMESPACE)
        ids = []
        async for wf in client.list_workflows(
                'WorkflowType="InspectionPeriodicWorkflow" AND %s="%s"' % (lr.SA_INSTANCE, INST_A)):
            ids.append(wf.id)
        return ids

    ids = asyncio.run(_by_instance())
    first = [t for t in ids if ticket_date_ok(t, PERIOD)]
    check("T3b 按实例 SA 查历史期恰好命中本票", len(first) == 1, "ids=%s" % ids[:5])


def t4_scan_own_repo(snap_a, snap_b, tree_a, tree_b):
    """T4 扫对仓 + 被扫树逐字节不变。"""
    txt_a, txt_b = findings_text(snap_a), findings_text(snap_b)
    check("T4a A 票发现命中 A 仓独特锚且不串 B",
          TOKEN_A in txt_a and TOKEN_B not in txt_a,
          "含A锚=%s 含B锚=%s" % (TOKEN_A in txt_a, TOKEN_B in txt_a))
    check("T4b B 票发现命中 B 仓独特锚且不串 A",
          TOKEN_B in txt_b and TOKEN_A not in txt_b,
          "含B锚=%s 含A锚=%s" % (TOKEN_B in txt_b, TOKEN_A in txt_b))
    def _states(snap):
        face = (snap or {}).get("face") if isinstance(snap, dict) else {}
        fs = (face or {}).get("findings") if isinstance(face, dict) else []
        return [inspect_lib.finding_state(f) for f in (fs or []) if isinstance(f, dict)]
    check("T4a2 A 票发现证据复核 verified（基座=A 仓内容级证明）",
          bool(txt_a.strip()) and "verified" in _states(snap_a), "states=%r" % _states(snap_a))
    check("T4b2 B 票发现证据复核 verified（基座=B 仓内容级证明）",
          bool(txt_b.strip()) and "verified" in _states(snap_b), "states=%r" % _states(snap_b))
    bad = [t.label for t in (tree_a, tree_b) if t.tree_unchanged()]
    check("T4c 被扫树逐字节不变（巡检不改码红线）", not bad, "被改树=%s" % bad)


def t5_board(tid_a, tid_b1, tid_b2):
    """T5 板面聚合：白名单并集、行 instance/period==SA 值、零旧形前缀、项目过滤各归各。"""
    rows, parsed = list_rows()
    blob = json.dumps(parsed, ensure_ascii=False)
    ids = [str(r.get("id") or "") for r in (rows or []) if isinstance(r, dict)]
    check("T5a 聚合白名单收全 A/B 两项目三实例（零 env 覆盖层）",
          rows is not None and all(t in ids for t in (tid_a, tid_b1, tid_b2)),
          "ids=%s parsed=%s" % (ids[:6], blob[:160]))
    check("T5b 新票行零旧形前缀（inspection- 前缀零残留·运行时腿）",
          rows is not None and not any(i.startswith("inspection-") for i in ids),
          "ids=%s" % ids[:6])
    row_a = row_of(rows, tid_a)
    check("T5c 行 instance/period==SA 真源值",
          str((row_a or {}).get("instance_id") or "") == INST_A
          and str((row_a or {}).get("period") or "") == PERIOD,
          "instance=%r period=%r"
          % ((row_a or {}).get("instance_id"), (row_a or {}).get("period")))
    rows_a, _ = list_rows(KEY_A)
    ids_a = [str(r.get("id") or "") for r in (rows_a or []) if isinstance(r, dict)]
    check("T5d 板面项目过滤各归各（A 板含 A 票不含 B 票）",
          rows_a is not None and tid_a in ids_a
          and tid_b1 not in ids_a and tid_b2 not in ids_a,
          "ids_a=%s" % ids_a[:6])


def t6_per_project_degrade(tid_a):
    """T6 分项目降级：坏声明项目不拖垮好项目板面 + degraded_projects 点名。"""
    rows, parsed = list_rows()
    blob = json.dumps(parsed, ensure_ascii=False)
    ids = [str(r.get("id") or "") for r in (rows or []) if isinstance(r, dict)]
    check("T6a 好项目行照常上板（坏文件只降自己项目）", tid_a in ids, "ids=%s" % ids[:6])
    check("T6b 回执 degraded_projects 点名坏项目（key+路径可见）",
          "degraded_projects" in blob and KEY_D in blob,
          "blob 含 degraded_projects=%s 含 %s=%s"
          % ("degraded_projects" in blob, KEY_D, KEY_D in blob))


def t7_stale_pointer():
    """T7 陈旧指针（指向不存在的票、超 grace 龄）：不得谎报 deduped；自动清可观测后
    照常开票（方案 §2.2 指针三态·有效态-票不在支路）。"""
    p = lr.plant_pointer(TRIGGER_ENV["SANDBAR_INSPECTION_DIR"], INST_B2, P2,
                         json.dumps({"ticket_id": "t990101-99", "instance": INST_B2,
                                     "period": P2, "project_key": KEY_B}).encode(),
                         age_s=3600.0)
    proc, parsed = trg(["trigger", "--instance", INST_B2, "--period", P2])
    res = (parsed or {}).get("result") if isinstance(parsed, dict) else {}
    tid = str((res or {}).get("ticket_id") or "")
    check("T7a 陈旧指针不谎报 deduped（票不存在≠既有）",
          proc.returncode == 0 and (parsed or {}).get("ok") is True
          and (res or {}).get("deduped") is not True,
          "rc=%s result=%s out=%s" % (proc.returncode,
                                      json.dumps(res, ensure_ascii=False)[:160],
                                      (proc.stdout or "")[-120:]))
    check("T7b 陈旧指针自动清可观测（回执留痕点名路径）",
          p in json.dumps(parsed, ensure_ascii=False),
          "回执点名指针=%s" % (p in json.dumps(parsed, ensure_ascii=False)))
    check("T7c 清后照常开票（t 形号日期段=期号段）",
          (parsed or {}).get("ok") is True and ticket_date_ok(tid, P2),
          "ticket_id=%r" % tid)
    note_started_ticket(tid)


def t8_malformed_pointer():
    """T8 畸形指针（空/半截字节、超 grace 龄）：不静默不谎报 deduped，自动清后开票。"""
    p = lr.plant_pointer(TRIGGER_ENV["SANDBAR_INSPECTION_DIR"], INST_B2, P3,
                         b"\x00\x01 half-written garbage", age_s=3600.0)
    proc, parsed = trg(["trigger", "--instance", INST_B2, "--period", P3])
    res = (parsed or {}).get("result") if isinstance(parsed, dict) else {}
    tid = str((res or {}).get("ticket_id") or "")
    check("T8a 畸形指针不谎报 deduped",
          proc.returncode == 0 and (parsed or {}).get("ok") is True
          and (res or {}).get("deduped") is not True,
          "rc=%s result=%s" % (proc.returncode, json.dumps(res, ensure_ascii=False)[:160]))
    check("T8b 畸形指针自动清可观测且照常开票",
          p in json.dumps(parsed, ensure_ascii=False) and ticket_date_ok(tid, P3),
          "ticket_id=%r 点名=%s" % (tid, p in json.dumps(parsed, ensure_ascii=False)))
    note_started_ticket(tid)


def t9_deadman_pointer_clean():
    """T9 指针不污染 deadman：台账目录里的 .ticket 不进畸形清单（离线腿）。"""
    for inst in (INST_A, INST_B1):
        proc, parsed = trg(["deadman", "--instance", inst, "--offline"])
        blob = json.dumps(parsed, ensure_ascii=False) if isinstance(parsed, dict) else (proc.stdout or "")
        has_ticket_malformed = ".ticket" in blob and "malformed" in blob.lower() \
            and re.search(r"malformed[^\]]*\.ticket", blob, re.S) is not None
        check("T9-%s deadman 离线可跑且 .ticket 指针不进畸形清单" % inst,
              (parsed or {}).get("ok") is True and not has_ticket_malformed,
              "ok=%r out=%s" % ((parsed or {}).get("ok"), blob[:200]))


def t10_schedule_up_aggregate():
    """T10 聚合调度：schedule-up 零 --decl-path 各读各自项目声明；action 指向 spawner。"""
    cli = os.path.join(lr.TP_DIR, "bin", "temporal")
    cli = cli if os.path.exists(cli) else "temporal"
    addr = ["--address", lr.TEST_TARGET_HOST, "--namespace", lr.TEST_NAMESPACE]
    for inst, cron in ((INST_A, CRON_A), (INST_B1, CRON_B)):
        _, up1 = trg(["schedule-up", "--instance", inst, "--note", "t260916-02 场景自建（退出即删）"])
        mode1 = str(((up1 or {}).get("result") or {}).get("mode") or "")
        _, up2 = trg(["schedule-up", "--instance", inst, "--note", "t260916-02 场景自建 v2"])
        mode2 = str(((up2 or {}).get("result") or {}).get("mode") or "")
        check("T10a-%s schedule-up 建→改→update（聚合声明源）" % inst,
              mode1 == "created" and mode2 == "updated",
              "mode1=%r mode2=%r" % (mode1, mode2))
        p = subprocess.run([cli] + addr + ["schedule", "describe",
                                           "--schedule-id", "sandbar-inspection-%s" % inst,
                                           "--output", "json"],
                           capture_output=True, text=True, timeout=60)
        blob = (p.stdout or "") + (p.stderr or "")
        plain_parts = []
        for m in re.finditer(r'"data":\s*"([A-Za-z0-9+/=]+)"', blob):
            try:
                plain_parts.append(base64.b64decode(m.group(1)).decode("utf-8", "replace"))
            except Exception:  # noqa: BLE001——非 base64 段跳过
                pass
        plain = blob + "\n" + "\n".join(plain_parts)
        # 绑定从浅（KI-051 锚语义）：该 CLI 的 describe json 无 cronExpressions 字面
        # （spec.structuredCalendar 为区间对象列表且 0 值形态特殊，arbitrate gen2 探针
        # 实测）——改锚 info.nextActionTimes：下次命中时刻==本项目声明 cron 的预测值
        #（互异 cron 各归各=聚合遍历证据），不锚日历内部形状。
        mm, hh, dom, mon = cron.split()[:4]
        marker = "%02d-%02dT%02d:%02d" % (int(mon), int(dom), int(hh), int(mm))
        try:
            doc = json.loads(p.stdout or "{}")
            if isinstance(doc, list):
                doc = doc[0] if doc else {}
            nats = json.dumps(((doc.get("info") or {}).get("futureActionTimes") or []))
        except Exception as ex:  # noqa: BLE001——形状异常点名，不静默放过
            nats = "parse_error:%s" % ex
        check("T10b-%s 调度带各自项目声明的 cron（遍历非单文件的字面证据）" % inst,
              p.returncode == 0 and marker in nats,
              "rc=%s 期望下次命中含=%s 实得=%s" % (p.returncode, marker, nats[:120]))
        check("T10c-%s 调度 action 指向 spawner（起票时刻铸 t 形号承接面）" % inst,
              ("InspectionPeriodSpawnWorkflow" in plain) or ("inspection-spawn-" in plain),
              "含spawner类型=%s 含spawn-id=%s"
              % ("InspectionPeriodSpawnWorkflow" in plain, "inspection-spawn-" in plain))


def t11_cross_family_visibility(tid_a):
    """T11 跨族票号互见：ticket-list id_prefix 全前缀扫描能列出巡检票（与 dev-lane
    共用一个票号空间=防撞号的用户面承接；方案 §2.2 扫描面统一）。"""
    today = "t" + PERIOD[2:8]
    _, parsed = run_client("ticket-list", {"id_prefix": today}, env=dict(TRIGGER_ENV))
    blob = json.dumps(parsed, ensure_ascii=False) if isinstance(parsed, dict) else ""
    check("T11 id_prefix 全前缀扫描列出巡检票（跨族互见）",
          (parsed or {}).get("ok") is True and tid_a in blob,
          "ok=%r 含A票=%s" % ((parsed or {}).get("ok"), tid_a in blob))


# ---------------------------------------------------------------- 主流程

def main() -> int:
    lr.precheck_stage()

    tmp = tempfile.mkdtemp(prefix="sandbar-t26091602-")
    reg_root = os.path.join(tmp, "projects")
    os.makedirs(reg_root, exist_ok=True)
    ledger_dir = os.path.join(tmp, "ledger")
    tree_a = drifty_tree("rlxa-%d" % PID, TOKEN_A)
    tree_b = drifty_tree("rlxb-%d" % PID, TOKEN_B)
    tid_a = tid_b1 = tid_b2 = ""
    try:
        # A/B 项目：声明在各**自己仓根**（默认落位 <dirs[0]>/inspection.yaml），
        # 实例集不同（聚合腿）；注册表缝另含一个坏声明项目 D（分项目降级腿）。
        lr.write_registry(reg_root, KEY_A, "RelocA", [tree_a.root])
        lr.write_registry(reg_root, KEY_B, "RelocB", [tree_b.root])
        lr.write_registry(reg_root, KEY_D, "RelocD", [os.path.join(tmp, "d-empty")])
        lr.write_file(os.path.join(tree_a.root, "inspection.yaml"),
                      lr.decl_yaml([(INST_A, KEY_A, CRON_A, "test")]))
        lr.write_file(os.path.join(tree_b.root, "inspection.yaml"),
                      lr.decl_yaml([(INST_B1, KEY_B, CRON_B, "test"),
                                    (INST_B2, KEY_B, CRON_B, "test")]))
        lr.write_file(os.path.join(tmp, "d-empty", "inspection.yaml"),
                      "schema: v1\ninstances: not-a-list\n")   # 声明坏形态（fail-closed 面）
        # 快照基线=夹具种植完成之后（T4c 守「巡检不改动被扫树」，不把自建声明误判成改树；
        # arbitrate gen2 修正——首跑即红暴露的时点错）。
        tree_a.keep_checksums()
        tree_b.keep_checksums()

        queue = "sandbar-ticket-insrl-%d" % PID
        TRIGGER_ENV.update({"SANDBAR_PROJECTS_DIR": reg_root,
                            "SANDBAR_TASK_QUEUE": queue,
                            "SANDBAR_INSPECTION_DIR": ledger_dir})
        try:
            # extra_env=夹具 env 同喂 worker：运行期决议（resolve_inspection_plan）在
            # worker 进程重读声明来源——worker 拿不到夹具注册表就会按真实注册表解析出
            # 「实例未在任何项目声明中」blocked（T4 根因，arbitrate gen2 闭环）
            stub_path = os.path.join(tmp, "inspect-stub-message.txt")
            TRIGGER_ENV.update({"SANDBAR_INSPECT_STUB": "1",
                                "SANDBAR_INSPECT_STUB_FILE": stub_path})
            with StageWorker(queue, extra_env=TRIGGER_ENV):
                # t260916-22 桩缝时序：A 锚桩→A 票→落面后换 B 锚桩→B1 票→空桩→B2 票
                # （inspect 在 spawn 时刻读桩文件；同相对路径两仓都在，引文只可能对上
                # 本仓内容=引擎 base_dir 正确性的内容级证明）
                write_stub_anchor(stub_path, TOKEN_A)
                tid_a = t1_open_one(INST_A, PERIOD)
                snap_a = poll_snapshot(INST_A, PERIOD, 150, want_findings=True)
                write_stub_anchor(stub_path, TOKEN_B)
                tid_b1 = t1_open_one(INST_B1, PERIOD)
                snap_b = poll_snapshot(INST_B1, PERIOD, 150, want_findings=True)
                write_stub_anchor(stub_path, "")
                tid_b2 = t1_open_one(INST_B2, PERIOD)
                tid_b2 = tid_b2 or ""
                check("T4前置 两票发现均落面",
                      bool(findings_text(snap_a).strip()) and bool(findings_text(snap_b).strip()),
                      "A=%s B=%s" % (bool(findings_text(snap_a).strip()),
                                     bool(findings_text(snap_b).strip())))
                t4_scan_own_repo(snap_a, snap_b, tree_a, tree_b)
                t5_board(tid_a, tid_b1, tid_b2)
                t6_per_project_degrade(tid_a)
                t7_stale_pointer()
                t8_malformed_pointer()
                t9_deadman_pointer_clean()
                t10_schedule_up_aggregate()
                t11_cross_family_visibility(tid_a)
        finally:
            TRIGGER_ENV.clear()
    finally:
        # 资源回收：调度删除（幂等）→ 票 cancel（lib 账本）→ 夹具拆除
        for inst in (INST_A, INST_B1):
            lr.delete_schedule_best_effort(inst)
        try:
            cleanup_tickets()
        except Exception as e:  # noqa: BLE001——自清失败不炸退出路径
            print("WARN: 退出自清异常（%s）" % e, flush=True)
        tree_a.cleanup()
        tree_b.cleanup()
        shutil.rmtree(tmp, ignore_errors=True)

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
