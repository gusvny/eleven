"""t260921-14（dsh 升级 T3）paths.dsh_bin 声明钉 + 三面版本自检 UT。

【故障模式取舍清单（方案 §2.6，review C2 要求的显式取舍；源实现→本票新键）】
 带过来（既有 paths 族/dsh_pin 家族纪律照抄）：
  1 空值/纯空白→红  2 非标量 {[ →红  3 引号包裹剥壳（与 TS 同判）  4 .. 越界红
  5 `~/…`/绝对路径放行（dsh_bin 的主用例就是机器级绝对路径）
  6 相对拼 main_dir + 缺 dirs 首项红  7 未知键红（closed set=PATHS_DECL_KEYS 自动
  覆盖新键）  8 paths 重复键红（_entry_paths_parse 逐键判重，零额外代码）
  9 坏条目文件（顶层形状/schema/编码）fail-closed  10 锚点判定归 consumer
  （want="file"）+新增不可执行红（os.access X_OK，dsh_bin 特有语义）
  11 未声明软回落缺省（None→裸 dsh 现状，可见性归 face/info 点名）
  12 probe 全终态回收（容器探针加按名 docker rm -f 兜底）
  13 probe 失败不挡启动（face error 照记）——与 10 两级分明：声明面缺陷红拦 spawn，
     --version 探测失败归观测面（真正 spawn 的失败自有 spawn 路径响亮）
 不带（+理由）：
  14 model_routes 的 decl_missing 仓内兜底表——dsh 无「仓内兜底二进制」概念，缺省
     （未声明）=PATH 裸命令本身是完整配置，非降级（裁定 b，t260916-02 inspection_decl
     「回落语义刻意不照抄」同款先例）
  15 inspection_decl 消费侧四态表——dsh_bin 消费面仅 spawn 一处，无四态表需求
  16 roles_dir 的 _decl_rel 强制相对——与用例相反（必须机器级绝对），走放宽口径
  17 EXPECTED/STRICT×新钉交互=显式裁定：期望比对对象=被钉二进制实证版（face↔spawn
     同源，C1 贯通）；SANDBAR_DSH_STRICT=1 钉错照样硬闸；worker 启动 meta face 不读
     声明仍 env 锚（process face / spawn face 两级分工，试验对账以票面 spawn face 为准）
  18 沙箱旋钮面不涉（dsh_bin 是路径非执行面旋钮）

覆盖（票面验收 L1）：pin 读取 / 默认回落等价现状 / 畸形与不可执行路径响亮点名 /
镜像 tag 三处同步锁（=test_agent_runtime.test_镜像版本三处同步，三处翻新自适配）+
face↔spawn 同源端到端（C1）+ memo 键 + 预检 basename + 容器实测探针四档 + tri 纯函数。

全程零网络/真 dsh（版本探测用临时桩脚本，docker 探针用假 docker 桩）；注册表走
SANDBAR_PROJECTS_DIR 注入隔离目录，绝不写真 ~/.sandbar/projects；禁真 Temporal/真 git。
"""
import json
import shlex
from pathlib import Path

import pytest

import dsh_pin
import shared

REPO = Path(__file__).resolve().parents[3]
ENGINE = Path(__file__).resolve().parents[1]

LEGACY_FACE_KEYS = ("mode", "cmd", "cmd_source", "bin", "real_bin", "version",
                    "version_state", "version_detail", "image", "image_source",
                    "expected", "ts", "expected_state")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """旋钮逐用例隔离：缺省分支测试不得被外层 env 污染（含注册表注入位）。"""
    for k in (dsh_pin.ENV_AGENT_CMD, dsh_pin.ENV_EXPECTED, dsh_pin.ENV_STRICT,
              dsh_pin.ENV_RUNTIME, dsh_pin.ENV_AGENT_IMAGE, "SANDBAR_PROJECTS_DIR",
              "FAKE_DOCKER_MODE"):
        monkeypatch.delenv(k, raising=False)


def _stub(tmp_path, body, name="stub_dsh.py"):
    """可执行桩（探子按 `<cmd0> --version` 直接执行，需 shebang+chmod，同真二进制）。"""
    p = tmp_path / name
    if not body.startswith("#!"):
        body = "#!/usr/bin/env python3\n" + body
    p.write_text(body, "utf-8")
    p.chmod(0o755)
    return str(p)


