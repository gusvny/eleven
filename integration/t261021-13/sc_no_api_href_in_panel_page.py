#!/usr/bin/env python3
"""sc_no_api_href_in_panel_page.py — t261021-13 static sweep guard: no anchor in
the executor-panel page source may point straight at an api/ route.

Intent (grey-box L3, offline seconds, read-only, zero docker/browser, never
touches 3099/7233): the incident's cause was the page's ONLY href aiming at
/sandbar-workbench/api/... (the epic doc link), which made the browser render a
raw JSON envelope. The ticket's sweep rule is "no anchor anywhere in this page
may point straight at an api/ route". This entry keeps that rule enforced
independently of the browser stack, so the sweep cannot go silently unchecked
when playwright/chromium are missing (the KI-036 env-red-covering-real-red
family; anchor semantics by shape, not copy literals — KI-051 discipline).

A1 the page module exists and is readable.
A2 the detector finds zero `href=".../api/..."` occurrences in the page source
   (green after the fix; red before it — the expected TDD signal).
A3 negative control: the same detector over a synthetic snippet carrying such
   an href DOES flag it — the guard can detect the incident shape by
   construction, so a detector regression cannot masquerade as a green sweep.
A4 the synthetic snippet is judged in memory only; the real tree is never
   mutated (byte-compare of the page file before/after).

Page module missing/unreadable = FAIL named (TDD-phase red expected;
arbitrate/merge must be green). ENV_FAIL exit 2 is not reachable here (pure
stdlib file read); an unreadable file is a named FAIL, not an env failure.
"""
import sys
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
PAGE = REPO / "server/plugins/executor-panel/src/host/panel-page.ts"

results = []


def case(name, ok, reason=""):
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {reason}" if reason else ""))


def api_hrefs(text):
    """Every href=" value in the text that aims at an api/ route."""
    import re
    return re.findall(r'href="[^"]*/api/[^"]*"', text)


def main():
    case("A1-page-module-readable", PAGE.is_file(), f"target={PAGE}")
    if not PAGE.is_file():
        finish()
    before = PAGE.read_bytes()
    src = before.decode("utf-8", errors="replace")

    found = api_hrefs(src)
    case("A2-no-api-href-in-page-source", len(found) == 0,
         (f"api-aimed hrefs in page source: {found}" if found else "no href targets an api/ route"))

    snippet = '<a href="/sandbar-workbench/api/wf/docs/doc?scope=docs">x</a>'
    case("A3-detector-flags-incident-shape", len(api_hrefs(snippet)) == 1,
         f"detector found {len(api_hrefs(snippet))} hit(s) in the synthetic incident snippet (expected 1)")

    case("A4-tree-unmutated", PAGE.read_bytes() == before, "page file byte-identical after the sweep")
    finish()


def finish():
    fail = results.count(False)
    env = 0
    print(f"SUMMARY pass={len(results) - fail} fail={fail} env_fail={env} na=0")
    sys.exit(2 if env else (1 if fail else 0))


if __name__ == "__main__":
    main()
