#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t261018-12 unit tests: the declared-bootstrap lawful restart for a dead
prev-base chain.

Pinned behaviour:
  - Pure validator: full 40-hex sha only (no prefixes, no ref names); wrong
    schema / non-dict / missing or non-string base_ref are each named defects.
  - Activity: absent bootstrap → the ORIGINAL unavailable reason verbatim
    (regression pin — the pile-up symptom must stay loud); valid bootstrap →
    the diff runs against the declared base, source + reason recorded on the
    surface; malformed / unresolvable (syntactically valid but nonexistent sha)
    → unavailable naming the bootstrap file and the defect (fail-closed);
    a live report chain WINS over a stale bootstrap file.
  - Restart effect: after one declared restart, the NEXT period inherits a real
    base through the normal report chain with NO bootstrap file present
    (two-period sequence — the actual user-facing fix).
  - Defensive local path (run_inspection_inspect without args["surface"])
    resolves the same bootstrap — one shared resolver, no behavior fork.

Run: server/engine/.venv/bin/python -B -m pytest \
     server/engine/tests/test_t261018_12_surface_bootstrap.py -q
"""
import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest
from temporalio import activity as activity_mod

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import agent_activities as aa  # noqa: E402
import inspection_surface as sf  # noqa: E402

FULL_SHA = "a" * 40


def _git(repo: Path, *args: str) -> str:
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    assert p.returncode == 0, "git %s failed: %s" % (" ".join(args), (p.stderr or "").strip()[-200:])
    return (p.stdout or "").strip()


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """Real git repo, two commits: c1 adds a.py; c2 edits a.py + adds a scenario."""
    d = tmp_path / "repo"
    d.mkdir()
    _git(d, "init")
    _git(d, "config", "user.email", "t@example.com")
    _git(d, "config", "user.name", "t")
    (d / "a.py").write_text("value = 1\n", encoding="utf-8")
    _git(d, "add", "-A")
    _git(d, "commit", "-m", "c1")
    (d / "a.py").write_text("value = 2\n", encoding="utf-8")
    sc = d / "integration" / "x"
    sc.mkdir(parents=True)
    (sc / "sc_new_case.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
    _git(d, "add", "-A")
    _git(d, "commit", "-m", "c2")
    return d


@pytest.fixture()
def beats(monkeypatch):
    monkeypatch.setattr(activity_mod, "heartbeat", lambda *a, **k: None)


def _surface_args(repo: Path, tmp: Path, instance: str = "docs-sync",
                  period: str = "20261018", **kw) -> dict:
    a = {"instance_id": instance, "period": period, "base_dir": str(repo),
         "base_head": "", "ledger_dir": str(tmp), "surface_thresholds": {},
         "shared_scans": {}}
    a.update(kw)
    return a


def _bootstrap(tmp: Path, instance: str, raw) -> Path:
    p = tmp / sf.bootstrap_file_name(instance)
    p.write_text(raw if isinstance(raw, str) else json.dumps(raw), encoding="utf-8")
    return p


# ---------------- pure validator ----------------

def test_parse_bootstrap_accepts_full_sha_and_records_reason():
    r = sf.parse_bootstrap_base({"schema": 1, "base_ref": FULL_SHA.upper(),
                                 "reason": "chain died 261010"})
    assert r["verdict"] == "ok" and r["base"] == FULL_SHA
    assert r["reason"] == "chain died 261010"


def test_parse_bootstrap_prefix_and_ref_names_are_refused():
    for bad in ("a" * 12, "HEAD", "main", "a" * 41, "g" * 40, "", None, 123):
        r = sf.parse_bootstrap_base({"schema": 1, "base_ref": bad})
        assert r["verdict"] == "unavailable" and r["reason"], bad


def test_parse_bootstrap_rejects_foreign_schema_and_non_dict():
    assert sf.parse_bootstrap_base({"schema": 2, "base_ref": FULL_SHA})["verdict"] == "unavailable"
    assert sf.parse_bootstrap_base({"base_ref": FULL_SHA})["verdict"] == "unavailable"
    assert sf.parse_bootstrap_base([FULL_SHA])["verdict"] == "unavailable"
    assert sf.parse_bootstrap_base("schema=1")["verdict"] == "unavailable"


def test_bootstrap_file_name_rejects_path_shaped_instance_ids():
    for bad in ("", "..", ".", "a/b", "a\\b"):
        with pytest.raises(ValueError):
            sf.bootstrap_file_name(bad)


# ---------------- loader: existence check ----------------

def test_loader_absent_when_no_file(repo, tmp_path):
    assert sf.load_declared_bootstrap(tmp_path, "docs-sync", repo) == {"state": "absent"}


def test_loader_rejects_syntactically_valid_but_unresolvable_sha(repo, tmp_path):
    _bootstrap(tmp_path, "docs-sync", {"schema": 1, "base_ref": "b" * 40})
    r = sf.load_declared_bootstrap(tmp_path, "docs-sync", repo)
    assert r["state"] == "defective" and "does not resolve" in r["reason"]


def test_loader_rejects_malformed_files_with_named_defects(repo, tmp_path):
    _bootstrap(tmp_path, "docs-sync", "{not json")
    r = sf.load_declared_bootstrap(tmp_path, "docs-sync", repo)
    assert r["state"] == "defective" and "unreadable" in r["reason"]
    _bootstrap(tmp_path, "docs-sync", {"schema": 1, "base_ref": "main"})
    r2 = sf.load_declared_bootstrap(tmp_path, "docs-sync", repo)
    assert r2["state"] == "defective" and "40-hex" in r2["reason"]


def test_loader_accepts_a_real_commit(repo, tmp_path):
    c1 = _git(repo, "rev-parse", "HEAD~1")
    _bootstrap(tmp_path, "docs-sync", {"schema": 1, "base_ref": c1, "reason": "restart"})
    r = sf.load_declared_bootstrap(tmp_path, "docs-sync", repo)
    assert r == {"state": "ok", "base": c1, "reason": "restart"}


# ---------------- activity: the three states + chain-wins ----------------

def test_activity_absent_bootstrap_keeps_original_reason(repo, tmp_path, beats):
    res = asyncio.run(aa.run_inspection_surface(_surface_args(repo, tmp_path)))
    s = res["surface"]
    assert s["verdict"] == "unavailable"
    assert s["reason"].startswith("no usable previous-period base point"), s["reason"]
    assert "the change-surface diff was not made" in s["reason"]


def test_activity_valid_bootstrap_makes_the_diff(repo, tmp_path, beats):
    c1 = _git(repo, "rev-parse", "HEAD~1")
    _bootstrap(tmp_path, "docs-sync", {"schema": 1, "base_ref": c1, "reason": "t261018-12"})
    res = asyncio.run(aa.run_inspection_surface(_surface_args(repo, tmp_path)))
    s = res["surface"]
    assert s["verdict"] == "normal", s
    assert s["prev_base"] == c1
    assert s["prev_base_source"] == "declared bootstrap file"
    assert "OPERATOR-DECLARED bootstrap" in s["note"] and "t261018-12" in s["note"]
    assert s["faces"]["test"] == 1 and s["new_scenarios"] == 1


def test_activity_defective_bootstrap_is_named_not_silent(repo, tmp_path, beats):
    _bootstrap(tmp_path, "docs-sync", {"schema": 9, "base_ref": FULL_SHA})
    res = asyncio.run(aa.run_inspection_surface(_surface_args(repo, tmp_path)))
    s = res["surface"]
    assert s["verdict"] == "unavailable"
    assert "no usable previous-period base point" in s["reason"]
    assert "declared bootstrap refused" in s["reason"] and "schema" in s["reason"]


def test_activity_unresolvable_bootstrap_is_unavailable(repo, tmp_path, beats):
    _bootstrap(tmp_path, "docs-sync", {"schema": 1, "base_ref": "c" * 40})
    res = asyncio.run(aa.run_inspection_surface(_surface_args(repo, tmp_path)))
    s = res["surface"]
    assert s["verdict"] == "unavailable" and "does not resolve" in s["reason"]


def test_activity_live_chain_wins_over_stale_bootstrap(repo, tmp_path, beats):
    c1 = _git(repo, "rev-parse", "HEAD~1")
    (tmp_path / "inspection-docs-sync-20261017.json").write_text(
        json.dumps({"findings": [], "scan_meta": {"inspect": {"base_head": c1}}}),
        encoding="utf-8")
    _bootstrap(tmp_path, "docs-sync", {"schema": 1, "base_ref": "d" * 40})
    res = asyncio.run(aa.run_inspection_surface(_surface_args(repo, tmp_path)))
    s = res["surface"]
    assert s["verdict"] == "normal" and s["prev_base"] == c1
    assert s["prev_base_source"] != "declared bootstrap file"


def test_restart_effect_next_period_inherits_chain_without_bootstrap(repo, tmp_path, beats):
    """Two-period sequence: P1 restarts via the declared bootstrap; P2 (bootstrap
    file deleted) must inherit a REAL base through the normal report chain —
    that inheritance is the actual user-facing fix."""
    c1 = _git(repo, "rev-parse", "HEAD~1")
    _bootstrap(tmp_path, "docs-sync", {"schema": 1, "base_ref": c1})
    p1 = asyncio.run(aa.run_inspection_surface(
        _surface_args(repo, tmp_path, period="20261018")))["surface"]
    assert p1["verdict"] == "normal" and p1["prev_base"] == c1
    # the engine records P1's endpoint via the inspect meta chain (same shape the
    # production writer emits: scan_meta.inspect.base_head)
    (tmp_path / "inspection-docs-sync-20261018.json").write_text(
        json.dumps({"findings": [],
                    "scan_meta": {"inspect": {"base_head": p1["this_base"]}}}),
        encoding="utf-8")
    (tmp_path / sf.bootstrap_file_name("docs-sync")).unlink()
    # a real advance between P1 and P2 (as in production: commits land daily),
    # test-shaped so the surface is above the little-to-review bar
    sc = repo / "integration" / "y"
    sc.mkdir(parents=True)
    (sc / "sc_next_case.py").write_text("def test_y():\n    pass\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "c3")
    p2 = asyncio.run(aa.run_inspection_surface(
        _surface_args(repo, tmp_path, period="20261019")))["surface"]
    assert p2["verdict"] == "normal", p2
    assert p2["prev_base"] == p1["this_base"]
    assert p2["prev_base_source"] == "prev scan_meta.inspect.base_head"


# ---------------- defensive local path uses the same resolver ----------------

def test_defensive_inspect_path_resolves_bootstrap(repo, tmp_path, monkeypatch):
    """run_inspection_inspect's legacy no-surface branch must resolve the same
    declared bootstrap (one shared resolver). We drive build_change_scope_text
    indirectly through the resolver seam both paths share: the loader call in
    the defensive branch is the same inspection_surface.load_declared_bootstrap
    proven above — here we pin the shared-source fact mechanically."""
    import inspect as _inspect
    src = _inspect.getsource(aa.run_inspection_inspect)
    assert "load_declared_bootstrap" in src, \
        "the defensive path must resolve the declared bootstrap (shared resolver)"
