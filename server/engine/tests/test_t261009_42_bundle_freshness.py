"""t261009-42 — the bundle freshness check rebuilds and compares, not diff-counts.

The ticket's question: merge-check item 3.5 approximated "is the shipped bundle
stale?" with "did the out prefix change in the lane diff?" — those are not the
same question. A type-only change or a new unreferenced file can never move a
byte-identical bundle, so the red was unsatisfiable. Now, when a declared
`entry:` exists, the check rebuilds the declared chain in a temp copy of the
lane and byte-compares (the accepted t261009-39 method); three states:

  - rebuilt-and-identical  → green ("it did not change" is a fact, not an offence)
  - rebuilt-and-different  → red, stale (the check's whole purpose; kept)
  - could-not-establish    → degraded = today's verdict, NAMED, never "assumed fresh"

A pair without `entry:` keeps today's diff-based verdict (fail-closed, spec 3).

Offline unit face: the build entry is a fixture stub (no npm/network/node);
every case runs in tmp_path with hard timeouts and full teardown on all
terminal paths. Malformed-input hooks: torn/absent committed out file,
malformed `entry:` key, timeout stub, non-zero-exit stub.
"""
import os
import stat
import textwrap
from pathlib import Path

import agent_activities as aa

REPO = Path(__file__).resolve().parents[3]


def _decl(pairs_text: str) -> str:
    return pairs_text


# ---------------------------------------------------------------- entry reader

def test_entry_reader_aligns_keys_with_pairs_by_order() -> None:
    """review_plan gen1 note 1: two declared pairs, keys only on the second —
    the entry must attach to pair #1, not pair #0."""
    text = textwrap.dedent("""\
        bundle_pairs:
          - src: server/plugins/a/src/
            out: server/plugins/a/lib/
          - src: server/plugins/b/src/
            out: server/plugins/b/lib/
            entry: server/plugins/b/build.sh
            budget_s: 90
        """)
    entries, diag = aa._read_bundle_entry_keys(text, 2)
    assert diag == ""
    assert entries[0] is None
    assert entries[1] == ("server/plugins/b/build.sh", 90)


def test_entry_reader_no_keys_returns_all_none() -> None:
    text = "bundle_pairs:\n  - src: a/\n    out: b/\n"
    entries, diag = aa._read_bundle_entry_keys(text, 1)
    assert diag == ""
    assert entries == [None]


def test_entry_reader_malformed_keys_fail_closed_named() -> None:
    cases = {
        "before_any_pair": "bundle_pairs:\n  entry: x.sh\n  - src: a/\n    out: b/\n",
        "duplicate": "bundle_pairs:\n  - src: a/\n    out: b/\n    entry: x.sh\n    entry: y.sh\n",
        "empty_value": "bundle_pairs:\n  - src: a/\n    out: b/\n    entry:\n",
        "budget_without_entry": "bundle_pairs:\n  - src: a/\n    out: b/\n    budget_s: 9\n",
        "non_integer_budget": "bundle_pairs:\n  - src: a/\n    out: b/\n    entry: x.sh\n    budget_s: soon\n",
    }
    for name, text in cases.items():
        entries, diag = aa._read_bundle_entry_keys(text, 1)
        assert entries == [], name
        assert diag, name  # named, non-empty diag


def test_entry_reader_count_mismatch_fails_closed() -> None:
    """review_plan gen1 note 1: keys reader vs parser pair-count mismatch is a
    named degradation, never a wrong-chain attachment."""
    text = "bundle_pairs:\n  - src: a/\n    out: b/\n    entry: x.sh\n"
    entries, diag = aa._read_bundle_entry_keys(text, 2)  # parser saw 2 pairs
    assert entries == []
    assert "saw 1 `- src:` lines, parser saw 2 pairs" in diag