def _write_entry(root: Path, key: str, home: Path = None, dsh_bin: str = None,
                 dup: bool = False, unknown_key: str = "") -> Path:
    """per-key 注册条目夹具（镜 t260916-02 手法）。home=None=不写 dirs（无主目录）；
    dsh_bin=None=不声明；dsh_bin=""=声明空值（空值红用例）。"""
    d = root / key
    d.mkdir(parents=True, exist_ok=True)
    lines = ["schema: v1", "project:", "  - key: %s" % key, "    name: F %s" % key]
    if home is not None:
        lines += ["    dirs:", "      - %s" % home]
    if dsh_bin is not None or dup or unknown_key:
        lines.append("paths:")
        if dsh_bin is not None:
            lines.append("  dsh_bin: %s" % dsh_bin)
        if dup:
            lines.append("  dsh_bin: %s" % dsh_bin)
        if unknown_key:
            lines.append("  %s: /x" % unknown_key)
    (d / "project.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return d / "project.yaml"


@pytest.fixture
def registry(monkeypatch, tmp_path):
    """隔离注册表夹具：返回 (root, write_entry, home)。绝不写真 ~/.sandbar/projects。"""
    root = tmp_path / "registry"
    root.mkdir()
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(root))
    return root, _write_entry, tmp_path / "home"


# ---- ① 声明键解析（shared.project_paths / dsh_bin_for_spawn） ----------------

def test_声明缺失返回None现状软回落(registry):
    root, write, home = registry
    write(root, "proj", home)
    assert shared.dsh_bin_for_spawn("proj") is None          # 取舍 #11：软回落现状
    info = shared.project_paths("proj")
    assert info["dsh_bin"] is None and info["dsh_bin_rel"] is None


def test_绝对路径解析(registry, tmp_path):
    root, write, home = registry
    stub = _stub(tmp_path, "print('9.9.9-pin')\n")
    write(root, "proj", home, dsh_bin=stub)
    assert str(shared.dsh_bin_for_spawn("proj")) == stub


def test_波浪号路径按HOME展开(registry, tmp_path, monkeypatch):
    root, write, _ = registry
    bindir = tmp_path / "binhome" / "bin"
    bindir.mkdir(parents=True)
    stub = _stub(bindir, "print('9.9.9-pin')\n", name="dsh")   # = <HOME>/bin/dsh
    monkeypatch.setenv("HOME", str(bindir.parent))
    write(root, "proj", tmp_path / "projhome", dsh_bin="~/bin/dsh")
    got = shared.dsh_bin_for_spawn("proj")
    assert got is not None and got.is_absolute() and str(got) == stub


def test_相对路径拼项目主目录(registry, tmp_path):
    root, write, home = registry
    bindir = home / "tools"
    bindir.mkdir(parents=True)
    _stub(bindir, "print('9.9.9-pin')\n", name="dsh")
    write(root, "proj", home, dsh_bin="tools/dsh")
    got = shared.dsh_bin_for_spawn("proj")
    assert got == bindir / "dsh" and str(got) == str(bindir / "dsh")


def test_引号包裹剥壳(registry, tmp_path):
    root, write, home = registry
    stub = _stub(tmp_path, "print('9.9.9-pin')\n")
    write(root, "proj", home, dsh_bin='"%s"' % stub)
    assert str(shared.dsh_bin_for_spawn("proj")) == stub


def test_空值红(registry):
    root, write, home = registry
    write(root, "proj", home, dsh_bin="")
    with pytest.raises(shared.ProjectPathsError, match="dsh_bin"):
        shared.dsh_bin_for_spawn("proj")


def test_非标量红(registry):
    root, write, home = registry
    write(root, "proj", home, dsh_bin="{a-b}")
    with pytest.raises(shared.ProjectPathsError, match="非标量"):
        shared.project_paths("proj")


def test_越界红(registry):
    root, write, home = registry
    write(root, "proj", home, dsh_bin="../../etc/dsh")
    with pytest.raises(shared.ProjectPathsError, match="\\.\\."):
        shared.project_paths("proj")


