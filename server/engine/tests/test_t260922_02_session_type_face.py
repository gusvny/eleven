"""t260922-02 双代会话词表面单测：0.1.5 类型识别 + 未覆盖响亮注记 + 双向词表锁。

被测（agent_activities，t260922-02 dsh 升级前置）：
  - SESSION_KNOWN_TYPES（S1 判据词表）：原 6 项 + 0.1.5 独有 11 项——两代
    GENERATED 目录 known-event-types.js 机械导出（0.1.1=48 / 0.1.5=56 / 并集 59）；
  - SESSION_TWO_GEN_TYPES（双代抑制超集 63 项 = 并集 59 ∪ {session 头行} ∪ chunk
    存储行 3）→ _judge_session_lines 加性键 uncovered_types/uncovered_count；
  - _aggregate_lane_usage：词表外类型聚合级人话点名 + uncovered_types 旗标——
    「禁静默」本票存在的理由（T2 升级时的响亮绊线）；
  - 0.1.1 回归锚（golden-first）：0.1.1 夹具的 judge 计数/aggregate totals/note
    与改码前快照逐字一致（本文件字面量即改码前实测，见 git history t260922-02）；
  - 词表锁（py←TS 方向）：读 workbench src/host/agent-live.ts 源码提取两张集合
    字面量对拍本侧（KI-046 冻结镜像防只改一边；对侧锁在
    server/plugins/workbench/tests/t260922-02-session-type-face.mjs）。

夹具真源：形状锚 0.1.5 安装包 dsh-session/lib/types/types.d.ts + 本泳道真 0.1.5
样本（.sandbar/probe-dsh015，隔离 home 实产 19 行头部记录）+ 真 0.1.1 会话直方图
（.dsh/sessions 实测 20 型全集）。0.1.5 夹具的 usage 故意缺 cacheReadTokens
（0.1.5 TokenUsage 该键转可选，dsh-llm types.d.ts:136）。

UT 全程禁网络/真 Temporal；zstd 用系统 CLI（缺则相关用例 skip，同 test_t260917-05）。
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import agent_activities as aa  # noqa: E402

TICKET = "t260922-02"
REPO = Path(__file__).resolve().parents[3]  # tests→engine→server→仓根（C6 教训：路径先实测）
TS_LIVE = REPO / "server/plugins/workbench/src/host/agent-live.ts"

HAS_ZSTD = subprocess.run(["zstd", "--version"], capture_output=True).returncode == 0


def _zstd_file(path: Path, raw: bytes) -> None:
    """把 zstd 压缩字节写到 path（父目录自动建）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    p = subprocess.run(["zstd", "-z", "-c"], input=raw, capture_output=True, check=True)
    path.write_bytes(p.stdout)


def _lines(fixture) -> list:
    """夹具对象 → jsonl 行数组（judge 的输入形状）。"""
    return [json.dumps(o) for o in fixture]


# ---------- 双代夹具（形状真源见文件头；与 workbench mjs 测试同构对账） ----------

