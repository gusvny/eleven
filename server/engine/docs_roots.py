# -*- coding: utf-8 -*-
"""docs_roots -- ONE declaration of where a project's documentation lives, and
ONE resolution that every in-scope consumer calls.

Design: docs/design/project-docs-roots-v1.md (requirement goals 1-4, 7, 9-11;
the console documents view and the knowledge feature are the second half and
are NOT touched here).

WHY THIS MODULE EXISTS

Six readers used to decide "where are the documents" on their own, each of them
by a hard-coded directory name. Names and paths can disagree, and the
disagreement has no error path: a moved root makes five readers silently wrong.
This module is the single place that knows the rules -- the declaration, the
implied default, the three states and the refusal wording -- so a consumer can
no longer carry its own answer.

THE DECLARATION

Additive, inside the `paths:` section of the project declaration the engine
already owns (`<projects_root>/<key>/project.yaml`, the registry of
docs/design/sandbar-project-onboarding-contract-v1.md ①d):

    paths:
      docs_roots:
        - repository: .
          path: docs

  - `repository` names one repository of the project: its path relative to the
    project root (the registry entry's first `dirs` item), written the same way
    the lane derivation writes a member repository. `.` (or an empty value) is
    the project root itself -- the single-repository case.
  - `path` is the documentation root inside that repository: a relative posix
    path with no `..` segment, no leading `/`, no trailing `/`.
  - Zero entries, an absent block or an absent declaration all mean "nothing is
    declared".
  - The rule lives inside `paths:` rather than in a new top-level section on
    purpose: both registry loaders (engine shared.py and its TypeScript mirror
    server/project-registry.ts) already pass the whole `paths:` block through
    unparsed, so a project that declares documentation roots is still a
    loadable, visible project. A new top-level section would have to teach every
    reader at once (the t260928-13 outage shape).

THE THREE STATES (requirement 4), and none of them is silent

  no declaration, docs directory present -> SERVED at the implied default root
        (`<tree>/docs`). Nothing is written back: a project is never reported as
        having declared what it did not declare.
  no declaration, no docs directory      -> REFUSED: `docs_roots_absent`.
  declared and present                   -> SERVED (an existing but empty root
        is a content finding, not a configuration refusal).
  declared and absent                    -> REFUSED: `docs_roots_root_absent`.
  declared, present, unreadable          -> REFUSED: `docs_roots_root_unreadable`.
  a declaration that cannot be parsed    -> REFUSED:
        `docs_roots_declaration_malformed` / `docs_roots_duplicate` /
        `docs_roots_declaration_unreadable`.

Every refusal names the project, the declaration behind it (when there is one)
and the path that was looked for; no consumer falls back to a default
directory, and no consumer is handed an empty list for a missing root.

WHAT "THE ROOTS IN EFFECT FOR THIS TREE" MEANS

Every consumer in scope works inside ONE repository (the judged tree of a
certification, the tree a documentation inspection scans, the lane worktree a
produce instance writes into). `resolve(project, tree=...)` therefore answers
"which declared roots live in THIS repository", so a multi-repository project
works with one root or with many and a consumer in repository B never inherits
repository A's roots. Two trees are the same repository when they are the same
directory, or when git says they share a common directory (that is what makes a
lane worktree and the main checkout the same repository). A tree that cannot be
attributed answers "no declared root applies here" -- the safe direction for a
judged surface (more content judged, never less) and a named state, never a
guess.

Light-import discipline: stdlib only, no `shared` import, no temporalio -- this
face must stay importable from a bare interpreter. The registry root is read
from the same env `shared.registry_root` reads (fresh on every call, so a test
env flip takes effect).

Tests (one section per consumer, all marked t261103-11):
  - server/engine/tests/test_t260901_14_registry_loader.py -- the declaration
    truth table, the three named refusals, and every reader face that must
    tolerate the declaration;
  - server/engine/tests/test_t261016_01_baseline_reuse.py -- the judged surface
    follows the resolved roots (including the default-off control);
  - server/engine/tests/test_t261006_11_inspection_doc_mech.py -- the mechanical
    document scan follows the resolved roots;
  - server/engine/tests/test_t260925_01_produce_activity.py -- the inspection
    produce chain's root follows the resolved roots.
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---- the declaration face ---------------------------------------------------

#: The `paths:` key this face owns inside a project declaration.
SECTION_KEY = "docs_roots"
#: The fully qualified name used in refusal wording (what to go and edit).
SECTION_LABEL = "paths.%s" % SECTION_KEY
#: The implied default root: a project that declares nothing and owns this
#: directory at its repository root behaves exactly as it did before the rule.
IMPLIED_ROOT = "docs"
#: Same registry root semantics as shared.registry_root (env read fresh on
#: every call; never cached, so a test env flip takes effect).
PROJECTS_DIR_ENV = "SANDBAR_PROJECTS_DIR"
DEFAULT_HOME_DIRNAME = ".sandbar"
#: The project key whitelist (mirrors shared.PROJECT_KEY_RE: a key is a path
#: segment here, so a traversal is refused before any join happens).
PROJECT_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
#: A declared path/segment lexicon: printable path characters only.
SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-/]*$")
#: The only two keys an entry may carry.
ENTRY_KEYS = ("repository", "path")

#: The declaration is present but its shape is unusable.
STOP_DECLARATION_MALFORMED = "docs_roots_declaration_malformed"
#: The declaration file exists but cannot be read/decoded.
STOP_DECLARATION_UNREADABLE = "docs_roots_declaration_unreadable"
#: The same (repository, path) pair is declared twice.
STOP_DUPLICATE = "docs_roots_duplicate"
#: No declaration AND no documentation directory at the repository root.
STOP_ABSENT = "docs_roots_absent"
#: Declared, but the declared root does not exist.
STOP_ROOT_ABSENT = "docs_roots_root_absent"
#: Declared and present, but not a readable directory.
STOP_ROOT_UNREADABLE = "docs_roots_root_unreadable"
#: The entry names a repository that is not a directory of the project.
STOP_REPOSITORY_UNKNOWN = "docs_roots_repository_unknown"
#: A consumer that can write only one root was handed several.
STOP_ROOT_AMBIGUOUS = "docs_roots_root_ambiguous"


class DocsRootsStop(Exception):
    """A named refusal (never a fallback, never an empty answer).

    `code` is one of the STOP_* constants; `message` names the project, the
    declaration behind it (when there is one) and the path that was looked for;
    `path`/`declaration`/`project` keep the parts machine-readable."""

    def __init__(self, code: str, message: str, *, project: str = "",
                 declaration: str = "", path: str = "") -> None:
        super().__init__("%s: %s" % (code, message))
        self.code = code
        self.message = message
        self.project = project
        self.declaration = declaration
        self.path = path

    def face(self) -> Dict[str, str]:
        return {"code": self.code, "message": self.message,
                "project": self.project, "declaration": self.declaration,
                "path": self.path}


# ---- the declaration read ---------------------------------------------------

def projects_root(projects_root_dir: Optional[Any] = None) -> Path:
    """Registry root: explicit argument > $SANDBAR_PROJECTS_DIR >
    ~/.sandbar/projects. Mirrors shared.registry_root instead of importing it
    (light-import rule)."""
    if projects_root_dir is not None:
        return Path(projects_root_dir)
    env = os.environ.get(PROJECTS_DIR_ENV)
    if env:
        return Path(env)
    return Path.home() / DEFAULT_HOME_DIRNAME / "projects"


def declaration_path(project_key: str,
                     projects_root_dir: Optional[Any] = None) -> Optional[Path]:
    """`<projects_root>/<key>/project.yaml`, or None when there is no project
    context (an empty or non-whitelisted key: no declaration can exist then,
    which is "absent", not "malformed")."""
    key = str(project_key or "")
    if not PROJECT_KEY_RE.match(key):
        return None
    return projects_root(projects_root_dir) / key / "project.yaml"


def _strip_line(raw: str) -> Optional[str]:
    """Drop a trailing comment and whitespace (this registry's own convention:
    values never contain `#`). Blank/whole-line-comment yields None."""
    line = re.sub(r"#.*$", "", raw).rstrip()
    return line if line.strip() else None


def _indent(raw: str) -> int:
    return len(raw) - len(raw.lstrip(" "))


def project_root_of(text: str) -> str:
    """The registry entry's first `dirs` item (the project root, the resolution
    base of every declared repository). Same reading as
    shared._entry_paths_parse: the first absolute list item under `project:`.
    Returns "" when the entry carries none (the caller names that as
    malformed -- a declaration whose base is unknown cannot be resolved)."""
    section = ""
    for raw in str(text or "").split("\n"):
        line = _strip_line(raw)
        if line is None:
            continue
        if not raw[:1].isspace():
            m = re.match(r"^([a-z_]+):", line)
            section = m.group(1) if m else ""
            continue
        if section != "project":
            continue
        m_item = re.match(r"^\s+-\s+(.+)$", line)
        if m_item and m_item.group(1).strip().startswith("/"):
            return m_item.group(1).strip()
    return ""


def _decl_path_value(kind: str, value: str, label: str, lineno: int) -> str:
    """Validate one declared `path`/`repository` value: a relative posix path
    inside its repository; absolute, `..`, empty, trailing slash and
    non-scalar shapes are refused by name."""
    v = value.strip()
    where = "%s:%d %s" % (label, lineno, kind)
    if not v:
        raise DocsRootsStop(STOP_DECLARATION_MALFORMED,
                            "%s: empty value (a declared %s needs a path)" % (where, kind),
                            declaration=label)
    if v[:1] in "{[":
        raise DocsRootsStop(STOP_DECLARATION_MALFORMED,
                            "%s: value is not a scalar: %r" % (where, v[:40]),
                            declaration=label)
    if v.startswith(("/", "~")) or (len(v) > 1 and v[1] == ":"):
        raise DocsRootsStop(STOP_DECLARATION_MALFORMED,
                            "%s: must be relative to its repository; found an "
                            "absolute path: %r" % (where, v[:60]), declaration=label)
    if any(seg == ".." for seg in v.split("/")):
        raise DocsRootsStop(STOP_DECLARATION_MALFORMED,
                            "%s: forbids the .. escape: %r" % (where, v),
                            declaration=label)
    if v.endswith("/"):
        raise DocsRootsStop(STOP_DECLARATION_MALFORMED,
                            "%s: must not end with a slash: %r" % (where, v),
                            declaration=label)
    if v == ".":
        if kind != "repository":
            # Excluding the whole repository would judge nothing: that is the
            # false-green shape a documentation root must never take.
            raise DocsRootsStop(STOP_DECLARATION_MALFORMED,
                                "%s: a documentation root cannot be the whole "
                                "repository (%r)" % (where, v), declaration=label)
        return ""
    if "\\" in v or not SEGMENT_RE.match(v):
        raise DocsRootsStop(STOP_DECLARATION_MALFORMED,
                            "%s: not a posix path: %r" % (where, v),
                            declaration=label)
    return v


@dataclass(frozen=True)
class DocsRootEntry:
    """One declared root as written: a repository of the project and a path
    inside that repository. `repository` is "" for the project root itself."""

    repository: str
    path: str

    def face(self) -> Dict[str, str]:
        return {"repository": self.repository or ".", "path": self.path}


def parse_declaration(text: str, label: str = "project.yaml") -> Optional[List[DocsRootEntry]]:
    """Judge the `paths.docs_roots` block of one declaration text.

    Truth table: block absent -> None (nothing declared); one entry -> one root;
    several entries -> several roots; the same (repository, path) twice ->
    `docs_roots_duplicate`; any other unusable shape (unknown key, missing key,
    duplicate key, a line outside the block's grammar, a list item outside the
    block) -> `docs_roots_declaration_malformed`. A broken declaration is never
    read as "nothing declared" -- that would let a typo silently move the
    documentation root back to the default.
    """
    lines = str(text or "").split("\n")
    block: Optional[List[Tuple[int, str]]] = None
    in_paths = False
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = _strip_line(raw)
        if line is None:
            i += 1
            continue
        if not raw[:1].isspace():
            in_paths = (line == "paths:")
            i += 1
            continue
        stripped = line.strip()
        if in_paths and stripped == SECTION_KEY + ":":
            if _indent(raw) != 2:
                # The block opener must sit where every other paths key sits
                # (two spaces): one level too deep is a shape this reader cannot
                # own, so it is named instead of being ignored.
                raise DocsRootsStop(STOP_DECLARATION_MALFORMED,
                                    "%s:%d %s: must be two-space indented inside paths:"
                                    % (label, i + 1, SECTION_LABEL), declaration=label)
            if block is not None:
                raise DocsRootsStop(STOP_DECLARATION_MALFORMED,
                                    "%s:%d duplicate %s: block" % (label, i + 1, SECTION_LABEL),
                                    declaration=label)
            block = []
            i += 1
            while i < len(lines):
                inner = lines[i]
                inner_line = _strip_line(inner)
                if inner_line is None:
                    i += 1
                    continue
                if _indent(inner) <= 2:
                    break          # the next paths key closes the block
                block.append((i + 1, inner))
                i += 1
            continue
        i += 1
    if block is None:
        return None

    entries: List[DocsRootEntry] = []
    current: Dict[str, str] = {}
    current_line = 0
    seen_pairs = set()

    def flush() -> None:
        nonlocal current
        if not current and not current_line:
            return
        for key in ENTRY_KEYS:
            if key not in current:
                raise DocsRootsStop(
                    STOP_DECLARATION_MALFORMED,
                    "%s:%d an entry is missing %r (every root names its repository "
                    "and its path)" % (label, current_line, key), declaration=label)
        pair = (current["repository"], current["path"])
        if pair in seen_pairs:
            raise DocsRootsStop(
                STOP_DUPLICATE,
                "%s:%d duplicate root: repository %r path %r is declared twice"
                % (label, current_line, pair[0] or ".", pair[1]),
                declaration=label, path=pair[1])
        seen_pairs.add(pair)
        entries.append(DocsRootEntry(repository=pair[0], path=pair[1]))
        current = {}

    for lineno, raw in block:
        stripped = raw.strip()
        item = re.match(r"^-\s*([A-Za-z_]+):\s*(.*)$", stripped)
        if item:
            flush()
            current_line = lineno
            key, value = item.group(1), item.group(2)
            if key not in ENTRY_KEYS:
                raise DocsRootsStop(
                    STOP_DECLARATION_MALFORMED,
                    "%s:%d unrecognized %s entry key: %r (only %s)"
                    % (label, lineno, SECTION_LABEL, key, ", ".join(ENTRY_KEYS)),
                    declaration=label)
            current[key] = _decl_path_value(key, value, label, lineno)
            continue
        cont = re.match(r"^([A-Za-z_]+):\s*(.*)$", stripped)
        if cont and current_line:
            key, value = cont.group(1), cont.group(2)
            if key not in ENTRY_KEYS:
                raise DocsRootsStop(
                    STOP_DECLARATION_MALFORMED,
                    "%s:%d unrecognized %s entry key: %r (only %s)"
                    % (label, lineno, SECTION_LABEL, key, ", ".join(ENTRY_KEYS)),
                    declaration=label)
            if key in current:
                raise DocsRootsStop(
                    STOP_DECLARATION_MALFORMED,
                    "%s:%d duplicate %r in one entry" % (label, lineno, key),
                    declaration=label)
            current[key] = _decl_path_value(key, value, label, lineno)
            continue
        raise DocsRootsStop(
            STOP_DECLARATION_MALFORMED,
            "%s:%d %s: line is neither `- repository: ...` nor `path: ...`: %r"
            % (label, lineno, SECTION_LABEL, stripped[:60]), declaration=label)
    flush()
    if not entries:
        raise DocsRootsStop(STOP_DECLARATION_MALFORMED,
                            "%s: %s: block carries no entry (declare at least one root "
                            "or remove the block)" % (label, SECTION_LABEL),
                            declaration=label)
    return entries


# ---- the resolved roots -----------------------------------------------------

@dataclass(frozen=True)
class DocsRoot:
    """One documentation root in effect: which repository, which path, where it
    actually is. `repository` is the project-root-relative path ("" = the
    project root repository); `path` is relative to that repository."""

    repository: str
    path: str
    directory: Path
    repository_dir: Path

    def face(self) -> Dict[str, str]:
        return {"repository": self.repository or ".", "path": self.path,
                "directory": str(self.directory)}

    @property
    def rel(self) -> str:
        """The root as a repository-relative posix path (what a consumer keys
        paths on: the judged-surface exclusion, a write-set root, a scan root)."""
        return self.path


@dataclass(frozen=True)
class DocsRoots:
    """The roots in effect for one tree. `source` is "declared" or "implied"
    (the implied default is never reported as declared); `reason` is "" or a
    named state such as "declared_elsewhere"."""

    project: str
    source: str
    declaration: str
    tree: str
    roots: Tuple[DocsRoot, ...] = ()
    reason: str = ""

    def paths(self) -> Tuple[str, ...]:
        """The declared paths as repository-relative posix paths, in
        declaration order (the judged surface's exclusion key)."""
        return tuple(r.path for r in self.roots)

    def single(self) -> DocsRoot:
        """The one root for a consumer that can write exactly one (the produce
        chain). Several roots are a named refusal, never a silent pick."""
        if len(self.roots) == 1:
            return self.roots[0]
        raise DocsRootsStop(
            STOP_ROOT_AMBIGUOUS,
            "project %r declares %d documentation root(s) in this repository (%s); "
            "this consumer writes one root, so the declaration cannot pick for it"
            % (self.project or "?", len(self.roots),
               ", ".join(self.paths()) or "none applicable"),
            project=self.project, declaration=self.declaration)

    def face(self) -> Dict[str, Any]:
        return {"project": self.project, "source": self.source,
                "declaration": self.declaration, "tree": self.tree,
                "reason": self.reason,
                "roots": [r.face() for r in self.roots]}


def _repository_identity(path: Any) -> Optional[str]:
    """The repository a tree belongs to, read from git, or None when git cannot
    answer (not a repository, git absent, timeout)."""
    p = Path(path)
    try:
        r = subprocess.run(["git", "-C", str(p), "rev-parse", "--git-common-dir"],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0 or not (r.stdout or "").strip():
        return None
    raw = r.stdout.strip().splitlines()[0]
    common = Path(raw)
    if not common.is_absolute():
        common = p / common
    try:
        return str(common.resolve())
    except OSError:
        return os.path.realpath(str(common))


def _realpath(path: Any) -> str:
    try:
        return str(Path(path).resolve())
    except OSError:
        return os.path.realpath(str(path))


def same_repository(a: Any, b: Any) -> bool:
    """True when two trees belong to one repository: the same directory, or two
    worktrees that share a git common directory. A tree git cannot attribute is
    NOT the same repository (the caller then reports "no root applies here",
    which for a judged surface means more content judged, never less)."""
    if _realpath(a) == _realpath(b):
        return True
    ia, ib = _repository_identity(a), _repository_identity(b)
    return bool(ia and ib and ia == ib)


def _read_declaration(project_key: str,
                      projects_root_dir: Optional[Any]) -> Tuple[Optional[str], str]:
    """(text, label): text is None when there is no declaration file at all.
    A file that exists but cannot be read is a NAMED stop, never "absent"."""
    p = declaration_path(project_key, projects_root_dir)
    if p is None or not p.is_file():
        return None, ""
    label = str(p)
    try:
        return p.read_text(encoding="utf-8"), label
    except UnicodeDecodeError as e:
        raise DocsRootsStop(STOP_DECLARATION_UNREADABLE,
                            "%s is not UTF-8 and cannot be parsed: %s"
                            % (label, str(e)[:120]), project=str(project_key),
                            declaration=label)
    except OSError as e:
        raise DocsRootsStop(STOP_DECLARATION_UNREADABLE,
                            "%s is unreadable: %s" % (label, str(e)[:200]),
                            project=str(project_key), declaration=label)


def resolve(project_key: str, *, tree: Optional[Any] = None,
            projects_root_dir: Optional[Any] = None) -> DocsRoots:
    """Resolve the documentation roots in effect for `tree`.

    - No declaration at all (no entry, no block, or no project context): the
      implied default root `<tree>/docs`, served only when it exists and is a
      readable directory; otherwise `docs_roots_absent` names the declaration
      key and the directory that was looked for. Nothing is written back and
      nothing is reported as declared.
    - A declaration: every entry is resolved and checked (its repository is a
      directory of the project, its root exists and is a readable directory);
      the entries that live in `tree`'s repository are returned in declaration
      order. Roots declared for another repository are NOT this tree's roots --
      `reason` says "declared_elsewhere" so a consumer can name that state
      instead of rendering an empty view.
    - A malformed/unreadable declaration is a NAMED stop; it is never read as
      "nothing declared".
    """
    key = str(project_key or "")
    tree_path = Path(tree) if tree else None
    text, label = _read_declaration(key, projects_root_dir)
    main_dir = project_root_of(text) if text is not None else ""
    entries: Optional[List[DocsRootEntry]] = None
    if text is not None:
        entries = parse_declaration(text, label or "project.yaml")

    if not entries:
        base: Optional[Path] = tree_path or (Path(main_dir) if main_dir else None)
        if base is None:
            raise DocsRootsStop(
                STOP_ABSENT,
                "project %r declares no documentation root (%s) and no repository "
                "root was given to look for the implied default directory %r"
                % (key or "?", SECTION_LABEL, IMPLIED_ROOT),
                project=key, declaration=label, path=IMPLIED_ROOT)
        cand = base / IMPLIED_ROOT
        if cand.is_dir():
            root = DocsRoot(repository="", path=IMPLIED_ROOT, directory=cand,
                            repository_dir=base)
            return DocsRoots(project=key, source="implied", declaration=label,
                             tree=str(base), roots=(root,))
        raise DocsRootsStop(
            STOP_ABSENT,
            "project %r declares no documentation root (%s) and no documentation "
            "directory exists at the repository root: looked for %s"
            % (key or "?", SECTION_LABEL, cand),
            project=key, declaration=label, path=str(cand))

    if not main_dir:
        raise DocsRootsStop(
            STOP_DECLARATION_MALFORMED,
            "%s: %s is declared but the entry carries no usable first dirs item "
            "(the project root is unknown, so no declared repository can be "
            "resolved)" % (label or "project.yaml", SECTION_LABEL),
            project=key, declaration=label)

    project_root = Path(main_dir)
    resolved: List[DocsRoot] = []
    for index, entry in enumerate(entries, 1):
        repo_dir = (project_root / entry.repository) if entry.repository else project_root
        if entry.repository and not repo_dir.is_dir():
            raise DocsRootsStop(
                STOP_REPOSITORY_UNKNOWN,
                "%s: %s entry %d names repository %r, which is not a directory of "
                "the project: looked for %s"
                % (label, SECTION_LABEL, index, entry.repository, repo_dir),
                project=key, declaration=label, path=str(repo_dir))
        directory = repo_dir / entry.path
        if not directory.exists():
            raise DocsRootsStop(
                STOP_ROOT_ABSENT,
                "%s: %s entry %d declares repository %r path %r but that root does "
                "not exist: looked for %s"
                % (label, SECTION_LABEL, index, entry.repository or ".",
                   entry.path, directory),
                project=key, declaration=label, path=str(directory))
        readable = directory.is_dir() and os.access(str(directory), os.R_OK | os.X_OK)
        if not readable:
            kind = "is not a directory" if not directory.is_dir() else "is not readable"
            raise DocsRootsStop(
                STOP_ROOT_UNREADABLE,
                "%s: %s entry %d declares repository %r path %r but that root %s: "
                "looked for %s"
                % (label, SECTION_LABEL, index, entry.repository or ".",
                   entry.path, kind, directory),
                project=key, declaration=label, path=str(directory))
        resolved.append(DocsRoot(repository=entry.repository, path=entry.path,
                                 directory=directory, repository_dir=repo_dir))

    if tree_path is not None:
        applicable = tuple(r for r in resolved if same_repository(r.repository_dir, tree_path))
    else:
        applicable = tuple(resolved)
    reason = "" if applicable else "declared_elsewhere"
    return DocsRoots(project=key, source="declared", declaration=label,
                     tree=str(tree_path or ""), roots=applicable, reason=reason)


def resolve_tree(tree: Any, *, project_key: str = "",
                 projects_root_dir: Optional[Any] = None) -> DocsRoots:
    """Shorthand for a consumer that knows the tree it works in (and maybe the
    project): never a second rule set, just the same call with `tree` named."""
    return resolve(project_key, tree=tree, projects_root_dir=projects_root_dir)


def refusal_text(exc: BaseException) -> str:
    """The one-line form a consumer stamps on its record/meta: code + the
    message that names what was looked for."""
    code = getattr(exc, "code", "") or type(exc).__name__
    return "%s:%s" % (code, getattr(exc, "message", str(exc)))