def test_相对声明但条目缺主目录红(registry, tmp_path):
    root, write, _ = registry
    write(root, "proj", None, dsh_bin="tools/dsh")   # 无 dirs → 无 main_dir
    with pytest.raises(shared.ProjectPathsError, match="无法定项目主目录"):
        shared.project_paths("proj")


def test_重复键红(registry, tmp_path):
    """C2①：paths 重复键红对 dsh_bin 同样执法（解析器逐键判重自动覆盖新键）。"""
    root, write, home = registry
    write(root, "proj", home, dsh_bin="/x/dsh", dup=True)
    with pytest.raises(shared.ProjectPathsError, match="重复"):
        shared.project_paths("proj")


def test_未知键仍红_回归(registry, tmp_path):
    root, write, home = registry
    write(root, "proj", home, unknown_key="dsh_binx")
    with pytest.raises(shared.ProjectPathsError, match="不认的键"):
        shared.project_paths("proj")


def test_锚点缺失红(registry, tmp_path):
    root, write, home = registry
    write(root, "proj", home, dsh_bin="%s/nope/dsh" % tmp_path)
    with pytest.raises(shared.ProjectPathsError, match="不存在"):
        shared.dsh_bin_for_spawn("proj")


def test_锚点是目录红(registry, tmp_path):
    root, write, home = registry
    d = tmp_path / "dshdir"
    d.mkdir()
    write(root, "proj", home, dsh_bin=str(d))
    with pytest.raises(shared.ProjectPathsError, match="不是文件"):
        shared.dsh_bin_for_spawn("proj")


def test_锚点不可执行红(registry, tmp_path):
    """裁定 a：翻钉坏了不回落裸 dsh——不可执行=fail-closed 红拦 spawn（取舍 #10）。"""
    root, write, home = registry
    p = tmp_path / "mute_dsh.py"
    p.write_text("#!/usr/bin/env python3\nprint('x')\n", "utf-8")
    p.chmod(0o644)  # 无 x 位
    write(root, "proj", home, dsh_bin=str(p))
    with pytest.raises(shared.ProjectPathsError, match="不可执行"):
        shared.dsh_bin_for_spawn("proj")


# ---- ② resolve_dsh_cmd 声明参数 ----------------------------------------------

def test_declared组成_缺省参数逐元素保持(tmp_path):
    stub = _stub(tmp_path, "print('9.9.9-pin')\n")
    r = dsh_pin.resolve_dsh_cmd(env={}, dsh_bin=stub)
    assert r["source"] == "declared"
    assert r["cmd"] == [stub, "--profile", "sandbar-headless"]
    assert r["dsh_bin_shadowed"] is False


def test_env与声明并存_env胜_shadowed(tmp_path):
    stub = _stub(tmp_path, "print('9.9.9-pin')\n")
    r = dsh_pin.resolve_dsh_cmd(env={"SANDBAR_AGENT_CMD": "%s --profile p" % stub},
                                dsh_bin="/x/y/dsh")
    assert r["source"] == "env" and r["cmd"][0] == stub
    assert r["dsh_bin_shadowed"] is True


def test_env独设_shadowed_false():
    r = dsh_pin.resolve_dsh_cmd(env={"SANDBAR_AGENT_CMD": "/x/dsh --profile p"})
    assert r["dsh_bin_shadowed"] is False


def test_缺省回归锚_与legacy常量等值():
    assert dsh_pin.resolve_dsh_cmd(env={})["cmd"] == shlex.split("dsh --profile sandbar-headless")


# ---- ③ face↔spawn 同源（C1 贯通） -------------------------------------------

def test_face_resolved贯通_版本探测于被钉二进制(tmp_path):
    stub = _stub(tmp_path, "print('9.9.9-pin')\n")
    resolved = dsh_pin.resolve_dsh_cmd(env={}, dsh_bin=stub)
    face = dsh_pin.dsh_face_payload(mode="host", env={}, resolved=resolved)
    assert face["cmd_source"] == "declared"
    assert face["cmd"] == [stub, "--profile", "sandbar-headless"]
    assert face["bin"] == stub
    assert face["version"] == "9.9.9-pin" and face["version_state"] == "ok"
    assert face["dsh_bin_shadowed"] is False


