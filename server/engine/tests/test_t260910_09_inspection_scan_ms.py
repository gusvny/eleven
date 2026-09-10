"""t260910-09 票②：机制面/简化面扫描器单测（inspection_scan_ms）。

真值表核心（方案 D2-D5 + review C2/C3 落地口径）：
  - S4 dead-man：三重零命中（场景零引用+日志字面零命中+全仓零引用点）→ med；
    任何一面非零不报；日志面无字面=N/A（不折算成 0/0——C2 空集恒真陷阱）；
    豁免声明（dead-man-exempt）不报；两重零 → low。
  - S5 影子代码：零引用点 × 新旧形态对 → med；健康对照不报。
  - S6 补丁退役：命名/标记特征+被取代 → med 且 suggestion 必含「删了会怎样」；
    仅特征无被取代 → low；重复防御层（调用链两层同 guard-ish 助手）→ med。
  - S7 过长/过深：阈值边界真值表（80/81 行、深度 5/6）→ low 点名带实测值。
  - 域注入（C3）：不同 scan_roots 各出真值表；test/selfcheck/fixtures 文件不进候选域。
  - 韧性（畸形输入用例——工单执行钩子②）：不可读文件、坏 ast（SyntaxError/NUL）、
    空仓、未知面——逐项降级进 meta 或 fail-closed 点名，不崩不静默。
  - 心跳：零发现 heartbeat=true（心跳票语义不变）；result 形状六键与票①同构（UI 面）。
纯标准库 + 固定桩文件，不读真仓、不碰网络。
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import inspection_scan_ms as ms  # noqa: E402

ENGINE = "server/engine"


def make_repo(tmp_path: Path, files: dict) -> Path:
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp_path


def findings_of(result: dict, scan_name: str, frag: str = "") -> list:
    return [f for f in result["findings"]
            if f["scan"] == scan_name and (not frag or frag in f["subject"])]


def one(result: dict, scan_name: str, frag: str):
    hits = findings_of(result, scan_name, frag)
    assert len(hits) == 1, "期望恰 1 条 %s%s，实得 %d：%r" % (
        scan_name, frag, len(hits), [f["subject"] for f in hits])
    return hits[0]


DEAD_MOD = (
    "import json\n"
    "\n"
    "\n"
    "def zombie_deploy():\n"
    "    \"\"\"零引用零场景零日志的机制（S4 正例）。\"\"\"\n"
    "    return json.dumps({})\n"
)

ALIVE_MOD = (
    "def live_heal():\n"
    "    return 1\n"
)

SCEN_ALIVE = "x = live_heal\n"          # 场景引用面救活 live_heal
CALLER_ALIVE = "y = live_heal()\n"      # 调用点面也救活（双保险，真值表要求任一面非零即活）


# ========================================================================================
# S4 dead-mechanism
# ========================================================================================

def test_s4_triple_zero_reports_med_with_denominators(tmp_path):
    """三重零命中 → med；证据三面各带分母/明写 N/A（C2）。"""
    root = make_repo(tmp_path, {
        "%s/dead_mod.py" % ENGINE: DEAD_MOD,
    })
    r = ms.run_mechanism_face_scan(root)
    f = one(r, "dead-mechanism", "zombie_deploy")
    assert f["severity"] == "med"
    assert "dead_mod.py:" in f["evidence"] and "定义" in f["evidence"]
    assert "场景引用 0/" in f["evidence"]                # 场景面：0/分母（斜率形计数）
    assert "日志面 N/A（模块 0 条 log 字面" in f["evidence"]  # 日志面：空集=N/A 不折算 0/0
    assert "引用点 0 处" in f["evidence"]                # 调用面：0 处
    assert "日志字面 0/" not in f["evidence"]            # 无字面时绝不出现伪 0/N 分数


def test_s4_log_face_zero_of_n_when_literals_present(tmp_path):
    """有 log 字面但外域零命中 → 日志面写作 0/N 条带分母（不是 N/A）。"""
    root = make_repo(tmp_path, {
        "%s/dead_log.py" % ENGINE:
            "import logging\n"
            "log = logging.getLogger(__name__)\n"
            "\n"
            "\n"
            "def ghost_rotate():\n"
            "    log.info(\"幽灵轮换机制启动\")\n",
    })
    r = ms.run_mechanism_face_scan(root)
    f = one(r, "dead-mechanism", "ghost_rotate")
    assert "日志字面 0/1 条在外域文件" in f["evidence"]
    assert "N/A" not in f["evidence"]


def test_s4_scenario_reference_vets(tmp_path):
    """场景引用非零 → 不报（反例：被场景挂着的机制不是 dead-man）。"""
    root = make_repo(tmp_path, {
        "%s/alive_mod.py" % ENGINE: ALIVE_MOD,
        "integration/sc_alive_guard.py": SCEN_ALIVE,
    })
    r = ms.run_mechanism_face_scan(root)
    assert not findings_of(r, "dead-mechanism", "live_heal")


def test_s4_code_reference_vets_even_without_scenario(tmp_path):
    """无场景引用但有代码引用点 → 结构面非零 → 完全不报（反例）。"""
    root = make_repo(tmp_path, {
        "%s/quiet_mod.py" % ENGINE: ALIVE_MOD,
        "bin/caller.py": "from x import live_heal\n",
    })
    r = ms.run_mechanism_face_scan(root)
    assert not findings_of(r, "dead-mechanism", "live_heal")


def test_s4_log_hit_downgrades_to_low_when_structure_zero(tmp_path):
    """场景 0 + 引用点 0 但日志字面在外域有命中 → 仍报但降 low（留观不判死）。"""
    root = make_repo(tmp_path, {
        "%s/quiet2_mod.py" % ENGINE:
            "import logging\n"
            "log = logging.getLogger(__name__)\n"
            "\n"
            "\n"
            "def log_only_alive():\n"
            "    log.info(\"仅在文档留名的机制执行\")\n",
        "docs/x.md": "仅在文档留名的机制执行入口\n",
    })
    r = ms.run_mechanism_face_scan(root)
    f = one(r, "dead-mechanism", "log_only_alive")
    assert f["severity"] == "low"


def test_s4_exempt_declaration_skips(tmp_path):
    """dead-man-exempt 声明 → 跳过且进 meta.exempted（声明即文档）。"""
    root = make_repo(tmp_path, {
        "%s/dead_mod.py" % ENGINE:
            "# dead-man-exempt: zombie_deploy\n" + DEAD_MOD,
    })
    r = ms.run_mechanism_face_scan(root)
    assert not findings_of(r, "dead-mechanism", "zombie_deploy")
    assert any("zombie_deploy" in e for e in r["meta"]["exempted"])


def test_s4_testish_files_excluded_from_candidates(tmp_path):
    """test_*/selfcheck_*/tests|fixtures 目录不进候选域（洪泛闸真值表）。"""
    root = make_repo(tmp_path, {
        "%s/test_deadish.py" % ENGINE: "def only_in_tests():\n    return 1\n",
        "%s/tests/helper_dead.py" % ENGINE: "def helper_dead():\n    return 2\n",
        "%s/selfcheck_probe.py" % ENGINE: "def selfcheck_only():\n    return 3\n",
    })
    r = ms.run_mechanism_face_scan(root)
    assert not findings_of(r, "dead-mechanism", "only_in_tests")
    assert not findings_of(r, "dead-mechanism", "helper_dead")
    assert not findings_of(r, "dead-mechanism", "selfcheck_only")
    assert r["meta"]["candidates"] == 0


def test_s4_private_and_main_not_candidates(tmp_path):
    """私有名/dunder/main 不是机制候选。"""
    root = make_repo(tmp_path, {
        "%s/quiet2.py" % ENGINE:
            "def _hidden():\n    return 1\n"
            "\n"
            "\n"
            "def main():\n    return 2\n",
    })
    r = ms.run_mechanism_face_scan(root)
    assert r["meta"]["candidates"] == 0 and r["heartbeat"] is True


# ========================================================================================
# S5 shadow-code
# ========================================================================================

def test_s5_shadow_pair_reports_med(tmp_path):
    """零引用 base × 在役 *_v2 变体 → med 影子路径，证据双点名。"""
    root = make_repo(tmp_path, {
        "%s/pair_mod.py" % ENGINE:
            "def export_pack():\n    return 1\n"
            "\n"
            "\n"
            "def export_pack_v2():\n    return 2\n"
            "\n"
            "\n"
            "z = export_pack_v2\n",
    })
    r = ms.run_mechanism_face_scan(root)
    f = one(r, "shadow-code", "export_pack ")
    assert f["severity"] == "med"
    # 影子判旧不冤在役：证据点兄弟变体位置（base* 形），在役名不出现在任何 finding 文本
    assert "export_pack*" in f["evidence"] and "引用点 0 处" in f["evidence"]
    assert all("export_pack_v2" not in str(x) for x in
               [(ff.get("subject"), ff.get("evidence"), ff.get("suggestion")) for ff in r["findings"]])


def test_s5_old_suffix_pair(tmp_path):
    """*_legacy 变体同构成立。"""
    root = make_repo(tmp_path, {
        "%s/pair_old.py" % ENGINE:
            "def pack_once():\n    return 1\n"
            "\n"
            "\n"
            "def pack_once_legacy():\n    return 2\n"
            "\n"
            "\n"
            "z = pack_once_legacy\n",
    })
    r = ms.run_mechanism_face_scan(root)
    one(r, "shadow-code", "pack_once ")


def test_s5_referenced_pair_not_shadow(tmp_path):
    """base 仍有引用点 → base 不是影子（反例；v2 同被引用则双双不报）。"""
    root = make_repo(tmp_path, {
        "%s/pair_live.py" % ENGINE:
            "def pack_two():\n    return 1\n"
            "\n"
            "\n"
            "def pack_two_v2():\n    return 2\n"
            "\n"
            "\n"
            "z = pack_two() or pack_two_v2\n",
    })
    r = ms.run_mechanism_face_scan(root)
    assert not findings_of(r, "shadow-code", "pack_two")


# ========================================================================================
# S6 patch-retirement / S7 long-nested
# ========================================================================================

def test_s6_patch_superseded_reports_med_with_risk_note(tmp_path):
    """命名特征+被取代（base 在役）→ med；suggestion 必含「删了会怎样」+ dev-lane 口径。"""
    root = make_repo(tmp_path, {
        "%s/patch_mod.py" % ENGINE:
            "def do_sync():\n    return 1\n"
            "\n"
            "\n"
            "def do_sync_patch():\n"
            "    # 兼容层：旧调用方缓冲\n"
            "    return do_sync()\n"
            "\n"
            "\n"
            "z = do_sync()\n",
    })
    r = ms.run_simplify_face_scan(root)
    f = one(r, "patch-retirement", "do_sync_patch")
    assert f["severity"] == "med"
    assert "删了会怎样" in f["suggestion"]
    assert "dev-lane" in f["suggestion"]


def test_s6_patch_named_only_is_low(tmp_path):
    """仅命名特征无被取代证据 → low（不冤枉）。"""
    root = make_repo(tmp_path, {
        "%s/patch_only.py" % ENGINE:
            "def retry_compat():\n    return 1\n"
            "\n"
            "\n"
            "z = retry_compat\n",
    })
    r = ms.run_simplify_face_scan(root)
    f = one(r, "patch-retirement", "retry_compat")
    assert f["severity"] == "low"


def test_s6_duplicate_defense_layer(tmp_path):
    """caller 与 callee 都调用同一 sanitize 助手 → med 重复防御层。"""
    root = make_repo(tmp_path, {
        "%s/defense.py" % ENGINE:
            "def sanitize_name(x):\n"
            "    return x.strip()\n"
            "\n"
            "\n"
            "def inner_store(x):\n"
            "    return sanitize_name(x)\n"
            "\n"
            "\n"
            "def outer_api(x):\n"
            "    x = sanitize_name(x)\n"
            "    return inner_store(x)\n",
    })
    r = ms.run_simplify_face_scan(root)
    f = one(r, "patch-retirement", "dup-defense:outer_api")
    assert f["severity"] == "med"
    assert "sanitize_name" in f["evidence"] and "删了会怎样" in f["suggestion"]


def _long_body(n: int) -> str:
    return "".join("    x%d = %d\n" % (i, i) for i in range(n))


def test_s7_long_function_boundary_truth_table(tmp_path):
    """80 行不报、81 行报 low——阈值边界真值表（阈值常量 LONG_FUNC_LINES=80）。"""
    files = {}
    for label, n in (("ok80", ms.LONG_FUNC_LINES), ("bad81", ms.LONG_FUNC_LINES + 1)):
        files["%s/len_%s.py" % (ENGINE, label)] = (
            "def len_%s():\n%s    return None\n" % (label, _long_body(n - 2)))
    root = make_repo(tmp_path, files)
    r = ms.run_simplify_face_scan(root)
    assert not findings_of(r, "long-function", "len_ok80")
    f = one(r, "long-function", "len_bad81")
    assert f["severity"] == "low" and ("81" in f["evidence"] and "80" in f["evidence"])


def test_s7_nesting_depth_boundary_truth_table(tmp_path):
    """深度 5 不报、6 报 low（If 链；阈值常量 MAX_NEST_DEPTH=5）。"""
    def src(depth: int) -> str:
        lines = ["def deep_%d(x):" % depth]
        ind = "    "
        for i in range(depth):
            lines.append("%sif x > %d:" % (ind * (i + 1), i))
        lines.append("%sx = 1" % (ind * (depth + 1)))
        lines.append("%sreturn x" % ind)
        return "\n".join(lines) + "\n"

    root = make_repo(tmp_path, {
        "%s/deep5.py" % ENGINE: src(5),
        "%s/deep6.py" % ENGINE: src(6),
    })
    r = ms.run_simplify_face_scan(root)
    assert not findings_of(r, "deep-nesting", "deep5")
    one(r, "deep-nesting", "deep6")


# ========================================================================================
# 域注入（C3）/ 韧性（畸形输入）/ 心跳与形状
# ========================================================================================

def test_c3_scan_roots_injection(tmp_path):
    """同一定义在注入域外不被扫（域注入真值表：换 roots 换候选集）。"""
    root = make_repo(tmp_path, {
        "elsewhere/lone.py": "def lonely_elsewhere():\n    return 1\n",
    })
    r = ms.run_mechanism_face_scan(root, scan_roots=("elsewhere",))
    one(r, "dead-mechanism", "lonely_elsewhere")
    r2 = ms.run_mechanism_face_scan(root, scan_roots=("server/engine",))
    assert not findings_of(r2, "dead-mechanism", "lonely_elsewhere")
    assert r2["meta"]["scan_roots"] == ["server/engine"]


def test_malformed_unparseable_and_unreadable_degrade(tmp_path):
    """坏 ast（SyntaxError）+ 不可读（乱码字节）逐项降级进 meta，其余候选照扫不株连。"""
    root = make_repo(tmp_path, {
        "%s/broken.py" % ENGINE: "def oops(:\n    pass\n",
        "%s/dead_ok.py" % ENGINE: DEAD_MOD,
    })
    (root / ENGINE / "binary_junk.py").write_bytes(b"\x00\xff\xfe\x00binary")
    r = ms.run_mechanism_face_scan(root)
    one(r, "dead-mechanism", "zombie_deploy")          # 好文件照扫
    degraded = "\n".join(r["meta"]["degraded"])
    assert "broken.py (unparseable" in degraded
    assert "binary_junk.py (unreadable" in degraded


def test_missing_repo_root_fails_closed(tmp_path):
    """仓根缺失 → ScanError 点名（fail-closed，非静默空结果）。"""
    with pytest.raises(ms.ScanError):
        ms.run_mechanism_face_scan(tmp_path / "nope")


def test_unknown_face_fails_closed_with_wired_list(tmp_path):
    """未知面 → ScanError 点名已接线面清单（分派 fail-closed，不静默回退测试面）。"""
    with pytest.raises(ms.ScanError) as ei:
        ms.run_face_scan("bogus-face", tmp_path)
    assert "mechanism" in str(ei.value) and "simplify" in str(ei.value)


def test_heartbeat_and_result_shape(tmp_path):
    """零发现 → heartbeat=true；result 形状与票①六键同构（UI 巡检行消费不破坏）。"""
    root = make_repo(tmp_path, {"%s/empty_mod.py" % ENGINE: "x = 1\n"})
    r = ms.run_simplify_face_scan(root)
    assert r["heartbeat"] is True and r["findings"] == []
    for key in ("face", "findings", "summary", "heartbeat", "meta"):
        assert key in r
    assert r["meta"]["red_line"].startswith("巡检只出报告")


def test_cli_single_line_json_contract(tmp_path):
    """CLI 契约（故障模式 4）：stdout 单行 JSON {ok, result|error}，ok 面含 face。"""
    root = make_repo(tmp_path, {"%s/dead_mod.py" % ENGINE: DEAD_MOD})
    proc = subprocess.run(
        [sys.executable, str(POC / "inspection_scan_ms.py"),
         "--face", "simplify", "--repo-root", str(root)],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0
    lines = [l for l in proc.stdout.strip().splitlines() if l.strip()]
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["ok"] is True and payload["result"]["face"] == "simplify"


def test_finding_id_stability_and_sorting(tmp_path):
    """id 确定性（同输入同 id，跨期 dedupe 前提）+ 确定性排序。"""
    root = make_repo(tmp_path, {"%s/dead_mod.py" % ENGINE: DEAD_MOD})
    a = ms.run_mechanism_face_scan(root)
    b = ms.run_mechanism_face_scan(root)
    assert [f["id"] for f in a["findings"]] == [f["id"] for f in b["findings"]]
    sev_rank = {"high": 0, "med": 1, "low": 2}
    ranks = [sev_rank[f["severity"]] for f in a["findings"]]
    assert ranks == sorted(ranks)
