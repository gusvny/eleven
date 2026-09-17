#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260904-19 场景：双场景并行不互撞+拆台零残留端到端（灰盒 L3，工单验收①④）。

intent（登记于 run_scenarios.py SCENARIOS，本文件为其执行体）：
- 两个 up 进程真同时发车（各自 compose 工程名，temporal-only 档）双台健康、
  JSON 端口互异、双双 ∉ 生产端口 {3099,7233,8233}；
- docker ps -a 按 com.docker.compose.project label（compose 公开语义）过滤 A/B
  容器集互不相交且 temporal-only 恰 1 容器；
- 拆 A 后 A 端口立即可 bind 且 B 台 TCP 复测仍活（down 爆炸半径恰一个工程）；
- full 档 console+temporal 双端口真活（helper exit 2=其判环境红不诬产品）；
- 三工程终态零残留、全部用过端口立即 bind 成功（验收④收口）。

与 developer L1（档位锁/分配原子性单测，integration/tests/test_stage_docker.py）
intent 不同层：本条守进程级真并发系统行为，mock 与先后错开都替代不了该形态。
资源口径：有意制造并发双台+一次 full 台（dsh 容器首装联网分钟级），登记 exclusive
独占执行防与兄弟场景的台互相污染判定面。

拓扑纪律（t260904-19 arbitrate gen4 修复，acceptance 必修项1 同源）：两进程**不设**
SANDBAR_STAGE_LOCK_DIR——生产=所有调用方共享缺省锁根，flock 档位互斥只在共享根下
生效；每进程独立锁根=档位表互不相通，本场景「真并发不互撞」会退化为空测（竞态输了
在真 docker 下还是假红源）。终态纪律：起过的三工程在 finally 兜底拆台（JSON 撕裂/
子进程异常/断言崩溃都不得残留容器与端口，验收④的崩溃路径半边；正常路径显式 down
与兜底 down 幂等叠加无害）。
"""
import json
import os
import re
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO, "integration"))
import stage_docker as sd  # noqa: E402

PROD_PORTS = {3099, 7233, 8233}
PASSED = FAILED = ENV_FAILED = 0

# daemon 资源类失败特征（t260905-06 仲裁 tests-fault 迭代）：docker daemon 侧资源
# 耗尽/不可达属环境缺件（t260904-12 归因纪律：环境红记成产品红=假红，误导仲裁——
# 实锤：宿主 28 条残留网络耗尽地址池，本场景双 up 被记 FAIL exit 1）。特征窄列
# 三类，不吞任意 up 失败——产品缺陷导致的 up 失败仍走 FAIL 断言面。
# t260912-02 注：fully subnetted 一支自受管网段落地起**不再是活路径**（起台建网
# 显式带子网，不走分配器库存；本场景新增受管网段腿=其回归锚），保留为防御性
# 归因（手工直跑 compose/旧期残留仍可能撞池），命中照归环境红不诬产品。
DAEMON_ENV_PAT = re.compile(
    r"address pools have been fully subnetted"
    r"|no space left on device"
    r"|Cannot connect to the Docker daemon", re.I)


def env_guard(err):
    """up stderr 命中 daemon 资源类失败 → 记 env_fail 并 exit 2（点名特征）。"""
    if err and DAEMON_ENV_PAT.search(err):
        envfail("docker daemon 资源类失败（%s…）：并发/零残留/爆炸半径腿没验成——归环境供给，清残留容器/网络后自动生效"
                % " ".join((err or "").strip().split())[:150])
        print("SUMMARY pass=%d fail=%d env_fail=%d na=0" % (PASSED, FAILED, ENV_FAILED))
        sys.exit(2)
    return False


def check(cond, label):
    global PASSED, FAILED
    print(("ok    " if cond else "FAIL  ") + label, flush=True)
    if cond:
        PASSED += 1
    else:
        FAILED += 1


def envfail(label):
    global ENV_FAILED
    ENV_FAILED += 1
    print("ENV_FAIL %s（环境缺件，没验成——原因归环境，exit 2）" % label, flush=True)


def spawn_up(project, services, tag):
    # 拓扑纪律：不设 SANDBAR_STAGE_LOCK_DIR——两进程与生产调用方共享缺省锁根，
    # flock 档位互斥在真拓扑下受检（per-call 锁根=互斥面空测，gen4 修复）。
    return subprocess.Popen([sys.executable, os.path.join(REPO, "integration", "stage_docker.py"),
                             "up", "--project", project, "--services", services,
                             "--timeout", "900"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, cwd=REPO)


def cli_down(project):
    return subprocess.run([sys.executable, os.path.join(REPO, "integration", "stage_docker.py"),
                           "down", "--project", project], capture_output=True, text=True,
                          timeout=300, cwd=REPO)


def bind_reusable(port):
    """端口可复用判据：带 SO_REUSEADDR 的 bind（=真实复用方 docker-proxy 的做法）。
    拆台后宿主侧 docker-proxy 可能残留 TIME_WAIT（主动 close 方），sd.bind_free 的
    独占 bind 口径（TIME_WAIT 也算不可用，预检场景正确）在窗口内必误判——「端口可
    复用」的工程语义是下一个台能 publish 上去（带 REUSEADDR），不是裸 bind。
    返回 None=可复用，否则为失败端口诊断串。"""
    s = socket.socket()
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", int(port)))
        return None
    except OSError as e:
        return "%s(errno=%s)" % (port, e.errno)
    finally:
        s.close()


def docker_present():
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=15).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def containers_of(project):
    p = subprocess.run(["docker", "ps", "-a", "--filter",
                        "label=com.docker.compose.project=%s" % project,
                        "--format", "{{.Names}}"], capture_output=True, text=True, timeout=15)
    return sorted(x for x in (p.stdout or "").splitlines() if x.strip())


def network_subnet(project):
    """该工程 compose 默认网络的子网（inspect 公开观测面；不存在=None）。"""
    p = subprocess.run(["docker", "network", "inspect", sd.NET_NAME_FMT % project,
                        "--format", "{{(index .IPAM.Config 0).Subnet}}"],
                       capture_output=True, text=True, timeout=15)
    return (p.stdout or "").strip() if p.returncode == 0 else None


def main():
    if not docker_present():
        p = subprocess.run([sys.executable, os.path.join(REPO, "integration", "stage_docker.py"),
                            "up", "--project", "t26090419-par-probe", "--services", "temporal"],
                           capture_output=True, text=True, timeout=120, cwd=REPO)
        check(p.returncode == 2 and "docker" in p.stderr,
              "docker 缺席：up 诚实环境红点名（exit %s）" % p.returncode)
        if FAILED:
            print("SUMMARY pass=%d fail=%d env_fail=%d na=0" % (PASSED, FAILED, ENV_FAILED))
            sys.exit(1)
        envfail("docker 缺席：真并发双起/零残留/爆炸半径腿没验成（装有 docker 的宿主自动生效）")
        print("SUMMARY pass=%d fail=%d env_fail=%d na=0" % (PASSED, FAILED, ENV_FAILED))
        sys.exit(2)

    tag = str(os.getpid())
    pa, pb = "t26090419-par-a-%s" % tag, "t26090419-par-b-%s" % tag
    pf = "t26090419-par-full-%s" % tag
    try:
        procs = [spawn_up(pa, "temporal", "a"), spawn_up(pb, "temporal", "b")]
        outs = [p.communicate() for p in procs]

        states = []
        # helper rc=2=其自判环境红（t260904-12 判据：环境缺件归环境，不诬产品；
        # arbitrate 实锤=daemon 地址池耗尽「all predefined address pools have been
        # fully subnetted」）。rc 其余非零仍=产品 FAIL，断言强度不减。
        if any(proc.returncode == 2 for proc in procs):
            detail = "; ".join(
                "%s rc=%s %s" % (name, proc.returncode, (err or "").strip()[-110:])
                for (proc, (out, err)), name in zip(zip(procs, outs), ("A", "B")))
            envfail("并发 up 环境红（helper rc=2 自判环境缺件）：%s" % detail[:240])
            print("SUMMARY pass=%d fail=%d env_fail=%d na=0" % (PASSED, FAILED, ENV_FAILED))
            sys.exit(2)
        for (proc, (out, err)), name in zip(zip(procs, outs), ("A", "B")):
            env_guard(err)
            if proc.returncode == 2:
                # helper exit2=其判环境红（本文件头注既定契约「不诬产品」）：daemon 级
                # 拒绝（如网络地址池耗尽）归环境（t260904-12 三态归类），场景 exit 2
                # 而非 1；rc=0/1 口径不变（1 仍产品红）。arbitrate t260905-03 gen2 实证
                # 'all predefined address pools have been fully subnetted' 曾被误记产品红。
                envfail("并发 up %s 环境红（helper exit2：%s）" % (name, err.strip()[-160:]))
                states.append(None)
            else:
                ok = proc.returncode == 0
                check(ok, "并发 up %s 双绿（rc=%s %s）" % (name, proc.returncode, err.strip()[-160:]))
                states.append(json.loads(out.strip().splitlines()[-1]) if ok else None)

        if all(states):
            a, b = states
            check(set(a["ports"].values()).isdisjoint(set(b["ports"].values())),
                  "双台端口互异（A=%s B=%s）" % (a["ports"], b["ports"]))
            check(PROD_PORTS.isdisjoint(set(a["ports"].values()) | set(b["ports"].values())),
                  "双台端口 ∉ 生产端口")
            # namespace 口径：缺省（未显式 --namespace）两台同用契约缺省名（C5，随
            # docker-compose.test.yml 声明；t260917-07 补完终切后=sandbar-test）——隔离由
            # 「引擎互异」（端口互异=独立 temporal 进程/数据面）承担，不由 namespace 名承担；
            # 显式 namespace 互异断言归显式传参场景（族B）。
            check(a["namespace"] == b["namespace"] == "sandbar-test",
                  "双台缺省 namespace=契约缺省值 sandbar-test（隔离由引擎互异承担）")
            ca, cb = containers_of(a["project"]), containers_of(b["project"])
            check(len(ca) == 1 and len(cb) == 1, "temporal-only 各恰 1 容器（%s / %s）" % (ca, cb))
            check(not (set(ca) & set(cb)), "容器集互不相交（label 过滤面）")

            # full 档：console+temporal 双端口真活
            pf_out = subprocess.run([sys.executable, os.path.join(REPO, "integration", "stage_docker.py"),
                                     "up", "--project", pf, "--services", "full", "--timeout", "900"],
                                    capture_output=True, text=True, timeout=1200, cwd=REPO)
            if pf_out.returncode == 0:
                stf = json.loads(pf_out.stdout.strip().splitlines()[-1])
                check(sd.port_open(stf["ports"]["console"]) and sd.port_open(stf["ports"]["temporal"]),
                      "full 台 console+temporal 双端口真活")
            elif pf_out.returncode == 2:
                envfail("full 台环境红（helper exit2：%s）"
                        % (pf_out.stderr.strip()[-160:] or "环境缺件"))
            else:
                if pf_out.returncode == 2:
                    envfail("full 台起台环境红（helper rc=2 自判环境缺件，不诬产品：%s）"
                            % pf_out.stderr.strip()[-180:])
                    print("SUMMARY pass=%d fail=%d env_fail=%d na=0" % (PASSED, FAILED, ENV_FAILED))
                    sys.exit(2)
                check(False, "full 台起台（rc=%s %s）" % (pf_out.returncode, pf_out.stderr.strip()[-160:]))

            # 受管网段腿（t260912-02，验收 B 的常跑回归网）：每台网络的子网必来自
            # 受管网段表——建网不再走 docker 分配器库存，「fully subnetted」病灶
            # （260912 实测 32 台走池 23/32）的回归锚落常跑套件，不只活在票内脚本。
            managed = set(sd.net_table())
            pf_state = (json.loads(pf_out.stdout.strip().splitlines()[-1])
                        if pf_out.returncode == 0 else None)
            for st in [s for s in (a, b, pf_state) if s]:
                sub = network_subnet(st["project"])
                check(sub in managed,
                      "%s 网络子网 ∈ 受管网段表（%s；表 %d 槽）"
                      % (st["project"], sub, len(managed)))

            # 拆 A：A 端口立即可 bind、B 台仍活（爆炸半径恰一个工程）
            d = cli_down(a["project"])
            check(d.returncode == 0 and json.loads(d.stdout or "{}").get("residue") == [],
                  "拆 A 零残留（%s）" % d.stderr.strip()[-120:])
            bind_bad = None
            t0 = time.time()
            while time.time() - t0 < 10:
                bind_bad = [bad for p in a["ports"].values() if (bad := bind_reusable(p))]
                if not bind_bad:
                    break
                time.sleep(0.5)
            check(not bind_bad, "拆 A 后 A 端口立即可复用（%s）" % (bind_bad or "全可复用"))
            check(sd.port_open(b["ports"]["temporal"]), "拆 A 后 B 台 TCP 复测仍活（爆炸半径恰一工程）")

            # 终态零残留收口
            for st in (b, json.loads(pf_out.stdout.strip().splitlines()[-1]) if pf_out.returncode == 0 else None):
                if st:
                    cli_down(st["project"])
            residue = []
            for proj in (pa, pb, pf):
                residue += containers_of(proj)
            check(residue == [], "三工程终态零残留（%s）" % residue)
            all_ports = [p for st in (a, b) for p in st["ports"].values()]
            if pf_out.returncode == 0:
                all_ports += list(json.loads(pf_out.stdout.strip().splitlines()[-1])["ports"].values())
            bind_bad = [bad for p in all_ports if (bad := bind_reusable(p))]
            check(not bind_bad,
                  "全部用过端口立即复用（%d 个；不可复用=%s）" % (len(all_ports), bind_bad or "无"))
    finally:
        # 终态回收矩阵：起过的三工程一律兜底拆台（幂等；崩溃路径零残留——验收④半边）
        for proj in (pa, pb, pf):
            try:
                cli_down(proj)
            except Exception as exc:  # 兜底尽力而为，不掩盖原异常
                print("WARN 兜底拆台异常（原异常继续上抛）: %r" % (exc,), flush=True)

    print("SUMMARY pass=%d fail=%d env_fail=%d na=0" % (PASSED, FAILED, ENV_FAILED))
    sys.exit(1 if FAILED else (2 if ENV_FAILED else 0))


if __name__ == "__main__":
    main()