def test_face_env胜_shadowed落在face(tmp_path):
    stub = _stub(tmp_path, "print('9.9.9-pin')\n")
    resolved = dsh_pin.resolve_dsh_cmd(env={"SANDBAR_AGENT_CMD": "%s --profile p" % stub},
                                       dsh_bin="/x/y/dsh")
    face = dsh_pin.dsh_face_payload(mode="host", env={}, resolved=resolved)
    assert face["cmd_source"] == "env" and face["bin"] == stub
    assert face["dsh_bin_shadowed"] is True


def test_face_不传resolved_与现状同形_键集additive(tmp_path):
    """回归锚：resolved 缺省=env 锚现状；新字段只 additive（取舍 #17 两级 face）。"""
    face = dsh_pin.dsh_face_payload(mode="host", env={}, probe=False)
    for k in LEGACY_FACE_KEYS:
        assert k in face
    assert face["dsh_bin_shadowed"] is False
    assert face["cmd_source"] == "default"
    assert face["cmd"] == ["dsh", "--profile", "sandbar-headless"]


def test_face_docker形态不消费resolved():
    face = dsh_pin.dsh_face_payload(mode="docker", env={}, probe=False,
                                    default_image="sandbar-agent:dsh-0.1.5-rc.2-s1",
                                    resolved={"cmd": ["/x/dsh"], "source": "declared",
                                              "raw": "/x/dsh", "dsh_bin_shadowed": False})
    assert face["cmd"] is None                       # 容器面：声明不消费（镜像承载）
    assert face["version"] == "0.1.5-rc.2"           # tag-derived
    assert face["dsh_bin_shadowed"] is False


# ---- ④ is_dsh_runner（预检 basename 口径） -----------------------------------

def test_is_dsh_runner_口径():
    assert dsh_pin.is_dsh_runner("dsh") is True
    assert dsh_pin.is_dsh_runner("/Users/x/.sandbar/dsh-015/bin/dsh") is True
    assert dsh_pin.is_dsh_runner("./dsh") is True
    assert dsh_pin.is_dsh_runner("/x/dsh_stub.py") is False   # 桩不误触
    assert dsh_pin.is_dsh_runner("Dsh") is False
    assert dsh_pin.is_dsh_runner("") is False
    assert dsh_pin.is_dsh_runner(None) is False


# ---- ⑤ tri_face_payload 纯函数（三面自检） -----------------------------------

def _eface(version="0.1.5-rc.2", state="ok", mode="host", **kw):
    f = {"mode": mode, "cmd": ["/x/dsh", "--profile", "sandbar-headless"],
         "cmd_source": "declared", "bin": "/x/dsh", "version": version,
         "version_state": state, "dsh_bin_shadowed": False}
    f.update(kw)
    return f


def test_tri_一致_host模式():
    tri = dsh_pin.tri_face_payload(_eface("0.1.1-rc.2"), "/opt/homebrew/bin/dsh",
                                   {"version": "0.1.1-rc.2", "state": "ok", "detail": ""})
    assert tri["consistency"] == "consistent"
    assert tri["divergences"] == []
    assert "container" not in tri["faces"]           # host 形态无容器面=缺席非失败
    assert "0.1.1-rc.2" in tri["note"]


def test_tri_divergent逐对点名():
    tri = dsh_pin.tri_face_payload(_eface("0.1.5-rc.2"), "/opt/homebrew/bin/dsh",
                                   {"version": "0.1.1-rc.2", "state": "ok", "detail": ""})
    assert tri["consistency"] == "divergent"
    assert any("host_global=0.1.1-rc.2" in d and "engine=0.1.5-rc.2" in d
               for d in tri["divergences"])
    assert "不一致" in tri["note"]


def test_tri_容器实测与tag不符也点名():
    """docker 形态：tag-derived（引擎面）vs 实测（容器面）不符=约定漂移，点名。"""
    tri = dsh_pin.tri_face_payload(
        _eface("0.1.1-rc.2", mode="docker", bin=None,
               cmd=None, image="sandbar-agent:dsh-0.1.1-rc.2-s1"),
        "/opt/homebrew/bin/dsh",
        {"version": "0.1.1-rc.2", "state": "ok", "detail": ""},
        {"version": "0.1.5-rc.2", "state": "ok", "detail": ""})
    assert tri["consistency"] == "divergent"
    assert any("container=0.1.5-rc.2" in d for d in tri["divergences"])
    assert "container" in tri["faces"]


