#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260921-06 场景④：消费缝迁移回归（L2 组件契约看守，验收⑤+要求3/5）。

intent（「批级共享不得改变任何判定口径」的缝面执法）：
- lib_gate.require_stage 是批消费者族（约 30 场景）唯一消费缝：env 缺席 ⇒ 现行行为
  **逐字保留**（自起独立台、sa_registered 判定、stage_down 拆台零残留）——直跑/例外
  场景零回归的契约锚；env 在场 ⇒ 批模式（不新建任何台：窗口内零新工程、批台容器
  身份不变；ns=场景申请值；地址=批台端口且返回态 project=批台名——端口/名不符=
  缝静默回落自起台形态，看守点红）；stage_down 在批模式只 ns-drop 绝不拆批台；
- with_stage.sh 批模式壳面：SANDBAR_STAGE_BATCH 在场 ⇒ ns-acquire→跑→ns-drop
  （**绝不 ensure/down**）；env 缺席 ⇒ ensure→跑→down（现行逐字）；ns-acquire 红 ⇒
  壳 exit 2 透传（不吞不改）——壳桩法（cwd 桩 stage_docker，记录子命令序列）；
- 批台护栏面：--kind batch 与 --keep 互斥（usage 拒收）——「不得退化整机共享」的
  CLI 闸（头注契约）。

与相邻场景 intent 分界：
- sc_batch_runner_form：守执行器预起/收口/窗口形态（runner 面）；本条守缝与壳的调用
  序契约（lib_gate/with_stage 面）；
- sc_batch_ns_isolation：守服务端隔离语义；本条不查 temporal 面隔离；
- t260904-19 CLI 契约族：守单台 up/ensure/down 契约本体；本条只守批模式新增分叉。

实现落地前红属预期（TDD 验收门），arbitrate/merge 期必须绿；
docker 缺席 ⇒ 真台段环境红（桩面段不依赖 docker 照跑）。
"""
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lib_batch import (  # noqa: E402
    Legs, REPO, RUN_SUFFIX, assets_for_project, boot_batch, cleanup_projects,
    compose_projects_scoped, container_id, docker_ok, down_stage, mkworkdir,
    ns_acquire, ns_drop, rmworkdir, stage_cli,
)

PROBE = HERE / "probe_consumer.py"
STUB = """#!/usr/bin/env python3
import json, os, sys
log = os.environ["T260921_STUB_LOG"]
with open(log, "a", encoding="utf-8") as fh:
    fh.write((sys.argv[1] if len(sys.argv) > 1 else "?") + "\\n")
cmd = sys.argv[1] if len(sys.argv) > 1 else ""
if os.environ.get("T260921_STUB_NSACQUIRE_FAIL") == "1" and cmd == "ns-acquire":
    print("ENV_FAIL: 桩注入 ns-acquire 失败", file=sys.stderr)
    sys.exit(2)
if cmd == "ensure":
    print(json.dumps({"project": os.environ.get("T260921_STUB_PROJECT", "stub"),
                      "ports": {"temporal": "17233"}, "namespace": "stub-ns",
                      "sa_registered": True}))
elif cmd == "ns-acquire":
    print(json.dumps({"project": os.environ.get("SANDBAR_STAGE_BATCH", ""),
                      "namespace": "stub-ns", "ports": {"temporal": "17233"},
                      "ns_registered": True}))
else:
    print(json.dumps({"ok": True}))
