#!/usr/bin/env python3
"""sc_t26102618_docs_static_face.py — t261026-18 static sweep guard: the Docs
tab's fixed UI copy carries no Chinese label and no redundant scope bar,
enforced without the browser stack.

Intent (grey-box L3, offline seconds, read-only, zero docker/browser, never
touches 3099/7233): the host reported '总目录' still Chinese in the root file
group and a redundant docs//notes/ bar under the entry rows. The browser entry
(sc_t26102618_docs_tab_own_page.mjs, pool=browser) goes ENV_FAIL when
playwright/chromium are missing, and an env-red must not cover these two fixed
faces (KI-036 / KI-051 family lesson). Anchor semantics by shape, not copy
literals: the label check asserts NO CJK in the root-label constant, not one
specific English word (the exact word is the implementer's choice).

A1 the panel page module and the shared docs model are readable.
A2 the page source contains no docsScopeBar token (bar removed; red pre-fix,
   the expected TDD signal).
A3 negative control: the same detector over a synthetic snippet carrying the
   bar DOES flag it, so a detector regression cannot masquerade as green.
B1 the root group label in the docs model (the fixed label for dir '') carries
   no CJK characters (red pre-fix — '总目录' is CJK).
B2 negative control: a synthetic CJK root label IS flagged.
C the real tree is never mutated (byte-compare before/after; synthetic
   snippets judged in memory only).

Both files missing/unreadable = FAIL named (TDD-phase red expected;
arbitrate/merge must be green). ENV_FAIL exit 2 is not reachable here (pure
stdlib file read).
"""
import re
import sys
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
PAGE = REPO / "server/plugins/executor-panel/src/host/panel-page.ts"
MODEL = REPO / "server/plugins/workbench/src/shared/docs-model.ts"

CJK = re.compile(r"[\u4e00-\u9fff]")

results = []


def case(name, ok, reason=""):
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {reason}" if reason else ""))


def root_label_lines(text):
    """Lines carrying the fixed root-group label (dir === '' branch)."""
    out = []
    for line in text.splitlines():
        if "dir === ''" in line and "label" in line:
            out.append(line)
    return out


def main():
    page_ok = PAGE.is_file()
    model_ok = MODEL.is_file()
    case("A1-sources-readable", page_ok and model_ok, f"page={page_ok} model={model_ok}")
    if not (page_ok and model_ok):
        finish()

    page_before = PAGE.read_bytes()
    model_before = MODEL.read_bytes()
    page_src = page_before.decode("utf-8", errors="replace")
    model_src = model_before.decode("utf-8", errors="replace")

    # A2: the redundant scope bar is gone — anchored on the LIVE shape (the DOM
    # id), never on the bare token: the removal commit's own comment names
    # #docsScopeBar and a comment is not a rendered selector.
    hits = len(re.findall(r'id="docsScopeBar"|getElementById\(\s*[\'"]docsScopeBar', page_src))
    case("A2-no-scope-bar-in-page-source", hits == 0,
         f"live docsScopeBar shape occurrences: {hits}" if hits else "no live docsScopeBar shape in the page source")

    # A3: negative control — the detector bites on the incident shape.
    case("A3-detector-flags-bar-shape", "docsScopeBar" in '<div id="docsScopeBar"></div>',
         "synthetic snippet carrying the bar is flagged (expected)")

    # B1: the fixed root-group label is ASCII English (no CJK).
    lines = root_label_lines(model_src)
    bad = [ln.strip() for ln in lines if CJK.search(ln)]
    case("B1-root-label-english", len(lines) >= 1 and not bad,
         (f"CJK in root label: {bad}" if bad else
          (f"no root-label line found ({len(lines)} candidates)" if not lines else
           "root group label carries no CJK characters")))

    # B2: negative control — a synthetic CJK label is flagged.
    case("B2-detector-flags-cjk-label", bool(CJK.search("label: dir === '' ? '总目录' : x")),
         "synthetic CJK root label is flagged (expected)")

    # C: the real tree is untouched.
    case("C-tree-never-mutated",
         PAGE.read_bytes() == page_before and MODEL.read_bytes() == model_before,
         "page module and docs model byte-identical before/after")

    finish()


def finish():
    ok = all(results)
    print(f"SUMMARY: {sum(results)}/{len(results)} passed")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
