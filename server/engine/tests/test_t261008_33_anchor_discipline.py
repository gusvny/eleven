"""t261008-33 anchor discipline unit tests: the engine env single point
(ANCHOR_ENV_KNOBS strip + lane_subprocess_env injection) and the anchor guard
(shared.anchor_guard_error), L1 level, plus a decision-table parity check
against the TS mirror (server/plugins/repo-anchor.mjs).

Coverage (zero Temporal / zero docker / zero 3099; git fixtures self-contained
in tmp):
  - integ_subprocess_env: SANDBAR_REPO is stripped whether the parent env
    carries the main-checkout value, a foreign value, or nothing
    (ANCHOR_ENV_KNOBS is its own family, not folded into TEST_STUB_ENV_KNOBS);
    the pre-existing strip families do not regress; the extra injection face is
    not swallowed.
  - lane_subprocess_env: the child anchor equals the lane root in all three
    parent-env shapes.
  - anchor_guard_error: linked worktree + foreign anchor = named error naming
    SANDBAR_ANCHOR_MISMATCH with both roots and both sources; anchor equal to
    the own tree / no anchor / non-worktree own tree = pass; malformed anchors
    (empty / relative / nonexistent / symlink loop) get a verdict, never a
    crash.
  - decision-table parity: the same table fed to the Python verdict and to node
    evaluating repo-anchor.mjs must agree row by row (mirror drift = red). If
    node is unavailable the parity check skips with an explicit named reason
    (degradation declared, not silent).

Fixture reclamation: mkdtemp_reclaimed throughout (t260907-06 precedent).
"""
import subprocess
import sys
from pathlib import Path

POC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC))

import pytest  # noqa: E402
import shared  # noqa: E402
from _tmp_reclaim import mkdtemp_reclaimed  # noqa: E402

NAMED = 'SANDBAR_ANCHOR_MISMATCH'


# ---------------- fixtures ----------------

def _git(*args, cwd):
    p = subprocess.run(['git'] + list(args), cwd=str(cwd),
                       capture_output=True, text=True)
    assert p.returncode == 0, 'git %s failed: %s' % (' '.join(args), p.stderr)
    return p.stdout.strip()


@pytest.fixture
def tree_shapes():
    """Three trees: a seed repo ("main") + a genuine linked worktree (the lane
    shape) + a standalone external copy."""
    root = mkdtemp_reclaimed('t261008-33-ut-')
    seed = root / 'main'
    seed.mkdir()
    _git('init', '-b', 'main', cwd=seed)
    _git('config', 'user.email', 'ut@example.com', cwd=seed)
    _git('config', 'user.name', 'ut', cwd=seed)
    (seed / 'README.md').write_text('seed\n', encoding='utf-8')
    _git('add', '-A', cwd=seed)
    _git('commit', '-qm', 'seed', cwd=seed)
    lane = root / 'lane'
    _git('worktree', 'add', str(lane), '-b', 'lane-ut', cwd=seed)
    assert (lane / '.git').is_file()          # linked-worktree criterion
    assert (seed / '.git').is_dir()           # standalone-checkout criterion
    standalone = root / 'external-copy'
    standalone.mkdir()
    _git('init', '-b', 'main', cwd=standalone)
    return {'root': root, 'seed': seed, 'lane': lane, 'standalone': standalone}


# ---------------- L1: env single point ----------------

def _integ_env(monkeypatch, anchor):
    import agent_activities as aa
    if anchor is None:
        monkeypatch.delenv('SANDBAR_REPO', raising=False)
    else:
        monkeypatch.setenv('SANDBAR_REPO', anchor)
    return aa.integ_subprocess_env()


def test_integ_env_strips_anchor_main_value(monkeypatch, tree_shapes):
    env = _integ_env(monkeypatch, str(tree_shapes['seed']))
    assert 'SANDBAR_REPO' not in env


def test_integ_env_strips_anchor_foreign_value(monkeypatch, tmp_path):
    env = _integ_env(monkeypatch, str(tmp_path / 'elsewhere'))
    assert 'SANDBAR_REPO' not in env


def test_integ_env_strips_anchor_absent_value(monkeypatch):
    env = _integ_env(monkeypatch, None)
    assert 'SANDBAR_REPO' not in env


