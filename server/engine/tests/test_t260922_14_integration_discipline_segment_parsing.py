"""t260922-14 集成禁跑执法切段解析 UT：引号/转义感知 + heredoc 正文=数据。

背景：旧 `_SEGMENT_SPLIT_RE` 正则切段不认引号/heredoc——`grep -E "…|verify_lane…"`
引号内 `|` 被当管道切段，`|` 之间的裸片段（恰为 `verify_lane`）撞入口表误红
（t260922-12 现场停摆；t260922-14 会话档 4 条只读探针同样被误红=第三类误红载体）。
修法：`_split_segments()` 引号/转义感知状态机切段 + heredoc body 按同逻辑行组级
动词保守分流（方案 v3，review R1/R3-R6 与 C1-C3 全部收口）。

用例组映射（方案 §验收口径）：
  TestQuoteAwareSegments      批次1：票面验收①②③（T1 回归形/T2 守护形/T4-T8 反例/
                              守护只读管道/T9 畸形/T10 现场原文形）
  TestHeredocBodyDisposition  批次2：追加⑦（H1-H12 + R1 红线 HA-HD + HE 过判声明 +
                              C1 X3 + C3 X1/X2 + 子壳括号剥理）
  TestDeclaredMissFamily      R5/C2：既有漏判族锁形（不收口，防静默翻红）
  TestDeclarationSync         票面④声明=执法同批（-08 TestDeclarationSync 先例）

标注约定（R3/R4）：「守护形」=现状已绿、改后必须保持绿（非回归形）；「回归形」=
改前红改后绿；「改前确实红」为实现段流程步骤（取证复跑 .sandbar/probe_repro_gen0.py
与 .sandbar/cert_fixtures_t260922_14.py），不写成常驻 UT 断言。
UT 全程禁网络/真 Temporal/真 git；判据命令一律**字符串字面量**喂纯函数
scan_bash_command——不执行任何集成入口（被测纪律本身就是本段的纪律）。
"""
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import integration_discipline as idisc  # noqa: E402

RUN_SCEN = "python3 integration/run_scenarios.py"

# t260922-12 现场被判红的原命令整串（票面原文；echo/grep/ls/sed 全只读动词，
# 引号内 grep -E 正则交替含 verify_lane，`|` 之间裸片段撞入口表=第二类误红现场）。
FIELD_CMD_12 = (
    'echo "== REPO 用途 ==" && grep -n "REPO" integration/scenario_ledger.py && \\\n'
    'echo "== t260922-12 夹具 monkeypatch/_run_baseline ==" && '
    'grep -rn "monkeypatch\\|_run_baseline" integration/t260922-12/*.py | head && \\\n'
    'echo "== 受影响面其它电池 ==" && '
    'ls integration/tests/ | grep -E "t260910_13|verify_lane|failure_protocol|ledger" && \\\n'
    'echo "== 电池 import verify_lane 方式 ==" && '
    "sed -n '1,60p' integration/tests/test_t260922_12_gate_ledger.py"
)

# t260922-14 会话档 gen0 判红原文形（第三类误红载体：python3 - <<'PYEOF' 探针正文
# 被逐行判；正文含与 t260922-12 同构的红形字面量行）。改前确实红的取证：复跑
# .sandbar/probe_repro_gen0.py / .sandbar/cert_fixtures_t260922_14.py（R4：不进断言）。
FIELD_PROBE_14 = (
    "python3 - <<'PYEOF'\n"
    "import sys\n"
    "sys.path.insert(0, 'server/engine')\n"
    "import integration_discipline as idis\n"
    'CMD = \'ls integration/tests/ | grep -E "t260910_13|verify_lane'
    '|failure_protocol|ledger"\'\n'
    "print(idis.scan_bash_command(CMD))\n"
    "PYEOF\n"
)


