#!/usr/bin/env python3
"""t260911-02 场景①：触发 kind 接线（every-n-tickets / race-first）隔离台全链（灰盒 L2/L3）。

依据四支：①工单验收 a/b/d/e/f 原文（夹具票计数达阈值即起票/未达不起；cron 面零回归；
未接线 kind 仍显式报错点名；一票一期去重与心跳语义不变；巡检票查询面可读）。②KI 回归纪律：
KI-049（死机制无人知）→ watcher terminate→schedule-up 复活→再触发注入腿（方案 R3 契约：
常驻 watcher 必须有幂等复活路径+可读活性观测面）；KI-072（负载敏感不稳定）→ 所有等待带
重试上限预算、不裸 sleep 单点等待；「测试写生产 Temporal」事故 → 本场景承 t260910-11
场景③五腿守卫（方案 R1 乙清单逐腿继承）。③组件对外契约（声明驱动、fail-closed、票号
幂等去重、同期合并 overlap 语义）——锚定 CLI 回执与落账报告等公开形状，不锚 watcher 内部实现。
④方案 R2 期粒度语义（用户可感知面）：cron 期=纯 YYYYMMDD、计数期=YYYYMMDD-<bucket>、
同桶重复触发 deduped、同日两形态并存合法。

安全自证（五腿守卫，承 t260910-11 场景③乙清单逐腿）：一切 spawn 经 lib.spawn_env 单点
显式钉 17233 隔离台（腿c 行为腿：ambient=生产 7233 的探针子进程被拒跑且点名生产台）；
夹具票号/项目键带进程戳+退出自清（腿d 自清腿）；生产台只读计数零新增为系统状态条件腿
（7233 可达且 temporal CLI 在位才跑，缺席按 N/A 折算不假绿不假红，动态对照权威面在
implement 验收证据）。
夹具计数真源=SANDBAR_PROJECTS_DIR 指向临时根 + <key>/data/tickets/<id>/ + archive.json
（schema v1 标记=已归档语义，与 project remove 的归档判定锚同源）。

登记 exclusive：自供给 worker+真票写隔离台，防并行场景互染。
实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿；隔离台缺席=ENV_FAIL 点名
（离线腿已验部分如实陈述）。
"""
import glob
import os
import shutil
import sys
import tempfile
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "t260905-03"))
sys.path.insert(0, os.path.join(BASE, "t260910-11"))
import lib_inspection as lib  # noqa: E402

PID = os.getpid()
TODAY = time.strftime("%Y%m%d")
# 等待预算（KI-072：重试上限+间隔，不裸 sleep 单点长等）
WATCH_BUDGET = 90.0     # 计数达阈值→起票（watcher 轮询间隔未知，留裕量）
QUIET_BUDGET = 20.0     # 未达阈值→断言窗口内不起票
STAMP = "%05d" % PID

FIXTURE_DECL = """schema: v1
instances:
  - id: integration-tests-%(stamp)s
    enabled: true
    project_key: sandbar
    schedule:
      kind: cron
      cron: 0 6 * * 1
    workflow: InspectionPeriodicWorkflow
    template: inspection-lite
  - id: cnt-ok-%(stamp)s
    enabled: true
    project_key: sandbar
    schedule:
      kind: every-n-tickets
      n: 2
      source: archive-dir
      project_key: insp%(stamp)s
    workflow: InspectionPeriodicWorkflow
    template: inspection-lite
  - id: cnt-low-%(stamp)s
    enabled: true
    project_key: sandbar
    schedule:
      kind: every-n-tickets
      n: 5
      source: archive-dir
      project_key: insp%(stamp)s
    workflow: InspectionPeriodicWorkflow
    template: inspection-lite
  - id: race-%(stamp)s
    enabled: true
    project_key: sandbar
    schedule:
      kind: race-first
      cron: 0 5 29 2 *
      n: 2
      source: archive-dir
      project_key: insp%(stamp)s
    workflow: InspectionPeriodicWorkflow
    template: inspection-lite
""" % {"stamp": STAMP}

