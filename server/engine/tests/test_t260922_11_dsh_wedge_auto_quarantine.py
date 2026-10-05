"""t260922-11 单元测试：dsh 撕裂点名自动隔离（分歧转动作）。

面①（探针判据矩阵，锁现状）：工单四类样本 + 跨帧类 + 畸形类的引擎两层判据——
  帧好整流合法类（空帧/无尾换行/跨帧记录）一律**不**隔离（对照组纪律：E 类=
  探针盲区快照，本票不改探针，收敛靠 dsh 点名通道）；帧裂/好帧内截断行/空文件/
  帧内二进制 → 隔离。
面②（t260922-11 helper 层）：撕裂文案命中（畸形输入不抛）/辅证 id 解析/定点选档
  （双代只动 newest、跨 id 不误选、盲区不碰）/wedge 核心（id 主锚 env+辅证日志、
  存在性核验落 action、move-failed 不谎报、事件落盘、attempt 回落 0）/成功注记
  （有/无记录、无 quarantine 目录=R2、畸形事件跳过）。
面③（接线源级断言，KI-093 先例 test_t260916_29:487）：四处失败分支 reap→wedge→
  raise/_err 序在位；成功注记恰挂主面两 return 点。

UT 全程禁网络/真 Temporal/真 git；zstd 子进程=被测代码同款依赖（夹具与探针），
conftest 零真 docker 网闸不受影响。
"""
import inspect
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent_activities as aa  # noqa: E402
import dsh_torn_fixtures as fx  # noqa: E402
from agent_activities import (  # noqa: E402
    DSH_TEAR_HIT_CAP,
    DSH_TEAR_MARKERS,
    _apply_session_wedge_note,
    _dsh_tear_hit,
    _newest_session_file_for_id,
    _parse_dsh_named_session,
    _quarantine_torn_sessions,
    _session_jsonl_torn,
    _wedge_attempt,
    _wedge_quarantine_once,
)
from shared import StageResult  # noqa: E402

# t260922-06 现场原文（工单正文逐字）——检测/解析层的固定桩，不依赖真 dsh。
INCIDENT_LOG = (
    "dsh-headless-resume: 恢复会话 t260922-06-integration 失败（回落新建同 id 会话）："
    'session "t260922-06-integration" not found\n'
    "corrupt Zstandard session log: complete frame contains a torn JSONL record\n")

SID = "t260922-06-integration"

# dsh 读侧拒读词族的全部实测措辞（260922 观测表 .sandbar/observe_matrix_gen7.txt
# 七类逐条 + 挂起项第二种形态 live 原文）——触发面回归的固定桩，不依赖真 dsh。
# 打回实锚：前两种措辞在旧 marker 表（工单立票两形态）下零命中=漏检（今日
# t260922-07/t260922-10 各中一次人工隔离）。
V_EMPTY_HEADERLESS = "empty or header-less Zstandard session log"
V_FIRST_FRAME = ("corrupt Zstandard session log: "
                 "first frame is not exactly one header line")
V_HEADER_JSON = "corrupt session log: header line is not valid JSON"
V_SEQ_GAP = ("corrupt session log: seq gap in committed region at line 2679 "
             "(expected 26106, got 26097)")
# 观测表七类 → 各自被 dsh 拒读的实锚措辞（逐类对齐，一行一实锚）
KIND_VERDICTS = (
    ("frame_torn", V_EMPTY_HEADERLESS),
    ("empty_file", V_EMPTY_HEADERLESS),
    ("truncated_line", V_FIRST_FRAME),
    ("empty_frame", V_FIRST_FRAME),
    ("no_trailing_newline", V_FIRST_FRAME),
    ("record_across_frames", V_FIRST_FRAME),
    ("binary_in_frame", V_HEADER_JSON),
    pytest.param("frame_torn", V_SEQ_GAP,
                 id="seq_gap_live_second_form"),  # live 原文（挂起项第二种形态）
)


def _mk_dsh_one(tmp_path: Path, kind: str,
                fname: str = "session.jsonl.zstd") -> Path:
    """单样本 DSH_HOME：<tmp>/dsh-home/sessions/session.jsonl.zstd（检疫扫面用，
    平面布局=既有检疫 UT 同款）。"""
    dsh = tmp_path / "dsh-home"
    f = dsh / "sessions" / fname
    f.parent.mkdir(parents=True)
    f.write_bytes(fx.build_bytes(kind))
    return dsh