def test_integ_env_keeps_prior_families_and_extra(monkeypatch, tmp_path):
    """The pre-existing strip families do not regress; the extra explicit
    injection face is not swallowed by the anchor family."""
    import agent_activities as aa
    monkeypatch.setenv('SANDBAR_AGENT_STUB', '1')
    monkeypatch.setenv('SANDBAR_TASK_QUEUE', 'q1')
    monkeypatch.setenv('SANDBAR_REPO', str(tmp_path))
    env = aa.integ_subprocess_env({'SANDBAR_INTEG_LEDGER_SOURCE': 'x'})
    assert 'SANDBAR_AGENT_STUB' not in env
    assert 'SANDBAR_TASK_QUEUE' not in env
    assert 'SANDBAR_REPO' not in env
    assert env['SANDBAR_INTEG_LEDGER_SOURCE'] == 'x'


def test_lane_env_anchors_lane_root_all_parent_shapes(monkeypatch, tree_shapes):
    """Primary L1: the lane child anchor equals the lane root whether the parent
    env carried the main-checkout value, a foreign value, or nothing."""
    import agent_activities as aa
    lane = tree_shapes['lane']
    for anchor in (str(tree_shapes['seed']), '/nonexistent/foreign', None):
        if anchor is None:
            monkeypatch.delenv('SANDBAR_REPO', raising=False)
        else:
            monkeypatch.setenv('SANDBAR_REPO', anchor)
        env = aa.lane_subprocess_env(lane)
        assert env['SANDBAR_REPO'] == str(lane)


def test_anchor_family_is_its_own_tuple():
    """The anchor family stands alone (review R5): never folded into
    TEST_STUB_ENV_KNOBS."""
    assert shared.ANCHOR_ENV_KNOBS == ('SANDBAR_REPO',)
    assert 'SANDBAR_REPO' not in shared.TEST_STUB_ENV_KNOBS
    assert 'SANDBAR_REPO' not in shared.WORKER_ROUTING_ENV_KNOBS


# ---------------- L1: guard ----------------

def test_guard_named_error_on_disagree(tree_shapes):
    err = shared.anchor_guard_error(str(tree_shapes['seed']), 'env SANDBAR_REPO',
                                    tree_shapes['lane'])
    assert err and NAMED in err
    # both roots and both sources are named
    assert str(tree_shapes['seed']) in err
    assert str(tree_shapes['lane']) in err
    assert 'env SANDBAR_REPO' in err


def test_guard_passes_on_equal_anchor(tree_shapes):
    assert shared.anchor_guard_error(str(tree_shapes['lane']), 'config.repo',
                                     tree_shapes['lane']) is None


def test_guard_passes_on_no_anchor(tree_shapes):
    assert shared.anchor_guard_error('', '', tree_shapes['lane']) is None
    assert shared.anchor_guard_error(None, None, tree_shapes['lane']) is None


def test_guard_passes_on_non_worktree_own_tree(tree_shapes):
    """External-caller regression face: a standalone checkout keeps honouring a
    foreign explicit anchor (the documented escape hatch)."""
    for own in (tree_shapes['seed'], tree_shapes['standalone']):
        assert shared.anchor_guard_error('/some/other/repo', 'env SANDBAR_REPO',
                                         own) is None


def test_guard_location_derived_is_normal_state(tree_shapes):
    assert shared.anchor_guard_error('/any', 'location-derived', tree_shapes['lane']) is None


def test_guard_malformed_anchors_no_crash(tree_shapes):
    """Malformed input (house discipline): empty / relative / nonexistent /
    symlink loop - always a verdict, never a raise."""
    lane = tree_shapes['lane']
    for bad in ('', 'relative/path', '/nonexistent/checkout'):
        out = shared.anchor_guard_error(bad, 'env SANDBAR_REPO', lane)
        assert out is None or NAMED in out
    loop = tree_shapes['root'] / 'loop'
    try:
        loop.symlink_to(loop)
    except OSError:
        pytest.skip('symlink not supported')
    out = shared.anchor_guard_error(str(loop), 'env SANDBAR_REPO', lane)
    assert out is None or NAMED in out


def test_review_store_guard_mirrors(tree_shapes, monkeypatch):
    """The review_store local mirror must agree with the shared verdict for the
    same worktree / anchor shapes."""
    import importlib.util
    lane = tree_shapes['lane']
    # copy review_store.py into the lane at its real relative location so the
    # own-tree criterion lands inside the fixture tree
    mod_dir = lane / 'server' / 'plugins' / 'knowledge'
    mod_dir.mkdir(parents=True, exist_ok=True)
    src = POC.parent / 'plugins' / 'knowledge' / 'review_store.py'
    (mod_dir / 'review_store.py').write_text(src.read_text(encoding='utf-8'),
                                             encoding='utf-8')
    spec = importlib.util.spec_from_file_location('rs_fixture', mod_dir / 'review_store.py')
    rs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rs)
    monkeypatch.setenv('SANDBAR_REPO', str(tree_shapes['seed']))
    err = rs.anchor_guard_error()
    assert err and NAMED in err
    monkeypatch.setenv('SANDBAR_REPO', str(lane))
    assert rs.anchor_guard_error() is None
    monkeypatch.delenv('SANDBAR_REPO')
    assert rs.anchor_guard_error() is None


