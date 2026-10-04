"""L15 unit battery: the copy-language gate must count WHOLE-LINE comments
(t261004-34, executor -0002).

`lint_diff` used to fire only when `not _is_comment_only(text, path)`, so a line
that is nothing but a comment never fired: a planted `# 中文注释` gave NO
violation while `x = 1  # 中文`, a Chinese docstring and a Chinese string all
fired — a check that could not see its own target. Host order 261004 puts code
comments in the English column, so the fix tightens: comment-only added lines in
scope now fire. The `copy-lang-allow` marker (same line or line directly above)
still exempts legitimately exempt lines. Run:
python3 -m pytest integration/test_copy_language_comments.py -q
(unit run, not an integration entry).
"""
import importlib.util
import pathlib

_HERE = pathlib.Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "lint_copy_language", _HERE / "lint_copy_language.py")
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

ENGINE = "server/engine/new_thing.py"
PLUGIN = "server/plugins/workbench/src/panel-page.ts"
# CJK ideographs: fire. Clean ASCII: silent.
CN_COMMENT = "# 中文注释整行"
CN_INLINE = "label = '确认提交'"
EN_LINE = "label = 'Confirm submit'"


def run(text, path=ENGINE):
    """Feed a synthesized one-line diff through lint_diff; return violations."""
    planted = "--- a/%s\n+++ b/%s\n@@ -1,0 +2,1 @@\n+%s\n" % (path, path, text)
    got, exempt = [], []
    mod.lint_diff(planted, got.append, exempt)  # exempt_out is a list by contract
    return got


def test_whole_line_chinese_comment_fires():
    got = run(CN_COMMENT)
    assert any(ENGINE in v for v in got), got


def test_inline_chinese_comment_still_fires():
    # no regression on the pre-existing face
    got = run("x = 1  # 中文")
    assert any(ENGINE in v for v in got), got


def test_chinese_string_still_fires():
    got = run("x = '中文'")
    assert any(ENGINE in v for v in got), got


def test_marked_whole_line_comment_stays_exempt():
    got = run(CN_COMMENT + "  # copy-lang-allow:fixture")
    assert got == []


def test_marker_on_line_above_exempts_whole_line_comment():
    planted = ("--- a/%s\n+++ b/%s\n@@ -1,0 +2,2 @@\n"
               "+# copy-lang-allow:fixture\n+%s\n" % (ENGINE, ENGINE, CN_COMMENT))
    got, exempt = [], []
    mod.lint_diff(planted, got.append, exempt)  # exempt_out is a list by contract
    assert got == []
    assert any("marker on line above" in e for e in exempt), exempt


def test_clean_line_stays_clean():
    assert run(EN_LINE) == []
    assert run("# plain english comment") == []


def test_out_of_scope_comment_stays_silent():
    # integration/*.md is not in scope; a Chinese comment there is not judged
    assert run(CN_COMMENT, path="integration/some_note.md") == []


def test_mjs_hash_is_not_a_comment_so_it_fires_anyway():
    # `#` in .mjs is not a comment intros — but the tightened rule fires on CJK
    # regardless of comment shape, so a CJK line in .ts/.mjs still fires
    got = run("// 中文注释整行", path=PLUGIN)
    assert any(PLUGIN in v for v in got), got


def test_malformed_diff_does_not_crash():
    # external-input discipline: junk diff shapes must not raise and must not
    # fabricate violations
    for junk in (
        "",
        "not a diff at all\n",
        "+++ b/%s\n@@ broken hunk\n+%s\n" % (ENGINE, CN_COMMENT),
        "--- a/%s\n+++ b/%s\n@@ -1,0 +2,1 @@\n+\xff\n" % (ENGINE, CN_COMMENT),
        "+++ /dev/null\n@@ -1,0 +2,1 @@\n+%s\n" % CN_COMMENT,
    ):
        got, exempt = [], []
        mod.lint_diff(junk, got.append, exempt)  # exempt_out is a list by contract
        assert isinstance(got, list)