def _qdir(root: Path) -> Path:
    return root / ".sandbar" / "quarantine"


# ---------- 面①：探针判据矩阵（锁现状，步骤①） ----------


@pytest.mark.parametrize("kind", [
    "empty_frame", "no_trailing_newline", "record_across_frames"])
def test_healthy_classes_not_quarantined(tmp_path, kind):
    """帧好整流合法类一律不隔离（对照组：误隔离=反向事故；E 类=探针盲区快照——
    本票不改探针判据，跨帧类收敛走 dsh 点名通道）。"""
    dsh = _mk_dsh_one(tmp_path, kind)
    f = dsh / "sessions" / "session.jsonl.zstd"
    assert _session_jsonl_torn(f) is False
    _quarantine_torn_sessions(dsh)
    assert f.is_file()                          # 原位不动
    assert not _qdir(tmp_path).exists()         # 检疫目录都没建


@pytest.mark.parametrize("kind", [
    "frame_torn", "truncated_line", "binary_in_frame", "empty_file"])
def test_torn_classes_quarantined(tmp_path, kind):
    """帧裂/好帧内截断行/帧内二进制/0 字节文件 → 两层检疫照旧隔离（回归锁）。"""
    dsh = _mk_dsh_one(tmp_path, kind)
    f = dsh / "sessions" / "session.jsonl.zstd"
    _quarantine_torn_sessions(dsh)
    assert not f.exists()
    assert (_qdir(tmp_path) / "torn-sessions-session.jsonl.zstd").is_file()


def test_record_across_frames_shape_is_probe_blindspot(tmp_path):
    """E 类形态锁：两帧各自完整（zstd -t 过）+ 整流逐行合法（探针 False）——
    引擎两层都看不见它，这正是「dsh 判 torn 而探针判干净」的结构性来源（H1）。"""
    dsh = _mk_dsh_one(tmp_path, "record_across_frames")
    f = dsh / "sessions" / "session.jsonl.zstd"
    import subprocess
    assert subprocess.run(["zstd", "-t", str(f)],
                          capture_output=True).returncode == 0
    assert _session_jsonl_torn(f) is False


# ---------- 面②-1：检测/解析层 ----------


def test_tear_markers_match_ticket_texts():
    """工单立票两形态逐字在表；打回扩充的词族形态（无前缀 corrupt 族/第三种措辞
    empty or header-less）也在表——七类观测+live 第二种形态的措辞全部被词族命中。"""
    assert "torn JSONL record" in DSH_TEAR_MARKERS
    assert "corrupt Zstandard session log" in DSH_TEAR_MARKERS
    assert "corrupt session log" in DSH_TEAR_MARKERS
    assert "empty or header-less" in DSH_TEAR_MARKERS
    for line in (V_EMPTY_HEADERLESS, V_FIRST_FRAME, V_HEADER_JSON, V_SEQ_GAP):
        assert _dsh_tear_hit(line), line   # 四种实测措辞逐条命中


def test_dsh_tear_no_false_positive_on_benign_lines():
    """零误伤（打回 b) 反向）：会话日志的无害措辞不命中——词族锚 dsh 判据专属
    措辞形态，不锚 session log/corrupt 等泛词（命中→隔离的反面=不命中→零改动）。"""
    benign = [
        "dsh-headless-resume: 已恢复会话 %s（续写既有会话档）" % SID,
        "rotate session log ok (size=538104)",
        "anti-corruption scan: 0 findings",
        "session log flushed, 1144 lines written",
    ]
    for line in benign:
        assert _dsh_tear_hit(line) == [], line


def test_dsh_tear_hit_incident_and_malformed():
    """现场日志 → 恰 1 行命中（两 marker 同一行不重复计）；该行含双 marker 字样；
    空/None/无文案 → 零命中不抛（仲裁轮 3 归因：实现按行收集，原断言 len==2 把
    「两条文案」误当「两行」——现场两 marker 在同一行）。"""
    hits = _dsh_tear_hit(INCIDENT_LOG)
    assert len(hits) == 1
    assert "corrupt Zstandard session log" in hits[0]
    assert "torn JSONL record" in hits[0]
    assert _dsh_tear_hit("") == []
    assert _dsh_tear_hit(None) == []           # docstring 承诺：畸形输入不抛
    assert _dsh_tear_hit("all clean output\nnothing here\n") == []


