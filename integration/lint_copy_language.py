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
import os
import re
import subprocess
import sys
from pathlib import Path

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


def resolve_base(explicit, git):
    """Return (base-ref, how) or (None, reason). Never guess silently."""  # type: (str|None, callable) -> tuple
    if explicit:
        return explicit, "--base argument"
    env = os.environ.get("COPY_LANGUAGE_BASE", "").strip()
    if env:
        return env, "$COPY_LANGUAGE_BASE"
    for ref in ("origin/main", "main"):
        rc, out = git("merge-base", "HEAD", ref)
        if rc == 0 and out.strip():
            return out.strip(), "git merge-base HEAD %s" % ref
        # ref may not exist in a shallow/odd worktree; try the next one
    rc, _ = git("rev-parse", "--verify", "HEAD")
    if rc == 0:
        return "HEAD", "HEAD (uncommitted worktree diff only)"
    return None, "no git base resolvable and no HEAD"


def git(*args):
    r = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def parse_added_lines(diff_text):
    """Yield (path, new_lineno, line_text) for added lines only."""
    path = None
    new_lineno = 0
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:]
            continue
        if line.startswith("+++ "):
            path = None  # /dev/null (deleted file): no added lines to judge
            continue
        if line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            new_lineno = int(m.group(1)) - 1 if m else 0
            continue
        if path is None:
            continue
        if line.startswith("+") and not line.startswith("+++"):
            new_lineno += 1
            yield path, new_lineno, line[1:]
        elif line.startswith("-") or line.startswith("\\"):
            continue
        else:
            new_lineno += 1


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
        elif _in_scope(path) and not _is_comment_only(text, path) and CJK_RE.search(text):
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
            errors.append("L15 copy-language gate: " + v)
        print("L15 copy-language gate: %d violation(s)" % len(violations))
    else:
        print("L15 copy-language gate: clean")


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
