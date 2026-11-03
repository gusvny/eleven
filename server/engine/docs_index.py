"""docs_index -- the derived documentation index: builder, writer, and the reader that
tells its four states apart (design docs/design/project-docs-roots-v1.md; ticket
t261103-12, the index + presentation half).

The declaration and the resolution are NOT here. This module asks the ONE resolver
(`docs_roots.project_roots` -- the module the gate half owns and this half extends: same
declaration file, same parser, same validation, same named refusals) and only does the
derived-artefact half:

  - build one scan over the resolved roots;
  - write it into the project's own data directory, outside every repository;
  - read it back and say which state a reader is looking at.

The derived artefacts (design goal 5)
------------------------------------
    <projects root>/<key>/data/docs/index.json      the index
    <projects root>/<key>/data/docs/entries.json    optional LLM-facing entry list
    <projects root>/<key>/data/docs/fulltext.json   optional LLM-facing full text
    <projects root>/<key>/data/docs/rebuild-failed.json   the last failed rebuild

Who writes it
-------------
The DOCUMENTATION INSPECTION pass only (`rebuild`, wired through
inspection_doc_mech.run_doc_mech's injected hook and activities.run_inspection_doc_mech).
An operator may ask for an immediate rebuild (same function, `trigger="operator"`); that
is an explicit act, never the default path. A READER never writes: `read_index` opens
files and stats pages, and nothing else -- no mkdir, no tmp file, no lock. The read path
must stay cheap and predictable, and it must never fail for reasons the reader did not
ask about.

The four reader states (design goal 6)
--------------------------------------
- `absent`  -- never built yet (`index.json` missing). The reader says so; it never
  renders the missing index as "this project has no documents".
- `stale`   -- a rebuild is due: a page is newer than the build, the roots in effect
  changed since the build (a moved root must not leave the old index looking current),
  or the index was written by another schema. The reader gets `built_at` (the time of
  the last build) and `stale_reason`, and MUST label it; the entries are returned so a
  view can show them as stale, never as current.
- `failed`  -- the last rebuild could not complete (`rebuild-failed.json` newer than the
  last successful build, an unreadable index, or a refused declaration). The reader gets
  the named reason and NO entries: the previous index is never served as if it were
  fresh.
- `current` -- nothing above; the index matches the documents that were scanned.

Categories
----------
There are no fixed category subdirectories. The scan walks each resolved root whole; a
page's category comes from its frontmatter (`category:`), falls back to its own
directory name relative to the root, then to `root`. The index lists the categories it
actually found.

Optional LLM-facing projections (design goal 12)
-----------------------------------------------
`entries` (an entry list sized for an LLM) and `fulltext` (the same pages with their
body text). Both are derived from the same scan, rebuildable, and emitted ONLY when the
project declares them in its documentation-root declaration. A project that declares
nothing gets none -- never an engine default.

Failure modes carried (review checklist)
----------------------------------------
1. Unreadable page degrades alone      -- reported in `review.unreadable`; the scan goes on.
2. Malformed frontmatter is reported   -- `review.missing_frontmatter`, never dropped.
3. Atomic write                        -- tmp file + rename in the same directory.
4. A failed rebuild is recorded        -- `rebuild-failed.json` with the reason; the old
  index is neither deleted nor served as current.
5. Stale is computed, not assumed      -- roots + page mtimes are compared on every read.
6. No writes on the read path          -- asserted by a battery that makes every writer
  raise.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import docs_roots as roots_mod  # noqa: E402

#: Artefact vocabulary (the reader and the writer share these names).
INDEX_FILE = "index.json"
FAILED_FILE = "rebuild-failed.json"
ENTRIES_FILE = "entries.json"
FULLTEXT_FILE = "fulltext.json"
SCHEMA = "v1"
#: State vocabulary a reader must be able to tell apart (design goal 6).
ST_ABSENT = "absent"
ST_CURRENT = "current"
ST_STALE = "stale"
ST_FAILED = "failed"
STATES = (ST_ABSENT, ST_CURRENT, ST_STALE, ST_FAILED)

#: `updated:` older than this many days is reported in review.stale (no block).
STALE_DAYS = 180
#: Frontmatter keys a knowledge-base page is expected to carry.
REQUIRED_KEYS = ("title", "category", "updated")
#: Epic-registry pages carry their own three keys (their state is `retired`).
EPIC_KEYS = ("code", "retired", "summary")


class DocsIndexError(Exception):
    """A rebuild that cannot complete -- always recorded with its reason."""


# ------------------------------------------------------------------ helpers

def _iso(ts: Optional[float] = None) -> str:
    if ts is None:
        return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    return datetime.fromtimestamp(ts, timezone.utc).astimezone().isoformat(timespec="seconds")


def _parse_iso(text: Any) -> Optional[float]:
    if not isinstance(text, str) or text == "":
        return None
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def parse_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    """Leading `---` frontmatter -> (fields, body). A narrow flat-key parser: enough for
    title/category/tags/status/updated and the epic keys; malformed input degrades to
    ({}, text) and the caller reports it -- never a crash."""
    if not text.startswith("---"):
        return {}, text
    lines = text.split("\n")
    end = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end = i
            break
    if end is None:
        return {}, text
    fields: Dict[str, Any] = {}
    tags: List[str] = []
    cur_key = ""
    for raw in lines[1:end]:
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        stripped = line.strip()
        if stripped.startswith("- "):
            if cur_key == "tags":
                tags.append(stripped[2:].strip().strip("'\""))
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if not key or " " in key:
            continue
        cur_key = key
        if key == "tags":
            if value.startswith("[") and value.endswith("]"):
                tags = [t.strip().strip("'\"") for t in value[1:-1].split(",") if t.strip()]
            elif value:
                tags = [t.strip().strip("'\"") for t in value.split(",") if t.strip()]
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        fields[key] = value
    if tags:
        fields["tags"] = tags
    return fields, "\n".join(lines[end + 1:]).lstrip("\n")


def _parse_date(value: Any) -> Optional[date]:
    text = str(value or "")
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _title_of(fields: Dict[str, Any], body: str, stem: str) -> str:
    title = str(fields.get("title") or "").strip()
    if title:
        return title
    for line in body.split("\n"):
        if line.startswith("# "):
            return line[2:].strip()
    return stem


def _category_of(fields: Dict[str, Any], rel: str) -> str:
    """Categories come from the document, never from a fixed directory list."""
    declared = str(fields.get("category") or "").strip()
    if declared:
        return declared
    parent = rel.rsplit("/", 1)[0] if "/" in rel else ""
    if parent:
        return parent.rsplit("/", 1)[-1]
    return "root"


def _pages_of(root: "roots_mod.DocsRoot") -> List[Path]:
    base = root.directory
    return sorted(p for p in base.rglob("*.md")
                  if p.is_file() and not any(seg.startswith(".") for seg in
                                             p.relative_to(base).parts))


def _newest_mtime(root_list: Sequence["roots_mod.DocsRoot"]) -> Optional[float]:
    newest: Optional[float] = None
    for root in root_list:
        for page in _pages_of(root):
            try:
                mtime = page.stat().st_mtime
            except OSError:
                continue
            if newest is None or mtime > newest:
                newest = mtime
    return newest


# ------------------------------------------------------------------ builder

def build(roots: "roots_mod.DocsRoots", now: Optional[float] = None) -> Dict[str, Any]:
    """One scan over the resolved roots -> the index payload (reads only).

    A resolution carrying no root raises: there is nothing to build, and building an
    empty library for a project that HAS documents is exactly the fault this change
    removes.
    """
    if not roots.roots:
        raise DocsIndexError(
            "no documentation root in effect for project %r (%s)"
            % (roots.project, roots.reason or "no root applicable"))
    today = date.today()
    review: Dict[str, Any] = {"missing_frontmatter": [], "deprecated": [], "stale": [],
                             "unreadable": [], "malformed_epics": []}
    docs: List[Dict[str, Any]] = []
    root_rows: List[Dict[str, Any]] = []
    for root in roots.roots:
        pages = _pages_of(root)
        root_rows.append({"identity": root.identity,
                          "repository": root.repository or ".",
                          "path": root.path,
                          "directory": str(root.directory),
                          "state": roots_mod.root_state(root),
                          "docs": len(pages)})
        for page in pages:
            rel = page.relative_to(root.directory).as_posix()
            try:
                text = page.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as e:
                review["unreadable"].append({"root": root.identity, "path": rel,
                                             "reason": str(e)[:200]})
                continue
            fields, body = parse_frontmatter(text)
            title = _title_of(fields, body, page.stem)
            category = _category_of(fields, rel)
            status = str(fields.get("status") or "active")
            updated = str(fields.get("updated") or "")
            tags = fields.get("tags")
            tags = [str(t) for t in tags] if isinstance(tags, list) else (
                [str(tags)] if tags else [])
            missing = [k for k in REQUIRED_KEYS if not fields.get(k)]
            is_epic = all(k in fields for k in ("code", "retired"))
            if missing and not is_epic:
                review["missing_frontmatter"].append("%s:%s" % (root.identity, rel))
            if status == "deprecated":
                review["deprecated"].append("%s:%s" % (root.identity, rel))
            parsed_updated = _parse_date(updated)
            if parsed_updated is not None and (today - parsed_updated).days > STALE_DAYS:
                review["stale"].append("%s:%s" % (root.identity, rel))
            entry: Dict[str, Any] = {
                # Identity includes repository and root (design goal 8): two roots may
                # hold the same relative path and neither may shadow the other.
                "id": "%s:%s" % (root.identity, rel),
                "root": root.identity,
                "repository": root.repository or ".",
                "root_path": root.path,
                "path": rel,
                "file": page.name,
                "title": title,
                "category": category,
                "tags": tags,
                "status": status,
                "updated": updated,
                "has_frontmatter": bool(fields),
                "bytes": len(text.encode("utf-8")),
            }
            if is_epic:
                entry["code"] = str(fields.get("code") or page.stem)
                entry["retired"] = str(fields.get("retired") or "").lower() == "true"
                entry["summary"] = str(fields.get("summary") or "")
                defects = [k for k in EPIC_KEYS if not fields.get(k)]
                if entry["code"] != page.stem:
                    defects.append("code %r is not the file stem %r"
                                   % (entry["code"], page.stem))
                if defects:
                    review["malformed_epics"].append(
                        {"root": root.identity, "path": rel, "defects": defects})
            entry["_text"] = text          # projections only; stripped before writing
            docs.append(entry)
    docs.sort(key=lambda d: (d["category"], d["root"], d["path"]))
    categories = sorted({d["category"] for d in docs})
    return {
        "schema": SCHEMA,
        "project": roots.project,
        "built_at": _iso(now),
        "built_at_ts": now if now is not None else datetime.now().timestamp(),
        "source": roots.source,
        "declaration": roots.declaration,
        "projections": list(roots.projections()),
        "roots": root_rows,
        "total": len(docs),
        "categories": categories,
        "docs": docs,
        "review": review,
    }


def _entries_projection(payload: Dict[str, Any]) -> Dict[str, Any]:
    """The LLM-facing entry list: what a model needs to choose a page, no body text."""
    return {
        "schema": SCHEMA,
        "project": payload["project"],
        "built_at": payload["built_at"],
        "total": payload["total"],
        "entries": [{"id": d["id"], "title": d["title"], "root": d["root"],
                     "repository": d["repository"], "path": d["path"],
                     "category": d["category"], "tags": d["tags"]}
                    for d in payload["docs"]],
    }


def _fulltext_projection(payload: Dict[str, Any]) -> Dict[str, Any]:
    """The LLM-facing full-text variant: the same pages with their body text."""
    return {
        "schema": SCHEMA,
        "project": payload["project"],
        "built_at": payload["built_at"],
        "total": payload["total"],
        "docs": [{"id": d["id"], "title": d["title"], "root": d["root"],
                  "repository": d["repository"], "path": d["path"],
                  "category": d["category"], "text": d.pop("_text", "")}
                 for d in payload["docs"]],
    }


def _write_json(path: Path, data: Any) -> None:
    """Atomic in-directory write (tmp + rename): a reader never sees a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("%s.tmp.%d" % (path.name, os.getpid()))
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _copy(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Shallow copy with its own doc dicts (projections pop `_text`)."""
    out = dict(payload)
    out["docs"] = [dict(d) for d in payload["docs"]]
    out["review"] = dict(payload["review"])
    return out


def _without_text(payload: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(payload)
    out["docs"] = [{k: v for k, v in d.items() if k != "_text"} for d in payload["docs"]]
    return out


def rebuild(project_key: str,
            projects_root_dir: Optional[Any] = None,
            trigger: str = "inspection",
            now: Optional[float] = None) -> Dict[str, Any]:
    """Rebuild the derived artefacts for one project (the ONLY write entry).

    Returns `{ok, state, built_at, total, roots, projections, reason}`. A failure (a
    refused declaration included) is recorded in `rebuild-failed.json` with its named
    reason and returned as `ok: False`; it is never raised at the inspection caller,
    because a documentation refresh must not take the inspection pass down with it.
    """
    target_dir = roots_mod.index_dir(project_key, projects_root_dir)
    declaration = str(roots_mod.declaration_path(project_key, projects_root_dir) or "")
    try:
        roots = roots_mod.project_roots(project_key, projects_root_dir=projects_root_dir)
        payload = build(roots, now=now)
        declared = list(roots.projections())
        payload["projections"] = declared
        payload["trigger"] = trigger
        _write_json(target_dir / INDEX_FILE, _without_text(payload))
        if "entries" in declared:
            _write_json(target_dir / ENTRIES_FILE, _entries_projection(_copy(payload)))
        elif (target_dir / ENTRIES_FILE).exists():
            (target_dir / ENTRIES_FILE).unlink()      # the declaration withdrew it
        if "fulltext" in declared:
            _write_json(target_dir / FULLTEXT_FILE, _fulltext_projection(_copy(payload)))
        elif (target_dir / FULLTEXT_FILE).exists():
            (target_dir / FULLTEXT_FILE).unlink()
        failed = target_dir / FAILED_FILE
        if failed.exists():
            failed.unlink()                           # a success supersedes the record
        return {"ok": True, "state": ST_CURRENT, "built_at": payload["built_at"],
                "built_at_ts": payload["built_at_ts"], "total": payload["total"],
                "roots": payload["roots"], "projections": declared,
                "declaration": payload["declaration"], "reason": ""}
    except Exception as e:                            # noqa: BLE001 — recorded, never fatal
        reason = (roots_mod.refusal_text(e) if isinstance(e, roots_mod.DocsRootsStop)
                  else str(e)[:500])
        code = getattr(e, "code", "docs_index_rebuild_failed")
        try:
            _write_json(target_dir / FAILED_FILE, {
                "schema": SCHEMA, "project": project_key, "failed_at": _iso(now),
                "failed_at_ts": now if now is not None else datetime.now().timestamp(),
                "trigger": trigger, "reason": reason, "code": code,
                "declaration": declaration})
        except OSError:
            pass                                      # the reason still returns to the caller
        return {"ok": False, "state": ST_FAILED, "built_at": "", "total": 0, "roots": [],
                "projections": [], "declaration": declaration, "reason": reason,
                "code": code}


# ------------------------------------------------------------------ reader

@dataclass
class IndexRead:
    """What a reader gets: the state, the build time, the reason, and (only when it is
    honest to show them) the entries."""

    state: str
    project: str
    built_at: str = ""                 # the time of the last successful build
    stale_reason: str = ""
    reason: str = ""                   # the named failure (state=failed)
    code: str = ""
    roots: List[Dict[str, Any]] = field(default_factory=list)        # as recorded
    roots_now: List[Dict[str, Any]] = field(default_factory=list)    # in effect now
    declaration: str = ""
    projection_names: List[str] = field(default_factory=list)
    payload: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "project": self.project,
            "built_at": self.built_at,
            "stale_reason": self.stale_reason,
            "reason": self.reason,
            "code": self.code,
            "declaration": self.declaration,
            "roots": self.roots,
            "roots_now": self.roots_now,
            "total": int((self.payload or {}).get("total") or 0),
            "docs": list((self.payload or {}).get("docs") or []),
            "categories": list((self.payload or {}).get("categories") or []),
            "review": dict((self.payload or {}).get("review") or {}),
            "projections": list(self.projection_names),
        }

    @property
    def entries(self) -> List[Dict[str, Any]]:
        """The entries a consumer may render -- empty when the index is absent/failed."""
        return list((self.payload or {}).get("docs") or [])


def read_index(project_key: str,
               projects_root_dir: Optional[Any] = None,
               newest_mtime: Optional[float] = None) -> IndexRead:
    """Read the derived index and state its freshness. NEVER writes (see module header).

    `newest_mtime` lets a caller that already walked the roots supply the measurement;
    when omitted this function walks them itself (reads and stats only).
    """
    target_dir = roots_mod.index_dir(project_key, projects_root_dir)
    index_path = target_dir / INDEX_FILE
    failed_path = target_dir / FAILED_FILE
    declaration = str(roots_mod.declaration_path(project_key, projects_root_dir) or "")
    roots: Optional["roots_mod.DocsRoots"] = None
    roots_error: Optional["roots_mod.DocsRootsStop"] = None
    try:
        roots = roots_mod.project_roots(project_key, projects_root_dir=projects_root_dir)
    except roots_mod.DocsRootsStop as e:
        roots_error = e
    roots_now: List[Dict[str, Any]] = []
    if roots is not None:
        roots_now = [{"identity": r.identity, "repository": r.repository or ".",
                      "path": r.path, "directory": str(r.directory),
                      "state": roots_mod.root_state(r)} for r in roots.roots]

    def refusal() -> IndexRead:
        assert roots_error is not None
        return IndexRead(state=ST_FAILED, project=project_key, declaration=declaration,
                         code=roots_error.code, reason=roots_mod.refusal_text(roots_error),
                         roots_now=roots_now)

    if not index_path.exists():
        # Two very different cases, kept apart on purpose: no index yet, and no root at
        # all. Both are "not current"; only the first is absent.
        if roots_error is not None:
            return refusal()
        return IndexRead(state=ST_ABSENT, project=project_key, declaration=declaration,
                         roots_now=roots_now)

    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("index is not a JSON object")
    except (OSError, UnicodeDecodeError, ValueError) as e:
        return IndexRead(state=ST_FAILED, project=project_key, declaration=declaration,
                         code="docs_index_unreadable", roots_now=roots_now,
                         reason="index unreadable at %s (%s)" % (index_path, str(e)[:200]))

    built_at = str(payload.get("built_at") or "")
    raw_ts = payload.get("built_at_ts")
    built_ts = float(raw_ts) if isinstance(raw_ts, (int, float)) else _parse_iso(built_at)
    projections = payload.get("projections")
    projection_names = ([str(p) for p in projections]
                        if isinstance(projections, list) else [])

    failure: Any = None
    if failed_path.exists():
        try:
            failure = json.loads(failed_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            failure = {"reason": "rebuild-failed record unreadable",
                       "code": "docs_index_failure_record_unreadable"}
    if isinstance(failure, dict):
        fail_ts = failure.get("failed_at_ts")
        if not isinstance(fail_ts, (int, float)):
            fail_ts = _parse_iso(failure.get("failed_at")) or 0.0
        if built_ts is None or float(fail_ts) >= built_ts:
            return IndexRead(state=ST_FAILED, project=project_key, built_at=built_at,
                             declaration=declaration,
                             code=str(failure.get("code") or "docs_index_rebuild_failed"),
                             roots=payload.get("roots") or [], roots_now=roots_now,
                             reason=str(failure.get("reason") or "rebuild failed"))

    if roots_error is not None:
        return refusal()

    stale_reason = ""
    if payload.get("schema") != SCHEMA:
        stale_reason = ("index schema %r is not %r — rebuild due"
                        % (payload.get("schema"), SCHEMA))
    built_roots = sorted(str(r.get("identity") or "") for r in (payload.get("roots") or []))
    now_roots = sorted(r["identity"] for r in roots_now)
    if not stale_reason and built_roots != now_roots:
        stale_reason = ("the documentation roots in effect changed since the build "
                        "(built from %s; now %s)" % (built_roots or "(none)",
                                                     now_roots or "(none)"))
    if not stale_reason:
        if newest_mtime is None:
            newest_mtime = _newest_mtime(roots.roots if roots is not None else ())
        if newest_mtime is not None and built_ts is not None and newest_mtime > built_ts:
            stale_reason = ("a document is newer than the build (page mtime %s, built %s)"
                            % (_iso(newest_mtime), built_at))
    return IndexRead(
        state=ST_STALE if stale_reason else ST_CURRENT,
        project=project_key, built_at=built_at, stale_reason=stale_reason,
        declaration=declaration, roots=payload.get("roots") or [], roots_now=roots_now,
        projection_names=projection_names, payload=payload)


# ------------------------------------------------------------------ inspection hook

def inspection_rebuild(project_key: str,
                       projects_root_dir: Optional[Any] = None) -> Dict[str, Any]:
    """The rebuild the documentation inspection calls. The returned dict goes into the
    inspection meta verbatim, so the pass records what the index state became."""
    result = rebuild(project_key, projects_root_dir, trigger="inspection")
    result["trigger"] = "inspection"
    return result


# ------------------------------------------------------------------ CLI

def main(argv: Optional[Sequence[str]] = None) -> int:
    """Operator channel: `python3 docs_index.py --project <key> [--trigger operator]`
    rebuilds one project's derived documentation artefacts, and `--state` only reads
    (the read path: it never writes). stdout is one JSON line ({ok, result|error}), the
    same contract as the engine's other CLI faces."""
    import argparse
    ap = argparse.ArgumentParser(description="derived documentation index (builder/reader)")
    ap.add_argument("--project", required=True, help="project key (registry key)")
    ap.add_argument("--projects-root", default=None,
                    help="override the per-key projects root (default: $SANDBAR_PROJECTS_DIR "
                         "or ~/.sandbar/projects)")
    ap.add_argument("--trigger", default="operator", choices=("operator", "inspection"),
                    help="who asked for the rebuild (recorded with the build)")
    ap.add_argument("--state", action="store_true",
                    help="read the index state instead of rebuilding (never writes)")
    args = ap.parse_args(list(argv) if argv is not None else None)
    try:
        if args.state:
            payload: Dict[str, Any] = {
                "ok": True,
                "result": read_index(args.project, args.projects_root).to_dict()}
        else:
            payload = {"ok": True, "result": rebuild(args.project, args.projects_root,
                                                     trigger=args.trigger)}
    except Exception as e:      # noqa: BLE001 — CLI contract: one JSON line, never a traceback
        payload = {"ok": False, "error": str(e)[:500]}
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
