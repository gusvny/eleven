#!/usr/bin/env python3
"""Copy-language gate (t261004-24): new user-visible copy must stay English.

Executor request -0003: t261004-12 shipped new console-visible copy in Chinese.
`docs/reference/writing-standard.md` §1 governs alert texts, panel strings,
ledger and settings copy; §2 makes the console surface English. This check is
the mechanical per-diff face of that rule: it inspects only ADDED lines of a
diff and fails when a new line carries CJK text inside product surfaces.

Scope (printed on every run):
  server/plugins/*/src/**            console-visible copy, ledger + settings copy, alert text
  server/engine/**                   engine product surfaces
  integration/lib_stage_console.mjs  integration face carrying product copy
  integration/lib_stage_ui_surface.mjs

Legacy lines are never inspected (per-diff by construction). A line that
rewrites a legacy Chinese comment/copy line surfaces as an added line and
fails — that is intended: modified text must comply with the standard.

Comments count, and the source is the same standard: §2 puts code comments in
the English column (host order 261004, recorded in server/session_charter.md —
CLAUDE.md rule 3 "modern Chinese" is retired; existing Chinese comments stay as
they are until touched). So a new or touched Chinese comment line inside the
scope below fires like any other copy line. `notes/` prose is Chinese by design
and stays out of scope.

Exemption (visible to a reviewer, keyed by rule id):
  put `copy-lang-allow:<id>` in a comment on the same line, or in a comment on
  the line directly above. Known ids:
    data     — detection patterns / prompt text that must stay in the language
               the executor writes (e.g. server/plugins/watchdog prose-backstop)
    fixture  — test fixture text
Exempt lines are listed in the run output.

Base resolution (fail-closed):
  $COPY_LANGUAGE_BASE > `git merge-base HEAD origin/main` > `git merge-base HEAD main`
  > HEAD (uncommitted worktree diff only).

Usage: python3 integration/lint_copy_language.py [--base <ref>] (cwd = repo root)
       Exit 0 = pass, 1 = violations, 2 = environment failure (fail-closed).
Module use: from lint_copy_language import lint_copy_language; lint_copy_language()
appends to lint_tests.py's shared errors list via its return value.
"""
import re
import sys
from pathlib import Path

# t261004-42: the base-resolution chain and the added-line parser moved to the
# shared module so the tier-marker lint (L19) reuses them instead of drifting.
# The local `git` callable keeps its name (module consumers and the battery call
# `git(...)`); behavior is byte-identical to the pre-extraction copy.
from lib_lint_diff import git_run as git  # noqa: E402
from lib_lint_diff import parse_added_lines, resolve_base  # noqa: E402

REPO = Path(__file__).resolve().parents[1]

# CJK: CJK ideographs (incl. ext A) + kana. CJK punctuation (U+3000 block,
# fullwidth forms) alone does not fire — the gate targets text, not typography.
CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")

SCOPE_GLOBS = [
    "server/plugins/*/src/**",
    "server/engine/**",
]
SCOPE_FILES = [
    "integration/lib_stage_console.mjs",
    "integration/lib_stage_ui_surface.mjs",
]
MARKER_RE = re.compile(r"copy-lang-allow:([A-Za-z0-9_-]+)")
# Line-comment intros per extension (a `#` in .mjs is not a comment).
COMMENT_PREFIXES = {".py": ("#",), ".mjs": ("//",), ".ts": ("//",), ".sh": ("#",)}


def _in_scope(path: str) -> bool:
    p = Path(path)
    for pat in SCOPE_GLOBS:
        # cheap glob match without fnmatch ** pitfalls
        parts = pat.split("/")
        if _glob_match(p.parts, parts):
            return True
    return path in SCOPE_FILES


def _glob_match(parts, pat_parts):
    import fnmatch
    if not pat_parts:
        return not parts
    head = pat_parts[0]
    if head == "**":
        for i in range(len(parts) + 1):
            if _glob_match(parts[i:], pat_parts[1:]):
                return True
        return False
    if not parts:
        return False
    return fnmatch.fnmatch(parts[0], head) and _glob_match(parts[1:], pat_parts[1:])


def _strip_comment(text: str, path: str) -> str:
    ext = Path(path).suffix
    for pref in COMMENT_PREFIXES.get(ext, ("//", "#")):
        idx = text.find(pref)
        if idx != -1:
            return text[:idx]
    return text


def _is_comment_only(text: str, path: str) -> bool:
    return _strip_comment(text, path).strip() == ""


def lint_diff(diff_text: str, emit, exempt_out):
    """Core check over a unified diff. emit(msg) records a violation."""
    prev = {}  # path -> previous new-file line text (context or added)
    prev_carry = {}
    for path, lineno, text in parse_added_lines(diff_text):
        marker_here = MARKER_RE.search(text)
        if marker_here:
            exempt_out.append("%s:%d copy-lang-allow:%s" % (path, lineno, marker_here.group(1)))
        elif prev_carry.get(path) and MARKER_RE.search(prev_carry[path]):
            marker = MARKER_RE.search(prev_carry[path])
            exempt_out.append("%s:%d copy-lang-allow:%s (marker on line above)"
                              % (path, lineno, marker.group(1)))
        # Whole-line comments count too (t261004-34, executor -0002): the host
        # order 261004 puts code comments in the English column, so a comment-only
        # added line fires like any other copy line. The docstring promises this;
        # dropping the old `not _is_comment_only` term is the tighten — it can
        # never loosen the gate. `_strip_comment`/`_is_comment_only` stay: the
        # marker-carry logic below still uses them, so `copy-lang-allow` on the
        # same line or the line directly above keeps exempting legitimately
        # exempt lines (including comment-only ones).
        elif _in_scope(path) and CJK_RE.search(text):
            emit("%s:%d new copy carries CJK text: %s" % (path, lineno, text.strip()[:120]))
        prev_carry[path] = text if _is_comment_only(text, path) or marker_here else None