class TestQuoteAwareSegments:
    """批次1：切段引号/转义感知（票面验收①②③）。"""

    def test_t260922_12_field_command_green(self):
        """T1 回归形：t260922-12 现场原命令整串（改前判红 entry=verify_lane）→ 放行。"""
        assert idisc.scan_bash_command(FIELD_CMD_12) == []

    def test_t260922_14_field_probe_fixture_green(self):
        """T10 现场原文形（R4 落法：只锁改后绿）。改前确实红为实现段流程步骤，
        取证路径见模块 docstring 与 .sandbar/probe_repro_gen0.py，不进本断言。"""
        assert idisc.scan_bash_command(FIELD_PROBE_14) == []

    def test_quoted_alternation_guarded_green(self):
        """T2 守护形（R3：现状已绿，改后必须保持绿——非「改前红」回归形）：
        引号内/转义的 `|` 是 grep 正则交替，不是管道，不切段。"""
        for cmd in [
            'grep -E "verify_lane|x" file',
            'grep "a\\|b" f',
            'grep a\\|b f',
            "grep 'a|b' f",
            'grep "|" f',
            'echo "a|b" f',
            "echo 'a && b'",
            "sed -n 'a|b' f",
        ]:
            assert idisc.scan_bash_command(cmd) == [], "误伤：%s" % cmd

    def test_readonly_pipeline_guarded_green(self):
        """守护形：现场只读管道两形（ls|grep -E 交替、grep|head）保持放行。"""
        for cmd in [
            'ls integration/tests/ | grep -E '
            '"t260910_13|verify_lane|failure_protocol|ledger"',
            'grep -rn "monkeypatch\\|_run_baseline" '
            'integration/t260922-12/*.py | head',
        ]:
            assert idisc.scan_bash_command(cmd) == [], "误伤只读：%s" % cmd

    def test_pipe_run_still_red(self):
        """T4 票面反例：管道真跑仍判红（切段不得把真跑藏进管道下游）。"""
        hits = idisc.scan_bash_command("ls | " + RUN_SCEN)
        assert hits and hits[0]["entry"] == "run_scenarios.py"

    def test_shell_c_quoted_run_still_red(self):
        """T5 票面反例：-c 引号内真跑仍判红；引号内真管道（加长版）一并递归判
        （假绿向修复的锁定用例）。"""
        hits = idisc.scan_bash_command("cat x | bash -c '" + RUN_SCEN + "'")
        assert hits and hits[0]["entry"] == "run_scenarios.py"
        hits = idisc.scan_bash_command("cat x | bash -c '" + RUN_SCEN + " | head'")
        assert hits and hits[0]["entry"] == "run_scenarios.py"

    def test_constructed_reds_keep(self):
        """T6 票面反例表：连写/管道/-m/-m pytest/直接执行形全保持判红。"""
        for cmd, entry in [
            ("echo hi && sc_foo.py", "sc_*"),
            ("python3 -m run_scenarios", "run_scenarios.py"),
            ("python3 -m pytest integration/tests/sc_x.py", "sc_*"),
            ("./integration/with_stage.sh", "with_stage.sh"),
            ("bash integration/with_stage.sh", "with_stage.sh"),
            ("source integration/with_stage.sh", "with_stage.sh"),
            ("python3 integration/baselines/foo.py", "baselines"),
            ("node integration/baselines/x.mjs", "baselines"),
        ]:
            hits = idisc.scan_bash_command(cmd)
            assert hits, "真跑形被放宽：%s" % cmd
            assert hits[0]["entry"] == entry, (cmd, hits)

    def test_newline_and_continuation_segments(self):
        """T7/T8：换行分段不并段（防换行藏真跑）；续行拼接后动词保持锚定仍判。"""
        hits = idisc.scan_bash_command("echo hi\n" + RUN_SCEN)
        assert hits and hits[0]["entry"] == "run_scenarios.py"
        hits = idisc.scan_bash_command("echo a && \\\n" + RUN_SCEN)
        assert hits and hits[0]["entry"] == "run_scenarios.py"

    def test_malformed_inputs_no_crash(self):
        """T9 畸形输入（岗位纪律：消费外部命令串必带）：未闭合引号/裸分隔/悬空
        heredoc——不抛；可判则判（真跑兜底照红），既有摘要/递归封顶口径不变。"""
        hits = idisc.scan_bash_command(RUN_SCEN + ' "unclosed')
        assert hits and hits[0]["entry"] == "run_scenarios.py"   # 兜底照判
        hits = idisc.scan_bash_command(RUN_SCEN + " " + "x" * 9000)
        assert hits and len(hits[0]["cmd"]) <= 200               # cmd 摘要截断
        deep = RUN_SCEN
        for _ in range(6):                                       # -c 递归封顶
            deep = "bash -c '%s'" % deep
        assert isinstance(idisc.scan_bash_command(deep), list)
        for bad in [
            "", " ", '"', "'", "\"'", "\\", "\\\\", "||", "&&&", "|&;;",
            'echo "a', "echo 'a", "echo \\", 'python3 "x | y', "###", "a#b",
            'echo "#"', "echo '#'", "echo `a|b`", "\n\n\n", "&&& ||| ;;;",
            "python3 - <<", "python3 - <<\n" + RUN_SCEN,
            "bash <<\n" + RUN_SCEN + "\n\n",
            "cat <<'EOF'", "cat <<EOF", "<<<", "cat <<EOF |",
            "python3 - <<'未闭合'\nx\n", "cat <<A <<B\nx\n",
            "eval <<'EOF'\n" + RUN_SCEN, "xargs <<\n" + RUN_SCEN,
        ]:
            assert isinstance(idisc.scan_bash_command(bad), list), repr(bad)

    def test_crlf_no_crash(self):
        """R6：CRLF 不特判（只承诺不抛）。"""
        assert isinstance(idisc.scan_bash_command("echo hi\r\n" + RUN_SCEN), list)


