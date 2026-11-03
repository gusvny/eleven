#!/usr/bin/env python3
"""Retired builder: the documentation index no longer lives inside the repository.

Design: docs/design/project-docs-roots-v1.md goal 5. The index is a DERIVED artefact
produced from the documents alone, and its home is the project's own data directory,
outside every repository of the project:

    <projects root>/<project key>/data/docs/index.json

The documentation inspection rebuilds it in its own periodic pass; an operator may ask
for a rebuild now through the engine's index face. This script therefore writes
NOTHING: it prints where the index lives, prints the command that rebuilds it, and
exits with a refusal (2), so an old habit or an old automation notices instead of
silently believing it refreshed something.

Why a stub and not a deletion: callers outside the write set of the ticket that retired
it still name this script (the knowledge feature's documented rebuild path, retired
scenario faces, operator notes). A stub that names the new location is a pointer they
can follow; a missing file is a dead end. No consumer reads an in-repository copy as
the truth, and that is the rule this retirement implements.

Usage (repository root):
    python3 docs/scripts/build_index.py [--project <project key>]
"""

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LEGACY_COPY = REPO / "docs" / "index.json"


def _resolver():
    """Import the engine's ONE resolver: the index location is declared there and is
    never repeated here. The engine is not on sys.path when this script runs from the
    repository root, so that path is added first."""
    sys.path.insert(0, str(REPO / "server" / "engine"))
    import docs_roots  # noqa: E402  (deliberate late import: see the docstring)
    return docs_roots


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="RETIRED: print where the derived documentation index lives "
                    "(this script never writes)")
    ap.add_argument("--project", default="",
                    help="project key whose index directory to name (else a pattern "
                         "with <project key> is printed)")
    args = ap.parse_args(argv)
    key = (args.project or "").strip()
    try:
        docs_roots = _resolver()
        if key:
            home = docs_roots.index_dir(key)
            rebuild = "python3 server/engine/docs_index.py --project %s" % key
            state = "python3 server/engine/docs_index.py --project %s --state" % key
        else:
            home = docs_roots.projects_root() / "<project key>" / "data" / "docs"
            rebuild = "python3 server/engine/docs_index.py --project <project key>"
            state = ("python3 server/engine/docs_index.py --project <project key> "
                     "--state")
    except Exception as e:      # noqa: BLE001 — a stub still answers without the engine
        home = Path("<projects root>") / "<project key>" / "data" / "docs"
        rebuild = "python3 server/engine/docs_index.py --project <project key>"
        state = rebuild + " --state"
        print("warning: the documentation-root resolver could not be loaded (%s); "
              "printing the conventional location instead" % str(e)[:200],
              file=sys.stderr)

    print("RETIRED: this script no longer builds docs/index.json inside the "
          "repository.")
    print("The derived documentation index lives outside every repository, in the "
          "project's own data directory:")
    print("  %s/index.json" % home)
    print("Rebuild it (the only write path): %s" % rebuild)
    print("Read its state without writing: %s" % state)
    print("The documentation inspection rebuilds it automatically in its periodic "
          "pass.")
    if LEGACY_COPY.is_file():
        print("The committed copy at %s is the legacy in-repository index. No consumer "
              "reads it as the truth (design docs/design/project-docs-roots-v1.md "
              "goal 5)." % LEGACY_COPY.relative_to(REPO))
    print("Refused: this run wrote no file.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
