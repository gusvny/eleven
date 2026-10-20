# -*- coding: utf-8 -*-
"""261019 (host ruling a1): a single-repository project's line is the DEFAULT.

Why: declaring `lines.json` is a project's statement of where delivery flows,
but a dev-lane ticket only took that path when its creator repeated
`lane_version=develop-buffer-v1` + `develop_line_id` on every start. Measured on
261019: thirteen dev-lane tickets were created without the pair, so every one of
them ran the full-suite gate caliber (the line-scoped feedback face does not
apply to legacy lanes) and squash-landed straight onto main.

The default is deliberately narrow, and each limit is a measured property of the
machinery it feeds:
  * dev-lane only — the only workflow whose input carries the two fields (a
    foreign template receiving them is a named refusal elsewhere in intake);
  * exactly ONE declared line — two lines is an ambiguity a human resolves;
  * exactly ONE repository — `land_to_line` refuses a multi-repository line BY
    NAME ("the per-ticket landing wires the single-repository phase"), so
    defaulting a multi-repo project would refuse every ticket it opens;
  * a missing/unreadable declaration changes nothing (legacy, as before).

Multi-repo projects (dengzhufpv) declare no line today, and this rule keeps them
on the legacy path even if they did.
"""
import json
import os
import sys

import client as cl

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _write_lines(tmp_path, monkeypatch, lines):
    root = tmp_path / "projects"
    (root / "proj-a" / "data" / "develop").mkdir(parents=True)
    (root / "proj-a" / "data" / "develop" / "lines.json").write_text(
        json.dumps(lines), encoding="utf-8")
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(root))
    return root


def _line(line_id, repos):
    return {"line_id": line_id,
            "repositories": [{"name": r, "branch": "develop"} for r in repos]}


def test_single_repo_single_line_is_the_default(tmp_path, monkeypatch):
    _write_lines(tmp_path, monkeypatch, [_line("main-line", ["only-repo"])])
    assert cl._default_line_for_project("proj-a", "dev-lane") == "main-line"


def test_multirepo_line_is_never_defaulted(tmp_path, monkeypatch):
    _write_lines(tmp_path, monkeypatch, [_line("mr-line", ["a", "b"])])
    assert cl._default_line_for_project("proj-a", "dev-lane") == "", \
        "a multi-repository line is refused at landing; defaulting to it would " \
        "refuse every ticket"


def test_two_declared_lines_are_ambiguous(tmp_path, monkeypatch):
    _write_lines(tmp_path, monkeypatch,
                 [_line("one", ["r"]), _line("two", ["r2"])])
    assert cl._default_line_for_project("proj-a", "dev-lane") == ""


def test_no_declaration_keeps_the_legacy_path(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    (root / "proj-a").mkdir(parents=True)
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(root))
    assert cl._default_line_for_project("proj-a", "dev-lane") == ""


def test_unreadable_declaration_is_not_a_refusal(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    p = root / "proj-a" / "data" / "develop"
    p.mkdir(parents=True)
    (p / "lines.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(root))
    assert cl._default_line_for_project("proj-a", "dev-lane") == "", \
        "an unreadable declaration must leave the ticket on the legacy path, " \
        "not fail intake"


def test_a_foreign_template_never_defaults(tmp_path, monkeypatch):
    _write_lines(tmp_path, monkeypatch, [_line("main-line", ["only-repo"])])
    for tpl in ("light-lane", "content-studio", "", None):
        assert cl._default_line_for_project("proj-a", tpl) == "", tpl


def test_real_projects_land_where_they_should():
    """The live declarations, read as they are (no fixture): sandbar is the
    single-repo pilot, the two multi-repo/knowledge projects stay legacy."""
    assert cl._default_line_for_project("sandbar", "dev-lane") == "develop-buffer"
    assert cl._default_line_for_project("dengzhufpv", "dev-lane") == ""
    assert cl._default_line_for_project("nusuyou", "dev-lane") == ""
