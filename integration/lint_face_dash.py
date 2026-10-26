"""L28 — the ONE narrow check for the dash funnel (t261026-11, host ruling 261026).

Exactly one rule, deliberately NOT a shape scan: outside the funnel module
(server/plugins/workbench/src/shared/face-value.ts), a bare placeholder
literal ('—' / "—") in a host face module under server/plugins/*/src is an
error — except for the per-file:line entries in the exemption table
(integration/face_dash_exemptions.json), which are today's pre-funnel sites
at check-authoring time.

Only-shrinks discipline (same as the known-red roster): a NEW bare literal is
an error, and a STALE exemption — a table entry whose line no longer carries
the literal — is itself an error, so the table can only shrink. A future fix
that routes a site through the funnel edits the table down; growth is a red.

Line-keyed, as the ticket specifies ("per-file:line exemption table"): an
unrelated edit that shifts a line number turns that entry stale and the run
red — that is the declared price of the discipline; rebase the table to the
same entries at their new lines in the same change.

Comment lines are not literals: a line whose first non-blank character starts
a comment (//, /*, *) is skipped, so prose em-dashes in comments never trip
the rule; em-dash PROSE inside string copy is also safe (the pattern matches
a quoted dash, nothing else).

Usage:
    python3 integration/lint_face_dash.py                    # the check
    python3 integration/lint_face_dash.py --write-baseline   # seed/regenerate the table
Wired into integration/lint_tests.py as L28; this file is also a standalone
entry so the rule can be pointed at one incident in seconds.

HISTORY: first authored in the gen0 acceptance-walkthrough round and lost when
the rework cycle reset the workspace before the worker settle could carry it
(only run_scenarios.py survived in the arbitrate commit). Re-authored here
byte-for-byte in intent in gen1; the reseed below is from the post-rework tree.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FUNNEL_REL = "server/plugins/workbench/src/shared/face-value.ts"
TABLE_REL = "integration/face_dash_exemptions.json"
TABLE = REPO / TABLE_REL
PLACEHOLDER = re.compile(r"['\"]—['\"]")
SKIP_DIRS = {"node_modules", "dist", "build", "__pycache__", ".sandbar", "overlay"}
COMMENT_PREFIXES = ("//", "/*", "*")


def scan(root=None):
    """Return {rel_path: [line numbers]} of every bare placeholder literal
    outside the funnel module. `root` is injectable so a mechanism test can
    plant a fixture tree instead of walking the real one."""
    base = Path(root) if root is not None else REPO / "server/plugins"
    hits: dict[str, list[int]] = {}
    if not base.is_dir():
        return hits
    for cur, dirs, files in os.walk(str(base)):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if not name.endswith((".ts", ".tsx")):
                continue
            p = Path(cur) / name
            rel = os.path.relpath(str(p), str(REPO)).replace(os.sep, "/")
            if rel == FUNNEL_REL:
                continue  # the funnel module owns the one literal — exempt by name
            try:
                text = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            lines = []
            for i, line in enumerate(text.splitlines(), 1):
                if not PLACEHOLDER.search(line):
                    continue
                if line.lstrip().startswith(COMMENT_PREFIXES):
                    continue  # a comment is prose, not a literal
                lines.append(i)
            if lines:
                hits[rel] = lines
    return hits


def load_table():
    """Return the exemption table as {rel_path: [lines]} or None when absent."""
    if not TABLE.exists():
        return None
    try:
        data = json.loads(TABLE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError("exemption table %s is not readable JSON: %s" % (TABLE_REL, e))
    if not isinstance(data, dict):
        raise ValueError("exemption table %s must be a JSON object" % TABLE_REL)
    bad = [k for k, v in data.items() if not k.startswith("_") and not isinstance(v, list)]
    if bad:
        raise ValueError("exemption table %s must map file -> [line, ...]; "
                         "bad key(s): %s" % (TABLE_REL, ", ".join(bad[:4])))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def write_baseline(root=None):
    """Seed/regenerate the exemption table from today's live sites."""
    hits = scan(root)
    payload = {
        "_rule": "L28 face-dash exemptions (t261026-11): per-file:line sites that "
                 "predate the funnel. ONLY SHRINKS — a new literal is a red, a "
                 "stale entry is a red; regenerate same-size in the same change "
                 "when an edit shifts line numbers.",
        "_generated_by": TABLE_REL + " via lint_face_dash.py --write-baseline",
    }
    payload.update({k: sorted(v) for k, v in sorted(hits.items())})
    TABLE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                     encoding="utf-8")
    print("L28 baseline written: %s (%d files, %d sites)"
          % (TABLE_REL, len(hits), sum(len(v) for v in hits.values())))
    return 0


def lint_face_dash(errors, root=None):
    """The check. Appends named errors to `errors` (lint_tests.py convention);
    prints its own one-line verdict either way."""
    table = load_table()  # may raise ValueError -> lint_tests names it, do not mask
    hits = scan(root)
    exempt = table or {}

    new_hits = []
    for rel, lines in sorted(hits.items()):
        allowed = set(exempt.get(rel, []))
        for ln in lines:
            if ln not in allowed:
                new_hits.append("%s:%d" % (rel, ln))
    stale = []
    hit_set = {(rel, ln) for rel, lines in hits.items() for ln in lines}
    for rel, lines in sorted(exempt.items()):
        if rel not in hits and rel != FUNNEL_REL and not (REPO / rel).exists():
            stale.append("%s (file gone)" % rel)
            continue
        for ln in lines:
            if (rel, ln) not in hit_set:
                stale.append("%s:%d" % (rel, ln))

    if new_hits:
        errors.append(
            "L28 face-dash funnel: NEW bare placeholder literal outside the "
            "funnel module at %s — route it through face-value.ts value()/"
            "absent() (or add a dated exemption-table entry with a reason in "
            "the same change, and only via table shrink)" % ", ".join(new_hits[:8]))
    if stale:
        errors.append(
            "L28 face-dash funnel: STALE exemption table entries at %s — the "
            "table must ONLY SHRINK; remove the dead entries in the same "
            "change that moved/fixed the site (%s)" % (", ".join(stale[:8]), TABLE_REL))
    if not new_hits and not stale:
        print("L28 face-dash funnel: %d exempted site(s) across %d file(s), "
              "no new literal, no stale exemption (%s)"
              % (sum(len(v) for v in hits.values()), len(hits), TABLE_REL))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--write-baseline" in argv:
        return write_baseline()
    errors: list[str] = []
    try:
        lint_face_dash(errors)
    except ValueError as e:
        print("L28 ERROR: %s" % e)
        return 1
    for e in errors:
        print("ERROR: %s" % e)
    print("L28 done: %d error" % len(errors))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
