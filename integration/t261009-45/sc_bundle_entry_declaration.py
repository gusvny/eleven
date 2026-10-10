#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261009-45 integration scenario: the PROJECT declaration carries the build entry.

intent (the ticket's whole change is two lines in server/merge-checks.yaml; the
user-visible contract they buy): the real workbench bundle pair in the project's
own server/merge-checks.yaml is ENTRY-BACKED — merge-check item 3.5 and the
t261009-38 settle path gate both see a declared, resolvable, executable build
entry with a positive integer budget, so a lane whose src-only change rebuilds
byte-identical output goes GREEN (the KI "unsatisfiable red" that parked
t261009-35/-41 is actually disarmed for the real pair, not just for synthetic
fixtures).

Intent split (checked against the registered set — no duplication):
- t261009-42-bundle-freshness-verdict owns the three-state verdict mechanism
  over SYNTHETIC pairs (its own fixture declaration, stub build scripts);
- t261009-38-bundle-out-gate-land / -mergecheck-pair-agreement own the settle
  gate and the whitelist widening, also over synthetic pairs;
- t260903-12-sc_merge_checks_pairs owns declaration/repo alignment generally;
- THIS entry owns the REAL project file's face: keys present and well-formed,
  entry target resolvable, both consumers agree on the same real file, the
  omission face (no budget_s -> lawful, engine default) and the degrade face
  (malformed value -> named legacy verdict, never fail-open).

Bindings stay shallow: only the declaration file's content and the reader
functions at the real consumers' call sites (path_gates.parse_bundle_pairs,
_read_bundle_entry_keys, _read_bundle_pairs_for_gate). A contract-preserving
refactor that keeps these faces does not break this scenario.

Pre-implement (declaration not yet written) = FAIL naming the missing faces
(TDD signal); required green at the integration gate / merge.
Run: PY -B integration/t261009-45/sc_bundle_entry_declaration.py  (cwd = repo root)
Three-state exit: PASS 0 / FAIL 1 / ENV_FAIL 2. Offline, seconds, zero docker /
Temporal / browser, never touches 3099.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "integration"))
sys.path.insert(0, str(REPO / "integration" / "t260904-18"))

from lib_t260904_18 import (  # noqa: E402
    check, env_fail, summary,
)

CFG = REPO / "server" / "merge-checks.yaml"
DECLARED_ENTRY = "server/plugins/workbench/build-client.sh"
DECLARED_SRC = "server/plugins/workbench/src/client/"
DECLARED_OUT = "server/plugins/workbench/lib/"

sys.path.insert(0, str(REPO / "server" / "engine"))
try:
    import agent_activities as aa  # noqa: E402
except Exception as e:  # engine tree unavailable = environment, not a red
    env_fail("engine agent_activities unimportable (%s: %s)" % (type(e).__name__, e))

try:
    text = CFG.read_text("utf-8")
except Exception as e:
    env_fail("project declaration server/merge-checks.yaml unreadable (%s: %s)"
             % (type(e).__name__, e))


def main() -> int:
    # ---- P1 the real file parses through the strict pair parser (after the
    # optional-key strip, the exact composition both consumers run): one pair,
    # the declared src/out, nothing else. The KI regression face: before the
    # strip seam existed, these very two lines raised ValueError here.
    stripped = aa._strip_bundle_optional_keys(text)
    try:
        pairs = aa._parse_bundle_pairs(stripped)
        check("P1 strict parse of real declaration succeeds after optional-key strip",
              isinstance(pairs, list), "parse raised")
    except Exception as e:
        check("P1 strict parse of real declaration succeeds after optional-key strip",
              False, "raised %s: %s" % (type(e).__name__, e))
        pairs = []
    check("P2 real declaration declares exactly the workbench pair",
          [(s, o) for s, o in pairs] == [(DECLARED_SRC, DECLARED_OUT)],
          "pairs=%r" % (pairs,))

    # ---- P3 the entry keys attach to that pair, well-formed: the declared
    # script path and a positive integer budget (the explicit 600).
    entries, diag = aa._read_bundle_entry_keys(text, len(pairs))
    check("P3 entry reader accepts the real declaration with no diag",
          diag == "", "diag=%r" % diag)
    check("P4 pair #1 is entry-backed with budget 600",
          len(entries) == 1 and entries[0] == (DECLARED_ENTRY, 600),
          "entries=%r" % (entries,))
    check("P5 declared budget is a positive integer",
          bool(entries) and entries[0][1] is not None and entries[0][1] > 0,
          "budget=%r" % (entries[0][1] if entries else None,))

    # ---- P6 the declared entry resolves on disk: a regular, executable file
    # at the repo root (what the check will invoke from a lane).
    target = REPO / DECLARED_ENTRY
    check("P6 declared build entry exists as a regular file", target.is_file(),
          "path=%s" % target)
    check("P7 declared build entry is executable",
          target.is_file() and bool(target.stat().st_mode & 0o111),
          "mode=%o" % (target.stat().st_mode if target.is_file() else 0,))

    # ---- P8 both consumers agree on the REAL file: the settle-gate loader
    # (same file, same parser, same strip) returns the same pair with no diag —
    # one declaration, two faces, no drift (KI: the extension lived in one
    # consumer while a second strict parser rejected it).
    gate_pairs, gate_diag = aa._read_bundle_pairs_for_gate(REPO)
    check("P8 settle-gate loader reads the real declaration clean",
          gate_diag == "" and [(s, o) for s, o in gate_pairs] == [(DECLARED_SRC, DECLARED_OUT)],
          "diag=%r pairs=%r" % (gate_diag, gate_pairs))

    # ---- P9 omission face: a copy without the budget_s line is still lawful
    # (entry kept, budget None -> engine default 600). The declared-explicit 600
    # and the default must be indistinguishable to the reader except for the
    # value itself — the policy-lives-in-the-repo claim, read back.
    no_budget = "\n".join(l for l in text.splitlines()
                          if not l.strip().startswith("budget_s:")) + "\n"
    e2, d2 = aa._read_bundle_entry_keys(no_budget, len(pairs))
    check("P9 declaration without budget_s is lawful (entry kept, default budget)",
          d2 == "" and bool(e2) and e2[0] == (DECLARED_ENTRY, None),
          "diag=%r entries=%r" % (d2, e2))

    # ---- P10 degrade face: a malformed budget value on the real shape yields
    # a NAMED diag and empty entries (legacy verdict fallback), never fail-open.
    bad = re.sub(r"budget_s:\s*\d+", "budget_s: soon", text)
    e3, d3 = aa._read_bundle_entry_keys(bad, len(pairs))
    check("P10 malformed budget_s degrades to a named legacy verdict",
          e3 == [] and d3 != "" and "budget_s" in d3,
          "entries=%r diag=%r" % (e3, d3))

    # ---- P11 family sweep: the real repo declares bundle_pairs exactly once
    # (a second declaration file elsewhere would be a second policy source the
    # consumers do not read — the KI taught that a second parser face is where
    # this design breaks).
    hits = []
    for p in (REPO / "server").rglob("*.yaml"):
        if ".sandbar" in p.parts or "node_modules" in p.parts:
            continue
        try:
            if "bundle_pairs:" in p.read_text("utf-8", errors="replace"):
                hits.append(str(p.relative_to(REPO)))
        except Exception:
            pass
    check("P11 server/ declares bundle_pairs exactly once (the project file)",
          hits == ["server/merge-checks.yaml"], "hits=%r" % hits)

    return summary()


if __name__ == "__main__":
    sys.exit(main())