class TestHeredocBodyDisposition:
    """批次2：heredoc 正文=数据（宿主令 260922 追加⑦）+ 组级保守分流（review R1）。

    红线：HA-HD 四形（管道下游消费方/eval/xargs 直挂）必须仍红；
    对照：H4 cat 直挂数据 / H1 python3 直挂 / H9 python3|head 必须绿（⑦正主）。
    真值注记（t260922-14 实测）：eval 直挂无实参不消费 stdin、source/. 直挂需文件
    实参、裸 xargs 默认 echo 仅回显——三者照判属保守纳入（现状亦判，只紧不松）。
    """

    def test_h1_python3_heredoc_body_is_data(self):
        """H1 ⑦正主：python3 直挂探针 body=python 代码（含红形字符串字面量）→ 数据。"""
        body = ("python3 - <<'PYEOF'\n"
                "import sys\n"
                "CMD = 'ls | python3 integration/run_scenarios.py'\n"
                "print(CMD)\n"
                "PYEOF\n")
        assert idisc.scan_bash_command(body) == []

    def test_h2_h3_shell_direct_still_red(self):
        hits = idisc.scan_bash_command("bash <<'EOF'\n" + RUN_SCEN + "\nEOF\n")
        assert hits and hits[0]["entry"] == "run_scenarios.py"
        hits = idisc.scan_bash_command("sh <<EOF\necho hi && sc_foo.py\nEOF\n")
        assert hits and hits[0]["entry"] == "sc_*"

    def test_h4_cat_direct_body_is_data(self):
        """R1 对照红线：cat 直挂（组内无解释/执行动词）body=数据，必须绿。"""
        body = "cat <<EOF\nls | " + RUN_SCEN + "\nEOF\n"
        assert idisc.scan_bash_command(body) == []

    def test_h5_here_string_not_consuming_lines(self):
        """`<<<` here-string 非行消费，不得吞掉后续真跑行。"""
        hits = idisc.scan_bash_command('cat <<< "a|verify_lane|b"\n' + RUN_SCEN + "\n")
        assert hits and hits[0]["entry"] == "run_scenarios.py"

    def test_h6_bash_s_still_red(self):
        hits = idisc.scan_bash_command("bash -s <<'EOF'\n" + RUN_SCEN + "\nEOF\n")
        assert hits and hits[0]["entry"] == "run_scenarios.py"

    def test_h7_h8_unclosed_delimiter_two_ways(self):
        # 未闭合 + python 目标：余文按数据，不抛不红
        assert idisc.scan_bash_command("python3 - <<'EOF'\n" + RUN_SCEN + "\n") == []
        # 未闭合 + bash 目标：真跑仍判（保守兜底）
        hits = idisc.scan_bash_command("bash <<EOF\n" + RUN_SCEN + "\n")
        assert hits and hits[0]["entry"] == "run_scenarios.py"

    def test_h9_python3_heredoc_piped_to_head(self):
        """组内无解释/执行动词（python3/head）→ body=数据。"""
        body = "python3 - <<'EOF' | head\n" + RUN_SCEN + "\nEOF\n"
        assert idisc.scan_bash_command(body) == []

    def test_h10_two_heredocs_one_line(self):
        assert idisc.scan_bash_command("cat <<A <<B\nx\nA\ny\nB\n") == []

    def test_h11_dashed_tab_body_still_red(self):
        body = "bash <<-EOF\n\t" + RUN_SCEN + "\n\tEOF\n"
        hits = idisc.scan_bash_command(body)
        assert hits and hits[0]["entry"] == "run_scenarios.py"

    def test_h12_source_direct_conservative_red(self):
        hits = idisc.scan_bash_command("source <<'EOF'\n" + RUN_SCEN + "\nEOF\n")
        assert hits and hits[0]["entry"] == "run_scenarios.py"

    # ---- R1 红线四形（假绿洞回归锁）：必须仍红 ----

    def test_ha_pipe_downstream_bash(self):
        hits = idisc.scan_bash_command("cat <<'EOF' | bash\n" + RUN_SCEN + "\nEOF\n")
        assert hits and hits[0]["entry"] == "run_scenarios.py"

    def test_hb_pipe_downstream_sh(self):
        hits = idisc.scan_bash_command("cat <<'EOF' | sh\n" + RUN_SCEN + "\nEOF\n")
        assert hits and hits[0]["entry"] == "run_scenarios.py"

    def test_hc_eval_direct_conservative_red(self):
        hits = idisc.scan_bash_command("eval <<'EOF'\n" + RUN_SCEN + "\nEOF\n")
        assert hits and hits[0]["entry"] == "run_scenarios.py"

    def test_hd_xargs_direct_conservative_red(self):
        hits = idisc.scan_bash_command("xargs <<'EOF'\n" + RUN_SCEN + "\nEOF\n")
        assert hits and hits[0]["entry"] == "run_scenarios.py"

    def test_he_group_overjudge_declared(self):
        """HE 组级过判声明形：python3 直挂 | bash——body 实为 python 代码却照判
        （现状亦判，非放宽；UT 锁形防漂移）。"""
        body = "python3 - <<'EOF' | bash\n" + RUN_SCEN + "\nEOF\n"
        hits = idisc.scan_bash_command(body)
        assert hits and hits[0]["entry"] == "run_scenarios.py"

    # ---- review C3：两条便宜的真跑路径锁形 ----

    def test_x1_xargs_with_utility_real_run(self):
        """X1：xargs python3 <<EOF——body 行作实参被真执行（真跑路径，prog=xargs
        在触发表内）。"""
        body = "xargs python3 <<'EOF'\nintegration/run_scenarios.py\nEOF\n"
        hits = idisc.scan_bash_command(body)
        assert hits and hits[0]["entry"] == "run_scenarios.py"

    def test_x2_sudo_bash_wrapper_still_red(self):
        """X2：sudo bash <<EOF——包装器跳过后 prog=bash ∈ 触发表，body 照判。"""
        body = "sudo bash <<'EOF'\n" + RUN_SCEN + "\nEOF\n"
        hits = idisc.scan_bash_command(body)
        assert hits and hits[0]["entry"] == "run_scenarios.py"

    def test_x3_pipe_downstream_python3_is_data(self):
        """X3（review C1）：下游为非 shell 解释器（python3）时 body 按 python 执行，
        bash 执法器不判（与 `-c` 内联不解析同族）——锁绿防未来静默翻红。"""
        body = ("cat <<'EOF' | python3\n"
                + RUN_SCEN + "  # body=python 代码形（此注释仅为可读性）\n"
                "EOF\n")
        assert idisc.scan_bash_command(body) == []

    def test_subshell_anchored_shell_heredoc_still_red(self):
        """子壳括号单词形：prog 剥括号后 `(bash`→bash 仍命中触发表（判据不松；
        对应 C2 X4 的 shell 版——`(python3` 形走 TestDeclaredMissFamily.dm4）。"""
        body = "(bash <<'EOF'\n" + RUN_SCEN + "\nEOF\n)\n"
        hits = idisc.scan_bash_command(body)
        assert hits and hits[0]["entry"] == "run_scenarios.py"