# ---------------- decision-table parity (Python <-> TS mirror) ----------------

# Row: (own_is_worktree, anchor_set, anchor_equal_own, anchor_src) -> expected 'pass' | 'error'
# gen6 rework: the guard covers ENV-sourced anchors only; a config.repo anchor
# (the documented primary seam: external callers / deliberate fixtures) passes.
DECISION_TABLE = [
    # worktree own tree + inherited foreign env anchor -> named error (the incident)
    (True, True, False, 'env SANDBAR_REPO', 'error'),
    # worktree own tree + env anchor equal to the own root -> pass
    (True, True, True, 'env SANDBAR_REPO', 'pass'),
    # worktree own tree + no anchor -> pass (location-derived is the normal state)
    (True, False, False, 'location-derived', 'pass'),
    # worktree own tree + DELIBERATE foreign config.repo anchor -> pass (outcome 3:
    # external callers / the t260907-11 fixture face; explicit in-code, not inherited)
    (True, True, False, 'config.repo', 'pass'),
    # standalone checkout (main checkout / external copy) + foreign env anchor -> pass
    # (escape-hatch semantics)
    (False, True, False, 'env SANDBAR_REPO', 'pass'),
    (False, False, False, 'location-derived', 'pass'),
]


def _py_verdict(anchor, anchor_src, own_root):
    out = shared.anchor_guard_error(anchor, anchor_src, own_root)
    return 'error' if out else 'pass'


def _js_str(s):
    import json
    return json.dumps(str(s))


