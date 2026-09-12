#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260912-02 场景：爆发起台阶梯×受管网段×清场与生产面零影响（灰盒 L3，
工单验收 A+B+G 的机械入口，integration 岗 design_integration_tests 段）。

intent（登记于 run_scenarios.py SCENARIOS，本文件为其执行体）：
- 并发 32 台 dsh 真台同一瞬发车：32/32 成功、单台零超时红、整批墙钟 ≤60s；
- 全部子进程 stdout/stderr 与 docker network 事件流零命中
  「fully subnetted」（地址池报错零复发），且零保险丝/满员红（缺省 100 不触闸）；
- 逐台 inspect 断言建网网段全部落在受管网段表（base /16 切 /24）内、跨台
  两两互异、且无一等于手工直跑 compose 的缺省网段（保留槽不被分配器发出）；
- 并发 48 台 temporal：每路退出码只允许 0（成功）或 2（环境红点名 STAGE_ENV）
  ——非环境类失败=产品红；成功数 ≥40；
- G 收口：起过的 80 个工程容器/网络/卷逐项零残留、全机容器数与网络数回落
  跑前基线、3099/7233 的 LISTEN pid 跑前跑后一致（生产面全程未触碰）。

与既有场景 intent 分工：t260904-19-parallel-zero-residue 锚双台隔离与爆炸
半径（N=2），t260910-12-herd-no-crosstalk 锚 N=6 风暴窗端口互斥与幂等——
本条锚 **爆发规模（32/48）下网段自管与地址池零复发**，是本票病灶三的用户级
证据，规模与断言面均不同层不互替。

