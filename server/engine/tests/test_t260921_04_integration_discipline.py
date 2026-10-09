"""t260921-04 developer 段集成禁跑执法 UT（宿主令 260921「单测可跑、集成禁跑」）。

被测：integration_discipline（FORBIDDEN_ENTRIES 规范表 + scan_bash_command 执行锚定
匹配器 + prompt_clause 文案渲染）、agent_activities._scan_integration_sessions
（角色钉档会话扫描）、_apply_integration_discipline（段回执归位）、_read_result
（执法两字段读侧）、dev_lane.FLOW_BRIEF（clause 注入口径同步）。

票面验收用例映射（方案 §5）：
  ① 构造用例 / ② 正用例 / ③ 反用例（只读不判）→ TestMatcher + TestSessionScan
  P1/P2 并行分叉用例（review C1/KI-093：角色钉档防误伤/防漏判）→ TestSessionScan
  N1 零档（C5）/ N2 多回合（C4）/ N3 异常响亮（C2b）→ TestSessionScan
  畸形输入用例（岗位纪律：消费外部会话档必带）→ TestMatcher + TestSessionScan
  ④ 口径同步用例（反用例④：文案禁了必须机械判、机械判的文案必说）→ TestPromptSync
  K1（review 附条件）：bash/sh -c 嵌套命令串递归判，正反例 → TestMatcher

UT 全程禁网络/真 Temporal/真 git；zstd 用系统 CLI 造档（缺则整类 skip，
test_t260916_23 先例）。不跑任何集成入口（被测纪律本身就是本段的纪律）。
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
import dev_lane  # noqa: E402
import integration_discipline as idisc  # noqa: E402
import shared  # noqa: E402

TICKET = "t260921-04"
RUN_SCEN = "python3 integration/run_scenarios.py"


# ---------- 夹具工具 ----------

def _zstd_bytes(raw: bytes) -> bytes:
    return subprocess.run(["zstd", "-z", "-c"], input=raw,
                          capture_output=True, check=True).stdout


def _frame(seq, ftype, data):
    return {"type": ftype, "seq": seq, "time": 1789956469345, "data": data}


def _user(seq, text="【派活指令】阶段：implement（角色=developer）"):
    return _frame(seq, "user/message",
                  {"content": [{"type": "text", "text": text}]})


def _bash(seq, command, name="bash"):
    return _frame(seq, "tool/call",
                  {"turn": 1, "step": seq, "callId": "c%d" % seq, "name": name,
                   "arguments": json.dumps({"command": command,
                                            "description": "d"})})


def _tool(seq, arguments):
    """任意 arguments 的 tool/call 帧（畸形/非 bash 形用）。"""
    return _frame(seq, "tool/call",
                  {"turn": 1, "step": seq, "callId": "c%d" % seq,
                   "name": "bash", "arguments": arguments})


def _write_session(root: Path, role: str, frames, tail: bytes = b"",
                   name: str = "session.jsonl.zstd") -> Path:
    d = root / ".dsh" / "sessions" / "ws-x" / ("%s-%s" % (TICKET, role))
    d.mkdir(parents=True, exist_ok=True)
    raw = b"".join((json.dumps(f) + "\n").encode() for f in frames) + tail
    p = d / name
    p.write_bytes(_zstd_bytes(raw))
    return p


def _touch_newer(path: Path):
    """把档 mtime 推到「最新」（P1/P2 并行分叉用例用：模拟在飞档活写）。"""
    st = path.stat()
    os.utime(path, (st.st_atime + 30, st.st_mtime + 30))


# ---------- S1：执行锚定匹配器（纯函数） ----------

class TestMatcher:
    def test_construct_case_hit_forms(self):
        """构造用例：各执行形态都得判红，点名入口与命令。"""
        for cmd, entry in [
            (RUN_SCEN, "run_scenarios.py"),
            ("cd /tmp/x && python3 run_scenarios.py", "run_scenarios.py"),
            ("./integration/run_scenarios.py --list", "run_scenarios.py"),
            ("python3 -m integration.run_scenarios", "run_scenarios.py"),
            ("timeout 300 " + RUN_SCEN, "run_scenarios.py"),
            ("sudo " + RUN_SCEN, "run_scenarios.py"),
            ("nohup " + RUN_SCEN + " &", "run_scenarios.py"),
            ("env SANDBAR_X=1 " + RUN_SCEN, "run_scenarios.py"),
            ("nice -n 5 " + RUN_SCEN, "run_scenarios.py"),
            ("node integration/baselines/ticket-validate.mjs", "baselines"),
            ("python3 integration/baselines/probe.py", "baselines"),
            ("sh integration/with_stage.sh t260901-13", "with_stage.sh"),
            ("source integration/with_stage.sh", "with_stage.sh"),
            ("python3 server/tools/verify_lane.py lane=integ", "verify_lane"),
            ("python3 admin.py call verify_lane", "verify_lane"),
            ("python3 integration/t260903-01/sc_foo.py", "sc_*"),
            ("node integration/t260903-01/sc_bar.mjs", "sc_*"),
            # C3：pytest 实参 basename 命中=收集即 import 执行
            ("pytest integration/t260903-01/sc_foo.py", "sc_*"),
            ("python3 -m pytest integration/t260903-01/sc_foo.py", "sc_*"),
        ]:
            hits = idisc.scan_bash_command(cmd)
            assert hits, "应判红：%s" % cmd
            assert hits[0]["entry"] == entry, (cmd, hits)
            assert cmd[:len(hits[0]["cmd"])] == hits[0]["cmd"]

    def test_positive_case_allowed_face(self):
        """正用例：允许面（受影响面单测/lint/辅助工具面）全不判。"""
        for cmd in [
            "pytest server/engine/tests/test_x.py",
            "pytest server/engine/tests/test_t260921_04_integration_discipline.py -q",
            "pytest integration/tests/test_bench.py",
            "python3 integration/lint_tests.py",           # 允许面（静态检查）
            "python3 integration/bench.py",                # 辅助工具面（边界清单）
            "python3 integration/stage_docker.py ensure --keep",
            "python3 -m pytest server/engine/tests -k matcher",
            "python3 -m pytest integration/tests",         # 目录形不判
        ]:
            assert idisc.scan_bash_command(cmd) == [], "误伤：%s" % cmd

    def test_readonly_case_no_hit(self):
        """反用例：只读动词的参数提及、echo、git——一律不判（验收③）。"""
        for cmd in [
            "grep -rn run_scenarios server/engine",
            'grep -rn "run_scenarios\\|verify_lane" server/engine/*.py',
            "sed -n '1,50p' integration/run_scenarios.py",
            "cat integration/baselines/ticket-validate.mjs | head -3",
            "ls integration && git log --oneline -3",
            "git diff integration/run_scenarios.py",
            "echo python3 integration/run_scenarios.py",
            "man python3 integration/run_scenarios.py",
        ]:
            assert idisc.scan_bash_command(cmd) == [], "误伤只读：%s" % cmd

    def test_k1_shell_c_recursion(self):
        """K1（review 附条件）：bash/sh -c 嵌套串按同规则递归——正反例成对。"""
        # 正例：递归后动词锚定命中
        hits = idisc.scan_bash_command('bash -c "%s"' % RUN_SCEN)
        assert hits and hits[0]["entry"] == "run_scenarios.py"
        hits = idisc.scan_bash_command(
            "sh -c 'node integration/baselines/ticket-validate.mjs'")
        assert hits and hits[0]["entry"] == "baselines"
        hits = idisc.scan_bash_command(
            "bash -c 'cd integration && python3 run_scenarios.py -k x'")
        assert hits and hits[0]["entry"] == "run_scenarios.py"
        # 反例（review 原话用例）：递归后只读动词照样豁免——不得因路径子串误判
        assert idisc.scan_bash_command('bash -c "ls integration/baselines"') == []
        assert idisc.scan_bash_command("sh -c 'cat integration/run_scenarios.py'") == []

    def test_boundary_declared_no_hit(self):
        """docstring 边界清单落字项：不执法的形态必须真的不判（口径诚实）。"""
        assert idisc.scan_bash_command(
            'python3 -c "import integration.run_scenarios"') == []   # -c 内联
        assert idisc.scan_bash_command(
            "ls integration | xargs -I{} python3 {}") == []          # xargs
        assert idisc.scan_bash_command("pytest integration") == []   # 目录形
        assert idisc.scan_bash_command("pytest integration/tests") == []

    def test_malformed_inputs_no_crash(self):
        """畸形输入用例：非串/空/引号不平衡/超长/深度嵌套——不抛，可判则判。"""
        assert idisc.scan_bash_command(None) == []
        assert idisc.scan_bash_command(123) == []
        assert idisc.scan_bash_command("") == []
        assert idisc.scan_bash_command("   ") == []
        hits = idisc.scan_bash_command(RUN_SCEN + ' "unclosed')  # shlex 失败→兜底
        assert hits and hits[0]["entry"] == "run_scenarios.py"
        hits = idisc.scan_bash_command(RUN_SCEN + " " + "x" * 9000)
        assert hits and len(hits[0]["cmd"]) <= 200               # 截断点名
        deep = RUN_SCEN
        for _ in range(6):                                       # 递归深度封顶
            deep = "bash -c '%s'" % deep
        assert isinstance(idisc.scan_bash_command(deep), list)

    def test_multi_segment_single_hit(self):
        hits = idisc.scan_bash_command(
            "cd /tmp && echo hi; " + RUN_SCEN + " && echo done")
        assert len(hits) == 1 and hits[0]["entry"] == "run_scenarios.py"


# ---------- S2：会话扫描（角色钉档 / 段归属 / 零静默） ----------

@pytest.mark.skipif(shutil.which("zstd") is None,
                    reason="zstd CLI 缺席（引擎读侧既有依赖，缺供即环境红）")
class TestSessionScan:
    def test_construct_case_red_named(self, tmp_path):
        """用例①：developer 档本回合执行 run_scenarios.py → 命中且点名命令。"""
        _write_session(tmp_path, "developer",
                       [_user(0), _bash(1, RUN_SCEN + " -k x")])
        violations, notes = aa._scan_integration_sessions(tmp_path, TICKET,
                                                          "developer")
        assert len(violations) == 1
        assert RUN_SCEN in violations[0]["cmd"]
        assert violations[0]["entry"] == "run_scenarios.py"
        assert violations[0]["seq"] == "1"

    def test_positive_case_green(self, tmp_path):
        """用例②：只跑受影响面单测 + lint → 绿、无点名。"""
        _write_session(tmp_path, "developer", [
            _user(0),
            _bash(1, "pytest server/engine/tests/test_x.py -q"),
            _bash(2, "python3 integration/lint_tests.py"),
        ])
        violations, notes = aa._scan_integration_sessions(tmp_path, TICKET,
                                                          "developer")
        assert violations == []

    def test_readonly_case_green(self, tmp_path):
        """用例③：只读集成代码/文档（含 prompt 回显提及）→ 不判红。"""
        _write_session(tmp_path, "developer", [
            _user(0, "方案里要核对 integration/run_scenarios.py 的口径"),
            _frame(1, "tool/call", {"name": "grep", "arguments": json.dumps(
                {"pattern": "run_scenarios", "path": "server/engine"})}),
            _bash(2, "sed -n '1,50p' integration/run_scenarios.py"),
            _bash(3, "grep -rn verify_lane server/engine"),
        ])
        violations, notes = aa._scan_integration_sessions(tmp_path, TICKET,
                                                          "developer")
        assert violations == []

    def test_p1_parallel_fork_no_false_red(self, tmp_path):
        """P1（C1/KI-093）：integration 档含违规且 mtime 最新 → developer 段不背红。"""
        _write_session(tmp_path, "developer", [_user(0), _bash(1, "pytest test_x.py")])
        intg = _write_session(tmp_path, "integration",
                              [_user(0), _bash(1, RUN_SCEN)])
        _touch_newer(intg)  # 在飞档：mtime 必最新
        violations, notes = aa._scan_integration_sessions(tmp_path, TICKET,
                                                          "developer")
        assert violations == []

    def test_p2_parallel_fork_no_missed_red(self, tmp_path):
        """P2（C1/KI-093）：developer 档违规 + integration 档最新 → 红不丢。"""
        dev = _write_session(tmp_path, "developer", [_user(0), _bash(1, RUN_SCEN)])
        intg = _write_session(tmp_path, "integration",
                              [_user(0), _bash(1, RUN_SCEN)])
        _touch_newer(intg)
        violations, notes = aa._scan_integration_sessions(tmp_path, TICKET,
                                                          "developer")
        assert len(violations) == 1
        assert violations[0]["cmd"].startswith("python3 integration/run_scenarios.py")
        assert "developer" in str(dev)  # 命中来自 developer 档（选档钉角色）

    def test_n1_no_session_loud_note(self, tmp_path):
        """N1（C5）：role 目录不存在 → 不判红 + 响亮 note（不静默绿）。"""
        violations, notes = aa._scan_integration_sessions(tmp_path, TICKET,
                                                          "developer")
        assert violations == []
        assert any("未发现" in n and "t260921-04-developer" in n for n in notes)

    def test_n2_multiturn_note(self, tmp_path):
        """N2（C4）：两回合共档（超时重试形态），违规在早回合 → 本段不判 + note。"""
        _write_session(tmp_path, "developer", [
            _user(0, "第 1 次进段"), _bash(1, RUN_SCEN),
            _user(2, "第 2 次进段"), _bash(3, "pytest test_x.py"),
        ])
        violations, notes = aa._scan_integration_sessions(tmp_path, TICKET,
                                                          "developer")
        assert violations == []
        assert any("仅判最近回合" in n and "1 回合未执法" in n for n in notes)

    def test_n3_scan_exception_loud(self, tmp_path, monkeypatch):
        """N3（C2b）：扫描异常响亮不吞（与 env fail-open 刻意不同）——note 记类名。"""
        _write_session(tmp_path, "developer", [_user(0), _bash(1, RUN_SCEN)])

        def boom(path):
            raise RuntimeError("注入故障")

        monkeypatch.setattr(aa, "_decompress_session_text", boom)
        violations, notes = aa._scan_integration_sessions(tmp_path, TICKET,
                                                          "developer")
        assert violations == []
        assert any("RuntimeError" in n for n in notes)

    def test_malformed_frames_counted(self, tmp_path):
        """畸形输入用例：arguments 非 JSON / 非串帧 → 计数 note 不拦其余帧。"""
        _write_session(tmp_path, "developer", [
            _user(0),
            _tool(1, "not-json{{"),
            _tool(2, json.dumps({"cmd_no_command_key": "x"})),
            _bash(3, RUN_SCEN),
        ])
        violations, notes = aa._scan_integration_sessions(tmp_path, TICKET,
                                                          "developer")
        assert len(violations) == 1
        assert any("畸形 1 条" in n for n in notes)

    def test_torn_and_garbage_loud_not_red(self, tmp_path):
        """畸形输入用例：torn zstd / 二进制内容 → 响亮 note，不判红不静默。"""
        good = _zstd_bytes(b'{"type":"user/message","seq":0,"data":{}}\n')
        d = tmp_path / ".dsh" / "sessions" / "ws-x" / ("%s-developer" % TICKET)
        d.mkdir(parents=True)
        torn = d / "session.jsonl.zstd"
        torn.write_bytes(good[:len(good) // 2])  # 截半=帧不完整
        violations, notes = aa._scan_integration_sessions(tmp_path, TICKET,
                                                          "developer")
        assert violations == []
        assert any("解压失败" in n or "零可解析" in n or "不可读" in n for n in notes)
        garbage = d / "session.v3.jsonl.zstd"
        garbage.write_bytes(_zstd_bytes(b"\x00\x01\x02\xff\xfe binary junk"))
        violations, notes = aa._scan_integration_sessions(tmp_path, TICKET,
                                                          "developer")
        assert violations == []
        assert any("零可解析" in n for n in notes)


# ---------- 段回执归位 / 读侧 ----------

def _mk_args(role="developer", result_file=""):
    return shared.AgentStageArgs(ticket_id=TICKET, stage_id="implement",
                                 role=role, prompt="p", workspace=None,
                                 result_file=result_file, log_file="")


class TestReceiptApply:
    def test_construct_leg_receipt_red_and_stamped(self, tmp_path):
        """用例①票面：命中 → status=failed + summary 点名 + 结果文件回写。"""
        _write_session(tmp_path, "developer", [_user(0), _bash(1, RUN_SCEN)])
        rfile = tmp_path / "stage_implement_gen0.json"
        rfile.write_text(json.dumps({"status": "ok", "summary": "做完了",
                                     "report": "r", "evidence": "e"}), "utf-8")
        res = aa._read_result(rfile)
        res = aa._apply_integration_discipline(res, tmp_path,
                                               _mk_args(result_file=str(rfile)))
        assert res.status == "failed"
        assert "【红线】developer 段禁跑集成" in res.summary
        assert RUN_SCEN in res.summary
        assert "集成禁跑红线证据" in res.report
        raw = json.loads(rfile.read_text("utf-8"))
        assert raw["status"] == "failed" and raw["integration_violations"]

    def test_idempotent_reentry_no_double_prefix(self, tmp_path):
        """幂等缓存重入：文件已带红 → 不重复前缀、不重复改写。"""
        _write_session(tmp_path, "developer", [_user(0), _bash(1, RUN_SCEN)])
        rfile = tmp_path / "stage_implement_gen0.json"
        rfile.write_text(json.dumps({"status": "ok", "summary": "做完了",
                                     "report": "r", "evidence": "e"}), "utf-8")
        res = aa._apply_integration_discipline(
            aa._read_result(rfile), tmp_path, _mk_args(result_file=str(rfile)))
        res2 = aa._apply_integration_discipline(
            aa._read_result(rfile), tmp_path, _mk_args(result_file=str(rfile)))
        assert res2.summary.count("【红线】") == 1
        assert json.loads(rfile.read_text("utf-8"))["summary"] == res2.summary

    def test_integration_role_untouched(self, tmp_path):
        """非 developer 角色（如并行 design_integration_tests）不执法。"""
        _write_session(tmp_path, "integration", [_user(0), _bash(1, RUN_SCEN)])
        res = shared.StageResult(status="ok", summary="s")
        out = aa._apply_integration_discipline(res, tmp_path,
                                               _mk_args(role="integration"))
        assert out.status == "ok" and out.summary == "s"
        assert out.integration_violations == []

    def test_note_only_no_file_rewrite(self, tmp_path):
        """零档 note：只填内存 note，不回写结果文件（最小侵入）；note 非失败信号。"""
        rfile = tmp_path / "stage_implement_gen0.json"
        rfile.write_text(json.dumps({"status": "ok", "summary": "做完了",
                                     "report": "r", "evidence": "e"}), "utf-8")
        res = aa._apply_integration_discipline(
            aa._read_result(rfile), tmp_path, _mk_args(result_file=str(rfile)))
        assert res.status == "ok" and res.integration_scan_note
        raw = json.loads(rfile.read_text("utf-8"))
        assert "integration_violations" not in raw  # 无命中不回写

    def test_read_result_roundtrip_fields(self, tmp_path):
        """读侧白名单补字段：已回写红的档重试读回不丢红（review N2 对齐）。"""
        rfile = tmp_path / "r.json"
        rfile.write_text(json.dumps({
            "status": "failed", "summary": "s", "report": "r", "evidence": "e",
            "integration_violations": [{"cmd": RUN_SCEN, "entry":
                                        "run_scenarios.py", "segment": "x",
                                        "seq": "7"}],
            "integration_scan_note": "注记",
        }), "utf-8")
        res = aa._read_result(rfile)
        assert res.integration_violations[0]["cmd"] == RUN_SCEN
        assert res.integration_violations[0]["seq"] == "7"
        assert res.integration_scan_note == "注记"
        assert res.handover_runs == [] and res.env_fail is False  # 旧字段不受扰

    def test_default_fields_replay_safe(self):
        """老回执重放安全：新字段缺省 []/""（gate_refusal/env_fail 先例）。"""
        res = shared.StageResult()
        assert res.integration_violations == []
        assert res.integration_scan_note == ""


# ---------- t261009-36: a READ must not red-line a stage (live t261008-47) ----------

class TestT26100936ReadNotRun:
    """Live false positive (t261008-47): a read-only inspector given a baselines
    path as an argument was judged as running the suite.

    Root cause is not _match_entry_token alone (read-only verbs were already
    passed by the EXEC_VERBS gate): the `bash -lc "<string>"` combined short
    flag fell into the generic flag skip and the whole embedded string was
    matched as a bare token. These fixtures pin both directions: reads stay
    green, runs stay red (the red line only tightens)."""

    BASE_MJS = "integration/baselines/lane-stages-chain.mjs"

    def test_readonly_inspectors_with_baselines_arg_no_hit(self):
        """Reads stay green: sed/grep/cat/head/tail/wc/diff on baselines paths."""
        for cmd in [
            "sed -n 70p %s" % self.BASE_MJS,
            "sed -n '70p' %s" % self.BASE_MJS,
            "grep -n verify_lane %s" % self.BASE_MJS,
            "cat %s" % self.BASE_MJS,
            "head -20 integration/baselines/x.py",
            "tail -5 %s" % self.BASE_MJS,
            "wc -l integration/baselines/x.mjs",
            "diff integration/baselines/a.py integration/baselines/b.py",
        ]:
            assert idisc.scan_bash_command(cmd) == [], "false hit on read: %s" % cmd

    def test_wrapped_reader_no_hit(self):
        """Reads stay green under transparent wrappers: after wrapper skipping
        the resolved program is the inspector, so its args are read data."""
        for cmd in [
            "timeout 5 sed -n 70p %s" % self.BASE_MJS,
            "env -i sed -n 70p %s" % self.BASE_MJS,
            "sudo cat integration/baselines/x.py",
            "nohup grep -n verify_lane %s &" % self.BASE_MJS,
        ]:
            assert idisc.scan_bash_command(cmd) == [], "false hit on wrapped read: %s" % cmd

    def test_nested_shell_combined_flag_reader_no_hit(self):
        """The live incident shape: bash -lc "<read>" - the combined-flag -c
        recursion judges the string by the same rules, so it is green."""
        assert idisc.scan_bash_command(
            'bash -lc "sed -n 70p %s"' % self.BASE_MJS) == []
        assert idisc.scan_bash_command(
            'sh -ic "grep verify_lane integration/baselines/x.py"') == []

    def test_reader_pipeline_no_hit(self):
        """Reads stay green: a pipeline whose downstream is also a reader."""
        assert idisc.scan_bash_command(
            "sed -n 1p %s | grep verify_lane | wc -l" % self.BASE_MJS) == []
        # git is not an exec verb (passed by the EXEC_VERBS gate; not a
        # READONLY_INSPECTORS member - the gate decides, the set is a tripwire)
        assert idisc.scan_bash_command(
            "git grep verify_lane integration/baselines") == []

    def test_heredoc_body_readonly_group_no_hit(self):
        """Review comment 1: a heredoc body mentioning baselines in a
        non-executing group is not judged (group-level shelling-out detection
        is untouched by the whitespace defense belt)."""
        assert idisc.scan_bash_command(
            "cat <<EOF\nintegration/baselines/x.py mentioned\nEOF") == []

    def test_nested_shell_combined_flag_executor_hit(self):
        """Runs stay red: an execution inside the same -lc form - before the
        fix this was a silent miss (the fall-through cuts both ways)."""
        hits = idisc.scan_bash_command(
            'bash -lc "python3 integration/run_scenarios.py"')
        assert hits and hits[0]["entry"] == "run_scenarios.py"
        hits = idisc.scan_bash_command(
            'bash -lc "python3 -m integration.run_scenarios"')
        assert hits and hits[0]["entry"] == "run_scenarios.py"
        hits = idisc.scan_bash_command(
            'bash -lc "node %s"' % self.BASE_MJS)
        assert hits and hits[0]["entry"] == "baselines"

    def test_executor_forms_still_hit(self):
        """Runs stay red: the execution forms named by spec item 4 - the
        narrowing must not loosen any of them."""
        for cmd, entry in [
            ("python3 integration/baselines/x.py", "baselines"),
            ("node integration/baselines/x.mjs", "baselines"),
            ("bash integration/with_stage.sh", "with_stage.sh"),
            ("python3 integration/run_scenarios.py", "run_scenarios.py"),
            ("python3 -m integration.run_scenarios", "run_scenarios.py"),
            ('bash -c "python3 integration/baselines/x.py"', "baselines"),
            ("python3 integration/light-lane/sc_t04_prune_archive_legacy.py",
             "sc_*"),
            ("python3 server/tools/admin.py verify_lane", "verify_lane"),
        ]:
            hits = idisc.scan_bash_command(cmd)
            assert hits, "should be red: %s" % cmd
            assert hits[0]["entry"] == entry, (cmd, hits)

    def test_pipeline_downstream_executor_hit(self):
        """Runs stay red: a read pipeline whose downstream is an executor
        (spec item 4: the narrowing must not open a new leak)."""
        hits = idisc.scan_bash_command(
            "sed -n 1p list.txt | xargs python3 integration/baselines/x.py")
        assert hits and hits[0]["entry"] == "baselines"
        hits = idisc.scan_bash_command(
            "cat list | xargs -0 -n1 node integration/baselines/x.mjs")
        assert hits and hits[0]["entry"] == "baselines"
        hits = idisc.scan_bash_command(
            "cat list | xargs -I{} python3 integration/baselines/x.py")
        assert hits and hits[0]["entry"] == "baselines"

    def test_heredoc_fed_to_bash_hit(self):
        """Runs stay red: a heredoc group whose program word is a shell
        interpreter keeps judging its body line by line."""
        hits = idisc.scan_bash_command(
            'bash <<EOF\npython3 integration/baselines/x.py\nEOF')
        assert hits and hits[0]["entry"] == "baselines"

    def test_whitespace_token_never_entry(self):
        """Review comment 1: a token containing whitespace is never an entry
        (normal shlex never yields one; the malformed .split() fallback is the
        path this pure defense belt guards). Pinned so it does not drift."""
        assert idisc._match_entry_token("") is None
        assert idisc._match_entry_token("python3 integration/baselines/x.py") \
            is None
        assert idisc._match_entry_token(
            "integration/baselines/x.py") == "baselines"   # normal path intact

    def test_xargs_bare_still_no_hit(self):
        """Bare xargs (default echo) keeps the old no-hit verdict."""
        assert idisc.scan_bash_command(
            "ls integration | xargs -I{} python3 {}") == []

    def test_malformed_inputs_no_crash(self):
        """Malformed inputs (house rule): unbalanced quote in -lc, empty -lc
        string, xargs with no executor - no raise."""
        assert isinstance(idisc.scan_bash_command('bash -lc "sed -n 70p'),
                          list)  # fallback tokenization must not raise
        assert idisc.scan_bash_command('bash -lc ""') == []
        assert idisc.scan_bash_command("cat list | xargs") == []
        assert idisc.scan_bash_command("xargs -0") == []


# ---------- 口径同步（反用例④：文案=执法，两侧同批） ----------

class TestPromptSync:
    def test_clause_renders_from_entries(self):
        """文案从 FORBIDDEN_ENTRIES 渲染（同源，防手写漂移）。"""
        clause = idisc.prompt_clause()
        for _key, name in idisc.FORBIDDEN_ENTRIES:
            assert name in clause, name
        assert "单测可跑" in clause and "集成禁跑" in clause
        assert "run_integration_tests" in clause      # 归属段点名
        assert "lint_tests" in clause                 # 允许面点名

    def test_developer_briefs_carry_clause(self):
        """developer 两段（create_plan/implement）文案必须含执法口径全文。"""
        clause = idisc.prompt_clause()
        for stage in ("create_plan", "implement"):
            brief = dev_lane.FLOW_BRIEF[stage]
            assert clause in brief, stage
            for _key, name in idisc.FORBIDDEN_ENTRIES:
                assert name in brief, (stage, name)
            assert "集成禁跑" in brief and "单测可跑" in brief
            assert "run_integration_tests" in brief

    def test_non_developer_briefs_do_not_carry_clause(self):
        """非 developer 段不注入（执法按 role 收窄，两侧集合严格一致）。"""
        clause = idisc.prompt_clause()
        for stage, brief in dev_lane.FLOW_BRIEF.items():
            if stage in ("create_plan", "implement"):
                continue
            assert clause not in brief, stage
