"""t260924-09 走查/仲裁段取证面瘦身 UT（KI-117）。

被测：agent_activities._classify_suite_calls（纯分类器：定点豁免/口径漂移/口径
含非法 token/全量超上限）、_iter_suite_invocations（套件调用识别）、
_scan_suite_sessions（integration 角色钉档段会话扫描）、_apply_suite_budget（段
回执归位）+ _stamp_result_file_suite（结果文件 full_suite_violations 幂等回写）、
dev_lane.FLOW_BRIEF（arbitrate/acceptance_walkthrough 文案纪律与执法口径同步）、
挂点源码锁（双返回点链在 developer 集成禁跑执法之后）。

票面验收映射：
  必做①（文案）→ TestPromptSync；必做②（条数上限机械化）→ TestClassifier +
  TestApply；必做③（口径一致/畸形 token 复算）→ TestClassifier（C2/T1 用例）；
  必做④（对照证据）→ TestPromptSync（文案面，报告面走人工/走查自查）。
  T2（段归属=最后 user/message 帧之后）→ TestSessionScan。

UT 全程禁网络/真 Temporal/真 git，不跑任何集成入口（守卫拦的命令只作为**字符串
夹具**出现在分类器入参里，从不执行——t260921-04 先例）。zstd 用系统 CLI 造档。
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agent_activities as aa  # noqa: E402
import dev_lane  # noqa: E402
import shared  # noqa: E402

TICKET = "t260924-09"
GATE = "--exclude-pools engine,exclusive"
BARE = "python3 integration/run_scenarios.py"
TARGETED = "python3 integration/run_scenarios.py --only sc_some_case"


def _kinds(violations):
    return sorted(v["kind"] for v in violations)


# ---------- S1：纯分类器 ----------

class TestClassifier:
    def test_targeted_exempt(self):
        """定点复跑（--only 名单非空）豁免，多趟也不计入上限。"""
        v, n = aa._classify_suite_calls([TARGETED, TARGETED + ",sc_other"])
        assert v == []
        assert "定点 2 趟（豁免）" in n[0]

    def test_bare_full_is_drift(self):
        """裸全量（未传 --exclude-pools）=口径漂移，点名零排除与闸口径。"""
        v, _ = aa._classify_suite_calls([BARE])
        assert _kinds(v) == ["drift"]
        assert "bare full run" in v[0]["detail"]
        assert "engine,exclusive" in v[0]["detail"]

    def test_gate_caliber_full_counted_once_green(self):
        """合规全量（闸口径）首趟不违规、入计数。"""
        v, n = aa._classify_suite_calls(["%s %s" % (BARE, GATE)])
        assert v == []
        assert "合规全量 1 趟" in n[0]

    def test_second_full_over_limit(self):
        """R2 用例：合法形态全量第 2 趟=「全量超上限」违规（合法形态同样入上限）。"""
        v, _ = aa._classify_suite_calls(["%s %s" % (BARE, GATE)] * 2)
        assert _kinds(v) == ["over_limit"]
        assert "full run over limit" in v[0]["detail"]
        assert "run #2" in v[0]["detail"]

    def test_targeted_does_not_consume_full_limit(self):
        """定点与全量分账：定点 N 趟 + 合规全量 1 趟 = 绿。"""
        v, _ = aa._classify_suite_calls(
            [TARGETED, TARGETED, "%s %s" % (BARE, GATE)])
        assert v == []

    def test_missing_pool_is_drift(self):
        """缺闸池（只排 engine）=口径漂移，点名缺哪个池。"""
        v, _ = aa._classify_suite_calls([BARE + " --exclude-pools engine"])
        assert _kinds(v) == ["drift"]
        assert "exclusive" in v[0]["detail"]

    def test_malformed_only_token_is_drift(self):
        """C2 用例：`--exclude-pools engin` 实际零排除（解析器只剥离不判红）
        ——守卫必须复算 token，判漂移不得凭 flag 存在豁免。"""
        v, _ = aa._classify_suite_calls([BARE + " --exclude-pools engin"])
        assert _kinds(v) == ["drift"]
        # engin 语法合法（[a-z0-9-]+）但不在册=未知池不排除任何条目=实际全量
        # ——判漂移（缺闸池），不凭「传了 exclude」豁免
        assert "is not the gate scope" in v[0]["detail"]
        assert "exclusive" in v[0]["detail"]

    def test_gate_plus_extra_bad_token_distinct_kind(self):
        """T1 用例：`engine,exclusive,engin`——排除已生效 + 额外非法 token =
        独立 kind「malformed_token」，文案「口径含非法 token」且不含「裸全量」
        （与零排除型漂移区分归因方向）。"""
        v, _ = aa._classify_suite_calls(
            [BARE + " --exclude-pools engine,exclusive,engin"])
        assert _kinds(v) == ["malformed_token"]
        assert "contains illegal token" in v[0]["detail"]
        assert "bare full run" not in v[0]["detail"]

    def test_empty_exclude_value_is_drift(self):
        """空串 exclude（executor 语义=全量）→ 漂移。"""
        v, _ = aa._classify_suite_calls([BARE + " --exclude-pools="])
        assert _kinds(v) == ["drift"]
        v, _ = aa._classify_suite_calls([BARE + " --exclude-pools ''"])
        assert _kinds(v) == ["drift"]

    def test_eq_form_flag_parsing(self):
        """`--exclude-pools=…` 连写形：executor `_cli` 只认空格形（argv.index），
        =形会被静默忽略=实际裸全量——守卫与 executor 同语义判漂移（不凭
        「看起来传了」豁免）。"""
        v, _ = aa._classify_suite_calls(
            [BARE + " --exclude-pools=engine,exclusive"])
        assert _kinds(v) == ["drift"]
        assert "bare full run" in v[0]["detail"]

    def test_only_missing_value_means_full(self):
        """`--only` 缺值=空名单=executor 语义全量，不走豁免。"""
        v, _ = aa._classify_suite_calls([BARE + " --only"])
        assert _kinds(v) == ["drift"]

    def test_invocation_forms_recognized(self):
        """各执行形态都识别为套件调用（同执法锚定口径）：-m 模块、直接执行、
        sh -c 递归；只读动词不产出调用。"""
        v, _ = aa._classify_suite_calls([
            "python3 -m integration.run_scenarios",               # -m 模块形
            "./integration/run_scenarios.py",                     # 直接执行
            "bash -c '%s %s'" % (BARE, GATE),                     # -c 递归→合规
            "sh -c '%s'" % BARE,                                  # -c 递归→漂移
            "grep -rn run_scenarios server/engine",               # 只读不判
            "cat integration/run_scenarios.py | head -3",         # 只读不判
        ])
        # 漂移×3：-m 模块缺省=裸全量、直接执行裸、sh -c 递归裸；-c 闸口径=合规
        assert _kinds(v) == ["drift", "drift", "drift"]

    def test_multi_invocation_single_command_counts(self):
        """一条命令串里两趟全量（&&连写）也超上限（计数跨 invocation 累计）。"""
        v, _ = aa._classify_suite_calls(
            ["%s %s && %s %s" % (BARE, GATE, BARE, GATE)])
        assert _kinds(v) == ["over_limit"]

    def test_malformed_inputs_no_crash(self):
        """畸形输入用例：None/非串元素/空表——不抛，响亮 note 不静默绿。"""
        for bad in (None, [None, 123], [], ""):
            v, n = aa._classify_suite_calls(bad)
            assert v == []
            assert n, "零静默：%r" % (bad,)


# ---------- S2：段会话扫描（角色钉档/段归属/零静默） ----------

def _zstd_bytes(raw: bytes) -> bytes:
    return subprocess.run(["zstd", "-z", "-c"], input=raw,
                          capture_output=True, check=True).stdout


def _frame(seq, ftype, data):
    return {"type": ftype, "seq": seq, "time": 1789956469345, "data": data}


def _user(seq, text="【派活指令】阶段：acceptance_walkthrough（角色=integration）"):
    return _frame(seq, "user/message",
                  {"content": [{"type": "text", "text": text}]})


def _bash(seq, command):
    return _frame(seq, "tool/call",
                  {"turn": 1, "step": seq, "callId": "c%d" % seq, "name": "bash",
                   "arguments": json.dumps({"command": command, "description": "d"})})


def _write_session(root: Path, role: str, frames, tail: bytes = b"") -> Path:
    d = root / ".dsh" / "sessions" / "ws-x" / ("%s-%s" % (TICKET, role))
    d.mkdir(parents=True, exist_ok=True)
    raw = b"".join((json.dumps(f) + "\n").encode() for f in frames) + tail
    p = d / "session.jsonl.zstd"
    p.write_bytes(_zstd_bytes(raw))
    return p


@pytest.mark.skipif(shutil.which("zstd") is None,
                    reason="zstd CLI 缺席（引擎读侧既有依赖，缺供即环境红）")
class TestSessionScan:
    def test_scan_hits_with_seq(self, tmp_path):
        """正用例：integration 档裸全量+定点 → 漂移命中点名 seq，定点不判。"""
        _write_session(tmp_path, "integration",
                       [_user(0), _bash(1, BARE), _bash(2, TARGETED)])
        violations, notes = aa._scan_suite_sessions(tmp_path, TICKET, "integration")
        assert len(violations) == 1
        assert violations[0]["kind"] == "drift"
        assert violations[0]["seq"] == "1"

    def test_over_limit_across_commands(self, tmp_path):
        """两趟合规全量分散在两条命令 → 第 2 趟超上限命中（跨命令计数）。"""
        _write_session(tmp_path, "integration", [
            _user(0), _bash(1, "%s %s" % (BARE, GATE)),
            _bash(2, "%s %s" % (BARE, GATE)),
        ])
        violations, _ = aa._scan_suite_sessions(tmp_path, TICKET, "integration")
        assert _kinds(violations) == ["over_limit"]
        assert violations[0]["seq"] == "2"

    def test_t2_section_attribution(self, tmp_path):
        """T2：段归属=最后 user/message 帧之后——界前回合（前段）不判；
        界后（本段全部回合）入上限计数。"""
        _write_session(tmp_path, "integration", [
            _user(0, "第 1 次进段"), _bash(1, BARE),
            _user(2, "第 2 次进段"), _bash(3, BARE),
        ])
        violations, notes = aa._scan_suite_sessions(tmp_path, TICKET, "integration")
        assert len(violations) == 1
        assert violations[0]["seq"] == "3"
        assert any("只判最后 user/message 帧之后" in n for n in notes)

    def test_role_pinned_no_cross_role_pickup(self, tmp_path):
        """角色钉档：只扫 <ticket>-integration 档，developer 档违规不背入。"""
        _write_session(tmp_path, "developer", [_user(0), _bash(1, BARE)])
        violations, notes = aa._scan_suite_sessions(tmp_path, TICKET, "integration")
        assert violations == []
        assert any("未发现" in n and "t260924-09-integration" in n for n in notes)

    def test_zero_session_loud_note(self, tmp_path):
        """零档=响亮 note，不静默绿。"""
        violations, notes = aa._scan_suite_sessions(tmp_path, TICKET, "integration")
        assert violations == []
        assert any("未发现" in n for n in notes)

    def test_malformed_frames_counted(self, tmp_path):
        """畸形输入用例：arguments 非 JSON/缺字段帧计数 note，不拦其余帧。"""
        _write_session(tmp_path, "integration", [
            _user(0),
            _frame(1, "tool/call", {"name": "bash", "arguments": "not-json{{"}),
            _bash(2, BARE),
        ])
        violations, notes = aa._scan_suite_sessions(tmp_path, TICKET, "integration")
        assert len(violations) == 1
        assert any("畸形 1 条" in n for n in notes)

    def test_torn_and_garbage_loud(self, tmp_path):
        """畸形输入用例：torn zstd → 响亮 note 不判红不静默。"""
        good = _zstd_bytes(b'{"type":"user/message","seq":0,"data":{}}\n')
        d = tmp_path / ".dsh" / "sessions" / "ws-x" / ("%s-integration" % TICKET)
        d.mkdir(parents=True)
        (d / "session.jsonl.zstd").write_bytes(good[:len(good) // 2])
        violations, notes = aa._scan_suite_sessions(tmp_path, TICKET, "integration")
        assert violations == []
        assert any("解压失败" in n or "零可解析" in n or "不可读" in n for n in notes)

    def test_scan_exception_loud(self, tmp_path, monkeypatch):
        """扫描异常响亮不吞（fail-open=静默漏判红不可取）。"""
        _write_session(tmp_path, "integration", [_user(0), _bash(1, BARE)])

        def boom(path):
            raise RuntimeError("注入故障")

        monkeypatch.setattr(aa, "_decompress_session_text", boom)
        violations, notes = aa._scan_suite_sessions(tmp_path, TICKET, "integration")
        assert violations == []
        assert any("RuntimeError" in n for n in notes)


# ---------- S3：段回执归位 / 结果文件幂等回写 ----------

def _mk_args(role="integration", result_file=""):
    return shared.AgentStageArgs(ticket_id=TICKET, stage_id="arbitrate",
                                 role=role, prompt="p", workspace=None,
                                 result_file=result_file, log_file="")


class TestApply:
    def test_developer_role_passthrough(self, tmp_path):
        """developer 段不归本护栏管（归集成禁跑执法，互不越界）。"""
        res = shared.StageResult(status="ok", summary="s")
        out = aa._apply_suite_budget(res, tmp_path, _mk_args(role="developer"))
        assert out.status == "ok"
        assert out.full_suite_violations == []

    def test_violation_reds_stage_and_stamps_file(self, tmp_path):
        """命中：段红+summary 前缀点名+report/evidence 追加+结果文件回写。"""
        _write_session(tmp_path, "integration", [_user(0), _bash(1, BARE)])
        rfile = tmp_path / "result.json"
        rfile.write_text(json.dumps({"status": "ok", "summary": "走查完成"}),
                         "utf-8")
        res = shared.StageResult(status="ok", summary="走查完成")
        out = aa._apply_suite_budget(res, tmp_path, _mk_args(result_file=str(rfile)))
        assert out.status == "failed"
        assert "[evidence-face budget exceeded]" in out.summary
        assert "bare full run" in out.summary
        # t260924-09 缺陷③：summary 必点名首条命令原文（同 t260921-04 执法
        # 契约——台面一行可定位是哪条命令越界，kind/detail 只作归因）。
        assert BARE in out.summary
        assert out.full_suite_violations and out.full_suite_violations[0]["kind"] == "drift"
        assert "取证面护栏命中" in out.report
        assert "full_suite_violations=" in out.evidence
        raw = json.loads(rfile.read_text("utf-8"))
        assert raw["status"] == "failed"
        assert raw["full_suite_violations"][0]["kind"] == "drift"

    def test_idempotent_no_double_red(self, tmp_path):
        """幂等：文件已带 full_suite_violations / res 已带违规 → 不重复改写。"""
        _write_session(tmp_path, "integration", [_user(0), _bash(1, BARE)])
        rfile = tmp_path / "result.json"
        rfile.write_text(json.dumps({"status": "ok", "summary": "走查完成"}),
                         "utf-8")
        res = shared.StageResult(status="ok", summary="走查完成")
        out1 = aa._apply_suite_budget(res, tmp_path, _mk_args(result_file=str(rfile)))
        out2 = aa._apply_suite_budget(out1, tmp_path, _mk_args(result_file=str(rfile)))
        assert out2.summary == out1.summary  # 二次归位不叠前缀（already 分支）
        raw = json.loads(rfile.read_text("utf-8"))
        assert len(raw["full_suite_violations"]) == 1

    def test_green_no_file_write_note_only(self, tmp_path):
        """无违规：不翻红绿、不回写文件，note 进 integration_scan_note。"""
        _write_session(tmp_path, "integration", [_user(0), _bash(1, TARGETED)])
        rfile = tmp_path / "result.json"
        rfile.write_text(json.dumps({"status": "ok", "summary": "走查完成"}),
                         "utf-8")
        res = shared.StageResult(status="ok", summary="走查完成")
        out = aa._apply_suite_budget(res, tmp_path, _mk_args(result_file=str(rfile)))
        assert out.status == "ok"
        assert out.integration_scan_note
        raw = json.loads(rfile.read_text("utf-8"))
        assert "full_suite_violations" not in raw  # note 不落结果文件（最小侵入）

    def test_no_session_is_note_not_red(self, tmp_path):
        """零档=未判成不判绿也不误红（零静默 note 走注记面）。"""
        res = shared.StageResult(status="ok", summary="s")
        out = aa._apply_suite_budget(res, tmp_path, _mk_args())
        assert out.status == "ok"
        assert "未发现" in out.integration_scan_note


# ---------- S4：口径同步 / 挂点源码锁 / 双真源夹具锁 ----------

class TestPromptSync:
    def test_gate_pools_two_truth_sources_locked(self):
        """双真源夹具锁：守卫常量 == 闸配置 verify.yaml exclude_pools（改池须
        同批同步两处——见 agent_activities.GATE_EXCLUDE_POOLS 注记）。"""
        import re as _re
        yml = (Path(__file__).resolve().parents[3] / "verify.yaml").read_text("utf-8")
        m = _re.search(r"exclude_pools:\s*(\S+)", yml)
        assert m, "verify.yaml 缺 exclude_pools 配置"
        assert tuple(m.group(1).split(",")) == aa.GATE_EXCLUDE_POOLS

    @pytest.mark.parametrize("stage", ["arbitrate", "acceptance_walkthrough"])
    def test_prompt_carries_discipline(self, stage):
        """必做①/④：两段派活文案写死四条纪律关键词（文案面与执法同批）。"""
        prompt = dev_lane.FLOW_BRIEF[stage]
        assert "--only" in prompt
        assert "--exclude-pools engine,exclusive" in prompt
        assert "对照证据" in prompt
        assert "只许 1 趟" in prompt
        assert "full_suite_violations" in prompt

    def test_guard_wording_distinct_kinds(self):
        """T1 措辞锁：守卫侧「口径含非法 token」与「裸全量」文案互斥可辨
        （报错必须精确——归因不引向零排除）。"""
        v1, _ = aa._classify_suite_calls([BARE])
        v2, _ = aa._classify_suite_calls(
            [BARE + " --exclude-pools engine,exclusive,engin"])
        assert "bare full run" in v1[0]["detail"] and "illegal token" not in v1[0]["detail"]
        assert "contains illegal token" in v2[0]["detail"] and "bare full run" not in v2[0]["detail"]

    def test_hook_source_lock(self):
        """挂点源码锁：真 spawn 返回点以赋值/返回形链「执法 → 取证护栏」，防止
        后续改动漏挂（缓存命中路径漏执法）。"""
        src = Path(aa.__file__).read_text("utf-8")
        assert src.count("def _apply_suite_budget(") == 1
        # t261001-03：真 spawn 返回点随轮询循环合一改走「return _apply_suite_budget(
        # …)」形——挂点仍在真 spawn 路径（_on_result），计数由 2 收敛到 1；缓存命中
        # 路径（_stub_stage_shortcut 直 return stub）不经执法面，口径不变。
        assert src.count("res = _apply_suite_budget(") == 1
        assert src.count("return _apply_suite_budget(") == 1, \
            "取证护栏必须挂在真 spawn 返回点（合一后的 _on_result 链尾）"
        assert src.count("_apply_integration_discipline(") == 3  # def + 2 调用点

    def test_shared_field_defaults_safe(self):
        """老回执重放安全：full_suite_violations 缺省空表。"""
        res = shared.StageResult(status="ok", summary="s")
        assert res.full_suite_violations == []