def test_tri_incomplete点名判不了的面():
    tri = dsh_pin.tri_face_payload(_eface(), "/opt/homebrew/bin/dsh",
                                   {"version": None, "state": "error", "detail": "which 落空"})
    assert tri["consistency"] == "incomplete"
    assert any("host_global" in f for f in tri["incomplete"])
    assert "不完整" in tri["note"]


def test_tri_引擎面同源_不自产第二套():
    """engine 面读传入 face（face↔spawn 同源，C1）：face 变 tri 随之变，无第二套解析。"""
    tri_a = dsh_pin.tri_face_payload(_eface("9.9.9-a"), None, None)
    tri_b = dsh_pin.tri_face_payload(_eface("9.9.9-b"), None, None)
    assert tri_a["faces"]["engine"]["version"] == "9.9.9-a"
    assert tri_b["faces"]["engine"]["version"] == "9.9.9-b"


# ---- ⑥ probe_image_dsh_version（假 docker 四档 + 全终态回收） ----------------

def _fake_docker(tmp_path, ledger):
    p = tmp_path / "fake_docker.py"
    p.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys, time\n"
        "args = sys.argv[1:]\n"
        "with open(%r, 'a') as f:\n"
        "    f.write(json.dumps(args) + chr(10))\n"
        "mode = os.environ.get('FAKE_DOCKER_MODE', 'ok')\n"
        "if args[:1] == ['run']:\n"
        "    if mode == 'ok':\n"
        "        print('9.9.9-container')\n"
        "    elif mode == 'nonzero':\n"
        "        sys.stderr.write('boom')\n"
        "        sys.exit(3)\n"
        "    elif mode == 'malformed':\n"
        "        print('9.9.9-container')\n"
        "        print('extra')\n"
        "    elif mode == 'timeout':\n"
        "        time.sleep(5)\n"
        "    sys.exit(0)\n"
        "sys.exit(0)\n" % str(ledger), "utf-8")
    p.chmod(0o755)
    return str(p)


def _ledger_lines(ledger):
    return [json.loads(ln) for ln in Path(ledger).read_text("utf-8").splitlines() if ln.strip()]


