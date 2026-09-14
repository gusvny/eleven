# -*- coding: utf-8 -*-
"""agent_runtime 容器执行面单测（t260913-04 方案 D1–D9；review C4/C6/R8 注入面）。

fake docker：以 SANDBAR_DOCKER_BIN 注入一个 stdlib 桩——argv 全量落日志、状态由
FAKE_DOCKER_STATE 目录控制；exec 分支用【真 sandbar_exec】回放 supervisor 契约
（pgid 档/组信号全走真路径），kill 形态在宿主侧真 killpg。

覆盖：ensure 白名单等值与自愈/重建/门（docker 缺、镜像缺、main 拒）、exec env 白名单
（DSH_PERMISSION_MODE 结构性禁入——红线 C 单元面）、reap 五终态（幂等/容器不在/
pgid 坏档/inspect 报错容忍/有界升级 KILL）、remove 幂等、gc 孤儿、版本三处同步、
agent_activities 接线守卫（三点 spawn、零直 Popen、reap 全走 AgentProc）。
"""
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import agent_runtime as ar  # noqa: E402

PY = sys.executable
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
        monkeypatch.delenv("SANDBAR_AGENT_RUNTIME", raising=False)

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


@pytest.fixture
def fake(tmp_path, monkeypatch):
    return FakeDocker(tmp_path, monkeypatch)


LANE = None  # 由各测试建


def _lane(tmp_path):
    lane = tmp_path / "lane-t1"
    lane.mkdir()
    return lane


# ---- ensure_container ----

def test_ensure_挂载面白名单等值_仅泳道一项(tmp_path, fake):
    lane = _lane(tmp_path)
    ar.ensure_container("t1", lane)
    run = fake.runs()[-1]
    mounts = [v for k, v in zip(run, run[1:]) if k == "-v"]
    assert mounts == ["%s:%s" % (lane, lane)], "挂载面必须恰好=泳道一项（红线2/C4）"
    assert "--privileged" not in run and "--cap-add" not in run
    assert "--pid=host" not in run and "--network=host" not in run
    assert "--user" in run, "属主对齐（R4）"
    assert run[run.index("--user") + 1] == "%d:%d" % (os.getuid(), os.getgid())
    assert "sleep" in run and "infinity" in run


def test_ensure_幂等复用_停容器自愈重建(tmp_path, fake):
    lane = _lane(tmp_path)
    name = ar.container_name_for("t1")
    ar.ensure_container("t1", lane)
    ar.ensure_container("t1", lane)
    assert len(fake.runs()) == 1, "running 容器必须复用不重建"
    fake.set("running-" + name, "false")
    ar.ensure_container("t1", lane)
    ops = [a[:2] for a in fake.argvs()]
    assert ["rm", "-f"] in ops and len(fake.runs()) == 2, "停容器拆了重建"


def test_ensure_镜像缺_fail_closed点名构建命令(tmp_path, fake):
    fake.set("image-missing")
    with pytest.raises(ar.AgentRuntimeError, match="build_agent_image"):
        ar.ensure_container("t1", _lane(tmp_path))


def test_ensure_docker缺_fail_closed不回落(tmp_path, fake):
    fake.set("docker-down")
    with pytest.raises(ar.AgentRuntimeError, match="host"):
        ar.ensure_container("t1", _lane(tmp_path))


def test_ensure_泳道不存在_拒(tmp_path, fake):
    with pytest.raises(ar.AgentRuntimeError, match="泳道目录不存在"):
        ar.ensure_container("t1", tmp_path / "nope")


def test_spawn_docker_main工作区_拒_点名红线(tmp_path, fake, monkeypatch):
    monkeypatch.setenv("SANDBAR_AGENT_RUNTIME", "docker")
    with pytest.raises(ar.AgentRuntimeError, match="main workspace"):
        ar.spawn_agent([PY, "-c", "pass"], cwd=tmp_path, env={}, logf=subprocess.DEVNULL,
                       ticket_id="t1", stage_tag="g0", workspace_kind="main",
                       lane=tmp_path, log=lambda m: None)


