#!/usr/bin/env python3
"""t260922-07 判据精度收口回归（离线秒级零网络零 docker；探针半按路径载入、引擎半
sys.path 载入，先例 test_probe_live_prompt.py / server/engine/tests/test_t260917_05）。

守四面（票面验收①②③⑤的 UT 锁；review 意见 1/2/4 条款在此落死）：
- 探针正文/侧车分流：0.1.1 金样本台账逐字不变（v0-full 10 行冻结，与场景
  sc_t260922_07_probe_sidecar_criteria 同源同值）+ 侧车单列 INVENTORY 恰 1 条 +
  侧车档正文行与 vN-full 逐行相等 + 正文/侧车分类真值表（.gz 篡改形=非正文仍红、
  未知新名不豁免）+ 仅侧车无正文仍响亮红（收窄不是静默豁免）；
- 越界位三根审计（纯函数）：根内三样各判根内、符号链接解析后归位、畸形输入
  （NUL 字节/判不了）宁红不猜、$HOME 恰在根内的怪环境=ENV 路径两向自洽、
  建位/清理全终态（含半途失败回收与 keep 取证保留）；
- 引擎两诊断面：session.lock/Session.LOCK 退出 unknown/盲区，双不识/假想新代名
  仍点名，正文双名与目录形态不入（既有语义回归），OSError→空清单，检疫动作零改动；
- 名单机械同源（review 意见2）：探针/引擎 SESSION_SIDECAR_NAMES 逐字相等且含
  session.lock——注释互指只是文字，机械断言才防名单漂移成假绿/假红。

运行：server/engine/.venv/bin/python -m pytest
integration/t260916-24/test_t260922_07_criteria_precision.py（引擎面 import
agent_activities 需 engine venv；探针面任意 py3.9+ 也可独立跑）。
"""
import importlib.util
import pathlib
import shutil
import subprocess
import sys

import pytest

T26 = pathlib.Path(__file__).resolve().parent
REPO = T26.parents[1]
PROBE = T26 / "probe_dsh_seam.py"

sys.path.insert(0, str(REPO / "server" / "engine"))
import agent_activities as aa  # noqa: E402

HAS_ZSTD = subprocess.run(["zstd", "--version"], capture_output=True).returncode == 0


