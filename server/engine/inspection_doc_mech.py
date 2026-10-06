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
  M1 doc-m1-*          index three-way consistency: docs/index.json ↔
                       docs/README.md ↔ actual files (page exists but
                       unregistered / registered but file gone / README leg
                       drift / frontmatter five fields missing). Severity med.
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
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from inspection_inspect import mint_finding_id  # noqa: E402  (single id mint)

# ---- lexical constants (top of file; any change ships with a truth-table UT) ----
DOC_ROOT = "docs"
DESIGN_SUB = "docs/design"
NOTES_ROOT = "notes"
REQUIRED_FIELDS = ("title", "category", "tags", "status", "updated")   # carried S9
CATEGORIES = ("design", "content", "ops", "reference")
STATUSES = ("active", "draft", "deprecated")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SEVERITY = "med"          # M1-M6: static surfaces never certify high (C1 item 9)
SEVERITY_M7_PTR = "low"   # M7(a) pointer findings only

RULE_M1_INDEX = "doc-m1-index"              # index leg drift (unregistered / ghost)
RULE_M1_README = "doc-m1-readme"            # README leg drift
RULE_M1_FRONTMATTER = "doc-m1-frontmatter"  # frontmatter five fields
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

MAX_EVIDENCE_QUOTES = 5   # evidence cap per finding (long lists stay readable)
MAX_M7_PTR = 40           # pointer findings cap (same order as the agent budget)


class DocMechError(Exception):
    """Fail-closed scan error (repo root missing, etc.)."""


# ========================================================================
# small pure helpers
# ========================================================================

def _norm_slash(p: str) -> str:
    return str(p).replace("\\", "/")


def _is_normative(rel: str) -> bool:
    rel = _norm_slash(rel)
    return rel in _NORMATIVE_EXACT or any(rel.startswith(p) for p in _NORMATIVE_PREFIX)


def _is_docs(rel: str) -> bool:
    return _norm_slash(rel).startswith(DOC_ROOT + "/")


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

def _read_pages(repo: Path) -> Tuple[List[str], List[str]]:
    """All library pages (docs/ + notes/) as (rel, text). Unreadable files
    degrade alone (C1 item 2)."""
    rels: List[str] = []
    unreadable: List[str] = []
    for root in (DOC_ROOT, NOTES_ROOT):
        base = repo / root
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


