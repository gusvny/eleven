"""L22 stale-pin lint (t261009-02): a scenario must not pin a CJK literal that
no longer exists in any source it could come from.

Rule source: ticket t261009-02 — commit f5c6b9ad translated a host refusal
(`worktree 越出仓库根：…` → `worktree is outside the repository root: …`) and
left the pinning scenario red on main, blocking an unrelated ticket's gate.
The general rule "a user-visible wording change carries its pinning anchors in
the same change" is pinned here mechanically, not by discipline.

Mechanics: extract CJK string literals used in *pin positions* only —
  .mjs / .py  `X.includes('<lit>')`          (substring pins)
  .py         `'<lit>' in X` / `X in '<lit>'` (membership pins)
Message-builder strings (f-strings, j.ok()/ok() human labels) are NOT pin
positions and are never flagged — that keeps e.g.
t260920-03/sc_terminology_baseline_floor.py:85 (an f-string builder mentioning
越出) green, per the ticket's negative-case requirement (no blanket CJK sweep).

A pinned CJK literal is stale unless:
  (a) it occurs verbatim in a non-integration source tree (server/, sandbar/),
  (b) it occurs elsewhere in the same scenario file outside pin positions
      (fixture-writer side — the scenario both writes and reads the string),
  (c) it has an explicit per-file:line entry in STALE_PIN_ALLOW with a reason
      (relief valve; a literal that legitimately lives only in docs/ lands here).

Honest limit (stated, not promised): this catches the observed class — a pin
whose literal survives nowhere it could come from. It cannot prove a pin
matches the *right* host message, and cannot catch a rewording whose old
literal still exists elsewhere in the tree. A deeper host-string→pin
correlation guard is not cheap and is deliberately not built here.

Unit battery: integration/test_stale_pin_lint.py (in-process synthetic trees,
no integration entry executed).
"""
import ast
import io
import re
import tokenize
from pathlib import Path

CJK = re.compile(r"[\u4e00-\u9fff]")

# .includes('lit') / .includes("lit") — mjs and (rare) py substring pins
PIN_INCLUDES = re.compile(r"\.includes\(\s*(['\"])(?P<lit>[^'\"]*)\1")
# '<lit>' in X  /  X in '<lit>' — py membership pins
PIN_IN_LEFT = re.compile(r"(['\"])(?P<lit>[^'\"]*)\1\s+in\b")
PIN_IN_RIGHT = re.compile(r"\bin\s+(['\"])(?P<lit>[^'\"]*)\1")

# source trees scanned for relief (a): non-integration product sources plus
# integration shared code (run_scenarios.py, lib_*.py, conftest*.py) — a pin
# may legitimately target a string those produce. Scenario files (sc_*) and
# test batteries are NOT relief sources: a scenario writing a string itself is
# relief (b) and is judged per-file.
SOURCE_DIRS = ("server", "sandbar")
SOURCE_SKIP = ("node_modules", ".venv", "__pycache__", ".git")

# (c) explicit exemptions: {(relpath, line_no): reason} — silent ≠ exempt
STALE_PIN_ALLOW = {
    # t261009-02: pins run_scenarios.py:4354's produced face `本轮只跑点名 %d 条…`
    # (integration shared code is deliberately NOT a relief corpus — see
    # _iter_integration_shared — so this live pin needs a named exemption)
    ("integration/t260930-01/sc_known_red_round_exempt.py", 129):
        "pins run_scenarios.py:4354 printf face 本轮只跑点名 %d 条 (live)",
    # t261009-02: the rendered body-card title's only source record is a comment
    # (server/plugins/workbench/src/client/index.tsx:820); the corpus strips
    # comments (so prose cannot relieve a pin), which makes this live pin look
    # stale. Named here rather than weakening the stripper.
    ("integration/t260925-18/sc_ui_english_spec_markdown.mjs", 204):
        "pins live DOM title 工单正文（原始需求） — source record is a src comment",
}


def _py_string_spans(text):
    """(start, end) char offsets of Python STRING tokens — matches inside them
    are data (adaptation tables, fixtures), not live code-level pins."""
    spans = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.STRING:
                spans.append((tok.start[0], tok.start[1], tok.end[0], tok.end[1]))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return spans  # malformed file: judge by regex only
    return spans


def _inside_string(spans, line, col):
    return any((sl, sc) <= (line, col) < (el, ec) for sl, sc, el, ec in spans)


def _is_negative_pin(line, match_start):
    """A negated pin (`!x.includes('lit')`, `not 'lit' in x`) asserts the
    literal's ABSENCE — zero-residual pins are green precisely when the copy
    is gone, so absence can never be stale in the f5c6b9ad sense."""
    before = line[max(0, match_start - 16):match_start]
    return "!" in before or "not " in before


