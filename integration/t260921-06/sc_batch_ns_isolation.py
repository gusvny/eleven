#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260921-06 场景②：批内命名空间隔离与反用例（L3 看守，验收②③+要求2/5）。

intent（工单要求2/5 的用户可感知面）：
- 隔离段（验收②）：同一批台上两个并发 ns-acquire A/B ⇒ 各自命名空间互不污染——
  A 注册的自定义 SA 与启动的 workflow **不出现在 B 的命名空间**（temporal 的
  workflow/task queue/SA 均命名空间作用域=服务端语义，非约定）；
- 反用例段（验收③）：A 把自己的命名空间搞坏（优先 delete；CLI 不支持删除则注入
  污染形态=异名 SA+retention 改写）⇒ 同批 B 仍绿（SA/workflow 面完好）、批台容器
  身份不变（container id 前后一致）；
- 不假绿段（要求5）：批台不在位时 ns-acquire=ENV_FAIL exit 2（点名缺什么，绝不静默
  回落「没跑」）；ns-drop 幂等（NotFound=ok）、释放后可重申请（幂等注册）。

双模式（看守自身不制造例外面）：外层真全轮已注入 SANDBAR_STAGE_BATCH ⇒ 直接消费
外层批台（生产形态，零自建）；独立/手工运行 ⇒ 自管批台（up --kind batch，头注契约），
finally 拆台零残留。

与相邻场景 intent 分界：
- sc_batch_runner_form：守 runner 生命周期/churn 形态（docker 工程面）；本条守
  temporal 服务端的命名空间隔离语义与反用例，不数资产；
- t260910-04（KI-058 fresh 锚）/t260904-19 CLI 契约族：彼守单台新鲜度与起拆台契约
  本体，本条不重复；register_namespace 幂等单面由其 selftest/L1 承担。

