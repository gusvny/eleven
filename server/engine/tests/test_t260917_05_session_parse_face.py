"""t260917-05 会话发现面「零静默降级」单测：解析面判据三态 + S3 分类点名 + 检疫盲区。

被测（agent_activities）：
  - _judge_session_lines / _session_face_s1_text：判据纯函数，S1 真值表三段
    （review 钉死：解压失败≠S1、解压成功且全文空白≠S1、有非空白内容但零可解析
    行——含二进制乱文本——→ S1 响亮）；
  - _aggregate_lane_usage 三态接线：S1 响亮+format_suspect 注记、S2 保留既有轻
    文案、S3 分类点名+suspect_unmatched 注记、混合态（坏文件浮出不静默）、点名
    封顶、健康路径 note==""（既有约束不得被新注记污染）；
  - _session_quarantine_blindspots + _quarantine_torn_sessions 盲区点名：不挪
    不解析（不懂的格式不动），既有两层检疫并行回归。

UT 全程禁网络/真 Temporal；zstd 用系统 CLI（缺则相关用例 skip，与
test_t260904_09 同款环境闸）。
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import agent_activities as aa  # noqa: E402

TICKET = "t260917-05"

HAS_ZSTD = subprocess.run(["zstd", "--version"], capture_output=True).returncode == 0


def _zstd_bytes(raw: bytes) -> bytes:
    """zstd 压一段字节（走被测代码同款 CLI 依赖）。"""
    p = subprocess.run(["zstd", "-z", "-c"], input=raw, capture_output=True, check=True)
    return p.stdout


def _zstd_file(path: Path, raw: bytes) -> None:
    """把 zstd 压缩字节写到 path（父目录自动建）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_zstd_bytes(raw))


def _usage_line(i=10, o=20, c=5, usage=None):
    u = usage if usage is not None else {"inputTokens": i, "outputTokens": o,
                                         "cacheReadTokens": c}
    return json.dumps({"type": "assistant/message", "data": {"usage": u}})


# ---------- 判据纯函数：_judge_session_lines 真值表 ----------


def test_judge_usage_counts_message_not_chunk():
    """usage 记录数只数 assistant/message——chunk 同名 usage 不数不加（不双算红线）。"""
    lines = [
        json.dumps({"type": "request/context",
                    "data": {"provider": "p", "model": "m"}}),
        _usage_line(1, 2, 3),
        json.dumps({"type": "assistant/chunk",
                    "data": {"chunk": {"type": "usage"},
                             "usage": {"inputTokens": 1, "outputTokens": 2}}}),
    ]
    j = aa._judge_session_lines(lines)
    assert j["blank"] is False
    assert j["parsed"] == 3 and j["known_types"] == 3
    assert j["usage_records"] == 1          # chunk 不计
    assert j["usage_without_known_keys"] == 0
    assert len(j["objs"]) == 3              # 金额累加复用面


def test_judge_malformed_shapes():
    """畸形输入不抛：全坏行 / 二进制乱文本行 / 非 JSON 映射行 / 非 list / 条目非串。"""
    j = aa._judge_session_lines(["这不是json", '{"torn', "\x00\x01binary"])
    assert j["blank"] is False and j["parsed"] == 0
    j2 = aa._judge_session_lines(["\n", "  ", ""])
    assert j2["blank"] is True and j2["parsed"] == 0
    j3 = aa._judge_session_lines(["[1,2,3]"])   # 合法 JSON 但非映射 → 不计 parsed
    assert j3["parsed"] == 0 and j3["blank"] is False
    assert aa._judge_session_lines(None)["blank"] is True    # 非 list 不抛
    # 条目非串 → 按空白行处理（docstring 钉死合同；TS 镜像 agent-live.ts
    # judgeSessionLines 同构：typeof ln !== 'string' 即跳过）。全非串=blank 且
    # parsed=0；混排时串条目照常判定（非串不吞判据面）。
    j4 = aa._judge_session_lines([42, None, {"a": 1}])
    assert j4["blank"] is True and j4["parsed"] == 0 and j4["objs"] == []
    j5 = aa._judge_session_lines([42, _usage_line(), None])
    assert j5["parsed"] == 1 and j5["usage_records"] == 1
    assert aa._judge_session_lines([_usage_line(usage={"tokens": 5})])["usage_without_known_keys"] == 1