def test_spawn_host形态_旧语义零依赖fake(tmp_path, monkeypatch):
    rc_file = tmp_path / "rc"
    proc = ar.spawn_agent([PY, "-c", "import sys;open(sys.argv[1],'w').write('ok')", str(rc_file)],
                          cwd=tmp_path, env=dict(os.environ),
                          logf=subprocess.DEVNULL, ticket_id="t1",
                          stage_tag="g0", log=lambda m: None)
    assert proc.mode == "host"
    assert proc.wait(timeout=15) == 0 and rc_file.read_text() == "ok"


def test_exec_env白名单_沙箱旋钮结构性禁入(tmp_path, fake, monkeypatch):
    """红线 C 单元面：宿主 env 即便带着 danger-full-access，容器 exec 也只拿白名单。"""
    monkeypatch.setenv("DSH_PERMISSION_MODE", "danger-full-access")
    monkeypatch.setenv("DSH_SANDBOX_OFF", "1")
    lane = _lane(tmp_path)
    out = lane / "probe.txt"
    container = ar.ensure_container("t1", lane)
    proc = ar.exec_agent(container, lane,
                         [PY, "-c", "import os,sys;open(sys.argv[1],'w').write("
                                    "'mode='+os.environ.get('DSH_PERMISSION_MODE','absent')+'|'"
                                    "'home='+os.environ['HOME']+'|'"
                                     "'tmp='+os.environ['TMPDIR'])", str(out)],
                         {"DSH_HOME": str(lane / ".dsh"), "DSH_HEADLESS_SESSION": "s1",
                          "DSH_PERMISSION_MODE": "danger-full-access"},
                         logf=subprocess.DEVNULL, stage_tag="g0")
    assert proc.wait(timeout=20) == 0
    body = out.read_text()
    assert "mode=absent" in body, "DSH_PERMISSION_MODE 不得进容器 env（红线 C）"
    assert "home=/tmp/agent-home" in body and "tmp=/tmp" in body, "C4：运行期可写目录=容器本地"
    exec_argv = [a for a in fake.argvs() if a and a[0] == "exec"][-1]
    env_vals = [exec_argv[i + 1] for i, x in enumerate(exec_argv) if x == "-e"]
    assert not any(v.startswith("DSH_PERMISSION_MODE=") for v in env_vals), \
        "-e 白名单外出现沙箱旋钮（红线 C）"
    assert str(lane / ".sandbar" / "exec") in " ".join(exec_argv), "pgid 档在泳道 .sandbar/exec"
    assert "-w" in exec_argv and str(lane) in exec_argv


def test_exec_总链_桩命令写工作区_宿主可见_reap幂等(tmp_path, fake):
    """C2 口径：真 docker 面（此处=fake 传输+真 supervisor），桩命令全链。"""
    lane = _lane(tmp_path)
    container = ar.ensure_container("t1", lane)
    result = lane / "stage_x.json"   # 父目录=泳道本身，免 .sandbar 预建（引擎侧由宿主建）
    proc = ar.spawn_agent(
        [PY, "-c", "import json,sys; "
                   "open(sys.argv[1],'w').write(json.dumps({'status':'ok'}))", str(result)],
        cwd=lane, env={"DSH_HOME": str(lane / ".dsh")}, logf=subprocess.DEVNULL,
        ticket_id="t1", stage_tag="stage_gen0", workspace_kind="worktree",
        lane=lane, log=lambda m: None)
    assert proc.wait(timeout=20) == 0
    assert json.loads(result.read_text())["status"] == "ok", "结果文件宿主可见（D1/D）"
    assert proc.reap("t1", "stage") == "", "已退出 reap 幂等返回空"


def test_reap_中飞组杀_迟写被排_容器存活(tmp_path, fake):
    lane = _lane(tmp_path)
    container = ar.ensure_container("t1", lane)
    late = lane / "late.txt"
    proc = ar.exec_agent(container, lane,
                         [PY, "-c", "import time,sys; time.sleep(30); "
                                    "open(sys.argv[1],'w').write('late')", str(late)],
                         {}, logf=subprocess.DEVNULL, stage_tag="fly")
    time.sleep(1.0)
    note = proc.reap("t1", "fly", term_timeout=10, kill_timeout=5)
    assert "terminate" in note
    proc.wait(timeout=15)
    assert not late.exists(), "迟写未被组杀（KI-009 对齐失败）"
    assert ar._container_running(container) is True, "组杀不得误伤容器（并行段共存前提）"