资源口径：有意制造 32×dsh + 48×temporal 真台爆发（本票修复的生产级负载形态），
登记 exclusive 独占执行——地址池/保险丝判定对共机负载敏感，并发池会污染判定
面。docker/测试镜像缺席=ENV_FAIL exit 2。实现段落地前红属预期（TDD 信号），
arbitrate/merge 期必须绿。
"""
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib_lifecycle_case import (  # noqa: E402
    FORBIDDEN_PORTS,
    FUSE_MARK,
    PROD_PORTS,
    check,
    cli_async,
    compose_containers,
    compose_networks,
    compose_volumes,
    docker_present,
    env_guard,
    envfail,
    finish,
    global_counts,
    guarded_down,
    iso_root,
    last_json,
    listen_pid,
    manual_default_subnet,
    na,
    net_table,
    network_subnets,
    rm_rf,
    stage_tag,
    tcp_open,
)

TAG = stage_tag("t26091202-burst")
ROOT = iso_root("burst")
N_DSH, N_TEMP = 32, 48
BURST_WALL_BUDGET_S = 60.0
UP_TIMEOUT = 55             # 单台预算 < 整批墙钟帽：超时即「零超时」腿红
TEMP_TIMEOUT = 150
DSH_PROJS = ["%s-d%02d" % (TAG, i) for i in range(N_DSH)]
TEMP_PROJS = ["%s-t%02d" % (TAG, i) for i in range(N_TEMP)]
ALL_PROJS = DSH_PROJS + TEMP_PROJS
TCP_SPOT_CHECK = 4


def fire_batch(projects, services, timeout):
    """同一瞬并发发车、等全部落定。返回 ([(proj, rc, out, err)], 整批墙钟秒)。"""
    t0 = time.time()

    def _one(proj):
        proc = cli_async(ROOT, "up", "--project", proj, "--services", services,
                         "--timeout", timeout)
        try:
            out, err = proc.communicate(timeout=timeout + 120)
            return (proj, proc.returncode, out or "", err or "")
        except (OSError, subprocess.SubprocessError) as exc:
            return (proj, -1, "", "spawn/communicate 异常：%r" % (exc,))

    with ThreadPoolExecutor(max_workers=len(projects)) as ex:
        results = list(ex.map(_one, projects))
    return results, time.time() - t0


def assert_subnet_face(projects, table, manual_default, leg):
    """B 腿公共面：逐台网络存在、网段∈受管表、跨台互异、≠手工缺省网段。"""
    nets = {p: compose_networks(p) for p in projects}
    check(all(len(v) >= 1 for v in nets.values()),
          "%s：每台恰有 compose 建网（%d 台全有）" % (leg, len(projects)))
    observed = network_subnets([n for v in nets.values() for n in v])
    used = {}   # subnet -> 网络名（跨台互异断言面）
    missing, foreign = [], []
    for p, names in nets.items():
        for n in names:
            subs = observed.get(n) or []
            if not subs:
                missing.append(n)
            for s in subs:
                if s not in table:
                    foreign.append("%s:%s" % (n, s))
                if s in used and used[s] != n:
                    foreign.append("撞号 %s: %s vs %s" % (s, used[s], n))
                used[s] = n
    check(not missing, "%s：逐台 inspect 均可读出网段（读不出 %d 条）" % (leg, len(missing)))
    check(not foreign, "%s：网段全在受管表内且跨台两两互异（违例 %s）"
          % (leg, foreign[:4]))
    if manual_default:
        check(manual_default not in used,
              "%s：保留槽（手工缺省 %s）不被分配器发出" % (leg, manual_default))
    return set(used)


def main():
    if not docker_present():
        envfail("docker 缺席——爆发起台面不可验（启动 Docker/OrbStack 后重试）")
        finish()

    table = net_table()
    if not check(len(table) == 256,
                 "受管网段表推导=256 个 /24 槽（实得 %d）" % len(table)):
        finish()
    manual_default = manual_default_subnet()
    check(manual_default is not None,
          "compose 渲染出手工缺省网段（保留槽契约在场，实得 %r）" % manual_default)
    check(manual_default in table,
          "手工缺省网段落在受管表内（%r）" % manual_default)

    base_containers, base_networks = global_counts()
    snap_c0, snap_n0 = machine_snapshot()
    pid3099 = listen_pid(3099)
    pid7233 = listen_pid(7233)
    if pid3099 is None:
        na("3099 LISTEN pid 跑前采样（lsof 缺席或控制台未在跑）")
    if pid7233 is None:
        na("7233 LISTEN pid 跑前采样")

    events_f = tempfile.NamedTemporaryFile(prefix="sandbar-t26091202-events-",
                                           suffix=".log", delete=False)
    events_f.close()
    events = None
    try:
        events = subprocess.Popen(
            ["docker", "events", "--filter", "type=network"],
            stdout=open(events_f.name, "wb"), stderr=subprocess.DEVNULL)
        time.sleep(1.0)   # 事件流就绪窗（事件腿是 B 的证据面 belt-and-braces）

        # ---- A 腿：32×dsh 同一瞬爆发 ----
        results, wall = fire_batch(DSH_PROJS, "dsh", UP_TIMEOUT)
        for proj, _rc, _out, err in results:
            env_guard(err, "32 台起台腿 %s" % proj)
        bad = [(p, rc) for p, rc, _o, _e in results if rc != 0]
        check(not bad, "32/32 起台成功（非零 %d 台：%s）" % (len(bad), bad[:3]))
        check(wall <= BURST_WALL_BUDGET_S,
              "32 台整批墙钟 ≤60s（实得 %.1fs）" % wall)

        all_err = "\n".join(e for _p, _r, _o, e in results)
        all_out = "\n".join(o for _p, _r, o, _e in results)
        check("fully subnetted" not in (all_err + all_out),
              "B：地址池报错在 stdout/stderr 零命中")
        check(FUSE_MARK not in all_err, "零保险丝红（缺省 100 不被 32 台触发）")
        check("满员" not in all_err, "零满员字样红（排队闸已退役）")
        check("STAGE_ENV" not in all_err, "A：零环境红行（零超时）")

        states = []
        for proj, rc, out, _err in results:
            st = None
            try:
                st = json_loads_last(out)
            except Exception:
                st = None
            states.append((proj, st))
        all_ports = []
        for proj, st in states:
            ports = (st or {}).get("ports") or {}
            check(bool(ports), "%s：up JSON 带端口面" % proj)
            for v in ports.values():
                try:
                    p_int = int(v)
                except (TypeError, ValueError):
                    check(False, "%s：端口非整数 %r" % (proj, v))
                    continue
                check(p_int not in PROD_PORTS and p_int not in FORBIDDEN_PORTS,
                      "%s：端口 %d ∉ 生产/禁区面" % (proj, p_int))
                all_ports.append(p_int)
        check(len(all_ports) == len(set(all_ports)),
              "32 台端口两两互异（%d 个）" % len(all_ports))
        for proj, st in states[:TCP_SPOT_CHECK]:
            port = ((st or {}).get("ports") or {}).get("console")
            check(port and tcp_open(port),
                  "%s：console 端口可服务（抽查 %s）" % (proj, port))

        assert_subnet_face(DSH_PROJS, set(table), manual_default, "32×dsh")

        downs = guarded_down(DSH_PROJS, ROOT)
        check(all(rc == 0 for rc in downs.values()), "32 台拆台全 rc=0")
        residue = [p for p in DSH_PROJS
                   if compose_containers(p) or compose_networks(p) or compose_volumes(p)]
        check(not residue, "32 台拆台零残留（容器/网络/卷逐项空，残留 %s）" % residue[:3])

        # ---- A 腿第二阶：48×temporal，只许成功或环境红 ----
        results_t, wall_t = fire_batch(TEMP_PROJS, "temporal", TEMP_TIMEOUT)
        for proj, _rc, _out, err in results_t:
            env_guard(err, "48 台起台腿 %s" % proj)
        oks_t = [(p, rc) for p, rc, _o, _e in results_t if rc == 0]
        env_reds = [(p, rc) for p, rc, _o, e in results_t
                    if rc == 2 and "STAGE_ENV" in (e or "")]
        other = [(p, rc, (e or "")[-120:]) for p, rc, _o, e in results_t
                 if rc != 0 and not (rc == 2 and "STAGE_ENV" in (e or ""))]
        check(not other, "48 台无非环境类失败（违例 %s）" % other[:3])
        check(len(oks_t) >= 40, "48 台成功 ≥40（实得 %d，env 红 %d）"
              % (len(oks_t), len(env_reds)))
        err_t = "\n".join(e for _p, _r, _o, e in results_t)
        check("fully subnetted" not in err_t, "48 台轮地址池报错零命中")
        check(FUSE_MARK not in err_t, "48 台轮零保险丝红（100 档不被 48 触发）")
        if env_reds:
            envfail("48 台轮出现 %d 路环境红（负载敏感供给面，归环境不诬产品：%s）"
                    % (len(env_reds), env_reds[:2]))

        ports_t = []
        for proj, rc, out, _e in results_t:
            if rc != 0:
                continue
            st = json_loads_last(out)
            for v in ((st or {}).get("ports") or {}).values():
                try:
                    ports_t.append(int(v))
                except (TypeError, ValueError):
                    pass
        check(len(ports_t) == len(set(ports_t)), "48 台成功者端口两两互异")
        check(not (set(ports_t) & (PROD_PORTS | FORBIDDEN_PORTS)),
              "48 台端口 ∉ 生产/禁区面")
        assert_subnet_face([p for p, rc in oks_t], set(table), manual_default,
                           "48×temporal 成功者")

        downs_t = guarded_down(TEMP_PROJS, ROOT)
        check(all(rc == 0 for rc in downs_t.values()), "48 台拆台全 rc=0")
        residue_t = [p for p in TEMP_PROJS
                     if compose_containers(p) or compose_networks(p) or compose_volumes(p)]
        check(not residue_t, "48 台拆台零残留（残留 %s）" % residue_t[:3])

        # ---- G 收口：全机面回落基线 + 生产端口未触碰 ----
        end_containers, end_networks = global_counts()
        snap_c1, snap_n1 = machine_snapshot()
        check(no_ticket_growth(snap_c0, snap_c1),
              "G：全机新增容器零本票残留（回落基线判据；跑前 %d / 跑后 %d；%s）"
              % (base_containers, end_containers,
                 delta_detail(snap_c0, snap_c1)))
        check(no_ticket_growth(snap_n0, snap_n1),
              "G：全机新增网络零本票残留（回落基线判据；跑前 %d / 跑后 %d；%s）"
              % (base_networks, end_networks,
                 delta_detail(snap_n0, snap_n1)))
        if pid3099 is not None:
            now3099 = listen_pid(3099)
            check(now3099 == pid3099, "3099 LISTEN pid 未被触碰（%s → %s）"
                  % (pid3099, now3099))
        if pid7233 is not None:
            now7233 = listen_pid(7233)
            check(now7233 == pid7233, "7233 LISTEN pid 未被触碰（%s → %s）"
                  % (pid7233, now7233))

        if events is not None and events.poll() is None:
            events.terminate()
            try:
                events.wait(timeout=15)
            except (OSError, subprocess.SubprocessError):
                events.kill()
            events = None
        try:
            with open(events_f.name, encoding="utf-8", errors="replace") as fh:
                ev_text = fh.read()
        except OSError:
            ev_text = ""
        if ev_text.strip():
            check("fully subnetted" not in ev_text,
                  "B：docker network 事件流零地址池报错（事件 %d 字节）" % len(ev_text))
        else:
            na("docker network 事件流采样（捕获为空——观测面缺席，主断言在子进程输出腿）")
    finally:
        guarded_down(ALL_PROJS, ROOT)   # 兜底（幂等）：崩溃路径也零残留
        if events is not None and events.poll() is None:
            events.terminate()
        rm_rf(events_f.name)
    finish()


def json_loads_last(text):
    """末行 JSON（up 回报契约形状）；解析失败抛 ValueError 由调用方兜。"""
    return __import__("json").loads((text or "").strip().split("\n")[-1])


def machine_snapshot():
    """全机容器/网络的「名 → compose 工程」快照（G 腿归因用）。

    裸计数相等断言在共机多泳道窗内会被外部增量打假红（260913 首轮套件实测：
    跑前 7/7 → 跑后 10/9，增量全属他泳道工程，单跑本场景 11→11/9→9 全绿）。
    本票编造的残留必然带本票 compose 工程标签——按归属判定既不放宽也不误伤。
    """
    def _q(argv):
        p = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        out = {}
        for ln in (p.stdout or "").splitlines():
            if not ln.strip():
                continue
            name, _, proj = ln.partition("\t")
            out[name.strip()] = proj.strip()
        return out
    return (_q(["docker", "ps", "-a", "--format",
                '{{.Names}}\t{{.Label "com.docker.compose.project"}}']),
            _q(["docker", "network", "ls", "--format",
                '{{.Name}}\t{{.Label "com.docker.compose.project"}}']))


def _new_items(before, after):
    return {k: v for k, v in after.items() if k not in before}


def no_ticket_growth(before, after):
    """全机新增项里零本票归属（TAG 前缀/工程名含 TAG）=通过；有=红（真残留）。"""
    for name, proj in _new_items(before, after).items():
        if TAG in (proj or "") or TAG in name:
            return False
    return True


def delta_detail(before, after):
    """新增项点名（工程归属逐条可见——归因证据落断言行，不靠事后猜）。"""
    new = _new_items(before, after)
    if not new:
        return "无新增"
    shown = ", ".join("%s←%s" % (k, v or "无归属")
                      for k, v in sorted(new.items())[:6])
    return "新增 %d：%s%s" % (len(new), shown,
                             "…" if len(new) > 6 else "")


if __name__ == "__main__":
    main()
