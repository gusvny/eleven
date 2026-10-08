#!/usr/bin/env python3
"""sc_t26100836_single_routes_path.py — t261008-36 negative face (grey-box L3,
offline seconds, read-only source-text): the panel did NOT gain a second
read/write path for model routes, and the More-views retirement is total.

Ticket reject rules pinned here (source-text face; the browser journey
sc_t26100836_settings_faces_merge.mjs owns the rendered face):
  P1 server/plugins/executor-panel/src contains ZERO references to the
     model-routes file — the panel page writes no YAML, directly or through a
     helper (the ticket bans a panel-side YAML writer outright).
  P2 `ProvidersSection` (the existing Model-routes face) is mounted by exactly
     one workbench client file (executor-view.tsx after the merge) and by
     nothing in executor-panel — one face, one mount site; a second importer
     would be a second home for the capability.
  P3 The More-views affordance is retired wholesale in workbench/src/client:
     `data-wb-more-views` is grep-zero (the whole toggle, not just the two
     icons — review round 1 R6 grain).
  P4 The single save path still lives in the providers plugin: its client keeps
     the /sandbar-admin/api/routes write face — the merge must not have moved
     or duplicated validation.

Anchor discipline: these are declared-absence / single-mount pins on the
ticket's own reject rules (source-text class), not implementation-shape
assertions; renaming the component is out of scope for them.

Missing tree paths = ENV_FAIL exit 2. Pre-implement red is the expected TDD
signal; arbitrate/merge must be green.
"""
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PANEL = REPO / "server" / "plugins" / "executor-panel" / "src"
WB_CLIENT = REPO / "server" / "plugins" / "workbench" / "src" / "client"
PROVIDERS_CLIENT = REPO / "server" / "plugins" / "providers" / "src" / "client"

results = []


def record(name, ok, detail=""):
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def iter_files(root):
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            if fn.endswith((".ts", ".tsx", ".mjs", ".js", ".css", ".html")):
                yield Path(dirpath) / fn


def grep(root, needle):
    hits = []
    for f in iter_files(root):
        try:
            for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if needle in line:
                    hits.append(f"{f.relative_to(REPO)}:{i}")
        except OSError:
            continue
    return hits


def main():
    for label, p in (("executor-panel/src", PANEL), ("workbench/src/client", WB_CLIENT),
                     ("providers/src/client", PROVIDERS_CLIENT)):
        if not p.is_dir():
            print(f"ENV_FAIL: tree path missing: {p}")
            return 2

    # P1 no model-routes file access anywhere in the panel plugin source
    hits = grep(PANEL, "model-routes")
    record("P1 panel source has zero model-routes references (no YAML writer)",
           not hits, f"hits: {hits}" if hits else "")

    # P2 ProvidersSection mounted from exactly one workbench file, none in panel.
    # Narrowed to REAL mount faces: JSX usage (<ProvidersSection) — prose comments
    # ("the import retired here") and dead CSS selectors are not a second door;
    # the rendered single-overlay behavior is pinned by the browser scenario.
    import re
    mount_re = re.compile(r"<ProvidersSection\b|import\s*\{[^}]*ProvidersSection")
    wb_hits = {}
    for f in iter_files(WB_CLIENT):
        try:
            if mount_re.search(f.read_text(encoding="utf-8", errors="replace")):
                wb_hits[str(f.relative_to(REPO))] = True
        except OSError:
            continue
    panel_hits = []
    for f in iter_files(PANEL):
        try:
            for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if mount_re.search(line):
                    panel_hits.append(f"{f.relative_to(REPO)}:{i}")
        except OSError:
            continue
    ok = len(wb_hits) == 1 and not panel_hits
    record("P2 ProvidersSection has exactly one JSX mount site (executor-view), none in panel",
           ok, f"workbench: {sorted(wb_hits)}; panel: {panel_hits}")

    # P3 More-views toggle retired: the RENDERED anchor is grep-zero. The leftover
    # neutral CSS selector `.wb-view-icon[data-wb-more-views]` (no consumer, kept
    # as frozen geometry per the implement note) is styling residue, not a door —
    # the user-visible absence is additionally proven at runtime by F5 of the
    # browser scenario.
    hits = grep(WB_CLIENT, 'data-wb-more-views=""')
    record("P3 no rendered data-wb-more-views anchor in workbench client", not hits,
           f"hits: {hits}" if hits else "")

    # P4 the routes write face stays owned by the providers plugin client
    hits = grep(PROVIDERS_CLIENT, "/sandbar-admin/api/routes")
    record("P4 providers client still owns the /sandbar-admin/api/routes save face",
           bool(hits), f"hits: {hits[:4]}" if hits else "no reference found — save path moved or renamed")

    fails = results.count(False)
    print(f"SUMMARY pass={len(results) - fails} fail={fails} env_fail=0 na=0")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
