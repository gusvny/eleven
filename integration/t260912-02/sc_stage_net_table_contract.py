#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260912-02 场景：受管网段分配的 CLI 契约缝（灰盒 L2/L3，病灶三的用户级
契约面，integration 岗 design_integration_tests 段）。

intent（登记于 run_scenarios.py SCENARIOS，本文件为其执行体）：
- 两台真台各建一网：网段全部落在受管网段表（base /16 切 /24）内且两台互异
  （分配时与在册对照防撞号的用户级证据；随机选槽不可猜不进断言——不可猜性
  无公开观测面，锁死它反而绑实现）；
- 同项目 ensure 幂等复用：reused 且建网网段**不漂移**（复用不得重新分配）；
- down 拆台后网络消失、该网段在全机 daemon 网络中不再被占用（槽位归还）；
- compose 渲染契约（手工直跑路径的保留槽）：不带 SANDBAR_TEST_SUBNET 渲染
  出缺省 ipam 子网且落在受管表内；显式注入自由槽后渲染=注入值——手工并行
  台经 env 错槽的出路在场（C8 遗留的护栏）；
- 畸形 SANDBAR_STAGE_NET_BASE：up 非零拒收（usage 档，非 0/2）、输出点名
  旋钮名、零容器产生（外部输入三态纪律：畸形拒收绝不静默回落）。

与既有场景 intent 分工：t260912-02-burst-managed-subnets 锚爆发规模下地址池
零复发（系统行为），本条锚分配器对外契约缝（单台粒度：表内/互异/不漂移/
还槽/渲染/拒收）；畸形网段底座的真值表归 developer L1（NetAllocTest），
本条只守 CLI 进程级拒收缝。docker 缺席=ENV_FAIL exit 2。实现段落地前红属
预期（TDD 信号），arbitrate/merge 期必须绿。
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib_lifecycle_case import (  # noqa: E402
    COMPOSE,
    check,
    cli as _cli,
    compose_containers,
    compose_networks,
    docker_present,
    envfail,
    finish,
    guarded_down,
    iso_root,
    last_json,
    net_table,
    network_subnets,
    stage_tag,
    tcp_open,
    up_stage,
)

TAG = stage_tag("t26091202-nettable")
ROOT = iso_root("nettable")
PA = "%s-a" % TAG
PB = "%s-b" % TAG
PC = "%s-c" % TAG
ALL = [PA, PB, PC]


def daemon_subnets():
    """全机在用网段集合（还槽断言面）。"""
    p = subprocess.run(["docker", "network", "ls", "-q"], capture_output=True,
                       text=True, timeout=60)
    ids = [x for x in (p.stdout or "").split() if x.strip()]
    if not ids:
        return set()
    out = set()
    # 逐条 inspect（数量级 ~几十，秒级）
    for nid in ids:
        q = subprocess.run(["docker", "network", "inspect", nid, "--format",
                            "{{json .IPAM.Config}}"], capture_output=True,
                           text=True, timeout=30)
        try:
            cfg = json.loads((q.stdout or "[]").strip() or "[]")
        except ValueError:
            continue
        for c in cfg if isinstance(cfg, list) else []:
            if c.get("Subnet"):
                out.add(str(c["Subnet"]))
    return out


def render_subnet(extra_env=None):
    """compose 渲染 default 网络的 ipam 子网（无 daemon 依赖）。"""
    env = dict(os.environ)
    env.pop("SANDBAR_TEST_SUBNET", None)
    env.update(extra_env or {})
    p = subprocess.run(["docker", "compose", "-f", COMPOSE,
                        "config", "--format", "json"],
                       capture_output=True, text=True, timeout=60,
                       cwd=os.path.abspath(os.path.join(
                           os.path.dirname(os.path.abspath(__file__)),
                           "..", "..")),
                       env=env)
    if p.returncode != 0:
        return None, (p.stderr or "")[-140:]
    try:
        cfg = json.loads(p.stdout or "{}")
        net = (cfg.get("networks") or {}).get("default") or {}
        for c in (net.get("ipam") or {}).get("config") or []:
            if c.get("subnet"):
                return str(c["subnet"]), ""
    except (ValueError, AttributeError):
        return None, "渲染 JSON 形状不符"
    return None, "渲染无 ipam subnet（networks 块缺席？）"