def test_dsh_tear_hit_cap_and_line_truncate():
    """命中封顶 DSH_TEAR_HIT_CAP 条；单行截断（畸形超长行不撑爆记录面）。"""
    big = "".join("x tear torn JSONL record %d\n" % i for i in range(10))
    hits = _dsh_tear_hit(big)
    assert len(hits) == DSH_TEAR_HIT_CAP
    huge_line = "torn JSONL record " + "y" * 100000
    hits2 = _dsh_tear_hit(huge_line)
    assert len(hits2) == 1 and len(hits2[0]) <= 500


def test_parse_dsh_named_session():
    """辅证解析：现场「恢复会话 <id> 失败」行 → id；无可解析行 → None（C4：
    corrupt 来自 flush 期异步抛出时该行可整条缺席，机制须照转）。"""
    assert _parse_dsh_named_session(INCIDENT_LOG) == SID
    assert _parse_dsh_named_session(
        "corrupt Zstandard session log: complete frame contains a torn JSONL "
        "record\n") is None
    assert _parse_dsh_named_session("") is None


# ---------- 面②-2：定点选档层 ----------


def test_newest_session_file_for_id_dual_gen_and_scoping(tmp_path):
    """双代并存取 mtime 最新（_pick_newest_session 消歧）；跨 id 目录不误选；
    盲区/旧扁平文件不入候选（纪律镜像 _scan_integration_sessions）。"""
    root = tmp_path
    dsh = fx.mk_dsh_with_session(root, SID, ["empty_frame"])
    sess_dir = dsh / "sessions" / "lane1" / SID
    # 同目录放第二代（更旧 mtime）+ 盲区名 + 旧扁平名 + 邻 id 目录
    v3 = sess_dir / "session.v3.jsonl.zstd"
    v3.write_bytes(fx.build_bytes("empty_frame"))
    (sess_dir / "meta.unknown").write_bytes(b"?")
    flat = dsh / "sessions" / "lane1" / ("session-" + SID + ".zstd")
    flat.write_bytes(fx.build_bytes("empty_frame"))
    other = dsh / "sessions" / "lane1" / "other-id" / "session.jsonl.zstd"
    other.parent.mkdir(parents=True)
    other.write_bytes(fx.build_bytes("empty_frame"))
    os.utime(v3, (1000, 1000))                  # v3 更旧
    os.utime(sess_dir / "session.jsonl.zstd", (2000, 2000))
    got = _newest_session_file_for_id(dsh, SID)
    assert got is not None and got.name == "session.jsonl.zstd"   # newest
    # 跨 id 不误选
    assert _newest_session_file_for_id(dsh, "nope-id") is None
    # 盲区/旧扁平文件全部原位不动（选档层只读不碰）
    assert (sess_dir / "meta.unknown").is_file() and flat.is_file()


def test_newest_session_file_for_id_missing(tmp_path):
    dsh = tmp_path / "dsh-home"
    dsh.mkdir()
    assert _newest_session_file_for_id(dsh, SID) is None   # 无 sessions 树
    assert _newest_session_file_for_id(dsh, "") is None    # 空 id 防呆


# ---------- 面②-3：wedge 核心 ----------


def test_wedge_no_marker_noop(tmp_path):
    """日志无撕裂文案 → None；档原位不动；不建检疫目录（零误伤纪律）。"""
    dsh = fx.mk_dsh_with_session(tmp_path, SID, ["record_across_frames"])
    f = dsh / "sessions" / "lane1" / SID / "session.jsonl.zstd"
    note = _wedge_quarantine_once(dsh, SID, "all clean\nexit 0\n", "t", "s", 0, 0)
    assert note is None
    assert f.is_file()
    assert not _qdir(tmp_path).exists()


@pytest.mark.parametrize("kind,verdict", KIND_VERDICTS)
def test_wedge_triggers_on_every_observed_class(tmp_path, kind, verdict):
    """打回 b) 机械判据：观测表七类+live 第二种形态（seq 跳号）逐条——dsh 拒读
    措辞进 spawn 日志 → 命中词族 → 定点隔离（档挪走+事件在案+原文入档）。杜绝
    「只改标记字符串不加用例」的再漏检面：每类固定桩=观测实锚措辞逐字+对应类
    夹具档，不依赖真 dsh。"""
    dsh = fx.mk_dsh_with_session(tmp_path, SID, [kind])
    f = dsh / "sessions" / "lane1" / SID / "session.jsonl.zstd"
    log = ("dsh-headless-resume: 恢复会话 %s 失败（回落新建同 id 会话）：%s\n"
           % (SID, verdict))
    note = _wedge_quarantine_once(dsh, SID, log, "t", "s", 0, 0)
    assert note is not None and "已自动隔离" in note
    assert not f.exists()                       # 点名档挪离原位
    recs = list(_qdir(tmp_path).glob("session-wedge-t-s-*.json"))
    assert len(recs) == 1                       # 事件恰一份
    d = json.loads(recs[0].read_text("utf-8"))
    assert d["action"] == "quarantined"
    assert d["session_id"] == SID
    assert any(verdict[:60] in h for h in d["dsh_tear_lines"])  # 原文入档


