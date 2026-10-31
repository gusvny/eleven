"""t261031-28: `python -m <static analyzer> <integration file>` is a read-only check.

Root cause (incident t261031-24, cross-project report): the developer-stage red line
matched the file argument of any exec verb against FORBIDDEN_ENTRIES. The `-m` branch
exempted only STATIC_TOOL_MODULES, which held stdlib parse tools. A third-party static
analyzer was not a member, so `python3 -m pyflakes integration/sc_*.py` turned the stage
red and the round was spent on a read-only check.

This module pins five faces:
1. green face: every admitted analyzer is exempt for every entry shape;
2. red face: pytest, unittest and the other executors keep their hits;
3. guards: no executor enters the union, the two subsets stay disjoint, and the union
   stays the sum (one edit point);
4. declaration sync: the docstring and prompt_clause() name every admitted analyzer,
   and the entry table does not drift;
5. the second consumer: agent_activities._iter_suite_invocations clears the
   space-separated analyzer form, while the joined form keeps its declared split.

Run: ``python3 -m pytest server/engine/tests/test_t261031_28_integration_discipline_static_analyzer.py -q``
(stdlib + pytest only; no network, no real Temporal, no integration entry).
"""
import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import integration_discipline as idisc  # noqa: E402

#: Scenario-shaped entry paths, one per entry-table family that an analyzer can read.
ENTRY_PATHS = (
    "integration/sc_x.py",
    "integration/run_scenarios.py",
    "integration/baselines/x.py",
    "integration/with_stage.sh",
)

#: Module names that import and run their argument. None of them may be admitted.
EXECUTOR_MODULES = (
    "pytest", "unittest", "doctest", "runpy", "timeit", "cProfile", "profile",
    "pdb", "trace", "coverage",
)


class TestAnalyzerExemptionGreen:
    """Acceptance AC1, AC2, AC5: the analyzer form is read-only, so it never hits."""

    def test_incident_command_green(self):
        """The command reported by t261031-24, verbatim."""
        assert idisc.scan_bash_command("python3 -m pyflakes integration/sc_*.py") == []

    def test_python_alias_green(self):
        assert idisc.scan_bash_command("python -m pyflakes integration/sc_*.py") == []

    def test_every_admitted_analyzer_green_for_every_entry_shape(self):
        for name in sorted(idisc.STATIC_ANALYZERS):
            for entry in ENTRY_PATHS:
                cmd = "python3 -m %s %s" % (name, entry)
                assert idisc.scan_bash_command(cmd) == [], cmd

    def test_analyzer_flags_and_glob_arguments_green(self):
        for cmd in (
            "python3 -m flake8 --max-line-length=100 integration/sc_x.py",
            "python3 -m mypy --ignore-missing-imports integration/sc_*.py",
            "python3 -m ruff check integration/t260902-07/sc_x.py",
            "python3 -m pyflakes /repo/integration/t260902-07/sc_x.py",
        ):
            assert idisc.scan_bash_command(cmd) == [], cmd

    def test_wrapper_and_assignment_prefixes_green(self):
        for cmd in (
            "timeout 300 python3 -m pyflakes integration/sc_*.py",
            "PYTHONPATH=. python3 -m pyflakes integration/sc_*.py",
            "env A=1 python3 -m pyflakes integration/sc_*.py",
        ):
            assert idisc.scan_bash_command(cmd) == [], cmd

    def test_shell_recursion_green(self):
        for cmd in (
            "bash -c 'python3 -m pyflakes integration/sc_x.py'",
            'bash -lc "python3 -m pyflakes integration/run_scenarios.py"',
        ):
            assert idisc.scan_bash_command(cmd) == [], cmd

    def test_joined_form_is_green_in_this_matcher(self):
        """AC5 (matcher side): `-m<module>` reads the same union. The second consumer
        keeps a declared split for this form (see TestSecondConsumer)."""
        for cmd in (
            "python3 -mpyflakes integration/run_scenarios.py",
            "python3 -mflake8 integration/sc_x.py",
        ):
            assert idisc.scan_bash_command(cmd) == [], cmd

    def test_exemption_is_segment_local(self):
        hits = idisc.scan_bash_command(
            "python3 -m pyflakes integration/sc_x.py && python3 integration/run_scenarios.py")
        assert [h["entry"] for h in hits] == ["run_scenarios.py"]

    def test_exemption_is_not_retroactive(self):
        hits = idisc.scan_bash_command(
            "python3 integration/run_scenarios.py -m pyflakes")
        assert [h["entry"] for h in hits] == ["run_scenarios.py"]


