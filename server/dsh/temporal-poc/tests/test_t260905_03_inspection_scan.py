"""t260905-03 票①：测试面扫描器单测（inspection_scan）。

核心是 KI-051 回放（R1/C1 定稿口径）：
  - high 夹具 = 复刻故障机制（生产方在位 + 模板拼接 + 锚字面全漂）→ 必报 high；
  - med 夹具 = 真实 capture.mjs 案形态（新旧文案共享前缀，相似度悬置）→ 必报 med；
  - 两者与「文件已挪」夹具（S3 形态）严格分离，防另一故障模式冒充 KI-051 回放。
另覆盖：组合片段在场、字面在场零发现、重复场景阈值边界、行号越界、畸形被扫输入
不崩（AST 毁损/非元组清单/乱码）、心跳零发现、id 确定性、CLI 单行 JSON 契约。
纯标准库 + 固定桩文件，不读真仓、不碰网络。
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import inspection_scan as scan  # noqa: E402

SCENARIOS_PY = '''"""场景执行器桩"""
SCENARIOS = [
    ("sc_alpha", "守卫场景甲：验证甲行为", "python3 x.py"),
    ("sc_beta", "守卫场景乙：验证乙行为", "python3 y.py"),
]
'''


def make_repo(tmp_path: Path, files: dict) -> Path:
    (tmp_path / "integration" / "baselines").mkdir(parents=True, exist_ok=True)
    (tmp_path / "integration" / "run_scenarios.py").write_text(SCENARIOS_PY, encoding="utf-8")
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp_path


def run_scan(root: Path) -> dict:
    return scan.run_test_face_scan(root)


def finding_of(result: dict, scan_name: str, frag: str):
    return [f for f in result["findings"] if f["scan"] == scan_name and frag in f["subject"]]


# ========================================================================================
# S2：守卫锚→生产方在场性（KI-051 回放）
# ========================================================================================

def test_ki051_pure_rewrite_form_reports_high(tmp_path):
    """KI-051 high 支路（C1）：生产方在位（模板拼接、字面搜不到）、守卫断言旧字面、
    核心片段全缺 → 必报 high。生产方与守卫通过路径引用绑定（引用解析命中）。"""
    producer = (
        'const mark = "+ 钮";\n'
        'const copy = "项目行" + mode + mark;   // 模板拼接：字面搜索搜不到\n'
    )
    guard = (
        '// 守卫 capture UI 文案（playwright 形态）\n'
        'const producer = "server/dsh/workbench/lib/copy_panel.mjs";\n'
        'const text = await page.locator(".copy-panel").innerText();\n'
        'assert(text === "点击「+ 新建会话」开始新会话");\n'
    )
    root = make_repo(tmp_path, {
        "server/dsh/workbench/lib/copy_panel.mjs": producer,
        "integration/baselines/sc_copy_guard.mjs": guard,
    })
    result = run_scan(root)
    hits = finding_of(result, "guard-anchor", "sc_copy_guard")
    assert len(hits) == 1, json.dumps(result["findings"], ensure_ascii=False)
    assert hits[0]["severity"] == "high"
    assert "生产方已定位" in hits[0]["evidence"] or "字面" in hits[0]["evidence"]


def test_ki051_real_shared_prefix_form_reports_med(tmp_path):
    """KI-051 真实 capture.mjs 案形态（R1 必报）：新旧文案共享前缀「隔离台」——
    组合片段未命中但部分核心片段在场（相似度悬置）→ 必报 med 交人审，不静默漏报。"""
    producer = 'const copy = "隔离台项目行" + mode + "钮";\n'
    guard = (
        'const producer = "server/dsh/workbench/lib/copy_panel.mjs";\n'
        'const text = await page.locator(".copy-panel").innerText();\n'
        'assert(text === "隔离台「+ 新建会话」");\n'
    )
    root = make_repo(tmp_path, {
        "server/dsh/workbench/lib/copy_panel.mjs": producer,
        "integration/baselines/sc_copy_guard.mjs": guard,
    })
    result = run_scan(root)
    hits = finding_of(result, "guard-anchor", "sc_copy_guard")
    assert len(hits) == 1
    assert hits[0]["severity"] == "med"
    assert "悬置" in hits[0]["evidence"]


def test_anchor_literal_present_no_finding(tmp_path):
    producer = 'const copy = "点击「+ 新建会话」开始新会话";\n'
    guard = (
        'const producer = "server/dsh/workbench/lib/copy_panel.mjs";\n'
        'const text = await page.locator(".copy-panel").innerText();\n'
        'assert(text === "点击「+ 新建会话」开始新会话");\n'
    )
    root = make_repo(tmp_path, {
        "server/dsh/workbench/lib/copy_panel.mjs": producer,
        "integration/baselines/sc_copy_guard.mjs": guard,
    })
    result = run_scan(root)
    assert finding_of(result, "guard-anchor", "sc_copy_guard") == []
    assert result["meta"]["anchors_checked"] == 1


def test_anchor_fragments_window_hit_no_finding(tmp_path):
    """组合片段策略：单行内全片段命中（字面顺序变了但措辞都在场）→ 零发现。"""
    producer = 'const copy = "点击" + sep + "开始新会话";\n'  # 片段散在同行的拼接
    guard = (
        'const producer = "server/dsh/workbench/lib/copy_panel.mjs";\n'
        'const text = await page.locator(".copy-panel").innerText();\n'
        'assert(text === "开始新会话：点击");\n'
    )
    root = make_repo(tmp_path, {
        "server/dsh/workbench/lib/copy_panel.mjs": producer,
        "integration/baselines/sc_copy_guard.mjs": guard,
    })
    result = run_scan(root)
    assert finding_of(result, "guard-anchor", "sc_copy_guard") == []


def test_guard_without_locatable_producer_skipped_not_reported(tmp_path):
    """生产方定位不到（守卫无现存文件引用）→ 锚跳过记 meta，不出发现（防误报满屏）。"""
    guard = (
        'const producer = "server/nowhere/gone.mjs";\n'
        'const text = await page.locator(".copy-panel").innerText();\n'
        'assert(text === "彻底不存在的文案片段");\n'
    )
    root = make_repo(tmp_path, {"integration/baselines/sc_orphan.mjs": guard})
    result = run_scan(root)
    assert finding_of(result, "guard-anchor", "sc_orphan") == []
    assert result["meta"]["anchors_skipped_no_producer_ctx"] == 1


def test_non_ui_guard_excluded_from_anchor_scan(tmp_path):
    """非 UI 守卫（无 DOM 捕获标记）不进 S2——其字符串是场景自述非文案锚。"""
    producer = 'const x = 1;\n'
    guard = (
        'const producer = "server/dsh/workbench/lib/copy_panel.mjs";\n'
        'assert(step === "场景自述一：这不该进锚扫");\n'
    )
    root = make_repo(tmp_path, {
        "server/dsh/workbench/lib/copy_panel.mjs": producer,
        "integration/baselines/sc_logic_only.mjs": guard,
    })
    result = run_scan(root)
    assert finding_of(result, "guard-anchor", "") == []
    assert result["meta"]["guards_non_ui"] == 1


# ========================================================================================
# S3：过时断言（与 KI-051 夹具严格分离的「文件已挪/行号越界」形态）
# ========================================================================================

def test_stale_missing_path_qualified_reports_high(tmp_path):
    guard = 'const helper = "integration/gone_helper.py";\n'
    root = make_repo(tmp_path, {"integration/baselines/sc_uses_helper.mjs": guard})
    result = run_scan(root)
    hits = finding_of(result, "stale-ref", "gone_helper")
    assert len(hits) == 1 and hits[0]["severity"] == "high"


def test_stale_line_number_out_of_range_reports_high(tmp_path):
    root = make_repo(tmp_path, {})
    (root / "integration" / "helper_ok.py").write_text("a = 1\nb = 2\n", encoding="utf-8")
    guard_path = root / "integration" / "baselines" / "sc_uses_helper.mjs"
    guard_path.write_text(
        'const helper = "integration/helper_ok.py";  // 见 L9999\n', encoding="utf-8")
    result = run_scan(root)
    hits = finding_of(result, "stale-ref", "L9999")
    assert len(hits) == 1 and hits[0]["severity"] == "high"
    assert "行号越界" in hits[0]["evidence"]


def test_env_path_refs_not_reported(tmp_path):
    """node_modules 等装态相关路径=external，不报（不冤判环境为漂移）。"""
    guard = (
        'const nm = "server/dsh/ui-check/node_modules/playwright-core/index.mjs";\n'
        'const cred = "~/.dsh/credentials.yaml";\n'
    )
    root = make_repo(tmp_path, {"integration/baselines/sc_env_paths.mjs": guard})
    result = run_scan(root)
    assert finding_of(result, "stale-ref", "") == []
    assert result["meta"]["stale_refs_external"] >= 1   # node_modules 装态路径
    # ~/.dsh 凭据（HOME 语境）在引用提取层即排除；node_modules 在状态判定前排除——
    # 两条都不计 refs_checked（环境路径不是仓库引用，不算核查面）
    assert result["meta"]["stale_refs_checked"] == 0


def test_dts_glob_fragment_filtered(tmp_path):
    guard = 'const t = "*.d.ts glob";\n'
    root = make_repo(tmp_path, {"integration/baselines/sc_glob.mjs": guard})
    result = run_scan(root)
    assert finding_of(result, "stale-ref", "d.ts") == []


# ========================================================================================
# S1：重复场景检测
# ========================================================================================

def test_duplicate_scenarios_reported_med(tmp_path):
    text = SCENARIOS_PY.replace(
        '"守卫场景乙：验证乙行为"', '"守卫场景甲：验证甲行为"')
    root = make_repo(tmp_path, {})
    (root / "integration" / "run_scenarios.py").write_text(text, encoding="utf-8")
    result = run_scan(root)
    hits = finding_of(result, "duplicate", "dup:")
    assert len(hits) == 1 and hits[0]["severity"] == "med"


def test_distinct_scenarios_no_duplicate_finding(tmp_path):
    root = make_repo(tmp_path, {})
    result = run_scan(root)
    assert finding_of(result, "duplicate", "dup:") == []
    assert result["heartbeat"] is True and result["findings"] == []


# ========================================================================================
# 畸形被扫输入不崩（外部输入执行钩子）
# ========================================================================================

def test_malformed_scenario_entries_become_findings_not_crash(tmp_path):
    text = 'SCENARIOS = [("only-two", "缺 cmd"), "不是元组", 42]\n'
    root = make_repo(tmp_path, {})
    (root / "integration" / "run_scenarios.py").write_text(text, encoding="utf-8")
    result = run_scan(root)
    assert result["meta"]["scenarios"] == 0
    assert len(finding_of(result, "duplicate", "scenarios-manifest")) >= 3


def test_malformed_guard_syntax_error_recorded_not_crash(tmp_path):
    root = make_repo(tmp_path, {"integration/baselines/sc_broken.py": "def (:\n"})
    result = run_scan(root)
    assert result["heartbeat"] is True
    assert any("sc_broken" in g for g in result["meta"]["guards_unparseable"])


def test_missing_scenarios_manifest_fails_closed(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    (root / "integration").mkdir()
    with pytest.raises(scan.ScanError, match="场景清单缺位"):
        scan.run_test_face_scan(root)


def test_missing_repo_root_fails_closed(tmp_path):
    with pytest.raises(scan.ScanError, match="仓库根不存在"):
        scan.run_test_face_scan(tmp_path / "nope")


def test_binary_garbage_guard_not_crash(tmp_path):
    garbage = "x = '\x00\x01\x02 拾 \xff'\n" + "中文文案字面量 Enough" * 3
    root = make_repo(tmp_path, {"integration/baselines/sc_garbage.py": garbage})
    result = run_scan(root)  # 不崩即过；发现与否交判定逻辑
    assert "summary" in result


# ========================================================================================
# 汇总/确定性/CLI 契约
# ========================================================================================

def test_finding_id_deterministic():
    a = scan.finding_id("guard-anchor", "x ⇢ y")
    b = scan.finding_id("guard-anchor", "x ⇢ y")
    c = scan.finding_id("guard-anchor", "x ⇢ z")
    assert a == b and a != c and a.startswith("guard-anchor:")


def test_summary_severity_ordering_and_counts(tmp_path):
    root = make_repo(tmp_path, {
        "integration/baselines/sc_g1.mjs": 'const p = "server/dsh/workbench/lib/a.mjs";\nassert(c === "完全漂移的文案甲乙丙");\n',
        "integration/baselines/sc_g2.mjs": 'const p = "integration/zz_gone.py";\n',
        "server/dsh/workbench/lib/a.mjs": "const q = 1;\n",
    })
    result = run_scan(root)
    sev = [f["severity"] for f in result["findings"]]
    assert sev == sorted(sev, key=lambda s: {"high": 0, "med": 1, "low": 2}[s])
    assert result["summary"]["high"] == sum(1 for s in sev if s == "high")
    assert result["heartbeat"] is False


def test_cli_single_line_json_contract(tmp_path):
    root = make_repo(tmp_path, {})
    proc = subprocess.run(
        [sys.executable, str(POC / "inspection_scan.py"), "--repo-root", str(root)],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0
    lines = proc.stdout.strip().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["ok"] is True and payload["result"]["heartbeat"] is True


def test_cli_missing_root_single_line_error():
    proc = subprocess.run(
        [sys.executable, str(POC / "inspection_scan.py"), "--repo-root", "/nonexistent-repo"],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 1
    lines = proc.stdout.strip().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["ok"] is False and "仓库根" in payload["error"]
