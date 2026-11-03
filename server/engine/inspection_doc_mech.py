"""inspection_doc_mech — the doc-face mechanical layer (M1-M7, t261006-11).

Successor of the retired static scanners (inspection_scan_doc.py S8/S9/S10,
t260916-22). The retired module stays untouched except for its retirement notes:
new code wires THIS module, never that one.

Position: a pure-function layer, zero temporalio dependency (same discipline as
inspection_inspect.py). The activity shell lives in activities.py
(run_inspection_doc_mech); the inspection period workflow merges these findings
into the inspect-stage payload for face=doc, so panel / report / adjudication /
dedupe keep one pipe.

Design source of truth: the 261004 doc-face inspection design draft under
notes/discussions/ (sections 2-3; the file name itself is Chinese by the notes
naming convention, so it is not spelled out here — see docs/index.json).

Rules (design section 3; severity per rule, stated once):
  M1 doc-m1-*          index three-way consistency: the DERIVED index ↔
                       the documentation root's README.md ↔ actual files
                       (page exists but unregistered / registered but file
                       gone / README leg drift / frontmatter fields missing).
                       Since t261103-17 the index leg reads the derived index
                       in the project's own data directory, resolved through
                       the ONE documentation-root resolver (docs_roots.
                       index_dir): never a copy inside a repository (design
                       project-docs-roots-v1.md goal 5). The index leg judges
                       the same states the readers distinguish (docs_index.
                       read_index): absent (a first pass, NOT a finding),
                       stale (one finding naming why a rebuild is due), failed
                       (one finding naming its reason) -- plus "unlocated" for
                       a scan that has no project key to look the artefact up
                       with. None of them ever reads as "this page is
                       unregistered", and no derived state is a crash.
                       Frontmatter is
                       SCHEMA-AWARE (host ruling 261029): a page under
                       docs/epics/ is judged by the epic schema
                       (doc-m1-frontmatter-epic — required code / retired /
                       summary, code identical to the file stem, defined by
                       docs/design/epic-registry-v1.md), every other docs/ page
                       by the five knowledge-base fields (doc-m1-frontmatter).
                       A malformed epic page is a named finding, never an
                       exemption. The README leg covers the four knowledge-base
                       categories: a page registered under another index
                       category (the epic store) is catalogued by its own
                       registry, not by a README row. Severity med.
  M2 doc-m2-unreachable  referenced paths reachable — NORMATIVE face only
                       (docs/README.md, docs/reference/*, docs/ops/*,
                       testing-guide.md, terminology.md). Only explicit shapes:
                       markdown links and backtick paths with known suffixes;
                       never prose guessing. Severity med.
  M3 doc-m3-language   language discipline on NEW lines only (diff-fed):
                       docs/ added lines must not carry CJK (two declared
                       exceptions: terminology.md, writing-standard.md);
                       notes/ added prose lines must not be CJK-free (the
                       controlled-Chinese face). Existing text is never judged.
                       Shape checks skip fenced code blocks and inline code
                       spans. Severity med.
  M4 doc-m4-progress-list  progress/todo/ticket-list content written into
                       docs/ pages (task checkboxes, or one line listing >=3
                       distinct ticket ids) — a discipline violation (a ledger
                       in a document is a dead ledger). notes/ is exempt (it is
                       the scratchpad by design). Severity med.
  M5 doc-m5-*          references named on NEW lines must exist: ticket ids
                       (t<6d>-<n>), commit-like 40-hex tokens, backtick file
                       refs. Existence predicates are injected; when the caller
                       supplies none, the check degrades with a meta note
                       (never a silent green). Severity med.
  M6 doc-m6-supersede  a docs/design page whose frontmatter status is
                       deprecated must carry a superseded-by pointer. Severity
                       med.
  M7 doc-m7-*          code-change surface ↔ documents, both directions:
                       (a) every changed code file mentioned by some library
                       page yields a doc-m7-must-check POINTER finding for the
                       agent layer (severity low — it is a pointer, not a
                       defect); (b) a changed page naming a code surface must
                       have that surface still existing (explicit backtick
                       shapes only; severity med).

False-positive governance (design section 3, all three mandatory):
  1. Narrow by class: docs/design (historical face) is exempt from path drift
     (M2 / M5 file refs); notes/ is exempt from M4.
  2. Narrow the rules: only markdown links and backtick paths with known
     suffixes. Glob-like tokens (*, {, trailing wildcard) are never treated as
     paths — the fixed S10 lesson (140-false-positive period).
  3. Explicit exemption: `<!-- doc-exempt: <rule-id> -->` anywhere in a page
     suppresses the named rule for that page (family-prefix semantics carried
     from the retired module). Every suppression is counted in
     meta.exempted — auditable, never silent.

Path resolution (fixed S10, integration-gate RC1 semantics): a referenced
path is judged by its explicit shape — a leading `/` resolves from the repo
root; an explicit `./`/`../` token resolves from the DOCUMENT'S OWN DIRECTORY;
any other slash-bearing token is checked under BOTH bases (document directory,
then repo root) and is missing only when neither exists — the library uses both
docs-relative rows (`design/x.md`) and repo-shaped paths (`src/code.py`), and a
single-base reading of either style is exactly the 140-false-positive shape; a
bare filename resolves doc-directory first with a repo-wide basename search on
top (see `_missing`).

Catalogue rows (same discipline, host ruling 261029): a docs/README.md row is
RESOLVED, never blindly prefixed with `docs/` — docs base first (the only base a
row carrying a directory component is written against), then the repository
root, then a unique basename match under docs/ for a bare file name (see
`_resolve_row`). A row that resolves to an existing file outside docs/ is a
non-library reference, not a catalogue row; a row that resolves nowhere keeps
the docs/-relative form so the missing-row finding still fires.

Output shape: identical to agent findings (inspection_inspect.py) —
subject / severity / evidence[{path,line,quote}] / why / suggestion, id minted
by the same mint_finding_id (content hash, stable across periods), scan =
rule id. Narrative fields (subject/why/suggestion) are English by the 260930
report-language gate; the quote is verbatim data.

Failure-mode checklist (carried from the retired module's C1 list, per item):
   1 repo-root missing fail-closed        → carried (run_doc_mech raises DocMechError).
   2 unreadable item degrades alone       → carried (meta.unreadable, never crashes the scan).
   3 malformed structured input degrades  → carried (bad index.json / bad frontmatter → per-item finding or note, no fake green).
   4 single-line JSON CLI contract        → carried ({ok, result|error}).
   5 zero findings = heartbeat            → carried (meta.heartbeat).
   6 pure read, zero writes               → carried.
   7 never executes the scanned object    → carried (docs are text+JSON).
   8 false-positive flood gate            → carried (explicit exemption comments + narrow shapes, both above).
   9 static surface never certifies high  → carried (med only, except the M7 low pointers).
  10 lexical constants at the top         → carried (any change ships with a truth-table UT).
  11 deterministic ordering               → carried (severity → scan → subject).
  12 stable finding ids across periods    → carried (mint_finding_id, no timestamps).
  13 meta records scope limits            → carried (meta.caveats).
Not carried: S1-S4 surfaces, the retired CLI surface, deadman wiring (retired
scope; the old module remains legacy-replay-only).

Waiting on open host decisions (NOT invented here): (a) exemption form beyond
the in-comment one (class whitelist) — collect_exemptions is the extension
point; (b) whether mechanical findings get the same per-item false-report
adjudication — they flow into the verdict pipe unchanged, separable by the
scan tag.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from inspection_inspect import mint_finding_id  # noqa: E402  (single id mint)

# ---- lexical constants (top of file; any change ships with a truth-table UT) ----
# DOC_ROOT is the IMPLIED default documentation root only: since t261103-11 the
# root a scan walks is a parameter (resolved from the project's ONE documentation
# root declaration by docs_roots.resolve), and every rule below takes that root.
# The constant keeps the pre-declaration behaviour byte for byte for a project
# that declares nothing and owns docs/.
DOC_ROOT = "docs"
DESIGN_SUB = "docs/design"
EPICS_SUB = "docs/epics"
NOTES_ROOT = "notes"
REQUIRED_FIELDS = ("title", "category", "tags", "status", "updated")   # carried S9
CATEGORIES = ("design", "content", "ops", "reference")
STATUSES = ("active", "draft", "deprecated")
#: the epic store keeps its OWN frontmatter schema (docs/design/epic-registry-v1.md,
#: host ruling 261029): one boolean of state, a code identical to the file stem and
#: a one-sentence summary. The five knowledge-base fields do not apply to it, and
#: the epic schema is not widened onto the rest of the library either.
EPIC_REQUIRED_FIELDS = ("code", "retired", "summary")
EPIC_BOOL_VALUES = ("true", "false")
#: index categories outside the knowledge-base four. A page registered there is
#: catalogued by its own store, not by the docs/README.md rows (the README lists
#: design/content/ops/reference pages; the epics are one file per code, listed by
#: the epic registry and the Docs tab group).
NON_CATALOGUE_CATEGORIES = ("epics",)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SEVERITY = "med"          # M1-M6: static surfaces never certify high (C1 item 9)
SEVERITY_M7_PTR = "low"   # M7(a) pointer findings only

RULE_M1_INDEX = "doc-m1-index"              # index leg drift (unregistered / ghost)
RULE_M1_README = "doc-m1-readme"            # README leg drift
RULE_M1_FRONTMATTER = "doc-m1-frontmatter"  # frontmatter five fields
RULE_M1_FRONTMATTER_EPIC = "doc-m1-frontmatter-epic"  # the docs/epics schema
RULE_M2 = "doc-m2-unreachable"
RULE_M3_DOCS = "doc-m3-language-docs"
RULE_M3_NOTES = "doc-m3-language-notes"
RULE_M4_CHECKBOX = "doc-m4-progress-list"
RULE_M4_TICKETS = "doc-m4-ticket-list"
RULE_M5_TICKET = "doc-m5-ticket"
RULE_M5_COMMIT = "doc-m5-commit"
RULE_M5_FILE = "doc-m5-file"
RULE_M6 = "doc-m6-supersede"
RULE_M7_PTR = "doc-m7-must-check"
RULE_M7_STALE = "doc-m7-stale"

# ---- t261103-17: the index leg reads the DERIVED index --------------------
# The index leg never reads `<repository>/<root>/index.json` any more: a copy of the
# index inside a repository is not the truth (design project-docs-roots-v1.md goal 5).
# It reads the derived index in the project's own data directory, resolved through the
# ONE documentation-root resolver (`docs_roots.index_dir`), and judges the states the
# readers already distinguish (`docs_index.read_index`): absent / stale / failed /
# current. `unlocated` is this scanner's own state for a pass that has no project key,
# so the artefact cannot be looked up at all -- a named state, never a silent green
# and never a crash.
INDEX_STATE_UNLOCATED = "unlocated"
#: The derived index states that are NOT a finding about any page (design goal 6).
INDEX_STATES_QUIET = (INDEX_STATE_UNLOCATED, "absent")

# M2 explicit path shapes (carried S10, narrowed): backtick or markdown-link
# token, with a slash or a known suffix; globs and URLs never count.
KNOWN_SUFFIX_RE = r"\.(?:py|mjs|ts|tsx|js|sh|md|ya?ml|json)\b"
_MD_LINK_RE = re.compile(r"\]\(([^)\s]+)\)")
_BACKTICK_RE = re.compile(r"`([^`\n]+)`")
_PATHISH_RE = re.compile(
    r"(?<![\w/\-.])(?:\.\./|\./|/)?"
    r"[A-Za-z0-9_][\w\-./]*?" + KNOWN_SUFFIX_RE)
_URL_RE = re.compile(r"^[a-z][a-z0-9+.\-]*:|^//|^#")
_GLOBISH_RE = re.compile(r"[*{}?]|\*$")
#: template placeholders ($VAR/path, <dir>/file) are not literal paths — the
#: docs use them to describe shapes, never to reference a real file.
_PLACEHOLDER_RE = re.compile(r"[$<>|]")
_TICKET_RE = re.compile(r"\bt\d{6}-\d{1,2}\b")
_COMMIT_RE = re.compile(r"\b[0-9a-f]{40}\b")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_CHECKBOX_RE = re.compile(r"^\s*[-*]\s\[[ xX]\]")
_SUPERSEDE_RE = re.compile(r"superseded[- ]by", re.IGNORECASE)
_EXEMPT_RE = re.compile(r"doc-exempt:\s*([^\n>]*)")
_EXEMPT_TOK_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-]*$")

#: normative-face pages for M2/M5-file (design section 2: the pages that must
#: match reality). Everything else under docs/ (design/, others) is historical
#: or out of the path-drift class.
_NORMATIVE_EXACT = ("docs/README.md", "docs/testing-guide.md", "docs/terminology.md")
_NORMATIVE_PREFIX = ("docs/reference/", "docs/ops/")
#: M3 declared language exceptions (docs/ pages allowed to carry Chinese by design)
_M3_DOCS_EXEMPT = ("docs/terminology.md", "docs/writing-standard.md")
#: the same exceptions written relative to the documentation root in effect.
_M3_DOCS_EXEMPT_REL = tuple(x[len(DOC_ROOT) + 1:] if x.startswith(DOC_ROOT + "/") else x
                            for x in _M3_DOCS_EXEMPT)

MAX_EVIDENCE_QUOTES = 5   # evidence cap per finding (long lists stay readable)
MAX_M7_PTR = 40           # pointer findings cap (same order as the agent budget)


class DocMechError(Exception):
    """Fail-closed scan error (repo root missing, etc.)."""


# ========================================================================
# small pure helpers
# ========================================================================

def _norm_slash(p: str) -> str:
    return str(p).replace("\\", "/")


#: The normative-face shapes, written relative to the documentation root (so a
#: declared root keeps its own normative face instead of silently having none).
_NORMATIVE_REL_EXACT = tuple(x[len(DOC_ROOT) + 1:] if x.startswith(DOC_ROOT + "/") else x
                             for x in _NORMATIVE_EXACT)
_NORMATIVE_REL_PREFIX = tuple(x[len(DOC_ROOT) + 1:] if x.startswith(DOC_ROOT + "/") else x
                              for x in _NORMATIVE_PREFIX)


def _root_rel(rel: str, root: str):
    """`rel` relative to the documentation root in effect, or None when the page
    is not inside that root."""
    rel = _norm_slash(rel)
    return rel[len(root.rstrip("/")) + 1:] if rel.startswith(root.rstrip("/") + "/") else None


def _is_normative(rel: str, root: str = DOC_ROOT) -> bool:
    """A normative-face page (the pages that must match reality)."""
    sub = _root_rel(rel, root)
    if sub is None:
        return False
    return sub in _NORMATIVE_REL_EXACT or any(sub.startswith(p)
                                              for p in _NORMATIVE_REL_PREFIX)


def _is_docs(rel: str, root: str = DOC_ROOT) -> bool:
    return _norm_slash(rel).startswith(root.rstrip("/") + "/")


def _is_epic_page(rel: str, root: str = DOC_ROOT) -> bool:
    """A page under <root>/epics/ is an EPIC record: judged by the epic schema."""
    return _norm_slash(rel).startswith(root.rstrip("/") + "/epics/")


def _non_catalogue_page(rel: str, indexed_category: str,
                        root: str = DOC_ROOT) -> bool:
    """True when a page is NOT a <root>/README.md catalogue row: it lives in the
    epic store, or the index registers it under a non-catalogue category. The
    README catalogue covers the four knowledge-base categories only."""
    return _is_epic_page(rel, root) or indexed_category in NON_CATALOGUE_CATEGORIES


def _is_url_or_anchor(tok: str) -> bool:
    return bool(_URL_RE.match(tok)) or ":" in tok.split("/")[0]


def extract_paths(text: str) -> List[Tuple[str, int]]:
    """Explicit path shapes only: markdown links then backtick tokens. Glob-like
    tokens and URLs/anchors are dropped (the fixed S10 discipline). Returns
    (token, offset) pairs in document order."""
    out: List[Tuple[str, int]] = []
    for m in _MD_LINK_RE.finditer(text):
        tok = m.group(1).split("#")[0]
        if tok and not _is_url_or_anchor(tok) and not _GLOBISH_RE.search(tok) \
                and not _PLACEHOLDER_RE.search(tok):
            out.append((tok, m.start()))
    for m in _BACKTICK_RE.finditer(text):
        tok = m.group(1).strip()
        if not tok or " " in tok or "\t" in tok:
            continue        # a backtick command line (`python3 x.py run`) is not a path ref
        if tok.startswith("/") or "/" in tok or re.search(KNOWN_SUFFIX_RE, tok):
            if not _is_url_or_anchor(tok) and not _GLOBISH_RE.search(tok) \
                    and not _PLACEHOLDER_RE.search(tok) and _PATHISH_RE.search(tok):
                out.append((tok, m.start()))
    return out


def _strip_inline_code(line: str) -> str:
    return re.sub(r"`[^`]*`", "``", line)


def _fence_state_iter(lines: Iterable[str]) -> Iterable[Tuple[int, str, bool]]:
    """Yield (lineno, line, in_fence) for each line, tracking ``` fences."""
    fence = False
    for i, line in enumerate(lines, start=1):
        if line.lstrip().startswith("```"):
            yield i, line, fence
            fence = not fence
            continue
        yield i, line, fence


