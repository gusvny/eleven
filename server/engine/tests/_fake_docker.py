# -*- coding: utf-8 -*-
"""fake docker 桩单源（t260921-05 自 test_agent_runtime.py 挪移单源化，防两份桩漂移）。

挪移纪律：FAKE_DOCKER 脚本与 FakeDocker 类正文逐字节等价（取舍清单见
.sandbar/plan_t260921-05.md §1.2.1）；仅文件头 import 与 HERE 常量为挪移适配——
类里 sandbar_exec 路径原靠 test 模块的 HERE，本模块自带同语义 HERE。
状态开关由 FAKE_DOCKER_STATE 目录文件驱动（docker-down/image-missing/containers.tsv/
inspect-error/running-*/run-fails/rm-garbage/exec-hang）；argv 全量 JSONL 落
FAKE_DOCKER_LOG（调用形状断言/零调用断言读口）。
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

FAKE_DOCKER = r'''#!/usr/bin/env python3
import json, os, signal, subprocess, sys, time
STATE = os.environ["FAKE_DOCKER_STATE"]; LOG = os.environ["FAKE_DOCKER_LOG"]
def sf(n): return os.path.join(STATE, n)
def has(n): return os.path.exists(sf(n))
def sread(n, d=""):
    try: return open(sf(n)).read().strip()
    except OSError: return d
with open(LOG, "a") as f: f.write(json.dumps(sys.argv[1:]) + "\n")
a = sys.argv[1:]
if a == ["info"]:
    sys.exit(1 if has("docker-down") else 0)
if a[:2] == ["image", "inspect"]:
    sys.exit(1 if has("image-missing") else 0)
if a[:2] == ["ps", "-a"]:
    if has("ps-hang"): time.sleep(600); sys.exit(9)   # t260921-05：gc 悬挂子用例（配超时常量收紧快测）
    out = sread("containers.tsv")
    sys.stdout.write(out + ("\n" if out else "")); sys.exit(0)
if a[:2] == ["inspect", "-f"]:
    name = a[3]
    if has("inspect-error"): sys.stderr.write("explosive daemon boom"); sys.exit(1)
    if not has("running-" + name):
        sys.stderr.write("Error: No such container: %s" % name); sys.exit(1)
    sys.stdout.write(sread("running-" + name, "true")); sys.exit(0)
if a[0] == "run":
    if has("run-fails"): sys.stderr.write("run exploded"); sys.exit(1)
    name = a[a.index("--name") + 1]
    open(sf("running-" + name), "w").write("true")
    print("fakeid-" + name); sys.exit(0)
if a[:2] == ["rm", "-f"]:
    name = a[2]
    if has("rm-hang"): time.sleep(600); sys.exit(9)   # t260921-05：remove 悬挂子用例（配超时常量收紧快测）
    if has("rm-garbage"): sys.stderr.write("rm daemon volcano"); sys.exit(1)
    if not has("running-" + name):
        sys.stderr.write("Error: No such container: %s" % name); sys.exit(1)
    os.unlink(sf("running-" + name)); sys.exit(0)
if a[0] == "exec":
    if has("exec-hang"): time.sleep(600); sys.exit(9)
    if len(a) > 2 and a[2] == "kill":
        sig = signal.SIGKILL if "KILL" in a[3] else signal.SIGTERM
        try: os.killpg(int(a[5].lstrip("-")), sig)
        except OSError: pass
        sys.exit(0)
    i = a.index("/bin/sh")
    rest = a[i + 3:]                       # $0(sandbar-exec) 之后的真参
    pgid_file, cmd = rest[1], rest[2:]
    cwd, envp, j = None, {}, 0
    while j < i:
        if a[j] == "-w": cwd = a[j + 1]; j += 2
        elif a[j] == "-e":
            k, _, v = a[j + 1].partition("="); envp[k] = v; j += 2
        else: j += 1
    # 真 docker exec 的 env 语义=镜像 ENV + (-e 参数)，不透传 docker CLI 客户端自己的
    # 进程 env——fake 基线只保留 PATH（≈镜像 ENV），红线 C 的白名单断言才有真实含义。
    env = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")}
    env.update(envp)
    rc = subprocess.run([sys.executable, os.environ["FAKE_SANDBAR_EXEC"], pgid_file] + cmd,
                        cwd=cwd, env=env).returncode
    sys.exit(rc)
sys.stderr.write("fake docker: unsupported %r" % (a[:2],)); sys.exit(64)
'''


class FakeDocker:
    def __init__(self, tmp_path, monkeypatch):
        self.state = tmp_path / "state"
        self.state.mkdir()
        self.log = tmp_path / "docker.log"
        self.bin = tmp_path / "fake-docker"
        self.bin.write_text(FAKE_DOCKER)
        self.bin.chmod(0o755)
        self.sandbox_exec = str(HERE.parent / "sandbar_exec.py")
        monkeypatch.setenv("SANDBAR_DOCKER_BIN", str(self.bin))
        monkeypatch.setenv("FAKE_DOCKER_STATE", str(self.state))
        monkeypatch.setenv("FAKE_DOCKER_LOG", str(self.log))
        monkeypatch.setenv("FAKE_SANDBAR_EXEC", self.sandbox_exec)
        # env 翻转（t260921-05，plan §1.2.1 #11=唯一行为变更）：模式闸上后，docker 形态
        # 用例必须显式钉 docker 运行模式过闸；host 形态用例不使用本夹具（裸 monkeypatch）。
        monkeypatch.setenv("SANDBAR_AGENT_RUNTIME", "docker")

    def set(self, name, val="1"):
        (self.state / name).write_text(val)

    def clear(self, name):
        try:
            (self.state / name).unlink()
        except OSError:
            pass

    def argvs(self):
        out = []
        for line in self.log.read_text().splitlines():
            out.append(json.loads(line))
        return out

    def runs(self):
        return [a for a in self.argvs() if a and a[0] == "run"]