def _load_probe():
    spec = importlib.util.spec_from_file_location("probe_dsh_seam_t26092207", PROBE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def probe():
    return _load_probe()


def _ledger_of(probe, rel, tmp_path):
    """金样本档 → (Rows, 台账行字面清单)（/tmp 副本操作，不改仓内 fixtures）。"""
    dst = tmp_path / rel.replace("/", "_")
    shutil.copytree(str(probe.FIXTURE_ROOT / rel), str(dst))
    r = probe.Rows()
    probe.check_session_bundle(dst / "sessions", *probe.FIXTURE_ROUTE, rows=r)
    return r, [probe.format_row(x) for x in r.rows]


# ---- 0.1.1 判据逐字不变锚（与场景 sc_t260922_07_probe_sidecar_criteria 同源同值，
# ---- 改前实跑快照 260922；两处常量互为机械锁）----

V0_GOLDEN_LEDGER = (
    "[PASS] a 文件名口径：probe/t260916-24-gen0/session.jsonl → v0 代口径",
    "[PASS] 完整性（坏行/半行/坏帧）：全部记录可解析",
    "[PASS] b 必填面 provider/model：provider='probe-provider' model='probe-model-X'"
    "（context 主/header 备）",
    "[PASS] b 必填面 usage：inputTokens/outputTokens 均可取整型",
    "[PASS] b 可选面 cacheReadTokens：在场且整型（max=3）",
    "[PASS] b+ 消费必需型：assistant/message ×1",
    "[PASS] b+ 消费必需型：request/context ×1",
    "[PASS] b+ 消费必需型：request/header ×1",
    "[INVENTORY] b+ 族内类型：assistant/chunk ×1（属于 v0.1.1 族；漂移不影响本票判据，"
    "底册交 T5）",
    "[PASS] d 钉模型生效：实际 provider/model == 期望（probe-provider/probe-model-X）",
)


def test_v0_golden_ledger_verbatim(probe, tmp_path):
    """0.1.1 金样本台账 10 行逐字不变（票面验收①后半）：判据收口对 0.1.1 零漂移。"""
    _, lines = _ledger_of(probe, "golden/v0-full", tmp_path)
    assert tuple(lines) == V0_GOLDEN_LEDGER


def test_vn_full_ledger_unchanged_by_narrowing(probe, tmp_path):
    """vN 全键档（无侧车）台账同样不受收窄影响（无侧车时零新行零改行）。"""
    _, lines_full = _ledger_of(probe, "golden/vN-full", tmp_path)
    assert len(lines_full) == 11  # 改前基线快照（260922）：1+1+3+3+2+1 行
    assert not any("侧车" in ln for ln in lines_full)
    assert lines_full[0].startswith("[PASS] a 文件名口径")
    assert lines_full[-1].startswith("[PASS] d 钉模型生效")


def test_vn_sidecar_green_body_rows_equal_vn_full_and_sidecar_listed_once(probe, tmp_path):
    """票面验收①：0.1.5 侧车形金样本 → 绿；正文判据行与 vN-full 逐行相等（侧车
    不进正文清单、不改任何正文行）；session.lock 的 INVENTORY 单列行恰 1 条。"""
    r_side, lines_side = _ledger_of(probe, "golden/vN-sidecar", tmp_path)
    _, lines_full = _ledger_of(probe, "golden/vN-full", tmp_path)
    assert r_side.count("FAIL") == 0 and r_side.count("ENV") == 0
    assert [ln for ln in lines_side if "侧车" not in ln] == lines_full
    lock_rows = [ln for ln in lines_side
                 if ln.startswith("[INVENTORY]") and "session.lock" in ln]
    assert len(lock_rows) == 1
    assert "不计入正文计数" in lock_rows[0]


# ---- 正文/侧车分类真值表（review 意见1 勘误版：.gz 篡改形=非正文仍红）----

@pytest.mark.parametrize("name,gen", [
    ("session.jsonl", "v0"),
    ("session.jsonl.zstd", "v0"),
    ("session.v3.jsonl", "vN"),
    ("session.v3.jsonl.zstd", "vN"),
    ("session.v3.jsonl.gz", None),   # 篡改形：非正文（GEN_PATTERNS 不匹配 .gz）
    ("session.title.txt", None),     # 未知新名：非正文
    ("session.lock", None),          # 侧车：非正文
    ("Session.lock", None),
    ("session", None),               # 裸前缀也非正文
])
def test_body_gen_truth_table(probe, name, gen):
    assert probe.session_body_gen(name) == gen


@pytest.mark.parametrize("name,want", [
    ("session.lock", True),
    ("Session.LOCK", True),          # 大小变体同豁免（名单判按 lower 归一）
    ("session.jsonl", False),
    ("session.v3.jsonl.zstd", False),
    ("session.title.txt", False),    # 未知新名不做形状豁免——先红、人工裁决后入名单
    ("lock.session", False),
    ("", False),
])
def test_sidecar_truth_table(probe, name, want):
    assert probe.is_session_sidecar(name) is want


def test_collect_body_and_sidecar_split(probe, tmp_path):
    """收集面分流：正文只收两代口径；侧车名单命中（大小写变体跨目录注入——macOS
    大小写不敏感同目录会撞名）；.gz 篡改形两边都不收（留给断言 a 红）。"""
    sess = tmp_path / "sessions"
    d = sess / "t" / "t-dev"
    d.mkdir(parents=True)
    (d / "session.v3.jsonl.zstd").write_bytes(b"junk")
    (d / "session.lock").write_text("")
    d2 = sess / "t" / "t-integration"
    d2.mkdir(parents=True)
    (d2 / "Session.LOCK").write_text("")
    (d / "session.v3.jsonl.gz").write_text("junk")
    assert [f.name for f in probe.collect_session_files(sess)] == ["session.v3.jsonl.zstd"]
    assert sorted(f.name for f in probe.collect_sidecar_files(sess)) == \
        ["Session.LOCK", "session.lock"]


def test_sidecar_only_tree_still_loud_red(probe, tmp_path):
    """只有侧车没有正文 = 仍按断言 a 响亮红「无任何会话产物」——单列不是豁免红。"""
    dst = tmp_path / "tree"
    (dst / "sessions" / "t" / "t-dev").mkdir(parents=True)
    (dst / "sessions" / "t" / "t-dev" / "session.lock").write_text("")
    r = probe.Rows()
    probe.check_session_bundle(dst / "sessions", "p", "m", rows=r)
    fail_rows = [x for x in r.rows if x[0] == "FAIL"]
    assert any("a 文件名口径" in n for _lvl, n, _d in fail_rows)
    assert any("无任何会话产物" in d for _lvl, _n, d in fail_rows)


def test_tampered_gz_still_red_under_assertion_a(probe, tmp_path):
    """不放宽反方向（票面验收⑤）：bad-filename 档（.gz 篡改形，非正文不收不豁免）
    改后仍命中断言名「a 文件名口径」——红形从「两代口径均不匹配」变为「无正文产物」，
    断言名与拦停级不变（改前 12 FAIL 基线在结果文件）。"""
    r, _ = _ledger_of(probe, "tampered/bad-filename", tmp_path)
    fails = [x[1] for x in r.rows if x[0] == "FAIL"]
    assert fails and any("a 文件名口径" in n for n in fails)


def test_unknown_new_name_not_collected_and_still_red(probe, tmp_path):
    """未知新形（假想 session.title.txt）不进正文清单也不豁免——断言 a 仍红点名。"""
    dst = tmp_path / "tree"
    (dst / "sessions" / "t" / "t-dev").mkdir(parents=True)
    (dst / "sessions" / "t" / "t-dev" / "session.title.txt").write_text(
        '{"type":"assistant/message","data":{"usage":{"inputTokens":1,"outputTokens":2}}}\n')
    r = probe.Rows()
    probe.check_session_bundle(dst / "sessions", "p", "m", rows=r)
    assert any("a 文件名口径" in x[1] for x in r.rows if x[0] == "FAIL")


# ---- 越界位三根审计（纯函数；t260922-07②）----

def test_audit_inside_each_root_is_rejected(probe, tmp_path):
    """根内三样各判根内（改前病灶=目标建在 tmpdir∈可写根）：cwd 内 / /tmp 内 /
    tmpdir 内 → 一律 ok=False，detail 点名命中的根。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    tmpdir_root = pathlib.Path(probe.tempfile.gettempdir())
    for target in (ws / "esc.txt", tmp_path / "esc.txt", tmpdir_root / "esc-ut.txt"):
        ok, detail = probe.audit_escape_target(target, ws)
        assert ok is False
        assert "可写根内" in detail or "判不了" in detail


def test_audit_outside_roots_passes(probe, tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    ok, detail = probe.audit_escape_target(
        tmp_path / "outside" / "main-repo" / ".git" / "probe_escape.txt", ws,
        roots=[ws])
    assert ok is True and "三根之外" in detail


def test_audit_resolves_symlinks_before_judging(probe, tmp_path):
    """符号链接解析后归位：字面路径在根内、真实落点在根外 → 判根外（按 resolve 判，
    不按字符串前缀判）。roots 显式单根=鉴别力面。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    link = ws / "link"
    link.symlink_to(elsewhere, target_is_directory=True)
    ok, _ = probe.audit_escape_target(link / "x" / "probe_escape.txt", ws, roots=[ws])
    assert ok is True
    ok2, _ = probe.audit_escape_target(ws / "real" / "probe_escape.txt", ws, roots=[ws])
    assert ok2 is False


def test_audit_malformed_input_fails_closed(probe, tmp_path):
    """畸形输入（NUL 字节路径等判不了形态）→ ok=False 宁红不猜，不抛。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    ok, detail = probe.audit_escape_target("bad\x00path/probe_escape.txt", ws)
    assert ok is False
    assert "判不了" in detail


def test_audit_home_weird_env_honest_both_ways(probe, tmp_path):
    """怪环境两向自洽（计划 §1.2「$HOME 恰在 tmp 下」形态）：默认三根下，
    $HOME 在根内 → 必须判根内（ENV 路径），不因「目标在 $HOME」就放行；
    $HOME 在根外（本机常态）→ 判根外。同一不变量的诚实判定，环境无关可跑。"""
    ws = tmp_path / "ws"
    ws.mkdir()
    target = (pathlib.Path.home() / probe.ESCAPE_ROOT_NAME / "x" / "main-repo"
              / ".git" / "probe_escape.txt")
    ok, detail = probe.audit_escape_target(target, ws)
    roots = [pathlib.Path(str(r)).resolve() for r in probe.writable_roots(ws)]
    home_inside = any(pathlib.Path.home().resolve().is_relative_to(r) for r in roots)
    if home_inside:
        assert ok is False and "可写根内" in detail
    else:
        assert ok is True and "三根之外" in detail


def test_escape_build_and_cleanup_full_terminal(probe, tmp_path):
    """建位/清理全终态（票面验收②）：建真在场 → 清理零残留（含空父目录）；
    keep=取证保留不删。"""
    home = tmp_path / "home"
    home.mkdir()
    r = probe.Rows()
    main_repo, esc_dir = probe.build_escape_main_repo(r, home_root=home)
    assert main_repo is not None and (main_repo / ".git").is_dir()
    assert r.count("ENV") == 0 and r.count("FAIL") == 0
    probe.cleanup_escape_dir(esc_dir, keep=False)
    assert not esc_dir.exists()
    assert not (home / probe.ESCAPE_ROOT_NAME).exists()  # 父目录空则移除
    main2, esc2 = probe.build_escape_main_repo(r, home_root=home)
    probe.cleanup_escape_dir(esc2, keep=True)
    assert esc2.is_dir()  # keep：取证保留
    probe.cleanup_escape_dir(esc2, keep=False)
    probe.cleanup_escape_dir(None, keep=False)  # None=无建位面，幂等不抛


def test_escape_build_failure_is_env_red_never_fallback(probe, tmp_path):
    """建位失败（$HOME 位被文件占用）→ ENV 红点名 + (None, None)，绝不退回根内目标。"""
    home = tmp_path / "home"
    home.write_text("occupied")  # 目录位被文件占 → mkdir 必败
    r = probe.Rows()
    main_repo, esc_dir = probe.build_escape_main_repo(r, home_root=home)
    assert main_repo is None and esc_dir is None
    assert r.count("ENV") == 1
    assert "绝不退回" in "".join(x[2] for x in r.rows)


def test_render_live_prompt_contains_both_targets(probe, tmp_path):
    """prompt 渲染双路径在案（泳道内写 + $HOME 越界位），占位符守卫不破
    （t260922-03 回归锁延续到新目标位）。"""
    w = tmp_path / "lane" / "probe_write_here.txt"
    e = (pathlib.Path.home() / probe.ESCAPE_ROOT_NAME / "x" / "main-repo"
         / ".git" / "probe_escape.txt")
    out = probe.render_live_prompt(w, e)
    assert str(w) in out and str(e) in out
    with pytest.raises(AssertionError):
        probe._assert_placeholder_count("仅 %s 一个", 2, "漂移样本")


# ---- 引擎两诊断面（票面验收③）----

def _inject_tree(tmp_path):
    sess = tmp_path / ".dsh" / "sessions"
    dev = sess / "myslug" / "myslug-developer"
    dev.mkdir(parents=True)
    (dev / "session.v3.jsonl.zstd").write_text('{"type":"assistant/message"}\n')
    (dev / "session.lock").write_text("")
    (dev / "strange.session.bin").write_text("junk")
    rev = sess / "myslug" / "myslug-reviewer"
    rev.mkdir(parents=True)
    (rev / "session.lock").mkdir()          # 目录形态（is_file 守卫）
    (sess / "session.jsonl.zst").write_text("junk")  # 假想新代名
    return sess


def test_engine_sidecar_exits_both_diagnostic_faces(tmp_path):
    """改前红/改后绿（改前基线：两面均点名 session.lock/Session.LOCK——见结果文件）：
    侧车退出 unknown/盲区；双不识与假想新代名仍点名（收窄不误伤响亮面）；
    正文双名与目录形态不入（既有语义回归）。"""
    sess = _inject_tree(tmp_path)
    unknown = aa._session_suspect_unmatched(sess, "myslug")["unknown"]
    blind = aa._session_quarantine_blindspots(tmp_path / ".dsh")
    for names in (unknown, blind):
        assert not any(pathlib.PurePosixPath(x).name == "session.lock" for x in names)
    assert any(x.endswith("strange.session.bin") for x in unknown)
    assert any(x.endswith("session.jsonl.zst") for x in blind)
    assert not any(x.endswith("session.v3.jsonl.zstd")
                   for x in list(unknown) + list(blind))
    assert not any(x.endswith("myslug-reviewer/session.lock")
                   for x in list(unknown) + list(blind))


def test_engine_sidecar_case_variant_exempt(tmp_path):
    """大小写变体跨目录注入（macOS 大小写不敏感，同目录会撞成同一文件）。"""
    sess = tmp_path / ".dsh" / "sessions"
    it = sess / "myslug" / "myslug-integration"
    it.mkdir(parents=True)
    (it / "Session.LOCK").write_text("")
    unknown = aa._session_suspect_unmatched(sess, "myslug")["unknown"]
    blind = aa._session_quarantine_blindspots(tmp_path / ".dsh")
    assert not any(x.endswith("Session.LOCK") for x in list(unknown) + list(blind))


def test_engine_diagnostic_oserror_degrades_to_empty(tmp_path, monkeypatch):
    """OSError → 各类为空（既有语义回归，不放大环境故障）。"""
    sess = tmp_path / "s"
    sess.mkdir()

    def boom(self, pattern=None):
        raise OSError("boom")

    monkeypatch.setattr(pathlib.Path, "rglob", boom)
    assert aa._session_suspect_unmatched(sess, "t") == \
        {"unknown": [], "other_ticket": [], "legacy_flat": []}
    assert aa._session_quarantine_blindspots(tmp_path) == []


@pytest.mark.skipif(not HAS_ZSTD, reason="zstd CLI 不可用（检疫动作 zstd -t 同款依赖）")
def test_engine_quarantine_action_untouched(tmp_path):
    """检疫动作零改动（票面验收③「隔离点名口径不受影响」的机械锚）：撕裂正文仍被
    挪入 quarantine/torn-*；侧车在场不改变该行为。"""
    qsess = tmp_path / ".dsh" / "sessions" / "myslug" / "myslug-developer"
    qsess.mkdir(parents=True)
    torn = qsess / "session.v3.jsonl.zstd"
    torn.write_bytes(b"this is definitely not a zstd frame")
    (qsess / "session.lock").write_text("")
    aa._quarantine_torn_sessions(tmp_path / ".dsh")
    assert not torn.exists()
    qdir = tmp_path / ".sandbar" / "quarantine"
    moved = sorted(q.name for q in qdir.glob("torn-*")) if qdir.is_dir() else []
    assert moved


# ---- 名单机械同源（review 意见2）----

def test_sidecar_names_identical_across_probe_and_engine(probe):
    """探针/引擎两侧 SESSION_SIDECAR_NAMES 逐字相等且含 session.lock（跨边界无法
    共享模块——注释互指只是文字，机械断言才防名单漂移成假绿/假红）。"""
    pn = tuple(probe.SESSION_SIDECAR_NAMES)
    en = tuple(aa.SESSION_SIDECAR_NAMES)
    assert pn == en
    assert "session.lock" in pn
    assert pn == tuple(n.lower() for n in pn)  # 名单本体全小写（判按 lower 归一的前提）


def test_resume_set_semantics_body_only(probe, tmp_path):
    """resume 文件集随正文口径（票面验收①关联面）：before/after 集合由
    collect_session_files 取 → 侧车不再计入（0.1.5 下 resume 重建 lock 不假红）；
    「回落新建会话必落新正文文件」假设的声明在 check_resume docstring（记账非放宽）。"""
    sess = tmp_path / "sessions"
    d = sess / "t" / "t-dev"
    d.mkdir(parents=True)
    (d / "session.jsonl.zstd").write_bytes(b"junk")
    (d / "session.lock").write_text("")
    before = {str(f.relative_to(sess)) for f in probe.collect_session_files(sess)}
    (d / "session.v3.jsonl.zstd").write_bytes(b"junk2")  # 回落新建=新正文文件
    after = {str(f.relative_to(sess)) for f in probe.collect_session_files(sess)}
    assert after - before == {"t/t-dev/session.v3.jsonl.zstd"}
