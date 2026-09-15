#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t260915-18 场景共享夹具（integration 岗 design_integration_tests 段）。

三条场景（kill 回收 / 孤儿清扫半径 / inventory 映射）共用的前置与基础步骤
（岗位用例设计纪律：前置基础步骤允许共享复用，场景 intent 各不同面不互替）。

复用 t260912-02/lib_lifecycle_case.py（跨票共享先例=t260907-08 夹具跨票
import t260905-08 lib）：三态框架 / 隔离锁根 CLI / docker 公开观测面 / hold
处置 / 并行拆台兜底全部沿用，本文件只加本票增量面：

- iso_root18：本票专属隔离锁根（前缀 t26091518，避免与 02 票锁根混淆）；
- inventory：`stage_docker.py inventory` 子命令调用 + 宽容 JSON 抽取
  （工单②映射回执的唯一公开入口）；
- orphanize：真台孤儿化手术——杀 hold（防内存副本回写租约）+ 删租约文件
  =「本管域容器而无租约」形态（KI-077 当日 37 孤儿的最小可信复现）；
- foreign_container：域外观测容器注入（working_dir 标签指向仓外临时目录，
  前缀避开 `sandbar-baseline-*` 在管域白名单）——in-domain 判定的负锁样本。

灰盒纪律不变：断言只锚公开面（CLI 退出码 / stdout JSON / stderr 点名行 /
docker compose label 观测面），不锚实现内部命名。
"""
import hashlib
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
T02_LIB_DIR = os.path.join(REPO, "integration", "t260912-02")
if T02_LIB_DIR not in sys.path:
    sys.path.insert(0, T02_LIB_DIR)

from lib_lifecycle_case import (  # noqa: E402,F401  再出口：三条场景统一从这里拿
    check,
    cli,
    compose_containers,
    compose_networks,
    compose_volumes,
    craft_lease,
    docker_present,
    drop_owner,
    edit_lease,
    env_guard,
    envfail,
    extract_json,
    finish,
    guarded_down,
    hold_pids,
    kill_holds,
    kill_pid,
    last_json,
    lease_file,
    na,
    read_lease_file,
    rm_rf,
    stage_tag,
    sweep,
    up_ok,
    up_stage,
    wait_until,
)

# 孤儿清扫旋钮（本票新增面的公开契约名；前缀旋钮=本设计段新增的半径限定，
# 依据见 sc_stage_orphan_sweep.py 头注「半径限定」节）。
ENV_SWEEP_ORPHANS = "SANDBAR_STAGE_SWEEP_ORPHANS"
ENV_ORPHAN_MIN_AGE_S = "SANDBAR_STAGE_ORPHAN_MIN_AGE_S"
ENV_SWEEP_ORPHAN_PREFIX = "SANDBAR_STAGE_SWEEP_ORPHAN_PREFIX"
ENV_STAGE_TICKET = "SANDBAR_STAGE_TICKET"

# docker 公开观测面直接可用的测试镜像（verify.yaml integration supply 保证在场）。
TEST_IMAGE = "test-temporal:cli-1.8.3"


def iso_root18(slug):
    """本票专属隔离锁根：租约/锁面只在此根内，生产共享根的在飞台绝不被触碰。"""
    root = "/tmp/sandbar-t26091518-%s-%s" % (
        slug, hashlib.md5(REPO.encode("utf-8")).hexdigest()[:8])
    os.makedirs(root, exist_ok=True)
    return root


def inventory(root, timeout=120, env_extra=None):
    """`stage_docker.py inventory` 调用（工单②映射回执唯一公开入口）。
    返回 (proc, report_json_or_None)。"""
    proc = cli(root, "inventory", timeout=timeout, env_extra=env_extra or {})
    return proc, extract_json(proc.stdout or "")


def orphanize(root, project):
    """真台孤儿化手术：杀 hold（防内存副本回写）+ 删租约文件。返回是否成立。"""
    kill_holds(project, timeout=15)
    lf = lease_file(root, project)
    try:
        os.remove(lf)
    except FileNotFoundError:
        pass
    return not os.path.exists(lf)


def foreign_container(project):
    """注入一只「域外」运行容器：compose 工程标签齐全但 working_dir 指向仓外
    临时目录（前缀避开 sandbar-baseline-* 在管域白名单）。
    长命命令用镜像自带 entrypoint（/temporal server start-dev，临时 ephemeral
    server，不发布任何宿主端口=3099/7233 红线零接触）——镜像无 shell/sleep
    可假设（scratch 系），`sleep 600` 形态会秒退把 γ 负锁打成伪红（260915
    冒烟实锤）。返回 (cid, tmpdir)。"""
    outside = tempfile.mkdtemp(prefix="fgn-t26091518-")
    args = ["docker", "run", "-d",
            "--label", "com.docker.compose.project=%s" % project,
            "--label", "com.docker.compose.project.working_dir=%s" % outside,
            "--entrypoint", "/temporal", TEST_IMAGE,
            "server", "start-dev", "--log-level", "error"]
    p = subprocess.run(args, capture_output=True, text=True, timeout=120)
    cid = (p.stdout or "").strip()
    if p.returncode != 0 or not cid:
        return None, outside
    # 秒退守卫：起不来的容器（镜像/入口不符）不能当 γ 负锁样本（docker ps
    # 只看 running，秒退=伪红）。
    time.sleep(2)
    if not container_alive(cid):
        rm_foreign_container(cid)
        return None, outside
    return cid, outside


def rm_foreign_container(cid):
    if cid:
        subprocess.run(["docker", "rm", "-f", cid],
                       capture_output=True, text=True, timeout=60)


def container_alive(cid):
    if not cid:
        return False
    p = subprocess.run(["docker", "ps", "-q", "--no-trunc", "--filter",
                        "id=%s" % cid], capture_output=True, text=True,
                       timeout=30)
    return bool((p.stdout or "").strip())


def compose_project_containers_alive(project):
    """容器级存活断言面（比 compose_containers 多一层「真的还在跑」语义）。"""
    return len(compose_containers(project)) > 0
