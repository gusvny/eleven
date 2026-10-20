"""t261016-11 ②: the line is not a lane — pure-predicate battery.

The foreign-repair face (t261012-09) deleted landed line content because it was
"absent on main" (measured: engine commit bb73e620 removed 1160 lines the line
legitimately carries). `foreign_write.line_owned` + the `line_owned=` injection
into `foreign_files` close that hole. These tests are repo-free: every IO seam
is an injected callable.

Loaded by file path (no engine package import needed): the module is
stdlib-only by contract.
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.join(HERE, os.pardir, "foreign_write.py")


def _load():
    spec = importlib.util.spec_from_file_location("foreign_write_ut", MOD)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


fw = _load()


def _blob(path, ref):
    """Deterministic fake blob lookup: content keyed by (ref, path)."""
    return {(ref, path): "%s:%s" % (ref, path)}.get((ref, path))


def test_line_owned_hash_equal_is_true():
    assert fw.line_owned("server/engine/foreign_write.py", "develop:h",
                         lambda p, r: "develop:h", ["develop"]) is True


def test_line_owned_hash_mismatch_is_false():
    # landed on the line but the tree's copy differs (post-landing edit):
    # fail-closed to the pre-fix verdict, the repair may judge it foreign.
    assert fw.line_owned("p", "tree-h", lambda p, r: "line-h", ["develop"]) is False


def test_line_owned_absent_on_line_is_false():
    assert fw.line_owned("p", "h", lambda p, r: None, ["develop"]) is False


def test_line_owned_empty_line_refs_is_false():
    # no line candidates known => never claims line ownership (no relaxation)
    assert fw.line_owned("p", "h", lambda p, r: "h", []) is False
    assert fw.line_owned("p", "h", lambda p, r: "h", None) is False


def test_line_owned_malformed_inputs_are_false():
    assert fw.line_owned("", "h", lambda p, r: "h", ["develop"]) is False
    assert fw.line_owned(None, "h", lambda p, r: "h", ["develop"]) is False
    assert fw.line_owned("p", "", lambda p, r: "h", ["develop"]) is False
    assert fw.line_owned("p", None, lambda p, r: "h", ["develop"]) is False


def test_line_owned_dict_refs_supported():
    assert fw.line_owned("p", "h", lambda p, r: "h",
                         [{"ref": "develop", "ticket": "x"}]) is True
    assert fw.line_owned("p", "h", lambda p, r: "h",
                         [{"nope": 1}]) is False


def test_foreign_files_line_owned_excluded_from_verdict():
    changed = ["stray_main_lacks.py", "server/engine/foreign_write.py",
               "integration/t261012-09/sc_x.py"]
    out = fw.foreign_files(changed, ["own/"],
                           line_owned=lambda p: p != "stray_main_lacks.py")
    assert out == ["stray_main_lacks.py"], out


def test_foreign_files_without_line_face_keeps_old_verdict():
    # backward compatible: no injection => byte-identical to the old caliber
    changed = ["own/work.txt", "stray.txt"]
    assert fw.foreign_files(changed, ["own/"]) == ["stray.txt"]


def test_foreign_files_faulting_line_predicate_never_foreign():
    def boom(_p):
        raise RuntimeError("fault injected")
    # landing semantics: a faulting predicate is never a foreign verdict —
    # the path drops out of the foreign list (deletion is the dangerous side)
    assert fw.foreign_files(["stray.txt"], ["own/"], line_owned=boom) == []


def test_foreign_files_line_exclusion_order_after_existing_faces():
    # runtime prefixes, notes and protected paths stay excluded regardless of
    # the new predicate; the new exclusion never widens the foreign set.
    changed = [".sandbar/x", "notes/k.md", "verify.yaml", "own/a", "b"]
    out = fw.foreign_files(changed, ["own/"], protected_paths=("verify.yaml",),
                           line_owned=lambda p: p == "b")
    assert out == [], out  # own/a is in-set; every other face excludes its own


def test_importers_remain_readme_pointer():
    # the module docstring states the floor; assert the contract words exist so
    # a silent rewrite of the refusal stance is caught by this battery too.
    doc = (fw.importers_remain.__doc__ or "") + (fw.line_owned.__doc__ or "")
    assert "refused" in doc
    assert "line is not a lane" in fw.line_owned.__doc__
