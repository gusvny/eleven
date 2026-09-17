"""t260916-20 验收②：gitlink 形态路径 × 写集条目真值表（锁引擎侧判定源归一语义）。

背景（nusuyou t260916-08 实案）：gitlink 在 git diff/status 里的路径是目录名
（`content`，无尾斜杠），而写集条目惯写 `content/`（带尾斜杠）。引擎侧三处写集
判定源中两处（path_gates._entries 经 _within、agent_activities._dirty_within_write_set）
已对条目 `rstrip("/")` 归一——本表把该语义钉死防漂移（漂移=闸误判返场）。

已知残缺口（本票不修，交宿主）：server/tools/verify_lane.py `_in_write_set` 的
`path == e` 腿用原始条目未剥尾斜杠——`content` × `content/` 在该处判假，即事故里
「越界写: content」误诊文案的真源；该文件在 server/tools/，不在本票写集
（server/engine/; integration/）。

真值表即断言体，畸形输入用例全覆盖（非串/空/`..`/绝对路径/反斜杠/glob 哨兵/非列表）。
"""
import sys
from pathlib import Path

POC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC))

import pytest  # noqa: E402
from path_gates import _entries, _within  # noqa: E402
from agent_activities import _dirty_within_write_set  # noqa: E402


# ---------- _entries × _within（path_gates 写集判定源） ----------

@pytest.mark.parametrize("path,write_set,expected", [
    # 事故形态：gitlink 路径（无尾斜杠）× 写集条目（带尾斜杠）→ 必须判真
    ("content", ["content/"], True),
    ("content", ["content"], True),
    ("content/x.py", ["content/"], True),   # 前缀腿
    ("content", ["content//"], True),       # rstrip 剥掉全部尾斜杠
    ("content", ["content/x"], False),      # 条目更深 → 不覆盖目录名本身
    ("content", ["other/"], False),
    ("contentation", ["content/"], False),  # 前缀≠段边界：不能 startswith("content") 裸前缀
    ("content", "content/", False),         # 写集非列表 → 清洗失败 → 空条目 → 判假（fail-closed）
    ("content", [], False),
    ("content", None, False),
])
def test_within_gitlink_path_truth_table(path, write_set, expected):
    ok, pats = _entries(write_set)
    if not pats:
        assert expected is False, "条目清洗失败时 _within 必然判假"
        assert _within(path, pats) is False
    else:
        assert _within(path, pats) is expected


@pytest.mark.parametrize("bad", [[], [""], ["   "], [123], [None], ["a", 1], "content/", None])
def test_entries_malformed_write_set_fail_closed(bad):
    ok, pats = _entries(bad)
    assert ok is False and pats == []


def test_entries_normalizes_and_keeps_multiple():
    ok, pats = _entries(["content/", "app/src", " f.txt "])
    assert ok is True
    assert pats == ["content", "app/src", "f.txt"]


# ---------- _dirty_within_write_set（agent_activities KI-009 判定源） ----------

@pytest.mark.parametrize("files,write_set,expected", [
    # 事故形态同款：gitlink/未跟踪目录路径 × 带尾斜杠条目
    (["content"], ["content/"], True),
    (["content/x.py"], ["content/"], True),
    (["content/", "content/b.py"], ["content/"], True),  # 未跟踪目录折叠形态混在多文件里
    (["content/", "code.py"], ["content/"], False),      # 同批混入写集外文件 → 恒 False（fail-closed）
    (["content"], ["content"], True),
    (["content"], ["content/x"], False),
    (["content"], ["other"], False),
])
def test_dirty_within_gitlink_truth_table(files, write_set, expected):
    assert _dirty_within_write_set(files, write_set) is expected


@pytest.mark.parametrize("bad_files", [
    [], ["../x"], ["/abs/x"], ["a\\b"], ["a/../b"], ["a/.."], [None], [123], [""],
])
def test_dirty_within_malformed_files_fail_closed(bad_files):
    assert _dirty_within_write_set(bad_files, ["content/"]) is False


@pytest.mark.parametrize("bad_ws", [[], None, [""], ["  "], [123], "content/", {}])
def test_dirty_within_malformed_write_set_fail_closed(bad_ws):
    assert _dirty_within_write_set(["content"], bad_ws) is False


def test_dirty_within_both_clean_shape_still_true():
    # 健全路径回归面：归一不改变原有判定（防「修 gitlink 形态、坏普通形态」）
    assert _dirty_within_write_set(["app/src/a.py", "f.txt"], ["app/src", "f.txt"]) is True