def test_reap_容器已不在_幂等不抛(tmp_path, fake):
    """R8①+C6①：inspect 权威判「不在」→ 幂等 note；stderr 文案只是兜底。"""
    lane = _lane(tmp_path)
    container = ar.ensure_container("t1", lane)
    proc = ar.exec_agent(container, lane, [PY, "-c", "import time; time.sleep(30)"],
                         {}, logf=subprocess.DEVNULL, stage_tag="gone")
    fake.clear("running-" + container)   # 下次 inspect → No such container
    note = proc.reap("t1", "gone", term_timeout=5, kill_timeout=2)
    assert "容器已不在" in note
    proc.kill(); proc.wait(timeout=5)


def test_reap_inspect报错_容忍不抛不靠文案(tmp_path, fake):
    """C6③：daemon 报错（非「No such container」文案）→ 留痕容忍，绝不外抛。"""
    lane = _lane(tmp_path)
    container = ar.ensure_container("t1", lane)
    proc = ar.exec_agent(container, lane, [PY, "-c", "import time; time.sleep(30)"],
                         {}, logf=subprocess.DEVNULL, stage_tag="boom")
    fake.set("inspect-error")
    note = proc.reap("t1", "boom", term_timeout=5, kill_timeout=2)
    assert "探测失败" in note and "容忍" in note
    proc.kill(); proc.wait(timeout=5)


def test_reap_pgid坏档_跳过组杀留痕(tmp_path, fake):
    """R8/畸形输入：pgid 档被写坏（外部输入面）→ 不杀错、不抛、客户端仍收尾。"""
    lane = _lane(tmp_path)
    container = ar.ensure_container("t1", lane)
    proc = ar.exec_agent(container, lane, [PY, "-c", "import time; time.sleep(30)"],
                         {}, logf=subprocess.DEVNULL, stage_tag="bad")
    pgid_path = Path(proc.pgid_file)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not pgid_path.exists():
        time.sleep(0.05)
    pgid_path.write_text("NOT_A_PID;")
    note = proc.reap("t1", "bad", term_timeout=5, kill_timeout=2)
    assert "pgid 档缺失/坏" in note
    proc.kill(); proc.wait(timeout=5)


def test_reap_docker悬挂_有界返回不阻塞收尾(tmp_path, fake):
    """C6②：daemon 无响应（exec 悬挂）→ reap 有界（超时参数收紧）留痕返回。"""
    lane = _lane(tmp_path)
    container = ar.ensure_container("t1", lane)
    proc = ar.exec_agent(container, lane, [PY, "-c", "import time; time.sleep(30)"],
                         {}, logf=subprocess.DEVNULL, stage_tag="hang")
    fake.set("exec-hang")
    t0 = time.monotonic()
    note = proc.reap("t1", "hang", term_timeout=0.2, kill_timeout=0.2)
    assert time.monotonic() - t0 < 12, "reap 必须有界（不阻塞段结束路径）"
    assert "容忍" in note or "异常" in note
    proc.kill(); proc.wait(timeout=5)


def test_remove_三态(tmp_path, fake):
    lane = _lane(tmp_path)
    ar.ensure_container("t1", lane)
    assert "已拆" in ar.remove_container("t1")
    assert ar.remove_container("t1") == ""   # not-found=幂等空 note（真 docker rc1+No such container 同形）
    ar.ensure_container("t2", lane)
    fake.set("rm-garbage")
    assert "留痕不抛" in ar.remove_container("t2")


