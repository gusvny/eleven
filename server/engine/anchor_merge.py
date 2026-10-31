"""Anchor-manifest merge resolution (ticket t261031-30).

Why this module exists: `integration/test_anchors.json` is a JSON manifest with
one label per engine test and per registered scenario. `integration/lint_tests.py`
L16 (coverage / vocabulary / sync path) and L18 (snapshot marker discipline) judge
it. Git cannot marker-merge a JSON object, so two tickets that each add one anchor
entry always conflict at squash time. Measured 261031: one landing refused outright
("CONFLICT (content): integration/test_anchors.json") and three more blocked, each
costing a lane resync, a hand union and a hand recount of `_header.labelled_counts`.

The declared resolution is design (b), UNION WITH A VERIFIED RECOUNT: both sides'
entries are kept by a JSON union (never by markers) and every
`_header.labelled_counts` value is recomputed from the real dict lengths. Design (a),
regenerate at merge, was rejected: an anchor label and its note are AUTHORED text,
so a regeneration either invents them (a guessed label is a lie about what the test
asserts) or drops the lane author's entry. Union keeps the authored words and is the
smaller change.

Fail closed, named, never a silently merged file. This module REFUSES BY NAME when:
  - a side cannot be read (`anchors_unreadable`) or does not parse
    (`anchors_malformed`: bad JSON, non-object root, missing section, or a
    top-level key that names neither tree);
  - the two `_header` prose faces differ (`anchors_header_diverged`) — only the
    counts may move;
  - one entry exists on both sides with different values (`anchors_entry_conflict`);
  - an entry carries no anchor or an anchor outside the declared vocabulary
    (`anchors_unlabelled`), or declares production-snapshot with no sync_path
    (`anchors_snapshot_without_sync_path`);
  - the union would lose an entry or change one (`anchors_lost_entry`);
  - the recounted header would not equal the real dict lengths
    (`anchors_count_mismatch`);
  - two sides disagree on one displaced entry (`anchors_toplevel_diverged`).
The verification judges the BYTES that will land (parse back the canonical text),
not only the in-memory object.

Displaced entries (measured 261031, this tree's own copy): an earlier hand union
wrote five correct entries at the TOP level of the manifest instead of into their
tree. L16/L18 read only the two trees, so the rot was invisible and would have
survived every future merge. The union therefore recognises a top-level key that
is a test or scenario path: a duplicate of a judged entry is dropped (the judged
copy wins — it is the one L16/L18 see), and one that is not judged yet is MOVED
into its tree, value unchanged. Nothing is lost and the rot cannot propagate; the
note names every key treated this way.

L16/L18 stay the judges. This module never exempts the manifest: it only produces a
file whose entries are all present and all labelled.

Reuse: the canonical bytes and the file write come from `integration/lib_registry.py`
(`canonical_registry_bytes` / `write_registry`) — the one declared registry writer.
The module is loaded by path, so this module adds no import-order dependency. A
missing or broken writer is a named refusal, never a second serializer.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

#: The manifest this module resolves, relative to the tree root.
MANIFEST_PATH = "integration/test_anchors.json"

#: The two entry trees, in the manifest's own order.
TREES = ("engine_tests", "scenarios")

#: The declared header key and the label vocabulary (the SAME tuple L16 judges:
#: a resolver that accepted a wider vocabulary would buy a green the linter then
#: takes back at gate time).
HEADER_KEY = "_header"
COUNT_KEY = "labelled_counts"
ANCHOR_VOCAB = ("behaviour", "contract", "production-snapshot", "source-text")
SNAPSHOT = "production-snapshot"

# ---- refusal names (the merge-time protocol words) ---------------------------
#: A side's blob cannot be read (git show failed: absent path, delete/modify shape).
R_UNREADABLE = "anchors_unreadable"
#: A side's text is not the manifest shape (JSON, object root, sections, keys).
R_MALFORMED = "anchors_malformed"
#: The `_header` prose faces differ; only `labelled_counts` may move.
R_HEADER_DIVERGED = "anchors_header_diverged"
#: One key holds different values on the two sides: a union cannot keep both.
R_ENTRY_CONFLICT = "anchors_entry_conflict"
#: An entry has no anchor, or an anchor outside the declared vocabulary.
R_UNLABELLED = "anchors_unlabelled"
#: A production-snapshot entry names no sync_path (L16 judges the same pairing).
R_SNAPSHOT_NO_SYNC = "anchors_snapshot_without_sync_path"
#: The verified recount found an entry missing or changed after the union.
R_LOST = "anchors_lost_entry"
#: The header counts do not equal the real dict lengths after the union.
R_COUNT = "anchors_count_mismatch"
#: Two sides disagree on one displaced top-level entry (a union cannot keep both).
R_TOPLEVEL_DIVERGED = "anchors_toplevel_diverged"
#: The canonical writer (integration/lib_registry.py) is absent or broken.
R_WRITER = "anchors_writer_unavailable"
#: The resolver itself faulted (an exception escaped the pure paths).
R_RESOLVER = "anchors_resolver_fault"
#: The resolved file could not be staged, or the index still holds other conflicts.
R_STAGE = "anchors_stage_failed"

_MISSING = object()

#: lib_registry modules already loaded, keyed by resolved file path.
_LIB_CACHE: Dict[str, Any] = {}


class AnchorRefusal(Exception):
    """A named, fail-closed refusal. `name` is the protocol word, `detail` names
    the side, the tree and the key that failed (a reader must not have to guess)."""

    def __init__(self, name: str, detail: str = ""):
        self.name = name
        self.detail = detail
        super().__init__(self.brief())

    def brief(self) -> str:
        return "%s: %s" % (self.name, self.detail) if self.detail else self.name


class Resolution:
    """The outcome of a conflict-resolution attempt.

    status: resolved | not_applicable | refused
      - resolved: `obj` is the union and `text` the canonical bytes to write;
      - not_applicable: the conflict is not an anchors-only conflict, so the
        caller keeps its own path (today's behaviour, byte for byte);
      - refused: `name`/`detail` carry the named refusal.
    """

    def __init__(self, status: str, name: str = "", detail: str = "",
                 note: str = "", obj: Optional[Dict[str, Any]] = None,
                 text: str = ""):
        self.status = status
        self.name = name
        self.detail = detail
        self.note = note
        self.obj = obj
        self.text = text

    def brief(self) -> str:
        if self.status == "refused":
            return "%s: %s" % (self.name, self.detail) if self.detail else self.name
        return self.note or self.status

    def __repr__(self) -> str:  # pragma: no cover - diagnostic only
        return "Resolution(%r, %r, %r)" % (self.status, self.name, self.detail)


# ---- canonical writer (integration/lib_registry.py) --------------------------

def registry_module(repo) -> Any:
    """Load `integration/lib_registry.py` from the tree rooted at `repo`.

    Loaded by path so this module carries no sys.path side effect and cannot pick
    up another tree's copy. Any failure is the named refusal R_WRITER.
    """
    path = (Path(repo) / "integration" / "lib_registry.py").resolve()
    key = str(path)
    if key in _LIB_CACHE:
        return _LIB_CACHE[key]
    if not path.is_file():
        raise AnchorRefusal(R_WRITER, "canonical writer missing at %s" % path)
    spec = importlib.util.spec_from_file_location(
        "_anchor_merge_lib_registry_%d" % (abs(hash(key)),), path)
    if spec is None or spec.loader is None:
        raise AnchorRefusal(R_WRITER, "canonical writer not loadable at %s" % path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception as e:  # noqa: BLE001 — a broken writer is a named refusal
        raise AnchorRefusal(R_WRITER, "%s: %s" % (type(e).__name__, e))
    _LIB_CACHE[key] = mod
    return mod


def canonical_bytes(repo, obj: Any) -> str:
    """The canonical registry text for `obj` (one writer, never a second one)."""
    mod = registry_module(repo)
    try:
        return mod.canonical_registry_bytes(obj)
    except Exception as e:  # noqa: BLE001
        raise AnchorRefusal(R_WRITER, "canonical serialization failed: %s: %s"
                            % (type(e).__name__, e))


# ---- pure judgement ---------------------------------------------------------

def parse_manifest(text: str, side: str) -> Dict[str, Any]:
    """Parse one side's manifest text. Malformed input is a named refusal."""
    try:
        obj = json.loads(text)
    except Exception as e:  # noqa: BLE001
        raise AnchorRefusal(R_MALFORMED, "%s: not JSON (%s)" % (side, e))
    if not isinstance(obj, dict):
        raise AnchorRefusal(R_MALFORMED, "%s: root is %s, not an object"
                            % (side, type(obj).__name__))
    for tree in TREES:
        if not isinstance(obj.get(tree), dict):
            raise AnchorRefusal(R_MALFORMED, "%s: section %r missing or not an object"
                                % (side, tree))
    if not isinstance(obj.get(HEADER_KEY), dict):
        raise AnchorRefusal(R_MALFORMED, "%s: %s missing or not an object"
                            % (side, HEADER_KEY))
    # A top-level key that is not the header, not a tree and not a test/scenario
    # path is a shape this union cannot place — refuse before any comparison.
    for k in displaced_entries(obj):
        if tree_of(k) is None:
            raise AnchorRefusal(R_MALFORMED, "%s: top-level key %r is neither an "
                                "engine test nor a scenario path" % (side, k))
    return obj


def tree_of(path_key: str) -> Optional[str]:
    """The entry tree a displaced top-level path key belongs to (None = neither)."""
    if path_key.startswith("server/"):
        return "engine_tests"
    if path_key.startswith("integration/"):
        return "scenarios"
    return None


def displaced_entries(obj: Dict[str, Any]) -> Dict[str, Any]:
    """The top-level keys that are not the header and not a tree, in file order.

    Measured 261031: a hand union wrote correct entries at the top level of this
    very manifest. They are returned here, never refused, so the union can drop a
    judged duplicate or move a real stray into its tree.
    """
    reserved = (HEADER_KEY,) + TREES
    return {k: v for k, v in obj.items() if k not in reserved}


def judge_entry(tree: str, key: str, value: Any) -> None:
    """One entry must be an object carrying a vocabulary anchor; a
    production-snapshot entry must name its sync_path. Raises AnchorRefusal."""
    if not isinstance(value, dict):
        raise AnchorRefusal(R_UNLABELLED, "%s: %s holds %s, not an object"
                            % (tree, key, type(value).__name__))
    anchor = value.get("anchor")
    if anchor not in ANCHOR_VOCAB:
        raise AnchorRefusal(R_UNLABELLED, "%s: %s anchor=%r (vocabulary: %s)"
                            % (tree, key, anchor, "|".join(ANCHOR_VOCAB)))
    if anchor == SNAPSHOT and not value.get("sync_path"):
        raise AnchorRefusal(R_SNAPSHOT_NO_SYNC,
                            "%s: %s declares %s with no sync_path"
                            % (tree, key, SNAPSHOT))


def union_manifests(ours: Dict[str, Any], theirs: Dict[str, Any],
                    ours_name: str = "main", theirs_name: str = "lane"
                    ) -> Tuple[Dict[str, Any], str]:
    """Union two parsed manifests. Returns `(merged, note)`.

    Order: our side's entries keep their places, the other side's new entries are
    appended in its own order, so a union of two single-entry appends reads like a
    normal append and the diff stays small. Raises AnchorRefusal on every shape
    that cannot keep one entry on each side.
    """
    ho = ours[HEADER_KEY]
    ht = theirs[HEADER_KEY]
    plain_o = {k: v for k, v in ho.items() if k != COUNT_KEY}
    plain_t = {k: v for k, v in ht.items() if k != COUNT_KEY}
    if plain_o != plain_t:
        diff = sorted(set(plain_o) ^ set(plain_t)) or [
            k for k in sorted(plain_o) if plain_o.get(k) != plain_t.get(k)]
        raise AnchorRefusal(R_HEADER_DIVERGED, "header field(s) differ: %s"
                            % ", ".join(diff or ["<unnamed>"]))
    header = dict(ho)
    merged: Dict[str, Any] = {HEADER_KEY: header}
    main_only = lane_only = shared = 0
    for tree in TREES:
        so, st = ours[tree], theirs[tree]
        sec: Dict[str, Any] = {}
        for k, v in so.items():
            sec[k] = v
        for k, v in st.items():
            if k in sec:
                if sec[k] != v:
                    raise AnchorRefusal(
                        R_ENTRY_CONFLICT,
                        "%s: %s holds different values on %s and %s — a union "
                        "cannot keep both" % (tree, k, ours_name, theirs_name))
                shared += 1
                continue
            sec[k] = v
            lane_only += 1
        main_only += sum(1 for k in so if k not in st)
        merged[tree] = sec
    # Displaced top-level entries (see the module doc: a botched hand union wrote
    # correct entries one level too high). A judged duplicate is dropped — the
    # judged copy is the one L16/L18 see; any other stray is MOVED into its tree
    # with its value unchanged. Nothing is lost and the rot cannot propagate.
    do, dt = displaced_entries(ours), displaced_entries(theirs)
    dropped: List[str] = []
    moved: List[str] = []
    for k in list(do) + [k for k in dt if k not in do]:
        target = tree_of(k)
        if target is None:
            raise AnchorRefusal(R_MALFORMED,
                                "top-level key %r is neither an engine test nor a "
                                "scenario path" % k)
        if k in ours[target] or k in theirs[target]:
            dropped.append(k)
            continue
        vo, vt = do.get(k, _MISSING), dt.get(k, _MISSING)
        if vo is not _MISSING and vt is not _MISSING and vo != vt:
            raise AnchorRefusal(R_TOPLEVEL_DIVERGED,
                                "%s: displaced entry %s holds different values on "
                                "%s and %s" % (target, k, ours_name, theirs_name))
        merged[target][k] = vo if vo is not _MISSING else vt
        moved.append(k)
    for tree in TREES:
        for k, v in merged[tree].items():
            judge_entry(tree, k, v)
    counts: Dict[str, int] = {tree: len(merged[tree]) for tree in TREES}
    header[COUNT_KEY] = counts
    note = ("anchor manifest unioned: %s-only=%d %s-only=%d shared=%d; counts "
            "recounted engine_tests=%d scenarios=%d"
            % (ours_name, main_only, theirs_name, lane_only, shared,
               counts["engine_tests"], counts["scenarios"]))
    if dropped:
        note += "; dropped %d displaced duplicate(s) of judged entries: %s" % (
            len(dropped), ", ".join(dropped))
    if moved:
        note += "; moved %d displaced entry(ies) into their tree: %s" % (
            len(moved), ", ".join(moved))
    return merged, note


def verify_union(sides: Sequence[Tuple[str, Dict[str, Any]]],
                 merged: Dict[str, Any]) -> None:
    """Fail closed: every entry a side carried must survive with the same value,
    and the header counts must equal the real dict lengths. Raises AnchorRefusal."""
    for side, obj in sides:
        for tree in TREES:
            for k, v in obj[tree].items():
                got = merged.get(tree, {}).get(k, _MISSING)
                if got is _MISSING:
                    raise AnchorRefusal(R_LOST, "%s: %s entry %s is missing from "
                                        "the union" % (side, tree, k))
                if got != v:
                    raise AnchorRefusal(R_LOST, "%s: %s entry %s would change in "
                                        "the union" % (side, tree, k))
        for k, v in displaced_entries(obj).items():
            target = tree_of(k)
            if target is None:
                raise AnchorRefusal(R_MALFORMED, "%s: top-level key %r is neither "
                                    "an engine test nor a scenario path" % (side, k))
            got = merged.get(target, {}).get(k, _MISSING)
            if got is _MISSING:
                raise AnchorRefusal(R_LOST, "%s: displaced entry %s is missing from "
                                    "%s in the union" % (side, k, target))
            if k not in obj[target] and got != v:
                # a moved entry keeps its value; a dropped duplicate keeps the
                # judged value, which is the one the linter sees
                raise AnchorRefusal(R_LOST, "%s: displaced entry %s would change in "
                                    "the union" % (side, k))
    counts = merged.get(HEADER_KEY, {}).get(COUNT_KEY)
    real = {tree: len(merged.get(tree) or {}) for tree in TREES}
    if counts != real:
        raise AnchorRefusal(R_COUNT, "%s=%r but the real dict lengths are %r"
                            % (COUNT_KEY, counts, real))


# ---- git-facing -----------------------------------------------------------------

def resolve_conflict(run_git, repo, ours_ref: str, theirs_ref: str,
                     conflict_files: Iterable[str],
                     path: str = MANIFEST_PATH) -> Resolution:
    """Resolve an anchors-only squash conflict from the two refs' manifests.

    `run_git(argv, cwd)` is the caller's git runner (the engine passes
    `agent_activities._git`, so there is one git layer). Read-only: nothing is
    written here — the caller applies a `resolved` result, so the same call serves
    the merge_check rehearsal (a dry run) and the landing (an apply).

    Every shape other than "exactly this path conflicts, both sides readable and
    labelled" is `not_applicable` (keep the caller's own path) or `refused` (named).
    """
    files = [str(f) for f in (conflict_files or [])]
    if path not in files:
        return Resolution("not_applicable",
                          detail="%s is not a conflicted path" % path)
    others = [f for f in files if f != path]
    if others:
        return Resolution("not_applicable",
                          detail="other paths also conflict (left to the caller): %s"
                                 % ", ".join(others[:5]))
    texts: Dict[str, str] = {}
    for side, ref in (("ours", ours_ref), ("theirs", theirs_ref)):
        try:
            p = run_git(["show", "%s:%s" % (ref, path)], repo)
        except Exception as e:  # noqa: BLE001 — a git fault is a named refusal
            return Resolution("refused", name=R_RESOLVER,
                              detail="%s (%s): git runner faulted: %s: %s"
                                     % (side, ref, type(e).__name__, e))
        if p.returncode != 0:
            return Resolution("refused", name=R_UNREADABLE,
                              detail="%s (%s): git show failed: %s"
                                     % (side, ref, (p.stderr or "").strip()[-200:]))
        texts[side] = p.stdout or ""
    try:
        ours = parse_manifest(texts["ours"], "ours")
        theirs = parse_manifest(texts["theirs"], "theirs")
        merged, note = union_manifests(ours, theirs)
        text = canonical_bytes(repo, merged)
        landed = parse_manifest(text, "resolved")
        if landed != merged:
            raise AnchorRefusal(R_LOST, "the canonical text does not parse back to "
                                        "the union")
        verify_union([("ours", ours), ("theirs", theirs), ("resolved", landed)],
                     landed)
    except AnchorRefusal as e:
        return Resolution("refused", name=e.name, detail=e.detail)
    except Exception as e:  # noqa: BLE001 — never a crash, always a name
        return Resolution("refused", name=R_RESOLVER,
                          detail="%s: %s" % (type(e).__name__, e))
    return Resolution("resolved", obj=merged, text=text, note=note)


def apply_resolution(repo, resolution: Resolution,
                     path: str = MANIFEST_PATH) -> Path:
    """Write a `resolved` result through the canonical writer and read it back.

    The read-back is the point: the file that lands must parse to the verified
    union, so a writer fault cannot stage something the verification never saw.
    """
    if resolution.status != "resolved" or resolution.obj is None:
        raise AnchorRefusal(R_RESOLVER, "apply called with status %r"
                            % resolution.status)
    mod = registry_module(repo)
    target = Path(repo) / path
    try:
        mod.write_registry(target, resolution.obj)
    except Exception as e:  # noqa: BLE001
        raise AnchorRefusal(R_WRITER, "write_registry failed: %s: %s"
                            % (type(e).__name__, e))
    try:
        back = parse_manifest(target.read_text(encoding="utf-8"), "written")
    except AnchorRefusal as e:
        raise AnchorRefusal(R_WRITER, "written manifest does not read back: %s"
                            % e.brief())
    except Exception as e:  # noqa: BLE001
        raise AnchorRefusal(R_WRITER, "written manifest unreadable: %s: %s"
                            % (type(e).__name__, e))
    if back != resolution.obj:
        raise AnchorRefusal(R_LOST, "the written manifest differs from the "
                                    "verified union")
    return target
