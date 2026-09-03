"""KI-015 回归永久化（t260902-10）：_sh 输出裁剪 / _diff_names crop=None。

历史缺陷（t260902-05 实证）：_sh 把输出裁到最后 2000 字节，白名单 diff 大时
①首行被裁成半截路径 → 假越界误阻断；②裁点之前的文件静默漏检。
修复 = _sh 加 crop 参数 + _diff_names 传 crop=None。本文件把修复锁死。

subprocess 全桩（monkeypatch），不真跑 git。
"""
import subprocess

import pytest

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))

import verify_lane


class FakeCompleted:
    def __init__(self, out):
        self.returncode = 0
        self.stdout = out
        self.stderr = ""


# ~2349 字节多行路径 diff（KI-015 实证形态：末 2000 字节裁点落在首行中间）。
BIG_DIFF = "".join("server/dsh/workbench/src/ticket-detail/ticket-row-%03d.tsx\n" % i
                   for i in range(41))
assert 2200 < len(BIG_DIFF.encode()) < 2500


@pytest.fixture()
def git_diff(monkeypatch):
    """桩掉 verify_lane.subprocess.run，记录调用并回放 BIG_DIFF。"""
    calls = []

    def fake_run(cmd, cwd=None, capture_output=False, text=False, timeout=None):
        calls.append({"cmd": cmd, "timeout": timeout})
        return FakeCompleted(BIG_DIFF)

    monkeypatch.setattr(verify_lane.subprocess, "run", fake_run)
    return calls


def test_sh_default_crops_tail(monkeypatch):
    """默认 crop=2000 保留历史行为（人类可读 detail 允许裁）——顺带复现问题形态。"""
    monkeypatch.setattr(verify_lane.subprocess, "run",
                        lambda *a, **k: FakeCompleted(BIG_DIFF))
    rc, out = verify_lane._sh(["git", "diff"], "/tmp")
    assert rc == 0
    assert len(out) == 2000
    assert not out.startswith("server/")  # 首行已被裁成半截（缺陷形态复现）


def test_diff_names_passes_crop_none_and_full_output(git_diff):
    """回归锁①：_diff_names 必须显式传 crop=None（桩断言实参），输出全量、首行完整。"""
    rc, out = verify_lane._diff_names("main", "/tmp")
    assert rc == 0
    cmd = git_diff[0]["cmd"]
    assert "core.quotepath=false" in cmd and "--name-only" in cmd and "main...HEAD" in cmd
    lines = out.splitlines()
    assert len(lines) == 41
    assert all(l.startswith("server/") and l.endswith(".tsx") for l in lines), "首行/行完整性"


def test_no_silent_miss_via_code_pipeline(git_diff, tmp_path):
    """回归锁②：大 diff 裁点前文件不静默漏检——经 _code 全链路每个文件都被判。"""
    (tmp_path / "verify.yaml").write_text(
        "schema: v1\nlanes:\n  code:\n    write_allow:\n      - server/\n", "utf-8")
    # 显式传零写集：若漏检（某文件没被 _in_write_set 判到），不会出越界红——
    # 所以「红 items 数 = diff 行数」即证明每个文件都被逐行判到。
    r = verify_lane.run({"lane": "code", "path": str(tmp_path),
                         "base": "main", "write_set": []})
    wl = [c for c in r["checks"] if c["check"] == "写集白名单"][0]
    assert not r["green"]  # 零写集 + 41 个文件 → 必红
    assert len(wl["items"]) == 41  # 每个文件各一条越界，无合并无漏检
    assert all("越界写" in i["detail"] for i in wl["items"])


def test_diff_first_line_not_truncated_in_pipeline(git_diff, tmp_path):
    """回归锁③（与人为裁剪基线对比）：全链路产出的假路径数=0（KI-015 实证里
    「ial/token-30d.json」这类半截路径假红不允许再现）。"""
    (tmp_path / "verify.yaml").write_text(
        "schema: v1\nlanes:\n  code:\n    write_allow:\n      - server/\n", "utf-8")
    r = verify_lane.run({"lane": "code", "path": str(tmp_path), "base": "main"})
    wl = [c for c in r["checks"] if c["check"] == "写集白名单"][0]
    assert wl["level"] == "green"  # 全部落 write_allow：无任何红
    assert not any("ial/" in i["detail"] for i in wl["items"])  # 无半截路径
