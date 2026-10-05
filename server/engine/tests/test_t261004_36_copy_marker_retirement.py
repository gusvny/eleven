"""t261004-36: the temporary `data` copy-language markers must not become permanent.

Background: the copy-language gate (integration/lint_copy_language.py) exempts a
line only when it carries a declared `copy-lang-allow:<id>` marker. The carried
engine tests of t261004-28 asserted the engine's Chinese refusal strings verbatim
and carried per-line `copy-lang-allow:` + `data` exemptions until the copy itself was
translated to English (host order 261004, settled by t261004-36).

This guard pins the retirement: after the engine's operator-visible refusal copy
was swept to English, no `copy-lang-allow:` + `data` marker may exist anywhere under
server/engine or integration. Other marker ids (`fixture`, `data` inside the
gate's own fixtures/tests that quote the marker as text) are not this ticket's
concern and are not banned here.
"""
import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SCAN_ROOTS = [REPO_ROOT / "server" / "engine", REPO_ROOT / "integration"]
_MARKER = "copy-lang-allow:" + "data"  # assembled from parts: this guard must never carry the literal
MARKER_RE = re.compile(re.escape(_MARKER) + r"\b")


def scan(roots):
    """Marker hits ("rootname/relpath:lineno" strings) under the given roots.
    Paths anchor to the SCANNED ROOT (the teeth probe scans a temp tree, so the
    anchor can never be the repo). Self is always excluded — this file documents
    the marker without carrying it as an exemption. Bytes-decoded per file (a
    decode failure is not a hit)."""
    self_path = pathlib.Path(__file__).resolve()
    hits = []
    for root in roots:
        for p in sorted(root.rglob("*")):
            if not p.is_file() or p == self_path:
                continue
            if p.suffix not in (".py", ".mjs", ".ts", ".sh", ".md"):
                continue
            try:
                text = p.read_bytes().decode("utf-8", errors="replace")
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if MARKER_RE.search(line):
                    hits.append("%s/%s:%d" % (root.name, p.relative_to(root), i))
    return hits


def test_no_temporary_data_marker_survives():
    """Zero assembled data-id markers under server/engine and integration.

    The marker id `data` stays documented in the gate for prompt/detection text;
    this ban only covers its temporary use on engine refusal-copy assertions.
    """
    hits = scan(SCAN_ROOTS)
    assert hits == [], (
        "temporary data-id copy markers must be retired once the engine "
        "refusal copy is English; found: %s" % ", ".join(hits)
    )


def test_scan_has_teeth():
    """Guard-has-teeth: the detector fires exactly once on a planted marker in
    a throwaway tree and stays silent on a clean file (t261004-36 acceptance
    round 5 caught a false green on the scenario face — a green from a detector
    never seen red is not trusted)."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="marker-teeth-") as td:
        root = pathlib.Path(td)
        dirty = root / "dirty.py"
        dirty.write_bytes(("x = 1  # " + _MARKER + "\n").encode("utf-8"))
        clean = root / "clean.py"
        clean.write_bytes(b"y = 2\n")
        hits = scan([root])
        assert [h.rsplit(":", 1)[0] for h in hits] == [root.name + "/dirty.py"], hits
        assert hits[0].endswith("dirty.py:1"), hits
