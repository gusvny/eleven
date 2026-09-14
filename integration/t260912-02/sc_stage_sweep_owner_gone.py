#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260912-02 场景：残台按主人存在性自动认领并拆——判定矩阵与负锁（灰盒 L3，
工单验收 C 的机械入口，integration 岗 design_integration_tests 段）。

intent（登记于 run_scenarios.py SCENARIOS，本文件为其执行体）：
- 注入五种残台形态，清扫必须全拆（容器+网络+卷逐项空）并在报告里逐条点名：
  (i)   compose 工作目录已删（真实台，容器/网络/卷俱在）；
  (i-a) 工作目录已删 + 持有者 pid 活 + 心跳新鲜（合成租约）——主人已死才是
        判据，pid 活与心跳新鲜都救不了（260912 残台形态：hold 活→租约永新鲜）；
  (ii)  泳道不在 git worktree list（owner_root 指向存在但非工作树的目录），
        杀 hold 后注入——lane 消失的自然余象就是锚死→hold ③ 自终止；
  (iii) 心跳陈旧超阈（合成租约，2h 前）且持有者 pid 活——pid 活只是辅证；
  (v)   legacy 旧格式（无 owner_root，repo_dir 指向已删目录）——260912 存量
        残台形态，按回落锚判拆；
- 注入四种**不得误拆**的对照（负锁，防判据恒真）：
  (α)   state=booting 且心跳新鲜且 owner 非工作树（hold 已死）——只有
        「booting 安全阀」救它（阀1 不看 holder 存活：起台中 hold 本就未接管）；
  (β)   泳道在 worktree list 的健康台（hold 活、心跳自然新鲜）——零接触；
  (iv)  legacy 旧格式 + repo_dir 指向存在但非工作树目录 + hold 活+心跳新鲜
        ——C4b fail-closed 不拆只留报告行（活台+锚存疑=保守放行）；
  (iv-b) 新格式同形态（hold 活+心跳新鲜+owner_root 非工作树）——C4b 不限
        legacy，crit_ii 对活台一律 fail-closed；
- `sweep --dry-run` 只认领不拆：点名被判拆集合，但真实台的容器仍在；
- 起台时挂点行为证明：再造一条残台后正常 `up` 新工程——新台健康的同时旧残台
  被顺手拆掉（起台时扫一遍的用户级证据），且健康对照台原封不动；
- 清扫二连幂等（第二遍 rc=0）。

与既有场景 intent 分工：t260910-12-holder-kill-reclaim 锚「租约过期 AND 持有者
进程消失」的判死回收（hold 被杀才触发）；本条锚 **hold 活着也拆得主**的主人
存在性清道夫（本票病灶二），判据面不同不互替。租约四象限断言原样在
test_stage_lease.py（L1），本条不重复其象限。合成租约一律用生产 TTL（90s，
hold 实写值）：阀2/C4b 的「新鲜」按租约 TTL 判（实测），长 TTL 注入会让
crit_iii 形态溜进阀2——注入贴近生产形态才测得出真行为。