def subnets_of(project):
    names = compose_networks(project)
    observed = network_subnets(names)
    subs = []
    for n in names:
        subs.extend(observed.get(n) or [])
    return names, subs


def main():
    if not docker_present():
        envfail("docker 缺席——网段契约缝不可验（启动 Docker/OrbStack 后重试）")
        finish()

    table = set(net_table())
    if not check(len(table) == 256, "受管网段表=256 槽（实得 %d）" % len(table)):
        finish()
    try:
        # ---- 分配：两台真台，表内 + 互异 ----
        proca, st_a = up_stage(ROOT, PA, services="temporal", timeout=600)
        if not check(proca.returncode == 0, "A 台起台 rc=0"):
            finish()
        procb, st_b = up_stage(ROOT, PB, services="temporal", timeout=600)
        if not check(procb.returncode == 0, "B 台起台 rc=0"):
            finish()
        names_a, subs_a = subnets_of(PA)
        names_b, subs_b = subnets_of(PB)
        check(bool(names_a) and bool(names_b), "两台各恰有建网")
        check(all(s in table for s in subs_a + subs_b),
              "网段全部落在受管表内（A=%s B=%s）" % (subs_a, subs_b))
        check(not (set(subs_a) & set(subs_b)),
              "两台网段互异（防撞号的用户级证据）")
        port_a = (st_a or {}).get("ports", {}).get("temporal")
        check(port_a and tcp_open(port_a), "A 台可服务（%s）" % port_a)

        # ---- 复用不漂移 ----
        proc_r = _cli(ROOT, "ensure", "--project", PA, "--services", "temporal",
                      timeout=300)
        check(proc_r.returncode == 0, "同项目 ensure 幂等 rc=0")
        st_r = last_json(proc_r) or {}
        check(bool(st_r.get("reused")), "复用面 reused=true（实得 %r）"
              % st_r.get("reused"))
        _names_r, subs_r = subnets_of(PA)
        check(set(subs_r) == set(subs_a),
              "复用后网段不漂移（%s → %s）" % (subs_a, subs_r))

        # ---- 拆台还槽 ----
        procd = _cli(ROOT, "down", "--project", PA, timeout=300)
        check(procd.returncode == 0, "A 台 down rc=0")
        check(not compose_networks(PA), "A 台拆台后网络消失")
        freed = set(subs_a)
        still = daemon_subnets() & freed
        check(not still, "网段归还全机池（%s 仍被占）" % still)

        # ---- compose 渲染契约（手工直跑路径的保留槽）----
        rendered, why = render_subnet()
        check(rendered is not None and rendered in table,
              "缺省渲染出保留槽网段且∈受管表（实得 %r%s）"
              % (rendered, ("；" + why) if why else ""))
        free_slot = None
        used_now = daemon_subnets()
        for slot in sorted(table):
            if slot not in used_now and slot != rendered:
                free_slot = slot
                break
        if check(free_slot is not None, "找到自由槽做注入渲染腿（%s）" % free_slot):
            rendered2, why2 = render_subnet({"SANDBAR_TEST_SUBNET": free_slot})
            check(rendered2 == free_slot,
                  "显式注入自由槽后渲染=注入值（实得 %r%s）"
                  % (rendered2, ("；" + why2) if why2 else ""))

        # ---- 畸形 base：usage 档拒收 + 点名旋钮 + 零容器 ----
        proc_m = _cli(ROOT, "up", "--project", PC, "--services", "temporal",
                      timeout=300,
                      env_extra={"SANDBAR_STAGE_NET_BASE": "10.213.0.0/99"})
        check(proc_m.returncode not in (0, 2),
              "畸形网段底座按 usage 档拒收（rc=%s，非 0/2）" % proc_m.returncode)
        check("NET_BASE" in ((proc_m.stderr or "") + (proc_m.stdout or "")),
              "拒收输出点名 SANDBAR_STAGE_NET_BASE 旋钮")
        check(not compose_containers(PC), "畸形底座下零容器产生")
    finally:
        guarded_down(ALL, ROOT)
    finish()


if __name__ == "__main__":
    main()
