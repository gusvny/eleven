"""t260911-02 单测：docs 面扫描器（inspection_scan_doc）——夹具树正反例 + 畸形输入。

纪律：正例命中与反例不报都由夹具树承担（review_plan R5：真仓首轮 2 条 frontmatter
已知发现≠场景失败，真仓不作判定基准）；每条畸形输入（坏 JSON/坏 YAML/缺字段/越界
路径/混杂条目）逐项点名降级，不假绿不崩。
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import inspection_scan_doc as doc
from inspection_scan import ScanError

FM = ("---\ntitle: t\ncategory: design\ntags:\n  - a\nstatus: active\n"
      "updated: 2026-09-11\n---\n\n# t\n")


def _mk_repo(tmp_path, index_docs, files, index_raw=None):
    """夹具仓：files={docs 相对路径: 文本}；index_docs=[path…] 或 index_raw=原文。"""
    (tmp_path / "docs").mkdir(exist_ok=True)
    for rel, text in files.items():
        p = tmp_path / "docs" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    payload = {"generated_at": "2026-09-11T00:00:00+08:00", "total": len(index_docs),
               "categories": ["design"], "docs": [{"path": p} for p in index_docs]}
    (tmp_path / "docs" / "index.json").write_text(
        index_raw if index_raw is not None else json.dumps(payload, ensure_ascii=False),
        encoding="utf-8")
    return tmp_path


def _subjects(result, rule):
    return [f["subject"] for f in result["findings"] if f["scan"] == rule]


# ---------- S8 index ↔ 实体 ----------

def test_s8_consistent_tree_zero_findings(tmp_path):
    repo = _mk_repo(tmp_path, ["design/a.md"], {"design/a.md": FM})
    r = doc.run_doc_face_scan(repo)
    assert r["heartbeat"] is True and r["findings"] == []


def test_s8_ghost_and_missing_named(tmp_path):
    repo = _mk_repo(tmp_path, ["design/ghost.md", "design/a.md"],
                    {"design/a.md": FM, "design/lonely.md": FM})
    r = doc.run_doc_face_scan(repo)
    assert any("ghost.md" in s and "幽灵" in s for s in _subjects(r, doc.RULE_S8_GHOST))
    assert any("lonely.md" in s and "缺登记" in s for s in _subjects(r, doc.RULE_S8_MISSING))


def test_s8_bad_json_degrades_named(tmp_path):
    repo = _mk_repo(tmp_path, [], {"design/a.md": FM}, index_raw="{not json")
    r = doc.run_doc_face_scan(repo)
    assert _subjects(r, doc.RULE_S8_GHOST) and "不可解析" in _subjects(r, doc.RULE_S8_GHOST)[0]


def test_s8_missing_index_file_named(tmp_path):
    (tmp_path / "docs").mkdir(exist_ok=True)
    (tmp_path / "docs" / "a.md").write_text(FM, encoding="utf-8")
    r = doc.run_doc_face_scan(tmp_path)
    assert any("缺失" in s for s in _subjects(r, doc.RULE_S8_GHOST))


# ---------- S9 frontmatter ----------

def test_s9_missing_fence_named(tmp_path):
    repo = _mk_repo(tmp_path, ["design/a.md"], {"design/a.md": "# 无围栏\n"})
    r = doc.run_doc_face_scan(repo)
    assert any("缺 frontmatter 围栏" in s for s in _subjects(r, doc.RULE_S9_FRONTMATTER))


@pytest.mark.parametrize("field", ["title", "category", "tags", "status", "updated"])
def test_s9_each_required_field_named(tmp_path, field):
    text = FM.replace("%s: t\n" % field, "", 1) if field == "title" else \
        {"category": FM.replace("category: design\n", ""),
         "tags": FM.replace("tags:\n  - a\n", ""),
         "status": FM.replace("status: active\n", ""),
         "updated": FM.replace("updated: 2026-09-11\n", "")}.get(field, FM)
    repo = _mk_repo(tmp_path, ["design/a.md"], {"design/a.md": text})
    r = doc.run_doc_face_scan(repo)
    assert any(("缺 %s" % field) in s for s in _subjects(r, doc.RULE_S9_FRONTMATTER)), field


def test_s9_illegal_category_and_status_named(tmp_path):
    repo = _mk_repo(tmp_path, ["design/a.md"],
                    {"design/a.md": FM.replace("category: design", "category: gossip")
                                     .replace("status: active", "status: maybe")})
    r = doc.run_doc_face_scan(repo)
    subs = "；".join(_subjects(r, doc.RULE_S9_FRONTMATTER))
    assert "gossip" in subs and "maybe" in subs


def test_s9_bad_date_named(tmp_path):
    repo = _mk_repo(tmp_path, ["design/a.md"],
                    {"design/a.md": FM.replace("updated: 2026-09-11", "updated: yesterday")})
    r = doc.run_doc_face_scan(repo)
    assert any("updated" in s for s in _subjects(r, doc.RULE_S9_FRONTMATTER))


def test_s9_duplicate_key_named(tmp_path):
    text = FM.replace("status: active\n", "status: active\nstatus: draft\n")
    repo = _mk_repo(tmp_path, ["design/a.md"], {"design/a.md": text})
    r = doc.run_doc_face_scan(repo)
    assert any("键重复" in s for s in _subjects(r, doc.RULE_S9_FRONTMATTER))


def test_s9_doc_exempt_suppresses(tmp_path):
    text = FM.replace("status: active", "status: maybe") + "\n<!-- doc-exempt: doc-s9 -->\n"
    repo = _mk_repo(tmp_path, ["design/a.md"], {"design/a.md": text})
    r = doc.run_doc_face_scan(repo)
    assert _subjects(r, doc.RULE_S9_FRONTMATTER) == []


# ---------- S10 引用路径 ----------

def test_s10_existing_repo_relative_ref_ok(tmp_path):
    (tmp_path / "server").mkdir()
    (tmp_path / "server" / "x.py").write_text("x=1", encoding="utf-8")
    text = FM + "见 `server/x.py` 与 [指南](docs/README.md)。\n"
    (tmp_path / "docs").mkdir(exist_ok=True)
    (tmp_path / "docs" / "README.md").write_text("# r\n", encoding="utf-8")
    repo = _mk_repo(tmp_path, ["design/a.md"], {"design/a.md": text})
    r = doc.run_doc_face_scan(repo)
    assert _subjects(r, doc.RULE_S10_MISSING) == []


def test_s10_missing_ref_named(tmp_path):
    text = FM + "见 `notes/gone-file.md`。\n"
    repo = _mk_repo(tmp_path, ["design/a.md"], {"design/a.md": text})
    r = doc.run_doc_face_scan(repo)
    assert any("gone-file.md" in s for s in _subjects(r, doc.RULE_S10_MISSING))


def test_s10_inside_repo_ref_not_escape(tmp_path):
    # docs/design/../.. 仍在仓内（repo/outside.md 存在）→ 不判越界不判缺失
    text = FM + "见 [外](../../outside.md)。\n"
    repo = _mk_repo(tmp_path, ["design/a.md"], {"design/a.md": text})
    (repo / "outside.md").write_text("x", encoding="utf-8")
    r = doc.run_doc_face_scan(repo)
    assert _subjects(r, doc.RULE_S10_ESCAPE) == [] and _subjects(r, doc.RULE_S10_MISSING) == []


def test_s10_escape_named(tmp_path):
    # ../../../outside.md 从 docs/design 解析出仓根 → 越界点名（存在与否不影响判定）
    text = FM + "见 [外](../../../outside.md)。\n"
    repo = _mk_repo(tmp_path, ["design/a.md"], {"design/a.md": text})
    r = doc.run_doc_face_scan(repo)
    assert any("outside.md" in s for s in _subjects(r, doc.RULE_S10_ESCAPE))


def test_s10_url_and_root_absolute_not_flagged(tmp_path):
    text = FM + "外链 [a](https://example.com/docs/x.md) 与契约字面 `/.sandbar/x.json`。\n"
    repo = _mk_repo(tmp_path, ["design/a.md"], {"design/a.md": text})
    r = doc.run_doc_face_scan(repo)
    assert _subjects(r, doc.RULE_S10_MISSING) == []
    assert _subjects(r, doc.RULE_S10_ESCAPE) == []


# ---------- 汇总/口径 ----------

def test_all_findings_med_and_heartbeat_zero(tmp_path):
    repo = _mk_repo(tmp_path, ["design/ghost.md"], {"design/a.md": "# 无围栏\n"})
    r = doc.run_doc_face_scan(repo)
    assert all(f["severity"] == "med" for f in r["findings"])
    assert r["heartbeat"] is False
    assert "caveat" in r["meta"]


def test_repo_root_missing_fail_closed(tmp_path):
    with pytest.raises(ScanError):
        doc.run_doc_face_scan(tmp_path / "nope")


def test_docs_dir_missing_fail_closed(tmp_path):
    with pytest.raises(ScanError):
        doc.run_doc_face_scan(tmp_path)


def test_cli_single_line_json(tmp_path):
    import subprocess, sys
    repo = _mk_repo(tmp_path, ["design/a.md"], {"design/a.md": FM})
    proc = subprocess.run([sys.executable, str(Path(doc.__file__)),
                           "--repo-root", str(repo)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["ok"] is True and payload["result"]["face"] == "doc"