class TestDeclaredMissFamily:
    """DM（review R5/C2）：既有漏判族锁形——非本票引入、本票不收口，docstring 已
    落字声明；UT 锁形防未来静默翻红（循 -08 TestDeclaredBoundary 先例：
    不判≠放宽，是声明边界）。"""

    def test_dm1_backtick_hidden_run(self):
        assert idisc.scan_bash_command("echo `" + RUN_SCEN + "`") == []

    def test_dm2_command_substitution_hidden_run(self):
        assert idisc.scan_bash_command("echo $(" + RUN_SCEN + ")") == []

    def test_dm3_process_substitution_sticks_basename(self):
        assert idisc.scan_bash_command("bash <(" + RUN_SCEN + ")") == []

    def test_dm4_subshell_anchored_python_heredoc(self):
        """C2 X4：子壳括号粘 prog（`(python3`）→ 组内无触发动词 → body 数据化。
        body 确按 python 执行（与 H1 同族），结果语义正确；多词子壳形（如
        `(cd x && bash) <<EOF`）为既有解析前沿局限，docstring 已落字。"""
        body = ("(python3 - <<'EOF'\n"
                "ls | python3 integration/run_scenarios.py\n"
                "EOF\n"
                ")\n")
        assert idisc.scan_bash_command(body) == []