def test_wedge_quarantines_dsh_named_newest(tmp_path):
    """核心用例（现场同型）：E 类档（引擎探针放行、dsh 点名 torn）→ 隔离 newest，
    命名/去向口径与人工处置一致，事件含 dsh 原文判据 + 引擎探针判据 + action。"""
    dsh = fx.mk_dsh_with_session(tmp_path, SID, ["record_across_frames"])
    f = dsh / "sessions" / "lane1" / SID / "session.jsonl.zstd"
    note = _wedge_quarantine_once(dsh, SID, INCIDENT_LOG, "t260922-06",
                                  "review_plan", 0, 1)
    assert note is not None and "已自动隔离" in note
    assert not f.exists()                       # 原位已挪走
    dst = _qdir(tmp_path) / ("torn-%s-session.jsonl.zstd" % SID)
    assert dst.is_file()                        # 命名口径 torn-<id>-<文件名>
    recs = sorted(_qdir(tmp_path).glob("session-wedge-t260922-06-review_plan-*.json"))
    assert len(recs) == 1
    d = json.loads(recs[0].read_text("utf-8"))
    assert d["action"] == "quarantined"
    assert d["session_id"] == SID
    assert d["probe"]["zstd_t_rc"] == 0         # 引擎探针判据与 dsh 原文并存（要求④）
    assert d["probe"]["jsonl_torn"] is False    # 探针盲区实锤在档
    assert any("torn JSONL record" in h for h in d["dsh_tear_lines"])
    assert d["attempt"] == 1 and d["gen"] == 0


def test_wedge_dual_gen_only_newest_moved(tmp_path):
    """双代并存只动 newest（dsh 读的就是 newest；动不读的旧代=误隔离）。"""
    dsh = fx.mk_dsh_with_session(tmp_path, SID, ["record_across_frames"])
    sess_dir = dsh / "sessions" / "lane1" / SID
    v3 = sess_dir / "session.v3.jsonl.zstd"
    v3.write_bytes(fx.build_bytes("record_across_frames"))
    os.utime(v3, (1000, 1000))
    os.utime(sess_dir / "session.jsonl.zstd", (2000, 2000))
    note = _wedge_quarantine_once(dsh, SID, INCIDENT_LOG, "t", "s", 0, 0)
    assert note and "已自动隔离" in note
    assert not (sess_dir / "session.jsonl.zstd").exists()   # newest 挪走
    assert v3.is_file()                                     # 旧代不动


def test_wedge_id_env_primary_log_aux_mismatch(tmp_path):
    """C4：主锚 env 优先；辅证 id 不一致 → 隔离主锚档 + 事件双记两 id。"""
    dsh_a = fx.mk_dsh_with_session(tmp_path, "id-a", ["record_across_frames"])
    sess_other = dsh_a / "sessions" / "lane1" / "id-b" / "session.jsonl.zstd"
    sess_other.parent.mkdir(parents=True)
    sess_other.write_bytes(fx.build_bytes("record_across_frames"))
    log = INCIDENT_LOG.replace(SID, "id-b")     # 日志点名 id-b
    note = _wedge_quarantine_once(dsh_a, "id-a", log, "t", "s", 0, 0)
    assert note and "已自动隔离" in note and "id-a" in note
    assert not (dsh_a / "sessions" / "lane1" / "id-a" /
                "session.jsonl.zstd").exists()              # 动的是主锚档
    assert sess_other.is_file()                             # 辅证档不碰
    rec = json.loads(sorted(_qdir(tmp_path).glob(
        "session-wedge-t-s-*.json"))[0].read_text("utf-8"))
    assert rec["session_id"] == "id-a" and rec["session_id_aux"] == "id-b"