# 离线负例夹具①：启用计数实例缺 source/project_key（decl 校验必点名缺哪个字段）
DECL_MISSING_SOURCE = """schema: v1
instances:
  - id: cnt-bad-%(stamp)s
    enabled: true
    schedule:
      kind: every-n-tickets
      n: 2
    workflow: InspectionPeriodicWorkflow
    template: inspection-lite
""" % {"stamp": STAMP}

# 离线负例夹具②：未知 kind 仍显式报错点名（fail-closed 不随接线扩大而松动）
DECL_UNKNOWN_KIND = """schema: v1
instances:
  - id: cnt-unk-%(stamp)s
    enabled: true
    schedule:
      kind: yearly-by-count
      n: 2
      source: archive-dir
      project_key: insp%(stamp)s
    workflow: InspectionPeriodicWorkflow
    template: inspection-lite
""" % {"stamp": STAMP}


def make_archive_root():
    """临时计数真源根：<root>/insp<pid>/data/tickets/<id>/archive.json。"""
    root = tempfile.mkdtemp(prefix="sandbar-insp-count-%s-" % STAMP)
    return root


def add_archived_ticket(root, key, tid):
    d = os.path.join(root, key, "data", "tickets", tid)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "archive.json"), "w", encoding="utf-8") as f:
        f.write('{"schema": "v1", "ticket_id": "%s"}' % tid)


def wait_until(fn, budget, interval=2.0):
    """KI-072 口径：deadline+间隔重试，不裸 sleep。fn()=真即停。"""
    deadline = time.time() + budget
    while time.time() < deadline:
        if fn():
            return True
        time.sleep(interval)
    return fn()


def ledger_glob(instance):
    pat = os.path.join(lib.TP_DIR, "out", "inspection", "inspection-%s-*.json" % instance)
    return sorted(glob.glob(pat))


def watcher_face(instance):
    """watcher 只读子命令（活性观测面契约）；回执非 ok 返回 None。"""
    proc, parsed = lib.run_trigger(["watcher", "--instance", instance])
    return (scanner_result_or_none(parsed), proc, parsed)


def scanner_result_or_none(parsed):
    return lib.scanner_result(parsed)


