"""t260916-22：inspect 段活动层单测（run_inspection_inspect / _prepare_agent_spawn）。

覆盖（方案 §4 步骤2 验证清单 + review C3 条款）：
- C3：_prepare_agent_spawn 缺省分支（不传 agent_home）与显式 agent_home=None 逐字节相等
  （cmd 列表与 env dict 全等），且 DSH_HOME 仍=cwd/.dsh——dev-lane 全体 spawn 热路径
  零回归的显式断言；
- agent_home 覆盖腿：DSH_HOME 钉到指定目录、cwd/.dsh 不落任何文件；
- 活动输入闸 fail-closed（缺 instance/period/base_dir/base 不存在/缺 agent_home）；
- 桩腿：合法夹具→铸 id 返回；畸形夹具/夹具缺失→点名失败（与真 agent 同契约）；
- 真 spawn 链（SANDBAR_INSPECT_CMD 注入假脚本）：Popen→日志→围栏解析→铸 id 全绿；
  argv 末尾=persona/read-only 两 patch + prompt；DSH_HOME=agent_home；退出码非零/
  无围栏输出→点名失败；超时→「agent 未完成」不假绿 + 进程组回收干净。
"""
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from temporalio import activity as activity_mod

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import agent_activities as aa  # noqa: E402
import inspection_inspect as ins  # noqa: E402


@pytest.fixture()
def beats(monkeypatch):
    """活动上下文外的 heartbeat 直录（temporalio 活动外调用本会 raise）。"""
    got = []
    monkeypatch.setattr(activity_mod, "heartbeat", lambda *a, **k: got.append(a))
    return got


@pytest.fixture()
def base_dir(tmp_path: Path) -> Path:
    d = tmp_path / "repo"
    d.mkdir()
    (d / "src.py").write_text("value = 1\n", encoding="utf-8")
    return d


def _args(base: Path, tmp: Path, **kw) -> dict:
    a = {"instance_id": "inst", "period": "20260916", "ticket_id": "t1",
         "face": "test", "base_dir": str(base),
         "agent_home": str(tmp / "agent-home"), "timeout_sec": 120}
    a.update(kw)
    return a


# ---------- C3：缺省分支逐字节不变 ----------

def test_prepare_agent_spawn_default_leg_byte_identical(tmp_path):
    cwd = tmp_path / "ws"
    cwd.mkdir()
    arts = tmp_path / "artifacts"
    arts.mkdir()
    kw = dict(cwd=cwd, role="dev", kind="", ticket_id="t1", artifacts_dir=arts,
              tag="gen1", project="proj")
    r_default = aa._prepare_agent_spawn(**kw)                      # 缺省（现状调用点形态）
    r_none = aa._prepare_agent_spawn(**kw, agent_home=None)        # 显式 None
    assert r_default == r_none                                     # 逐字节相等（C3）
    cmd, env = r_default
    assert env["DSH_HOME"] == str(cwd / ".dsh")
    assert (cwd / ".dsh").is_dir()


def test_prepare_agent_spawn_agent_home_override(tmp_path):
    cwd = tmp_path / "ws"
    cwd.mkdir()
    home = tmp_path / "agent-home" / "inst-20260916"
    cmd, env = aa._prepare_agent_spawn(cwd=cwd, role="inspection", kind="",
                                       ticket_id="t1",
                                       artifacts_dir=home, tag="inspect",
                                       project="proj", agent_home=home)
    assert env["DSH_HOME"] == str(home)
    assert home.is_dir()
    assert not (cwd / ".dsh").exists()        # 审查基座零落点（红线：不写真仓工作区）


# ---------- 输入闸 ----------

def test_inspect_input_gates_fail_closed(tmp_path, base_dir, monkeypatch, beats):
    monkeypatch.delenv("SANDBAR_INSPECT_STUB", raising=False)
    monkeypatch.delenv("SANDBAR_INSPECT_CMD", raising=False)
    for mut, why in [({"instance_id": ""}, "instance"),
                     ({"period": ""}, "period"),
                     ({"base_dir": ""}, "base_dir"),
                     ({"base_dir": str(tmp_path / "nope")}, "不存在")]:
        res = asyncio.run(aa.run_inspection_inspect(_args(base_dir, tmp_path, **mut)))
        assert res["ok"] is False and why in res["error"], mut
        assert beats == []                       # 闸前零心跳


