#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260912-02 验收 G：现场清场与生产面零影响。起 1 台→拆 1 台，前后对账：
网络总数回落基线、可用网段槽回落基线、无本票残留容器、生产 3099/7233 的监听
进程全程 pid 一致（未碰）、本台端口 ∉ 禁区。
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "integration", "t260910-12"))
from lib_herd_case import (  # noqa: E402
    FORBIDDEN_PORTS, check, cli, compose_containers, docker_present, env_guard,
    envfail, finish, guarded_down, stage_tag,
)
sys.path.insert(0, os.path.join(REPO, "integration"))
import stage_docker as sd  # noqa: E402

TAG = stage_tag("t26091202-g")
ROOT = "/tmp/sandbar-t26091202-g"


def net_count():
    p = subprocess.run(["docker", "network", "ls", "-q"],
                       capture_output=True, text=True, timeout=30)
    return len([x for x in (p.stdout or "").split() if x.strip()])


def pid_of(port):
    p = subprocess.run(["lsof", "-tiTCP:%d" % port, "-sTCP:LISTEN", "-n", "-P"],
                       capture_output=True, text=True, timeout=30)
    return ",".join(sorted(x for x in (p.stdout or "").split() if x.strip()))


def main():
    if not docker_present():
        envfail("docker 缺席——清场对账不可验")
        finish()
    os.makedirs(ROOT, exist_ok=True)
    env = {"SANDBAR_STAGE_LOCK_DIR": ROOT}
    base_net = net_count()
    base_slots = len(sd.net_free_slots()[0])
    base3099, base7233 = pid_of(3099), pid_of(7233)
    print("基线：网络 %d 条 / 可用槽 %d / pid3099=%s / pid7233=%s"
          % (base_net, base_slots, base3099 or "（无监听）", base7233 or "（无监听）"),
          flush=True)
    try:
        p = cli("up", "--project", TAG, "--services", "temporal", "--timeout", "900",
                env_extra=env)
        env_guard(p.stderr, "起台腿")
        check(p.returncode == 0, "起 1 台成功（rc=%s）" % p.returncode)
        import json as _json
        st = _json.loads((p.stdout or "").strip().splitlines()[-1])
        bad_ports = {k: v for k, v in (st.get("ports") or {}).items()
                     if int(v) in FORBIDDEN_PORTS}
        check(not bad_ports, "本台端口 ∉ 禁区（%s）" % (bad_ports or "全绿"))
        dur3099, dur7233 = pid_of(3099), pid_of(7233)
        check(dur3099 == base3099, "跑动中 3099 pid 一致（%s → %s）"
              % (base3099 or "无", dur3099 or "无"))
        check(dur7233 == base7233, "跑动中 7233 pid 一致（%s → %s）"
              % (base7233 or "无", dur7233 or "无"))
    finally:
        guarded_down([TAG], env_extra=env)
    check(not compose_containers(TAG), "本台容器零残留")
    after_net, after_slots = net_count(), len(sd.net_free_slots()[0])
    check(after_net == base_net, "网络数回落基线（%d → %d）" % (base_net, after_net))
    check(after_slots == base_slots, "可用网段槽回落基线（%d → %d）"
          % (base_slots, after_slots))
    check(pid_of(3099) == base3099, "收尾 3099 pid 一致（全程未碰）")
    check(pid_of(7233) == base7233, "收尾 7233 pid 一致（全程未碰）")
    import shutil as _sh
    _sh.rmtree(ROOT, ignore_errors=True)
    finish()


if __name__ == "__main__":
    main()