V011 = [  # 0.1.1 缩样：真会话直方图 20 型全集 + S1 核心（golden 快照锚）
    {"type": "session", "version": 1, "id": "s1", "createdAt": 1000},
    {"type": "request/context", "seq": 1, "time": 1100, "data": {"provider": "p", "model": "m"}},
    {"type": "request/header", "seq": 2, "time": 1200, "data": {"header": {"config": {"provider": "p", "model": "m"}}}},
    {"type": "permission/preset", "seq": 3, "time": 1300, "data": {"preset": "workspace-write"}},
    {"type": "sandbox/mode", "seq": 4, "time": 1400, "data": {"mode": "workspace-write"}},
    {"type": "approval/policy", "seq": 5, "time": 1500, "data": {"policy": "ask"}},
    {"type": "session/title", "seq": 6, "time": 1600, "data": {"title": "t", "source": {"kind": "fallback"}}},
    {"type": "turn/start", "seq": 7, "time": 1700, "data": {"turn": 1}},
    {"type": "step/start", "seq": 8, "time": 1800, "data": {"turn": 1, "step": 1}},
    {"type": "user/message", "seq": 9, "time": 1900, "data": {"content": [{"type": "text", "text": "hi"}]}},
    {"type": "reasoning-chunks", "seq": 10, "time": 2000, "data": {"texts": ["a"]}},
    {"type": "text-chunks", "seq": 11, "time": 2100, "data": {"texts": ["b"]}},
    {"type": "assistant/chunk", "seq": 12, "time": 2200, "data": {"chunk": {"type": "text"}}},
    {"type": "assistant/message", "seq": 13, "time": 2300, "data": {"message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}, "usage": {"inputTokens": 7, "outputTokens": 8, "cacheReadTokens": 1}}},
    {"type": "tool/call", "seq": 14, "time": 2400, "data": {"name": "read", "arguments": "{}"}},
    {"type": "tool/result", "seq": 15, "time": 2500, "data": {"message": {"role": "toolResult", "content": [{"type": "text", "text": "r"}]}}},
    {"type": "step/end", "seq": 16, "time": 2600, "data": {"turn": 1, "step": 1}},
    {"type": "turn/end", "seq": 17, "time": 2700, "data": {"turn": 1, "reason": "end"}},
    {"type": "session/end-seed", "data": {}},
    {"type": "agent/inbox/spliced", "seq": 18, "time": 2800, "data": {"target": "next-turn", "start": 0, "inserted": []}},
    {"type": "llm/retry", "seq": 19, "time": 2900, "data": {"provider": "zai"}},
    {"type": "llm/retry-started", "seq": 20, "time": 2950, "data": {"retry": 1}},
    {"type": "tool-call-chunks", "data": {}},
    {"type": "tool/code-dispatch", "data": {}},
    {"type": "tool/code-dispatch-start", "data": {}},
]
V015 = [  # 0.1.5 样：真 19 行头部记录缩样 + 0.1.5 独有 11 型全覆盖；usage 缺 cacheReadTokens（可选键钉）
    {"type": "session", "version": 3, "id": "s2", "createdAt": 1000},
    {"type": "permission/preset", "seq": 0, "time": 1100, "data": {"preset": "workspace-write"}},
    {"type": "sandbox/mode", "seq": 1, "time": 1200, "data": {"mode": "workspace-write"}},
    {"type": "approval/policy", "seq": 2, "time": 1300, "data": {"policy": "ask"}},
    {"type": "session/title-llm-request", "seq": 3, "time": 1400, "data": {"titleProvider": "session-title-first-prompt-llm", "route": {"provider": "p"}}},
    {"type": "agent/inbox/spliced", "seq": 4, "time": 1500, "data": {"target": "next-turn", "start": 0, "inserted": []}},
    {"type": "turn/start", "seq": 5, "time": 1600, "data": {"turn": 1}},
    {"type": "step/start", "seq": 6, "time": 1700, "data": {"turn": 1, "step": 1}},
    {"type": "system/message", "seq": 7, "time": 1800, "data": {"turn": 1, "step": 1, "message": {"role": "system", "content": [{"type": "text", "text": "sys"}]}}},
    {"type": "user/message", "seq": 8, "time": 1900, "data": {"content": [{"type": "text", "text": "q"}]}},
    {"type": "request/header", "seq": 9, "time": 2000, "data": {"header": {"config": {"provider": "p", "model": "m"}}}},
    {"type": "request/context", "seq": 10, "time": 2100, "data": {"provider": "p", "model": "m"}},
    {"type": "session/title", "seq": 11, "time": 2200, "data": {"title": "t", "source": {"kind": "fallback"}}},
    {"type": "assistant/attempt", "seq": 12, "time": 2300, "data": {"turn": 1, "step": 1, "stream": [{"type": "chunk", "time": 2301, "chunk": {"type": "text", "text": "partial"}}]}},
    {"type": "assistant/message", "seq": 13, "time": 2400, "data": {"turn": 1, "step": 1, "message": {"role": "assistant", "content": [{"type": "text", "text": "done"}]}, "stream": [], "usage": {"inputTokens": 11, "outputTokens": 13}}},
    {"type": "tool/call", "seq": 14, "time": 2500, "data": {"name": "read", "arguments": "{}"}},
    {"type": "tool/result", "seq": 15, "time": 2600, "data": {"message": {"role": "toolResult", "content": [{"type": "text", "text": "r"}]}}},
    {"type": "step/end", "seq": 16, "time": 2700, "data": {"turn": 1, "step": 1}},
    {"type": "turn/end", "seq": 17, "time": 2800, "data": {"turn": 1, "reason": "end"}},
    {"type": "deliverables/presented", "data": {}},
    {"type": "feedback/message-delete", "data": {}},
    {"type": "feedback/message-put", "data": {}},
    {"type": "model/selection", "data": {}},
    {"type": "session-log-deepseek/delivery-accepted", "data": {}},
    {"type": "subagent/catalog", "data": {}},
    {"type": "subagent/model-selection-policy", "data": {}},
    {"type": "tool/ptc-dispatch", "data": {}},
    {"type": "tool/ptc-dispatch-start", "data": {}},
]
PREDISPATCH = [  # CC1(a) 案：无 session 头行（撕裂/超早期中止形态）——旧码 known==0
    # 假 S1「格式不认识」（golden-first 实测钉：会话记录格式不认识（疑似 dsh 版本
    # 不匹配），统计值不可信），新码 known==2 不再假报（识别钉；野外是否出现该
    # 形态待真样本裁决，识别本身必须钉死）。
    {"type": "turn/start", "data": {"turn": 1}},
    {"type": "step/start", "data": {"turn": 1, "step": 1}},
    {"type": "system/message", "data": {"turn": 1, "step": 1, "message": {"role": "system", "content": [{"type": "text", "text": "sys"}]}}},
    {"type": "assistant/attempt", "data": {"turn": 1, "step": 1, "stream": []}},
]
UNCOV = [  # 反向注入：词表外类型（疑似更新代 dsh）——「缺得不静默」的机械钉
    {"type": "request/context", "data": {"provider": "p", "model": "m"}},
    {"type": "v9/whatever", "data": {}},
]


# ---------- 词表形状（底册机械导出的一致性） ----------


def test_vocab_shapes_and_mirror_container():
    """S1 集 17=6+11、超集 63=59+1+3、S1 ⊆ 超集；0.1.1 已识型不进 S1（C2 纪律）。"""
    assert len(aa.SESSION_KNOWN_TYPES) == 17
    assert len(aa.SESSION_TWO_GEN_TYPES) == 63
    assert aa.SESSION_KNOWN_TYPES <= aa.SESSION_TWO_GEN_TYPES
    for t in ("assistant/attempt", "system/message", "deliverables/presented",
              "feedback/message-delete", "feedback/message-put", "model/selection",
              "session-log-deepseek/delivery-accepted", "subagent/catalog",
              "subagent/model-selection-policy", "tool/ptc-dispatch",
              "tool/ptc-dispatch-start"):
        assert t in aa.SESSION_KNOWN_TYPES, t  # 0.1.5 独有 11 项全进 S1（C1）
    for t in ("agent/inbox/spliced", "session/title-llm-request"):
        # 两代目录都在列、0.1.1 真会话在产——进 S1 会改 0.1.1 计数（C2），只能进超集
        assert t not in aa.SESSION_KNOWN_TYPES and t in aa.SESSION_TWO_GEN_TYPES, t
    for t in ("session", "text-chunks", "reasoning-chunks", "tool-call-chunks"):
        assert t in aa.SESSION_TWO_GEN_TYPES, t  # 头行 + 存储行（目录外，实测补集）


# ---------- 0.1.1 回归锚（golden-first 快照 = 改码前实测字面） ----------


def test_v011_golden_unchanged():
    """0.1.1 夹具：judge 计数与改码前逐字一致（11 增项不可能命中 0.1.1 行）。"""
    j = aa._judge_session_lines(_lines(V011))
    assert j["blank"] is False
    assert j["parsed"] == 25
    assert j["known_types"] == 6          # golden：session/request×2/assistant×2/tool/call
    assert j["usage_records"] == 1
    assert j["usage_without_known_keys"] == 0
    assert j["uncovered_types"] == []     # 20 型全在超集内（C3 噪声守卫）
    assert j["uncovered_count"] == 0
    assert aa._session_face_s1_text("v011.zstd", j) is None


@pytest.mark.skipif(not HAS_ZSTD, reason="zstd CLI 不可用")
def test_v011_aggregate_golden_unchanged(tmp_path):
    """0.1.1 聚合 golden：totals 与 note==改码前字面，无任何新注记键。"""
    p = tmp_path / ".dsh/sessions/slug" / TICKET
    _zstd_file(p / "session.jsonl.zstd", ("\n".join(_lines(V011)) + "\n").encode())
    tokens, note = aa._aggregate_lane_usage(tmp_path, TICKET)
    assert tokens["in"] == 7 and tokens["out"] == 8 and tokens["cacheRead"] == 1
    assert tokens["tokens_zero"] is False
    assert note == ""
    assert "format_suspect" not in tokens and "uncovered_types" not in tokens


# ---------- 0.1.5 识别面（认得出 / 拿得到） ----------


def test_v015_recognized():
    """0.1.5 夹具：11 独有型全认（known 5→16），S1 不假报，无未覆盖误注。"""
    j = aa._judge_session_lines(_lines(V015))
    assert j["parsed"] == 28
    assert j["known_types"] == 16         # 改码前 golden=5（+11）
    assert j["usage_records"] == 1
    # 0.1.5 TokenUsage 的 cacheReadTokens 转可选：缺它不算「usage 缺全部已知键」
    assert j["usage_without_known_keys"] == 0
    assert j["uncovered_types"] == [] and j["uncovered_count"] == 0
    assert aa._session_face_s1_text("v015.zstd", j) is None


def test_v015_predispatch_no_false_s1():
    """预派发中止形态（CC1(a)：无 session 头行）：旧码假 S1 → 新码识别不假报。"""
    j = aa._judge_session_lines(_lines(PREDISPATCH))
    assert j["known_types"] == 2          # system/message + assistant/attempt（旧码=0）
    assert aa._session_face_s1_text("pred.zstd", j) is None


@pytest.mark.skipif(not HAS_ZSTD, reason="zstd CLI 不可用")
def test_v015_aggregate_usage_without_cacheread(tmp_path):
    """0.1.5 聚合「拿得到」：缺 cacheReadTokens 的 usage 照常入账（缺键记 0）。"""
    p = tmp_path / ".dsh/sessions/slug" / (TICKET + "-dev")
    _zstd_file(p / "session.v3.jsonl.zstd", ("\n".join(_lines(V015)) + "\n").encode())
    tokens, note = aa._aggregate_lane_usage(tmp_path, TICKET)
    assert tokens["in"] == 11 and tokens["out"] == 13 and tokens["cacheRead"] == 0
    assert tokens["tokens_zero"] is False
    assert note == ""                     # 健康路径，无注记键
    assert "uncovered_types" not in tokens


# ---------- 未覆盖点名面（缺得不静默——本票存在的理由） ----------


def test_uncovered_types_loud_not_fatal():
    """词表外类型：uncovered 加性点名（S1 不误触发——注记独立于判据真值表）。"""
    j = aa._judge_session_lines(_lines(UNCOV))
    assert j["known_types"] == 1
    assert j["uncovered_types"] == ["v9/whatever"]
    assert j["uncovered_count"] == 1
    assert aa._session_face_s1_text("uncov.zstd", j) is None  # 不混入 S1 语义


@pytest.mark.skipif(not HAS_ZSTD, reason="zstd CLI 不可用")
def test_uncovered_aggregate_note_and_flag(tmp_path):
    """聚合面：uncovered note 人话点名 + uncovered_types 旗标；totals 不受扰。"""
    p = tmp_path / ".dsh/sessions/slug" / TICKET
    _zstd_file(p / "session.jsonl.zstd", ("\n".join(_lines(UNCOV)) + "\n").encode())
    tokens, note = aa._aggregate_lane_usage(tmp_path, TICKET)
    assert tokens["uncovered_types"] is True
    assert "未覆盖" in note and "v9/whatever" in note and "疑似更新代 dsh" in note


def test_uncovered_noise_guard_structural():
    """C3 噪声守卫①（结构性自检）：超集逐型喂一行 → uncovered 恒空（常量自洽，
    字面量膨胀不烂）；S1 集逐型喂行 → known 命中且 uncovered 空。"""
    for t in sorted(aa.SESSION_TWO_GEN_TYPES):
        j = aa._judge_session_lines([json.dumps({"type": t, "data": {}})])
        assert j["uncovered_types"] == [], t
        assert j["uncovered_count"] == 0, t
    for t in sorted(aa.SESSION_KNOWN_TYPES):
        j = aa._judge_session_lines([json.dumps({"type": t, "data": {}})])
        assert j["known_types"] == 1 and j["uncovered_count"] == 0, t


# ---------- 畸形输入（消费外部记录面纪律） ----------


def test_judge_malformed_inputs_safe():
    """非 list/条目非串/坏 JSON/非映射 JSON/type 非串 → 不抛，uncovered 键恒在。

    （钉出既有潜在崩溃点：type 为不可哈希映射时 frozenset 成员测试曾 TypeError，
    isinstance 守卫后按「不入任何词表计数」处理；known/uncovered 都不数。）"""
    j = aa._judge_session_lines(None)
    assert j["uncovered_types"] == [] and j["uncovered_count"] == 0
    j = aa._judge_session_lines([123, None, "not json", "[1,2]", '{"type": 42, "data": {}}',
                                 '{"no_type": true}', '"str"', "   ", ""])
    assert j["blank"] is False                              # 有非空白行
    assert j["parsed"] == 2                                 # type:42 与 no_type 两个映射行
    assert j["known_types"] == 0
    assert j["uncovered_types"] == [] and j["uncovered_count"] == 0  # 非串/缺型不点名
    j = aa._judge_session_lines(['{"type": {"nested": true}}'])  # type 为映射对象
    assert j["parsed"] == 1 and j["known_types"] == 0
    assert j["uncovered_types"] == [] and j["uncovered_count"] == 0  # 不炸、不点名
    j = aa._judge_session_lines(['{"type": ["assistant/message"]}'])
    assert j["parsed"] == 1 and j["known_types"] == 0 and j["uncovered_count"] == 0


# ---------- 词表锁（py←TS 方向；对侧锁在 t260922-02-session-type-face.mjs） ----------


def _extract_ts_set(src: str, const_name: str) -> set:
    """从 agent-live.ts 源码提取 `export const NAME: ReadonlySet<string> = new Set([...])`
    的字符串字面量全集。正则不命中 → KeyError 响亮 FAIL（禁静默跳过，C5①）。"""
    m = re.search(r"export const %s: ReadonlySet<string> = new Set\(\[(.*?)\]\)" % const_name,
                  src, re.S)
    if m is None:
        raise LookupError("源码锁提取失败：agent-live.ts 未找到 %s 字面量——"
                          "TS 侧词表被重构？两侧必须同批改（KI-046）" % const_name)
    return set(re.findall(r"'([a-z0-9/-]+)'", m.group(1)))


def test_vocab_lock_ts_mirror_known_types():
    """锁①：TS SESSION_KNOWN_TYPES == engine SESSION_KNOWN_TYPES（逐项互等）。"""
    ts = _extract_ts_set(TS_LIVE.read_text("utf-8"), "SESSION_KNOWN_TYPES")
    assert ts == set(aa.SESSION_KNOWN_TYPES)


def test_vocab_lock_ts_mirror_two_gen_types():
    """锁②：TS SESSION_TWO_GEN_TYPES == engine SESSION_TWO_GEN_TYPES（逐项互等）。"""
    ts = _extract_ts_set(TS_LIVE.read_text("utf-8"), "SESSION_TWO_GEN_TYPES")
    assert ts == set(aa.SESSION_TWO_GEN_TYPES)


def test_vocab_lock_anchors_original_members():
    """C5② 独立锚：t260917-05 原 6 项 + 超集关键成员未被「顺手清理」——防噪声
    守卫被拆（先例 workflow-list-topology.mjs D 段「白名单既有键未被动」）。"""
    for t in ("request/context", "request/header", "assistant/message",
              "assistant/chunk", "session", "tool/call"):
        assert t in aa.SESSION_KNOWN_TYPES, t
    for t in ("text-chunks", "reasoning-chunks", "tool-call-chunks", "session",
              "permission/preset", "sandbox/mode", "approval/policy",
              "session/title", "llm/retry-started", "tool/code-dispatch"):
        assert t in aa.SESSION_TWO_GEN_TYPES, t