def rule_m1(repo: Path, pages: Dict[str, str], index: Any, index_err: Optional[str],
            readme_rels: set, all_rels: List[str], exempts: Dict[str, set]) -> List[Dict[str, Any]]:
    """M1 three-way: index.json ↔ README ↔ actual files + frontmatter (S9 carried)."""
    out: List[Dict[str, Any]] = []
    if index_err:
        out.append(_finding(
            RULE_M1_INDEX, "docs/index.json is unreadable: degraded three-way check",
            "docs/index.json", 1, index_err,
            "The machine index failed to parse, so the index leg of the three-way "
            "consistency check is absent this period.",
            "Fix docs/index.json (run docs/scripts/build_index.py), then re-run."))
    indexed = set()
    if isinstance(index, dict):
        for d in index.get("docs") or []:
            if isinstance(d, dict) and d.get("path"):
                # index.json paths are docs/-relative ("design/x.md"); normalize to
                # repo-relative so they compare against the actual-file set.
                p = _norm_slash(str(d["path"])).lstrip("./")
                indexed.add(p if p.startswith(DOC_ROOT + "/") else DOC_ROOT + "/" + p)
    actual = {r for r in all_rels if _is_docs(r)}
    # file vs index
    for rel in sorted(actual - indexed):
        if _exempted(exempts.get(rel, set()), RULE_M1_INDEX):
            continue
        out.append(_finding(
            RULE_M1_INDEX, "page exists but is not registered in docs/index.json",
            rel, 1, (pages.get(rel) or "").splitlines()[0][:200] if pages.get(rel) else "",
            "The page exists under docs/ but the machine index has no entry for it; "
            "plugins and agents consume the index.",
            "Register the page (python3 docs/scripts/build_index.py) or move it out of docs/."))
    for rel in sorted(indexed - actual):
        if _exempted(exempts.get(rel, set()), RULE_M1_INDEX):
            continue
        out.append(_finding(
            RULE_M1_INDEX, "index entry points at a file that does not exist",
            "docs/index.json", 1, rel,
            "docs/index.json registers %s but no such file exists — a ghost entry." % rel,
            "Remove the ghost entry (rebuild the index) or restore the file."))
    # README leg
    for rel in sorted((actual & indexed) - readme_rels):
        if _exempted(exempts.get(rel, set()), RULE_M1_README):
            continue
        out.append(_finding(
            RULE_M1_README, "page registered in index.json but missing from docs/README.md catalogue",
            "docs/README.md", 1, rel,
            "The human-readable catalogue (docs/README.md) does not list a page that "
            "exists and is indexed — the third leg of the three-way check.",
            "Add a catalogue row in the matching category section of docs/README.md."))
    for rel in sorted(readme_rels - actual):
        if _exempted(exempts.get(rel, set()), RULE_M1_README):
            continue
        out.append(_finding(
            RULE_M1_README, "catalogue row names a file that does not exist at that path",
            "docs/README.md", 1, rel,
            "docs/README.md lists %s but the file is not there (moved or gone)." % rel,
            "Fix the catalogue path or restore the file."))
    # frontmatter (S9 carried)
    for rel in sorted(actual):
        text = pages.get(rel)
        if text is None:
            continue
        fields, well = parse_frontmatter(text)
        defects = frontmatter_defects(fields, well)
        if defects and not _exempted(exempts.get(rel, set()), RULE_M1_FRONTMATTER):
            out.append(_finding(
                RULE_M1_FRONTMATTER, "frontmatter five-field check failed: " + "; ".join(defects),
                rel, 1, text.splitlines()[0][:200],
                "Every docs/ page carries YAML frontmatter with title/category/tags/"
                "status/updated (docs/README.md maintenance conventions).",
                "Add or fix the frontmatter fields listed in the subject."))
    return out


def _build_bare_index(repo: Path) -> set:
    out = set()
    for p in repo.rglob("*"):
        if p.is_file():
            out.add(p.name)
    return out


def rule_m2(repo: Path, pages: Dict[str, str], exempts: Dict[str, set],
            bare_index: Optional[set] = None) -> List[Dict[str, Any]]:
    """M2: referenced paths reachable — normative face only, explicit shapes only."""
    out: List[Dict[str, Any]] = []
    for rel in sorted(pages):
        if not _is_normative(rel):
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
            added: Dict[str, Dict[int, str]], exempts: Dict[str, set]) -> List[Dict[str, Any]]:
    """M3: language discipline on NEW lines only (existing text never judged)."""
    out: List[Dict[str, Any]] = []
    for rel, lines in sorted(added.items()):
        if rel not in pages:
            continue
        text = pages[rel]
        fence_map = {i: f for i, _, f in _fence_state_iter(text.splitlines())}
        in_docs = _is_docs(rel)
        if in_docs and rel in _M3_DOCS_EXEMPT:
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


def rule_m4(pages: Dict[str, str], exempts: Dict[str, set]) -> List[Dict[str, Any]]:
    """M4: progress/todo/ticket-list content inside docs/ (notes/ exempt by class)."""
    out: List[Dict[str, Any]] = []
    for rel in sorted(pages):
        if not _is_docs(rel):
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
            bare_index: Optional[set] = None) -> List[Dict[str, Any]]:
    """M5: references named on NEW lines must exist. Predicates injected; when a
    predicate is None the sub-check degrades with a meta note (the caller turns
    that into meta.caveats)."""
    out: List[Dict[str, Any]] = []
    for rel, lines in sorted(added.items()):
        text = pages.get(rel)
        if text is None:
            continue
        fence_map = {i: f for i, _, f in _fence_state_iter(text.splitlines())}
        historical = _is_docs(rel) and not _is_normative(rel)
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
            exempts: Dict[str, set]) -> List[Dict[str, Any]]:
    """M6: a docs/design page marked deprecated must carry a superseded-by pointer."""
    out: List[Dict[str, Any]] = []
    for rel in sorted(pages):
        if not _norm_slash(rel).startswith(DESIGN_SUB + "/"):
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