def test_strip_optional_keys_fixes_parse_seam() -> None:
    """Integration round 1 code-fault: the strict parser raises on `entry:` /
    `budget_s:` lines before the tolerant reader runs. The strip helper must make
    the strict parse succeed on a decorated declaration (the composition seam)."""
    import pytest
    text = ("bundle_pairs:\n"
            "  - src: a/\n"
            "    out: b/\n"
            "    entry: tools/build-bundle.sh\n"
            "    budget_s: 90\n")
    with pytest.raises(ValueError):
        aa._parse_bundle_pairs(text)          # strict parser alone rejects it
    pairs = aa._parse_bundle_pairs(aa._strip_bundle_optional_keys(text))
    assert pairs == [("a/", "b/")]            # ...and composes after the strip
    entries, diag = aa._read_bundle_entry_keys(text, len(pairs))
    assert diag == "" and entries == [("tools/build-bundle.sh", 90)]


def test_strip_keeps_fail_closed_on_genuinely_unknown_lines() -> None:
    """Only the two declared key names are stripped — any other unknown line
    still reaches the strict parser and still raises (no new back door)."""
    import pytest
    text = "bundle_pairs:\n  - src: a/\n    out: b/\n    rogue: x\n"
    with pytest.raises(ValueError):
        aa._parse_bundle_pairs(aa._strip_bundle_optional_keys(text))


# ---------------------------------------------------------------- rebuild helper

def _write_stub(repo: Path, rel: str, body: str) -> Path:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(body).lstrip(), "utf-8")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return p


def _make_repo(tmp_path: Path, committed: bytes) -> Path:
    repo = tmp_path / "repo"
    _write_stub(repo, "server/plugins/w/build.sh", """\
        #!/usr/bin/env bash
        set -euo pipefail
        cd "$(dirname "$0")"
        printf '%s' "$BUNDLE_STUB_OUTPUT" > lib/client.js
        """)
    (repo / "server/plugins/w/lib").mkdir(parents=True)
    (repo / "server/plugins/w/lib/client.js").write_bytes(committed)
    return repo


def test_rebuild_identical_is_green(tmp_path, monkeypatch) -> None:
    repo = _make_repo(tmp_path, b"same-bytes")
    monkeypatch.setenv("BUNDLE_STUB_OUTPUT", "same-bytes")
    state, detail, diff = aa._bundle_freshness_rebuild(
        repo, "server/plugins/w/lib/", "server/plugins/w/build.sh", 60)
    assert state == "rebuilt-and-identical"
    assert diff == []
    assert "byte-identical" in detail


def test_rebuild_different_is_red_named(tmp_path, monkeypatch) -> None:
    repo = _make_repo(tmp_path, b"committed-old")
    monkeypatch.setenv("BUNDLE_STUB_OUTPUT", "fresh-bytes")
    state, detail, diff = aa._bundle_freshness_rebuild(
        repo, "server/plugins/w/lib/", "server/plugins/w/build.sh", 60)
    assert state == "rebuilt-and-different"
    assert diff == ["client.js"]
    assert "client.js" in detail and "stale" in detail


def test_rebuild_missing_committed_file_is_malformed_input_red(tmp_path, monkeypatch) -> None:
    """Malformed-input hook: the committed out file is absent — not a green."""
    repo = _make_repo(tmp_path, b"x")
    (repo / "server/plugins/w/lib/client.js").unlink()
    monkeypatch.setenv("BUNDLE_STUB_OUTPUT", "x")
    state, detail, diff = aa._bundle_freshness_rebuild(
        repo, "server/plugins/w/lib/", "server/plugins/w/build.sh", 60)
    assert state == "rebuilt-and-different"
    assert diff == ["client.js"]


def test_rebuild_entry_missing_is_degraded_named(tmp_path) -> None:
    repo = _make_repo(tmp_path, b"x")
    state, detail, diff = aa._bundle_freshness_rebuild(
        repo, "server/plugins/w/lib/", "server/plugins/w/absent.sh", 60)
    assert state == "could-not-establish"
    assert diff == []
    assert "not found" in detail