def test_wedge_id_aux_fallback_when_env_missing(tmp_path):
    """C4：主锚缺（env 无 DSH_HEADLESS_SESSION）→ 辅证日志 id 补位定位档。"""
    dsh = fx.mk_dsh_with_session(tmp_path, "id-b", ["record_across_frames"])
    log = INCIDENT_LOG.replace(SID, "id-b")
    note = _wedge_quarantine_once(dsh, "", log, "t", "s", 0, 0)
    assert note and "已自动隔离" in note
    assert not (dsh / "sessions" / "lane1" / "id-b" /
                "session.jsonl.zstd").exists()


def test_wedge_both_ids_missing_warn_only(tmp_path):
    """C4：两源皆缺 → 只告警不隔离（返回 note 说明），行为不劣于现状。"""
    dsh = fx.mk_dsh_with_session(tmp_path, SID, ["record_across_frames"])
    f = dsh / "sessions" / "lane1" / SID / "session.jsonl.zstd"
    log = "corrupt Zstandard session log: complete frame contains a torn JSONL record\n"
    note = _wedge_quarantine_once(dsh, "", log, "t", "s", 0, 0)
    assert note is not None and "not quarantined" in note
    assert f.is_file()
    assert not _qdir(tmp_path).exists()         # 未隔离也不留假事件


def test_wedge_no_dual_name_file_blindspot_preserved(tmp_path):
    """id 目录只有盲区名文件 → 不发现不隔离不解析（盲区纪律），档原位不动。"""
    dsh = tmp_path / "dsh-home"
    weird = dsh / "sessions" / "lane1" / SID / "weird-session.dat"
    weird.parent.mkdir(parents=True)
    weird.write_bytes(b"mystery bytes")
    note = _wedge_quarantine_once(dsh, SID, INCIDENT_LOG, "t", "s", 0, 0)
    assert note is not None and "未发现会话档" in note
    assert weird.is_file() and weird.read_bytes() == b"mystery bytes"
    assert not _qdir(tmp_path).exists()


def test_wedge_move_failed_recorded_not_claimed(tmp_path, monkeypatch):
    """C2：隔离动作静默吞 OSError（_quarantine_session_file 恒 None）——成败以
    存在性核验落档：move 失败 → action=move-failed、档原位仍在、绝不记已隔离。"""
    dsh = fx.mk_dsh_with_session(tmp_path, SID, ["record_across_frames"])
    f = dsh / "sessions" / "lane1" / SID / "session.jsonl.zstd"

    def _boom(src, dst):
        raise OSError("disk full (simulated)")

    monkeypatch.setattr(aa.shutil, "move", _boom)
    note = _wedge_quarantine_once(dsh, SID, INCIDENT_LOG, "t", "s", 0, 0)
    assert note is not None and "move-failed" in note and "NOT quarantined" in note
    assert f.is_file()                          # 原位仍在=隔离未发生
    rec = json.loads(sorted(_qdir(tmp_path).glob(
        "session-wedge-t-s-*.json"))[0].read_text("utf-8"))
    assert rec["action"] == "move-failed"       # 证据面不谎报


def test_wedge_qdir_unwritable_full_degradation(tmp_path):
    """qdir 被文件占位（mkdir FileExistsError 被复用函数吞）→ 全降级不炸：
    隔离未发生、事件写失败仅告警、note 照常返回（失败路径主链绝不因观测面挂）。"""
    (tmp_path / ".sandbar").write_text("not a dir")   # .sandbar 是文件
    dsh = fx.mk_dsh_with_session(tmp_path, SID, ["record_across_frames"])
    f = dsh / "sessions" / "lane1" / SID / "session.jsonl.zstd"
    note = _wedge_quarantine_once(dsh, SID, INCIDENT_LOG, "t", "s", 0, 0)
    assert note is not None and "move-failed" in note
    assert f.is_file()


def test_wedge_attempt_fallback_zero(monkeypatch):
    """C5③：attempt 来源=_activity_info().attempt；无 activity 上下文回落 0。"""

    def _boom():
        raise RuntimeError("no activity context")

    monkeypatch.setattr(aa, "_activity_info", _boom)
    assert _wedge_attempt() == 0

    class _Info:
        attempt = 2
    monkeypatch.setattr(aa, "_activity_info", lambda: _Info())
    assert _wedge_attempt() == 2


# ---------- 面②-4：成功注记挂点 ----------


