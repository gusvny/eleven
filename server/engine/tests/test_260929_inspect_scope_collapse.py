"""260929 单测（宿主令）：无泳道实例的审查基点自播种（口径 A）+ 范围塌陷上票面。

起因（260929 宿主质询「simplify 的速度这么快，有好好看代码吗」）：simplify-face 那期
3 分 15 秒跑完，`scan_meta.inspect.scope_files = 0`——**它一行代码没看**。根因三段：
  ① 声明不带 suite 的实例**从不建泳道**（`inspection_flow.py:1351` 的 `if run_suite:`）；
  ② 本期基点＝泳道 base_ref ⇒ 空（`inspection_flow.py:1431`）；
  ③ 差分要求「上期基点 + 本期基点」都不空 ⇒ 整段跳过，范围只剩 KI 册/上期台账/回执。
而这条塌陷此前**只躺在 meta.scope_note 里**，票面看不出来 ⇒「跑完」被读成「审过」。

宿主 260929 裁定（两件）：
  - 范围口径=**A**：无泳道实例用「上期运行记录的 HEAD → 本期 HEAD」（自上次巡检以来
    main 动了什么），与申报式空转 skip_when_unchanged 同一基准面；本期取不到上期记录时
    **先自播种**（取当前 HEAD 记进台账，下期起可差分）；
  - 塌陷的处置=**记在票上，不记 KI 册**：零文件范围必须出 `scan="scope"` 发现。

运行：server/engine/.venv/bin/python -B -m pytest \
      server/engine/tests/test_260929_inspect_scope_collapse.py -q
"""
import asyncio
import json
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from temporalio import activity as activity_mod

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import agent_activities as aa  # noqa: E402
import inspection_inspect as ins  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    assert p.returncode == 0, "git %s 失败：%s" % (" ".join(args), (p.stderr or "").strip()[-200:])
    return (p.stdout or "").strip()


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """真 git 仓（两提交）：c1 建 a.py，c2 改 a.py 并新增 b.py。"""
    d = tmp_path / "repo"
    d.mkdir()
    _git(d, "init")
    _git(d, "config", "user.email", "t@example.com")
    _git(d, "config", "user.name", "t")
    (d / "a.py").write_text("value = 1\n", encoding="utf-8")
    _git(d, "add", "a.py")
    _git(d, "commit", "-m", "c1")
    (d / "a.py").write_text("value = 2\n", encoding="utf-8")
    (d / "b.py").write_text("other = 1\n", encoding="utf-8")
    _git(d, "add", "-A")
    _git(d, "commit", "-m", "c2")
    return d


@pytest.fixture()
def beats(monkeypatch):
    got = []
    monkeypatch.setattr(activity_mod, "heartbeat", lambda *a, **k: got.append(a))
    return got


@pytest.fixture()
def fake_dsh(tmp_path: Path, monkeypatch):
    """假 dsh：把 prompt 存档，末尾输出空 findings 围栏（零模型调用，真进程链同路）。"""
    out = tmp_path / "prompt_capture.txt"
    script = tmp_path / "fake_dsh.py"
    script.write_text(
        "import sys\n"
        "open(%r, 'w', encoding='utf-8').write(sys.argv[-1])\n"
        "print('no new defects')\n"
        "print('```json')\n"
        "print('{\"findings\": []}')\n"
        "print('```')\n" % str(out), encoding="utf-8")
    sh = tmp_path / "fake_dsh.sh"
    sh.write_text("#!/bin/sh\nexec %s %s \"$@\"\n" % (sys.executable, script), encoding="utf-8")
    sh.chmod(sh.stat().st_mode | stat.S_IEXEC)
    monkeypatch.delenv("SANDBAR_INSPECT_STUB", raising=False)
    monkeypatch.setenv("SANDBAR_INSPECT_CMD", "%s --patch p1 --patch p2" % sh)
    return out


def _args(base: Path, tmp: Path, **kw) -> dict:
    a = {"instance_id": "simplify-face", "period": "20260929", "ticket_id": "t1",
         "face": "simplify", "base_dir": str(base), "base_head": "",
         "agent_home": str(tmp / "agent-home"), "timeout_sec": 120,
         "ledger_dir": str(tmp), "suite_receipt": str(tmp / "none-suite.json")}
    a.update(kw)
    return a


def _prev_ledger(tmp: Path, period: str, base: str = "") -> Path:
    p = tmp / ("inspection-simplify-face-%s.json" % period)
    doc = {"findings": [], "period": period}
    if base:
        doc["scan_meta"] = {"inspect": {"base_head": base}}
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


# ---------------- 口径 A：上期记录的 HEAD → 本期 HEAD ----------------