def _ts_verdict(anchor, anchor_src, own_root, node_bin):
    """Evaluate the same row with node against repo-anchor.mjs."""
    mod = POC.parent / 'plugins' / 'repo-anchor.mjs'
    js = (
        "import { realpathSync } from 'node:fs';\n"
        "const m = await import(%s);\n"
        "const anchor = %s;\n"
        "const ownRoot = %s;\n"
        "const err = m.anchorGuardError(anchor, %s, ownRoot);\n"
        "console.log('V=' + (err ? 'error' : 'pass') + '|' + (err || '').slice(0, 60));\n"
    ) % (_js_str(mod), _js_str(anchor) if anchor else "''", _js_str(own_root), _js_str(anchor_src))
    p = subprocess.run([node_bin, '--input-type=module', '-e', js],
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, 'node evaluation failed: %s' % p.stderr[-300:]
    line = [l for l in p.stdout.splitlines() if l.startswith('V=')]
    assert line, p.stdout
    return line[0][2:].split('|')[0]


def test_ts_own_root_is_repo_root(tree_shapes):
    """Rework gen3 depth lock (arbitration code-fault): OWN_ROOT must be the REPO
    root of this checkout (two levels up from server/plugins/), not <repo>/server.
    The gen0 parity test passed own_root explicitly on both sides, so it could not
    see this off-by-one — this test pins the module's own derivation."""
    node = _node_bin()
    if not node:
        pytest.skip('node unavailable (declared, not silent)')
    import json as _json
    mod = POC.parent / 'plugins' / 'repo-anchor.mjs'
    repo_root = POC.parents[1]
    js = (
        "const m = await import(%s);\n"
        "console.log('R=' + m.OWN_ROOT);\n"
    ) % _js_str(mod)
    p = subprocess.run([node, '--input-type=module', '-e', js],
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr[-300:]
    got = [l for l in p.stdout.splitlines() if l.startswith('R=')][0][2:]
    assert Path(got).resolve() == repo_root.resolve(), \
        'OWN_ROOT=%s != repo root %s' % (got, repo_root)


def test_ts_real_tree_guard_and_location_branch(monkeypatch):
    """End-to-end against the REAL module location (no injected own_root): this
    checkout IS a linked worktree, so (a) an inherited foreign env anchor must
    make resolveRepo throw the named error, and (b) with no anchor the
    location-derived branch must return the repo root."""
    node = _node_bin()
    if not node:
        pytest.skip('node unavailable (declared, not silent)')
    repo_root = POC.parents[1]
    mod = POC.parent / 'plugins' / 'repo-anchor.mjs'
    js_foreign = (
        "const m = await import(%s);\n"
        "try { m.resolveRepo(undefined); console.log('R=pass:' + m.resolveRepoAnchor(undefined).repo); }\n"
        "catch (e) { console.log('R=guard:' + (e.name || '') + ':' + String(e.message).slice(0, 40)); }\n"
    ) % _js_str(mod)
    import os
    env = dict(os.environ)
    env['SANDBAR_REPO'] = '/nonexistent/foreign/checkout'
    p = subprocess.run([node, '--input-type=module', '-e', js_foreign],
                       capture_output=True, text=True, timeout=60, env=env)
    assert p.returncode == 0, p.stderr[-300:]
    out = [l for l in p.stdout.splitlines() if l.startswith('R=')][0]
    # 261016: this case is LAYOUT-dependent, and it now pins BOTH layouts instead
    # of assuming one. The guard is declared to cover LANE WORK only: a process
    # whose own tree is a linked worktree (.git is a gitfile) must refuse a
    # foreign inherited anchor, while a standalone checkout (the main checkout)
    # keeps honouring config.repo / SANDBAR_REPO exactly as documented. The suite
    # runs from both, and the previous single expectation turned a green tree red
    # whenever it ran outside a lane worktree — a false red on the merge gate.
    if (repo_root / ".git").is_file():
        assert out.startswith('R=guard:SANDBAR_ANCHOR_MISMATCH:'), out
    else:
        assert out == 'R=pass:/nonexistent/foreign/checkout', out
    env2 = dict(os.environ)
    env2.pop('SANDBAR_REPO', None)
    p2 = subprocess.run([node, '--input-type=module', '-e', js_foreign],
                        capture_output=True, text=True, timeout=60, env=env2)
    assert p2.returncode == 0, p2.stderr[-300:]
    out2 = [l for l in p2.stdout.splitlines() if l.startswith('R=')][0]
    assert out2.startswith('R=pass:') and Path(out2[len('R=pass:'):]).resolve() == repo_root.resolve(), out2


def test_no_process_global_anchor_env_writer():
    """Rework gen13 (arbitration round 6): no plugin-family code may write a tree
    identity into process.env.SANDBAR_REPO. Under parallel multi-tree plugin
    loading (stage container: /repo + /repo-nm), whichever tree applied first
    poisoned the process env and the other tree's consumers were refused at
    apply — the console died at boot. Source lock: the watchdog set-when-absent
    write is removed and no other writer exists in server/plugins/."""
    plugins = POC.parent / 'plugins'
    offenders = []
    for p in plugins.rglob('*'):
        if p.suffix not in ('.ts', '.mjs', '.js') or 'node_modules' in p.parts:
            continue
        try:
            txt = p.read_text(encoding='utf-8')
        except OSError:
            continue
        for i, line in enumerate(txt.split('\n'), 1):
            code = line.split('//')[0]
            if 'process.env.SANDBAR_REPO' in code and (
                    '=' in code.split('process.env.SANDBAR_REPO', 1)[1]):
                offenders.append('%s:%s' % (p, i))
    assert not offenders, 'process-global anchor env writers: %s' % offenders


def _node_bin():
    try:
        p = subprocess.run(['node', '--version'], capture_output=True, text=True)
        if p.returncode == 0:
            return 'node'
    except OSError:
        pass
    return None


def test_ts_mirror_matches_python_decision_table(tree_shapes):
    node = _node_bin()
    if not node:
        pytest.skip('node unavailable (parity check degrades to the Python side '
                    'only, declared not silent) - the integ-gate scenario '
                    'sc_t26100833_anchor_guard_named_failure still exercises the '
                    'TS module with a real node run')
    lane = tree_shapes['lane']
    seed = tree_shapes['seed']
    for own_is_wt, anchor_set, anchor_eq, anchor_src, expected in DECISION_TABLE:
        own = lane if own_is_wt else seed
        anchor = str(own if anchor_eq else tree_shapes['root'] / 'foreign')
        if not anchor_set:
            anchor = ''
        py = _py_verdict(anchor, anchor_src, own)
        ts = _ts_verdict(anchor, anchor_src, own, node)
        assert py == expected and ts == expected, \
            'row %s: py=%s ts=%s expected=%s' % ((own_is_wt, anchor_set, anchor_eq, anchor_src),
                                                 py, ts, expected)