class TestExecutorShapesStayRed:
    """Acceptance AC3: real execution keeps its hit and its entry key."""

    def test_pytest_and_unittest_path_forms_stay_red(self):
        for cmd, entry in (
            ("python3 -m pytest integration/t260902-07/tests/sc_x.py", "sc_*"),
            ("python3 -m pytest integration/sc_*.py", "sc_*"),
            ("python3 -m unittest integration/t260902-07/tests/sc_x.py", "sc_*"),
            ("python3 -m unittest integration/run_scenarios.py", "run_scenarios.py"),
        ):
            hits = idisc.scan_bash_command(cmd)
            assert hits and hits[0]["entry"] == entry, (cmd, hits)

    def test_other_executors_stay_red(self):
        for cmd, entry in (
            ("python3 -m doctest integration/sc_x.py", "sc_*"),
            ("python3 -m runpy integration/sc_x.py", "sc_*"),
            ("python3 -m coverage run integration/sc_x.py", "sc_*"),
            ("python3 -m pdb integration/sc_x.py", "sc_*"),
        ):
            hits = idisc.scan_bash_command(cmd)
            assert hits and hits[0]["entry"] == entry, (cmd, hits)

    def test_entry_table_forms_unchanged(self):
        for cmd, entry in (
            ("python3 integration/run_scenarios.py", "run_scenarios.py"),
            ("python3 -m run_scenarios", "run_scenarios.py"),
            ("python3 -m integration.run_scenarios", "run_scenarios.py"),
            ("python3 -m sc_x", "sc_*"),
            ("node integration/t260902-07/sc_x.mjs", "sc_*"),
            ("sh integration/with_stage.sh t260901-13", "with_stage.sh"),
            ("python3 integration/baselines/x.py", "baselines"),
            ("bash server/tools/verify_lane t1", "verify_lane"),
        ):
            hits = idisc.scan_bash_command(cmd)
            assert hits and hits[0]["entry"] == entry, (cmd, hits)

    def test_analyzer_name_does_not_exempt_a_later_execution(self):
        hits = idisc.scan_bash_command(
            "python3 -m pyflakes integration/sc_x.py; python3 integration/run_scenarios.py")
        assert [h["entry"] for h in hits] == ["run_scenarios.py"]


class TestGuards:
    """Acceptance AC4: admission stays a curated, disjoint, one-edit-point table."""

    def test_no_executor_is_admitted(self):
        for name in EXECUTOR_MODULES:
            assert name not in idisc.STATIC_TOOL_MODULES, name
            assert name not in idisc.STATIC_ANALYZERS, name

    def test_subsets_are_disjoint_and_union_is_the_sum(self):
        assert not (idisc.STATIC_PARSE_TOOLS & idisc.STATIC_ANALYZERS)
        assert (idisc.STATIC_PARSE_TOOLS | idisc.STATIC_ANALYZERS
                == idisc.STATIC_TOOL_MODULES)

    def test_parse_tool_members_frozen(self):
        assert idisc.STATIC_PARSE_TOOLS == frozenset(
            {"py_compile", "compileall", "ast", "tokenize", "dis"})

    def test_analyzer_members_frozen(self):
        """The admission set is a deliberate, reviewed list. Add a name only with a
        new UT case and docstring text in the same change."""
        assert idisc.STATIC_ANALYZERS == frozenset(
            {"pyflakes", "flake8", "pycodestyle", "pydocstyle", "pylint", "mypy",
             "ruff"})

    def test_member_names_are_lowercase_module_names(self):
        for name in idisc.STATIC_TOOL_MODULES:
            assert name == name.lower() and "/" not in name and " " not in name, name

    def test_entry_table_frozen(self):
        assert tuple(k for k, _n in idisc.FORBIDDEN_ENTRIES) == (
            "run_scenarios.py", "sc_*", "baselines", "with_stage.sh", "verify_lane")


