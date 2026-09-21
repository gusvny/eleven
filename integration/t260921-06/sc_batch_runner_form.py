#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260921-06 场景①：批台 runner 生命周期与真全轮 churn 形态（L3 看守，验收①④+要求5）。

intent（工单要求1/3/5 的用户可感知面）：
- 真全轮形态（验收①的执法面）：含台消费者的轮**恰预起 1 个批台**（batch-* 工程，
  容器/卷/网各恰 1），起止窗口内本泳道新出现的**其余** compose 工程名全部 ∈ 已知
  例外形（真全轮=例外清单 project_pattern ∪ 常驻台；本 miniature=例外形探针前缀），
  **清单外工程名出现即红**；窗口差分按 compose working_dir label 限定本泳道
  （gen1 review 条件2：并行泳道的台不计入，防看守假红常态化）；
- 消费缝注入面：批消费者条目的子进程 env 拿到 SANDBAR_STAGE_BATCH（=批台名），
  两个消费者各自命名空间（互异）同指同一批台地址；
- 每票集测段形态（exclude engine,exclusive）：**零预起零注入**——最高频路径零回归
  （方案 §L3-10「无消费者轮零建台」的动态面）；
- 全终态收口（验收④）：轮终批台拆台零残留（容器/卷/网归零）；SIGTERM 信号路径同样
  收口——拆台纪律不因批级共享改变；
- docker 缺席形态：整轮 exit 2 快速环境红（不假绿、不烧整套，等待预算封顶）。

与相邻场景 intent 分界（防 intent 级重复）：
- sc_batch_ns_isolation：守批内命名空间隔离与反用例（temporal 服务端语义面）；本条守
  runner 生命周期与资产计数形态（docker 工程面），不相交；
- sc_batch_manifest_contract：守例外清单静态契约与清点判据不变式（离线 ro）；本条守
  动态窗口形态；
- t260910-12/t260912-02/t260904-19 族：守单台机械（租约/清扫/保险丝/CLI 契约）——
  批台=一台普通租约复用其判据，本条不重复其面。

手法：假表注入（SCENARIOS 覆写后经 run_inner_runner.py 子进程直调 main()，既有
注入式电池手法，不经 INTEG_RUN_LOCK）；条目 cmd=本票探针（真消费缝/真 docker）。
实现落地前红属预期（TDD 验收门），arbitrate/merge 期必须绿；docker 缺席=ENV_FAIL exit 2。
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
    compose_projects_scoped, docker_ok, down_stage, mkworkdir, rmworkdir,
    sh, wait_until,
)

INNER = HERE / "run_inner_runner.py"
CONSUMER_PROBE = HERE / "probe_consumer.py"
EXC_PROBE = HERE / "probe_exception_stage.py"
LEG_TIMEOUT = {"A": 320, "B": 60, "C": 90, "D": 320}


def window_sampler(before, stop, interval=3.0):
    """轮内窗口采样线程（t260921-06 implement 段修正）：被观测工程（批台/例外形
    探针台）都在轮内自拆，轮后单点 `docker ps -a` 永远看不到（首跑实证 A2/A9 假红）
    ——故按 D 段同款轮询手法，取**轮内新现工程名并集**（transient 台也计入）。
    对 batch-* 工程同步记录资产计数**峰值**（A3 churn 判据「容器/卷/网各恰 1」的
    机械代理：轮终自拆后轮后恒 0，只有轮内采样可见）。
    返回 (sampler 线程, observed 集, batch 资产峰值 dict)；调用方 stop.set()+join 后读。"""
    observed = set()
    peak = {}

    def _loop():
        while not stop.is_set():
            now = compose_projects_scoped()
            if now is not None and before is not None:
                fresh = now - before
                observed.update(fresh)
                for n in fresh:
                    if n.startswith("batch-"):
                        asz = assets_for_project(n)
                        for k, v in asz.items():
                            peak[k] = max(peak.get(k, 0), v)
            time.sleep(interval)

    th = threading.Thread(target=_loop, daemon=True)
    th.start()
    return th, observed, peak


def base_env():
    """内层轮 env：剥离外层批注入（内层轮自含；外层批台先于窗口存在，不进差分）。"""
    env = {k: v for k, v in os.environ.items()
           if k not in ("SANDBAR_STAGE_BATCH", "SANDBAR_TARGET_HOST", "SANDBAR_NAMESPACE")}
    return env


def write_table(path, entries):
    Path(path).write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")


def consumer_table(work, tag, prefix):
    """两个批消费者条目（engine 池）+ 一个例外形条目。cmd 带参=探针 ns/回执路径；
    回执按段独立命名（各段「零回执」断言互不串扰）。"""
    return [
        {"name": "t26092106-fix-a", "intent": "批消费者探针 A", "pool": "engine",
         "cmd": "python3 -B %s t26092106-isa-%s %s" % (CONSUMER_PROBE, tag, work / ("%s_a.json" % prefix))},
        {"name": "t26092106-fix-b", "intent": "批消费者探针 B", "pool": "engine",
         "cmd": "python3 -B %s t26092106-isb-%s %s" % (CONSUMER_PROBE, tag, work / ("%s_b.json" % prefix))},
        {"name": "t26092106-fix-x", "intent": "例外形私有台探针", "pool": "engine",
         "cmd": "python3 -B %s %s" % (EXC_PROBE, work / ("%s_x.json" % prefix))},
    ]