def test_prev_recorded_head_gives_a_real_change_surface(repo, tmp_path, beats, fake_dsh):
    """上期台账记过 HEAD（c1）→ 本期 HEAD 是 c2 ⇒ 变化面**真有文件**，且清单进 prompt。"""
    c1 = _git(repo, "rev-parse", "HEAD~1")
    _prev_ledger(tmp_path, "20260928", base=c1)
    res = asyncio.run(aa.run_inspection_inspect(_args(repo, tmp_path)))
    assert res["ok"] is True, res
    meta = res["result"]["meta"]
    assert meta["scope"]["scope_files"] == 2, meta["scope"]        # a.py 改 + b.py 新增
    assert meta["scope_base_prev"] == c1
    assert meta["scope_effective_base"] == _git(repo, "rev-parse", "HEAD")
    prompt = fake_dsh.read_text(encoding="utf-8")
    assert "a.py" in prompt and "b.py" in prompt, "变化面清单必须真的进审查范围"
    assert not [f for f in res["result"]["findings"] if f.get("scan") == "scope"], \
        "有真变化面 ⇒ 不许出塌陷发现"


def test_no_prev_base_never_self_seeds(repo, tmp_path, beats, fake_dsh):
    """t261006-13 B2 closure: no lane and no previous record means NEVER self-seed —
    HEAD may serve only as this period's diff ENDPOINT and must not be recorded as a
    future previous-period base (self-seeding erases the diff = the period reviewed
    nothing). With no real base the scope-collapse finding still lands on the ticket
    face (in production the workflow additionally blocks the whole period on
    surface=unavailable; this activity face is defence in depth)."""
    res = asyncio.run(aa.run_inspection_inspect(_args(repo, tmp_path)))
    assert res["ok"] is True, res
    meta = res["result"]["meta"]
    head = _git(repo, "rev-parse", "HEAD")
    # HEAD is the endpoint (the diff is possible), and the note names "endpoint only"
    assert meta["scope_effective_base"] == head
    assert "never recorded as a future prev-base" in meta["scope"].get("this_base_source", "")
    assert "\u81ea\u64ad\u79cd" not in json.dumps(meta, ensure_ascii=False), \
        "the self-seed wording is deleted (B2): meta must not carry it"
    scope_fs = [f for f in res["result"]["findings"] if f.get("scan") == "scope"]
    assert len(scope_fs) == 1 and scope_fs[0]["severity"] == "med", \
        "no real base must be stated on the ticket face (defence-in-depth face intact)"


def test_no_new_commits_is_not_a_collapse(repo, tmp_path, beats, fake_dsh):
    """真无变化（上期基点==HEAD）**不算塌陷**：合法的「本期没动」，不许报。"""
    head = _git(repo, "rev-parse", "HEAD")
    _prev_ledger(tmp_path, "20260928", base=head)
    res = asyncio.run(aa.run_inspection_inspect(_args(repo, tmp_path)))
    assert res["ok"] is True, res
    assert res["result"]["meta"]["scope"]["scope_files"] == 0
    assert not [f for f in res["result"]["findings"] if f.get("scan") == "scope"], \
        "有基点、diff 成功、零改动＝合法空范围，不该报塌陷（否则天天假红）"


# ---------------- 塌陷判据（纯函数） ----------------

def test_collapse_finding_contract():
    f = ins.scope_collapse_findings(
        {"scope_files": 0, "scope_note": "无基点差分：对照上期 20260915——变化面差分未做"})
    assert len(f) == 1
    got = f[0]
    assert got["scan"] == "scope" and got["severity"] == "med"
    assert "did NOT review code" in got["subject"], "主题必须说清「没审到代码」，不含糊"
    assert got["suggest"] is False, "范围塌陷是引擎缺陷/声明缺基点，不该自动开修码票"
    assert isinstance(got["evidence"], list) and got["evidence"][0]["quote"]
    assert "sweep" not in json.dumps(got) or True   # 形状可 JSON 序列化（票面/台账都吃它）


@pytest.mark.parametrize("meta,expect", [
    ({}, 0),                                    # 无 scope meta：非本判据面
    ({"scope_files": 0}, 0),                    # 有基点、真无变化：合法
    ({"scope_files": 3}, 0),                    # 有范围：正常
    ({"scope_files": 0, "scope_note": "无基点差分：x"}, 1),
    ({"scope_files": 0, "diff_error": "git diff 失败（rc=128）"}, 1),
    ({"scope_files": 0, "diff_error": ""}, 0),  # 空串=没失败
    (None, 0),
])
def test_collapse_discrimination(meta, expect):
    assert len(ins.scope_collapse_findings(meta)) == expect


def test_collapse_finding_is_minted_with_an_id_by_the_activity():
    """活动侧统一铸 id（不信任自报）——塌陷发现走同一条 with_ids 路。"""
    from inspection_inspect import mint_finding_id
    f = ins.with_ids(ins.scope_collapse_findings(
        {"scope_files": 0, "scope_note": "无基点差分：x"}))[0]
    assert f["id"] == mint_finding_id(f) and f["scan"] == "scope"
