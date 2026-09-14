#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260912-02 场景：常驻租约在场时并发起台不再自我挤压（灰盒 L3，工单验收 F
的机械入口，integration 岗 design_integration_tests 段）。

intent（登记于 run_scenarios.py SCENARIOS，本文件为其执行体）：
- 在册 6 条常驻形态租约（在飞票控制台台/供给台的镜像面：state=up、keep、
  持有者进程活、心跳由场景侧持续续鲜、主人=本仓工作树）在场的前提下，
  并发 16 台 temporal 真台 ensure 发车：16/16 全绿、端口两两互异、全部
  ∉ 生产/禁区面、全程零保险丝红——常驻台不再挤掉场景台的名额（病灶一的
  用户级证据：旧满员闸把常驻计入 12 的名额正是自挤根源）；
- 6 条常驻租约在 16 台风暴后原封不动（租约在册、持有者进程仍活）；
- 风暴台终态零残留。

注入面=租约状态面（与真实常驻台对保险丝计数不可区分——计数只认租约不认
容器）。与 t260912-02-fuse-runaway-named-stop intent 分工：彼锚超限刹停
（失控循环被点名），本条锚限额内的名额不被常驻吃掉（正常负载永不触闸），
正反两面不互替。与 t260910-12-herd-no-crosstalk（N=6 端口互斥+幂等）不同
层：本条锚「常驻在场」这一床位前提。登记 exclusive：16 路并发 compose-up
是本票修复宣称的生产级负载，独占执行保判定面不被并发池污染。docker 缺席
=ENV_FAIL exit 2。实现段落地前红属预期（TDD 信号），arbitrate/merge 期必须绿。
"""
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib_lifecycle_case import (  # noqa: E402
    BeatKeeper,
    FORBIDDEN_PORTS,
    FUSE_MARK,
    PROD_PORTS,
    check,
    cli_async,
    craft_lease,
    docker_present,
    env_guard,
    envfail,
    extract_json,
    finish,
    guarded_down,
    iso_root,
    kill_holder,
    read_lease_file,
    sleep_holder,
    stage_tag,
    up_batch_env_only,
)

TAG = stage_tag("t26091202-headroom")
ROOT = iso_root("headroom")
N_RESIDENT = 6
N_BURST = 16
RESIDENTS = ["%s-r%02d" % (TAG, i) for i in range(N_RESIDENT)]
BURST = ["%s-b%02d" % (TAG, i) for i in range(N_BURST)]
ALL = RESIDENTS + BURST


def main():
    if not docker_present():
        envfail("docker 缺席——名额不挤压面不可验（启动 Docker/OrbStack 后重试）")
        finish()

    holders = []
    keeper = None
    try:
        # ---- 注入 6 条常驻形态租约（hold 镜像面：pid 活 + 心跳续鲜 + keep；
        # TTL/心跳按生产 hold 实写值，场景侧 BeatKeeper 续鲜）----
        for proj in RESIDENTS:
            hproc = sleep_holder()
            holders.append(hproc)
            craft_lease(ROOT, proj, state="up", holder_pid=hproc.pid,
                        keep=True, services=["dsh"],
                        owner_root=os.path.abspath(
                            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "..", "..")))
        keeper = BeatKeeper(ROOT, RESIDENTS, gap=2.0).start()
        alive = [p for p in RESIDENTS if read_lease_file(ROOT, p) is not None]
        if not check(len(alive) == N_RESIDENT, "6 条常驻租约注入在册"):
            finish()

        # ---- 16 台并发 ensure：名额不被常驻吃掉 ----
        t0 = time.time()

        def _one(proj):
            proc = cli_async(ROOT, "ensure", "--project", proj,
                             "--services", "temporal", "--timeout", "300")
            try:
                out, err = proc.communicate(timeout=420)
                return (proj, proc.returncode, out or "", err or "")
            except Exception as exc:   # 执行器杀死等：按产品红记录，不吞
                return (proj, -1, "", "异常 %r" % (exc,))

        with ThreadPoolExecutor(max_workers=N_BURST) as ex:
            results = list(ex.map(_one, BURST))
        wall = time.time() - t0
        for proj, _rc, _out, err in results:
            env_guard(err, "16 台起台腿 %s" % proj)
        oks = [(p, rc) for p, rc, _o, _e in results if rc == 0]
        nonzero = [(p, rc) for p, rc, _o, _e in results if rc != 0]
        # t260913-01 仲裁修（同族第 5 例，与 up_ok 同口径单源）：起台腿 rc 档位归类——
        # 非零全为 env(2)/conflict(3) ⇒ ENV_FAIL（prepare 型环境/并发面，not-checked，
        # 点名每台 rc）；含 fail(1)/usage(64)/执行器杀(-1) ⇒ FAIL（产品/契约面）。
        # 原实现一律 check(len(oks)==N) ⇒ 环境拒跑被记产品红（260914 实测 16 台里 2 台 rc=2）。
        if nonzero and up_batch_env_only({p: rc for p, rc in nonzero}):
            envfail("16 台并发起台未验成：%d 台 rc 档位全为 env/conflict（prepare 型环境/"
                    "并发面，非产品红）：%s" % (len(nonzero), nonzero[:4]))
        else:
            check(len(oks) == N_BURST, "16/16 全绿（实得 %d，非零 %s）"
                  % (len(oks), nonzero[:3]))
        all_err = "\n".join(e for _p, _r, _o, e in results)
        check(FUSE_MARK not in all_err,
              "全程零保险丝红（缺省 100 档，6 常驻+16 场景=22 活租约远不触闸）")
        check("fully subnetted" not in all_err, "地址池报错零命中")
        ports = []
        for proj, rc, out, _e in results:
            if rc != 0:
                continue
            st = extract_json(out) or {}
            for v in (st.get("ports") or {}).values():
                try:
                    ports.append(int(v))
                except (TypeError, ValueError):
                    pass
        check(len(ports) == len(set(ports)), "16 台端口两两互异（%d 个）" % len(ports))
        check(not (set(ports) & (PROD_PORTS | FORBIDDEN_PORTS)),
              "端口 ∉ 生产/禁区面")
        check(wall <= 240, "16 台墙钟有界（%.0fs）" % wall)

        # ---- 常驻原封不动 ----
        still = [p for p in RESIDENTS if read_lease_file(ROOT, p) is not None]
        check(len(still) == N_RESIDENT, "风暴后 6 条常驻租约全在册（实得 %d）"
              % len(still))
        alive_holders = sum(1 for h in holders if h.poll() is None)
        check(alive_holders == N_RESIDENT,
              "常驻持有者进程零误伤（%d/%d）" % (alive_holders, N_RESIDENT))

        # ---- 清场 ----
        downs = guarded_down(BURST, ROOT)
        check(all(rc == 0 for rc in downs.values()), "风暴台终态拆台全 rc=0")
    finally:
        if keeper is not None:
            keeper.stop()
        for hproc in holders:
            kill_holder(hproc)
        for proj in RESIDENTS:
            try:
                os.remove(os.path.join(ROOT, "project-%s.json" % proj))
            except OSError:
                pass
        guarded_down(ALL, ROOT)
    finish()


if __name__ == "__main__":
    main()
