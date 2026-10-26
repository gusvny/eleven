"""L29 unit battery: the suite-python interpreter lint must red a bare-
interpreter registry cmd over an engine-importing scenario script, and stay
green otherwise (t261026-35, Integration finding 261026).

Borrowed-implementation declaration (review row): the harness style is borrowed
from test_tier_marker_lint.py — in-memory injected registries, no spawn /
listener / timer / fd surface. NO fault faces carry over: the tier-marker rule
(diff-scoped intent markers) and this rule (launch shape over static imports)
share nothing but the file layout.

Shape-only contract: the check judges the launch argv[0] against the script's
static imports, never whether the venv actually holds temporalio. Run:
python3 -m pytest integration/test_lint_interp.py -q
(unit run, not an integration entry; malformed-input cases ride along).
"""
import importlib.util
import pathlib
import tempfile

_HERE = pathlib.Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("lint_tests",
                                               _HERE / "lint_tests.py")
lt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lt)


def _fixture_repo(tmp, script_body, local_shared=False):
    """A minimal tree: the scenario script under integration/, the engine
    module files it is judged against, optionally a shadowing local module."""
    repo = pathlib.Path(tmp)
    (repo / "integration" / "tfix").mkdir(parents=True, exist_ok=True)
    (repo / "server" / "engine").mkdir(parents=True, exist_ok=True)
    (repo / "server" / "engine" / "shared.py").write_text("")
    (repo / "server" / "engine" / "client.py").write_text("")
    (repo / "server" / "engine" / "dev_lane.py").write_text("")
    script = repo / "integration" / "tfix" / "sc_fix.py"
    script.write_text(script_body)
    if local_shared:
        (script.parent / "shared.py").write_text("X = 1\n")
    return repo, "integration/tfix/sc_fix.py"


def test_bare_interpreter_over_engine_import_is_red():
    with tempfile.TemporaryDirectory() as tmp:
        repo, script = _fixture_repo(tmp, "import temporalio\n")
        errs = lt.lint_interp_entries(
            [("sc-x", "intent", "python3 " + script)], repo=repo)
        assert len(errs) == 1 and "L29 sc-x" in errs[0]
        assert "bare python3" in errs[0] and "temporalio" in errs[0]


def test_bare_interpreter_over_each_engine_name_is_red():
    with tempfile.TemporaryDirectory() as tmp:
        for mod in ("shared", "client", "dev_lane"):
            repo, script = _fixture_repo(tmp, "import %s\n" % mod)
            errs = lt.lint_interp_entries(
                [("sc-x", "intent", "python3 " + script)], repo=repo)
            assert len(errs) == 1 and mod in errs[0], (mod, errs)


def test_helper_launch_is_green():
    with tempfile.TemporaryDirectory() as tmp:
        repo, script = _fixture_repo(tmp, "import temporalio\n")
        errs = lt.lint_interp_entries(
            [("sc-x", "intent",
              "sh integration/py_interp.sh " + script)], repo=repo)
        assert errs == []


def test_non_engine_import_bare_is_green():
    with tempfile.TemporaryDirectory() as tmp:
        repo, script = _fixture_repo(tmp, "import json\nimport os\n")
        errs = lt.lint_interp_entries(
            [("sc-x", "intent", "python3 " + script)], repo=repo)
        assert errs == []


def test_scenario_local_shadow_is_green():
    with tempfile.TemporaryDirectory() as tmp:
        repo, script = _fixture_repo(tmp, "import shared\n",
                                     local_shared=True)
        errs = lt.lint_interp_entries(
            [("sc-x", "intent", "python3 " + script)], repo=repo)
        assert errs == []


def test_cmd_without_script_token_is_named():
    with tempfile.TemporaryDirectory() as tmp:
        repo, _ = _fixture_repo(tmp, "import json\n")
        errs = lt.lint_interp_entries([("sc-x", "intent", "python3 -c '1'")],
                                      repo=repo)
        assert len(errs) == 1 and "no integration/*.py script token" in errs[0]


def test_missing_script_file_is_named():
    with tempfile.TemporaryDirectory() as tmp:
        repo, _ = _fixture_repo(tmp, "import json\n")
        errs = lt.lint_interp_entries(
            [("sc-x", "intent", "python3 integration/tfix/gone.py")],
            repo=repo)
        assert len(errs) == 1 and "cmd script missing" in errs[0]


def test_unparseable_script_is_named():
    with tempfile.TemporaryDirectory() as tmp:
        repo, script = _fixture_repo(tmp, "def broken(:\n")
        errs = lt.lint_interp_entries(
            [("sc-x", "intent", "python3 " + script)], repo=repo)
        assert len(errs) == 1 and "unparseable" in errs[0]


def test_real_fixed_registry_is_green():
    """The acceptance face: the rewritten real registry passes L29."""
    errs = lt.lint_interp_entries(_real_registry())
    assert errs == []


def _real_registry():
    import sys
    sys.path.insert(0, str(_HERE))
    import run_scenarios as rs
    return rs.SCENARIOS
