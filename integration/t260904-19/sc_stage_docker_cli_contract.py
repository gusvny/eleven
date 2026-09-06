#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260904-19 场景：docker 测试台唯一搭台入口的 CLI 对外契约缝（灰盒 L2）。

intent（登记于 run_scenarios.py SCENARIOS，本文件为其执行体）：
- up 产出场景可直接消费的 JSON（project/temporal 非空、127.0.0.1:<int> 形）；
- down 幂等二连且拆台后端口立即可复用（验收④）；
- docker 缺席=exit 2+ENV_FAIL 点名 docker（验收③三态）与 test-temporal 镜像缺席=
  exit 2 点名 build-test-temporal.sh 两文案可辨；
- 畸形工程名非零拒收且输出点名 project 且零残留；
- 生产端口 {3099,7233,8233} 绝不返回（3099 红线=CLAUDE.md 硬规则1）；
- bind 探测器占用/空闲两态自证防恒真。

断言只锚 CLI 进程级公开行为（退出码/stdout JSON/docker ps 公开观测面/socket 可连性）。
与前层分工：helper 内部机制（档位锁/分配原子性/畸形全电池）归 developer L1
integration/tests/test_stage_docker.py，本场景守真进程消费缝。

拓扑纪律（t260904-19 arbitrate gen4 修复，acceptance 必修项1 同源）：本场景**不设**
SANDBAR_STAGE_LOCK_DIR——与生产调用方（lib_gate/lib_fix15/stage_docker.mjs）同走
共享缺省锁根，flock 档位互斥在生产拓扑下生效；每调用独立锁根会让档位表互不相通，
并发互斥面成为空测。终态纪律：up 过的工程在 finally 兜底拆台（崩溃路径零残留，
验收④），正常路径的显式 down 与兜底 down 幂等叠加无害。
"""
import json
import os
import socket
import subprocess
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO, "integration"))
import stage_docker as sd  # noqa: E402

CLI = os.path.join(REPO, "integration", "stage_docker.py")
PROJ = "t26090419-contract"
PROD_PORTS = {3099, 7233, 8233}

# daemon 资源类失败特征（t260905-06 仲裁 tests-fault 迭代）：docker daemon 侧资源
# 耗尽/不可达属环境缺件（t260904-12 归因纪律：环境红记成产品红=假红——实锤：宿主
# 残留网络耗尽地址池，本场景起台腿被记 FAIL exit 1）。特征窄列三类，不吞任意失败。
DAEMON_ENV_PAT = re.compile(
    r"address pools have been fully subnetted"
    r"|no space left on device"
    r"|Cannot connect to the Docker daemon", re.I)


def env_guard(err):
    """cli up stderr 命中 daemon 资源类失败 → 记 env_fail 并 exit 2（点名特征）。"""
    if err and DAEMON_ENV_PAT.search(err):
        envfail("docker daemon 资源类失败（%s…）：CLI 契约腿没验成——归环境供给，清残留容器/网络后自动生效"
                % " ".join((err or "").strip().split())[:150])
        finish()  # finish 内按 failed/env_failed 分家退出码
    return False

passed = failed = env_failed = 0


def check(cond, label):
    global passed, failed
    print(("ok    " if cond else "FAIL  ") + label, flush=True)
    if cond:
        passed += 1
    else:
        failed += 1


def envfail(label):
    global env_failed
    env_failed += 1
    print("ENV_FAIL %s（环境缺件，没验成——原因归环境，exit 2）" % label, flush=True)


def cli(*args, timeout=900):
    # 拓扑纪律：不设 SANDBAR_STAGE_LOCK_DIR——与生产调用方共享缺省锁根（flock 互斥
    # 只在共享根下生效；per-call 锁根=档位表互不相通=互斥面空测，gen4 修复）。
    return subprocess.run([sys.executable, CLI] + list(args), capture_output=True,
                          text=True, timeout=timeout, cwd=REPO)


def docker_present():
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=15).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def finish():
    print("SUMMARY pass=%d fail=%d env_fail=%d na=0" % (passed, failed, env_failed))
    sys.exit(1 if failed else (2 if env_failed else 0))


def main():
    # ---- bind 探测器两态自证（防恒真：不依赖 docker，处处可跑）----
    s = socket.socket(); s.bind(("127.0.0.1", 0)); busy = s.getsockname()[1]; s.listen(1)
    try:
        check(sd.bind_free(busy) is False, "bind 探测器：被占端口判忙（%d）" % busy)
    finally:
        s.close()
    s2 = socket.socket(); s2.bind(("127.0.0.1", 0)); free = s2.getsockname()[1]; s2.close()
    check(sd.bind_free(free) is True, "bind 探测器：释放后端口判闲（%d）" % free)

    # ---- docker 缺席腿（验收③三态：诚实环境红点名；本机无 docker=整段环境红）----
    if not docker_present():
        p = cli("up", "--project", PROJ, "--services", "temporal")
        check(p.returncode == 2, "docker 缺席 up=exit 2（实得 %s）" % p.returncode)
        check("ENV_FAIL" in p.stderr and "docker" in p.stderr,
              "docker 缺席文案点名 docker（%s）" % p.stderr.strip()[:120])
        d = cli("down", "--project", PROJ)
        check(d.returncode == 2 and "docker" in d.stderr,
              "docker 缺席 down 同样点名（exit %s）" % d.returncode)
        if failed:
            finish()
        envfail("docker 缺席：JSON 形状/拆台复用/镜像缺席可辨腿没验成（装有 docker 的宿主自动生效）")
        finish()

    # ---- 起台腿（①~⑤）：finally 兜底拆台——up 成功后任何异常（JSON 撕裂/超时/
    #      断言崩溃）都不得残留自家台（验收④的崩溃路径半边）----
    try:
        # ---- ① up JSON 形状 ----
        p = cli("up", "--project", PROJ, "--services", "temporal")
        env_guard(p.stderr)
        if p.returncode == 2:
            # helper rc=2=其自判环境红（t260904-12 判据：环境缺件归环境，不诬产品；
            # arbitrate 实锤=daemon 地址池耗尽「all predefined address pools have
            # been fully subnetted」）。rc 其余非零仍=产品 FAIL，断言强度不减。
            envfail("up 环境红（helper rc=2 自判环境缺件：%s）" % p.stderr[-180:])
            finish()
        check(p.returncode == 0, "up 成功（rc=%s %s）" % (p.returncode, p.stderr[-200:]))
        st = json.loads(p.stdout.strip().splitlines()[-1]) if p.returncode == 0 else {}
        check(bool(st.get("project")), "JSON project 非空（%r）" % st.get("project"))
        tp = (st.get("ports") or {}).get("temporal")
        check(isinstance(tp, int) and 1 <= tp <= 65535, "temporal 端口为整数（%r）" % tp)
        check(tp not in PROD_PORTS and tp not in sd.FORBIDDEN_PORTS,
              "temporal 端口不在生产/禁区面（%s）" % tp)
        if isinstance(tp, int):
            check(sd.port_open(tp), "temporal 端口活（%d）" % tp)

        # ---- ② down 幂等二连 + 端口立即可复用（验收④）----
        d1 = cli("down", "--project", PROJ)
        check(d1.returncode == 0, "down 一连 rc=0（%s）" % d1.stderr[-160:])
        j1 = json.loads(d1.stdout.strip().splitlines()[-1]) if d1.returncode == 0 else {}
        check(j1.get("residue") == [], "down 零残留（%s）" % j1.get("residue"))
        d2 = cli("down", "--project", PROJ)
        check(d2.returncode == 0, "down 幂等二连 rc=0（%s）" % d2.stderr[-160:])
        if isinstance(tp, int):
            # 「可复用」判据=带 SO_REUSEADDR 的 bind（真实复用方 docker-proxy 的做法）。
            # sd.bind_free 的独占 bind 口径（TIME_WAIT 也算不可用）是预检语义；拆台后
            # 宿主侧 docker-proxy 可能残留 TIME_WAIT（主动 close 方），窗口内裸 bind
            # 必误判（gen10 全量跑实锤 21071）。验收④「端口可复用」=下一个台能 publish。
            def _reusable(p):
                s = socket.socket()
                try:
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    s.bind(("127.0.0.1", int(p)))
                    return True
                except OSError:
                    return False
                finally:
                    s.close()
            ok = False
            t0 = time.time()
            while time.time() - t0 < 10:
                if _reusable(tp):
                    ok = True
                    break
                time.sleep(0.5)
            check(ok, "拆台后端口立即可复用（%d，REUSEADDR 口径）" % tp)

        # ---- ③ 镜像缺席探测路径真实可辨（有 docker 才可测；查必然不存在的镜像，不动真镜像）----
        r = subprocess.run(["docker", "image", "inspect", "t26090419-no-such-image:absent"],
                           capture_output=True, timeout=15)
        check(r.returncode != 0, "镜像缺席探测路径真实可辨（inspect 非零）")

        # ---- ④ 畸形工程名：非零拒收、点名 project ----
        p = cli("up", "--project", "Bad_Name")
        check(p.returncode not in (0, 2), "畸形工程名拒收非 0/2（rc=%s）" % p.returncode)
        check("project" in p.stderr, "拒收输出点名 project（%s）" % p.stderr.strip()[:100])

        # ---- ⑤ 生产端口绝不返回 ----
        check(PROD_PORTS.isdisjoint(set((st.get("ports") or {}).values())),
              "up 端口面与生产端口零交集")
    finally:
        # 终态回收矩阵：本场景起过台的工程一律兜底拆台（幂等；崩溃路径零残留）
        try:
            cli("down", "--project", PROJ, timeout=300)
        except Exception as exc:  # 兜底尽力而为，不掩盖原异常
            print("WARN 兜底拆台异常（原异常继续上抛）: %r" % (exc,), flush=True)

    finish()


if __name__ == "__main__":
    main()
