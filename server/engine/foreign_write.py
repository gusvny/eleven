"""foreign_write — KI-01M4PAVBP6EZFGYC2VVQ0Z90J7 (t261012-09): pure predicates for
the engine-side foreign-file repair face.

The shape: a lane absorbed another ticket's unlanded files during a worker-settled
conflict resolution. The files are already COMMITTED on the lane branch, so they
only surface in the `base...HEAD` diff at merge_check; the lane cannot clean them
up (removing a file outside its write set IS a write outside its write set, so the
settle/path gate refuses the repair too). The engine returns them to main's
version itself — this module holds the pure classification and ownership
predicates; the IO (git restore/rm/commit) lives in agent_activities
(_repair_foreign_files), so both faces (merge_check and conflict resolution)
judge through this one source.

Style follows path_gates.py: zero IO, zero subprocess, injected predicates —
unit-testable without a repo.
"""
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, Union

# Runtime/coordination prefixes never judged foreign here (same set as
# verify_lane.py RUNTIME_PREFIXES; the legacy coordination directory comes from
# shared.DOT_DIR_OLD so this module carries no retired name of its own). Those paths
# have their own faces (settle pathspec excludes them; the whitelist skips them).
import shared as _shared

RUNTIME_PREFIXES: Tuple[str, ...] = (".sandbar/", _shared.DOT_DIR_OLD + "/", ".dsh/")


def parse_name_status_z(raw: str) -> List[Tuple[str, str]]:
    """Parse `git diff --name-status -z` output into (status, path) records.

    -z output shape: NUL-separated records `<status>\\0<path>\\0`; rename/copy
    records carry TWO paths (`R\\0<old>\\0<new>\\0`). A rename is recorded as TWO
    rows — the new path (what the merge would add) and the old path (what it
    would delete) — both repaired from main's version. Malformed tails (a
    dangling status with no path token) are dropped, never guessed into a path.
    """
    out: List[Tuple[str, str]] = []
    tokens = raw.split("\0")
    i = 0
    while i < len(tokens):
        st = tokens[i]
        if not st:
            i += 1
            continue
        if i + 1 >= len(tokens):
            break  # dangling status token, no path — drop, never guess
        if st[:1] in ("R", "C"):
            if i + 2 >= len(tokens):
                break
            old, new = tokens[i + 1], tokens[i + 2]
            if new:
                out.append(("M", new))
            if old and old != new:
                out.append(("D", old))
            i += 3
            continue
        p = tokens[i + 1]
        if p:
            out.append((st[:1], p))
        i += 2
    return out


def foreign_files(paths: Iterable, write_set: Any = None,
                  ticket_id: str = "",
                  test_face: Optional[Callable[[str], bool]] = None,
                  runtime_prefixes: Tuple[str, ...] = RUNTIME_PREFIXES,
                  protected_paths: Tuple[str, ...] = (),
                  line_owned: Optional[Callable[[str], bool]] = None) -> List[str]:
    """Paths OUTSIDE the ticket write set that the repair face owns.

    Admission stance (mirrors verify_lane's whitelist judge): an entry is an
    exact path or a directory prefix (`entry` or `entry/`). Excluded from the
    foreign verdict — each keeps its own existing named face:
      - `notes/` (host order 260904: the ledger belongs to main; the whitelist
        red already names it with its own text),
      - runtime prefixes (.sandbar/<legacy dot dir>/.dsh — outside SETTLE_PATHSPEC),
      - ticket-test-face files (path_gates.is_ticket_test_face, passed in as
        `test_face` — a lawful out-of-set deliverable of this ticket),
      - protected paths (path_gates.PROTECTED_PATHS, passed in as
        `protected_paths` — the protected-path gate owns that whole list: a
        base-existing modification goes to a human, a lane-created file such
        as the ticket's own verify.yaml declaration snapshot is admitted; the
        repair must never delete the declaration other gates still read),
      - LINE-owned paths (t261016-11, host order 261016 ②: the line is not a
        lane — the line legitimately carries landed content main does not have
        yet, so "absent on main" can never mean "foreign, delete it" there.
        `line_owned` is an injected predicate built from hash equality against
        line candidate refs; a faulting predicate is never a foreign verdict).
    Fail-closed guards: write_set empty/not-a-list → EVERY changed path is
    foreign by this predicate, but the REPAIR caller must not run on that shape
    (an empty set would classify the ticket's whole diff as foreign and erase
    its own work) — the caller pairs this predicate with repair_admissible and
    skips with a named note. Malformed path entries (non-str/empty) are skipped,
    never guessed into a path.
    """
    entries: List[str] = []
    if isinstance(write_set, list):
        entries = [str(e).strip().rstrip("/") for e in write_set
                   if isinstance(e, str) and e.strip()]
    in_set = {e for e in entries if e}
    out: List[str] = []
    for p in paths or ():
        if not isinstance(p, str) or not p.strip():
            continue
        if p.startswith(runtime_prefixes):
            continue
        if p == "notes" or p.startswith("notes/"):
            continue
        if any(p == e or p.startswith(e.rstrip("/") + "/")
               for e in protected_paths if e):
            continue
        if test_face is not None:
            try:
                if test_face(p):
                    continue
            except Exception:
                continue  # a faulting predicate is never a foreign verdict
        if line_owned is not None:
            try:
                if line_owned(p):
                    continue  # t261016-11 ②: line-owned landed content is not foreign
            except Exception:
                continue  # a faulting predicate is never a foreign verdict
        if any(p == e or p.startswith(e + "/") for e in in_set):
            continue
        if p not in out:
            out.append(p)
    return out