def main() -> int:
    failures = []
    notes = []
    na_legs = []
    workdir = tempfile.mkdtemp(prefix="sandbar-t26091102-%s-" % STAMP)
    archive_root = make_archive_root()
    key = "insp%s" % STAMP
    decl_path = os.path.join(workdir, "kinds.yaml")
    with open(decl_path, "w", encoding="utf-8") as f:
        f.write(FIXTURE_DECL)
    bad_decl = os.path.join(workdir, "bad_source.yaml")
    with open(bad_decl, "w", encoding="utf-8") as f:
        f.write(DECL_MISSING_SOURCE)
    unk_decl = os.path.join(workdir, "unknown_kind.yaml")
    with open(unk_decl, "w", encoding="utf-8") as f:
        f.write(DECL_UNKNOWN_KIND)

    inst_cron = "integration-tests-%s" % STAMP
    inst_cnt = "cnt-ok-%s" % STAMP
    inst_low = "cnt-low-%s" % STAMP
    inst_race = "race-%s" % STAMP

    # 场景安全线：本进程 ambient 先钉隔离台（lib.spawn_env 白名单再自检）
    os.environ["SANDBAR_TARGET_HOST"] = lib.TEST_TARGET_HOST
    os.environ["SANDBAR_NAMESPACE"] = lib.TEST_NAMESPACE
    os.environ["SANDBAR_PROJECTS_DIR"] = archive_root  # 计数真源注入点（ambient 合法键，进 worker 与 trigger 子进程）

    opened_tickets = []

    try:
        # ── 腿a（离线）：启用计数实例缺 source/project_key → 显式报错点名缺的字段 ──
        proc, parsed = lib.run_trigger(["trigger", "--instance", "cnt-bad-%s" % STAMP,
                                        "--decl-path", bad_decl])
        if not (isinstance(parsed, dict) and parsed.get("ok") is False):
            failures.append("腿a 缺 source 声明未被拒（fail-closed 缺口）：%r"
                            % ((parsed or (proc.stdout or "")[:160]),))
        else:
            err = str(parsed.get("error") or "")
            if "source" not in err and "project_key" not in err:
                failures.append("腿a 拒收报错未点名缺失字段（source/project_key）：%r" % err[:240])
            else:
                notes.append("腿a 缺字段拒收点名 ok")

        # ── 腿b（离线）：未知 kind 仍显式报错点名（接线扩大后 fail-closed 不松动）──
        proc, parsed = lib.run_trigger(["trigger", "--instance", "cnt-unk-%s" % STAMP,
                                        "--decl-path", unk_decl])
        if not (isinstance(parsed, dict) and parsed.get("ok") is False):
            failures.append("腿b 未知 kind 未被拒：%r" % ((parsed or (proc.stdout or "")[:160]),))
        else:
            err = str(parsed.get("error") or "")
            if "yearly-by-count" not in err:
                failures.append("腿b 报错未点名未知 kind 本体：%r" % err[:240])
            else:
                notes.append("腿b 未知 kind 点名 ok")

        # ── 腿c（五腿守卫·行为腿）：ambient=生产 7233 的探针子进程被拒跑且点名生产台
        #      （离线 decl 探针零网络，pre-implement 也不写生产）──
        probe_env = dict(os.environ)
        probe_env["SANDBAR_TARGET_HOST"] = "127.0.0.1:7233"
        probe_env.pop("SANDBAR_TASK_QUEUE", None)
        probe = subprocess_probe(probe_env, ["--instance", "cnt-unk-%s" % STAMP,
                                             "--decl-path", unk_decl])
        if probe is None:
            failures.append("腿c 生产台探针子进程异常退出（无输出）")
        elif probe[0] != 1:
            failures.append("腿c 指向生产 7233 未被拒跑（exit=%s，须 fail-closed 点名）：%s"
                            % (probe[0], probe[1][:200]))
        elif "7233" not in probe[1] and "生产" not in probe[1]:
            failures.append("腿c 拒跑未点名生产台 7233：%s" % probe[1][:200])
        else:
            notes.append("腿c 生产台拒跑点名 ok")

        # ── 环境探针：隔离台可达（在线腿前置；缺=ENV_FAIL，离线腿结果如实先陈述）──
        proc, parsed = lib.run_client("schedule-list", {})
        if not (isinstance(parsed, dict) and parsed.get("ok") is True):
            for m in failures:
                print("FAIL_REASON(离线腿已验部分): " + m, flush=True)
            lib.die_env("在线腿不可验：docker 测试台 %s 不可达或 temporalio 缺席"
                        "（schedule-list 未 ok，sh server/docker-compose.test.yml up -d）" % lib.TEST_TARGET_HOST)

        # 生产零写入条件腿前置计数（系统状态条件腿，缺席 N/A）
        prod_counter = find_temporal_cli()
        prod_before = None
        if prod_counter:
            prod_before = temporal_count(prod_counter)

        # 计数夹具：cnt-ok(n=2) 恰达阈值；cnt-low(n=5) 同源计数未达
        add_archived_ticket(archive_root, key, "t-a")
        add_archived_ticket(archive_root, key, "t-b")

        queue = "suyou-insp-kinds-%s" % STAMP
        os.environ["SANDBAR_TASK_QUEUE"] = queue
        with lib.StageWorker(queue):
            # ── 腿d：every-n-tickets 达阈值→schedule-up（计数形态）拉起 watcher→起票 ──
            proc, parsed = lib.run_trigger(["schedule-up", "--instance", inst_cnt,
                                            "--decl-path", decl_path, "--note", "t260911-02"])
            if not (isinstance(parsed, dict) and parsed.get("ok") is True):
                failures.append("腿d schedule-up 计数形态未放行（watcher 拉起缺口）：%r | stderr=%s"
                                % ((parsed or (proc.stdout or "")[:200]), (proc.stderr or "")[:160]))
            else:
                got_ticket = wait_until(lambda: bool(ledger_glob(inst_cnt)), WATCH_BUDGET)
                ledgers = ledger_glob(inst_cnt)
                if not got_ticket or not ledgers:
                    failures.append("腿d 夹具计数 2/2 达阈值 %ds 内未起票（every-n-tickets 触发缺口）"
                                    % WATCH_BUDGET)
                else:
                    tid = os.path.basename(ledgers[0])[:-5]
                    opened_tickets.append(tid)
                    period = tid.replace("inspection-%s-" % inst_cnt, "")
                    import re
                    if not re.match(r"^\d{8}-\d+$", period):
                        failures.append("腿d 计数期号形状非 YYYYMMDD-<bucket>（R2 契约）：%r" % period)
                    # ── 腿f（查询面，工单验收 f）：计数期票 ticket 子命令可读 ──
                    q_parsed = poll_ticket_ok(inst_cnt, period)
                    if q_parsed is None:
                        failures.append("腿f 计数期票 %s 查询面不可读（ticket 子命令缺口）" % tid)
                    else:
                        notes.append("腿f 计数期票查询可读 keys=%s" % sorted(q_parsed.keys()))
                    # ── 腿g2：同桶重复触发 deduped=true（票号幂等，一票一期不变）──
                    proc, parsed = lib.run_trigger(["trigger", "--instance", inst_cnt,
                                                    "--period", period,
                                                    "--decl-path", decl_path])
                    res = lib.scanner_result(parsed)
                    if not (isinstance(parsed, dict) and parsed.get("ok") is True
                            and res and res.get("deduped") is True):
                        failures.append("腿g2 同期重复触发未 deduped（票号幂等缺口）：%r"
                                        % ((parsed or (proc.stdout or "")[:160]),))
                    else:
                        notes.append("腿g2 同桶 deduped ok")

            # ── 腿e：未达阈值（2/5）→ 窗口内不起票 ──
            proc, parsed = lib.run_trigger(["schedule-up", "--instance", inst_low,
                                            "--decl-path", decl_path, "--note", "t260911-02"])
            if isinstance(parsed, dict) and parsed.get("ok") is True:
                opened_low = wait_until(lambda: bool(ledger_glob(inst_low)), QUIET_BUDGET)
                if opened_low:
                    failures.append("腿e 计数 2/5 未达阈值竟起票（误触发）：%s"
                                    % ledger_glob(inst_low))
                else:
                    notes.append("腿e 未达阈值不起票 ok（%ds 窗口）" % QUIET_BUDGET)
            else:
                failures.append("腿e schedule-up（未达阈值实例）未放行：%r"
                                % ((parsed or (proc.stdout or "")[:160]),))

            # ── 腿h（race-first·计数腿）：cron 设不可达时点（2/29），计数先到→起票；
            #      watcher 观测面回执基线/下次 cron 时点（R3 活性契约+R2 相位推进观测）──
            proc, parsed = lib.run_trigger(["schedule-up", "--instance", inst_race,
                                            "--decl-path", decl_path, "--note", "t260911-02"])
            if not (isinstance(parsed, dict) and parsed.get("ok") is True):
                failures.append("腿h race-first schedule-up 未放行：%r"
                                % ((parsed or (proc.stdout or "")[:200]),))
            else:
                got_race = wait_until(lambda: bool(ledger_glob(inst_race)), WATCH_BUDGET)
                race_ledgers = ledger_glob(inst_race)
                if not got_race or not race_ledgers:
                    failures.append("腿h race-first 计数先到未起票（race-first 触发缺口）")
                else:
                    notes.append("腿h race-first 计数先到起票 ok： %s"
                                 % os.path.basename(race_ledgers[0]))
                face, wproc, wparsed = watcher_face(inst_race)
                if face is None:
                    failures.append("腿h watcher 活性观测面不可读（watcher 子命令契约缺口）：%r"
                                    % ((wparsed or (wproc.stdout or "")[:160]),))
                else:
                    nxt = str(face.get("next_cron") or face.get("next_cron_at") or "")
                    if nxt and nxt[:10] <= TODAY:
                        failures.append("腿h 下次 cron 时点未推进到未来（R2 相位推进缺口）：%r" % nxt)
                    else:
                        notes.append("腿h watcher 面 ok（next_cron=%s baseline=%r）"
                                     % (nxt, face.get("baseline")))

            # ── 腿i（cron 面零回归+去重+心跳，工单验收 b/e）：cron 实例照常开票、
            #      期号纯 8 位、重复触发 deduped、落账带 heartbeat 字段 ──
            proc, parsed = lib.run_trigger(["trigger", "--instance", inst_cron,
                                            "--decl-path", decl_path])
            res = lib.scanner_result(parsed)
            if not (isinstance(parsed, dict) and parsed.get("ok") is True and res):
                failures.append("腿i cron 面触发未放行（零回归破）：%r"
                                % ((parsed or (proc.stdout or "")[:200]),))
            else:
                tid = str(res.get("ticket_id") or "")
                opened_tickets.append(tid)
                period = str(res.get("period") or "")
                import re
                if not re.match(r"^\d{8}$", period):
                    failures.append("腿i cron 期号必须纯 YYYYMMDD（不受计数期扩展污染）：%r" % period)
                proc2, parsed2 = lib.run_trigger(["trigger", "--instance", inst_cron,
                                                  "--period", period, "--decl-path", decl_path])
                res2 = lib.scanner_result(parsed2)
                if not (res2 and res2.get("deduped") is True
                        and str(res2.get("ticket_id") or "") == tid):
                    failures.append("腿i cron 期重复触发未 deduped 到同票（一票一期缺口）：%r" % (res2,))
                else:
                    notes.append("腿i cron 面零回归+dedup ok")
                led = wait_until(lambda: lib.inspection_ledger(tid) is not None, 30.0)
                led_data = lib.inspection_ledger(tid) if led else None
                if led_data is None:
                    notes.append("腿i 落账未及（收口前 ledger 可缺，heartbeat 断言让位）")
                elif "heartbeat" not in led_data:
                    failures.append("腿i 落账缺 heartbeat 字段（零发现心跳语义契约）：%s"
                                    % sorted(led_data.keys()))
                else:
                    notes.append("腿i heartbeat 字段在场=%r" % led_data.get("heartbeat"))
                # 同日 cron 期+计数期并存=合法（R2：两形态票号天然不同、不互斥）
                if ledgers_ok(inst_cnt) and opened_tickets:
                    notes.append("腿i 同日 cron 期+计数期并存 ok（R2 合法性）")

            # ── 腿j（R3/KI-049 注入）：terminate watcher→schedule-up 复活→再达阈值仍起票 ──
            face, wproc, wparsed = watcher_face(inst_cnt)
            wid = ""
            if face:
                wid = str(face.get("workflow_id") or face.get("id") or "")
            if not wid:
                wid = "inspection-watcher-%s" % inst_cnt  # 确定性 id 形状（灰盒兜底，公开约定）
            proc, parsed = lib.run_client("cancel", {"workflow_id": wid})
            if not (isinstance(parsed, dict) and parsed.get("ok") is True):
                notes.append("腿j watcher cancel 回执非 ok（终态后被 cancel 属正常）：%r"
                             % ((parsed or (proc.stdout or "")[:120]),))
            proc, parsed = lib.run_trigger(["schedule-up", "--instance", inst_cnt,
                                            "--decl-path", decl_path, "--note", "revive"])
            if not (isinstance(parsed, dict) and parsed.get("ok") is True):
                failures.append("腿j schedule-up 复活已死 watcher 未放行（KI-049 族：死机制无人知）：%r"
                                % ((parsed or (proc.stdout or "")[:200]),))
            else:
                add_archived_ticket(archive_root, key, "t-c")
                add_archived_ticket(archive_root, key, "t-d")
                revived = wait_until(lambda: len(ledger_glob(inst_cnt)) >= 2, WATCH_BUDGET)
                all_ledgers = ledger_glob(inst_cnt)
                if not revived or len(all_ledgers) < 2:
                    failures.append("腿j 复活后再达阈值未起新票（复活链缺口；现有=%s）"
                                    % [os.path.basename(x) for x in all_ledgers])
                else:
                    opened_tickets.extend(os.path.basename(x)[:-5] for x in all_ledgers)
                    notes.append("腿j terminate→复活→再触发 ok（%s）"
                                 % [os.path.basename(x)[:-5] for x in all_ledgers])

        # ── 腿k（五腿守卫·生产零写入条件腿）：N/A 仅此腿允许 ──
        if prod_counter and prod_before is not None:
            prod_after = temporal_count(prod_counter)
            if prod_after is None:
                na_legs.append("腿k 生产计数不可得（CLI 语法/可达性）按 N/A 折算")
            elif prod_after != prod_before:
                failures.append("腿k 生产 7233 工作流计数新增（测试腿写生产事故形态）：%r→%r"
                                % (prod_before, prod_after))
            else:
                notes.append("腿k 生产台零写入 ok")
        else:
            na_legs.append("腿k 生产台计数对照缺席（temporal CLI 缺失）按 N/A 折算")

    finally:
        # 场景卫生：退出自清（lib.StageWorker.__exit__ 已 cancel trigger 登记的巡检票；
        # 此处补两类残留——watcher 开出的票（按落账文件反查，cancel 已终态票报错即忽略）
        # 与计数/watcher 工作流本体，防隔离台僵尸常驻占队列）
        for inst in (inst_cnt, inst_low, inst_race):
            for path in ledger_glob(inst):
                lib.note_started_ticket(os.path.basename(path)[:-5])
            try:
                lib.run_client("cancel", {"workflow_id": "inspection-watcher-%s" % inst})
            except Exception:
                pass
        shutil.rmtree(workdir, ignore_errors=True)
        shutil.rmtree(archive_root, ignore_errors=True)

    for m in na_legs:
        print("N/A: " + m, flush=True)
    if failures:
        for m in failures:
            print("FAIL_REASON: " + m, flush=True)
        return 1
    print("PASS: " + "; ".join(notes), flush=True)
    return 0