def collect_pins(text, filename=""):
    """Return [(line_no, literal)] of CJK literals in pin positions of `text`.

    For .py text, matches inside string tokens are skipped (they are embedded
    data — e.g. t261004-28's named adaptation table — not pins in live code).
    Negated pins are skipped (see _is_negative_pin).
    """
    is_py = filename.endswith(".py")
    spans = _py_string_spans(text) if is_py else []
    pins = []
    for i, line in enumerate(text.splitlines(), 1):
        for rx in (PIN_INCLUDES, PIN_IN_LEFT, PIN_IN_RIGHT):
            for m in rx.finditer(line):
                if spans and _inside_string(spans, i, m.start("lit")):
                    continue
                if _is_negative_pin(line, m.start()):
                    continue
                lit = m.group("lit")
                if lit and CJK.search(lit):
                    pins.append((i, lit))
    return pins


def _iter_sources(repo):
    for d in SOURCE_DIRS:
        base = repo / d
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if p.is_dir() or any(part in p.parts for part in SOURCE_SKIP):
                continue
            if p.suffix not in (".ts", ".js", ".mjs", ".cjs", ".py", ".tsx",
                                ".jsx", ".vue", ".json", ".yaml", ".yml", ".sh"):
                continue
            try:
                yield p
            except OSError:
                continue


def _iter_scenario_files(repo):
    integ = repo / "integration"
    for p in sorted(integ.rglob("*")):
        if not p.is_file() or p.suffix not in (".mjs", ".py"):
            continue
        if p.name == "lib_stale_pin.py":
            continue
        # lint unit batteries legitimately embed stale pins as fixtures —
        # the battery proves the lint reds them in-process, not by self-scan
        if p.name.startswith("test_") and p.suffix == ".py":
            continue
        # baselines/ is the frozen regression-artifact zone (never executed as
        # a live face here) — L22 does not judge frozen artifacts
        if "baselines" in p.parts:
            continue
        yield p


def _iter_integration_shared(repo):
    """NOT used for relief. Kept as a named decision record: integration shared
    code (run_scenarios.py intents, lib_*.py) paraphrases message names in
    prose, so putting it in the relief corpus defeats the guard (measured:
    '越出'/'未物化' both survive in intent texts). A pin targeting a
    shared-code-produced string (the one known case: run_scenarios' 只跑点名
    face, pinned by t260930-01) goes through STALE_PIN_ALLOW with a reason
    instead — explicit, silent-never."""
    return []


def _strip_py_docstrings(text):
    """Blank module/class/function docstrings (prose mentions of message names
    must not relieve a pin); raw text on any parse failure (safe direction:
    parse failure keeps prose → can only over-relieve? no — it keeps MORE text,
    i.e. may relieve a prose hit; accepted, ast covers the real corpus)."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return text
    out = text
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                seg = body[0]
                lines = text.splitlines()
                # blank by line span (1-based, inclusive)
                ln0, ln1 = seg.lineno - 1, seg.end_lineno
                for j in range(ln0, ln1):
                    if 0 <= j < len(lines):
                        lines[j] = ""
                out = "\n".join(lines)
    return out


def _strip_js_comments(text):
    """Remove /*…*/ blocks and //… line comments from js-family corpus text.
    Cannot create occurrences, so a mangling edge only errs toward red — the
    safe direction for a relief index."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def _corpus_text(p, text):
    if p.suffix == ".py":
        return _strip_py_docstrings(text)
    if p.suffix in (".mjs", ".cjs", ".js", ".ts", ".tsx", ".jsx"):
        return _strip_js_comments(text)
    return text


def lint_stale_pins(repo, errors, source_texts=None):
    """Append one error line per stale CJK pin. Returns the error count added.

    `source_texts` overrides the on-disk source index (unit-test seam: pass a
    list of strings standing in for relief-source file contents).
    """
    if source_texts is None:
        corpus = []
        for p in list(_iter_sources(repo)) + list(_iter_integration_shared(repo)):
            try:
                corpus.append(_corpus_text(p, p.read_text("utf-8", errors="replace")))
            except OSError:
                continue
        source_texts = corpus
    # relief (a'): whitespace-insensitive index — scenarios that strip()
    # persona/spec text before comparing pin whitespace-collapsed literals;
    # markdown emphasis (`**`) inside the source spec is ignored the same way
    corpus_nows = "".join(re.sub(r"[\s*]+", "", s) for s in source_texts)

    added = 0
    for p in _iter_scenario_files(repo):
        try:
            text = p.read_text("utf-8", errors="replace")
        except OSError:
            continue
        rel = p.relative_to(repo).as_posix()
        pins = collect_pins(text, filename=p.name)
        if not pins:
            continue
        # relief (b): literal occurs on a non-pin line too
        pin_lines = {ln for ln, _ in pins}
        for line_no, lit in pins:
            if any(lit in s for s in source_texts):
                continue
            if re.sub(r"[\s*]+", "", lit) in corpus_nows:
                continue
            elsewhere = any(lit in ln_text for j, ln_text in enumerate(text.splitlines(), 1)
                            if j not in pin_lines)
            if elsewhere:
                continue
            if (rel, line_no) in STALE_PIN_ALLOW:
                continue
            errors.append(
                "L22 stale pin: %s:%d pins CJK literal %r that no product source "
                "(%s) and no non-pin line of the scenario contains — the wording "
                "moved without its anchor; re-point the pin (or add a reasoned "
                "STALE_PIN_ALLOW entry)" % (rel, line_no, lit, "+".join(SOURCE_DIRS)))
            added += 1
    return added