def test_rebuild_nonzero_exit_is_degraded_named(tmp_path, monkeypatch) -> None:
    repo = _make_repo(tmp_path, b"x")
    _write_stub(repo, "server/plugins/w/build.sh", """\
        #!/usr/bin/env bash
        echo "offline npm ci fail" >&2
        exit 1
        """)
    monkeypatch.delenv("BUNDLE_STUB_OUTPUT", raising=False)
    state, detail, _ = aa._bundle_freshness_rebuild(
        repo, "server/plugins/w/lib/", "server/plugins/w/build.sh", 60)
    assert state == "could-not-establish"
    assert "exited 1" in detail


def test_rebuild_timeout_is_degraded_named_not_a_hang(tmp_path, monkeypatch) -> None:
    repo = _make_repo(tmp_path, b"x")
    _write_stub(repo, "server/plugins/w/build.sh", """\
        #!/usr/bin/env bash
        sleep 30
        """)
    monkeypatch.delenv("BUNDLE_STUB_OUTPUT", raising=False)
    state, detail, _ = aa._bundle_freshness_rebuild(
        repo, "server/plugins/w/lib/", "server/plugins/w/build.sh", 1)
    assert state == "could-not-establish"
    assert "budget" in detail


def test_rebuild_tolerates_broken_symlink_in_tree(tmp_path, monkeypatch) -> None:
    """A broken symlink in the copied tree must not fail the copy (observed shape:
    .dsh/profiles/* dangling links) — the verdict stays judged by the build."""
    repo = _make_repo(tmp_path, b"same")
    link = repo / "server/plugins/w/dangling"
    link.symlink_to("no-such-target-anywhere")
    monkeypatch.setenv("BUNDLE_STUB_OUTPUT", "same")
    state, detail, _ = aa._bundle_freshness_rebuild(
        repo, "server/plugins/w/lib/", "server/plugins/w/build.sh", 60)
    assert state == "rebuilt-and-identical", detail


def test_rebuild_never_says_assumed_fresh(tmp_path, monkeypatch) -> None:
    """Every degraded detail names the failed step and never claims freshness."""
    repo = _make_repo(tmp_path, b"x")
    details = []
    for entry, out in (("server/plugins/w/absent.sh", None),):
        details.append(aa._bundle_freshness_rebuild(repo, "server/plugins/w/lib/", entry, 60)[1])
    _write_stub(repo, "server/plugins/w/build.sh", "#!/usr/bin/env bash\nexit 3\n")
    details.append(aa._bundle_freshness_rebuild(
        repo, "server/plugins/w/lib/", "server/plugins/w/build.sh", 60)[1])
    for d in details:
        assert "could not be established" in d
        assert "assumed fresh" not in d and "presumed fresh" not in d


def test_rebuild_temp_copy_reaped_on_every_path(tmp_path, monkeypatch) -> None:
    """Bounds: no bundle-freshness temp dir survives any terminal path.

    t261009-60: the assertion must read only THIS test's namespace, never the
    machine-global system temp — another lane running the gate legitimately
    creates `bundle-freshness-*` there and used to false-red us (KI-01M4J0JGY
    JWCJ1Z2XD3KW431FV). Patch both TMPDIR (children inherit) and tempfile.
    tempdir (gettempdir() memoises its first answer, so the env alone is
    order-dependent). Glob the scoped root only: an unreaped dir left by the
    code under test still lands here and still reds.
    """
    import tempfile as _tf
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setattr(_tf, "tempdir", str(tmp_path))
    repo = _make_repo(tmp_path, b"x")
    aa._bundle_freshness_rebuild(repo, "server/plugins/w/lib/",
                                 "server/plugins/w/absent.sh", 60)
    monkeypatch.setenv("BUNDLE_STUB_OUTPUT", "y")
    aa._bundle_freshness_rebuild(repo, "server/plugins/w/lib/",
                                 "server/plugins/w/build.sh", 60)
    leftovers = [p for p in tmp_path.glob("bundle-freshness-*")]
    assert leftovers == []