def repair_admissible(write_set: Any) -> Tuple[bool, str]:
    """The repair face's own admission guard (fail-closed).

    The engine repair is admitted by construction for the CLASSIFIED list, but
    classification needs a real write set: an empty/absent/malformed set would
    classify every changed path as foreign and the repair would erase the
    ticket's own work. Returns (False, reason) for that shape — the caller
    skips with the named reason and leaves the red (a human face), never
    repairs. A well-formed list (even one that admits nothing, e.g. judged via
    verify.yaml write_allow elsewhere) is admissible.
    """
    if not isinstance(write_set, list) or not write_set:
        return False, ("write_set empty or absent — the foreign classification "
                       "would cover the ticket's whole diff; repair skipped, "
                       "goes to a human")
    for e in write_set:
        if not isinstance(e, str) or not e.strip():
            return False, ("write_set carries a malformed entry (%r) — repair "
                           "skipped, goes to a human" % (e,))
    return True, ""


def line_owned(path: str, own_hash: str,
               blob_hash_of: Callable[[str, str], Optional[str]],
               line_refs: Iterable) -> bool:
    """t261016-11 ②: is this path's content LANDED LINE content?

    The line is not a lane: the line legitimately carries landed content that
    main does not have yet, so a path being "absent on main" must never read
    as "foreign, delete it". The judgment is the same single shape as
    `ownership`: hash equality or nothing. True ONLY when the path's blob on
    THIS tree (`own_hash`) is byte-identical to its blob at some line
    candidate ref (`blob_hash_of(path, ref)`; None = absent there). No fuzzy
    compare, no name similarity. False on: hash mismatch, absent on every line
    ref, or malformed input (non-str/empty path or hash) — fail-closed to the
    pre-fix verdict, never a silent relaxation. A candidate whose lookup
    faults is skipped by the caller (this predicate receives only clean
    lookups).

    Residual (stated in the plan): only ref-TIP content is covered; a
    line-carried file whose working-tree content was modified after landing
    falls outside this guard — the importer self-consistency floor
    (`importers_remain`) then still prevents an un-importable tree.
    """
    if not isinstance(path, str) or not path.strip():
        return False
    if not isinstance(own_hash, str) or not own_hash.strip():
        return False
    for r in line_refs or ():
        if isinstance(r, str):
            ref = r.strip()
        elif isinstance(r, dict):
            ref = str(r.get("ref") or "").strip()
        else:
            ref = ""
        if not ref:
            continue
        h = blob_hash_of(path, ref)
        if isinstance(h, str) and h.strip() and h == own_hash:
            return True
    return False


