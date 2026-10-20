"""t260922-06 会话 id 寻址口径引擎读侧锚（epic dsh-upgrade，seam 矩阵 #5 resume 专项）。

被测主张（源码实证，见方案 .sandbar/plan_t260922-06_resume_addressing.md）：
dsh 0.1.5 会话目录两层半径不变（<sessions>/<--projectKey(cwd)-->/<encodeSegment(id)>/），
自定义 id 原生有效（目录名=encodeSegment(id)、头记录 id=自定义 id、resume 按 id 全项目
扫描寻址）——引擎读侧 sub 目录名匹配规则与写/续侧同源同 id，「读得到即可续上」。

本文件把该主张钉成读侧回归锚：
① 0.1.5 布局（v3 文件名 + v3 头记录行 {"type":"session","version":3,"id":<自定义id>}）
   的会话档被 _aggregate_lane_usage 正常命中（同 id 写/续侧 ↔ 读侧双向）；
② v3 头记录 type="session" 已在 SESSION_KNOWN_TYPES、不翻 S1「格式不认识」；
③ encodeSegment 形态目录名：本引擎 id 字符集（<ticket>-<role> ⊆ [A-Za-z0-9._-]）下
   encodeSegment=恒等（转义样例目录名带 ~XXXX 也按名字面匹配现状——负向样例证明
   匹配半径仍钉在两层+前缀规则，不扩大）。

UT 全程禁网络/真 Temporal/真 git；zstd 用系统 CLI（缺则整文件 skip）——
与 test_t260916_23_session_dualname.py 同一夹具纪律。
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agent_activities as aa  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("zstd") is None,
                                reason="zstd CLI 缺席（引擎读侧既有依赖，缺供即环境红）")

TICKET = "t260922-06"
ROLE = TICKET + "-developer"
SESSION_ID = ROLE                    # 写/续侧确定性 id = <ticket>-<role>
PROJECT_KEY = "--Users-xingu-Documents-sandbar--.lane-t260922-06--"  # 0.1.5 projectKey 形态样例


# ---------- 夹具工具（与 dualname 套件同制式） ----------

def _zstd_bytes(raw: bytes) -> bytes:
    p = subprocess.run(["zstd", "-z", "-c"], input=raw, capture_output=True, check=True)
    return p.stdout


def _jsonl_bytes(objs: list) -> bytes:
    return b"".join((json.dumps(o) + "\n").encode() for o in objs)


def _v3_session_bytes(session_id: str) -> bytes:
    """0.1.5 会话档形态：v3 头记录 + request/context + assistant/message usage。"""
    return _zstd_bytes(_jsonl_bytes([
        {"type": "session", "version": 3, "id": session_id,
         "createdAt": 1790000000000, "cwd": "/x/y", "isSeeded": False},
        {"type": "request/context", "data": {"provider": "p", "model": "m1"}},
        {"type": "assistant/message", "data": {"usage": {
            "inputTokens": 3, "outputTokens": 5, "cacheReadTokens": 7}}},
    ]))


def _v3_lane(wt: Path, sub_name: str, session_id: str) -> Path:
    """0.1.5 两层布局：<wt>/.dsh/sessions/<--projectKey-->/<sub>/session.v3.jsonl.zstd。"""
    d = wt / ".dsh" / "sessions" / PROJECT_KEY / sub_name
    d.mkdir(parents=True, exist_ok=True)
    f = d / "session.v3.jsonl.zstd"
    f.write_bytes(_v3_session_bytes(session_id))
    return f


# ---------- ① 0.1.5 布局读侧命中（读/写/续同 id 双向锚） ----------

def test_v3_layout_aggregate_hit(tmp_path):
    """自定义 id 会话（0.1.5 布局）被读侧命中：usage 入账、note 干净、无零记。"""
    _v3_lane(tmp_path, SESSION_ID, SESSION_ID)
    tokens, note = aa._aggregate_lane_usage(tmp_path, TICKET)
    assert (tokens["in"], tokens["out"], tokens["cacheRead"]) == (3, 5, 7)
    assert tokens["tokens_zero"] is False
    assert tokens.get("format_suspect") is None
    assert tokens["by_model"] == {"p/m1": 8}
    assert note == ""


def test_v3_layout_stage_key_hit(tmp_path):
    """t260903-02 验收边：ticket-stage 专属 key（<ticket>-<stage> 前缀）同样命中。"""
    stage_id = TICKET + "-acceptance"
    _v3_lane(tmp_path, stage_id, stage_id)
    tokens, note = aa._aggregate_lane_usage(tmp_path, TICKET)
    assert (tokens["in"], tokens["out"], tokens["cacheRead"]) == (3, 5, 7)
    assert note == ""


def test_v3_layout_other_ticket_not_counted(tmp_path):
    """他票会话（sub 不匹配本票前缀）不入统计集——半径不因 0.1.5 扩大。"""
    _v3_lane(tmp_path, "t999999-99-developer", "t999999-99-developer")
    tokens, note = aa._aggregate_lane_usage(tmp_path, TICKET)
    assert tokens["tokens_zero"] is True
    assert (tokens["in"], tokens["out"], tokens["cacheRead"]) == (0, 0, 0)
    assert "t999999-99-developer" in note  # S3 点名：有会话样文件却未入统计，不静默 0


# ---------- ② v3 头记录 type="session" 已入册、不翻 S1 ----------

def test_v3_header_record_known_type():
    """头记录行（type=session）命中已知词表、不产 usage、不触发 S1 判据。"""
    raw = _v3_session_bytes(SESSION_ID)
    p = subprocess.run(["zstd", "-d", "-c"], input=raw, capture_output=True, check=True)
    j = aa._judge_session_lines(p.stdout.decode().split("\n"))
    assert j["blank"] is False
    assert j["parsed"] == 3
    assert j["known_types"] == 3          # session + request/context + assistant/message
    assert j["usage_records"] == 1
    assert j["usage_without_known_keys"] == 0


def test_v3_header_record_no_s1(tmp_path):
    """端到端：仅含头记录+usage 的 v3 档聚合后无 format_suspect、note 干净。"""
    _v3_lane(tmp_path, SESSION_ID, SESSION_ID)
    tokens, note = aa._aggregate_lane_usage(tmp_path, TICKET)
    assert tokens.get("format_suspect") is None
    assert note == ""


def test_session_known_types_contains_session_record():
    """词表守卫：type="session" 必须在册（0.1.5 头记录行依赖；漂移即红）。"""
    assert "session" in aa.SESSION_KNOWN_TYPES


# ---------- ③ id 字符集与匹配半径 ----------

def _encode_segment(raw: str) -> str:
    """dsh 0.1.5 encodeSegment 镜像（persistence-jsonl :852；只读消费方冻结镜像，
    KI-046 同款纪律：本镜像只服务测试判据，引擎运行面不引它）。"""
    out = []
    for ch in raw:
        if ch != "~" and ("a" <= ch <= "z" or "A" <= ch <= "Z"
                          or "0" <= ch <= "9" or ch in "._-"):
            out.append(ch)
        else:
            out.append("~%04X" % ord(ch))
    return "".join(out)


def test_engine_session_id_charset_is_encodesegment_identity():
    """本引擎 id 字符集（<ticket>-<role> ⊆ [A-Za-z0-9._-]）下 encodeSegment=恒等——
    目录名即 id，读侧前缀匹配与写/续侧同源（t260922-06 方案 §0.3）；
    字符集外的 id 会转义成 ~XXXX 目录名（与 id 字面失配）→ 引擎 id 必须留在安全集。"""
    for sid in (SESSION_ID, TICKET + "-acceptance", "t260922-06.reviewer", "a0._-9"):
        assert _encode_segment(sid) == sid
    # 字符集外样例（镜像语义自证，非引擎产出形态）：转义不恒等
    assert _encode_segment("a~b") == "a~007Eb"
    assert _encode_segment("../x") == "..~002Fx"


def test_radius_stays_two_levels_under_v3_name(tmp_path):
    """三层深度（sessions 直下放 v3 档）不入统计集——与 dualname 套件 review C2 同锚。"""
    f = tmp_path / ".dsh" / "sessions" / SESSION_ID / "session.v3.jsonl.zstd"
    f.parent.mkdir(parents=True)
    f.write_bytes(_v3_session_bytes(SESSION_ID))
    tokens, note = aa._aggregate_lane_usage(tmp_path, TICKET)
    assert tokens["tokens_zero"] is True
    assert SESSION_ID in note  # S3 点名，不静默