sys.exit(0)
"""


def strip_batch_env():
    return {k: v for k, v in os.environ.items()
            if k not in ("SANDBAR_STAGE_BATCH", "SANDBAR_TARGET_HOST", "SANDBAR_NAMESPACE")}


def run_probe(env, ns, receipt, timeout=240):
    argv = [sys.executable, "-B", str(PROBE), ns, str(receipt)]
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                           env=env, cwd=str(REPO))
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return -9, "探针超时"


def main():
    legs = Legs("t260921-06-batch-seam-regression")
    tag = RUN_SUFFIX
    work = mkworkdir()
    have_docker = docker_ok()
    created_guard = set()
    try:
        # ---------------- 段 A：env 缺席=现行行为逐字（真台）
        if have_docker:
            # 整窗重试（看守夹具自健，房式先例=with_stage 瞬态白名单重试；消费缝
            # 本体零改动）：solo 探针的旧路起台在共租机 daemon 拥堵窗会瞬态 env 红
            # （实测=compose up 建卷被拒，stage_docker 起台失败清场零残留）——
            # 重试一次，每窗重采快照（两次尝试工程名不同，采样并集按窗独立）。
            rc = out = receipt = None
            for attempt in range(2):
                before = compose_projects_scoped()
                # 窗口采样并集（轮内轮询）：探针旧行为=用毕自拆，轮后单点 ps 看不到
                # 新工程（t260921-06 implement 段修正，与 runner-form A 段同法）
                observed = set()
                stop = threading.Event()

                def _sample():
                    while not stop.is_set():
                        now = compose_projects_scoped()
                        if now is not None and before is not None:
                            observed.update(now - before)
                        time.sleep(2)

                th_s = threading.Thread(target=_sample, daemon=True)
                th_s.start()
                rc, out = run_probe(strip_batch_env(), "t26092106-seam-a-%s" % tag,
                                    work / "ra.json")
                stop.set()
                th_s.join(timeout=30)
                receipt = None
                try:
                    receipt = json.loads((work / "ra.json").read_text(encoding="utf-8"))
                except Exception:
                    pass
                if not (rc == 2 and receipt is not None and receipt.get("ok") is False) \
                        or attempt == 1:
                    break
                print("seam-guard: A 段探针瞬态 env 红，3s 后整窗重试一次", flush=True)
                time.sleep(3)
            # 三态映射（lib_gate 契约直译）：探针 rc=2=缝内环境红（起台面供给事件；
            # 共租机拥堵瞬态在案）→ 记 env_fail 段（exit 2 全程可见），不当产品红也
            # 不吞；其余非零=产品红照旧。
            if rc == 2 and receipt is not None and receipt.get("ok") is False:
                legs.env_fail_leg("A1 旧行为探针环境红（rc=2 透传，非产品红）",
                                  "error=%s tail=%s" % (str(receipt.get("error"))[:200], out[-200:]))
            elif legs.check("A1 旧行为探针三态绿", rc == 0 and bool(receipt and receipt.get("ok")),
                            "rc=%s tail=%s" % (rc, out[-240:])):
                proj = receipt.get("project")
                created_guard.add(proj)
                legs.check("A2 env 缺席=自起独立台（mode=solo、无批注入）",
                           receipt.get("mode") == "solo" and receipt.get("batch_env") == "",
                           "receipt=%s" % str(receipt)[:240])
                legs.check("A3 独立台确实建过（窗口新现=探针工程，轮内采样）",
                           observed == {proj}, "observed=%s proj=%s" % (observed, proj))
                asz = assets_for_project(proj)
                legs.check("A4 用毕拆台零残留（容器/卷/网归零）",
                           asz == {"containers": 0, "volumes": 0, "networks": 0}, "资产=%s" % asz)
        else:
            legs.env_fail_leg("A 段（真台面）", "docker daemon 不可达")

        # ---------------- 段 B：批模式=零新建台、ns 注入、stage_down 不拆批台（真台）
        if have_docker:
            env_batch = os.environ.get("SANDBAR_STAGE_BATCH")
            owns = False
            if env_batch:
                batch = env_batch
                # gen3 修正：外层批台分支取址必须走 ns_acquire（三元组助手）。原句
                # `_, st, tail = stage_cli(...)` 把 CompletedProcess 当三元组解包——
                # 独立跑（自管分支）走不到此行，真全轮注入批 env 时第一跳即 TypeError。
                rcq, st, tail = ns_acquire(batch, "t26092106-seam-b-%s" % tag)
                port = ((st or {}).get("ports") or {}).get("temporal") if st else None
                if rcq != 0 or not port:
                    legs.env_fail_leg("B 段（外层批台取址 ns-acquire）",
                                      "rc=%s tail=%s" % (rcq, tail))
                    port = None
                addr = "127.0.0.1:%s" % port if port else None
            else:
                batch = "batch-t26092106-seam-%s" % tag
                rc, st, tail = boot_batch(batch)
                if rc != 0 or not st:
                    legs.env_fail_leg("B 段（自管批台起台 up --kind batch）", "rc=%s %s" % (rc, tail))
                    batch, addr = None, None
                else:
                    owns = True
                    created_guard.add(batch)
                    port = (st.get("ports") or {}).get("temporal")
                    addr = "127.0.0.1:%s" % port if port else None
            if batch and addr:
                envB = strip_batch_env()
                envB["SANDBAR_STAGE_BATCH"] = batch
                before = compose_projects_scoped()
                before_id = container_id("%s-temporal" % batch)
                ns_b = "t26092106-seam-b-%s" % tag
                rc, out = run_probe(envB, ns_b, work / "rb.json")
                receipt = None
                try:
                    receipt = json.loads((work / "rb.json").read_text(encoding="utf-8"))
                except Exception:
                    pass
                after = compose_projects_scoped()
                if rc == 2 and receipt is not None and receipt.get("ok") is False:
                    legs.env_fail_leg("B1 批模式探针环境红（rc=2 透传，非产品红）",
                                      "error=%s tail=%s" % (str(receipt.get("error"))[:200], out[-200:]))
                else:
                    legs.check("B1 批模式探针三态绿", rc == 0 and bool(receipt and receipt.get("ok")),
                               "rc=%s tail=%s" % (rc, out[-240:]))
                legs.check("B2 批模式零新建台（窗口零新工程）",
                           after is not None and before is not None and (after - before) == set(),
                           "新工程=%s" % (after - before if after and before else None))
                legs.check("B3 批模式 ns=场景申请值",
                           (receipt or {}).get("state", {}).get("namespace") == ns_b
                           if receipt else False,
                           "state=%s" % str((receipt or {}).get("state"))[:200])
                legs.check("B4 批模式地址=批台端口（端口不符=缝静默回落自起台形态）",
                           ((receipt or {}).get("state", {}).get("ports") or {}).get("temporal") == port
                           if receipt else False,
                           "state=%s 批台端口=%s" % (str((receipt or {}).get("state"))[:200], port))
                legs.check("B4b 批模式返回态 project=批台名（缝真指批台，非自起台）",
                           (receipt or {}).get("state", {}).get("project") == batch
                           if receipt else False,
                           "state=%s 批台=%s" % (str((receipt or {}).get("state"))[:200], batch))
                legs.check("B5 批台身份不变（stage_down 绝不拆批台）",
                           before_id == container_id("%s-temporal" % batch) and bool(before_id),
                           "before=%s after=%s" % (before_id, container_id("%s-temporal" % batch)))
                if owns:
                    rc2, _, tail2 = down_stage(batch, timeout=180)
                    gone = rc2 == 0 and all(v <= 0 for v in assets_for_project(batch).values())
                    legs.check("B6 自管批台 finally 拆台零残留", bool(gone),
                               "rc=%s 资产=%s %s" % (rc2, assets_for_project(batch), tail2[:120]))
        else:
            legs.env_fail_leg("B 段（真台面）", "docker daemon 不可达")

        # ---------------- 段 C：with_stage.sh 壳面（cwd 桩，零 docker 依赖）
        stub_root = work / "stubtree"
        (stub_root / "integration").mkdir(parents=True, exist_ok=True)
        (stub_root / "integration" / "with_stage.sh").write_bytes(
            (REPO / "integration" / "with_stage.sh").read_bytes())
        (stub_root / "integration" / "stage_docker.py").write_text(STUB, encoding="utf-8")
        lib_transient = REPO / "integration" / "lib_transient_retry.py"
        if lib_transient.exists():
            (stub_root / "integration" / "lib_transient_retry.py").write_bytes(lib_transient.read_bytes())

        def run_shell(batch_env_value, nsacquire_fail=False):
            env = {k: v for k, v in os.environ.items()
                   if k not in ("SANDBAR_STAGE_BATCH", "T260921_STUB_NSACQUIRE_FAIL")}
            stub_log = work / ("stublog_%s" % abs(hash((batch_env_value, nsacquire_fail))))
            env["T260921_STUB_LOG"] = str(stub_log)
            env["T260921_STUB_PROJECT"] = batch_env_value or "stub-batch"
            if batch_env_value:
                env["SANDBAR_STAGE_BATCH"] = batch_env_value
            if nsacquire_fail:
                env["T260921_STUB_NSACQUIRE_FAIL"] = "1"
            p = subprocess.run(["sh", "integration/with_stage.sh", "t26092106-ws-%s" % tag, "true"],
                               capture_output=True, text=True, timeout=60, env=env, cwd=str(stub_root))
            seq = stub_log.read_text(encoding="utf-8").split() if stub_log.exists() else []
            return p.returncode, seq, (p.stdout or "") + (p.stderr or "")

        rc, seq, out = run_shell("batch-t26092106-stub")
        legs.check("C1 批模式壳面：ns-acquire→跑→ns-drop，绝不 ensure/down",
                   rc == 0 and seq == ["ns-acquire", "ns-drop"], "rc=%s seq=%s out=%s" % (rc, seq, out[-160:]))
        rc, seq, out = run_shell("")
        legs.check("C2 env 缺席壳面：ensure→跑→down（现行逐字）",
                   rc == 0 and seq == ["ensure", "down"], "rc=%s seq=%s out=%s" % (rc, seq, out[-160:]))
        rc, seq, out = run_shell("batch-t26092106-stub", nsacquire_fail=True)
        legs.check("C3 ns-acquire 红=壳 exit 2 透传（不吞不改）", rc == 2, "rc=%s seq=%s" % (rc, seq))

        # ---------------- 段 D：批台护栏——--kind batch 与 --keep 互斥（usage 拒收，零 docker）
        p = stage_cli(["up", "--project", "t26092106-mutex-%s" % tag,
                       "--kind", "batch", "--keep"], timeout=60)
        legs.check("D1 --kind batch 与 --keep 互斥=拒收（usage 红）", p.returncode != 0,
                   "rc=%s out=%s" % (p.returncode, ((p.stdout or "") + (p.stderr or ""))[-200:]))
        legs.finish()
    finally:
        now = compose_projects_scoped() or set()
        mine = {n for n in now if n.startswith("batch-t26092106-") or n.startswith("t26092106-")}
        if mine:
            cleanup_projects(mine, note="t260921-06 seam-regression 收尾")
        rmworkdir(work)


if __name__ == "__main__":
    main()
