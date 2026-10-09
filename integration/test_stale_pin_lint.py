"""L22 stale-pin lint unit battery (t261009-02).

The lint must red a scenario pin of a CJK literal that survives nowhere it
could come from (the f5c6b9ad accident class: refusal translated, anchor left
behind), and stay green when the literal is (a) live in a product source,
(b) written by the same scenario outside pin positions, (c) explicitly exempt,
or (d) not a pin at all (message builders / untranslated messages). Runs
in-process on synthetic trees — not an integration entry. Malformed-input
cases (empty tree, empty source, broken quoting) ride along per the
external-input test rule.

Run: python3 -m pytest integration/test_stale_pin_lint.py -q
"""
import importlib.util
import pathlib

_HERE = pathlib.Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("lib_stale_pin",
                                               _HERE / "lib_stale_pin.py")
sp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sp)


def make_tree(tmp_path, scenario, sources=()):
    (tmp_path / "integration").mkdir(exist_ok=True)
    scen = tmp_path / "integration" / "sc_x.mjs"
    scen.write_text(scenario, "utf-8")
    for i, body in enumerate(sources):
        d = tmp_path / "server" / ("mod%d" % i)
        d.mkdir(parents=True, exist_ok=True)
        (d / "f.ts").write_text(body, "utf-8")
    return tmp_path


def run(repo):
    errors = []
    n = sp.lint_stale_pins(repo, errors)
    return n, errors


def test_stale_pin_is_red(tmp_path):
    repo = make_tree(tmp_path,
                     "j.ok((d.emptyReason ?? '').includes('越出'), 'label 越出')\n",
                     sources=[])  # no server dir → empty index
    n, errors = run(repo)
    assert n == 1
    assert "sc_x.mjs:1" in errors[0] and "越出" in errors[0]


def test_live_source_literal_is_green(tmp_path):
    repo = make_tree(
        tmp_path,
        "j.ok((d.emptyReason ?? '').includes('outside the repository root'), 'x')\n",
        sources=["emptyReason: `worktree is outside the repository root: ${p}`"])
    n, errors = run(repo)
    assert (n, errors) == (0, [])


def test_cjk_literal_live_in_source_is_green(tmp_path):
    # a pin of a NOT-yet-translated message must stay green (negative case)
    repo = make_tree(
        tmp_path,
        "ok('未知项目' in r.body.error, 'error precise')\n",
        sources=["raise HttpError(400, f'unknown project 未知项目: {k}')"])
    n, errors = run(repo)
    assert (n, errors) == (0, [])


def test_same_file_writer_side_is_green(tmp_path):
    # scenario writes the CJK string itself (fixture), then pins it
    scenario = ("await post({ comment: '落项目仓' })\n"
                "j.ok(saved.comment === '落项目仓', 'comment round-trips')\n")
    repo = make_tree(tmp_path, scenario, sources=[])
    n, errors = run(repo)
    assert (n, errors) == (0, [])


def test_message_builder_not_a_pin_is_green(tmp_path):
    # t260920-03:85 shape: CJK inside an f-string message builder, no pin
    repo = make_tree(
        tmp_path,
        "v.append('%s：allowlist 键越出冻结面（冻结面=%s）' % (k, f))\n",
        sources=[])
    n, errors = run(repo)
    assert (n, errors) == (0, [])


def test_membership_pins_both_sides(tmp_path):
    red = make_tree(tmp_path, "ok('未物化' in g.emptyReason, 'named')\n", sources=[])
    n, errors = run(red)
    assert n == 1
    green = make_tree(tmp_path, "ok(g in '未物化字段', 'named')\n",
                      sources=["msg = '未物化字段说明'"])
    n2, errors2 = run(green)
    assert (n2, errors2) == (0, [])


def test_exemption_table_relief(tmp_path):
    scenario = "j.ok((d.emptyReason ?? '').includes('未物化'), 'named')\n"
    repo = make_tree(tmp_path, scenario, sources=[])
    sp.STALE_PIN_ALLOW[("integration/sc_x.mjs", 1)] = "docs-only literal (t-fix)"
    try:
        n, errors = run(repo)
        assert (n, errors) == (0, [])
    finally:
        sp.STALE_PIN_ALLOW.clear()
    # without the exemption it is red again — exemption is explicit, not silent
    n3, _ = run(repo)
    assert n3 == 1


def test_malformed_inputs_no_crash(tmp_path):
    # empty scenario file, broken quoting, non-UTF8 bytes, empty literal
    (tmp_path / "integration").mkdir(parents=True)
    (tmp_path / "integration" / "a.mjs").write_bytes(b"\xff\xfe.includes('\xb9\xfe')")
    (tmp_path / "integration" / "b.mjs").write_text(".includes('未", "utf-8")
    (tmp_path / "integration" / "c.py").write_text("", "utf-8")
    (tmp_path / "integration" / "d.mjs").write_text(".includes('')\n", "utf-8")
    n, errors = run(tmp_path)
    assert n == 0
    # deeply nested scenario under a subdirectory is still found
    sub = tmp_path / "integration" / "t1"
    sub.mkdir()
    (sub / "e.mjs").write_text("ok(x.includes('越出'), 'l')\n", "utf-8")
    n2, errors2 = run(tmp_path)
    assert n2 == 1 and "t1/e.mjs:1" in errors2[0]


def test_multiple_pins_reported_individually(tmp_path):
    scenario = ("j.ok(a.includes('越出'), 'x')\n"
                "j.ok(b.includes('未物化'), 'y')\n")
    repo = make_tree(tmp_path, scenario, sources=[])
    n, errors = run(repo)
    assert n == 2 and any(":1 " in e for e in errors) and any(":2 " in e for e in errors)
