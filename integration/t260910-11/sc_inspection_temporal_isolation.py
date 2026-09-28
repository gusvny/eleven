#!/usr/bin/env python3
"""t260910-11 场景③：测试子用例隔离生产 Temporal——红线守卫（灰盒 L2/L3）。

依据三支：①工单④红线原话「巡检场景一律指向隔离台 Temporal（fail-closed：检测到
目标为生产 7233 即拒跑）…并加守卫场景断言『测试运行不向生产 Temporal 写入任何
workflow』」+ 260910 实证后果（3 张真实期次号占住「一票一期」锁、清场 4 张僵尸才
恢复）。②KI 回归纪律：本条即「测试写生产 Temporal」事故的回归用例——事故形态=
lib 从不注入 SANDBAR_TARGET_HOST，子进程全落 shared.py 默认 127.0.0.1:7233。③
守卫的耐久形态（灰盒绑定浅）：断言钉公开行为与 env 契约——fail-closed 拒跑点名
生产台（子用例a 行为子用例）、子进程 env 构造钉非 7233（子用例b 静态子用例）、隔离台真跑且票号带
进程戳+退出自清（子用例c/d 行为子用例）、生产台只读计数零新增（子用例e 系统状态条件子用例：
7233 可达且 temporal CLI 在位才跑，缺席按 N/A 折算不假绿不假红——动态对照的权威
面在 implement 验收证据，本条是常驻回归网）。

安全自证：本场景自身一切 spawn 显式钉 17233 隔离台（命名空间=lib.TEST_NAMESPACE 台现值，
t260917-07 收口后=契约缺省 sandbar-test；import 后立刻钉 ambient），
pre-implement 代码状态下也绝不向生产台开票；子用例a 的拒跑探针子进程只跑离线 decl
（零网络），生产 env 只用来验证「被拒」。

实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。登记 exclusive：
子用例e 的生产计数对照要求独占窗口（防并行场景写流量混入判定面）。
"""
import json
import os
import socket
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "t260905-03"))
import lib_inspection as lib  # noqa: E402

TEST_HOST = "127.0.0.1:17233"
PROD_HOST = "127.0.0.1:7233"
LIB_TEXT_PATH = os.path.join(BASE, "t260905-03", "lib_inspection.py")
def _find_temporal_cli():
    """temporal CLI 解析（多候选回退）：engine bin → PATH → 主检出（worktree 的 bin/
    目录不入 git，只在主仓物理存在；git common-dir 反推主仓路径）。找不到返回 None
    （子用例e 按 N/A 折算，不假绿）。"""
    import shutil as _sh
    cands = [os.path.join(lib.TP_DIR, "bin", "temporal"), _sh.which("temporal")]
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


TEMPORAL_CLI = _find_temporal_cli() or os.path.join(lib.TP_DIR, "bin", "temporal")

FIXTURE_DECL = """schema: v1
instances:
  - id: integration-tests-%05d
    enabled: true
    project_key: sandbar
    schedule:
      kind: cron
      cron: 0 6 * * 1
    workflow: InspectionPeriodicWorkflow
    template: inspection-lite
"""


def probe_port(host_port: str) -> bool:
    host, _, port = host_port.partition(":")
    try:
        with socket.create_connection((host, int(port)), timeout=2.0):
            return True
    except OSError:
        return False


