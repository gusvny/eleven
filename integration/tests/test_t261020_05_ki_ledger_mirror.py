# -*- coding: utf-8 -*-
"""261020: the KI ledger gets a machine-readable mirror, derived from the prose.

Why: `notes/debts/known-issues.md` holds 326 answers in prose (two id shapes, a
markdown table for the older ones and `## KI-<ULID>` sections for the newer).
Every consumer that needed one grepped a 6000-line Chinese document — during the
261019 night the cost showed up on every fault ("already known?", "fixed?",
"which ticket?"), and two faults were re-discovered as if new.

The prose stays the source (a person writes it; host rule). The mirror is
DERIVED, and `--check` fails when the two drift, so a human edit cannot silently
disagree with what tools read.

Coverage: both id shapes are read, the status comes from what the records say
(table cell, section marker: 未修 => open / 已修 => fixed), unknown status stays
open (never guessed fixed), the section title is stripped of markdown and cut at
the provenance parenthetical, and drift is named in both directions plus per-id.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import ki_ledger as kl  # noqa: E402

PROSE = """
| 编号 | 标题 | 严重度 | 状态 | 定位 |
| --- | --- | --- | --- | --- |
| KI-001 | an old open finding | 非阻塞 | open | a.py:1 |
| KI-003 | an old fixed finding | 非阻塞 | fixed | b.py:2 |

## KI-01ABC **a new finding**（261020 实测定性；未修）

## KI-01ABD **another new one**（261020；已修 `deadbeef`）
"""


def _rows():
    return kl.parse(PROSE)["rows"]


def test_both_id_shapes_are_read():
    rows = _rows()
    assert set(rows) == {"KI-001", "KI-003", "KI-01ABC", "KI-01ABD"}


def test_table_status_is_read():
    rows = _rows()
    assert rows["KI-001"]["status"] == "open"
    assert rows["KI-003"]["status"] == "fixed"


def test_section_markers_decide_the_status():
    rows = _rows()
    assert rows["KI-01ABC"]["status"] == "open", "未修 is open"
    assert rows["KI-01ABD"]["status"] == "fixed", "已修 is fixed"


def test_an_unknown_status_is_never_guessed_fixed():
    rows = kl.parse("## KI-01ZZZ some finding without a marker\n")["rows"]
    assert rows["KI-01ZZZ"]["status"] == "open"


def test_the_section_title_is_clean():
    rows = _rows()
    assert rows["KI-01ABC"]["title"] == "a new finding", \
        "markdown bold and the provenance parenthetical are not the claim"
    assert rows["KI-01ABD"]["title"] == "another new one"


def test_the_mirror_round_trips_clean():
    parsed = kl.parse(PROSE)
    mirror = kl.render(parsed)
    assert kl.drift(parsed, mirror) == []


def test_drift_is_named_in_both_directions():
    parsed = kl.parse(PROSE)
    mirror = kl.render(parsed)
    # a prose-only addition
    more = kl.parse(PROSE + "\n## KI-01NEW a fresh finding\n")
    d1 = kl.drift(more, mirror)
    assert any("KI-01NEW" in p and "not in the mirror" in p for p in d1)
    # a mirror-only leftover
    gone = kl.parse(PROSE.split("## KI-01ABD")[0])
    d2 = kl.drift(gone, mirror)
    assert any("KI-01ABD" in p and "no longer has it" in p for p in d2)


def test_a_status_change_is_drift():
    parsed = kl.parse(PROSE)
    mirror = kl.render(parsed).replace('"status": "fixed"', '"status": "open"')
    d = kl.drift(parsed, mirror)
    assert any("status drift" in p for p in d)


def test_a_broken_mirror_line_is_named_not_skipped():
    parsed = kl.parse(PROSE)
    assert any("not JSON" in p for p in kl.drift(parsed, "{not json\n"))


def test_the_real_ledger_is_in_sync():
    """The repo's own ledger must be clean — a stale mirror is a red, not a note."""
    rc = kl.main(["--check"])
    assert rc == 0