def test_s1_truth_table():
    """S1 真值表（review 三段）：blank→None；非 blank 且零可解析/零已知事件/usage
    缺全部已知键 → 响亮；健康 → None。文案含票面例句与文件名。"""
    healthy = aa._judge_session_lines(['{"type": "session"}', _usage_line()])
    assert aa._session_face_s1_text("f.zstd", healthy) is None
    blank = aa._judge_session_lines(["\n", "  "])
    assert aa._session_face_s1_text("f.zstd", blank) is None          # 全空白≠S1
    garbage = aa._judge_session_lines(["这不是json", "\x00\x01bin"])  # 二进制乱文本→S1
    s1 = aa._session_face_s1_text("bad.zstd", garbage)
    assert s1 is not None and "格式不认识" in s1 and "疑似 dsh 版本不匹配" in s1 \
        and "统计值不可信" in s1 and "bad.zstd" in s1
    unknown_types = aa._judge_session_lines(['{"type": "v9/whatever", "data": {}}'])
    assert aa._session_face_s1_text("f.zstd", unknown_types) is not None  # 词表全不识
    no_keys = aa._judge_session_lines([_usage_line(usage={"tokensTotal": 9})])
    assert aa._session_face_s1_text("f.zstd", no_keys) is not None        # usage 缺三键


# ---------- 聚合接线：三态 / 混合态 / 封顶 / 健康路径 ----------


def _wt_with(wt: Path, sub: str, raw: bytes, name: str = "session.jsonl.zstd"):
    p = wt / ".dsh" / "sessions" / "slug" / sub / name
    _zstd_file(p, raw)


@pytest.mark.skipif(not HAS_ZSTD, reason="zstd CLI 不可用")
def test_aggregate_s1_garbage_content(tmp_path):
    """验收①态A：文件在、内容不可解析（乱文本）→ 响亮文案 + format_suspect，绝不静默 0。"""
    wt = tmp_path / "wt"
    _wt_with(wt, TICKET, "这不是会话记录，一行都不合法\n第二行也是乱码\n".encode())
    tokens, note = aa._aggregate_lane_usage(wt, TICKET)
    assert "格式不认识" in note and "疑似 dsh 版本不匹配" in note and "统计值不可信" in note
    assert tokens["format_suspect"] is True and tokens["tokens_zero"] is True


@pytest.mark.skipif(not HAS_ZSTD, reason="zstd CLI 不可用")
def test_aggregate_blank_content_not_s1(tmp_path):
    """真值表②：解压成功且全文空白 → 合法非 S1，走既有 S2 兜底文案（不挂版本不匹配）。"""
    wt = tmp_path / "wt"
    _wt_with(wt, TICKET, b"\n\n  \n")
    tokens, note = aa._aggregate_lane_usage(wt, TICKET)
    assert "format_suspect" not in tokens
    assert "会话无 usage 事件" in note and "格式不认识" not in note


@pytest.mark.skipif(not HAS_ZSTD, reason="zstd CLI 不可用")
def test_aggregate_usage_missing_known_keys(tmp_path):
    """S1 判据③：usage 对象在但三个已知键全缺（新版本改字段名形态）→ 响亮。"""
    wt = tmp_path / "wt"
    _wt_with(wt, TICKET, (_usage_line(usage={"tokensTotal": 9}) + "\n").encode())
    tokens, note = aa._aggregate_lane_usage(wt, TICKET)
    assert tokens["format_suspect"] is True and "格式不认识" in note


@pytest.mark.skipif(not HAS_ZSTD, reason="zstd CLI 不可用")
def test_aggregate_mixed_good_bad(tmp_path):
    """review 意见2 混合态：totals 来自好文件，坏文件的 S1 仍浮出（结果级置位+点名）。"""
    wt = tmp_path / "wt"
    _wt_with(wt, TICKET, "全是乱码没有一行合法\n".encode())                    # 坏（恰等目录）
    _wt_with(wt, TICKET + "-dev", (_usage_line(7, 8, 1) + "\n").encode())      # 好（前缀目录）
    tokens, note = aa._aggregate_lane_usage(wt, TICKET)
    assert tokens["in"] == 7 and tokens["out"] == 8          # 好文件照常计入
    assert tokens["format_suspect"] is True                  # 结果级置位
    assert "格式不认识" in note and "session.jsonl.zstd" in note  # 坏文件点名在 note


@pytest.mark.skipif(not HAS_ZSTD, reason="zstd CLI 不可用")
def test_aggregate_healthy_note_empty(tmp_path):
    """健康路径回归（review 意见5）：note==""，无任何新注记键。"""
    wt = tmp_path / "wt"
    _wt_with(wt, TICKET, (json.dumps({"type": "request/context",
                                      "data": {"provider": "p", "model": "m"}}) + "\n"
                          + _usage_line(3, 4, 0) + "\n").encode())
    tokens, note = aa._aggregate_lane_usage(wt, TICKET)
    assert note == ""
    assert "format_suspect" not in tokens and "suspect_unmatched" not in tokens
    assert tokens["tokens_zero"] is False