class TestDeclarationSync:
    """声明=执法同批（票面④）：docstring 源级断言（-08 TestDeclarationSync 先例）。"""

    def test_docstring_declares_quote_aware_segmentation(self):
        doc = inspect.getdoc(idisc)
        assert doc and "引号/转义感知" in doc
        assert "_split_segments" in doc
        assert "t260922-12" in doc and "t260922-14" in doc      # 两例反例存档

    def test_docstring_declares_heredoc_disposition(self):
        doc = inspect.getdoc(idisc)
        assert "heredoc 正文=数据" in doc
        for verb in ("bash", "sh", "zsh", "dash", "source", "eval", "xargs"):
            assert verb in doc, verb                             # 触发表落字
        assert "管道下游" in doc                                  # R1 语义
        assert "非 shell 解释器" in doc                           # C1 半句
        assert "保守纳入" in doc                                  # 真值注记不夸大
        assert "逐字一致" in doc                                  # R6 delimiter 语义

    def test_docstring_declares_miss_family(self):
        doc = inspect.getdoc(idisc)
        for token in ("反引号", "$(", "<(", "子壳括号", "既有已知漏判"):
            assert token in doc, token                           # R5/C2 漏判族补全

    def test_08_declaration_strings_preserved(self):
        """只增不删：-08 TestDeclarationSync 的源级断言字样必须原样保留。"""
        doc = inspect.getdoc(idisc)
        for token in ("-m", "STATIC_TOOL_MODULES", "py_compile", "compileall",
                      "ast", "tokenize", "dis", "连写", "-mpy_compile",
                      "既有已知漏判"):
            assert token in doc, token

    def test_segment_excerpt_still_raw_slice(self):
        """hit 的 segment 摘要保持原文切片语义（引号保留），cmd 摘要不变。"""
        hits = idisc.scan_bash_command("ls | " + RUN_SCEN)
        assert hits[0]["segment"] == RUN_SCEN
        cmd = "echo hi && " + RUN_SCEN
        hits = idisc.scan_bash_command(cmd)
        assert hits[0]["segment"] == RUN_SCEN and hits[0]["cmd"] == cmd[:200]