def _readme_rels(readme_text: str) -> set:
    """Catalogue rows in docs/README.md: backticked `*.md` paths inside tables
    and prose (explicit shapes only)."""
    out = set()
    for tok, _off in extract_paths(readme_text):
        t = _norm_slash(tok).lstrip("./")
        if not t.endswith(".md"):
            continue          # catalogue paths only; json/yaml rows are not M1 legs
        out.add(t if t.startswith(DOC_ROOT + "/") else DOC_ROOT + "/" + t)
    return out


def run_doc_mech(repo_root: str,
                 added_lines: Optional[Dict[str, Dict[int, str]]] = None,
                 changed_files: Optional[List[str]] = None,
                 ticket_exists: Optional[Callable[[str], bool]] = None,
                 commit_exists: Optional[Callable[[str], bool]] = None,
                 base_head: str = "") -> Dict[str, Any]:
    """Run M1-M7 over the whole library. All inputs injectable; malformed input
    degrades item by item (never crashes). Returns {findings, meta} with
    findings in the exact agent shape."""
    repo = Path(repo_root)
    if not repo.is_dir():
        raise DocMechError("repo root does not exist: %s" % repo_root)
    added = added_lines or {}
    changed = [c for c in (changed_files or [])]

    rels, _unread = _read_pages(repo)
    pages: Dict[str, str] = {}
    for rel in rels:
        t = _read_text(repo, rel)
        if t is not None:
            pages[rel] = t

    index: Any = None
    index_err: Optional[str] = None
    try:
        index = json.loads((repo / "docs" / "index.json").read_text("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as e:
        index_err = str(e)[:200]

    readme_text = pages.get("docs/README.md", "")
    readme_rels = _readme_rels(readme_text) if readme_text else set()

    exempts = {rel: collect_exemptions(t) for rel, t in pages.items()}
    fm = {rel: parse_frontmatter(t)[0] for rel, t in pages.items()}

    caveats: List[str] = []
    if ticket_exists is None:
        caveats.append("M5 ticket-existence predicate not supplied: ticket-id check degraded this period")
    if commit_exists is None:
        caveats.append("M5 commit-existence predicate not supplied: commit check degraded this period")
    if not base_head and not added:
        caveats.append("no change surface supplied: M3 and the new-line part of M5 are skipped this period")
    if index_err:
        caveats.append("docs/index.json unreadable: index leg of M1 degraded")

    findings: List[Dict[str, Any]] = []
    bare: Optional[set] = None
    findings += rule_m1(repo, pages, index, index_err, readme_rels, rels, exempts)
    findings += rule_m2(repo, pages, exempts, _build_bare_index(repo))
    if added:
        findings += rule_m3(rels, rels, pages, added, exempts)
        findings += rule_m5(repo, pages, added, exempts, ticket_exists, commit_exists,
                            _build_bare_index(repo))
    findings += rule_m4(pages, exempts)
    findings += rule_m6(pages, fm, exempts)
    if changed:
        findings += rule_m7(repo, pages, changed, exempts, _build_bare_index(repo))
    _cap_quotes(findings)
    findings.sort(key=lambda f: (f["severity"], f["scan"], f["subject"]))

    meta = {
        "scanner": "inspection_doc_mech",
        "pages_scanned": len(pages),
        "index_leg_degraded": bool(index_err),
        "diff_rules_ran": bool(added),
        "change_surface_files": len(changed),
        "exempted": sorted({r for rs in exempts.values() for r in rs}),
        "heartbeat": not findings,
        "caveats": caveats,
    }
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
    args = ap.parse_args(argv)
    try:
        if args.no_diff:
            changed, added = [], {}
        else:
            changed, added = _git_changed(args.repo_root, args.base)
        result = run_doc_mech(args.repo_root, added_lines=added,
                              changed_files=changed, base_head="" if args.no_diff else args.base)
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False)
              .encode("utf-8", "backslashreplace").decode("utf-8"))
        return 0
    except Exception as e:      # noqa: BLE001 — CLI contract: single-line JSON error
        print(json.dumps({"ok": False, "error": str(e)[:500]}, ensure_ascii=False)
              .encode("utf-8", "backslashreplace").decode("utf-8"))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