def test_inspect_paths_derived_when_unsupplied(base_dir, tmp_path, monkeypatch, beats):
    """agent_home/suite_receipt 缺省=活动侧按 INSPECTION_DIR 派生（workflow 体零路径
    计算、缺省传参兼容）；桩腿下派生路径不影响结果。"""
    monkeypatch.setenv("SANDBAR_INSPECT_STUB", "1")
    fixture = tmp_path / "fixture.json"
    fixture.write_text("```json\n%s\n```\n" % json.dumps(
        {"findings": _fixture_findings(base_dir)}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("SANDBAR_INSPECT_STUB_FILE", str(fixture))
    a = _args(base_dir, tmp_path)
    a.pop("agent_home")
    res = asyncio.run(aa.run_inspection_inspect(a))
    assert res["ok"] is True, res


# ---------- 桩腿 ----------

def _fixture_findings(base: Path) -> list:
    return [{"subject": "src.py 值未使用", "severity": "low",
             "evidence": [{"path": "src.py", "line": 1, "quote": "value = 1"}],
             "why": "赋值无消费者", "suggestion": "删除", "confidence": 0.7}]


def test_inspect_stub_ok_path(base_dir, tmp_path, monkeypatch, beats):
    fixture = tmp_path / "fixture.json"
    fixture.write_text("审查完毕。\n```json\n%s\n```\n" % json.dumps(
        {"findings": _fixture_findings(base_dir)}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("SANDBAR_INSPECT_STUB", "1")
    monkeypatch.setenv("SANDBAR_INSPECT_STUB_FILE", str(fixture))
    res = asyncio.run(aa.run_inspection_inspect(_args(base_dir, tmp_path)))
    assert res["ok"] is True
    fs = res["result"]["findings"]
    assert len(fs) == 1 and fs[0]["id"] and fs[0]["scan"] == "agent"
    assert res["result"]["meta"]["stub"] is True
    assert beats and "stub" in beats[-1][0]
    assert not (base_dir / ".dsh").exists()      # 桩腿同样不碰基座


def test_inspect_stub_malformed_and_missing_named(base_dir, tmp_path, monkeypatch, beats):
    monkeypatch.setenv("SANDBAR_INSPECT_STUB", "1")
    bad = tmp_path / "bad.json"
    bad.write_text("没有围栏块的输出", encoding="utf-8")
    monkeypatch.setenv("SANDBAR_INSPECT_STUB_FILE", str(bad))
    res = asyncio.run(aa.run_inspection_inspect(_args(base_dir, tmp_path)))
    assert res["ok"] is False and "解析失败" in res["error"]

    monkeypatch.setenv("SANDBAR_INSPECT_STUB_FILE", str(tmp_path / "absent.json"))
    res = asyncio.run(aa.run_inspection_inspect(_args(base_dir, tmp_path)))
    assert res["ok"] is False and "夹具缺失" in res["error"]


# ---------- 真 spawn 链（SANDBAR_INSPECT_CMD 假脚本） ----------

def _fake_dsh_script(tmp_path: Path, dump: Path, findings_json: str) -> Path:
    s = tmp_path / "fake_dsh.py"
    s.write_text(
        "import os, sys\n"
        "with open(%r, 'w') as f:\n"
        "    f.write('ARGV=' + chr(31).join(sys.argv[1:]) + chr(10))\n"
        "    f.write('DSH_HOME=' + os.environ.get('DSH_HOME', '') + chr(10))\n"
        "    f.write('CWD=' + os.getcwd() + chr(10))\n"
        "print('fake agent 工作中')\n"
        "print('```json')\n"
        "print(open(%r).read())\n"
        "print('```')\n" % (str(dump), str(tmp_path / "findings.json")),
        encoding="utf-8")
    (tmp_path / "findings.json").write_text(findings_json, encoding="utf-8")
    return s


def test_inspect_real_spawn_chain_green(base_dir, tmp_path, monkeypatch, beats):
    dump = tmp_path / "dump.txt"
    script = _fake_dsh_script(
        tmp_path, dump,
        json.dumps({"findings": _fixture_findings(base_dir)}, ensure_ascii=False))
    monkeypatch.setenv("SANDBAR_INSPECT_CMD",
                       "%s %s" % (sys.executable, script))
    monkeypatch.setenv("FAKE_DUMP", str(dump))          # dict(os.environ) 透传给假脚本
    res = asyncio.run(aa.run_inspection_inspect(_args(base_dir, tmp_path)))
    assert res["ok"] is True, res
    fs = res["result"]["findings"]
    assert len(fs) == 1 and fs[0]["id"] == ins.mint_finding_id(fs[0])
    meta = res["result"]["meta"]
    assert meta["base_dir"] == str(base_dir) and Path(meta["output_log"]).is_file()
    # 本轮实际模型路由进 meta（方案 §2.1 观察期对账面）：两形态必居其一——
    # 命中={provider,model}；无表/无命中/复算失败={defaulted:True, reason:人读}。
    rm = meta["model_route"]
    assert isinstance(rm, dict) and (("provider" in rm and "model" in rm)
                                     or (rm.get("defaulted") is True and rm.get("reason")))
    # 不锁具体 provider/model——生效表是仓外运维面（人审通道），随机器而异。


def test_inspect_route_meta_recompute_failure_degrades_not_breaks(
        base_dir, tmp_path, monkeypatch, beats):
    """路由复算炸=meta 点名降级，spawn 主链照常绿（meta 面绝不弄挂 inspect）。

    注：routes_file_for_spawn 在活动内被调用两次——第 1 次在 _prepare_agent_spawn
    （预备面，炸=整段不可跑，属另一契约），第 2 次在 meta 复算面。本测只放炸第 2 次：
    首调透传真实现，再调抛错。"""
    dump = tmp_path / "dump2.txt"
    script = _fake_dsh_script(
        tmp_path, dump,
        json.dumps({"findings": _fixture_findings(base_dir)}, ensure_ascii=False))
    monkeypatch.setenv("SANDBAR_INSPECT_CMD", "%s %s" % (sys.executable, script))
    orig = aa.routes_file_for_spawn
    calls = {"n": 0}

    def _flaky(project):
        calls["n"] += 1
        if calls["n"] == 1:
            return orig(project)
        raise RuntimeError("复算注入（UT）")

    monkeypatch.setattr(aa, "routes_file_for_spawn", _flaky)
    res = asyncio.run(aa.run_inspection_inspect(_args(base_dir, tmp_path)))
    assert res["ok"] is True, res
    assert calls["n"] >= 2
    rm = res["result"]["meta"]["model_route"]
    assert rm.get("defaulted") is True and "路由复算失败" in rm.get("reason", "")

    raw = dump.read_text(encoding="utf-8")
    argv = raw.split("ARGV=")[1].split("\n")[0].split(chr(31))
    assert argv[-1].startswith("# 巡检审查任务")        # prompt 在 argv 末尾
    patches = [Path(argv[i + 1]) for i, v in enumerate(argv) if v == "--patch"]
    assert len(patches) == 2 and all(p.is_file() for p in patches)
    pin = [p for p in patches if "read-only" in p.read_text(encoding="utf-8")]
    # 260920 修正（宿主令「直接修」）：补丁自带 read-only 预设表项（sandbox read-only +
    # approval ask）+ defaultPreset 选它——dsh 0.1.1-rc.2 表里没有 'read-only'，直接引用会
    # boot 拒启（实案 t260920-02）；换 workspace-write 会把只读沙箱改写成可写，故补表项。
    assert pin and "defaultPreset: 'read-only'" in pin[0].read_text(encoding="utf-8")
    assert "        sandbox: 'read-only'" in pin[0].read_text(encoding="utf-8")
    assert ("DSH_HOME=%s" % (tmp_path / "agent-home")) in raw
    assert "CWD=%s" % base_dir in raw                   # cwd=审查基座
    # 退场干净：日志含进程输出；agent-home 里无 .dsh 泄漏到基座
    assert not (base_dir / ".dsh").exists()


def test_inspect_cmd_failure_and_garbage_named(base_dir, tmp_path, monkeypatch, beats):
    fail = tmp_path / "fail.py"
    fail.write_text("raise SystemExit(3)\n", encoding="utf-8")
    monkeypatch.setenv("SANDBAR_INSPECT_CMD", "%s %s" % (sys.executable, fail))
    res = asyncio.run(aa.run_inspection_inspect(_args(base_dir, tmp_path)))
    assert res["ok"] is False and "退出码 3" in res["error"]

    dumb = tmp_path / "dumb.py"
    dumb.write_text("print('没有任何围栏块')\n", encoding="utf-8")
    monkeypatch.setenv("SANDBAR_INSPECT_CMD", "%s %s" % (sys.executable, dumb))
    res = asyncio.run(aa.run_inspection_inspect(_args(base_dir, tmp_path)))
    assert res["ok"] is False and "解析失败" in res["error"]


def test_inspect_timeout_not_green_and_reaped(base_dir, tmp_path, monkeypatch, beats):
    sleeper = tmp_path / "fake_dsh_sleep.py"
    sleeper.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    monkeypatch.setenv("SANDBAR_INSPECT_CMD", "%s %s" % (sys.executable, sleeper))
    # 预算 0.5s < 复核余量 60s → 内部 deadline 即时到期（预算误配显性化路径，
    # 同时覆盖超时腿的 reap/不假绿语义；生产缺省 1800s 不受影响）
    res = asyncio.run(aa.run_inspection_inspect(
        _args(base_dir, tmp_path, timeout_sec=0.5)))
    assert res["ok"] is False
    assert "agent 未完成" in res["error"] and "不假绿" in res["error"]
    probe = subprocess.run(["pgrep", "-f", str(sleeper)], capture_output=True)
    assert probe.returncode != 0                        # 进程组已回收（零残留）
