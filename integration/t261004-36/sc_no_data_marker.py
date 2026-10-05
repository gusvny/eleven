#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sc_no_data_marker.py — the temporary copy-language `data` exemption never
becomes permanent (t261004-36, gray-box L1/L2 static, offline seconds, zero
docker/ports/git).

intent (user-perceivable): host order 261004 accepted per-line `data`-id
exemptions (copy-lang-allow with id data) on the carried t261004-28 test lines
only UNTIL this ticket settles the engine refusal-copy language. Once the copy
is English the markers must be retired — "the markers must not become
permanent" is a stated requirement of ticket t261004-36. This scenario is the
permanent static guard: no such marker may exist anywhere under
server/engine/** or integration/**. (The `data` marker id itself stays a
documented, legitimate gate exemption for prompt/detection data in other
surfaces — this guard only pins that the ENGINE family no longer needs it.)

Pre-implement this is green by construction at the t261004-36 base (the
markers live in the t261004-28 lane, not yet merged); its job is the combined
tree after the merge — the same grep the implement handover must re-run.

Three states: engine tree missing = ENV_FAIL exit 2; any hit = FAIL exit 1.
Run directly: python3 integration/t261004-36/sc_no_data_marker.py (cwd=repo root).
"""
from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
# Assembled so this file never carries the literal marker itself.
MARKER = "copy-lang-allow" + ":data"
TREES = [REPO / "server" / "engine", REPO / "integration"]


def detect(tree):
    """Marker hits in one tree: [(path:lineno)]. Bytes-decoded per file; paths
    are relative to the SCANNED TREE (the teeth probe scans a temp tree, so the
    anchor is the tree, never the repo). The resolved tree root is printed by
    main so a false green is diagnosable."""
    hits = []
    for p in sorted(tree.rglob("*")):
        if not p.is_file() or p.suffix not in (".py", ".mjs", ".sh",
                                               ".ts", ".yaml", ".json"):
            continue
        raw = p.read_bytes()
        for i, line in enumerate(raw.decode("utf-8", errors="replace").splitlines(), 1):
            if MARKER in line:
                hits.append("%s:%d" % (p.relative_to(tree), i))
    return hits


def _teeth_check():
    """Guard-has-teeth probe: the same detector must fire on a planted marker
    in a throwaway tree, and stay silent on a clean file. If this fails the
    scan is unreliable (never trust a green that was never proven able to be
    red — t261004-36 acceptance round 5 found a false green on this face)."""
    import tempfile
    with tempfile.TemporaryDirectory(prefix="marker-teeth-") as td:
        root = pathlib.Path(td)
        dirty = root / "dirty.py"
        dirty.write_bytes(("x = 1  # " + MARKER + "\n").encode("utf-8"))
        clean = root / "clean.py"
        clean.write_bytes("y = 2\n".encode("utf-8"))
        hit = detect(root)
        if [str(h) for h in hit] != ["dirty.py:1"]:
            print("FAIL teeth: detector did not fire exactly once on a planted "
                  "marker (got %r) — scan unreliable" % (hit,))
            return False
    return True


def main():
    print("scan roots: %s" % ", ".join(str(t.resolve()) for t in TREES))
    if not _teeth_check():
        print("FAIL=t261004-36-no-data-marker (teeth probe failed)")
        return 1
    hits = []
    scanned = 0
    for tree in TREES:
        if not tree.is_dir():
            print("ENV_FAIL: tree missing: %s" % tree)
            return 2
        hits += detect(tree)
    scanned = sum(1 for tree in TREES for p in tree.rglob("*")
                  if p.is_file() and p.suffix in (".py", ".mjs", ".sh",
                                                  ".ts", ".yaml", ".json"))
    print("scanned %d files under %d trees" % (scanned, len(TREES)))
    if hits:
        for h in hits:
            print("FAIL marker present: %s" % h)
        print("FAIL=t261004-36-no-data-marker (%d hits)" % len(hits))
        return 1
    print("PASS=t261004-36-no-data-marker (0 hits under server/engine + integration; teeth probe fired)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
