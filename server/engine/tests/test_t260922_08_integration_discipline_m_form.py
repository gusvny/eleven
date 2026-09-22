"""t260922-08 集成禁跑执法 -m 形误伤收窄 UT（create_plan gen0 方案 R4 矩阵）。

背景：`python3 -m py_compile integration/run_scenarios.py`（静态语法自检）被
-m 分支误判红，已签字票 t260922-02 消解冲突时因此停摆。修法：-m 分支引入静态
工具模块白名单 STATIC_TOOL_MODULES——`-m <静态成员>` 之后本段剩余实参不再参与
入口表匹配；`-m <入口表命中>`（run_scenarios/sc_*）与 `-m pytest <文件>` 维持
判红（pytest 收集=import 执行，真跑）。

用例组映射（票面验收①②③④ + review C1/C2 条件）：
  ①③ 改后转绿面（含现场原命令整串必绿）       → TestMatcherMFormGreen
  ④   不放宽红锚（真跑形保持现状/豁免不追溯）  → TestMatcherMFormStaysRed
  ④   表完整性守卫 + 入口表冻结                → TestGuards
  C1/C2 声明边界（连写执行器既有漏判落字锚）    → TestDeclaredBoundary
  畸形输入（岗位纪律：消费外部命令串必带）      → TestMalformed
  ②   声明=执法同批（docstring/文案源级断言）  → TestDeclarationSync

UT 全程禁网络/真 Temporal/真 git；判据命令一律**字符串字面量**喂纯函数
scan_bash_command——不执行任何集成入口（被测纪律本身就是本段的纪律）。
"""
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import integration_discipline as idisc  # noqa: E402

RUN_SCEN = "python3 integration/run_scenarios.py"
# t260922-02 现场被判红的原命令整串（票面原文；两行=两段，段内含 ; || &&）。
FIELD_CMD = ('echo "=== 标记残留 ==="; '
             'grep -cn "^<<<<<<<\\|^=======\\|^>>>>>>>" integration/run_scenarios.py '
             '|| echo "零残留 ✓"\n'
             'echo "=== 语法 ==="; '
             'python3 -m py_compile integration/run_scenarios.py '
             '&& echo "py_compile ✓"')


class TestMatcherMFormGreen:
    """票面验收①③：-m 静态工具形放行（改前误红，改后必须绿）。"""

    def test_field_incident_command_green(self):
        """现场原命令整串（t260922-02 被判红原文）——grep 行与 py_compile 行全放行。"""
        assert idisc.scan_bash_command(FIELD_CMD) == []

    def test_ticket_table_green(self):
        """票面表格『应判放行』行 + 验收①点名的静态工具族 + 变体形。"""
        for cmd in [
            "python3 -m py_compile integration/run_scenarios.py",  # 现场误红形，必绿
            "python3 -m compileall integration/run_scenarios.py",
            "python3 -m compileall -q integration/",               # 目录形实参
            "python3 -m ast integration/run_scenarios.py",
            "python3 -m tokenize integration/run_scenarios.py",
            "python3 -m dis integration/run_scenarios.py",
            "python3 -m py_compile integration/t260903-01/sc_x.py",  # sc_ 文件被编译≠被执行
            "PYTHONPYCACHEPREFIX=out/pycache python3 -m py_compile "
            "integration/run_scenarios.py",                        # VAR= 前缀形
            "python3 -mpy_compile integration/run_scenarios.py",   # 连写形静态豁免
        ]:
            assert idisc.scan_bash_command(cmd) == [], "误伤：%s" % cmd