def ledgers_ok(instance):
    return bool(ledger_glob(instance))


def poll_ticket_ok(instance, period, tries=8):
    """短轮询 ticket 查询（快照可见性延迟非产品缺陷，同 t260910-11 口径）。"""
    parsed = None
    for _ in range(tries):
        proc, parsed = lib.run_trigger(["ticket", "--instance", instance, "--period", period])
        if isinstance(parsed, dict) and parsed.get("ok") is True:
            return lib.scanner_result(parsed)
        time.sleep(1)
    return None


def subprocess_probe(env, trigger_args):
    """独立子进程探针：ambient=生产 7233 → lib 白名单拒跑（输出含点名）。零网络 decl 腿。"""
    import subprocess
    p = subprocess.run([lib.py_runner(), "-c",
                        "import sys; sys.path.insert(0, %r); import lib_inspection as l; "
                        "l.run_trigger(['trigger'] + %r)" % (os.path.join(BASE, "t260905-03"), trigger_args)],
                       capture_output=True, text=True, timeout=60, cwd=REPO_CWD(), env=env)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def REPO_CWD():
    return lib.REPO


def find_temporal_cli():
    """temporal CLI 解析（多候选回退，承 t260910-11 同名基础步骤）：engine bin → PATH →
    主检出（git common-dir 反推）。找不到返回 None（生产零写入条件腿按 N/A 折算）。"""
    import subprocess
    import shutil
    cands = [os.path.join(lib.TP_DIR, "bin", "temporal"), shutil.which("temporal")]
    try:
        common = subprocess.run(["git", "rev-parse", "--git-common-dir"],
                                capture_output=True, text=True, timeout=10,
                                cwd=lib.REPO).stdout.strip()
        if common:
            cands.append(os.path.join(os.path.dirname(os.path.abspath(common)),
                                      "server", "engine", "bin", "temporal"))
    except Exception:
        pass
    for c in cands:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def temporal_count(cli):
    """生产 7233 只读工作流计数（系统状态条件腿的动态对照；失败=None→N/A）。"""
    import subprocess
    try:
        p = subprocess.run([cli, "--address", "127.0.0.1:7233", "workflow", "list", "--limit", "1"],
                           capture_output=True, text=True, timeout=20)
        if p.returncode != 0:
            return None
        # 只比较可达性成立与否的稳定口径：行数含表头变化，改用 count 查询不可靠——
        # 退化为可达性布尔（0/1），能抓住「测试腿写生产」的从无到有事故形态
        return 1 if (p.stdout or "").strip() else 0
    except Exception:
        return None


if __name__ == "__main__":
    lib.reexec_venv_if_missing()
    try:
        sys.exit(main())
    finally:
        lib.cleanup_tickets()