def _mk_record(root: Path, ticket: str, stage: str) -> Path:
    # 生产时序不变量：quarantine 目录由隔离动作（_quarantine_session_file:319
    # mkdir parents）先建，_write_wedge_record 只拼路径不建目录——直调记录函数的
    # 夹具须补齐该时序前提；只建 .sandbar 不够（仲裁轮 4 归因：quarantine 层缺席
    # → write_text FileNotFoundError 被 fail-open 吞 → 空 glob IndexError）。
    _qdir(root).mkdir(parents=True, exist_ok=True)
    aa._write_wedge_record(root / "dsh-home", {
        "ticket": ticket, "stage": stage, "gen": 0, "attempt": 1,
        "session_id": SID, "session_id_aux": SID, "file": "/x/y.zstd",
        "dst": "/q/torn-y.zstd", "action": "quarantined",
        "dsh_tear_lines": ["corrupt Zstandard session log: x"],
        "probe": {"zstd_t_rc": 0, "jsonl_torn": False}})
    return sorted(_qdir(root).glob("session-wedge-%s-%s-*.json"
                                   % (ticket, stage)))[0]


def test_apply_wedge_note_appends_on_records(tmp_path):
    rec = _mk_record(tmp_path, "t", "s")
    res = StageResult(status="ok", summary="s", report="r", evidence="e")
    out = _apply_session_wedge_note(res, tmp_path, "t", "s")
    assert "[引擎注记]" in out.report and "/x/y.zstd" in out.report
    assert "quarantined" in out.report
    assert "session-wedge" in out.evidence
    assert out is res                           # 原地归位（同 _apply_env_signal 形态）


def test_apply_wedge_note_zero_change_without_records(tmp_path):
    """无记录 → res 逐字节不变；无 quarantine 目录 → 零改动（R2 显式短路）。"""
    res = StageResult(status="ok", summary="s", report="r", evidence="e")
    out = _apply_session_wedge_note(res, tmp_path, "t", "s")   # 无 quarantine 目录
    assert out.report == "r" and out.evidence == "e"
    _mk_record(tmp_path, "other", "s")          # 他票他段的事件不串台
    out2 = _apply_session_wedge_note(res, tmp_path, "t", "s")
    assert out2.report == "r" and out2.evidence == "e"


def test_apply_wedge_note_skips_corrupt_record(tmp_path):
    """畸形事件档跳过不判（记录面非执法面）：只剩畸形档 = 零改动。"""
    qdir = _qdir(tmp_path)
    qdir.mkdir(parents=True)
    (qdir / "session-wedge-t-s-gen0-a0-120000.json").write_text("{ not json")
    res = StageResult(status="ok", summary="s", report="r", evidence="e")
    out = _apply_session_wedge_note(res, tmp_path, "t", "s")
    assert out.report == "r" and out.evidence == "e"


# ---------- 面③：接线源级断言（KI-093 先例） ----------


def test_wiring_source_level_four_faces():
    """四处失败分支接线在位且序正确（reap→wedge→raise/_err）；成功注记恰挂主面
    两 return 点；无多接少接（模块级行为由四处函数源断言合围）。

    t261001-03：三站（通用步/arbitrate/acceptance_walkthrough）的轮询循环已合一
    （_wait_for_agent_result），失败分支 reap→wedge→raise 序随之只住在 helper 里——
    源级断言改为锁 helper 一份 + 三站改走 helper（逐站重复接线=该段静默漏修的温床，
    与 KI-002 复发杆 test_260929_ki002_ki029_recurrence 同口径）。"""
    src_helper = inspect.getsource(aa._wait_for_agent_result)
    assert src_helper.count("_wedge_quarantine_once(") == 1
    assert src_helper.index("if rc is not None") < \
        src_helper.index("_wedge_quarantine_once(") < \
        src_helper.index("_result_gone_detail(") < \
        src_helper.index("raise RuntimeError(")
    src_main = inspect.getsource(aa._run_agent_stage_impl)
    assert src_main.count("_wedge_quarantine_once(") == 0
    assert src_main.count("_apply_session_wedge_note(") == 2    # 幂等缓存+真 spawn
    assert src_main.count("await _wait_for_agent_result(") == 1
    for fn in (aa._arbitrate_body, aa._acceptance_walkthrough_body):
        src = inspect.getsource(fn)
        assert src.count("_wedge_quarantine_once(") == 0, fn.__name__
        assert src.count("await _wait_for_agent_result(") == 1, fn.__name__
    src_insp = inspect.getsource(aa.run_inspection_inspect)
    assert src_insp.count("_wedge_quarantine_once(") == 1
    assert src_insp.index("if rc != 0") < \
        src_insp.index("_wedge_quarantine_once(") < \
        src_insp.index("return _err(msg)")
