#!/usr/bin/env python3
"""Content snapshot of the REAL projects root (t261030-25, KI-429).

Why this exists: a fixture wrote production state -- six ``run-*`` directories
under ``~/.sandbar/projects/sandbar/data/develop/rounds/`` plus run rows and
certification rows whose revision is not a git object in this repo -- and the
delivery line was frozen on that basis. The earlier hunt measured the rounds
directory by COUNT (11 -> 11) and therefore could not see a writer that both
adds its own evidence directory and prunes an old one (the round face keeps a
rolling window). Counting is the wrong instrument: this module fingerprints the
real root BY CONTENT, so "wrote and pruned" is still a visible change.

The snapshot is a FLAT map of relative path -> digest over a DECLARED watch
set (see ``WATCH_CONTENT`` / ``WATCH_STAT``). It records:

- directories as ``dir`` markers (an added/removed round directory is a change
  even when the directory is empty),
- files as ``sha256:<hex>`` of their bytes (the rounds tree, the delivery
  ledger, the guard/pointer files, the runs store),
- two oversized append-only ledgers as ``stat:<size>:<mtime_ns>`` (declared
  here, never silently: hashing 200 MB on every candidate would dominate the
  bisect, and any write to those files moves mtime_ns),
- the project directory's own top-level names (a new top-level artifact is a
  change even outside the watch set).

``digest()`` folds the map into one short hash: the before/after hash pair the
bisect prints. Stdlib only, read-only by construction (it never writes).
"""

import hashlib
import os
import pathlib

#: Environment variable the engine reads for the projects root
#: (``shared.perkey_projects_root``: empty or relative = unset).
PROJECTS_DIR_ENV = "SANDBAR_PROJECTS_DIR"

#: Files whose BYTES are hashed, relative to one project directory. Globs use
#: ``**`` (recursive) and are expanded with pathlib.
WATCH_CONTENT = (
    "data/develop/rounds/**",
    "data/develop/lines.json",
    "data/develop/landings.jsonl",
    "ledger/delivery.jsonl",
    "ledger/delivery-guard.json",
    "ledger/scenario-runs.jsonl",
    "ledger/executor-actions.jsonl",
    "ledger/run_watch_state.json",
)

#: Oversized append-only ledgers: witnessed by size + mtime_ns (declared
#: trade-off, see the module docstring).
WATCH_STAT = (
    "ledger/events.jsonl",
    "ledger/scenario-results.jsonl",
)

#: Subtrees witnessed by NAME only (a git worktree of this repo lives here;
#: its bytes belong to the repo, not to this watch set).
WATCH_NAMES = (
    "data/develop/wt/**",
)


def projects_root(env=None):
    """The projects root the engine would use RIGHT NOW (same rule as
    ``shared.perkey_projects_root``: empty or relative env = unset)."""
    env = os.environ if env is None else env
    raw = str(env.get(PROJECTS_DIR_ENV) or "")
    if not raw or not os.path.isabs(raw):
        return pathlib.Path.home() / ".sandbar" / "projects"
    return pathlib.Path(raw)


def project_dir(project_key, env=None):
    return projects_root(env) / str(project_key)


def _sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def _expand(root, pattern):
    """Expand one declared glob under ``root``. Returns existing paths only;
    a pattern that matches nothing is simply absent from the snapshot (the
    absence itself is stable, so a later appearance is still a diff)."""
    out = []
    for path in sorted(root.glob(pattern)):
        if path == root:
            continue
        out.append(path)
    return out


def snapshot(project_key, env=None, root=None):
    """Fingerprint one project directory. Returns
    ``{"root": <abs>, "project": <key>, "entries": {rel: digest}}``."""
    base = pathlib.Path(root) if root is not None else project_dir(project_key, env)
    entries = {}
    if base.is_dir():
        # top-level names of the project dir itself (new artifacts show up)
        for child in sorted(base.iterdir()):
            entries["<top>/" + child.name] = "dir" if child.is_dir() else "file"
    for pattern in WATCH_CONTENT:
        for path in _expand(base, pattern):
            rel = path.relative_to(base).as_posix()
            if path.is_dir():
                entries[rel] = "dir"
                continue
            try:
                entries[rel] = "sha256:" + _sha256_file(path)
            except OSError as e:  # vanished under us / unreadable: named
                entries[rel] = "unreadable:%s" % type(e).__name__
    for pattern in WATCH_NAMES:
        for path in _expand(base, pattern):
            rel = path.relative_to(base).as_posix()
            entries[rel] = "dir" if path.is_dir() else "file"
    for pattern in WATCH_STAT:
        for path in _expand(base, pattern):
            rel = path.relative_to(base).as_posix()
            try:
                st = path.stat()
                entries[rel] = "stat:%d:%d" % (st.st_size, st.st_mtime_ns)
            except OSError as e:
                entries[rel] = "unreadable:%s" % type(e).__name__
    return {"root": str(base), "project": str(project_key), "entries": entries}


def digest(snap):
    """One short hash over the whole snapshot (the before/after pair the
    bisect prints, ordered by path so it is stable)."""
    h = hashlib.sha256()
    for rel in sorted(snap["entries"]):
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(str(snap["entries"][rel]).encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()[:16]


def diff(before, after):
    """Named difference between two snapshots: ``(added, removed, changed)``,
    each a sorted list of relative paths. Empty on all three = byte-unchanged
    over the whole watch set."""
    b, a = before["entries"], after["entries"]
    added = sorted(set(a) - set(b))
    removed = sorted(set(b) - set(a))
    changed = sorted(k for k in set(a) & set(b) if a[k] != b[k])
    return added, removed, changed


def describe(before, after, limit=12):
    """Human line for a diff: counts always, the first ``limit`` names."""
    added, removed, changed = diff(before, after)
    total = len(added) + len(removed) + len(changed)
    if total == 0:
        return "UNCHANGED"
    parts = []
    for label, items in (("added", added), ("removed", removed),
                         ("changed", changed)):
        if items:
            shown = ", ".join(items[:limit])
            more = "" if len(items) <= limit else " ...(+%d)" % (len(items) - limit)
            parts.append("%s=%d [%s%s]" % (label, len(items), shown, more))
    return "CHANGED " + "; ".join(parts)
