#!/usr/bin/env python3
"""Shared diff-base helpers for the added-lines-only lint faces.

Extracted from `lint_copy_language.py` (t261004-24) so the tier-marker lint
(L19, t261004-42) reuses one base-resolution chain and one added-line parser
instead of a drifting second copy. Pure stdlib, no repo-tree writes.

`resolve_base` chain (fail-closed, never guesses):
  <explicit --base argument> > $<env_var> > `git merge-base HEAD origin/main`
  > `git merge-base HEAD main` > HEAD (uncommitted worktree diff only).
Returns (base_ref, how) or (None, reason).

`parse_added_lines` yields (path, new_lineno, line_text) for ADDED lines of a
unified diff only; context and removed lines never yield.

Both consumers call these with their own `git` callable (cwd = repo root), so
unit batteries can inject a fake git (malformed-input cases ride along).
"""
import os
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def git_run(*args):
    """Real git callable (cwd = repo root). Returns (rc, combined output)."""
    r = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def resolve_base(explicit, git, env_var="COPY_LANGUAGE_BASE"):
    """Return (base-ref, how) or (None, reason). Never guess silently."""  # type: (str|None, callable, str) -> tuple
    if explicit:
        return explicit, "--base argument"
    env = os.environ.get(env_var, "").strip()
    if env:
        return env, "$%s" % env_var
    for ref in ("origin/main", "main"):
        rc, out = git("merge-base", "HEAD", ref)
        if rc == 0 and out.strip():
            return out.strip(), "git merge-base HEAD %s" % ref
        # ref may not exist in a shallow/odd worktree; try the next one
    rc, _ = git("rev-parse", "--verify", "HEAD")
    if rc == 0:
        return "HEAD", "HEAD (uncommitted worktree diff only)"
    return None, "no git base resolvable and no HEAD"


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