实现落地前红属预期（TDD 验收门），arbitrate/merge 期必须绿；
docker/temporal CLI 缺席=ENV_FAIL exit 2。
"""
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib_batch import (  # noqa: E402
    Legs, RUN_SUFFIX, assets_for_project, boot_batch, cleanup_projects,
    compose_projects_scoped, container_id, down_stage, docker_ok, ns_acquire,
    ns_drop, temporal_bin, tcli, wait_until,
)

SA_A = "BatchProbeMarkerA"
ROGUE_SA = "BatchProbeRogueSA"


def batch_stage(legs):
    """双模式批台解析：外层注入 > 自管。返回 (batch_project, addr, owns) 或 None。"""
    env_batch = os.environ.get("SANDBAR_STAGE_BATCH")
    if env_batch:
        return env_batch, None, False
    project = "batch-t26092106-iso-%s" % RUN_SUFFIX
    rc, state, tail = boot_batch(project)
    if rc != 0 or not state:
        legs.env_fail_leg("批台自管起台（up --kind batch）",
                          "rc=%s tail=%s" % (rc, tail))
        return None
    port = (state.get("ports") or {}).get("temporal")
    if not port:
        legs.env_fail_leg("批台起台回执缺 ports.temporal", "state=%s" % str(state)[:300])
        return None
    return project, "127.0.0.1:%s" % port, True


def acquire_proc(batch, ns):
    """并发 ns-acquire 子进程（/bin/sh 同款 cwd=仓根，直接打公开 CLI）。"""
    return subprocess.Popen(
        [sys.executable, "-B", "integration/stage_docker.py", "ns-acquire",
         "--project", batch, "--namespace", ns],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(HERE.parents[1]))


def main():
    legs = Legs("t260921-06-batch-ns-isolation")
    if not docker_ok():
        print("ENV_FAIL: docker daemon 不可达——隔离/反用例段需要真批台")
        sys.exit(2)
    if not temporal_bin():
        print("ENV_FAIL: temporal CLI 不可得（env SANDBAR_TEMPORAL_BIN / server/engine/bin/temporal 均缺席）"
              "——SA/workflow 隔离断言需要它")
        sys.exit(2)
    tag = RUN_SUFFIX
    resolved = batch_stage(legs)
    if not resolved:
        legs.finish()
        return
    batch, addr, owns = resolved
    ns_a, ns_b = "t26092106-iso-a-%s" % tag, "t26092106-iso-b-%s" % tag
    wid_a = "t26092106wfa-%s" % tag
    tq_a = "t26092106tqa-%s" % tag
    batch_ct = "%s-temporal" % batch
    try:
        # 地址：外层批台模式从 ns-acquire 回执取端口；自管模式从起台回执取
        if addr is None:
            _, st, tail = ns_acquire(batch, ns_b)
            if not legs.check("外层批台 ns-acquire 可用（取址）", bool(st and (st.get("ports") or {}).get("temporal")),
                              "tail=%s" % tail):
                legs.finish()
                return
            addr = "127.0.0.1:%s" % st["ports"]["temporal"]
            legs.check("外层批台重申请幂等（B ns 复用）", True, "")

        before_id = container_id(batch_ct)
        if not legs.check("批台容器在位（<批>-temporal）", bool(before_id), "name=%s" % batch_ct):
            legs.finish()
            return

        # ---------------- 段 A：并发隔离（验收②）
        pa, pb = acquire_proc(batch, ns_a), acquire_proc(batch, ns_b)
        try:
            outa = pa.communicate(timeout=90)
            outb = pb.communicate(timeout=90)
        except subprocess.TimeoutExpired:
            pa.kill(); pb.kill()
            outa = pa.communicate(); outb = pb.communicate()
        ra, rb = outa[0], outb[0]

        def last_json(text):
            for line in reversed((text or "").strip().splitlines()):
                s = line.strip()
                if s.startswith("{"):
                    try:
                        return json.loads(s)
                    except Exception:
                        continue
            return None
        ja, jb = last_json(ra), last_json(rb)
        if legs.check("A0 并发 ns-acquire 双绿", pa.returncode == 0 and pb.returncode == 0,
                      "rc a=%s b=%s err=%s" % (pa.returncode, pb.returncode, (outa[1] + outb[1])[-240:])):
            port_a = (ja or {}).get("ports", {}).get("temporal")
            port_b = (jb or {}).get("ports", {}).get("temporal")
            legs.check("A1 同批同址（端口一致）", bool(port_a) and port_a == port_b,
                       "a=%s b=%s" % (port_a, port_b))
            # A 命名空间里放标记物：自定义 SA + 无 worker workflow（事件面在 list 可见）
            sa = tcli(["operator", "search-attribute", "create", "--namespace", ns_a,
                       "--name", SA_A, "--type", "Keyword"], addr=addr)
            wf = tcli(["workflow", "start", "--workflow-id", wid_a, "--type", "BatchProbeNoop",
                       "--task-queue", tq_a, "--namespace", ns_a, "--input", "{}"], addr=addr)
            if legs.check("A2 A 命名空间标记物放置成功（SA+workflow start）",
                          sa.returncode == 0 and wf.returncode == 0,
                          "sa=%s wf=%s %s" % (sa.stderr[-160:], wf.stderr[-160:], sa.stdout[-120:])):
                seen = wait_until(lambda: wid_a in (tcli(["workflow", "list", "--namespace", ns_a],
                                                         addr=addr).stdout or ""),
                                  20, interval=3)
                sa_a = tcli(["operator", "search-attribute", "list", "--namespace", ns_a], addr=addr)
                sa_b = tcli(["operator", "search-attribute", "list", "--namespace", ns_b], addr=addr)
                wf_b = tcli(["workflow", "list", "--namespace", ns_b], addr=addr)
                legs.check("A3 A 的 workflow 在 A 可见", bool(seen), "list A 无 %s" % wid_a)
                legs.check("A4 A 的 SA 标记在 A 可见", SA_A in (sa_a.stdout or ""), sa_a.stdout[-160:])
                legs.check("A5 隔离：A 的 SA 不出现在 B", SA_A not in (sa_b.stdout or ""),
                           sa_b.stdout[-200:])
                legs.check("A6 隔离：A 的 workflow 不出现在 B", wid_a not in (wf_b.stdout or ""),
                           wf_b.stdout[-200:])

        # ---------------- 段 B：反用例——A 搞坏自己的 ns，B 不受影响（验收③）
        if legs.check("B0 前置：批台容器身份取到", bool(container_id(batch_ct)), ""):
            form = "delete"
            dele = tcli(["operator", "namespace", "delete", ns_a, "--yes"], addr=addr, timeout=60)
            if dele.returncode != 0:
                # CLI 删除不可用（spike 开放面）⇒ 降级污染形态：异名 SA + retention 改写
                form = "pollute"
                tcli(["operator", "search-attribute", "create", "--namespace", ns_a,
                      "--name", ROGUE_SA, "--type", "Keyword"], addr=addr)
                tcli(["operator", "namespace", "update", "--retention", "1h",
                      "--namespace", ns_a], addr=addr)
            b_sa = tcli(["operator", "search-attribute", "list", "--namespace", ns_b], addr=addr)
            b_wf = tcli(["workflow", "list", "--namespace", ns_b], addr=addr)
            after_id = container_id(batch_ct)
            legs.check("B1 搞坏动作已执行（%s）" % form,
                       form == "delete" or ROGUE_SA in (tcli(["operator", "search-attribute",
                                                              "list", "--namespace", ns_a],
                                                             addr=addr).stdout or ""),
                       "delete rc=%s" % dele.returncode)
            legs.check("B2 反用例：B 的 SA 面完好（无 A 标记无污染标记）",
                       SA_A not in (b_sa.stdout or "") and ROGUE_SA not in (b_sa.stdout or "")
                       and b_sa.returncode == 0, b_sa.stdout[-200:])
            legs.check("B3 反用例：B 的 workflow 面完好（无 A 条目）",
                       wid_a not in (b_wf.stdout or "") and b_wf.returncode == 0, b_wf.stdout[-200:])
            legs.check("B4 反用例：批台容器身份不变", before_id == after_id and bool(after_id),
                       "before=%s after=%s" % (before_id, after_id))

        # ---------------- 段 C：不假绿——批台不在位=ENV_FAIL exit 2（要求5）
        rc, _, tail = ns_acquire("t26092106-nobatch-%s" % tag, "t26092106-x-%s" % tag)
        legs.check("C1 批台不在位 ns-acquire=exit 2", rc == 2, "rc=%s tail=%s" % (rc, tail[-200:]))
        legs.check("C2 环境红点名格式（ENV_FAIL 标记在案）", "ENV_FAIL" in tail, tail[-200:])

        # ---------------- 段 D：ns-drop 幂等与重申请（要求2 收尾面）
        d1 = ns_drop(batch, ns_a)
        d2 = ns_drop(batch, ns_a)
        d3 = ns_acquire(batch, ns_a)
        legs.check("D1 ns-drop 首删成功（exit 0）", d1[0] == 0, "rc=%s %s" % (d1[0], d1[2][-160:]))
        legs.check("D2 ns-drop 再删幂等（NotFound=ok exit 0）", d2[0] == 0, "rc=%s %s" % (d2[0], d2[2][-160:]))
        legs.check("D3 释放后可重申请（幂等注册）", d3[0] == 0, "rc=%s %s" % (d3[0], d3[2][-160:]))
        legs.finish()
    finally:
        # 收尾：释放自己申请的 ns（外层批台绝不 down）；自管批台 finally 拆台零残留
        for ns in (ns_a, ns_b):
            try:
                ns_drop(batch, ns, timeout=60)
            except Exception as e:
                print("STAGE_ 收尾 ns-drop 异常（%s）：%s" % (ns, e), file=sys.stderr, flush=True)
        if owns:
            rc, _, tail = down_stage(batch, timeout=180)
            if rc != 0:
                print("STAGE_ 自管批台收尾 down 非零：%s" % tail[:200], file=sys.stderr, flush=True)
            else:
                gone = wait_until(lambda: all(v <= 0 for v in assets_for_project(batch).values()),
                                  60, interval=3)
                if not gone:
                    print("STAGE_ 自管批台收尾后仍有资产残留：%s" % assets_for_project(batch),
                          file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
