"""t261004-05：`node --check <integration 场景文件>` 是静态语法自检，不算执行。

票面事实：t261003-10 / t261004-03 两个 implement 段被 `node --check sc_*.mjs`
误红阻断（Python 侧 py_compile 同形豁免、JS 侧不对称）。本票收口：
- node/nodejs 的 `--check` flag 豁免本段剩余实参（与 -m 静态白名单同向）；
- `node <入口>` 真跑照判红，执行锚点零放松；
- 声明=执法：prompt_clause() 同批点名两种语言的合法静态自检形。
回归夹具=两张被阻断票面记录的原命令（逐字）。
"""
import inspect

import integration_discipline as idisc

SC = "integration/t261003-06/sc_executor_panel_page_redesign.mjs"


class TestNodeCheckExemption:
    def test_blocked_ticket_t261003_10_command_is_exempt(self):
        """被阻断票原命令（grep + node --check 复合段）→ 静态自检不判红。"""
        cmd = f'grep -n "ovNeg\\|ovneg" {SC}; node --check {SC}'
        assert idisc.scan_bash_command(cmd) == []

    def test_bare_node_check_is_exempt(self):
        assert idisc.scan_bash_command(f"node --check {SC}") == []

    def test_node_check_non_scenario_file_is_exempt(self):
        """非入口文件同样走 --check 豁免分支（豁免不依赖 basename）。"""
        assert idisc.scan_bash_command(
            "node --check integration/run_scenarios.py") == []

    def test_node_check_flags_before_and_after(self):
        """--check 与其他 flag 混排、flag 在文件之后——其余实参不再判。"""
        assert idisc.scan_bash_command(
            f"node --check --v8-pool-size=2 {SC}") == []

    def test_node_check_only_binds_node(self):
        """bun/deno 的 --check 语义未核实，不豁免（保守收口）。"""
        assert idisc.scan_bash_command(f"bun --check {SC}") != []

    def test_degenerate_inputs_still_safe(self):
        assert idisc.scan_bash_command(None) == []
        assert idisc.scan_bash_command("") == []
        assert idisc.scan_bash_command("node --check") == []  # 零文件实参


class TestRealRunStillRed:
    """执行锚点零放松：真跑形全部维持判红。"""

    def test_node_run_scenario(self):
        hits = idisc.scan_bash_command(f"node {SC}")
        assert [h["entry"] for h in hits] == ["sc_*"]

    def test_node_run_run_scenarios(self):
        hits = idisc.scan_bash_command(
            "python3 integration/run_scenarios.py --gate t260904-02")
        assert [h["entry"] for h in hits] == ["run_scenarios.py"]

    def test_nodejs_variant_still_red(self):
        assert idisc.scan_bash_command(f"nodejs {SC}") != []

    def test_check_flag_does_not_leak_into_later_args(self):
        """--check 只豁免其后本段实参；分号新段（; 后真跑）照判。"""
        hits = idisc.scan_bash_command(f"node --check a.mjs; node {SC}")
        assert [h["entry"] for h in hits] == ["sc_*"]

    def test_python_side_asymmetry_baseline_unchanged(self):
        """Python 侧既有豁免与真跑锚点不因本票漂移。"""
        assert idisc.scan_bash_command(
            "python3 -m py_compile integration/t260904-02/sc_x.py") == []
        assert idisc.scan_bash_command(
            "python3 integration/t260904-02/sc_x.py") != []


class TestDeclarationSync:
    """声明=执法（同批落字）：文案与 docstring 点名 node --check。"""

    def test_prompt_clause_names_both_static_forms(self):
        clause = idisc.prompt_clause()
        assert "node --check" in clause
        assert "py_compile" in clause
        for _key, name in idisc.FORBIDDEN_ENTRIES:  # 禁跑面不稀释
            assert name in clause, name

    def test_docstring_declares_node_check(self):
        doc = inspect.getdoc(idisc)
        assert doc and "node --check" in doc
        assert "--check" in doc and "NODE_STATIC_CHECK_FLAGS" in doc

    def test_briefs_carry_updated_clause(self):
        import dev_lane
        clause = idisc.prompt_clause()
        for stage in ("create_plan", "implement"):
            assert clause in dev_lane.FLOW_BRIEF[stage], stage