def run_inner(env, table_path, exclude=None, timeout=200):
    argv = [sys.executable, "-B", str(INNER), str(table_path)]
    if exclude:
        argv.append(exclude)
    t0 = time.time()
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                           env=env, cwd=str(REPO))
        return p.returncode, (p.stdout or "") + (p.stderr or ""), time.time() - t0, None
    except subprocess.TimeoutExpired as e:
        return -9, ((e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or ""))[-800:], time.time() - t0, "内层轮超时（>%ds）" % timeout


def read_receipt(path):
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def main():
    legs = Legs("t260921-06-batch-runner-form")
    if not docker_ok():
        print("ENV_FAIL: docker daemon 不可达——本场景全段需要真 docker 台面（验收①④机械取数面）")
        sys.exit(2)
    tag = RUN_SUFFIX
    work = mkworkdir()
    created_guard = set()
    try:
        # ---------------- 段 A：真全轮形态（恰 1 批台 + 注入面 + 窗口例外形 + 收口零残留）
        tA = work / "table_a.json"
        write_table(tA, consumer_table(work, tag, "rca"))
        before = compose_projects_scoped()
        stop = threading.Event()
        th_s, observed, batch_peak = window_sampler(before or set(), stop)
        rc, out, dur, err = run_inner(base_env(), tA, timeout=LEG_TIMEOUT["A"])
        stop.set()
        th_s.join(timeout=30)
        after = compose_projects_scoped()
        # 窗口新现工程名=轮内采样并集 ∪ 轮后仍存（self-teardown 面见 window_sampler 注）
        new_projects = (set(observed)
                        | ((after - before) if (after is not None and before is not None) else set())) \
            if (before is not None) else None
        if rc == 2:
            legs.env_fail_leg("A1 内层轮环境红透传（rc=2）", "tail=%s" % out[-260:])
        elif legs.check("A1 内层轮三态绿（rc=0）", rc == 0, "rc=%s dur=%.0fs tail=%s" % (rc, dur, out[-300:])):
            batch_names = [n for n in (new_projects or []) if n.startswith("batch-")]
            if legs.check("A2 恰预起 1 个批台（batch-* 新增=1）", len(batch_names) == 1,
                          "新工程=%s" % (new_projects,)):
                batch = batch_names[0]
                created_guard.add(batch)
                # churn 判据（验收①）取轮内采样峰值——批台轮终自拆，轮后恒 0/0/0
                # （首跑实证），只有轮内采样看得到「各恰 1」的创建形态
                asz = batch_peak or assets_for_project(batch)
                legs.check("A3 批台容器/卷/网各恰 1（轮内峰值采样）",
                           asz == {"containers": 1, "volumes": 1, "networks": 1},
                           "峰值资产=%s" % asz)
                ra, rb = read_receipt(work / "rca_a.json"), read_receipt(work / "rca_b.json")
                ok_r = bool(ra and ra.get("ok")) and bool(rb and rb.get("ok"))
                if legs.check("A4 两个消费者探针全绿且回执在", ok_r, "ra=%s rb=%s" % (bool(ra), bool(rb))):
                    legs.check("A5 批注入面：env SANDBAR_STAGE_BATCH=批台名",
                               ra.get("batch_env") == batch and rb.get("batch_env") == batch,
                               "a=%r b=%r 批=%r" % (ra.get("batch_env"), rb.get("batch_env"), batch))
                    legs.check("A6 同一批台：两消费者地址相同",
                               (ra.get("state") or {}).get("ports") == (rb.get("state") or {}).get("ports"),
                               "ports a=%s b=%s" % ((ra.get("state") or {}).get("ports"),
                                                    (rb.get("state") or {}).get("ports")))
                    legs.check("A7 批内命名空间互异",
                               (ra.get("state") or {}).get("namespace") != (rb.get("state") or {}).get("namespace")
                               and (ra.get("state") or {}).get("namespace") == "t26092106-isa-%s" % tag,
                               "ns a=%s b=%s" % ((ra.get("state") or {}).get("namespace"),
                                                 (rb.get("state") or {}).get("namespace")))
                rx = read_receipt(work / "rca_x.json")
                if legs.check("A8 例外形探针全绿（私有台自管）", bool(rx and rx.get("ok")), "rx=%s" % bool(rx)):
                    created_guard.add(rx.get("project"))
                    legs.check("A9 窗口形态：新工程 ⊆ {批台}∪例外形（清单外即红的 miniature）",
                               set(new_projects or []) == {batch, rx.get("project")},
                               "新工程=%s 期望={%s, %s}" % (new_projects, batch, rx.get("project")))
                gone = wait_until(lambda: all(v == 0 for v in assets_for_project(batch).values()),
                                  60, interval=3)
                legs.check("A10 批终收口零残留（容器/卷/网归零）", bool(gone),
                           "资产=%s" % assets_for_project(batch))
        else:
            legs.env_fail_leg("A1 内层轮三态绿（rc=0）", "rc=%s tail=%s" % (rc, out[-260:]))

        # ---------------- 段 B：每票集测段形态（exclude engine,exclusive ⇒ 零预起零注入）
        tB = work / "table_b.json"
        write_table(tB, consumer_table(work, tag, "rcb")[:2])
        before = compose_projects_scoped()
        rc, out, dur, err = run_inner(base_env(), tB, exclude="engine,exclusive",
                                      timeout=LEG_TIMEOUT["B"])
        after = compose_projects_scoped()
        newb = [n for n in ((after - before) if (after is not None and before is not None) else [])
                if n.startswith("batch-")]
        legs.check("B1 每票段轮三态绿（rc=0）", rc == 0, "rc=%s tail=%s" % (rc, out[-240:]))
        legs.check("B2 零预起（batch-* 新增=0）", not newb, "新批台=%s" % newb)
        legs.check("B3 零注入（探针未运行=零回执）",
                   not (work / "rcb_a.json").exists() and not (work / "rcb_b.json").exists(),
                   "回执不应存在")
        legs.check("B4 排除面点名在案（本轮跳过池=…）", "跳过池" in out, "out 片段=%s" % out[-200:])

        # ---------------- 段 C：docker 缺席 ⇒ 整轮 exit 2 快速环境红（不烧整套）
        shim = work / "shim"
        shim.mkdir(exist_ok=True)
        (shim / "docker").write_text("#!/bin/sh\n"
                                     "echo 'shim: docker 注入缺席（t26092106 段C）' >&2\n"
                                     "exit 1\n", encoding="utf-8")
        os.chmod(str(shim / "docker"), 0o755)
        envC = base_env()
        envC["PATH"] = "%s:%s" % (shim, envC.get("PATH", ""))
        envC["SANDBAR_STAGE_WAIT_BUDGET_S"] = "3"
        tC = work / "table_c.json"
        write_table(tC, consumer_table(work, tag, "rcc"))
        rc, out, dur, err = run_inner(envC, tC, timeout=LEG_TIMEOUT["C"])
        legs.check("C1 docker 缺席整轮 exit 2（环境红不假绿）", rc == 2, "rc=%s tail=%s" % (rc, out[-240:]))
        legs.check("C2 快速红（<60s，等待预算封顶不硬等）", dur < 60, "dur=%.0fs" % dur)
        # 判别式=「无 ok=true 回执」：场景真跑成=有成功回执；环境红半途 bail 的失败回执
        # （ok=false）不算开跑（未验成≠跑过）。预起先行的快速红形态下连失败回执也不应有。
        rcc = [read_receipt(work / n) for n in ("rcc_a.json", "rcc_b.json", "rcc_x.json")]
        legs.check("C3 零场景开跑（无成功回执；预起先行形态下零回执）",
                   not any(r and r.get("ok") for r in rcc),
                   "回执=%s" % [(bool(r), (r or {}).get("ok")) for r in rcc])

        # ---------------- 段 D：SIGTERM 信号路径收口
        before = compose_projects_scoped()
        argv = [sys.executable, "-B", str(INNER), str(tA)]
        proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                env=base_env(), cwd=str(REPO))
        batch = wait_until(
            lambda: next(iter([n for n in ((compose_projects_scoped() or set()) - (before or set()))
                               if n.startswith("batch-")]), None),
            75, interval=3)
        if not legs.check("D1 预起批台在窗口内出现", bool(batch), "75s 内未见 batch-* 工程（预起面缺失）"):
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    proc.kill()
        else:
            created_guard.add(batch)
            time.sleep(2)  # 给消费者探针进入在飞窗（收口路径必须可打断）
            proc.terminate()
            try:
                proc.wait(timeout=60)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
            gone = wait_until(lambda: all(v == 0 for v in assets_for_project(batch).values()),
                              120, interval=4)
            legs.check("D2 SIGTERM 后执行器退出（≤60s）", proc.returncode is not None,
                       "rc=%s（不响应 SIGTERM=收口路径缺失）" % proc.returncode)
            legs.check("D3 信号路径收口零残留（批台容器/卷/网归零）", bool(gone),
                       "资产=%s" % assets_for_project(batch))
        legs.finish()
    finally:
        # 收尾卫生：本场景窗口内新建的批台/探针台逐工程兜底 down（看守不自己留残台）
        now = compose_projects_scoped() or set()
        mine = {n for n in now if n.startswith("batch-") or n.startswith("t26092106-")}
        if mine:
            cleanup_projects(mine, note="t260921-06 runner-form 收尾")
        rmworkdir(work)


if __name__ == "__main__":
    main()
