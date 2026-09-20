"""t260916-23 会话文件双名兼容引擎面 UT（epic dsh-upgrade T1 读侧前置）。

被测：agent_activities.SESSION_FILE_NAMES / _iter_session_files / _pick_newest_session、
_quarantine_torn_sessions（双名全量清扫）、_aggregate_lane_usage（两层半径钉死 +
同目录双代取 mtime 最新一份）。

票面验收①五态矩阵：仅旧名 / 仅新名 / 双名并存（mtime 双方向 + 平局）/ 皆无 /
损坏半行文件（发现层照常返回——名字层不读内容；检疫层隔离）。
review C2 负向子用例：两层布局以外（一层 / 三层）的同名档不入统计集。
review C3 守卫子用例：src 面旧名字面必须双名配对 / 落常量 / 带标记（取舍清单见
test_src_tree_session_literal_paired docstring；合成样本自证红绿随守卫交付）。
零回归锚：只造旧名文件的用例结果与改前语义一致（既有 test_t260905_10_t01 /
test_t260904_09 套件不改一字并行跑绿）。
UT 全程禁网络/真 Temporal/真 git；zstd 用系统 CLI（缺则整文件 skip）。
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agent_activities as aa  # noqa: E402
from agent_activities import (  # noqa: E402
    SESSION_FILE_NAMES,
    _iter_session_files,
    _pick_newest_session,
    _quarantine_torn_sessions,
)

pytestmark = pytest.mark.skipif(shutil.which("zstd") is None,
                                reason="zstd CLI 缺席（引擎读侧既有依赖，缺供即环境红）")

TICKET = "t260916-23"
OLD, NEW = "session.jsonl.zstd", "session.v3.jsonl.zstd"


# ---------- 夹具工具 ----------

def _zstd_bytes(raw: bytes) -> bytes:
    """zstd 压一段字节（走被测代码同款 CLI 依赖）。"""
    p = subprocess.run(["zstd", "-z", "-c"], input=raw, capture_output=True, check=True)
    return p.stdout


def _write_bin(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _jsonl_bytes(objs: list, tail: bytes = b"") -> bytes:
    out = b"".join((json.dumps(o) + "\n").encode() for o in objs)
    return out + tail


def _usage_bytes(i: int, o: int, c: int) -> bytes:
    return _zstd_bytes(_jsonl_bytes([
        {"type": "request/context", "data": {"provider": "p", "model": "m1"}},
        {"type": "assistant/message", "data": {"usage": {
            "inputTokens": i, "outputTokens": o, "cacheReadTokens": c}}},
    ]))


def _sub(wt: Path, name: str) -> Path:
    """三层布局：wt/.dsh/sessions/<slug>/<sub>/。"""
    return wt / ".dsh" / "sessions" / "slug0" / name


def _set_mtime(path: Path, t: float) -> None:
    os.utime(path, (t, t))


def _quarantine_dir(dsh: Path) -> Path:
    return dsh.parent / ".sandbar" / "quarantine"


# ---------- 常量形状（守卫与行为的锚点） ----------

def test_session_file_names_shape():
    """两代名取值与顺序钉死：[0]=旧代（平局优先）、[1]=新代 0.1.5+。"""
    assert SESSION_FILE_NAMES == ("session.jsonl.zstd", "session.v3.jsonl.zstd")


# ---------- 发现层五态（票面验收①） ----------

def test_iter_only_old(tmp_path):
    root = tmp_path / "sessions"
    _write_bin(root / "a" / OLD, b"x")
    assert _iter_session_files(root) == [root / "a" / OLD]


def test_iter_only_new(tmp_path):
    root = tmp_path / "sessions"
    _write_bin(root / "a" / NEW, b"x")
    assert _iter_session_files(root) == [root / "a" / NEW]


def test_iter_both_generations_sorted(tmp_path):
    root = tmp_path / "sessions"
    _write_bin(root / "b" / NEW, b"x")
    _write_bin(root / "a" / OLD, b"x")
    assert _iter_session_files(root) == [root / "a" / OLD, root / "b" / NEW]  # sorted 路径序


def test_iter_none_and_missing_root(tmp_path):
    root = tmp_path / "sessions"
    root.mkdir()
    assert _iter_session_files(root) == []          # 空目录
    assert _iter_session_files(tmp_path / "absent") == []  # 根缺失


def test_iter_skips_directory_named_like_session(tmp_path):
    """畸形输入：同名**目录**不算会话文件（is_file 守卫）。"""
    root = tmp_path / "sessions"
    (root / "a" / NEW).mkdir(parents=True)
    _write_bin(root / "b" / OLD, b"x")
    assert _iter_session_files(root) == [root / "b" / OLD]


# ---------- pick 层：mtime 双方向 + 平局 + stat 失败 ----------

def test_pick_new_mtime_wins(tmp_path):
    a = _write_bin(tmp_path / OLD, b"a")
    b = _write_bin(tmp_path / NEW, b"b")
    _set_mtime(a, 1000)
    _set_mtime(b, 2000)
    assert _pick_newest_session([a, b]) == b


def test_pick_old_mtime_wins(tmp_path):
    """语义=取最新（不偏袒新代）：旧代 mtime 更新时选旧代。"""
    a = _write_bin(tmp_path / OLD, b"a")
    b = _write_bin(tmp_path / NEW, b"b")
    _set_mtime(a, 3000)
    _set_mtime(b, 2000)
    assert _pick_newest_session([a, b]) == a


def test_pick_tie_prefers_old_name(tmp_path):
    a = _write_bin(tmp_path / OLD, b"a")
    b = _write_bin(tmp_path / NEW, b"b")
    _set_mtime(a, 2000)
    _set_mtime(b, 2000)
    assert _pick_newest_session([a, b]) == a  # 平局旧名（与「只有旧名」现状对齐）


def test_pick_skips_unreadable_stat(tmp_path):
    """畸形输入：stat 不可读的候选跳过（如并发被挪走），余者照选。"""
    a = _write_bin(tmp_path / OLD, b"a")
    ghost = tmp_path / "ghost" / OLD  # 不存在 → stat 失败
    assert _pick_newest_session([ghost, a]) == a
    assert _pick_newest_session([ghost]) is None


# ---------- 检疫面：双代全量清扫（不取最新——回退安全） ----------

def test_quarantine_torn_new_generation(tmp_path):
    """撕裂新名档（帧裂）同样被隔离——升级后读侧不吃坏帧。"""
    payload = _zstd_bytes(_jsonl_bytes([{"t": 1}]))
    dsh = tmp_path / "dshhome"
    f = _write_bin(dsh / "sessions" / "t-a-developer" / NEW, payload[:int(len(payload) * 0.6)])
    assert subprocess.run(["zstd", "-t", str(f)], capture_output=True).returncode != 0
    _quarantine_torn_sessions(dsh)
    assert not f.exists()
    assert (_quarantine_dir(dsh) / ("torn-t-a-developer-" + NEW)).is_file()


def test_quarantine_old_generation_regression(tmp_path):
    """旧名撕裂档照旧隔离（改前语义回归锚，含「torn-<父目录>-<名>」命名不变）。"""
    payload = _zstd_bytes(_jsonl_bytes([{"t": 1}, {"t": 2}]))
    dsh = tmp_path / "dshhome"
    f = _write_bin(dsh / "sessions" / "t-b-developer" / OLD, payload[:int(len(payload) * 0.6)])
    _quarantine_torn_sessions(dsh)
    assert not f.exists()
    assert (_quarantine_dir(dsh) / ("torn-t-b-developer-" + OLD)).is_file()


def test_quarantine_mixed_old_torn_new_good(tmp_path):
    """双名并存：只挪坏档，好档不连坐（哪怕好档是新代、坏档 mtime 更新）。"""
    good = _zstd_bytes(_jsonl_bytes([{"t": 1}, {"t": 2}]))
    torn = _zstd_bytes(_jsonl_bytes([{"t": 1}]))
    dsh = tmp_path / "dshhome"
    sub = dsh / "sessions" / "t-c-developer"
    fo = _write_bin(sub / OLD, torn[:int(len(torn) * 0.6)])
    fn = _write_bin(sub / NEW, good)
    _set_mtime(fo, 5000)
    _set_mtime(fn, 1000)
    _quarantine_torn_sessions(dsh)
    assert not fo.exists()
    assert fn.is_file()
    assert (_quarantine_dir(dsh) / ("torn-t-c-developer-" + OLD)).is_file()


def test_quarantine_mixed_old_good_new_torn_jsonl(tmp_path):
    """反向并存：好帧内截半的新名档被逐行试析兜住隔离，旧名好档不动。"""
    good = _zstd_bytes(_jsonl_bytes([{"t": 1}, {"t": 2}]))
    torn_jsonl = _zstd_bytes(b'{"t":1}\n{"t":2,"cut')  # 帧完整、record 中截断
    dsh = tmp_path / "dshhome"
    sub = dsh / "sessions" / "t-d-developer"
    fo = _write_bin(sub / OLD, good)
    fn = _write_bin(sub / NEW, torn_jsonl)
    _quarantine_torn_sessions(dsh)
    assert fo.is_file()
    assert not fn.exists()
    assert (_quarantine_dir(dsh) / ("torn-t-d-developer-" + NEW)).is_file()


def test_quarantine_missing_sessions_noop(tmp_path):
    dsh = tmp_path / "dshhome"
    dsh.mkdir()
    _quarantine_torn_sessions(dsh)
    assert not _quarantine_dir(dsh).exists()  # 零动作（既有行为）


# ---------- 统计面：双代取一份 + 半径钉死（review C2） ----------

def test_aggregate_only_new_generation(tmp_path):
    wt = tmp_path / "wt"
    _write_bin(_sub(wt, TICKET + "-developer") / NEW, _usage_bytes(100, 200, 50))
    tokens, _note = aa._aggregate_lane_usage(wt, TICKET)
    assert (tokens["in"], tokens["out"], tokens["cacheRead"]) == (100, 200, 50)
    assert tokens["tokens_zero"] is False


def test_aggregate_dual_generation_counts_one_new(tmp_path):
    """双名并存只计 mtime 最新一份：新代新 → 只算新代（防同一会话双代并计翻倍）。"""
    wt = tmp_path / "wt"
    sub = _sub(wt, TICKET + "-developer")
    fo = _write_bin(sub / OLD, _usage_bytes(10, 20, 5))
    fn = _write_bin(sub / NEW, _usage_bytes(100, 200, 50))
    _set_mtime(fo, 1000)
    _set_mtime(fn, 2000)
    tokens, _note = aa._aggregate_lane_usage(wt, TICKET)
    assert (tokens["in"], tokens["out"], tokens["cacheRead"]) == (100, 200, 50)


def test_aggregate_dual_generation_counts_one_old_newer(tmp_path):
    """取最新不偏袒新代：旧代 mtime 更新时统计旧代（升级窗口内旧会话仍在写的一致口径）。"""
    wt = tmp_path / "wt"
    sub = _sub(wt, TICKET + "-developer")
    fo = _write_bin(sub / OLD, _usage_bytes(10, 20, 5))
    fn = _write_bin(sub / NEW, _usage_bytes(100, 200, 50))
    _set_mtime(fo, 5000)
    _set_mtime(fn, 2000)
    tokens, _note = aa._aggregate_lane_usage(wt, TICKET)
    assert (tokens["in"], tokens["out"], tokens["cacheRead"]) == (10, 20, 5)


def test_aggregate_dual_generation_tie_prefers_old(tmp_path):
    """mtime 平局 → 旧名（与「只有旧名」现状对齐的确定性规则）。"""
    wt = tmp_path / "wt"
    sub = _sub(wt, TICKET + "-developer")
    fo = _write_bin(sub / OLD, _usage_bytes(10, 20, 5))
    fn = _write_bin(sub / NEW, _usage_bytes(100, 200, 50))
    _set_mtime(fo, 2000)
    _set_mtime(fn, 2000)
    tokens, _note = aa._aggregate_lane_usage(wt, TICKET)
    assert (tokens["in"], tokens["out"], tokens["cacheRead"]) == (10, 20, 5)


def test_aggregate_radius_two_levels_only(tmp_path):
    """review C2 负向子用例：两层布局以外（一层 / 三层）的同名档不入统计集；
    本票匹配前缀过滤（别票不混入）与改前一致。"""
    wt = tmp_path / "wt"
    sess = wt / ".dsh" / "sessions"
    _write_bin(_sub(wt, TICKET + "-developer") / OLD, _usage_bytes(10, 20, 5))       # 两层：计
    _write_bin(sess / "slug0" / OLD, _usage_bytes(1000, 0, 0))                        # 一层：不计
    _write_bin(_sub(wt, TICKET + "-developer") / "nested" / OLD, _usage_bytes(2000, 0, 0))  # 三层：不计
    _write_bin(_sub(wt, "other-ticket-dev") / OLD, _usage_bytes(3000, 0, 0))          # 别票前缀：不计
    tokens, _note = aa._aggregate_lane_usage(wt, TICKET)
    assert (tokens["in"], tokens["out"], tokens["cacheRead"]) == (10, 20, 5)


def test_aggregate_zero_note_dual_name(tmp_path):
    """零会话文案：双名并列表述（验收④——不残留旧名单数表述）。"""
    wt = tmp_path / "wt"
    (wt / ".dsh" / "sessions" / "slug0").mkdir(parents=True)
    tokens, note = aa._aggregate_lane_usage(wt, TICKET)
    assert tokens["tokens_zero"] is True
    assert OLD in note and NEW in note and "/" in note


# ---------- 守卫子用例（review C3：仿 t260907-04 naming-grep-assert 的轻量版） ----------

# 取舍清单（先例=t260907-04 sc_naming_grep_assert 的白名单纪律）：
# - 带：常量行豁免（SESSION_FILE_NAMES 字样——常量定义/消费行允许单侧出现）；
#       标记行豁免（session-name-compat——历史旧代释义行的申报通道）；
#       双名配对豁免（同行同时含新代名=并列表述，含常量定义行本身）。
# - 不带：运行态目录豁免不适用（本守卫只扫 src 源码面，不扫 data/out/运行产物）；
#         「旧代/legacy 释义行」兜底类**不设**——防止变成后门，需要时走标记申报；
#         测试面（engine/tests、workbench tests/smoke）不在扫描根（桩造旧名文件是合法断言面）。
# - 自证：_session_literal_offenders 为纯函数，合成样本红绿双证随守卫交付（下测）。

def _session_literal_offenders(lines):
    """旧会话名字面守卫（纯函数）：含 `session.jsonl` 字面却不满足双名口径的行。"""
    out = []
    for ln in lines:
        if "session.jsonl" not in ln:
            continue
        if ("session.v3.jsonl.zstd" in ln or "SESSION_FILE_NAMES" in ln
                or "session-name-compat" in ln):
            continue
        out.append(ln)
    return out


def test_guard_self_cert_red_green():
    """合成样本自证：配对/常量/标记三绿、裸旧名一红（守卫自身可被验证）。"""
    assert _session_literal_offenders(
        ["fp = join(sess, 'session.jsonl.zstd', 'session.v3.jsonl.zstd')"]) == []
    assert _session_literal_offenders(
        ['SESSION_FILE_NAMES: Tuple[str, ...] = ("session.jsonl.zstd",)']) == []
    assert _session_literal_offenders(
        ["# session-name-compat: 旧代字段在此仅作历史释义"]) == []
    off = _session_literal_offenders(["const fp = join(dir, 'session.jsonl.zstd')"])
    assert len(off) == 1 and "session.jsonl.zstd" in off[0]


def test_src_tree_session_literal_paired():
    """实树扫描：src 面不允许出现未配对的旧名字面（防第 7 处字面消费点回潮）。"""
    repo = Path(__file__).resolve().parents[3]
    files = [p for p in (repo / "server" / "engine").rglob("*.py")
             if "tests" not in p.parts]
    files += sorted((repo / "server" / "plugins" / "workbench" / "src").rglob("*.ts"))
    files += [repo / "server" / "plugins" / "workbench" / "node.ts"]
    offenders = []
    for p in files:
        if not p.is_file():
            continue
        for no, ln in enumerate(p.read_text(encoding="utf-8", errors="replace").split("\n"), 1):
            for bad in _session_literal_offenders([ln]):
                offenders.append("%s:%d: %s" % (p.relative_to(repo), no, bad.strip()[:80]))
    assert offenders == [], "src 面存在未配对的旧会话名字面（应双名并列/落常量/带 session-name-compat 标记）：%s" % offenders
