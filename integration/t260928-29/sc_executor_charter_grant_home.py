#!/usr/bin/env python3
"""executor-grant facts live in the sandbar section + the charter-identity scenario stays live-judged (t261009-14, registry: t261009-14-executor-charter-grant-home).

Intent (gray-box L2 static contract, ro pool, offline, sub-second, zero docker):

Ticket t261009-14 re-delivers the charter-identity contract by relocating the
executor-grant block (## 当前在案授权 / executor-grants.json) out of the generic
charter template into the `## project:sandbar` section. Two user-perceivable
commitments must stay pinned:

- G  No net loss of coverage: the grant facts survive the relocation — the
  sandbar section still names the on-file authorization source
  (`executor-grants.json`), and the generic template part carries no grant
  reference at all. Keyword classes differ from the sibling scenario's B1
  (`执行器` marker): file-name anchors survive marker-word rewording, so a
  later edit cannot green B1 while quietly dropping the grant block.
- N  Never booked: `t260928-29-executor-charter-identity` must not appear in
  integration/known-red-baseline.json entries. The roster's effect is to SKIP
  scenarios, so booking it would silence the exact regression class this
  ticket fixes (KI-01M4FE0T3FG7Y0G9R97NS4T7QJ: the red rode 72+ rounds as
  "brand-new noise" and a prior "removed as fixed" verdict was never
  re-checked). The scenario is offline and sub-second — it must be judged
  live every round, forever.

intent split (anti-duplication): sc_executor_charter_identity.py pins the
identity semantics (A-face anchors, B1 generic marker, C dual sections); this
scenario pins only the ticket's two add-ons — grant-fact placement and the
never-booked contract. Registry/roster machinery behavior is not asserted
here (that is the known-red-baseline hygiene test family's face).

G-face red before the implement stage lands is the expected TDD signal;
arbitrate/merge must be green.
"""
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from lib_env import EXIT_FAIL, EXIT_PASS  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
CHARTER = REPO / "server" / "session_charter.md"
BASELINE = REPO / "integration" / "known-red-baseline.json"
PROTECTED = "t260928-29-executor-charter-identity"

PASS = 0
FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("PASS %s" % label)
    else:
        FAIL += 1
        print("FAIL %s" % label)


def split_sections(text):
    parts = re.split(r"(?m)^(## project:([A-Za-z0-9_-]+))\s*$", text)
    generic = parts[0]
    secs = {}
    for i in range(1, len(parts), 3):
        secs[parts[i + 1]] = parts[i + 2]
    return generic, secs


def main():
    text = CHARTER.read_text("utf-8") if CHARTER.is_file() else ""
    generic, secs = split_sections(text)
    sand = secs.get("sandbar", "")

    print("\n=== G grant facts relocated with zero loss ===")
    ok("executor-grants.json" in sand,
       "G1 sandbar section still names the on-file grant source")
    ok(re.search(r"(?m)^##\s*当前在案授权\s*$", generic) is None,
       "G2 generic template carries no on-file authorization block (heading-level anchor; quoted cross-references are legitimate)")
    ok("executor-grants.json" not in generic,
       "G3 generic template carries no grant-file reference")

    print("\n=== N charter-identity scenario never booked ===")
    names = []
    try:
        data = json.loads(BASELINE.read_text("utf-8"))
        names = [e.get("name", "") for e in data.get("entries", [])]
    except (OSError, ValueError):
        pass
    ok(BASELINE.is_file() and bool(names),
       "N1 known-red roster present and parseable (guard is not vacuous)")
    ok(PROTECTED not in names,
       "N2 %s not in the roster (booking = skip = silencing)" % PROTECTED)

    print("\nRESULT pass=%d fail=%d" % (PASS, FAIL))
    return EXIT_PASS if FAIL == 0 else EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