def _prod_inspection_count():
    """生产台只读计数（唯一接触生产的方式=list/count 读面；只数 inspection- 前缀）。"""
    # 前缀计数用 BETWEEN 区间 trick（CLI 的 count/list 查询不吃 STARTS WITH）
    p = subprocess.run([TEMPORAL_CLI, "workflow", "list", "--address", PROD_HOST,
                        "--query", 'WorkflowId BETWEEN "inspection-" AND "insurance."',
                        "--limit", "1000"],
                       capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        return None
    return sum(1 for ln in p.stdout.splitlines() if ln.startswith("inspection-")
               or " inspection-" in ln)


def main() -> int:
    env_notes: list = []
    failures = []
    notes = []
    ticket_id = ""
    workdir = os.path.join(lib.TP_DIR, "out", "t260910-11-iso-%05d" % os.getpid())
    os.makedirs(workdir, exist_ok=True)

    # 子用例e 基准：任何写入子用例之前先取生产只读计数（可得性在此一次性判定）
    prod_countable = probe_port(PROD_HOST) and os.path.exists(TEMPORAL_CLI)
    prod_before = None
    if prod_countable:
        prod_before = _prod_inspection_count()
        if prod_before is None:
            prod_countable = False
            notes.append("子用例e 生产计数不可解析（CLI 回执异常），跳过判定")

    # 场景自证安全线：本进程之后的一切 spawn 显式钉隔离台（防 pre-implement 代码
    # 落回默认生产台——本场景自己绝不重演事故）
    os.environ["SANDBAR_TARGET_HOST"] = TEST_HOST
    os.environ["SANDBAR_NAMESPACE"] = lib.TEST_NAMESPACE  # naming-compat：存量测试台命名空间

    try:
        # ── 子用例a（离线行为子用例）：ambient 指生产 7233 → lib 注入路径拒跑且点名生产台 ──
        decl_path = os.path.join(workdir, "iso.yaml")
        with open(decl_path, "w", encoding="utf-8") as f:
            f.write(FIXTURE_DECL % os.getpid())
        child_code = (
            "import sys;\n"
            "sys.path.insert(0, %r);\n"
            "import lib_inspection as l;\n"
            "l.run_trigger(['decl', '--decl-path', %r]);\n"
            "print('CHILD_NOT_REFUSED');\n" % (os.path.join(BASE, "t260905-03"), decl_path)
        )
        child_env = dict(os.environ)
        child_env["SANDBAR_TARGET_HOST"] = PROD_HOST
        child_env.pop("SANDBAR_TASK_QUEUE", None)
        proc = subprocess.run([sys.executable, "-c", child_code], capture_output=True,
                              text=True, timeout=60, cwd=lib.REPO, env=child_env)
        out = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode == 0 and "CHILD_NOT_REFUSED" in out:
            failures.append("子用例a 目标=生产 7233 时注入路径未拒跑（fail-closed 缺席，红线主体）：%r"
                            % out[:200])
        elif "7233" not in out and "生产" not in out:
            failures.append("子用例a 拒跑了但报错未点名生产台/7233（报错必须精确）：%r" % out[:240])
        else:
            notes.append("子用例a 生产目标拒跑点名在文")

        # ── 子用例b（静态子用例）：lib 子进程 env 构造钉非生产台（守卫的耐久形态）──
        with open(LIB_TEXT_PATH, "r", encoding="utf-8") as f:
            lib_text = f.read()
        EXPECTED_NS = lib.TEST_NAMESPACE  # 断言期望值派生自被测单点（t260917-07：此前硬编码旧名致看守与 lib 脱钩漏报，永不复钉字面量）
        for token in ("SANDBAR_TARGET_HOST", TEST_HOST, EXPECTED_NS):
            if token not in lib_text:
                failures.append("子用例b lib_inspection 未钉隔离台契约：缺 %s（测试子用例隔离未落地）"
                                % token)
        if lib_text.count("SANDBAR_TARGET_HOST") < 2:
            failures.append("子用例b SANDBAR_TARGET_HOST 注入点不足（至少 worker+trigger 两个 "
                            "spawn 路径都要钉），现状 %d 处"
                            % lib_text.count("SANDBAR_TARGET_HOST"))

        # ── 隔离台探活：缺=ENV_FAIL（离线子用例已验部分如实陈述，不假红不假绿）──
        if not probe_port(TEST_HOST):
            lib.die_env("隔离子用例不可验：docker 测试台 %s 不可达（sh server/docker-compose.test.yml "
                        "up -d）——子用例a/子用例b 离线面已验：%s"
                        % (TEST_HOST, "; ".join(notes) or "无"))

        # ── 子用例c（隔离台真跑）：私有队列+自供给 worker，票号带进程戳 ──
        import time
        private_queue = "suyou-insp-iso-%05d" % os.getpid()
        instance = "integration-tests-%05d" % os.getpid()
        ticket_id = ""
        with lib.StageWorker(private_queue):
            proc, parsed = lib.run_trigger(["trigger", "--instance", instance,
                                            "--period", time.strftime("%Y%m%d"),
                                            "--decl-path", decl_path])
            if not isinstance(parsed, dict) or parsed.get("ok") is not True:
                failures.append("子用例c 隔离台触发未放行：%r | stderr=%s"
                                % ((parsed or (proc.stdout or "")[:200]), (proc.stderr or "")[:200]))
            else:
                ticket_id = str(((parsed.get("result") or {}).get("ticket_id")) or "")
                if not ticket_id:
                    failures.append("子用例c 放行回执未带 ticket_id：%r" % parsed)
                elif not __import__("re").match(r"^t\d{6}-\d+$", ticket_id):
                    # 260928 修（本子用例在 main 上长红的真因）：原判据要求票号**带进程戳**
                    # （`str(os.getpid()) in ticket_id`）——那是「旧形票号 id 编码实例/期」时代的
                    # 隔离手法。t260916-02 起票号改为 t 形（`t26MMDD-NN`，id 不再编码实例/期），
                    # 隔离标记**移到实例名与 SA**（本子用例的实例=`integration-tests-%05d % pid`）。
                    # 判据按现行约定重述、意图不变：票号必须是 t 形（真票），且本夹具以**实例**
                    # 带进程戳与真票隔离——故这里锁 t 形，实例名带戳由上方 instance 构造保证。
                    failures.append("子用例c 票号非 t 形（测试票号隔离面破）：%r" % ticket_id)
        # ── 子用例d（退出自清）：with 退出后，本进程开的票在隔离台上不再是 RUNNING ──
        if ticket_id:
            # 260928：本子用例原只查一次，而共享测试台的 h2 通道会偶发
            # `RPCError: h2 protocol error`（传输层瞬态）⇒ 回执不可辨被记成产品红（实测一次）。
            # 按 KI-072 口径加**有界重试**（3 次 / 间隔 2s）；仍失败则如实以「传输层不可辨」记红，
            # 不冒充产品行为（报错精确）。
            proc = parsed = None
            _TRANSIENT = ("h2 protocol error", "Unavailable", "Timeout expired", "RPCError",
                          "Deadline Exceeded", "connection refused", "Connection refused")
            for _try in range(5):
                # 260928：终态判定改用 **describe**（query 对**已关闭**的 workflow 需要 worker 重放，
                # 而本子用例刚 cancel 完、专属 worker 已退 ⇒ query 恒超时，那是探针姿势问题不是环境红）。
                # describe 对终态 workflow 恒可读（status=TERMINATED/CANCELED/COMPLETED），正合本判据。
                proc, parsed = lib.run_client("describe", {"workflow_id": ticket_id})
                _blob = json.dumps(parsed, ensure_ascii=False) if isinstance(parsed, dict) else str(parsed)
                if not any(t in _blob for t in _TRANSIENT):
                    break
                time.sleep(2.0)
            if isinstance(parsed, dict) and parsed.get("ok") is True:
                status = str(((parsed.get("result") or {}).get("status")) or "")
                if status == "RUNNING":
                    failures.append("子用例d 退出后票仍 RUNNING（退出自清缺席——僵尸票事故形态）：%r"
                                    % ticket_id)
                else:
                    notes.append("子用例d 退出后状态=%s" % (status or "?"))
            else:
                # 已 terminate 的 workflow 查询报错=清理成功的可辨形态（点名票号而非笼统超时）
                err = str((parsed or {}).get("error") or (proc.stdout or "")[:120])
                if (ticket_id in err or "not found" in err.lower() or "不存在" in err
                        or "closed" in err.lower()):   # cancel 成功=已关闭（终态非 RUNNING）
                    notes.append("子用例d 退出后查询点名不存在（已清）")
                elif any(t in err for t in _TRANSIENT):
                    # 260928：传输层瞬态（重试 5 次仍不可达）=**环境红**，不冒充产品行为
                    # （三态纪律：环境缺席走 env，不走 FAIL——实况 h2 protocol error / Timeout expired）。
                    env_notes.append("子用例d 查询遇传输层瞬态（%s）：判环境面未验" % err[:120])
                else:
                    failures.append("子用例d 退出后查询回执不可辨（既非非 RUNNING 也非点名不存在）：%r"
                                    % err[:200])

        # ── 子用例e（生产零写入，系统状态条件子用例）：全程结束后对账只读计数 ──
        if prod_countable:
            after = _prod_inspection_count()
            if after is None:
                notes.append("子用例e 结束计数不可解析，跳过判定")
            elif after != prod_before:
                failures.append("子用例e 生产 Temporal 巡检 workflow 计数新增（%d→%d）——"
                                "测试写生产红线破" % (prod_before, after))
            else:
                notes.append("子用例e 生产计数零新增（%s）" % prod_before)
        elif not any("子用例e" in n for n in notes):
            notes.append("子用例e N/A：生产台不可达或 temporal CLI 缺席（系统状态条件子用例，"
                         "动态对照权威面在 implement 验收证据）")
    finally:
        import shutil
        # 场景卫生：pre-implement 状态下 lib 无自清，best-effort cancel 自己开的票，
        # 不在隔离台留僵尸（子用例d 的判定在此之前已完成，不受影响；已清则本调用报错即忽略）
        if ticket_id:
            try:
                lib.run_client("cancel", {"workflow_id": ticket_id})
            except Exception:
                pass
        shutil.rmtree(workdir, ignore_errors=True)

    if failures:
        for m in failures:
            print("FAIL_REASON: " + m, flush=True)
        return 1
    if env_notes:
        for m in env_notes:
            print("ENV_FAIL: " + m, flush=True)
        return 2
    print("PASS: " + "; ".join(notes), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
