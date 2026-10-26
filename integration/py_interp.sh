#!/bin/sh
# Suite python interpreter resolution — the ONE rule for every python scenario
# leg (ticket t261026-35, Integration finding 261026: engine-importing
# scenarios ran system python3 and died with "No module named temporalio"
# because the old per-entry shim chains resolved relative to cwd with no
# fallback beyond it).
#
# Resolution order:
#   1. $SANDBAR_POC_PYTHON — only when set AND executable; a set-but-unusable
#      pointer is NAMED on stderr before falling through (never silent, per the
#      could-not-run naming contract of t261011-18).
#   2. server/engine/.venv/bin/python of the tree under test (cwd-relative).
#   3. the main checkout venv — the git common directory's sibling
#      server/engine/.venv/bin/python, so a line-round clone or worktree
#      without its own .venv still finds the checkout the clone came from.
#   4. plain python3.
# Every launch names the chosen interpreter on stderr in one line.
#
# Cmd contract: the runner executes every registry cmd with /bin/sh -c from the
# repo root, so all relative paths here are cwd-relative by design.
#
# -B: no scenario under test depends on __pycache__ persistence (checked in the
# implement report of t261026-35); the flag keeps clone trees clean.

set -u

py=""
ptr="${SANDBAR_POC_PYTHON:-}"
if [ -n "$ptr" ]; then
    if [ -x "$ptr" ]; then
        py="$ptr"
    else
        printf 'py_interp: SANDBAR_POC_PYTHON set but not executable (%s) - falling through to the next tier\n' "$ptr" >&2
    fi
fi
if [ -z "$py" ] && [ -x "server/engine/.venv/bin/python" ]; then
    py="server/engine/.venv/bin/python"
fi
if [ -z "$py" ]; then
    common=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || common=""
    if [ -n "$common" ] && [ -x "$common/../server/engine/.venv/bin/python" ]; then
        py="$common/../server/engine/.venv/bin/python"
    fi
fi
if [ -z "$py" ]; then
    py="python3"
fi

printf 'py_interp: interpreter=%s\n' "$py" >&2
exec "$py" -B "$@"