def importers_remain(tree_root, module_paths: Iterable,
                     read_text: Optional[Callable[[str], Optional[str]]] = None
                     ) -> List[Tuple[str, str]]:
    """t261016-11 ③: who imports the modules the repair plans to REMOVE?

    Pure over an injected reader: `read_text(abs_path) -> str | None`. Default
    reader does the IO (reads `.py` files under `tree_root`); tests inject a
    dict-backed reader and stay repo-free. Returns (importer_path, module)
    pairs. Module names are derived from each removal path (`x/y.py` -> `x.y`
    and its tail `y`; a bare `m.py` -> `m`) and matched against `import X` /
    `from X import ...` statements parsed with stdlib `ast`.

    The judgment is IMPORTABILITY, not path shape (KI-379): only a `.py` path
    is a module candidate. A path that cannot be imported — a JSON/text stamp
    or any other data artifact — contributes NO target and is never reported
    as an importer hit, so it never blocks its own removal (a build stamp such
    as `server/plugins/workbench/.build-stamp.json` is exactly that shape).

    Fail-closed shapes (never silently read as "no importers"):
      - a `.py` file that cannot be parsed counts as ONE unknown importer pair
        ("<file>", "<unparseable>") — the refusal names it, a human looks;
      - a non-str/empty module path is skipped from matching but reported as
        ("<malformed>", repr) so the caller still refuses the whole repair
        rather than repairing on an unknown shape;
      - a read fault (read_text returns None or raises) counts that file as
        unknown the same way.
    The CALLER owns the refusal: any non-empty return means the whole repair
    is refused (no rm, no restore, no commit) — never a tree that cannot
    import its own engine.
    """
    import ast as _ast
    import os as _os
    root = _os.fspath(tree_root)
    targets: List[Tuple[str, str]] = []
    for p in module_paths or ():
        if not isinstance(p, str) or not p.strip():
            targets.append(("<malformed>", repr(p)))
            continue
        rel = p.strip().lstrip("./")
        parts = [x for x in rel.split("/") if x]
        if not parts or not parts[-1].endswith(".py"):
            continue  # not an importable module: no target, no importer hit
        stem = parts[-1][:-3]
        dotted = ".".join(parts[:-1] + [stem])
        for name in ([dotted] if dotted != stem else []) + [stem]:
            if (name, p) not in targets:
                targets.append((name, p))
    names = {t[0] for t in targets if not t[0].startswith("<")}
    out: List[Tuple[str, str]] = []
    seen = set()

    def _report(imp: str, mod: str) -> None:
        key = (imp, mod)
        if key not in seen:
            seen.add(key)
            out.append(key)

    if names:
        for dirpath, _dirs, files in _os.walk(root):
            _dirs[:] = [d for d in _dirs
                        if d not in (".git", ".sandbar", ".dsh", "__pycache__")]
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                full = _os.path.join(dirpath, fn)
                rel = _os.path.relpath(full, root)
                try:
                    src = read_text(full) if read_text is not None \
                        else _default_read(full)
                except Exception:
                    src = None
                if src is None:
                    _report(rel, "<unreadable>")
                    continue
                try:
                    tree = _ast.parse(src)
                except (SyntaxError, ValueError, RecursionError):
                    _report(rel, "<unparseable>")
                    continue
                mods = set()
                for node in _ast.walk(tree):
                    if isinstance(node, _ast.Import):
                        for a in node.names:
                            mods.add(a.name)
                    elif isinstance(node, _ast.ImportFrom) and node.module:
                        mods.add(node.module)
                for t_name, t_path in targets:
                    if t_name.startswith("<"):
                        continue
                    if t_name in mods or any(m.startswith(t_name + ".")
                                             for m in mods):
                        _report(rel, t_path)
    for t_name, t_path in targets:
        if t_name.startswith("<"):
            _report(t_name, t_path)
    return out


def _default_read(path: str) -> Optional[str]:
    import os as _os
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def _candidate_label(c: Union[str, Dict]) -> Tuple[str, str, str]:
    """Normalize one candidate ref into (ref, ticket-label, source). A plain
    string is a lane branch name: the owner label is the branch name itself
    (the ticket id is not derivable from the alias part without guessing — the
    label stays the measured fact) and the source is 'refs'."""
    if isinstance(c, str) and c.strip():
        name = c.strip()
        return name, name[len("lane/"):] if name.startswith("lane/") else name, "refs"
    if isinstance(c, dict):
        ref = str(c.get("ref") or "").strip()
        if ref:
            ticket = str(c.get("ticket") or "").strip()
            return ref, (ticket or ref), str(c.get("source") or "registry")
    return "", "", ""


def ownership(path: str, own_hash: str,
              blob_hash_of: Callable[[str, str], Optional[str]],
              candidate_refs: Iterable[Union[str, Dict]]) -> str:
    """The owner verdict for one foreign path: hash equality or silence ONLY.

    own_hash is the foreign file's blob hash as committed on THIS lane;
    blob_hash_of(path, ref) returns the blob hash of `ref:path` at a candidate
    ref (None = absent there). A candidate lane whose version of the path is
    byte-identical (hash-equal) to the foreign file → 'belongs to lane <owner>
    (source=<source>)'; several lanes carrying the same bytes name every owner;
    no hash match anywhere → 'belongs to no live lane'. Never a guess: no fuzzy
    compare, no name similarity, no inference. A candidate whose lookup faults
    is the CALLER's named skip (pass a blob_hash_of that returns None only for
    'absent'). main can be passed as a candidate too — a file byte-identical to
    main's version is nobody's unlanded work, and the verdict names it the same
    way (the caller decides whether to list main among the candidates).
    Malformed path (non-str/empty) → the silence verdict, never a lane name.
    """
    if not isinstance(path, str) or not path.strip():
        return "belongs to no live lane"
    if not isinstance(own_hash, str) or not own_hash.strip():
        return "belongs to no live lane"
    matched: List[Tuple[str, str]] = []
    for c in candidate_refs or ():
        ref, label, source = _candidate_label(c)
        if not ref:
            continue
        h = blob_hash_of(path, ref)
        if isinstance(h, str) and h.strip() and h == own_hash:
            matched.append((label, source))
    if matched:
        labels = sorted({"%s (source=%s)" % (lbl, src) for lbl, src in matched})
        return "belongs to lane %s" % ", ".join(labels)
    return "belongs to no live lane"