def lint_copy_language(errors, base=None):
    """lint_tests.py entry (L15). Appends to errors; returns nothing."""
    print("L15 copy-language gate: scope = %s; %s" % (
        ", ".join(SCOPE_GLOBS + SCOPE_FILES), "added lines only (per-diff)"))
    # base is resolved first; a bad ref must fail closed, not green
    base_ref, how = resolve_base(base, git)
    if base_ref is None:
        errors.append("L15 copy-language gate fail-closed: %s" % how)
        return
    rc, diff_text = git("diff", "--unified=0", base_ref)
    if rc != 0:
        errors.append("L15 copy-language gate fail-closed: git diff failed: %s"
                      % diff_text.strip()[:200])
        return
    print("L15 copy-language gate: base = %s (%s)" % (base_ref, how))
    # Host ruling -0008: untracked-but-not-ignored in-scope files ride the same
    # added-line face (a new file is all added lines by definition).
    untracked = untracked_diff(git)
    if untracked:
        diff_text = diff_text + "\n" + untracked
        print("L15 copy-language gate: untracked in-scope files judged: %d"
              % untracked.count("+++ b/"))
    violations: list[str] = []
    exempt: list[str] = []
    lint_diff(diff_text, violations.append, exempt)
    if exempt:
        print("L15 copy-language gate: exempt lines (%d):" % len(exempt))
        for e in exempt:
            print("  " + e)
    else:
        print("L15 copy-language gate: exempt lines: none")
    if violations:
        for v in violations:
            # Report each failing line: a bare count is not a report (t261004-24
            # follow-up — the wired-in run printed only "N violation(s)", so a lane
            # could not see which line failed).
            print("FAIL: " + v)
            errors.append("L15 copy-language gate: " + v)
        print("L15 copy-language gate: %d violation(s)" % len(violations))
    else:
        print("L15 copy-language gate: clean")


def untracked_diff(git):
    """Synthesized added-line diff for UNTRACKED-but-not-ignored in-scope files
    (host ruling on -0008, t261004-26): `git diff <base>` never shows a file git
    does not track, so a brand-new file carrying Chinese would dodge the gate
    entirely. Each such file is rendered as a /dev/null -> file unified diff —
    every line is an added line, exactly the per-diff face. Unreadable files are
    skipped here (the L1 syntax gate owns unreadable sources); the tracked-file
    face is unchanged."""
    rc, out = git("ls-files", "-o", "--exclude-standard", "-z")
    if rc != 0:
        return ""
    chunks = []
    for rel in (p for p in out.split("\0") if p and _in_scope(p)):
        try:
            lines = Path(rel).read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        chunks.append("--- /dev/null\n+++ b/%s\n@@ -0,0 +1,%d @@\n" % (rel, len(lines))
                      + "".join("+" + ln + "\n" for ln in lines))
    return "\n".join(chunks)


def main(argv):
    base = None
    if "--base" in argv:
        i = argv.index("--base")
        base = argv[i + 1] if i + 1 < len(argv) else ""
        if not base:
            print("FAIL: --base needs a ref argument", file=sys.stderr)
            return 2
    errors: list[str] = []
    base_ref, how = resolve_base(base, git)
    if base_ref is None:
        print("ENV_FAIL: copy-language gate fail-closed: %s" % how, file=sys.stderr)
        return 2
    rc, diff_text = git("diff", "--unified=0", base_ref)
    if rc != 0:
        print("ENV_FAIL: git diff failed: %s" % diff_text.strip()[:300], file=sys.stderr)
        return 2
    # Host ruling -0008: untracked-but-not-ignored in-scope files ride the same
    # added-line face (a new file is all added lines by definition).
    untracked = untracked_diff(git)
    if untracked:
        diff_text = diff_text + "\n" + untracked
        n_files = untracked.count("+++ b/")
        print("copy-language gate: untracked in-scope files judged: %d" % n_files)
    print("copy-language gate: scope = %s" % ", ".join(SCOPE_GLOBS + SCOPE_FILES))
    print("copy-language gate: base = %s (%s); added lines only" % (base_ref, how))
    violations: list[str] = []
    exempt: list[str] = []
    lint_diff(diff_text, violations.append, exempt)
    if exempt:
        print("copy-language gate: exempt lines (%d):" % len(exempt))
        for e in exempt:
            print("  " + e)
    else:
        print("copy-language gate: exempt lines: none")
    for v in violations:
        print("FAIL: " + v)
    print("copy-language gate: %d violation(s)" % len(violations))
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