def test_aggregate_s3_classified_when_discovery_empty(tmp_path):
    """验收①态B+S3 分流（review 意见3）：发现集空而目录有会话样文件 → 按类点名，
    已知布局不误诊「版本不匹配」，双不识才挂疑似；suspect_unmatched 置位。"""
    wt = tmp_path / "wt"
    sess = wt / ".dsh" / "sessions" / "slug"
    (sess / "t9999-x").mkdir(parents=True)
    (sess / "t9999-x" / "session.jsonl.zstd").write_bytes(b"x")   # 他票三层布局
    (sess / "session-legacy.zstd").write_bytes(b"x")              # 旧扁平布局
    (sess / "strange.session.bin").write_bytes(b"x")              # 名/布局双不识
    tokens, note = aa._aggregate_lane_usage(wt, TICKET)
    assert tokens["suspect_unmatched"] is True and tokens["tokens_zero"] is True
    assert "无本票会话文件" in note                 # 既有基线文案保留
    assert "他票会话" in note                       # 他票：不误诊
    assert "旧代布局" in note                       # 旧扁平：不误诊
    assert "疑似 dsh 版本不匹配" in note            # 双不识：才挂疑似
    assert note.index("名字/布局不认识") < note.index("他票会话")  # unknown 排前
    assert "strange.session.bin" in note and "session-legacy.zstd" in note


def test_aggregate_s3_empty_tree_keeps_old_note(tmp_path):
    """目录真空（无任何会话样文件）→ 维持既有 note，无 suspect_unmatched（不虚报）。"""
    wt = tmp_path / "wt"
    (wt / ".dsh" / "sessions" / "slug" / "empty-sub").mkdir(parents=True)
    tokens, note = aa._aggregate_lane_usage(wt, TICKET)
    assert "suspect_unmatched" not in tokens
    assert "无本票会话文件" in note and "未入统计" not in note


def test_aggregate_s3_roll_call_capped(tmp_path):
    """review 意见4：点名清单封顶（前 20 条 + 「等共 N 个」），不把大目录写进账本。"""
    wt = tmp_path / "wt"
    sess = wt / ".dsh" / "sessions" / "slug"
    sess.mkdir(parents=True)
    for i in range(25):
        (sess / ("f%d.session.bin" % i)).write_bytes(b"x")
    tokens, note = aa._aggregate_lane_usage(wt, TICKET)
    assert tokens["suspect_unmatched"] is True
    assert "等共 25 个" in note
    assert note.count(".session.bin") == 20  # 点名正文恰 20 条，其余进尾注计数


def test_format_capped_bounds():
    assert aa._format_capped([]) == ""
    assert aa._format_capped(["a"]) == "a"
    out = aa._format_capped(["f%d" % i for i in range(25)])
    assert out.count("、") == aa.SESSION_NOTE_CAP - 1 and "等共 25 个" in out
    out20 = aa._format_capped(["f%d" % i for i in range(20)])
    assert "等共" not in out20


# ---------- 检疫面盲区：点名但不挪不解析 ----------


def test_blindspots_classification(tmp_path):
    """已知两布局豁免；新代假想名/含 session 杂文件在列；目录缺失 → 空清单。"""
    dsh = tmp_path / "d.dsh"
    sess = dsh / "sessions"
    (sess / "sess-a").mkdir(parents=True)
    (sess / "sess-a" / "session.jsonl.zstd").write_bytes(b"")            # 现行三层：豁免
    (sess / "session-legacy.zstd").write_bytes(b"")                      # 旧扁平：豁免
    (sess / "sess-new").mkdir(parents=True, exist_ok=True)
    (sess / "sess-new" / "session.jsonl.zst").write_bytes(b"x")          # 新代假想名：盲区
    (sess / "notes.txt").write_bytes(b"x")                               # 无关文件：不在列
    blind = aa._session_quarantine_blindspots(dsh)
    assert blind == ["sess-new/session.jsonl.zst"]
    assert aa._session_quarantine_blindspots(tmp_path / "nope.dsh") == []


@pytest.mark.skipif(not HAS_ZSTD, reason="zstd CLI 不可用")
def test_quarantine_blindspot_named_not_moved(tmp_path):
    """盲区文件：检疫后原位不动、不进隔离区（点名≠处置）；同批撕裂档照旧隔离
    （两层检疫既有行为并行回归）。"""
    dsh = tmp_path / "e.dsh"
    sess = dsh / "sessions"
    torn_dir = sess / "sess-torn"
    torn_dir.mkdir(parents=True)
    torn = torn_dir / "session.jsonl.zstd"
    torn.write_bytes(_zstd_bytes(b'{"i":1}\n') + b'{"i":2,"cu')   # 帧好内撕裂
    newgen_dir = sess / "sess-newgen"
    newgen_dir.mkdir()
    newgen = newgen_dir / "session.jsonl.zst"
    newgen.write_bytes(b"next-gen payload")
    aa._quarantine_torn_sessions(dsh)
    assert not torn.exists()                    # 既有检疫照旧
    assert newgen.exists()                      # 盲区文件不挪（不懂的格式不动）
    quarantine = tmp_path / ".sandbar" / "quarantine"
    if quarantine.exists():
        # 隔离区里只有既有撕裂档（.zstd），新代名（.zst）绝不进隔离区
        assert not list(quarantine.glob("*session.jsonl.zst"))
    assert aa._session_quarantine_blindspots(dsh) == ["sess-newgen/session.jsonl.zst"]
