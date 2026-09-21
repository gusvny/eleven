"""server/engine 单元测试包（t260902-10 测试体系 L1）。

最小 conftest：只把被测包目录加进 sys.path，无其它魔法。
运行：仓库根 `server/engine/.venv/bin/python -m pytest server/engine/tests -q`
（venv 缺失时用任一装有 pytest 的解释器；UT 全程禁网络/真 Temporal/真 git）。
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def fake_docker(tmp_path, monkeypatch):
    """fake docker 桩夹具（t260921-05）：桩单源在 _fake_docker.py，跨测试模块复用。

    docker 形态用例（容器行为验证）一律吃本夹具——桩注入 + 显式 docker 运行模式，
    不连真 daemon（见 plan §1.2.1 取舍清单 #11 的 env 翻转说明）。"""
    from _fake_docker import FakeDocker
    return FakeDocker(tmp_path, monkeypatch)


_NET_DOCKER = r'''#!/usr/bin/env python3
"""零真 docker 网桩（t260921-05）：单测会话内被意外触达的 docker 调用在此快败留痕。"""
import json, os, sys
with open(os.environ["SANDBAR_UT_NET_LOG"], "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\n")
sys.stderr.write("sandbar-ut-net: blocked docker call: %r\n" % (sys.argv[1:],))
sys.exit(72)
'''


@pytest.fixture(scope="session", autouse=True)
def _no_real_docker_net(tmp_path_factory):
    """单测面零真 docker 网（t260921-05，plan §1.3）：全会话把 SANDBAR_DOCKER_BIN 钉成
    「只记录快败桩」——argv JSONL 落日志、stderr 前缀 sandbar-ut-net、exit 72（非 1
    保留值，防与真 docker rc/stderr 语义混淆误读）——误触达立即红而非挂 30s 或假成功；
    会话收尾断言日志 0 行（不把「没跑」当「通过」的反假绿闸）。

    docker 形态用例经 fake_docker 夹具 monkeypatch 自注入桩，不经过本网；host 模式下
    容器拆/扫已被 agent_runtime 模式闸短路——任何落进本网日志的调用=意外 docker 触达
    =按 argv 点名红。前提：pytest 单进程（未上 xdist）；将来上 xdist 需改为分片日志
    聚合后再断言。
    """
    d = tmp_path_factory.mktemp("docker-net")
    log = d / "docker-calls.log"
    bin_ = d / "sandbar-ut-net-docker"
    bin_.write_text(_NET_DOCKER)
    bin_.chmod(0o755)
    saved = {k: os.environ.get(k) for k in ("SANDBAR_DOCKER_BIN", "SANDBAR_UT_NET_LOG")}
    os.environ["SANDBAR_DOCKER_BIN"] = str(bin_)
    os.environ["SANDBAR_UT_NET_LOG"] = str(log)
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        lines = log.read_text().splitlines() if log.exists() else []
        assert not lines, ("单测面出现真实 docker 调用（host 形态必须零调用；"
                           "sandbar-ut-net 记录如下，按 argv 定位调用方）：\n"
                           + "\n".join(lines[:8]))