def parse_frontmatter(text: str) -> Tuple[Dict[str, Any], bool]:
    """Leading YAML frontmatter → (fields, well_formed_block). Deliberately a
    narrow parser: only what M1 needs (five flat fields); a list item under
    `tags:` counts as non-empty. Malformed input degrades to
    well_formed_block=False (M1 reports it), never raises."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, False
    fields: Dict[str, Any] = {}
    closed = False
    cur_key = ""
    for line in lines[1:]:
        if line.strip() == "---":
            closed = True
            break
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[:1] in (" ", "-", "\t"):          # continuation / list item
            if cur_key == "tags" and line.lstrip().startswith("- "):
                fields.setdefault("tags", [])
                if isinstance(fields["tags"], list):
                    fields["tags"].append(line.lstrip()[2:].strip())
            continue
        m = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", line)
        if not m:
            continue
        cur_key = m.group(1)
        val = m.group(2).strip().strip("'\"")
        if cur_key == "tags" and not val:
            fields[cur_key] = []            # list-form tags: items follow on `- ` lines
        elif cur_key == "tags" and val.startswith("[") and val.endswith("]"):
            fields[cur_key] = [t.strip() for t in val[1:-1].split(",") if t.strip()]
        elif cur_key == "tags" and val:
            fields[cur_key] = [val]
        else:
            fields[cur_key] = val
    return fields, closed


def frontmatter_defects(fields: Dict[str, Any], well_formed: bool) -> List[str]:
    """Five-field legality (carried S9). Returns human-readable defect tokens."""
    if not well_formed:
        return ["missing or unterminated frontmatter block"]
    out: List[str] = []
    for key in REQUIRED_FIELDS:
        val = fields.get(key)
        if key == "tags":
            if not val or not isinstance(val, list):
                out.append("tags empty")
            continue
        if not val:
            out.append("%s empty" % key)
            continue
        if key == "category" and val not in CATEGORIES:
            out.append("category %r not in %s" % (val, ",".join(CATEGORIES)))
        if key == "status" and val not in STATUSES:
            out.append("status %r not in %s" % (val, ",".join(STATUSES)))
        if key == "updated" and not DATE_RE.match(str(val)):
            out.append("updated %r not YYYY-MM-DD" % val)
    return out


def epic_frontmatter_defects(fields: Dict[str, Any], well_formed: bool,
                             rel: str) -> List[str]:
    """Epic-schema legality for a docs/epics/ page (epic-registry-v1, host ruling
    261029). Returns human-readable defect tokens; an empty list means the page
    satisfies the schema it is registered under. A malformed epic page is a
    NAMED finding here — the directory is judged, never exempted."""
    if not well_formed:
        return ["missing or unterminated frontmatter block"]
    out: List[str] = []
    for key in EPIC_REQUIRED_FIELDS:
        if not fields.get(key):
            out.append("%s empty" % key)
    code = str(fields.get("code") or "")
    stem = Path(_norm_slash(rel)).stem
    if code and code != stem:
        out.append("code %r does not match the file stem %r" % (code, stem))
    retired = str(fields.get("retired") or "").lower()
    if retired and retired not in EPIC_BOOL_VALUES:
        out.append("retired %r not true/false" % fields.get("retired"))
    return out


def collect_exemptions(text: str) -> set:
    """`doc-exempt: <rule-id...>` family-prefix exemption set (carried S8/S9/S10
    exempt_rules; the extension point for a future class whitelist)."""
    out: set = set()
    for m in _EXEMPT_RE.finditer(text):
        for tok in m.group(1).replace(",", " ").split():
            tok = tok.strip()
            if tok and _EXEMPT_TOK_RE.match(tok):   # "--" / comment debris never counts
                out.add(tok)
    return out


def _exempted(rules: set, rule: str) -> bool:
    return any(rule == r or rule.startswith(r + "-") or r.startswith(rule) for r in rules)


# ========================================================================
# finding minting (agent shape, single-sourced id)
# ========================================================================

def _finding(rule: str, subject: str, path: str, line: int, quote: str,
             why: str, suggestion: str, severity: str = SEVERITY) -> Dict[str, Any]:
    f = {
        "scan": rule,
        "severity": severity,
        "subject": subject,
        "evidence": [{"path": path, "line": line, "quote": quote[:200]}],
        "why": why,
        "suggestion": suggestion,
    }
    f["id"] = mint_finding_id(f)
    return f


def _cap_quotes(findings: List[Dict[str, Any]]) -> None:
    for f in findings:
        f["evidence"] = f["evidence"][:MAX_EVIDENCE_QUOTES]


# ========================================================================
# rules
# ========================================================================

def _read_pages(repo: Path, root: str = DOC_ROOT) -> Tuple[List[str], List[str]]:
    """All library pages (<root>/ + notes/) as (rel, text). Unreadable files
    degrade alone (C1 item 2). `root` is the documentation root in effect for
    this scan (the declared one, or the implied default)."""
    rels: List[str] = []
    unreadable: List[str] = []
    for rel_root in (root.rstrip("/") or DOC_ROOT, NOTES_ROOT):
        base = repo / rel_root
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.md")):
            rel = _norm_slash(p.relative_to(repo))
            rels.append(rel)
    return rels, unreadable


def _read_text(repo: Path, rel: str) -> Optional[str]:
    try:
        return (repo / rel).read_text("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _resolve(repo: Path, doc_rel: str, tok: str) -> Optional[Path]:
    """FIXED S10 resolution (deterministic, shape-based; integration-gate RC1
    semantics — the gate OVERRIDES the earlier single-base review pin):
      - a leading `/` resolves from the repo root;
      - an explicit `./`/`../` token resolves from the DOCUMENT'S OWN DIRECTORY
        (an explicit relative shape is a doc-relative claim);
      - any other slash-bearing token is checked against BOTH bases in a fixed
        order (document directory first, then repo root) and is MISSING only
        when it exists under neither — the library uses both `design/x.md`
        (docs-relative, docs/README.md rows) and `src/code.py` (repo-shaped)
        styles, and a single-base reading of either style is exactly the
        140-false-positive shape;
      - a bare filename (no slash) resolves from the document directory;
        `_missing` adds the repo-wide basename search on top of it.
    Returns the resolved path (None when out of bounds); reachability is
    decided by `_missing`, which needs both candidates for slash tokens."""
    tok = _norm_slash(tok)
    if tok.startswith("/"):
        return (repo / tok.lstrip("/")).resolve()
    cand = (repo / doc_rel).parent / tok
    if tok.startswith("./") or tok.startswith("../") or "/" not in tok:
        try:
            return cand.resolve()
        except OSError:
            return None
    return cand            # slash token: caller checks both bases via _missing


def _missing(repo: Path, doc_rel: str, tok: str, bare_index: Optional[set]) -> bool:
    """True when the referenced path does not exist. Slash tokens (non-relative,
    non-absolute) are checked under BOTH bases (document directory, then repo
    root) and fire only when neither exists; bare filenames get one extra
    deterministic fallback — if ANY file in the repo carries that basename, the
    reference is reachable by name. No other guessing (fixed S10)."""
    tok = _norm_slash(tok)
    if tok.startswith("/") or tok.startswith("./") or tok.startswith("../") \
            or "/" not in tok:
        target = _resolve(repo, doc_rel, tok)
        if target is not None and target.exists():
            return False
        if "/" not in tok and bare_index is not None:
            return Path(tok).name not in bare_index
        return True
    # slash token, no explicit relative marker: both bases, fixed order
    doc_base = (repo / doc_rel).parent / tok
    if doc_base.exists() or (repo / tok).exists():
        return False
    return True


def rule_m1(repo: Path, pages: Dict[str, str], index: Any,
            readme_rels: set, all_rels: List[str], exempts: Dict[str, set],
            root: str = DOC_ROOT, index_state: str = "current",
            index_reason: str = "", index_built_at: str = "",
            index_path: str = "") -> List[Dict[str, Any]]:
    """M1 three-way: derived index ↔ README ↔ actual files + frontmatter (S9 carried).

    `root` is the documentation root in effect (the README lives inside it); `index`
    holds the derived index rows of THIS root, selected by the caller from the derived
    index in the project data directory. `index_state` is the state the derived-index
    reader reports (`docs_index.read_index`), and it decides what may be judged:

      current   -- the rows are compared against the files (the three-way check);
      absent    -- the index was never built (a first pass): NOT a finding, and no
                   page is reported unregistered;
      stale     -- ONE finding names why a rebuild is due and the time of the last
                   build; the old rows are never compared as if they were current;
      failed    -- ONE finding names the reason; no page is reported unregistered;
      unlocated -- this pass has no project key, so the derived index cannot be looked
                   up: no finding, and the caller names the state in a caveat.

    The index-independent leg (a catalogue row that names a file that does not exist)
    and the frontmatter checks are judged in every state.

    Wording: the implied default root keeps the sentences this check has always used
    (design goal 3: an undeclared project's verdicts stay byte for byte today's, ids
    included). A DECLARED root names itself -- its own README path and its own derived
    index -- so a moved root is never described with the default directory name.
    """
    default = root.rstrip("/") == DOC_ROOT
    index_label = "docs/index.json" if default else "the derived index (%s)" % (
        index_path or root)
    catalogue = "docs/README.md" if default else "%s/README.md" % root
    out: List[Dict[str, Any]] = []
    if index_state == "failed":
        out.append(_finding(
            RULE_M1_INDEX,
            "the derived documentation index is not usable: %s"
            % (index_reason or "the last rebuild did not complete"),
            index_path or root, 1, (index_reason or "")[:200],
            "The derived index lives in the project data directory, outside every "
            "repository, and the index leg of the three-way check needs it. The "
            "recorded reason is: %s. No page is reported unregistered while the index "
            "is unusable: a failure of the index is never a finding about a document."
            % (index_reason or "not recorded"),
            "Fix the cause named in this finding (design docs/design/"
            "project-docs-roots-v1.md goal 6), then re-run. The next documentation "
            "inspection pass rebuilds the index; an operator may rebuild it now: "
            "python3 server/engine/docs_index.py --project <project key>."))
    elif index_state == "stale":
        out.append(_finding(
            RULE_M1_INDEX,
            "the derived documentation index is stale: a rebuild is due (%s)"
            % (index_reason or "a document changed after the last build"),
            index_path or root, 1,
            "last built %s" % (index_built_at or "at an unrecorded time"),
            "The derived index was last built at %s and no longer matches the "
            "documents. Its rows are not compared against the files as if they were "
            "current: a page added since the build would otherwise read as "
            "unregistered." % (index_built_at or "an unrecorded time"),
            "The documentation inspection rebuilds the index in its own periodic "
            "pass; an operator may rebuild it now: python3 server/engine/"
            "docs_index.py --project <project key>."))
    indexed = set()
    indexed_category: Dict[str, str] = {}
    if index_state == "current" and isinstance(index, dict):
        for d in index.get("docs") or []:
            if isinstance(d, dict) and d.get("path"):
                # Derived rows are root-relative ("design/x.md"); normalize to
                # repo-relative so they compare against the actual-file set.
                p = _norm_slash(str(d["path"])).lstrip("./")
                rel = p if p.startswith(root + "/") else root + "/" + p
                indexed.add(rel)
                indexed_category[rel] = str(d.get("category") or "")
    actual = {r for r in all_rels if _is_docs(r, root)}
    # file vs index (only when the index is current: see the state table above)
    if index_state == "current":
        for rel in sorted(actual - indexed):
            if _exempted(exempts.get(rel, set()), RULE_M1_INDEX):
                continue
            out.append(_finding(
                RULE_M1_INDEX,
                "page exists but is not registered in %s" % index_label,
                rel, 1,
                (pages.get(rel) or "").splitlines()[0][:200] if pages.get(rel) else "",
                ("The page exists under docs/ but the machine index has no entry for "
                 "it; plugins and agents consume the index.") if default else (
                 "The page exists under %s/ but the derived index has no entry for it; "
                 "the console and the agents read that index." % root),
                "Register the page (python3 docs/scripts/build_index.py) or move it "
                "out of docs/." if default else (
                 "Rebuild the derived index (the next documentation inspection pass, "
                 "or python3 server/engine/docs_index.py --project <project key>) or "
                 "move the page out of %s/." % root)))
        for rel in sorted(indexed - actual):
            if _exempted(exempts.get(rel, set()), RULE_M1_INDEX):
                continue
            out.append(_finding(
                RULE_M1_INDEX, "index entry points at a file that does not exist",
                ("docs/index.json" if default else (index_path or root)), 1, rel,
                ("docs/index.json registers %s but no such file exists — a ghost "
                 "entry." % rel) if default else (
                 "The derived index registers %s but no such file exists — a ghost "
                 "entry." % rel),
                "Remove the ghost entry (rebuild the index) or restore the file."))
    # README leg (narrowed by class: the catalogue lists the knowledge-base
    # categories. A page registered under another category — the epic store, one
    # file per code — is catalogued by its own registry, so its absence from the
    # README rows is not drift).
    for rel in sorted((actual & indexed) - readme_rels):
        if _non_catalogue_page(rel, indexed_category.get(rel, ""), root):
            continue
        if _exempted(exempts.get(rel, set()), RULE_M1_README):
            continue
        out.append(_finding(
            RULE_M1_README,
            ("page registered in index.json but missing from docs/README.md catalogue"
             if default else "page registered in the derived index but missing from "
                             "the %s/README.md catalogue" % root),
            catalogue, 1, rel,
            ("The human-readable catalogue (%s) does not list a page that exists and "
             "is indexed — the third leg of the three-way check." % catalogue),
            "Add a catalogue row in the matching category section of %s." % catalogue))
    for rel in sorted(readme_rels - actual):
        if _exempted(exempts.get(rel, set()), RULE_M1_README):
            continue
        out.append(_finding(
            RULE_M1_README, "catalogue row names a file that does not exist at that path",
            catalogue, 1, rel,
            "%s lists %s but the file is not there (moved or gone)."
            % (catalogue, rel),
            "Fix the catalogue path or restore the file."))
    # frontmatter (S9 carried; schema-aware since 261029 — docs/epics/ is judged
    # by the epic schema, everything else by the five knowledge-base fields)
    for rel in sorted(actual):
        text = pages.get(rel)
        if text is None:
            continue
        fields, well = parse_frontmatter(text)
        if _is_epic_page(rel, root):
            defects = epic_frontmatter_defects(fields, well, rel)
            rule = RULE_M1_FRONTMATTER_EPIC
            why = ("A docs/epics/ page carries the epic schema — required code / retired "
                   "/ summary, and code identical to the file stem "
                   "(docs/design/epic-registry-v1.md).")
        else:
            defects = frontmatter_defects(fields, well)
            rule = RULE_M1_FRONTMATTER
            why = ("Every other docs/ page carries YAML frontmatter with title/category/"
                   "tags/status/updated (docs/README.md maintenance conventions).")
        if defects and not _exempted(exempts.get(rel, set()), rule):
            out.append(_finding(
                rule, ("frontmatter epic-schema check failed: " if _is_epic_page(rel, root)
                       else "frontmatter five-field check failed: ") + "; ".join(defects),
                rel, 1, text.splitlines()[0][:200],
                why,
                "Add or fix the frontmatter fields listed in the subject."))
    return out


def _build_bare_index(repo: Path) -> set:
    out = set()
    for p in repo.rglob("*"):
        if p.is_file():
            out.add(p.name)
    return out


# ---- the derived index (t261103-17) ---------------------------------------

@dataclass(frozen=True)
class DerivedIndex:
    """What ONE read of the derived documentation index says (read-only).

    `state` is one of docs_index STATES (`current` / `absent` / `stale` / `failed`) or
    this scanner's `unlocated`; `payload` holds the built index (rows are selected per
    scanned root by `_entries_of_root`)."""

    state: str = INDEX_STATE_UNLOCATED
    path: str = ""
    built_at: str = ""
    reason: str = ""
    code: str = ""
    declaration: str = ""
    payload: Optional[Dict[str, Any]] = None

    @property
    def judged(self) -> bool:
        """True only for a current index: the rows may be compared with the files."""
        return self.state == "current"

    def face(self) -> Dict[str, Any]:
        return {"state": self.state, "path": self.path, "built_at": self.built_at,
                "reason": self.reason, "code": self.code,
                "declaration": self.declaration}


def _read_derived_index(project_key: str,
                        projects_root_dir: Optional[Any] = None) -> DerivedIndex:
    """Read the derived index for ONE project. Never writes, never raises.

    The location comes from the ONE resolver (`docs_roots.index_dir`): the project's
    data directory, outside every repository. A pass with no project key cannot name
    that directory at all, and says so as `unlocated` instead of guessing a path inside
    the repository (design goal 5: a copy inside a repository is never the truth).
    """
    key = str(project_key or "")
    if not key:
        return DerivedIndex(
            state=INDEX_STATE_UNLOCATED,
            reason="no project key was supplied, so the derived documentation index "
                   "(a per-project artefact in the project data directory) cannot be "
                   "located: the index leg of M1 is not judged this period")
    import docs_index
    import docs_roots
    try:
        path = str(docs_roots.index_dir(key, projects_root_dir))
    except docs_roots.DocsRootsStop as e:
        return DerivedIndex(state=INDEX_STATE_UNLOCATED,
                            reason=docs_roots.refusal_text(e), code=e.code)
    try:
        read = docs_index.read_index(key, projects_root_dir)
    except Exception as e:      # noqa: BLE001 — a reader never takes the scan down
        return DerivedIndex(state="failed", path=path,
                            code="docs_index_read_failed", reason=str(e)[:300])
    if read.state == "failed" and read.code == docs_roots.STOP_ABSENT:
        # A project that declares nothing AND whose registry entry cannot name its
        # project root has no derivable index home. Nothing failed and nothing was
        # built: the artefact is unlocated (the scan root itself came from the tree).
        return DerivedIndex(state=INDEX_STATE_UNLOCATED, path=path, code=read.code,
                            reason=read.reason, declaration=read.declaration)
    return DerivedIndex(state=read.state, path=path, built_at=read.built_at,
                        reason=read.stale_reason or read.reason, code=read.code,
                        declaration=read.declaration, payload=read.payload)


def _built_dirs(derived: DerivedIndex) -> str:
    """The tree(s) the read index was built from, as recorded in its own rows."""
    dirs = sorted({str(r.get("directory") or "") for r
                   in ((derived.payload or {}).get("roots") or [])
                   if r.get("directory")})
    return ", ".join(dirs)


def _index_matches_tree(derived: DerivedIndex, repo: Path,
                        roots: Sequence[Tuple[str, Optional[str]]]) -> bool:
    """True when the read index was built from the tree this scan walks.

    An index built elsewhere (a lane worktree scanning an index built from the main
    checkout) is still a current index -- for ITS tree. The answer is used to NAME that
    condition in a caveat, never to change a verdict (the row comparison stays the same
    rule for every tree)."""
    built = {str(Path(str(r.get("directory"))).resolve())
             for r in ((derived.payload or {}).get("roots") or [])
             if r.get("directory")}
    if not built:
        return True                      # nothing recorded: nothing to compare
    walked = {str((Path(repo) / root).resolve()) for root, _ident in roots}
    return bool(built & walked)


def _entries_of_root(derived: DerivedIndex, root: str,
                     identity: Optional[str]) -> Optional[Dict[str, Any]]:
    """The derived index rows that belong to ONE scanned root.

    Rows carry a root identity (repository + declared path, design goal 8), so a
    multi-root project never mixes two roots into one comparison. An ops caller that
    supplied the root by argument has no identity, and its rows fall back to the
    declared path. None when the index is not current (nothing may be compared).
    """
    if not derived.judged:
        return None
    payload = derived.payload or {}
    rows: List[Dict[str, str]] = []
    # A row with no root field can only be described by an index that holds one root;
    # such a row is still compared (a hand-edited row must not vanish from the check).
    single_root_index = len(payload.get("roots") or []) <= 1
    for d in (payload.get("docs") or []):
        if not isinstance(d, dict) or not d.get("path"):
            continue
        row_root = d.get("root")
        if identity:
            if row_root:
                if row_root != identity:
                    continue
            elif not single_root_index or d.get("root_path") not in (None, root):
                continue
        elif row_root or d.get("root_path") not in (None, root):
            continue
        rows.append({"path": str(d["path"]),
                     "category": str(d.get("category") or "")})
    return {"docs": rows}


def rule_m2(repo: Path, pages: Dict[str, str], exempts: Dict[str, set],
            bare_index: Optional[set] = None,
            root: str = DOC_ROOT) -> List[Dict[str, Any]]:
    """M2: referenced paths reachable — normative face only, explicit shapes only.
    The normative face is read relative to the documentation root in effect."""
    out: List[Dict[str, Any]] = []
    for rel in sorted(pages):
        if not _is_normative(rel, root):
            continue                       # narrow by class: historical face exempt
        text = pages[rel]
        base = (repo / rel).parent
        for tok, off in extract_paths(text):
            line_no = text.count("\n", 0, off) + 1
            if not _missing(repo, rel, tok, bare_index):
                continue
            quote = text.splitlines()[line_no - 1].strip()[:200]
            if _exempted(exempts.get(rel, set()), RULE_M2):
                continue
            out.append(_finding(
                RULE_M2, "referenced path does not exist: %s" % tok,
                rel, line_no, quote,
                "A normative-face page points at a path that exists under neither "
                "the document's own directory nor the repo root (%s)." % tok,
                "Fix the path, or register the missing entry, or declare "
                "`<!-- doc-exempt: %s -->` if the surface is legitimately fixed." % RULE_M2))
    return out


def rule_m3(docs_rels: List[str], notes_rels: List[str], pages: Dict[str, str],
            added: Dict[str, Dict[int, str]], exempts: Dict[str, set],
            root: str = DOC_ROOT) -> List[Dict[str, Any]]:
    """M3: language discipline on NEW lines only (existing text never judged)."""
    out: List[Dict[str, Any]] = []
    for rel, lines in sorted(added.items()):
        if rel not in pages:
            continue
        text = pages[rel]
        fence_map = {i: f for i, _, f in _fence_state_iter(text.splitlines())}
        in_docs = _is_docs(rel, root)
        if in_docs and _root_rel(rel, root) in _M3_DOCS_EXEMPT_REL:
            continue
        rule = RULE_M3_DOCS if in_docs else RULE_M3_NOTES
        for line_no in sorted(lines):
            if fence_map.get(line_no):
                continue
            raw = lines[line_no]
            probe = _strip_inline_code(raw)
            has_cjk = bool(_CJK_RE.search(probe))
            if in_docs and has_cjk and not _exempted(exempts.get(rel, set()), rule):
                out.append(_finding(
                    rule, "new docs/ line carries Chinese (English STE face)",
                    rel, line_no, raw.strip()[:200],
                    "Since 261004 docs/ is written in English (ASD-STE100 checklist); "
                    "this check fires on diff-new lines only — existing text is untouched.",
                    "Rewrite the line in English, or move the content to notes/, or "
                    "declare `<!-- doc-exempt: %s -->` for a deliberate exception." % rule))
            elif not in_docs and not has_cjk and re.search(r"[A-Za-z]{4,}\s+[A-Za-z]{4,}", probe) \
                    and not _exempted(exempts.get(rel, set()), rule):
                out.append(_finding(
                    rule, "new notes/ prose line carries no Chinese (controlled-Chinese face)",
                    rel, line_no, raw.strip()[:200],
                    "notes/ is the controlled-Chinese face since 261004; a new prose line "
                    "that is pure English suggests the discipline slipped.",
                    "Rewrite the line in controlled Chinese, or declare "
                    "`<!-- doc-exempt: %s -->` (code/token lines are exempt by shape)." % rule))
    return out


def rule_m4(pages: Dict[str, str], exempts: Dict[str, set],
            root: str = DOC_ROOT) -> List[Dict[str, Any]]:
    """M4: progress/todo/ticket-list content inside the documentation root
    (notes/ exempt by class)."""
    out: List[Dict[str, Any]] = []
    for rel in sorted(pages):
        if not _is_docs(rel, root):
            continue
        rules_hit = {r for r in (RULE_M4_CHECKBOX, RULE_M4_TICKETS)
                     if not _exempted(exempts.get(rel, set()), r)}
        if not rules_hit:
            continue
        for i, line, in_fence in _fence_state_iter(pages[rel].splitlines()):
            if in_fence:
                continue
            if RULE_M4_CHECKBOX in rules_hit and _CHECKBOX_RE.match(line):
                out.append(_finding(
                    RULE_M4_CHECKBOX, "progress checkbox list written into a docs/ page",
                    rel, i, line.strip()[:200],
                    "A task ledger inside a document is a dead ledger (M4 discipline): "
                    "progress belongs in the ticket engine, not in docs/.",
                    "Move the list to the ticket engine / notes/, or declare "
                    "`<!-- doc-exempt: %s -->`." % RULE_M4_CHECKBOX))
            else:
                ids = set(_TICKET_RE.findall(line))
                if RULE_M4_TICKETS in rules_hit and len(ids) >= 3:
                    out.append(_finding(
                        RULE_M4_TICKETS, "line enumerates %d ticket ids (a ticket list inside docs/)" % len(ids),
                        rel, i, line.strip()[:200],
                        "A ticket list inside a document is a dead ledger (M4 discipline); "
                        "the engine holds the authoritative list.",
                        "Reference the epic/ticket source instead of enumerating ids, or "
                        "declare `<!-- doc-exempt: %s -->`." % RULE_M4_TICKETS))
    return out


def rule_m5(repo: Path, pages: Dict[str, str], added: Dict[str, Dict[int, str]],
            exempts: Dict[str, set],
            ticket_exists: Optional[Callable[[str], bool]],
            commit_exists: Optional[Callable[[str], bool]],
            bare_index: Optional[set] = None,
            root: str = DOC_ROOT) -> List[Dict[str, Any]]:
    """M5: references named on NEW lines must exist. Predicates injected; when a
    predicate is None the sub-check degrades with a meta note (the caller turns
    that into meta.caveats)."""
    out: List[Dict[str, Any]] = []
    for rel, lines in sorted(added.items()):
        text = pages.get(rel)
        if text is None:
            continue
        fence_map = {i: f for i, _, f in _fence_state_iter(text.splitlines())}
        historical = _is_docs(rel, root) and not _is_normative(rel, root)
        for line_no in sorted(lines):
            if fence_map.get(line_no):
                continue
            raw = lines[line_no]
            if _exempted(exempts.get(rel, set()), RULE_M5_TICKET):
                ids = []
            else:
                ids = sorted(set(_TICKET_RE.findall(raw)))
            if ticket_exists is not None:
                for tid in ids:
                    if not ticket_exists(tid):
                        out.append(_finding(
                            RULE_M5_TICKET, "named ticket id does not exist: %s" % tid,
                            rel, line_no, raw.strip()[:200],
                            "A new line names ticket %s, but no ticket record resolves "
                            "for it (ticket data dir missing)." % tid,
                            "Fix the id, or drop the reference, or declare "
                            "`<!-- doc-exempt: %s -->`." % RULE_M5_TICKET))
            if historical:
                continue            # narrow by class: historical face, path/commit drift
            if _exempted(exempts.get(rel, set()), RULE_M5_COMMIT):
                shas = []
            else:
                shas = sorted(set(_COMMIT_RE.findall(raw)))
            if commit_exists is not None:
                for sha in shas:
                    if not commit_exists(sha):
                        out.append(_finding(
                            RULE_M5_COMMIT, "named commit does not exist in this repository: %s…" % sha[:10],
                            rel, line_no, raw.strip()[:200],
                            "A new line names a 40-hex commit that git cannot resolve.",
                            "Fix the hash or reference the ticket instead."))
            if not _exempted(exempts.get(rel, set()), RULE_M5_FILE):
                for tok, off in extract_paths(raw):
                    if not _missing(repo, rel, tok, bare_index):
                        continue
                    out.append(_finding(
                        RULE_M5_FILE, "referenced file on a new line does not exist: %s" % tok,
                        rel, line_no, raw.strip()[:200],
                        "A new line references a path that exists under neither the "
                        "document's directory nor the repo root.",
                        "Fix the path or declare `<!-- doc-exempt: %s -->`." % RULE_M5_FILE))
    return out


def rule_m6(pages: Dict[str, str], fm: Dict[str, Dict[str, Any]],
            exempts: Dict[str, set],
            root: str = DOC_ROOT) -> List[Dict[str, Any]]:
    """M6: a design page marked deprecated must carry a superseded-by pointer."""
    out: List[Dict[str, Any]] = []
    for rel in sorted(pages):
        if not _norm_slash(rel).startswith(root.rstrip("/") + "/design/"):
            continue
        status = (fm.get(rel) or {}).get("status")
        if status != "deprecated":
            continue
        if _exempted(exempts.get(rel, set()), RULE_M6):
            continue
        if not _SUPERSEDE_RE.search(pages[rel]):
            out.append(_finding(
                RULE_M6, "deprecated design page has no superseded-by pointer",
                rel, 1, (pages[rel].splitlines()[0])[:200],
                "A replaced document must say who replaced it (design section 2, "
                "historical face rule); readers following an old page otherwise land "
                "on stale truth.",
                "Add a `Superseded by <path>` pointer at the top of the page, or "
                "declare `<!-- doc-exempt: %s -->`." % RULE_M6))
    return out


def rule_m7(repo: Path, pages: Dict[str, str], changed_files: List[str],
            exempts: Dict[str, set], bare_index: Optional[set] = None) -> List[Dict[str, Any]]:
    """M7 both directions: (a) changed code file mentioned by a library page →
    low pointer finding for the agent layer; (b) changed page naming a code
    surface that no longer exists → med."""
    out: List[Dict[str, Any]] = []
    # page → named-token index (explicit shapes only), built once
    named: List[Tuple[str, str, int, str]] = []   # (rel, tok, line_no, quote)
    for rel in sorted(pages):
        text = pages[rel]
        for tok, off in extract_paths(text):
            line_no = text.count("\n", 0, off) + 1
            named.append((rel, _norm_slash(tok).lstrip("./"), line_no,
                          text.splitlines()[line_no - 1].strip()[:200]))
    # (a) changed code files mentioned by pages → must-check pointers
    ptr = 0
    for cf in sorted(changed_files):
        cfn = _norm_slash(cf).lstrip("./")
        if cfn.endswith(".md"):
            continue
        for rel, tok, line_no, quote in named:
            if ptr >= MAX_M7_PTR:
                return out
            if tok == cfn or tok.endswith("/" + cfn) or cfn.endswith("/" + tok):
                out.append(_finding(
                    RULE_M7_PTR, "code surface changed this period; page mentions it — must-check",
                    rel, line_no, quote,
                    "M7 pointer (severity low, not a defect): %s changed in the change "
                    "surface and this page names it; the agent layer verifies the page "
                    "still matches reality." % cfn,
                    "Agent layer: verify the page's claims against the current code.",
                    severity=SEVERITY_M7_PTR))
                ptr += 1
    # (b) changed pages naming code surfaces that must still exist
    for rel in sorted(set(changed_files)):
        reln = _norm_slash(rel)
        if reln not in pages:
            continue
        if _exempted(exempts.get(reln, set()), RULE_M7_STALE):
            continue
        for tok, off in extract_paths(pages[reln]):
            line_no = pages[reln].count("\n", 0, off) + 1
            if not _missing(repo, reln, tok, bare_index):
                continue
            out.append(_finding(
                RULE_M7_STALE, "changed page names a code surface that does not exist: %s" % tok,
                reln, line_no, pages[reln].splitlines()[line_no - 1].strip()[:200],
                "The page changed this period and names a surface that exists under "
                "neither the document's directory nor the repo root.",
                "Fix the named path or remove the stale claim."))
            break   # one stale-surface finding per changed page keeps the list readable
    return out


# ========================================================================
# scan entry point
# ========================================================================

def _resolve_row(repo: Path, tok: str, root: str = DOC_ROOT) -> Optional[str]:
    """Resolve one catalogue row of the documentation root's README → repo-relative
    path, or None. `root` is the documentation root in effect.

    A row is written the way the reader of its section resolves it, so the same
    token can be docs-relative (`design/x.md`), repository-root-relative (the
    maintenance prose names `notes/README.md` and the root `CLAUDE.md`) or a bare
    file name that lives in one of the docs sub-directories (the Root level table
    names `writing-standard.md`, which sits in `docs/reference/`). Fixed order,
    no prose guessing:
      1. the catalogue's own base, docs/ — the only base a row carrying a
         directory component is written against;
      2. the repository root;
      3. for a bare file name only, a UNIQUE basename match anywhere under docs/.
         An ambiguous name never resolves: it stays a missing-row finding, so the
         drift stays visible instead of being guessed away.
    """
    root = root.rstrip("/") or DOC_ROOT
    t = _norm_slash(tok).lstrip("./")
    if not t:
        return None
    sub = t[len(root) + 1:] if t.startswith(root + "/") else t
    if (repo / root / sub).exists():
        return root + "/" + sub
    if (repo / sub).exists():
        return sub
    if "/" in sub:
        return None
    hits = sorted(p for p in (repo / root).rglob("*.md")
                  if p.is_file() and p.name == sub)
    if len(hits) == 1:
        return _norm_slash(hits[0].relative_to(repo).as_posix())
    return None


def _readme_rels(repo: Path, readme_text: str, root: str = DOC_ROOT) -> set:
    """Catalogue rows in the documentation root's README → repo-relative paths.

    Rows are backticked `*.md` paths inside tables and prose (explicit shapes
    only). Each row is RESOLVED (see `_resolve_row`) rather than blindly
    prefixed with `docs/`: the README writes some rows from the section they sit
    in and some from the repository root, and prefixing was reporting live files
    as missing (host ruling 261029 — fix the checker, not the docs).

    A row that resolves to an existing file OUTSIDE docs/ is a reference to a
    non-library file, not a catalogue row (it is never asked to appear in a docs
    leg). A row that resolves nowhere keeps the docs/-relative form, so the
    missing-row finding still fires.
    """
    root = root.rstrip("/") or DOC_ROOT
    out = set()
    for tok, _off in extract_paths(readme_text):
        t = _norm_slash(tok).lstrip("./")
        if not t.endswith(".md"):
            continue          # catalogue paths only; json/yaml rows are not M1 legs
        rel = _resolve_row(repo, t, root)
        if rel is None:
            out.add(t if t.startswith(root + "/") else root + "/" + t)
        elif _is_docs(rel, root):
            out.add(rel)
        # else: resolves outside docs/ — a legitimate non-library reference
    return out


def _scan_root(repo: Path, root: str,
               added: Dict[str, Dict[int, str]], changed: List[str],
               ticket_exists: Optional[Callable[[str], bool]],
               commit_exists: Optional[Callable[[str], bool]],
               base_head: str, derived: Optional[DerivedIndex] = None,
               root_identity: Optional[str] = None) -> Dict[str, Any]:
    """M1-M7 over ONE documentation root of one repository. The root is a
    parameter (the declared one, the implied default, or an explicitly supplied
    one) -- never a directory name guessed here.

    Since t261103-17 the index leg reads the DERIVED index (`derived`, read once per
    pass from the project data directory through docs_roots), never a file inside this
    repository, and it judges that artefact's state instead of assuming an index.
    """
    root = root.rstrip("/") or DOC_ROOT
    rels, _unread = _read_pages(repo, root)
    pages: Dict[str, str] = {}
    for rel in rels:
        t = _read_text(repo, rel)
        if t is not None:
            pages[rel] = t

    derived = derived if derived is not None else _read_derived_index("")
    index = _entries_of_root(derived, root, root_identity)

    readme_text = pages.get(root + "/README.md", "")
    readme_rels = _readme_rels(repo, readme_text, root) if readme_text else set()

    exempts = {rel: collect_exemptions(t) for rel, t in pages.items()}
    fm = {rel: parse_frontmatter(t)[0] for rel, t in pages.items()}

    caveats: List[str] = []
    if ticket_exists is None:
        caveats.append("M5 ticket-existence predicate not supplied: ticket-id check degraded this period")
    if commit_exists is None:
        caveats.append("M5 commit-existence predicate not supplied: commit check degraded this period")
    if not base_head and not added:
        caveats.append("no change surface supplied: M3 and the new-line part of M5 are skipped this period")
    if derived.state in INDEX_STATES_QUIET:
        caveats.append(
            "docs_index_%s: the derived documentation index is not judged this period "
            "(%s); the index leg of M1 and the part of the catalogue leg that needs it "
            "are skipped, and no page is reported unregistered"
            % (derived.state, derived.reason or "not built yet"))
    elif derived.state in ("stale", "failed"):
        caveats.append(
            "docs_index_%s: the derived documentation index is not current, so the "
            "index leg of M1 is a single finding naming that state and no page is "
            "reported unregistered" % derived.state)

    findings: List[Dict[str, Any]] = []
    bare: Optional[set] = None
    findings += rule_m1(repo, pages, index, readme_rels, rels, exempts, root,
                        index_state=derived.state, index_reason=derived.reason,
                        index_built_at=derived.built_at, index_path=derived.path)
    findings += rule_m2(repo, pages, exempts, _build_bare_index(repo), root)
    if added:
        findings += rule_m3(rels, rels, pages, added, exempts, root)
        findings += rule_m5(repo, pages, added, exempts, ticket_exists, commit_exists,
                            _build_bare_index(repo), root)
    findings += rule_m4(pages, exempts, root)
    findings += rule_m6(pages, fm, exempts, root)
    if changed:
        findings += rule_m7(repo, pages, changed, exempts, _build_bare_index(repo))
    return {"findings": findings, "pages_scanned": len(pages),
            # The leg ran as designed only for a CURRENT index; `absent` is the
            # designed first pass (not a degrade), while a stale, failed or
            # unlocatable index means the per-page comparison did not happen.
            "index_leg_degraded": derived.state in ("stale", "failed",
                                                    INDEX_STATE_UNLOCATED),
            "index_state": derived.state,
            "exempted": exempts, "caveats": caveats}


def _scan_roots(repo: Path, docs_root: Optional[str], project_key: str,
                projects_root_dir: Optional[Any] = None
                ) -> Tuple[Dict[str, Any], List[Tuple[str, Optional[str]]]]:
    """(the roots-in-effect face for meta, the roots to scan as (path, identity)).

    t261103-11 (design docs/design/project-docs-roots-v1.md goal 2): the ONE
    resolution every consumer calls decides which roots this scan walks. An
    explicit `docs_root` (an ops caller that already resolved) wins; otherwise
    the declaration resolution answers -- declared roots for this repository,
    or the implied default root. A refusal is raised by name (DocMechError
    carrying the code), never degraded into an empty library: "no documents" and
    "documents not found" must not read alike.

    The root identity (repository + declared path, design goal 8) is carried along:
    it is how M1 picks this root's rows out of the project-wide derived index, so two
    roots that hold the same relative path never mix.

    t261103-17: `projects_root_dir` is the same registry the derived index is read
    from, so the resolution, the writer and the reader can never consult two different
    registries.
    """
    if docs_root:
        one = str(docs_root).strip().rstrip("/") or DOC_ROOT
        return ({"source": "argument", "declaration": "", "tree": str(repo),
                 "reason": "", "roots": [{"path": one}]}, [(one, None)])
    import docs_roots
    try:
        res = docs_roots.resolve(project_key, tree=repo,
                                 projects_root_dir=projects_root_dir)
    except docs_roots.DocsRootsStop as e:
        raise DocMechError(docs_roots.refusal_text(e)) from None
    return (res.face(), [(r.path, r.identity) for r in res.roots])


def run_doc_mech(repo_root: str,
                 added_lines: Optional[Dict[str, Dict[int, str]]] = None,
                 changed_files: Optional[List[str]] = None,
                 ticket_exists: Optional[Callable[[str], bool]] = None,
                 commit_exists: Optional[Callable[[str], bool]] = None,
                 base_head: str = "",
                 docs_root: Optional[str] = None,
                 project_key: str = "",
                 index_rebuild: Optional[Callable[[], Dict[str, Any]]] = None,
                 docs_projects_root: Optional[str] = None) -> Dict[str, Any]:
    """Run M1-M7 over the whole library. All inputs injectable; malformed input
    degrades item by item (never crashes). Returns {findings, meta} with
    findings in the exact agent shape.

    The documentation root(s) come from the ONE declaration resolution
    (`docs_roots.resolve`): an undeclared project that owns docs/ scans docs/
    exactly as before, a project that declares roots has each of its roots in
    this repository scanned, and a missing/unreadable/malformed root is a NAMED
    refusal (DocMechError carrying the code) rather than a green empty scan.

    `index_rebuild` is the documentation inspection's ONE automatic write
    (t261103-12): the callable rebuilds the derived documentation index outside the
    repository (`docs_index.rebuild`), and its outcome lands in meta.docs_index. None
    means no rebuild this pass (unit tests, replay paths). A rebuild failure is
    recorded, never raised — a documentation refresh must not take the pass down.

    t261103-17: the index leg of M1 reads that DERIVED index back (after the rebuild,
    so a pass that rebuilt it judges the fresh one), resolved through docs_roots, and
    the state it read lands in meta.docs_index_state. `docs_projects_root` is the same
    registry override the rebuild gets, so the writer and the reader can never look in
    two different places.
    """
    index_note: Optional[Dict[str, Any]] = None
    if index_rebuild is not None:
        try:
            index_note = index_rebuild()
        except Exception as e:      # noqa: BLE001 — recorded failure, never fatal
            index_note = {"ok": False, "state": "failed", "reason": str(e)[:300]}
    repo = Path(repo_root)
    if not repo.is_dir():
        raise DocMechError("repo root does not exist: %s" % repo_root)
    added = added_lines or {}
    changed = [c for c in (changed_files or [])]
    roots_face, roots = _scan_roots(repo, docs_root, project_key, docs_projects_root)
    derived = _read_derived_index(project_key, docs_projects_root)

    findings: List[Dict[str, Any]] = []
    pages_scanned = 0
    index_degraded = False
    exempted: set = set()
    caveats: List[str] = []
    if not roots:
        # Declared, but every root lives in another repository of the project:
        # a NAMED state (the scan covers nothing here), never a silent green.
        caveats.append("docs_roots_declared_elsewhere: the declaration names no "
                       "documentation root in this repository (%s)"
                       % (roots_face.get("declaration") or "no declaration"))
    if derived.judged and not _index_matches_tree(derived, repo, roots):
        # The artefact is per PROJECT (docs_roots.index_dir); a scan of another tree
        # of the project (a lane worktree, a second checkout) reads rows built from
        # that other tree. Named here, never silently mixed into the verdicts: the
        # rows are still compared (the index is current for its own tree), but a
        # reader can see which tree the drift describes.
        caveats.append(
            "docs_index_other_tree: the derived documentation index was built from %s "
            "but this scan walks %s -- the index describes another tree of the project, "
            "so index-leg findings here may be that tree's state"
            % (_built_dirs(derived) or "(unknown)",
               str((repo / roots[0][0]).resolve()) if roots else str(repo)))
    for root, identity in roots:
        part = _scan_root(repo, root, added, changed, ticket_exists,
                          commit_exists, base_head, derived=derived,
                          root_identity=identity)
        findings += part["findings"]
        pages_scanned += part["pages_scanned"]
        index_degraded = index_degraded or part["index_leg_degraded"]
        exempted |= {r for rs in part["exempted"].values() for r in rs}
        for c in part["caveats"]:
            if c not in caveats:
                caveats.append(c)
    _cap_quotes(findings)
    findings.sort(key=lambda f: (f["severity"], f["scan"], f["subject"]))

    meta = {
        "scanner": "inspection_doc_mech",
        "pages_scanned": pages_scanned,
        "index_leg_degraded": bool(index_degraded),
        "diff_rules_ran": bool(added),
        "change_surface_files": len(changed),
        "exempted": sorted(exempted),
        "heartbeat": not findings,
        "caveats": caveats,
        "docs_roots": roots_face,
        "docs_index_state": derived.face(),
    }
    if index_note is not None:
        meta["docs_index"] = index_note
    return {"findings": findings, "meta": meta}


# ========================================================================
# CLI (ops channel; same single-line JSON contract as the retired scanner)
# ========================================================================

def _git_changed(repo_root: str, base: str) -> Tuple[List[str], Dict[str, Dict[int, str]]]:
    """Change surface from git (activity/CLI side only; UTs inject instead).
    Returns (changed_files, added_lines {rel: {lineno: added text}})."""
    import subprocess
    changed: List[str] = []
    added: Dict[str, Dict[int, str]] = {}
    for args in (["diff", "--name-only", base],):
        r = subprocess.run(["git", "-C", repo_root] + args, capture_output=True,
                           text=True, timeout=60)
        if r.returncode != 0:
            return changed, added
        changed = [l for l in r.stdout.splitlines() if l.strip()]
    r = subprocess.run(["git", "-C", repo_root, "diff", "--unified=0", base],
                       capture_output=True, text=True, timeout=120)
    cur = ""
    new_line = 0
    for line in r.stdout.splitlines():
        if line.startswith("+++ b/"):
            cur = _norm_slash(line[6:])
        elif line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            new_line = int(m.group(1)) if m else 0
        elif line.startswith("+") and not line.startswith("+++") and cur and new_line:
            added.setdefault(cur, {})[new_line] = line[1:]
            new_line += 1
        elif not line.startswith("-"):
            if cur and new_line:
                new_line += 1
    return changed, added


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="doc-face mechanical layer (M1-M7)")
    ap.add_argument("--repo-root", required=True)
    ap.add_argument("--base", default="HEAD",
                    help="git base for the change surface (diff-fed rules M3/M5/M7)")
    ap.add_argument("--no-diff", action="store_true",
                    help="skip the change surface entirely (M1/M2/M4/M6 only)")
    ap.add_argument("--docs-root", default="",
                    help="scan this documentation root instead of resolving the "
                         "declaration (ops override; the resolved default is the "
                         "implied root of the repository)")
    ap.add_argument("--project", default="",
                    help="project key whose documentation-root declaration decides "
                         "the scan roots and whose derived index the index leg reads")
    ap.add_argument("--projects-root", default=None,
                    help="override the per-key projects root the derived index lives "
                         "under (default: $SANDBAR_PROJECTS_DIR or ~/.sandbar/projects)")
    args = ap.parse_args(argv)
    try:
        if args.no_diff:
            changed, added = [], {}
        else:
            changed, added = _git_changed(args.repo_root, args.base)
        result = run_doc_mech(args.repo_root, added_lines=added,
                              changed_files=changed,
                              base_head="" if args.no_diff else args.base,
                              docs_root=args.docs_root or None,
                              project_key=args.project,
                              docs_projects_root=args.projects_root)
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False)
              .encode("utf-8", "backslashreplace").decode("utf-8"))
        return 0
    except Exception as e:      # noqa: BLE001 — CLI contract: single-line JSON error
        print(json.dumps({"ok": False, "error": str(e)[:500]}, ensure_ascii=False)
              .encode("utf-8", "backslashreplace").decode("utf-8"))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