def test_gc_只拆泳道已亡的孤儿(tmp_path, fake):
    live_lane = _lane(tmp_path)
    dead_lane = tmp_path / "gone-lane"          # 不建目录=泳道已亡
    (fake.state / "containers.tsv").write_text(
        "sandbar-agent-live\t%s\nsandbar-agent-dead\t%s\n" % (live_lane, dead_lane))
    fake.set("running-sandbar-agent-live")
    fake.set("running-sandbar-agent-dead")
    notes = ar.gc_stale_containers()
    assert any("sandbar-agent-dead" in n for n in notes)
    assert not any("sandbar-agent-live" in n for n in notes)
    assert not (fake.state / "running-sandbar-agent-dead").exists()
    assert (fake.state / "running-sandbar-agent-live").exists(), "活票容器不得误拆"


def test_gc_docker缺_容忍note(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBAR_DOCKER_BIN", "/nonexistent/docker-bin")
    notes = ar.gc_stale_containers()
    assert notes == ["docker 不可用，跳过容器扫尾"]


# ---- 内容单点与防漂移 ----

def test_sandbox_pin_内容契约():
    """D5/D8 + 宿主 260914 A 案：字面量 mode=danger-full-access（容器内全权，隔离=
    挂载面；模式字面量不被 env/profile 篡改这层保障不变）+ 入口级 disabled:false
    （260913 探针：config 内写无效）+ workspaceRoot（C1）+ 900s 超时。"""
    pin = ar.sandbox_pin_yaml()
    assert "mode: 'danger-full-access'" in pin
    assert "mode: 'workspace-write'" not in pin
    # 只钉 sandbox 模式时合成缺省=(全权,ask) 不匹配任何预设 → dsh boot 拒启（260914
    # 实测）——defaultPreset 必须同钉（报错指引原话）。
    assert "- id: permission\n  disabled: false\n  config:\n    " \
           "defaultPreset: 'danger-full-access'" in pin
    assert "workspaceRoot: !!js process.cwd()" in pin
    assert "- id: sandbox-policy\n  disabled: false" in pin
    assert "- id: bash-sandbox\n  disabled: false" in pin
    assert "timeoutMs: %d" % ar.BASH_TIMEOUT_MS_DEFAULT in pin
    assert "maxTimeoutMs: %d" % ar.BASH_TIMEOUT_MS_DEFAULT in pin


def test_镜像版本三处同步():
    """R3#8：build 脚本缺省 == Dockerfile ARG 缺省 == agent_runtime 缺省 tag。"""
    script = (HERE.parent / "build_agent_image.sh").read_text()
    df = (HERE.parent / "Dockerfile.agent").read_text()
    dv = script.split('DV="${1:-', 1)[1].split('}"', 1)[0]
    seq = script.split('SEQ="${2:-', 1)[1].split('}"', 1)[0]
    assert ("sandbar-agent:dsh-%s-%s" % (dv, seq)) == ar.DEFAULT_AGENT_IMAGE
    assert ("ARG DSH_VERSION=%s" % dv) in df
    assert ar.DEFAULT_AGENT_IMAGE in script  # 脚本 echo 提示行也点名 tag（观测位）


def test_agent_activities_接线守卫():
    """传输层收口的机械防漂移：三点走 spawn_agent；agent 进程零直 Popen；
    reap 全走 AgentProc（_reap_agent_proc 仅剩定义与 host 迟 import）。"""
    src = (HERE.parent / "agent_activities.py").read_text()
    assert src.count("agent_runtime.spawn_agent(") == 3
    assert "subprocess.Popen(cmd" not in src
    assert "_reap_agent_proc(proc," not in src   # 调用形态清零（定义行签名不算）
    assert src.count("proc.reap(") == 6
    assert "agent_runtime.sandbox_pin_yaml()" in src
    assert src.count("agent_runtime.remove_container(") == 2   # teardown_lane + 内联清理
    assert "agent_runtime.gc_stale_containers(" in src          # prepare_workspace 扫尾


def test_runtime_mode_非法值_fail_closed(monkeypatch):
    monkeypatch.setenv("SANDBAR_AGENT_RUNTIME", "Docker ")   # 大小写/空白容忍
    assert ar.runtime_mode() == "docker"
    monkeypatch.setenv("SANDBAR_AGENT_RUNTIME", "full-access")
    with pytest.raises(ar.AgentRuntimeError):
        ar.runtime_mode()
