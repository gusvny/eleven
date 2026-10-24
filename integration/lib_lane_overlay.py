#!/usr/bin/env python3
"""Lawful home for lane sandbox overlays — OUTSIDE the measured tree (t261021-10).

Incident (ticket body): a lane built its full-repo verification overlay at
`integration/<ticket>/overlay/` INSIDE the worktree, so the stage path gate
(arbitrate, kind `test_face`) read the untracked `server/engine/.venv` symlink
under it as `unauthorized_path` and auto-quarantined the whole overlay. Option A
was chosen: the overlay moves out of the measured tree, and the gate stays
untouched. This module is the ONE predicate in ONE place:

  * `overlay_root(ticket_id)`  - the lawful, out-of-tree overlay home for a
    ticket; every future lane overlay builder MUST create under it.
  * `overlay_path_is_lawful(path, repo_root)` - the pure judgement the lint
    rule (lint_tests.py L26) and this module's own builder both read: a path
    inside the repo tree is NEVER a lawful overlay home (the gate measures it);
    a path under the declared out-of-tree root is. A hand-written file under
    `integration/` stays refused — this fixes nothing about `integration/`
    generally, it only declares where a scratch overlay may live.

Consumers today: lint_tests.py L26 and tests/test_lib_lane_overlay.py. When the
first scenario runner wires its overlay creation, call `overlay_root` here
instead of re-deriving a path — that is the whole point of the single home.
"""
import os
import re
import shutil
import tempfile
from pathlib import Path

#: Env knob overriding the overlay home root (test seam + host override). A
#: knob value that points INSIDE a repo tree is refused by `overlay_root` —
#: the knob cannot re-import the incident through configuration.
OVERLAY_ROOT_ENV = "SANDBAR_LANE_OVERLAY_ROOT"

#: Ticket id shape: digits-digits, no separators, no traversal. Anything else
#: is a named refusal, never a silent fallback into the tree.
_TICKET_RE = re.compile(r"^t[0-9]{6}-[0-9]{2}$")


class OverlayLocationError(ValueError):
    """A named refusal for a malformed ticket id or an in-tree overlay root."""


def overlay_root(ticket_id, env=None):
    """Return the lawful out-of-tree overlay home for `ticket_id`.

    Default: `<system temp>/sandbar-lane-overlay/<ticket_id>`. The env knob
    `SANDBAR_LANE_OVERLAY_ROOT` overrides the root part (the ticket segment is
    always appended). Fail-closed rules, each a named `OverlayLocationError`:
      * ticket_id is empty, shape-mismatched, or carries path separators / `..`;
      * the resolved root is inside `repo_root` when the caller passes one (the
        knob may not point the overlay back into a measured tree).
    No directory is created here — creation belongs to `build_overlay`.
    """
    env = os.environ if env is None else env
    if not isinstance(ticket_id, str) or not _TICKET_RE.match(ticket_id):
        raise OverlayLocationError(
            "overlay_root: ticket id %r is not a <NNNNNN-NN> token; refusing "
            "to derive an overlay home from a malformed id" % (ticket_id,))
    root = env.get(OVERLAY_ROOT_ENV, "").strip()
    if root:
        root_path = Path(root)
    else:
        root_path = Path(tempfile.gettempdir()) / "sandbar-lane-overlay"
    home = root_path / ticket_id
    repo_root = env.get("SANDBAR_REPO_ROOT", "").strip()
    if repo_root:
        _refuse_if_inside(home, Path(repo_root))
    return home


def _refuse_if_inside(home, repo_root):
    """Named refusal when `home` sits inside `repo_root` (symlink-safe: both
    sides resolved; a non-existent tail still resolves its existing prefix)."""
    try:
        home_r = Path(os.path.realpath(str(home)))
        repo_r = Path(os.path.realpath(str(repo_root)))
    except OSError as e:                        # unreadable prefix = refuse, never guess
        raise OverlayLocationError(
            "overlay_root: cannot resolve %s against repo root %s (%s)"
            % (home, repo_root, e))
    if home_r == repo_r or repo_r in home_r.parents:
        raise OverlayLocationError(
            "overlay_root: %s resolves INSIDE the repo tree %s — the stage "
            "path gate measures that tree (t261021-10 incident); the overlay "
            "home must stay outside it" % (home, repo_root))


def overlay_path_is_lawful(path, repo_root):
    """Pure predicate: may `path` be a lane sandbox overlay home?

    Lawful = OUTSIDE the repo tree (nothing the gate measures contains it).
    Unlawful = inside the repo tree, which covers BOTH the incident shape
    (`integration/<ticket>/overlay/...`) and a hand-written file anywhere under
    the tree — this predicate opens nothing about `integration/` generally.
    Zero IO, stdlib-only; the lint and the builder read this same function.
    """
    if not isinstance(path, (str, os.PathLike)) \
            or not isinstance(repo_root, (str, os.PathLike)):
        return False
    if not str(path).strip() or not str(repo_root).strip():
        return False
    if "\x00" in str(path) or "\x00" in str(repo_root):
        return False
    try:
        p = Path(os.path.realpath(str(path)))
        r = Path(os.path.realpath(str(repo_root)))
    except (TypeError, ValueError, OSError):
        return False
    if p == r or r in p.parents:
        return False
    return True


def build_overlay(ticket_id, files, env=None):
    """Materialise a scratch overlay under the lawful home; return its path.

    `files` maps repo-relative paths to text content (or `Path` sources to
    copy). Creation and cleanup are paired: `dispose_overlay` removes the whole
    ticket home; the caller owns calling it on EVERY exit path (L8 tmp-hygiene
    discipline — a mkdtemp-class act always has a reclaim verb next to it).
    """
    home = overlay_root(ticket_id, env=env)
    home.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        dst = home / rel
        # `overlay_root` already refused an in-tree home, and `rel` is joined
        # under it; a traversal-shaped rel (leading `..`) could still escape,
        # so the resolved destination is re-checked against the home.
        if os.path.realpath(dst) != os.path.realpath(str(home)) \
                and not Path(os.path.realpath(dst)).is_relative_to(
                    Path(os.path.realpath(home))):
            raise OverlayLocationError(
                "build_overlay: %r escapes the declared overlay home" % (rel,))
        dst.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, Path):
            shutil.copy2(content, dst)
        else:
            dst.write_text(content, encoding="utf-8")
    return home


def dispose_overlay(ticket_id, env=None):
    """Remove the ticket's overlay home; every terminal state ends reclaimed."""
    home = overlay_root(ticket_id, env=env)
    shutil.rmtree(home, ignore_errors=True)
    return home