def test_probe容器绿(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.jsonl"
    dbin = _fake_docker(tmp_path, ledger)
    monkeypatch.setenv("FAKE_DOCKER_MODE", "ok")
    r = agent_runtime_probe("sandbar-agent:dsh-0.1.5-rc.2-s1", dbin)
    assert r["state"] == "ok" and r["version"] == "9.9.9-container"
    run_line = [ln for ln in _ledger_lines(ledger) if ln[:1] == ["run"]]
    assert run_line and run_line[0][2] == "--name" and run_line[0][3].startswith("sandbar-dsh-probe-")
    assert run_line[0][5:7] == ["dsh", "--version"]


def test_probe容器非零红(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.jsonl"
    dbin = _fake_docker(tmp_path, ledger)
    monkeypatch.setenv("FAKE_DOCKER_MODE", "nonzero")
    r = agent_runtime_probe("sandbar-agent:x", dbin)
    assert r["state"] == "error" and "boom" in r["detail"]


def test_probe容器畸形输出红(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.jsonl"
    dbin = _fake_docker(tmp_path, ledger)
    monkeypatch.setenv("FAKE_DOCKER_MODE", "malformed")
    r = agent_runtime_probe("sandbar-agent:x", dbin)
    assert r["state"] == "error" and "非单行版本样" in r["detail"]


def test_probe容器超时_进程组收割加按名强拆(tmp_path, monkeypatch):
    """取舍 #12：超时路径全终态——killpg 收割客户端 + 按名 rm -f 兜底（孤儿无存留）。"""
    import os as _os
    ledger = tmp_path / "ledger.jsonl"
    dbin = _fake_docker(tmp_path, ledger)
    monkeypatch.setenv("FAKE_DOCKER_MODE", "timeout")
    r = agent_runtime_probe("sandbar-agent:x", dbin, timeout=0.5)
    assert r["state"] == "error" and "超时" in r["detail"]
    lines = _ledger_lines(ledger)
    assert any(ln[:1] == ["rm"] and "-f" in ln for ln in lines)   # 按名强拆已执行
    assert _os.path.exists(ledger)


def agent_runtime_probe(image, dbin, timeout=10.0):
    """迟 import：本文件底部接线用例已带起 agent_activities（temporalio 重面），
    本组用例保持轻面（agent_runtime stdlib-only 可独立 import）。"""
    import agent_runtime
    return agent_runtime.probe_image_dsh_version(image, docker_bin_override=dbin,
                                                 timeout=timeout)


# ---- ⑦ agent_activities 接线（C1 端到端 + memo 键 + 预检 + 巡检同源） --------

def test_接线源码锚():
    """新接线锚（接替 t260916-24 旧锚）：cmd/face 同源、预检 basename、巡检同源、
    tri 落票面、dsh_pin 的 resolved 缺省回落形态——任一被绕过=红。"""
    aa_src = (ENGINE / "agent_activities.py").read_text("utf-8")
    assert "resolved_dsh = _dsh_resolved(project)" in aa_src
    assert "face = _dsh_face_once(resolved_dsh)" in aa_src
    assert "not dsh_pin.is_dsh_runner(cmd[0])" in aa_src
    assert '_dsh_resolved(project)["cmd"]' in aa_src
    assert 'pin_payload["tri"] = tri' in aa_src
    dp_src = (ENGINE / "dsh_pin.py").read_text("utf-8")
    assert "resolved = resolved or resolve_dsh_cmd(env)" in dp_src


def test_dsh_resolved声明贯通_host形态(registry, tmp_path):
    import agent_activities
    root, write, home = registry
    stub = _stub(tmp_path, "print('9.9.9-pin')\n")
    write(root, "proj", home, dsh_bin=stub)
    r = agent_activities._dsh_resolved("proj")
    assert r["source"] == "declared" and r["cmd"][0] == stub
    assert r["dsh_bin_shadowed"] is False


def test_dsh_resolved_docker形态点名不消费(registry, tmp_path, monkeypatch, caplog):
    import agent_activities
    import logging
    root, write, home = registry
    stub = _stub(tmp_path, "print('9.9.9-pin')\n")
    write(root, "proj", home, dsh_bin=stub)
    monkeypatch.setenv("SANDBAR_AGENT_RUNTIME", "docker")
    with caplog.at_level(logging.WARNING):
        r = agent_activities._dsh_resolved("proj")
    assert r["source"] == "default" and r["cmd"][0] == "dsh"   # cmd 保持容器内裸 dsh
    assert any("docker 形态不消费" in rec.message for rec in caplog.records)


def test_dsh_resolved_env遮蔽点名(registry, tmp_path, monkeypatch, caplog):
    """env 遮蔽的是【有效】声明（坏声明不受 env 豁免——声明缺陷先红，裁定 a）。"""
    import agent_activities
    import logging
    root, write, home = registry
    stub = _stub(tmp_path, "print('9.9.9-pin')\n")
    write(root, "proj", home, dsh_bin=stub)
    monkeypatch.setenv("SANDBAR_AGENT_CMD", "%s --profile p" % stub)
    with caplog.at_level(logging.WARNING):
        r = agent_activities._dsh_resolved("proj")
    assert r["source"] == "env" and r["dsh_bin_shadowed"] is True
    assert any("遮蔽" in rec.message for rec in caplog.records)


def test_dsh_resolved_坏声明红(registry, tmp_path):
    import agent_activities
    root, write, home = registry
    write(root, "proj", home, dsh_bin="%s/nope/dsh" % tmp_path)
    with pytest.raises(shared.ProjectPathsError):
        agent_activities._dsh_resolved("proj")


def test_face_once_memo键_同cmd复用异cmd各自探(tmp_path):
    import agent_activities
    s1 = _stub(tmp_path, "print('9.9.9-a')\n", name="a.py")
    s2 = _stub(tmp_path, "print('9.9.9-b')\n", name="b.py")
    r1 = dsh_pin.resolve_dsh_cmd(env={}, dsh_bin=s1)
    r2 = dsh_pin.resolve_dsh_cmd(env={}, dsh_bin=s2)
    f1a = agent_activities._dsh_face_once(r1)
    f1b = agent_activities._dsh_face_once(r1)
    assert f1a is f1b                                  # 同解析形态：probe 只付一次
    f2 = agent_activities._dsh_face_once(r2)
    assert f2 is not f1a                               # 异形态不串面（单值 memo 会串）
    assert f2["bin"] == s2 and f2["version"] == "9.9.9-b"


def test_host_global与tri_memo_换PATH换桩不串面(tmp_path, monkeypatch):
    """同一 worker 进程先后注入不同 PATH 桩（集成场景子用例的真实形态）：宿主面按
    which() 结果逐键 memo、tri key 含宿主 bin——跨子用例绝不吃到上一子用例的缓存。"""
    import os as _os
    import agent_activities
    bin1 = tmp_path / "bin1"
    bin1.mkdir()
    _stub(bin1, "print('9.9.9-h1')\n", name="dsh")
    path1 = str(bin1) + _os.pathsep + _os.environ["PATH"]
    monkeypatch.setenv("PATH", path1)
    h1 = agent_activities._host_global_dsh()
    assert h1["probe"]["version"] == "9.9.9-h1"
    bin2 = tmp_path / "bin2"
    bin2.mkdir()
    _stub(bin2, "print('9.9.9-h2')\n", name="dsh")
    path2 = str(bin2) + _os.pathsep + _os.environ["PATH"]
    monkeypatch.setenv("PATH", path2)
    h2 = agent_activities._host_global_dsh()
    assert h2 is not h1 and h2["probe"]["version"] == "9.9.9-h2"
    # tri 组装：同引擎 face + 不同宿主 bin → 两个 tri（leg3 场景防串面的锚）。
    # docker 形态的容器探针注入假 docker（conftest 看门狗守单测零真 docker 调用）。
    fake = tmp_path / "fake_docker.sh"
    fake.write_text("#!/bin/sh\nif [ \"$1\" = run ]; then echo 9.9.9-ctr; fi\nexit 0\n", "utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("SANDBAR_DOCKER_BIN", str(fake))
    eface = _eface("9.9.9-tag", mode="docker", bin=None, cmd=None,
                   image="sandbar-agent:dsh-9.9.9-tag-s1")
    monkeypatch.setenv("PATH", path1)
    t1 = agent_activities._dsh_tri_face_once(eface)
    monkeypatch.setenv("PATH", path2)
    t2 = agent_activities._dsh_tri_face_once(eface)
    assert t1["faces"]["host_global"]["version"] == "9.9.9-h1"
    assert t2["faces"]["host_global"]["version"] == "9.9.9-h2"


def test_预检钉绝对路径不跳过(tmp_path):
    """t260916-28 不变量钉态不回归：basename=dsh 的绝对路径仍触发泳道 .dsh 自检。"""
    import agent_activities
    lane_dsh = tmp_path / ".dsh"                       # 缺 profile/settings → 应拒绝
    refusal = agent_activities._lane_dsh_preflight(
        ["/Users/x/.sandbar/dsh-015/bin/dsh", "--profile", "sandbar-headless"],
        lane_dsh, [])
    assert refusal is not None and refusal["reason_code"].startswith("lane_dsh_")
    stub = tmp_path / "dsh_stub.py"
    stub.write_text("#!/usr/bin/env python3\n", "utf-8")
    assert agent_activities._lane_dsh_preflight([str(stub)], lane_dsh, []) is None
    assert agent_activities._lane_dsh_preflight([], lane_dsh, []) is None


def test_钉后期望对照对象是被钉二进制(tmp_path):
    """取舍 #17：期望比对=被钉二进制的实证版（face 贯通后 enforce_expected 不再对错对象）。"""
    stub = _stub(tmp_path, "print('9.9.9-pin')\n")
    resolved = dsh_pin.resolve_dsh_cmd(env={}, dsh_bin=stub)
    face = dsh_pin.dsh_face_payload(
        mode="host", env={"SANDBAR_DSH_EXPECTED_VERSION": "0.1.1-rc.2"},
        resolved=resolved)
    assert face["version"] == "9.9.9-pin"
    assert face["expected_state"] == "mismatch"
    with pytest.raises(dsh_pin.DshPinError) as ei:
        dsh_pin.enforce_expected(
            face, env={"SANDBAR_DSH_EXPECTED_VERSION": "0.1.1-rc.2",
                       "SANDBAR_DSH_STRICT": "1"})
    assert "9.9.9-pin" in str(ei.value) and "0.1.1-rc.2" in str(ei.value)
