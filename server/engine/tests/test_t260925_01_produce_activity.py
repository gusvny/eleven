"""t260925-01 票：produce 段活动层单测（run_inspection_produce）。

覆盖（方案步3）：
- 输入闸 fail-closed（缺 instance/period/base_dir、base 不存在）；
- 桩子用例：合法夹具→铸 id+四闸结果返回（桩-闸不同源：夹具只供围栏，差分/自检照跑）；
  畸形夹具/夹具缺失→点名失败（与真 agent 同契约）；
- 写集闸接线（A2）：夹具声明越界路径 + 泳道真有越界文件 → out_of_root 点名；
- 保护面闸接线（A3）：碰 docs/design → protected_overlap 点名且不硬失败；
- 零 change 显式（A5）：零 change 声明缺证据 → zero_change_error 判红；
- 真 spawn 链（SANDBAR_PRODUCE_CMD 注入假脚本）：argv 末尾=persona/write 两 patch+
  prompt、写 pin=workspace-write 形态、围栏解析、超时→不假绿。
桩/假脚本桩固定文件复现，不靠真外部源。
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
import inspection_produce as prod  # noqa: E402


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBAR_INSPECTION_DIR", str(tmp_path / "ledger"))
    monkeypatch.delenv("SANDBAR_PRODUCE_STUB", raising=False)
    monkeypatch.delenv("SANDBAR_PRODUCE_STUB_FILE", raising=False)
    monkeypatch.delenv("SANDBAR_PRODUCE_CMD", raising=False)
    # 钉 host 形态：本文件测 host spawn 链（force_host）；runner 侧若带 docker 旋钮
    # （生产 worker env 泄漏）会让 spawn 面触发真实 docker 探针——单测哨兵红且与被测
    # 对象无关（merge_check gen4 实案）。相对字节码缓存前缀同理双保险。
    monkeypatch.delenv("SANDBAR_AGENT_RUNTIME", raising=False)
    monkeypatch.delenv("SANDBAR_AGENT_IMAGE", raising=False)
    monkeypatch.delenv("PYTHONPYCACHEPREFIX", raising=False)
    yield


@pytest.fixture(autouse=True)
def beats(monkeypatch):
    """活动上下文外的 heartbeat 直录（temporalio 活动外调用本会 raise）。"""
    got = []
    monkeypatch.setattr(activity_mod, "heartbeat", lambda *a, **k: got.append(a))
    yield got


@pytest.fixture()
def lane(tmp_path: Path) -> Path:
    """git 泳道（隔离台，非 worktree）：有提交基线 + docs/ 树。"""
    d = tmp_path / "lane"
    (d / "docs").mkdir(parents=True)
    (d / "docs" / "a.md").write_text(
        "---\ntitle: A\ncategory: design\ntags: [x]\nstatus: active\n"
        "updated: 2026-09-25\n---\n# A\n", encoding="utf-8")
    (d / "docs" / "index.json").write_text(
        '{"docs": [{"path": "docs/a.md"}]}', encoding="utf-8")
    env = dict(os.environ, GIT_CEILING_DIRECTORIES=str(tmp_path))
    for cmd in (["git", "-C", str(d), "init", "-q"],
                ["git", "-C", str(d), "config", "user.email", "t@t"],
                ["git", "-C", str(d), "config", "user.name", "t"],
                ["git", "-C", str(d), "add", "-A"], ["git", "-C", str(d), "commit", "-qm", "base"]):
        subprocess.run(cmd, check=True, capture_output=True, env=env)
    return d


def _args(lane: Path, tmp_path: Path, **kw) -> dict:
    a = {"instance_id": "doc-sync", "period": "20260925", "ticket_id": "t260925-01",
         "docs_root": "docs", "base_dir": str(lane),
         "agent_home": str(tmp_path / "agent-home"), "timeout_sec": 120}
    a.update(kw)
    return a


def _stub(monkeypatch, fence: str, tmp_path: Path) -> Path:
    f = tmp_path / "stub-fence.json"
    f.write_text(fence, encoding="utf-8")
    monkeypatch.setenv("SANDBAR_PRODUCE_STUB", "1")
    monkeypatch.setenv("SANDBAR_PRODUCE_STUB_FILE", str(f))
    return f


# ---------- 输入闸 ----------

@pytest.mark.parametrize("mutate", [
    {"instance_id": ""}, {"period": ""}, {"base_dir": ""},
])
def test_input_gates_fail_closed(lane, tmp_path, monkeypatch, mutate):
    _stub(monkeypatch, GOOD, tmp_path)
    args = _args(lane, tmp_path)
    args.update(mutate)
    r = asyncio.run(aa.run_inspection_produce(args))
    assert r["ok"] is False and "fail-closed" in r["error"]


def test_base_missing_fail_closed(tmp_path):
    r = asyncio.run(aa.run_inspection_produce(_args(tmp_path / "nope", tmp_path)))
    assert r["ok"] is False and "不存在" in r["error"]


GOOD = ('```json\n{"changes": [{"path": "docs/a.md", "action": "modify",'
        ' "summary": "补链接"}], "zero_change": false, "evidence": []}\n```')


# ---------- 桩链（差分+自检照跑） ----------

def test_stub_green(lane, tmp_path, monkeypatch, beats):
    (lane / "docs" / "a.md").write_text("# A 更新\n", encoding="utf-8")
    # 引擎协调目录（spawn 预备面产物）必须被差分滤除——否则写集闸误报越界
    #（验收 gen1 实案：.sandbar 进 diff → A2 误红）
    (lane / ".sandbar" / "coord").mkdir(parents=True)
    (lane / ".sandbar" / "coord" / "junk").write_text("x\n", encoding="utf-8")
    _stub(monkeypatch, GOOD, tmp_path)
    r = asyncio.run(aa.run_inspection_produce(_args(lane, tmp_path)))
    assert r["ok"] is True
    res = r["result"]
    assert res["changes"][0]["path"] == "docs/a.md" and res["changes"][0]["id"]
    assert res["selfcheck"]["out_of_root"] == []
    assert res["selfcheck"]["protected_overlap"] == []
    assert res["selfcheck"]["zero_change_error"] == ""
    assert res["selfcheck"]["all_paths"] == ["docs/a.md"]  # 差分真源=git（.sandbar 已滤）
    assert beats


def test_stub_out_of_root_named(lane, tmp_path, monkeypatch):
    (lane / "src.py").write_text("x = 2\n", encoding="utf-8")
    bad = GOOD.replace('"changes": [{"path": "docs/a.md", "action": "modify",'
                       ' "summary": "补链接"}]',
                       '"changes": [{"path": "src.py", "action": "modify",'
                       ' "summary": "改代码（越界）"}]')
    _stub(monkeypatch, bad, tmp_path)
    r = asyncio.run(aa.run_inspection_produce(_args(lane, tmp_path)))
    assert r["ok"] is True  # 活动不失败——拒收是自检结论，落盘权在人审
    oor = r["result"]["selfcheck"]["out_of_root"]
    assert {h["path"] for h in oor} == {"src.py"}
    assert "docs" in oor[0]["reason"]


def test_stub_protected_overlap_named_not_failed(lane, tmp_path, monkeypatch):
    (lane / "docs" / "design").mkdir()
    (lane / "docs" / "design" / "d.md").write_text("drift\n", encoding="utf-8")
    _stub(monkeypatch, GOOD.replace("docs/a.md", "docs/design/d.md"), tmp_path)
    r = asyncio.run(aa.run_inspection_produce(_args(lane, tmp_path)))
    assert r["ok"] is True
    assert r["result"]["selfcheck"]["protected_overlap"] == ["docs/design", "docs/design/d.md"]


def test_stub_zero_change_missing_evidence_red(lane, tmp_path, monkeypatch):
    zc = ('```json\n{"changes": [], "zero_change": true, "evidence": []}\n```')
    _stub(monkeypatch, zc, tmp_path)
    r = asyncio.run(aa.run_inspection_produce(_args(lane, tmp_path)))
    assert "evidence" in r["result"]["selfcheck"]["zero_change_error"]


def test_stub_doc_selfcheck_wired(lane, tmp_path, monkeypatch):
    (lane / "docs" / "b.md").write_text("# B\n", encoding="utf-8")  # 缺登记
    _stub(monkeypatch, GOOD, tmp_path)
    r = asyncio.run(aa.run_inspection_produce(_args(lane, tmp_path)))
    finds = r["result"]["selfcheck"]["doc_findings"]
    assert any(f["check"] == "index" and "缺登记" in f["detail"] for f in finds)


def test_stub_malformed_fixture_named(lane, tmp_path, monkeypatch):
    _stub(monkeypatch, "```json\nnope\n```", tmp_path)
    r = asyncio.run(aa.run_inspection_produce(_args(lane, tmp_path)))
    assert r["ok"] is False and "fail-closed" in r["error"]


def test_stub_fixture_missing_named(lane, tmp_path, monkeypatch):
    monkeypatch.setenv("SANDBAR_PRODUCE_STUB", "1")
    monkeypatch.setenv("SANDBAR_PRODUCE_STUB_FILE", str(tmp_path / "absent.json"))
    r = asyncio.run(aa.run_inspection_produce(_args(lane, tmp_path)))
    assert r["ok"] is False and "夹具缺失" in r["error"]


# ---------- 真 spawn 链（SANDBAR_PRODUCE_CMD 注入假脚本） ----------

def test_real_spawn_chain_with_fake_dsh(lane, tmp_path, monkeypatch):
    (lane / "docs" / "a.md").write_text("# A 更新\n", encoding="utf-8")
    script = tmp_path / "fake-dsh.py"
    script.write_text(
        "import sys\n"
        "args = sys.argv[1:]\n"
        "assert '--patch' in args and any('write' in p for p in args), args\n"
        "prompt = args[-1]\n"
        "sys.stderr.write(prompt[:80])\n"
        "print('junk line')\n"
        "print('```json')\n"
        "print('{\"changes\": [{\"path\": \"docs/a.md\", \"action\": \"modify\","
        " \"summary\": \"s\"}], \"zero_change\": false, \"evidence\": []}')\n"
        "print('```')\n", encoding="utf-8")
    monkeypatch.setenv("SANDBAR_PRODUCE_CMD",
                       "%s %s" % (sys.executable, script))
    r = asyncio.run(aa.run_inspection_produce(_args(lane, tmp_path)))
    assert r["ok"] is True, r.get("error")
    assert r["result"]["selfcheck"]["out_of_root"] == []
    # 写 pin 文件落 agent_home 且为 workspace-write 形态（非只读钉）
    pin = Path(r["result"]["meta"]["agent_home"]) / "patch_produce_write.yml"
    assert pin.is_file() and "workspace-write" in pin.read_text(encoding="utf-8")


def test_real_spawn_timeout_no_fake_green(lane, tmp_path, monkeypatch):
    script = tmp_path / "hang.py"
    script.write_text("import time; time.sleep(30)\n", encoding="utf-8")
    monkeypatch.setenv("SANDBAR_PRODUCE_CMD", "%s %s" % (sys.executable, script))
    r = asyncio.run(aa.run_inspection_produce(
        _args(lane, tmp_path, timeout_sec=prod.PRODUCE_DEADLINE_MARGIN_SEC + 5)))
    assert r["ok"] is False and "超时" in r["error"]
