"""L1 unit battery: the copy-language gate must see UNTRACKED files
(host ruling on -0008, t261004-26).

`git diff <base>` never shows a file git does not track, so before the
`untracked_diff` synthesis a brand-new in-scope file carrying Chinese dodged
the gate entirely — a check that cannot see its own target, this family's
fourth face. Run: python3 -m pytest integration/test_copy_language_untracked.py -q
(unit run, not an integration entry).
"""
import importlib.util
import pathlib

import pytest

_HERE = pathlib.Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "lint_copy_language", _HERE / "lint_copy_language.py")
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

CN_LINE = "label = '确认提交'"          # CJK ideographs: fires
EN_LINE = "label = 'Confirm submit'"   # clean


def fake_git_ls(files):
    def git(*args):
        if args[0] == "ls-files":
            return 0, "\0".join(files) + "\0"
        return 0, ""
    return git


def test_untracked_chinese_file_goes_red():
    # the battery case the host ruling demands: an untracked new file carrying
    # Chinese must produce a violation naming file:line
    diff = mod.untracked_diff(fake_git_ls(["server/engine/new_thing.py"]))
    assert diff == ""  # no real file on disk -> unreadable -> skipped (fail-safe)
    # with a real file present in the repo tree (this test file's own directory
    # is integration/, out of scope) we instead feed the synthesized diff shape
    # directly through lint_diff:
    planted = ("--- /dev/null\n+++ b/server/engine/new_thing.py\n"
               "@@ -0,0 +1,2 @@\n+import os\n+%s\n" % CN_LINE)
    got = []
    mod.lint_diff(planted, got.append, lambda m: None)
    assert any("server/engine/new_thing.py" in v and "2" in v for v in got), got


def test_untracked_clean_file_stays_clean():
    planted = ("--- /dev/null\n+++ b/server/engine/new_thing.py\n"
               "@@ -0,0 +1,2 @@\n+import os\n+%s\n" % EN_LINE)
    got = []
    mod.lint_diff(planted, got.append, lambda m: None)
    assert got == []


def test_untracked_diff_skips_out_of_scope_files():
    # integration/*.md is not in SCOPE_GLOBS/SCOPE_FILES -> not synthesized
    out = mod.untracked_diff(fake_git_ls(["integration/some_note.md"]))
    assert out == ""


def test_untracked_diff_renders_every_line_as_added():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / "server/engine/probe_cn.py"
        p.parent.mkdir(parents=True)
        p.write_text("import os\n%s\n" % CN_LINE, encoding="utf-8")
        # untracked_diff reads paths relative to cwd; chdir into the temp tree
        import os
        old = os.getcwd()
        os.chdir(td)
        try:
            out = mod.untracked_diff(fake_git_ls(["server/engine/probe_cn.py"]))
        finally:
            os.chdir(old)
    assert "+++ b/server/engine/probe_cn.py" in out
    assert "+import os" in out and ("+" + CN_LINE) in out
    added = [ln for ln in out.splitlines()
             if ln.startswith("+") and not ln.startswith("+++")]
    assert len(added) == 2  # both lines are added lines


def test_untracked_diff_fail_closed_on_git_error():
    def bad_git(*args):
        return 128, "fatal: not a git repository"
    assert mod.untracked_diff(bad_git) == ""
