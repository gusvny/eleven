"""t260904-09 settle 出仓快照单测：幂等 / 失败软降级 / 零交付两态 / 畸形输入。

被测：agent_activities._freeze_settle_snapshot 及其两个子纯函数
（_squash_snapshot_delivery、_aggregate_lane_usage）、_settle_snapshot_dir。
UT 全程禁网络/真 Temporal；git 用 tmp 仓，zstd 用系统 CLI（缺则相关用例 skip）。
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import agent_activities as aa  # noqa: E402

KEY = "projkey"
TICKET = "t260904-09"


def _git(cwd, *args):
    p = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    return p.stdout.strip()


def _make_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "a.txt").write_text("one\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


def _commit(repo, msg, files=None):
    for name, content in (files or {"f.txt": "x\n"}).items():
        (repo / name).write_text(content)
        _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", msg)
    return _git(repo, "rev-parse", "--short", "HEAD")


def _zstd_file(path: Path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = "\n".join(lines) + "\n"
    src = path.with_suffix("")  # 去掉 .zstd 得压缩源路径
    src.write_text(raw)
    subprocess.run(["zstd", "-f", "-q", "-o", str(path), str(src)],
                   capture_output=True, check=True)
    src.unlink()
    assert path.exists()


def _usage_msg(i=10, o=20, c=5, model=None):
    out = []
    if model:
        out.append(json.dumps({"type": "request/context",
                               "data": {"provider": model[0], "model": model[1]}}))
    out.append(json.dumps({"type": "assistant/message",
                           "data": {"usage": {"inputTokens": i, "outputTokens": o,
                                              "cacheReadTokens": c}}}))
    # chunk 里同名 usage 是同一份，加了会翻倍——放进来验证不双算
    out.append(json.dumps({"type": "assistant/chunk",
                           "data": {"chunk": {"type": "usage"},
                                    "usage": {"inputTokens": i, "outputTokens": o}}}))
    return out


def _env(tmp_path, **kw):
    env = {"SANDBAR_SETTLE_SNAPSHOT_DIR": str(tmp_path / "snaproot")}
    env.update(kw)
    return env


@pytest.fixture
def clean_env(monkeypatch):
    for k in ("SANDBAR_SETTLE_SNAPSHOT_DIR", "SANDBAR_METRICS_DIR", "SANDBAR_PROJECTS_DIR"):
        monkeypatch.delenv(k, raising=False)
    yield monkeypatch


HAS_ZSTD = subprocess.run(["zstd", "--version"], capture_output=True).returncode == 0


def test_snapshot_dir_env_chain(tmp_path, clean_env):
    # env 替换项目根整体
    clean_env.setenv("SANDBAR_SETTLE_SNAPSHOT_DIR", "/tmp/snap-x")
    assert aa._settle_snapshot_dir(KEY) == Path("/tmp/snap-x") / KEY / "data" / "settle"
    # 次选 SANDBAR_METRICS_DIR
    clean_env.delenv("SANDBAR_SETTLE_SNAPSHOT_DIR")
    clean_env.setenv("SANDBAR_METRICS_DIR", "/tmp/m-x")
    assert aa._settle_snapshot_dir(KEY) == Path("/tmp/m-x") / KEY / "data" / "settle"
    # 空 key / 非法 key → None（快照跳过）
    assert aa._settle_snapshot_dir("") is None
    assert aa._settle_snapshot_dir("../evil") is None


def test_delivery_two_states(tmp_path, clean_env):
    repo = _make_repo(tmp_path)
    good = _commit(repo, "%s squash 收口（一单一提交，KI-006）" % TICKET,
                   {"f.txt": "line1\nline2\n"})
    # 二进制行跳过求和
    (repo / "bin.dat").write_bytes(b"\x00\x01")
    _git(repo, "add", "bin.dat")
    _git(repo, "commit", "-q", "-m", "%s 二次" % TICKET)
    good2 = _git(repo, "rev-parse", "--short", "HEAD")

    d, note = aa._squash_snapshot_delivery(repo, good, TICKET)
    assert d["zero_change"] is False and d["commits"] == 1
    assert d["squash_commit"] == good
    assert d["base"] == _git(repo, "rev-parse", "--short", good + "^1")

    # 他票 squash 在 HEAD（真·无内容可收）→ 零交付不取 numstat
    other = _commit(repo, "t9999-99 squash 收口（别的票）")
    d2, note2 = aa._squash_snapshot_delivery(repo, other, TICKET)
    assert d2["zero_change"] is True
    assert d2["add"] == 0 and d2["del"] == 0 and d2["commits"] == 0
    assert "非本票交付" in note2
    assert good2  # 前态可用


def test_aggregate_usage(tmp_path, clean_env):
    wt = tmp_path / "wt"
    sess = wt / ".dsh" / "sessions" / "slug" / TICKET
    if not HAS_ZSTD:
        pytest.skip("zstd CLI 不可用")
    _zstd_file(sess / "session.jsonl.zstd", _usage_msg(10, 20, 5, model=("p", "m1")))
    # 角色第二份会话（票号- 前缀目录）
    _zstd_file(wt / ".dsh" / "sessions" / "slug" / (TICKET + "-dev") / "session.jsonl.zstd",
               _usage_msg(1, 2, 3))
    # 他票会话不入选
    _zstd_file(wt / ".dsh" / "sessions" / "slug" / "t9999-99" / "session.jsonl.zstd",
               _usage_msg(100, 100, 100))
    tokens, note = aa._aggregate_lane_usage(wt, TICKET)
    assert tokens["in"] == 11 and tokens["out"] == 22 and tokens["cacheRead"] == 8
    assert tokens["by_model"] == {"p/m1": 30, "?/?": 3}  # 第二份会话无模型上下文 → 未知桶
    assert tokens["tokens_zero"] is False and tokens["by_stage_available"] is False
    assert note == ""


def test_aggregate_malformed_and_missing(tmp_path):
    wt = tmp_path / "wt2"
    # 无 sessions 目录 → 全零 + note，不抛
    tokens, note = aa._aggregate_lane_usage(wt, TICKET)
    assert tokens["in"] == 0 and tokens["tokens_zero"] is True and "无泳道会话目录" in note
    if not HAS_ZSTD:
        pytest.skip("zstd CLI 不可用")
    # 畸形：坏帧 + 坏行 + 非 usage 消息 → 坏的跳过、好的计入
    sess = wt / ".dsh" / "sessions" / "slug" / TICKET
    sess.mkdir(parents=True)
    (sess / "broken.zst").write_bytes(b"not-a-frame")  # 名字不带 session.jsonl.zstd，不入集
    good = sess / "session.jsonl.zstd"
    subprocess.run(["zstd", "-f", "-q", "-o", str(good),
                    "-"], input=b'{"bad json"\n' +
                   json.dumps({"type": "assistant/message",
                               "data": {"usage": {"inputTokens": 7, "outputTokens": 0}}}).encode()
                   + b"\n", capture_output=True)
    tokens2, note2 = aa._aggregate_lane_usage(wt, TICKET)
    assert tokens2["in"] == 7
    # 纯坏帧文件：解压失败不毁整体，tokens 记零
    (sess / "session.jsonl.zstd").write_bytes(b"\x28\xb5\x2f\xfdbroken")
    tokens3, note3 = aa._aggregate_lane_usage(wt, TICKET)
    assert tokens3["in"] == 0 and tokens3["tokens_zero"] is True
    assert "解压失败" in note3 or "usage" in note3


def test_freeze_idempotent_and_soft_fail(tmp_path, clean_env):
    repo = _make_repo(tmp_path)
    snap_root = tmp_path / "snaproot"
    clean_env.setenv("SANDBAR_SETTLE_SNAPSHOT_DIR", str(snap_root))
    if HAS_ZSTD:
        wt = tmp_path / "wt"
        _zstd_file(wt / ".dsh" / "sessions" / "slug" / TICKET / "session.jsonl.zstd",
                   _usage_msg(3, 4, 0, model=("p", "m")))
    else:
        wt = tmp_path / "wt-empty"
    c = _commit(repo, "%s squash 收口" % TICKET)

    note1 = aa._freeze_settle_snapshot(repo, wt, TICKET, KEY, c)
    assert "已落盘" in note1
    path = snap_root / KEY / "data" / "settle" / ("%s.json" % TICKET)
    first = json.loads(path.read_text())

    # 幂等：重复 settle 载荷一致 → 跳过、文件未动
    note2 = aa._freeze_settle_snapshot(repo, wt, TICKET, KEY, c)
    assert "跳过" in note2 and "幂等" in note2
    assert json.loads(path.read_text()) == first

    # 不一致（他票 commit）→ keep-old 不回写
    other = _commit(repo, "t9999 squash 收口", {"g.txt": "y\n"})
    note3 = aa._freeze_settle_snapshot(repo, wt, TICKET, KEY, other)
    assert "保留旧件" in note3
    assert json.loads(path.read_text()) == first

    # 无项目 key → 跳过 note，不落盘
    note4 = aa._freeze_settle_snapshot(repo, wt, "t2", "", c)
    assert "跳过" in note4

    # 票 id 路径穿越（integration W8）：`../` 注入 fail-closed 跳过，不落盘
    note_w8 = aa._freeze_settle_snapshot(repo, wt, "../escape_t260904-09", KEY, c)
    assert "形状非法" in note_w8
    assert not (snap_root / KEY / "data" / "escape_t260904-09.json").exists()
    assert not list(snap_root.rglob("*escape*"))

    # 旧快照畸形 JSON → keep-old
    path.write_text("{{{bad")
    note5 = aa._freeze_settle_snapshot(repo, wt, TICKET, KEY, c)
    assert "不可解析" in note5
    path.write_text(json.dumps(first))

    # 目录不可写（用只读目录冒充快照根）→ catch-all note，不抛
    ro = tmp_path / "ro"
    ro.mkdir()
    os.chmod(ro, 0o500)
    try:
        clean_env.setenv("SANDBAR_SETTLE_SNAPSHOT_DIR", str(ro))
        note6 = aa._freeze_settle_snapshot(repo, wt, "t3", KEY, c)
        assert "失败" in note6 and "不阻塞" in note6
    finally:
        os.chmod(ro, 0o700)


def test_squash_merge_wiring(tmp_path, clean_env):
    """接线验证：_squash_merge 落收口提交时快照随之落盘、warns 携带 note；
    project_key 缺省（向后兼容）时跳过、返回值不变。"""
    repo = _make_repo(tmp_path)
    snap_root = tmp_path / "snaproot"
    clean_env.setenv("SANDBAR_SETTLE_SNAPSHOT_DIR", str(snap_root))
    lane = tmp_path / "lane"
    _git(repo, "worktree", "add", "-q", "-b", "lane/%s" % TICKET, str(lane))
    (lane / "w.txt").write_text("work\n")
    _git(lane, "add", "-A")
    _git(lane, "commit", "-q", "-m", "stage")

    res = aa._squash_merge(repo, lane, "lane/%s" % TICKET, TICKET,
                           defer_teardown=True, project_key=KEY)
    assert res.ok is True
    snap = snap_root / KEY / "data" / "settle" / ("%s.json" % TICKET)
    assert snap.exists()
    payload = json.loads(snap.read_text())
    assert payload["delivery"]["squash_commit"] == res.merge_commit
    assert payload["delivery"]["commits"] == 1
    assert "settle 快照" in res.error

    # 缺省 project_key：不落新盘（t9999 票名）、行为兼容
    lane2 = tmp_path / "lane2"
    _git(repo, "worktree", "add", "-q", "-b", "lane/t2", str(lane2))
    (lane2 / "w2.txt").write_text("w2\n")
    _git(lane2, "add", "-A")
    _git(lane2, "commit", "-q", "-m", "s2")
    res2 = aa._squash_merge(repo, lane2, "lane/t2", "t2", defer_teardown=True)
    assert res2.ok is True
    assert not (snap_root / KEY / "data" / "settle" / "t2.json").exists()
    assert "跳过" in res2.error