class TestDeclarationSync:
    """Acceptance AC6: declaration equals enforcement in one batch."""

    def test_docstring_names_every_admitted_analyzer(self):
        doc = inspect.getdoc(idisc)
        assert doc and "STATIC_ANALYZERS" in doc
        for name in sorted(idisc.STATIC_TOOL_MODULES):
            assert name in doc, name

    def test_docstring_declares_rule_and_executor_denylist(self):
        doc = inspect.getdoc(idisc)
        assert "does not import" in doc
        for name in ("pytest", "unittest", "coverage"):
            assert name in doc, name
        assert "declared residual" in doc and "t261031-28" in doc

    def test_prompt_clause_names_the_analyzer_form(self):
        clause = idisc.prompt_clause()
        assert "python3 -m <analyzer> <file>" in clause
        for name in sorted(idisc.STATIC_ANALYZERS):
            assert name in clause, name
        for _key, name in idisc.FORBIDDEN_ENTRIES:
            assert name in clause, name

    def test_prompt_clause_reports_the_executor_anchor(self):
        clause = idisc.prompt_clause()
        assert "-m pytest or -m unittest on an integration entry" in clause

    def test_briefs_carry_the_updated_clause(self):
        import dev_lane
        clause = idisc.prompt_clause()
        for stage in ("create_plan", "implement"):
            assert clause in dev_lane.FLOW_BRIEF[stage], stage


class TestSecondConsumer:
    """Acceptance AC7 (C4 scoped): the walkthrough/arbitrate classifier shares the
    union for the space-separated form, and keeps its declared split for `-m<module>`."""

    @staticmethod
    def _aa():
        return pytest.importorskip(
            "agent_activities", reason="engine entry chain needs the runtime deps")

    def test_space_separated_analyzer_is_not_a_suite_invocation(self):
        aa = self._aa()
        cmds = ["python3 -m pyflakes integration/run_scenarios.py",
                "python3 -m flake8 integration/run_scenarios.py"]
        for cmd in cmds:
            assert list(aa._iter_suite_invocations(cmd)) == [], cmd
        violations, _notes = aa._classify_suite_calls(cmds)
        assert violations == []

    def test_joined_form_split_is_declared(self):
        """agent_activities skips `-m<module>` through its generic flag branch; that
        file is outside this ticket's write set. The split is declared in the
        docstring, so the declaration and the consumer agree about the same command."""
        aa = self._aa()
        assert [list(a) for a in
                aa._iter_suite_invocations(
                    "python3 -mpyflakes integration/run_scenarios.py")] == [[]]

    def test_real_full_run_still_classifies_as_drift(self):
        aa = self._aa()
        violations, notes = aa._classify_suite_calls(
            ["python3 integration/run_scenarios.py"])
        assert [v["kind"] for v in violations] == ["drift"], notes


class TestMalformed:
    """House rule: malformed input never raises and never fakes a verdict."""

    def test_argless_and_dangling(self):
        for cmd in ("python3 -m", "python3 -m pyflakes",
                    "python3 -m pyflakes -", "python3 -m pyflakes --version"):
            assert idisc.scan_bash_command(cmd) == [], cmd

    def test_unclosed_quote_with_analyzer(self):
        assert idisc.scan_bash_command(
            'python3 -m pyflakes "unclosed integration/sc_x.py') == []

    def test_degenerate_inputs(self):
        for bad in (None, 123, "", "   ", [], {}):
            assert idisc.scan_bash_command(bad) == []
