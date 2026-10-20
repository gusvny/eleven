"""t261016-11 ③: the self-consistency floor of the foreign repair.

Measured defect: the repair deleted `server/engine/foreign_write.py` (absent on
main) while `agent_activities.py` kept `import foreign_write` — the tree could
no longer import its own engine (the round's reds and a 900 s hang followed).
`foreign_write.importers_remain` is the pure floor: a removal whose importers
remain must refuse the WHOLE repair, by name, with zero tree writes.

Batteries: dict-backed injected reader (repo-free truth tables) plus real
tempfile-tree cases (the default reader face) and the deformed-input set.
"""
import importlib.util
import os
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
MOD = os.path.join(HERE, os.pardir, "foreign_write.py")


def _load():
    spec = importlib.util.spec_from_file_location("foreign_write_ut3", MOD)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


fw = _load()


def _reader(files):
    """Content injected by file suffix; enumeration still walks a REAL tree
    (the function's contract: tree_root gives the file list, read_text the
    bytes) — each dict-based case plants real empty files via tmp_path."""
    def read(path):
        for k, v in files.items():
            if path.endswith(k):
                return v
        return None
    return read


def _tree(tmp_path, names):
    for n in names:
        f = tmp_path / n
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("", "utf-8")
    return str(tmp_path)


def test_importer_of_removed_module_is_named(tmp_path):
    files = {"app.py": "import foreign_write\n", "other.py": "x = 1\n"}
    root = _tree(tmp_path, files.keys())
    out = fw.importers_remain(root, ["server/engine/foreign_write.py"],
                              read_text=_reader(files))
    assert ("app.py", "server/engine/foreign_write.py") in out, out
    assert len(out) == 1, out


def test_from_import_and_dotted_module_named(tmp_path):
    files = {"a.py": "from engine.tools import wrench\n",
             "b.py": "import engine.tools\n"}
    root = _tree(tmp_path, files.keys())
    out = fw.importers_remain(root, ["engine/tools.py"],
                              read_text=_reader(files))
    got = {imp for imp, _mod in out}
    assert got == {"a.py", "b.py"}, out


def test_no_importers_means_removal_may_proceed(tmp_path):
    files = {"a.py": "x = 1\n"}
    root = _tree(tmp_path, files.keys())
    assert fw.importers_remain(root, ["gone.py"],
                               read_text=_reader(files)) == []


def test_submodule_import_matches_parent_module_path(tmp_path):
    files = {"a.py": "import pkg.tools.helper\n"}
    root = _tree(tmp_path, files.keys())
    out = fw.importers_remain(root, ["pkg/tools/helper.py"],
                              read_text=_reader(files))
    assert ("a.py", "pkg/tools/helper.py") in out, out


def test_unparseable_file_counts_as_unknown_importer(tmp_path):
    files = {"broken.py": "def (:\n"}
    root = _tree(tmp_path, files.keys())
    out = fw.importers_remain(root, ["m.py"], read_text=_reader(files))
    assert ("broken.py", "<unparseable>") in out, out


def test_unreadable_file_counts_as_unknown_importer(tmp_path):
    root = _tree(tmp_path, ["a.py"])
    out = fw.importers_remain(root, ["m.py"],
                              read_text=lambda p: None)
    assert out and out[0][1] == "<unreadable>", out


def test_reader_fault_counts_as_unknown_importer(tmp_path):
    def boom(_p):
        raise OSError("fault injected")
    root = _tree(tmp_path, ["a.py"])
    out = fw.importers_remain(root, ["m.py"], read_text=boom)
    assert out and out[0][1] == "<unreadable>", out


def test_malformed_module_path_still_refuses(tmp_path):
    root = _tree(tmp_path, ["a.py"])
    out = fw.importers_remain(root, [""], read_text=_reader({}))
    assert out and out[0][0] == "<malformed>", out  # named, not silently repaired
    out2 = fw.importers_remain(root, [None], read_text=_reader({}))
    assert out2 and out2[0][0] == "<malformed>", out2


def test_non_module_path_named(tmp_path):
    root = _tree(tmp_path, ["a.py"])
    out = fw.importers_remain(root, ["notes/x.md"], read_text=_reader({}))
    assert out and "<not-a-module>" in out[0], out


def test_duplicate_reporting_is_deduped(tmp_path):
    files = {"a.py": "import m\nfrom m import x\n"}
    root = _tree(tmp_path, files.keys())
    out = fw.importers_remain(root, ["m.py"], read_text=_reader(files))
    assert out == [("a.py", "m.py")], out


def test_real_tree_default_reader(tmp_path):
    (tmp_path / "a.py").write_text("import foreign_write\n", "utf-8")
    sub = tmp_path / "pkg"
    sub.mkdir()
    (sub / "b.py").write_text("x = 1\n", "utf-8")
    out = fw.importers_remain(tmp_path, ["server/engine/foreign_write.py"])
    assert ("a.py", "server/engine/foreign_write.py") in out, out


def test_real_tree_ignores_non_py_and_dotdirs(tmp_path):
    (tmp_path / "a.txt").write_text("import m\n", "utf-8")
    dot = tmp_path / ".git"
    dot.mkdir()
    (dot / "c.py").write_text("import m\n", "utf-8")
    assert fw.importers_remain(tmp_path, ["m.py"]) == []


def test_real_tree_syntax_error_named(tmp_path):
    (tmp_path / "broken.py").write_text("def (:\n", "utf-8")
    out = fw.importers_remain(tmp_path, ["m.py"])
    assert ("broken.py", "<unparseable>") in out, out


def test_binary_file_counts_unknown(tmp_path):
    (tmp_path / "b.py").write_bytes(b"\xff\xfe\x00import m\x00")
    out = fw.importers_remain(tmp_path, ["m.py"])
    assert out and out[0][1] in ("<unparseable>", "<unreadable>"), out


def test_empty_tree_empty_paths():
    with tempfile.TemporaryDirectory() as d:
        assert fw.importers_remain(d, []) == []