class TestMatcherMFormStaysRed:
    """票面验收④：真跑判据零放宽——改前红形改后一律仍红。"""

    def test_ticket_table_stays_red(self):
        for cmd, entry in [
            (RUN_SCEN, "run_scenarios.py"),                # 裸直形（--help 行同 intent）
            ("bash -c 'python3 integration/run_scenarios.py'",
             "run_scenarios.py"),                          # -c 递归形
            ("python3 -m run_scenarios", "run_scenarios.py"),
            ("python3 -m integration.run_scenarios", "run_scenarios.py"),
            ("python3 -m sc_x", "sc_*"),
            ("python3 -m pytest integration/t260902-07/tests/sc_x.py",
             "sc_*"),                                      # pytest 收集=import 执行
            ("sh integration/with_stage.sh t260901-13", "with_stage.sh"),
            ("node integration/baselines/ticket-validate.mjs", "baselines"),
        ]:
            hits = idisc.scan_bash_command(cmd)
            assert hits, "真跑形被放宽：%s" % cmd
            assert hits[0]["entry"] == entry, (cmd, hits)

    def test_exemption_not_retroactive(self):
        """豁免不追溯：先命中后 -m 静态，同段先前命中保留（静态不洗白真跑）。"""
        hits = idisc.scan_bash_command(RUN_SCEN + " -m py_compile")
        assert hits and hits[0]["entry"] == "run_scenarios.py"

    def test_static_exemption_segment_local(self):
        """break 只在段内生效：静态豁免跨 && 不泄漏，后续真跑段照判。"""
        hits = idisc.scan_bash_command(
            "python3 -m py_compile integration/run_scenarios.py && " + RUN_SCEN)
        assert len(hits) == 1 and hits[0]["entry"] == "run_scenarios.py"


class TestGuards:
    """表完整性守卫：白名单不含执行器；入口表冻结（票面边界：不动口径）。"""

    def test_static_set_has_no_executor(self):
        """防未来把执行器塞进豁免表（塞入即放宽真跑判据）。"""
        for name in ("pytest", "unittest", "timeit", "cProfile", "profile",
                     "pdb", "runpy"):
            assert name not in idisc.STATIC_TOOL_MODULES, name

    def test_entry_table_frozen(self):
        """FORBIDDEN_ENTRIES 逐项冻结——本票只收窄 -m 误伤面，不动入口表口径。"""
        assert idisc.FORBIDDEN_ENTRIES == (
            ("run_scenarios.py", "integration/run_scenarios.py"),
            ("sc_*", "integration/**/sc_*.py|.mjs"),
            ("baselines", "integration/baselines/*"),
            ("with_stage.sh", "integration/with_stage.sh"),
            ("verify_lane", "verify_lane（含 admin.py call verify_lane）"),
        )


class TestDeclaredBoundary:
    """review C1/C2：连写形执行器模块既有漏判——声明边界落字锚（口径诚实，
    循 test_t260921_04.test_boundary_declared_no_hit 先例）。
    注意：这是**既有漏判**（泛化 flag 跳过分支，非本票引入、本票不收口），
    不是本票放宽——故单列声明边界组，不入 stays_red 红组（review C2 落点纪律）。"""

    def test_joined_form_executor_miss_declared(self):
        assert idisc.scan_bash_command("python3 -mrun_scenarios") == []
        assert idisc.scan_bash_command("python3 -msc_x") == []


class TestMalformed:
    """畸形输入（岗位纪律）：不抛、按兜底语义照常判。"""

    def test_dangling_and_argless(self):
        assert idisc.scan_bash_command("python3 -m") == []             # 悬空 -m
        assert idisc.scan_bash_command("python3 -m py_compile") == []  # 静态模块零实参
        assert idisc.scan_bash_command("python3 -m py_compile -q") == []

    def test_unclosed_quote_with_static_tool(self):
        """引号不平衡 → shlex 兜底切词，静态豁免语义照常（不炸不误判）。"""
        assert idisc.scan_bash_command(
            'python3 -m py_compile "unclosed integration/run_scenarios.py') == []

    def test_degenerate_inputs(self):
        for bad in (None, 123, "", "   "):
            assert idisc.scan_bash_command(bad) == []


class TestDeclarationSync:
    """票面验收②：声明=执法同批——docstring 边界清单与文案侧同批落字
    （源级断言，test_t260917_08 先例）。"""

    def test_docstring_declares_m_form_semantics(self):
        doc = inspect.getdoc(idisc)
        assert doc and "-m" in doc and "STATIC_TOOL_MODULES" in doc
        for member in sorted(idisc.STATIC_TOOL_MODULES):
            assert member in doc, member              # 白名单成员逐个落字
        assert "连写" in doc and "-mpy_compile" in doc  # 连写形豁免方向（C1）
        assert "既有已知漏判" in doc                   # 连写执行器漏判方向（C1 双向完整）

    def test_prompt_clause_covers_static_selfcheck(self):
        clause = idisc.prompt_clause()
        assert "py_compile" in clause and "静态" in clause
        for _key, name in idisc.FORBIDDEN_ENTRIES:    # 文案增量不稀释禁跑面
            assert name in clause, name
        assert "集成禁跑" in clause and "单测可跑" in clause