注入面=租约状态面手术（工单验收 C 明令「手工改租约制造形态」）。docker 缺席
=ENV_FAIL exit 2。
"""
import os
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib_lifecycle_case import (  # noqa: E402
    BeatKeeper,
    check,
    compose_containers,
    compose_networks,
    compose_volumes,
    craft_lease,
    docker_present,
    edit_lease,
    envfail,
    finish,
    guarded_down,
    hold_pids,
    iso_root,
    kill_holds,
    kill_holder,
    read_lease_file,
    rm_rf,
    sleep_holder,
    stage_tag,
    sweep,
    tcp_open,
    up_batch_env_only,
    up_ok,
    up_stage,
)

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
TAG = stage_tag("t26091202-sweep")
ROOT = iso_root("sweep")

P_DEL = "%s-del" % TAG           # (i)   真台·工作目录已删
P_DEL_SYNTH = "%s-dsynth" % TAG  # (i-a) 合成·目录删+pid活+心跳新鲜
P_LANE = "%s-lane" % TAG         # (ii)  真台·泳道不在 worktree list（hold 已死）
P_STALE = "%s-stale" % TAG       # (iii) 合成·心跳陈旧+pid活
P_LEGACY = "%s-legacy" % TAG     # (v)   真台·legacy+repo_dir 已删
P_BOOT = "%s-boot" % TAG         # (α)   真台·booting 新鲜（阀1 负锁）
P_LIVE = "%s-live" % TAG         # (β)   真台·在册健康（阀2 负锁）
P_LEGIT = "%s-legit" % TAG       # (iv)  真台·legacy+repo_dir 在但非工作树（C4b 负锁）
P_LEGIT_SYNTH = "%s-legsyn" % TAG  # (iv-b) 合成·新格式活台 C4b 负锁
P_HOOK = "%s-hook" % TAG         # 起台时挂点用残台
P_NEW = "%s-new" % TAG           # 挂点腿的正常新台

REAL_PROJS = [P_DEL, P_LANE, P_LEGACY, P_BOOT, P_LIVE, P_LEGIT, P_HOOK]
CONDEMNED = [P_DEL, P_DEL_SYNTH, P_LANE, P_STALE, P_LEGACY]
STALE_AGE_S = 7200.0            # 2h ≫ 缺省阈 600s，旋钮无关


def boot_batch(projects):
    """并行起真台（temporal-only），返回 {proj: (proc, state_json)}。"""

    def _one(proj):
        proc, st = up_stage(ROOT, proj, services="temporal", timeout=600)
        return (proj, proc, st)

    with ThreadPoolExecutor(max_workers=4) as ex:
        return {proj: (proc, st) for proj, proc, st in ex.map(_one, projects)}


def make_gone_dir():
    d = tempfile.mkdtemp(prefix="sandbar-t26091202-gone-")
    rm_rf(d)
    return d


def make_foreign_dir():
    """存在但非 git 工作树的目录（泳道已不在 worktree list 的镜像形态）。"""
    return tempfile.mkdtemp(prefix="sandbar-t26091202-foreign-")


def assert_torn(root, proj, leg):
    check(not compose_containers(proj), "%s：%s 容器零残留" % (leg, proj))
    check(not compose_networks(proj), "%s：%s 网络零残留" % (leg, proj))
    check(not compose_volumes(proj), "%s：%s 卷零残留" % (leg, proj))
    check(read_lease_file(root, proj) is None, "%s：%s 租约已释放" % (leg, proj))


def assert_intact(root, proj, ports, leg, want_state=None, want_hold=False):
    check(len(compose_containers(proj)) >= 1, "%s：%s 容器原封不动" % (leg, proj))
    check(read_lease_file(root, proj) is not None, "%s：%s 租约仍在册" % (leg, proj))
    port = (ports or {}).get("temporal")
    check(port and tcp_open(port), "%s：%s 台仍可服务（%s）" % (leg, proj, port))
    if want_state:
        st = (read_lease_file(root, proj) or {}).get("state")
        check(st == want_state, "%s：%s 租约 state 保持 %s（实得 %r）"
              % (leg, proj, want_state, st))
    if want_hold:
        check(len(hold_pids(proj)) >= 1, "%s：%s 持有腿仍在跑（零接触）"
              % (leg, proj))


def main():
    if not docker_present():
        envfail("docker 缺席——残台清扫面不可验（启动 Docker/OrbStack 后重试）")
        finish()

    gone_i = make_gone_dir()            # 已删目录（(i)/(i-a) 用）
    gone_v = make_gone_dir()            # 已删目录（(v) 用）
    gone_hook = make_gone_dir()         # 已删目录（挂点腿用）
    foreign_lane = make_foreign_dir()   # 存在但非工作树（(ii) 用）
    foreign_legit = make_foreign_dir()  # 存在但非工作树（(iv) 用）
    foreign_live = make_foreign_dir()   # 存在但非工作树（(iv-b) 用）
    holder_stale = sleep_holder()       # (iii) 活 pid
    holder_dsynth = sleep_holder()      # (i-a) 活 pid
    holder_legsyn = sleep_holder()      # (iv-b) 活 pid
    keeper = None
    try:
        # ---- 起真台 + 状态面手术 ----
        batch1 = boot_batch([P_DEL, P_LANE, P_LEGACY, P_BOOT])
        batch2 = boot_batch([P_LIVE, P_LEGIT, P_HOOK])
        booted = dict(batch1)
        booted.update(batch2)
        failed_boot = [p for p in REAL_PROJS
                       if (booted.get(p) or (None, None))[0].returncode != 0]
        if failed_boot:
            # t260913-01 仲裁修（同族补齐，与 net_table 同口径）：批量起台失败按引擎
            # 自报档位归类——全为 env(2)/conflict(3) ⇒ ENV_FAIL（prepare 型环境/并发面，
            # 带每台 rc 证据，not-checked）；任一为 fail(1)/usage(64) ⇒ FAIL（产品/契约面）。
            # 原实现一律记 FAIL＝三态协议违约；并发窗实测 7 台里 3 台起不来（260914）。
            rcs = {p: (booted.get(p) or (None, None))[0].returncode for p in failed_boot}
            if up_batch_env_only(rcs):
                envfail("7 台真台全部起好：%d 台起台失败（rc 档位全为 env/conflict"
                        "＝prepare 型环境/并发面，非产品红）：%s"
                        % (len(failed_boot), rcs))
                finish()
            if not check(False, "7 台真台全部起好（失败 %s，rc=%s：含非 env/conflict 档"
                                "＝产品/契约面）" % (failed_boot, rcs)):
                finish()
        ports = {p: ((booted.get(p) or (None, {}))[1] or {}).get("ports") or {}
                 for p in REAL_PROJS}

        # 手术 1：真实残台（杀 hold——hold 活着会以读改写心跳冲掉手术判据）。
        # P_LEGIT 例外：C4b 负锁要求活台（hold 活+心跳新鲜），hold 保留。
        for proj in [P_DEL, P_LANE, P_LEGACY, P_BOOT, P_HOOK]:
            kill_holds(proj)
        edit_lease(ROOT, P_DEL, lambda d: {**d, "owner_root": gone_i})
        edit_lease(ROOT, P_LANE, lambda d: {**d, "owner_root": foreign_lane})
        edit_lease(ROOT, P_LEGACY,
                   lambda d: dict({k: v for k, v in d.items()
                                   if k != "owner_root"}, repo_dir=gone_v))
        edit_lease(ROOT, P_BOOT, lambda d: {**d, "state": "booting",
                                            "owner_root": foreign_lane})
        # (iv)：hold 活着 → 读改写保留其它字段，只换锚（legacy 形态）
        edit_lease(ROOT, P_LEGIT,
                   lambda d: dict({k: v for k, v in d.items()
                                   if k != "owner_root"},
                                  repo_dir=foreign_legit))
        # 手术 2：合成形态（生产 TTL=hold 实写值 90s，贴近生产租约形状）
        craft_lease(ROOT, P_DEL_SYNTH, state="up", holder_pid=holder_dsynth.pid,
                    owner_root=gone_i)
        craft_lease(ROOT, P_STALE, state="up", holder_pid=holder_stale.pid,
                    heartbeat_ts=time.time() - STALE_AGE_S, owner_root=str(REPO))
        craft_lease(ROOT, P_LEGIT_SYNTH, state="up",
                    holder_pid=holder_legsyn.pid, owner_root=foreign_live)
        # 场景侧心跳保持（真实残台形态=心跳新鲜但主人已死；清扫可长达分钟级，
        # TTL 只有 90s——不保持则判据会漂成「过期」污染归因）
        keeper = BeatKeeper(ROOT, [P_DEL, P_LANE, P_LEGACY, P_BOOT, P_HOOK,
                                   P_DEL_SYNTH, P_LEGIT_SYNTH]).start()

        # ---- dry-run：认领不拆 ----
        proc_d, report_d = sweep(ROOT, "--dry-run", timeout=180)
        check(proc_d.returncode == 0, "sweep --dry-run rc=0（实得 %s）"
              % proc_d.returncode)
        check(report_d is not None, "清扫报告为可解析 JSON（dry-run）")
        out_d = proc_d.stdout or ""
        missing = [p for p in CONDEMNED if p not in out_d]
        check(not missing, "dry-run 逐条点名被判拆残台（缺 %s）" % missing)
        check(len(compose_containers(P_DEL)) >= 1,
              "dry-run 只认领不拆（%s 容器仍在）" % P_DEL)

        # ---- 真清扫：全拆 + 逐条点名 ----
        proc_s, report_s = sweep(ROOT, timeout=300)
        check(proc_s.returncode == 0, "sweep rc=0（实得 %s，stderr=%s）"
              % (proc_s.returncode, (proc_s.stderr or "")[-160:]))
        out_s = proc_s.stdout or ""
        named_missing = [p for p in CONDEMNED if p not in out_s]
        check(not named_missing, "清扫报告逐条点名（缺 %s）" % named_missing)
        if report_s is None:
            check(False, "清扫报告为可解析 JSON（实得 stdout 尾部 %r）"
                  % (proc_s.stdout or "")[-160:])
        else:
            vals = _json_values(report_s)
            check(all(p in vals for p in CONDEMNED),
                  "报告 JSON 树含全部被判拆工程名")
        assert_torn(ROOT, P_DEL, "(i) 工作目录已删")
        assert_torn(ROOT, P_LANE, "(ii) 泳道不在 worktree list")
        assert_torn(ROOT, P_LEGACY, "(v) legacy+repo_dir 已删")
        check(read_lease_file(ROOT, P_DEL_SYNTH) is None,
              "(i-a) 合成残台（pid 活+心跳新鲜+目录删）被判拆并释放")
        check(read_lease_file(ROOT, P_STALE) is None,
              "(iii) 心跳陈旧+pid 活被判拆并释放（pid 只是辅证）")

        # ---- 负锁：四个对照原封不动 ----
        assert_intact(ROOT, P_BOOT, ports.get(P_BOOT), "(α) booting 新鲜阀",
                      want_state="booting")
        assert_intact(ROOT, P_LIVE, ports.get(P_LIVE), "(β) 在册健康阀",
                      want_hold=True)
        assert_intact(ROOT, P_LEGIT, ports.get(P_LEGIT),
                      "(iv) legacy 活台 fail-closed", want_hold=True)
        check(P_LEGIT in out_s, "(iv)：fail-closed 不拆但报告留痕点名")
        check(read_lease_file(ROOT, P_LEGIT_SYNTH) is not None,
              "(iv-b) 新格式活台 fail-closed 租约仍在册")
        check(P_LEGIT_SYNTH in out_s, "(iv-b)：fail-closed 留痕点名")

        # ---- 起台时挂点：新台 up 顺手拆掉再造残台 ----
        edit_lease(ROOT, P_HOOK, lambda d: {**d, "owner_root": gone_hook})
        proc_n, st_n = up_stage(ROOT, P_NEW, services="temporal", timeout=600)
        if not up_ok(proc_n, "挂点腿新台 up 成功（rc=%s）"
                     % proc_n.returncode):
            finish()
        check(not compose_containers(P_HOOK) and not compose_networks(P_HOOK),
              "起台时扫一遍：%s 残台被顺手拆掉" % P_HOOK)
        check(read_lease_file(ROOT, P_HOOK) is None, "挂点腿残台租约已释放")
        port_new = (st_n or {}).get("ports", {}).get("temporal")
        check(port_new and tcp_open(port_new), "挂点腿新台可服务（%s）" % port_new)
        assert_intact(ROOT, P_LIVE, ports.get(P_LIVE), "挂点腿不误伤健康台")
        check(len(compose_containers(P_BOOT)) >= 1
              and read_lease_file(ROOT, P_BOOT) is not None,
              "挂点腿不误伤 booting 对照台")

        # ---- 幂等二扫 ----
        proc_s2, _r2 = sweep(ROOT, timeout=180)
        check(proc_s2.returncode == 0, "清扫二连幂等 rc=0")

        # ---- 清场 ----
        keeper.stop()
        keeper = None
        downs = guarded_down([p for p in REAL_PROJS + [P_NEW]], ROOT)
        bad_down = {p: rc for p, rc in downs.items() if rc != 0}
        check(not bad_down, "终态兜底拆台全 rc=0（违例 %s）" % bad_down)
    finally:
        if keeper is not None:
            keeper.stop()
        kill_holder(holder_stale)
        kill_holder(holder_dsynth)
        kill_holder(holder_legsyn)
        guarded_down(REAL_PROJS + [P_NEW], ROOT)
        rm_rf(foreign_lane)
        rm_rf(foreign_legit)
        rm_rf(foreign_live)
        for p in (P_DEL, P_DEL_SYNTH, P_LANE, P_STALE, P_LEGACY, P_BOOT,
                  P_LEGIT_SYNTH, P_HOOK):
            try:
                os.remove(os.path.join(ROOT, "project-%s.json" % p))
            except OSError:
                pass
    finish()


def _json_values(obj):
    """JSON 树全部字符串值（点名断言不锚报告字段名——格式漂移不破断言）。"""
    out = set()
    if isinstance(obj, dict):
        for v in obj.values():
            out |= _json_values(v)
    elif isinstance(obj, list):
        for v in obj:
            out |= _json_values(v)
    elif isinstance(obj, str):
        out.add(obj)
    return out


if __name__ == "__main__":
    main()
