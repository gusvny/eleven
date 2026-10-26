"""L21 unit battery: the tier-marker lint must red a new/changed expensive-pool
registry entry that lacks the declared marker, and stay green otherwise
(t261004-42; rule source docs/reference/test-tiers-and-e2e-admission.md,
Enforcement item 1).

Shape-only contract: the check judges presence and declared shape of the
`tier:` / `cost:` tokens, never the truth of the justification. Added/changed
scope mirrors the copy-language gate, so a legacy entry without markers stays
green until its line is touched. Run:
python3 -m pytest integration/test_tier_marker_lint.py -q
(unit run, not an integration entry; external-input malformed cases ride along).
"""
import importlib.util
import pathlib

_HERE = pathlib.Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("lib_tier_marker",
                                               _HERE / "lib_tier_marker.py")
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

GOOD = ("seam: panel write gate answers before the ledger opens, harness seam "
        "over the production route (t261004-42) cost: seconds")


def entries(*triples):
    return list(triples)


def reg_file(*entry_blocks):
    """A synthetic registry file body: 4-space `("name",` entry starts."""
    return "SCENARIOS = [\n" + "\n".join(entry_blocks) + "\n]\n"


E1 = '    ("sc-a",\n     "intent one",\n     "python3 x.py", "engine"),'
E2 = '    ("sc-b",\n     "intent two",\n     "python3 y.py", "ro"),'


def diff_for(path, *added, start=2):
    return ("--- a/%s\n+++ b/%s\n@@ -1,0 +%d,%d @@\n"
            % (path, path, start, len(added)) + "".join("+" + a + "\n" for a in added))


# ---- marker_defects: the declared grammar ----------------------------------

def test_well_formed_marker_is_clean():
    assert mod.marker_defects("prefix tier: harness seam over the write gate "
                              "cost: seconds suffix") == []


def test_missing_tier_token_is_named():
    d = mod.marker_defects("no marker here at all")
    assert any("tier: token missing" in x for x in d) and any("cost: token missing" in x for x in d), d


def test_missing_cost_token_is_named():
    d = mod.marker_defects("tier: the seam")
    assert any("cost: token missing" in x for x in d) and not any("tier:" in x for x in d), d


def test_cost_out_of_vocabulary_is_named():
    d = mod.marker_defects("tier: the seam cost: hours")
    assert any("cost:" in x and "seconds/minutes" in x for x in d), d


def test_empty_tier_value_is_named():
    d = mod.marker_defects("tier: cost: seconds")
    assert any("tier: value empty" in x for x in d), d


# ---- check_registry: expensive-pool + changed-only scope -------------------

def test_changed_expensive_entry_without_marker_reds_named():
    got = mod.check_registry([("sc-a", "no markers", "engine")], {"sc-a"})
    assert got == ["sc-a: tier: token missing (name the seam or the journey)",
                   "sc-a: cost: token missing (declare the runtime class)"], got


def test_changed_cheap_entry_needs_no_marker():
    assert mod.check_registry([("sc-b", "no markers", "ro")], {"sc-b"}) == []
    assert mod.check_registry([("sc-b", "no markers", "main")], {"sc-b"}) == []
    assert mod.check_registry([("sc-b", "no markers", "serial")], {"sc-b"}) == []


def test_unchanged_legacy_expensive_entry_stays_green():
    assert mod.check_registry([("sc-a", "no markers", "engine")], set()) == []
    assert mod.check_registry([("sc-a", "no markers", "browser")], {"sc-other"}) == []


def test_each_expensive_pool_is_in_scope():
    for pool in mod.EXPENSIVE_POOLS:
        got = mod.check_registry([("sc-x", "no markers", pool)], {"sc-x"})
        assert got, pool


def test_changed_entry_with_good_marker_is_clean():
    assert mod.check_registry([("sc-a", "tier: the journey cost: minutes",
                                "exclusive")], {"sc-a"}) == []


def test_defect_lines_name_scenario_and_part():
    got = mod.check_registry([("sc-a", "tier: cost: parsecs", "browser")], {"sc-a"})
    assert all(l.startswith("sc-a: ") for l in got) and len(got) == 2, got


# ---- changed_entry_names: added-line to entry mapping ----------------------

def test_added_entry_is_changed():
    text = reg_file(E1, E2)
    diff = diff_for(mod.REGISTRY_REL, '    ("sc-a",', '     "intent one",')
    assert mod.changed_entry_names(text, diff) == {"sc-a"}


def test_intent_only_rewrite_marks_that_entry_changed():
    # E2's intent line sits on file line 6 (header line 1, E1 spans 2-4)
    text = reg_file(E1, E2)
    diff = diff_for(mod.REGISTRY_REL, '     "intent two REWRITTEN",', start=6)
    assert mod.changed_entry_names(text, diff) == {"sc-b"}


def test_untouched_entries_stay_out():
    text = reg_file(E1, E2)
    diff = diff_for("some/other.py", "+whatever")
    assert mod.changed_entry_names(text, diff) == set()


def test_diff_for_other_path_is_ignored():
    text = reg_file(E1)
    diff = diff_for("integration/elsewhere.py", '    ("sc-a",')
    assert mod.changed_entry_names(text, diff) == set()


def test_garbage_diff_is_no_crash_no_invention():
    text = reg_file(E1)
    for garbage in ("", "\n\n\n", "not a diff", "@@ -1 +1 @@\n+stray hunk"):
        assert mod.changed_entry_names(text, garbage) == set(), garbage


def test_last_entry_without_trailing_start_is_mapped():
    text = reg_file(E1, E2)
    diff = diff_for(mod.REGISTRY_REL, '     "python3 y.py", "ro"),', start=7)
    assert mod.changed_entry_names(text, diff) == {"sc-b"}


# ---- mechanical interpreter swap is NOT a change (t261026-35) --------------

def _replace_diff(path, old, new, old_start=7):
    """A unified diff hunk with a real -/+ replacement pair at one position."""
    return ("--- a/%s\n+++ b/%s\n@@ -%d,1 +%d,1 @@\n-%s\n+%s\n"
            % (path, path, old_start, old_start, old, new))


def test_interpreter_only_swap_is_not_a_change():
    # t261026-35: migrating the launch prefix to the shared helper does not
    # make the entry tier-relevant — the script, pool and intent are the same
    text = reg_file(E1, E2)
    diff = _replace_diff(mod.REGISTRY_REL,
                         '     "python3 y.py", "ro"),',
                         '     "sh integration/py_interp.sh y.py", "ro"),')
    assert mod.changed_entry_names(text, diff) == set()

def test_strip_launch_prefix_normalizes_known_shapes():
    old = ('"PY=server/engine/.venv/bin/python; [ -x \\"$PY\\" ] || PY=python3; '
           '\\"$PY\\" -B integration/x/sc.py", "ro"),')
    new = '"sh integration/py_interp.sh integration/x/sc.py", "ro"),'
    assert mod.strip_launch_prefix(old) == mod.strip_launch_prefix(new)
    assert mod.strip_launch_prefix(old) != ""


def test_pool_change_on_cmd_line_still_reds():
    # the gate keeps its tooth: a pool move IS an admission-relevant change
    # (file_text carries the NEW line, as a real working tree would)
    text = reg_file(E1, E2.replace('"python3 y.py", "ro"),',
                                   '"python3 y.py", "engine"),'))
    diff = _replace_diff(mod.REGISTRY_REL,
                         '     "python3 y.py", "ro"),',
                         '     "python3 y.py", "engine"),')
    assert mod.changed_entry_names(text, diff) == {"sc-b"}
