"""t260916-21 admin.log 轮转面单测（按天轮转/保留窗/同日过大顺切/写失败点名）。

覆盖（工单验收①-⑤ + review C1/C2/C3/C6 + 合并门宿主修订①②③）：
- 日切：跨日首写惰性轮转、归档名=admin.log.YYYYMMDD（mtime 日=关闭日）、
  新文件续写、O_APPEND 行完整性；
- 存量迁移（②）：现存文件（含旧 run_id/actor/name schema 行 + 新行）字节级
  一致原样归档（sha256），不删不截断；
- 恰好一次（①）：多进程混合写者并发（走轮转逻辑的 audit 写者 ×N + 纯按路径
  append 的写者 ×M，模拟 tools_registry/workbench 同语义写集外写者）下归档
  恰一份、总行数守恒、每行恰落一个文件、无 rolling 残留；
- 同日过大顺切（④，宿主 260916 定稿措辞=纯拆分无告警语义）：同日超阈切
  admin.log.YYYYMMDD-HHMMSS，行数守恒；≤0=关；
- 保留窗（③）：**默认 14 天（宿主 260916 定稿）**、过期删、窗内留、≤0=永不删；
  删除面仅限归档命名面（admin.log.bak / 非法日期 20269999 / 怪后缀 / 同名目录
  跳过不炸）；
- 配置面（宿主修订②：project metadata，不用 env 旋钮）：引擎所属项目
  project.yaml 顶层 admin_log: {keep_days, max_mb} 读面——缺省 14/512 兜底、
  畸形值回落、≤0 照传、缓存随注册表/文件变更刷新；shared 装载器对该 additive
  字段的容忍（旧读取方不炸、条目不被隔离）；
- rolling 孤儿（C2）：先按 mtime 日收编入归档面（不静默删），收编失败才降级
  删除并点名；超窗孤儿收编后由下次清扫按归档面政策处置；
- 写失败点名（⑤）：回执带 audit_write_failed、stderr 留痕、logging WARN、
  client.py _emit 先审计后打印（marker 可达 stdout 回执）；
- env 隔离（⑥）：SANDBAR_ADMIN_LOG 全套面（归档/清扫/去重）从该路径派生。
全程禁网络/真 Temporal/真 git；日志路径与注册表桩一律 env 指向 tmp。
"""
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

import audit
import shared

ENGINE_DIR = Path(audit.__file__).resolve().parent


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    """每用例独立日志文件 + 独立注册表根（空=内置缺省 14/512）+ 配置缓存复位。"""
    log = tmp_path / "admin.log"
    monkeypatch.setenv("SANDBAR_ADMIN_LOG", str(log))
    reg = tmp_path / "registry"
    reg.mkdir()
    monkeypatch.setenv("SANDBAR_PROJECTS_DIR", str(reg))
    monkeypatch.delenv(audit.ENTRY_ENV, raising=False)
    monkeypatch.delenv(audit.CALL_ID_ENV, raising=False)
    audit._reset_config()
    return log


def _day(ts):
    return time.strftime("%Y%m%d", time.localtime(ts))


def _ago(days):
    return time.time() - days * 86400.0


def _seed(log, text, mtime=None):
    log.write_text(text, encoding="utf-8")
    if mtime is not None:
        os.utime(log, (mtime, mtime))


def _archives(tmp_path, log_name="admin.log"):
    return sorted(p for p in tmp_path.iterdir()
                  if p.name.startswith(log_name + ".")
                  and not p.name.startswith("%s.%s." % (log_name, audit.ROLLING_TAG)))


def _stub_registry(reg, keep=None, max_mb=None, key="enginetest"):
    """造一个合法注册表桩：引擎所属项目条目（dirs 覆盖引擎仓根）+ 可选 admin_log
    配置块。返回条目 yaml 路径。"""
    d = Path(reg) / key
    d.mkdir(parents=True, exist_ok=True)
    lines = ["schema: v1", "project:", "  - key: %s" % key,
             "    name: 引擎测试桩", "    dirs:", "      - %s" % audit.ENGINE_REPO]
    if keep is not None or max_mb is not None:
        lines.append("admin_log:")
        if keep is not None:
            lines.append("  keep_days: %d" % keep)
        if max_mb is not None:
            lines.append("  max_mb: %d" % max_mb)
    y = d / "project.yaml"
    y.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return y


# ---------- 配置面：解析纯函数（外部输入面，畸形必回落不炸） ----------

def test_parse_admin_log_overrides_basic():
    text = ("schema: v1\nproject:\n  - key: k\n    name: n\n    dirs:\n"
            "      - /tmp/k\n"
            "admin_log:\n"
            "  keep_days: 7   # 行尾注释不污染\n"
            "  max_mb: 256\n")
    assert audit._parse_admin_log_overrides(text) == {"keep_days": 7, "max_mb": 256}


def test_parse_admin_log_overrides_absent_block():
    assert audit._parse_admin_log_overrides("schema: v1\nproject:\n") == {}


def test_parse_admin_log_overrides_malformed_values_skipped():
    text = ("admin_log:\n"
            "  keep_days: 两周\n"      # 非整数=该键回落缺省
            "  max_mb: 1.5\n"          # 非整数
            "  unknown_key: 3\n"       # 不认的子键=忽略
            "other_top: 1\n"           # 顶层他键收块
            "  keep_days: 99\n")       # 块外的缩进行不得误收
    assert audit._parse_admin_log_overrides(text) == {}


def test_parse_admin_log_overrides_negative_passthrough():
    text = "admin_log:\n  keep_days: 0\n  max_mb: -1\n"
    assert audit._parse_admin_log_overrides(text) == {"keep_days": 0, "max_mb": -1}


def test_parse_admin_log_overrides_flow_style_unsupported():
    """行内 flow（admin_log: {keep_days: 7}）不认=整块回落缺省（注册表块风格既有形状）。"""
    assert audit._parse_admin_log_overrides("admin_log: {keep_days: 7}\n") == {}


# ---------- 配置面：读面（引擎所属项目条目 + 内置缺省兜底 + 缓存刷新） ----------

def test_config_defaults_when_registry_empty():
    cfg = audit._admin_log_config()
    assert cfg["keep_days"] == 14  # 宿主 260916 定稿默认
    assert cfg["max_mb"] == 512
    assert audit._oversize_bytes() == 512 * 1024 * 1024


def test_config_reads_engine_project_entry():
    _stub_registry(Path(os.environ["SANDBAR_PROJECTS_DIR"]), keep=2, max_mb=1)
    audit._reset_config()
    cfg = audit._admin_log_config()
    assert cfg["keep_days"] == 2 and cfg["max_mb"] == 1
    assert audit._oversize_bytes() == 1024 * 1024
    assert audit._keep_days() == 2


def test_config_cache_reloads_on_file_change():
    reg = Path(os.environ["SANDBAR_PROJECTS_DIR"])
    y = _stub_registry(reg, keep=2, max_mb=1)
    audit._reset_config()
    assert audit._keep_days() == 2
    y.write_text("schema: v1\nproject:\n  - key: enginetest\n    name: n\n"
                 "    dirs:\n      - %s\nadmin_log:\n  keep_days: 9\n" % audit.ENGINE_REPO,
                 encoding="utf-8")
    st = y.stat()
    os.utime(y, (st.st_atime, st.st_mtime + 2))  # mtime 变更 → 缓存刷新
    assert audit._keep_days() == 9


def test_config_malformed_yaml_falls_back():
    reg = Path(os.environ["SANDBAR_PROJECTS_DIR"])
    d = reg / "enginetest"
    d.mkdir()
    (d / "project.yaml").write_bytes(b"\xff\xfe garbage")
    audit._reset_config()
    assert audit._admin_log_config()["keep_days"] == 14  # fail-open 内置缺省


def test_config_non_covering_entry_ignored():
    """dirs 不覆盖引擎仓根的条目（如别的项目）不当作引擎所属项目。"""
    reg = Path(os.environ["SANDBAR_PROJECTS_DIR"])
    d = reg / "otherproj"
    d.mkdir()
    (d / "project.yaml").write_text(
        "schema: v1\nproject:\n  - key: otherproj\n    name: n\n    dirs:\n"
        "      - /Users/user/Documents/dengzhufpv\nadmin_log:\n  keep_days: 1\n",
        encoding="utf-8")
    audit._reset_config()
    assert audit._admin_log_config()["keep_days"] == 14


def test_shared_loader_tolerates_admin_log_field():
    """宿主修订②：注册表 schema 加字段要容忍旧读取方——shared 装载器对顶层
    admin_log: 块透传（条目正常装载、零隔离、条目形状不带该块）。"""
    _stub_registry(Path(os.environ["SANDBAR_PROJECTS_DIR"]), keep=2, max_mb=1)
    projects, quarantined = shared.load_projects_registry()
    assert quarantined == []
    assert [p["key"] for p in projects] == ["enginetest"]
    assert "admin_log" not in projects[0]


# ---------- 日切（验收①）+ 存量迁移（验收②） ----------

def test_first_write_creates_fresh_file(tmp_path):
    cid = audit.audit_call("x", {"ok": True})
    log = audit._log_path()
    assert log.exists() and cid
    assert _archives(tmp_path) == []  # 首写无归档


def test_day_rotation_archives_and_continues(tmp_path):
    log = audit._log_path()
    _seed(log, "old-row\n", mtime=_ago(2))
    audit.audit_call("fresh", {"ok": True})
    day = _day(_ago(2))
    arch = tmp_path / ("admin.log.%s" % day)
    assert arch.read_text(encoding="utf-8") == "old-row\n"  # 原样归档
    assert log.read_text(encoding="utf-8").count("\n") == 1  # 新文件续写
    assert json.loads(log.read_text(encoding="utf-8").splitlines()[0])["sub"] == "fresh"


def test_legacy_two_schema_rows_archived_byte_identical(tmp_path):
    """存量迁移：跨两代 schema 行（旧 run_id/actor/name → 新 call_id/source/sub）
    字节级一致归档，不删不截断（验收②）。"""
    log = audit._log_path()
    legacy = (
        '{"ts": 1759528500, "run_id": "r1", "actor": "deepseek-chat", "name": "params_get"}\n'
        '{"ts": 1759528600, "call_id": "c2", "source": "bare", "sub": "ticket-list", "ok": true}\n'
    )
    _seed(log, legacy, mtime=_ago(2))
    before = hashlib.sha256(log.read_bytes()).hexdigest()
    audit.audit_call("post-rotation", {"ok": True})
    arch = tmp_path / ("admin.log.%s" % _day(_ago(2)))
    assert hashlib.sha256(arch.read_bytes()).hexdigest() == before  # 字节级一致
    rows = [json.loads(x) for x in arch.read_text(encoding="utf-8").splitlines()]
    assert "run_id" in rows[0] and "call_id" in rows[1]  # 两代 schema 行都留考古


# ---------- 同日过大顺切（验收④，宿主定稿措辞） ----------

def test_oversize_cut_same_day_when_over_threshold(tmp_path):
    _stub_registry(Path(os.environ["SANDBAR_PROJECTS_DIR"]), max_mb=1)  # 1MB 可测阈值
    audit._reset_config()
    log = audit._log_path()
    n = 1300
    for i in range(n):  # 每行定长 ~900B，累计必过 1MB
        audit.audit_call("bulk", {"ok": True, "blob": "z" * 700})
    audit.audit_call("after-cut", {"ok": True})  # 越阈后首写 → 顺切下一文件
    archs = [p for p in _archives(tmp_path)
             if re.match(r"^admin\.log\.\d{8}-\d{6}(-[0-9a-f]{1,8})?$", p.name)]
    assert len(archs) == 1  # 当日顺切恰一刀
    arch_rows = len(archs[0].read_text(encoding="utf-8").splitlines())
    active_rows = len(log.read_text(encoding="utf-8").splitlines())
    assert arch_rows + active_rows == n + 1  # 行数守恒（零丢失）
    assert arch_rows >= 1 and active_rows >= 1  # 刀落在越阈后的首次写入前


def test_oversize_zero_disables_cut(tmp_path):
    _stub_registry(Path(os.environ["SANDBAR_PROJECTS_DIR"]), max_mb=0)  # ≤0=关顺切
    audit._reset_config()
    log = audit._log_path()
    for i in range(1300):  # 累计 ~1.1MB 超任意小阈值，但顺切已关
        audit.audit_call("bulk", {"ok": True, "blob": "z" * 700})
    audit.audit_call("tail", {"ok": True})
    assert _archives(tmp_path) == []  # 零归档
    assert len(log.read_text(encoding="utf-8").splitlines()) == 1301


# ---------- 保留窗（验收③，默认 14 天）+ 清扫面健壮（C3） ----------

def test_keep_default_14_days_behavior(tmp_path):
    """宿主修订①：默认保留 14 天——空注册表（内置缺省）下 13 天档留、15 天档删。"""
    (tmp_path / ("admin.log.%s" % _day(_ago(13)))).write_text("in\n", encoding="utf-8")
    (tmp_path / ("admin.log.%s" % _day(_ago(15)))).write_text("out\n", encoding="utf-8")
    log = audit._log_path()
    _seed(log, "old\n", mtime=_ago(2))
    audit.audit_call("fresh", {"ok": True})  # 触发轮转+清扫（缺省 14）
    assert (tmp_path / ("admin.log.%s" % _day(_ago(13)))).exists()
    assert not (tmp_path / ("admin.log.%s" % _day(_ago(15)))).exists()


def test_keep_window_deletes_expired_only(tmp_path):
    _stub_registry(Path(os.environ["SANDBAR_PROJECTS_DIR"]), keep=2)
    audit._reset_config()
    for days in (1, 3):
        (tmp_path / ("admin.log.%s" % _day(_ago(days)))).write_text("x\n", encoding="utf-8")
    (tmp_path / "admin.log.bak").write_text("keep\n", encoding="utf-8")  # 命名面外
    (tmp_path / "admin.log.20269999").write_text("keep\n", encoding="utf-8")  # 非法日期
    log = audit._log_path()
    _seed(log, "old\n", mtime=_ago(2))
    audit.audit_call("fresh", {"ok": True})  # 触发轮转+清扫
    assert not (tmp_path / ("admin.log.%s" % _day(_ago(3)))).exists()  # 过期删
    assert (tmp_path / ("admin.log.%s" % _day(_ago(1)))).exists()  # 窗内留
    assert (tmp_path / "admin.log.bak").exists()  # 面外不碰
    assert (tmp_path / "admin.log.20269999").exists()  # 非法日期不碰


def test_keep_zero_keeps_everything(tmp_path):
    _stub_registry(Path(os.environ["SANDBAR_PROJECTS_DIR"]), keep=0)  # ≤0=永不删
    audit._reset_config()
    old = tmp_path / ("admin.log.%s" % _day(_ago(40)))
    old.write_text("x\n", encoding="utf-8")
    log = audit._log_path()
    _seed(log, "old\n", mtime=_ago(2))
    audit.audit_call("fresh", {"ok": True})
    assert old.exists()


def test_sweep_skips_directory_and_weird_faces(tmp_path, capsys):
    """review C3：清扫消费目录列表=外部输入面——同名目录/怪名跳过不炸、删除失败
    stderr 留痕不 raise。"""
    d = tmp_path / "admin.log.20260101"
    d.mkdir()  # 归档名同名目录
    (tmp_path / "admin.log.2026010").write_text("x\n", encoding="utf-8")  # 7 位
    audit._sweep()
    assert d.is_dir()
    assert (tmp_path / "admin.log.2026010").exists()
    audit._sweep(now=time.time())  # 重复跑同样不炸
    assert "Traceback" not in capsys.readouterr().err


def test_sweep_deletion_failure_named_not_raised(tmp_path, capsys):
    if getattr(os, "geteuid", lambda: 1)() == 0:
        pytest.skip("root 下只读目录删文件仍成功，无法注错")
    expired = tmp_path / ("admin.log.%s" % _day(_ago(40)))
    expired.write_text("x\n", encoding="utf-8")
    _stub_registry(Path(os.environ["SANDBAR_PROJECTS_DIR"]), keep=2)
    audit._reset_config()
    d = tmp_path
    d.chmod(0o555)  # 目录只读：unlink 必败（macOS/Linux 语义）
    try:
        audit._sweep(now=time.time())  # 不 raise 即过
    finally:
        d.chmod(0o755)
    assert expired.exists()  # 删不动就保留（数据保全优先）
    assert "保留窗删除失败" in capsys.readouterr().err


# ---------- rolling 孤儿收编（review C2：数据保全） ----------

def test_orphan_rolling_adopted_then_policy_deleted(tmp_path, capsys):
    _stub_registry(Path(os.environ["SANDBAR_PROJECTS_DIR"]), keep=2)
    audit._reset_config()
    orphan = tmp_path / "admin.log.rolling.999.deadbe"
    orphan.write_text('{"orphan": true}\n', encoding="utf-8")
    os.utime(orphan, (_ago(3), _ago(3)))
    log = audit._log_path()
    _seed(log, "old\n", mtime=_ago(2))
    audit.audit_call("fresh", {"ok": True})  # 轮转赢家跑清扫 → 收编孤儿
    adopted = tmp_path / ("admin.log.%s" % _day(_ago(3)))
    assert adopted.exists()
    assert '{"orphan": true}\n' == adopted.read_text(encoding="utf-8")  # 内容保全
    assert not orphan.exists()
    audit._sweep(now=time.time())  # 第二次清扫：收编后超窗 → 按归档面政策处置
    assert not adopted.exists()
    assert "Traceback" not in capsys.readouterr().err


def test_orphan_adopt_failure_degrades_named(tmp_path, capsys):
    if getattr(os, "geteuid", lambda: 1)() == 0:
        pytest.skip("root 下只读目录仍可改名，无法注错")
    _stub_registry(Path(os.environ["SANDBAR_PROJECTS_DIR"]), keep=0)  # 关删除面，单测收编降级腿
    audit._reset_config()
    orphan = tmp_path / "admin.log.rolling.998.cafe12"
    orphan.write_text('{"orphan": 1}\n', encoding="utf-8")
    d = tmp_path
    d.chmod(0o555)  # 目录只读：收编 rename 必败 → 降级删除也必败 → 保留+点名
    try:
        audit._sweep(now=time.time())
    finally:
        d.chmod(0o755)
    assert orphan.exists()  # 删不动就保留
    assert "rolling 孤儿收编失败" in capsys.readouterr().err


# ---------- 去重：归档名永不覆盖 ----------

def test_dedup_never_overwrites_existing_archive(tmp_path):
    day = _day(_ago(2))
    arch = tmp_path / ("admin.log.%s" % day)
    arch.write_text("PREEXISTING\n", encoding="utf-8")
    log = audit._log_path()
    _seed(log, "seed-row\n", mtime=_ago(2))
    audit.audit_call("fresh", {"ok": True})
    assert arch.read_text(encoding="utf-8") == "PREEXISTING\n"  # 旧归档不动
    deduped = [p for p in _archives(tmp_path) if p.name.startswith("admin.log.%s-" % day)]
    assert len(deduped) == 1
    assert deduped[0].read_text(encoding="utf-8") == "seed-row\n"  # 去重后缀保全


# ---------- 多进程混合写者并发恰好一次（验收① + review C1） ----------

_ROT_CHILD = """
import os, sys, time, random
sys.path.insert(0, %(engine)r)
import audit
time.sleep(random.uniform(0, 0.05))
for i in range(%(per)d):
    audit.audit_call('rot-' + os.environ['TAG'] + '-' + str(i), {'ok': True})
"""

_PLAIN_CHILD = """
import os, time, random
time.sleep(random.uniform(0, 0.02))
p = os.environ['SANDBAR_ADMIN_LOG']
for i in range(%(per)d):  # 每行独立开/关：不持 fd 跨轮转（tools_registry 同语义）
    with open(p, 'a', encoding='utf-8') as f:
        f.write('plain-' + os.environ['TAG'] + '-' + str(i) + '\\n')
"""


def test_multiprocess_mixed_writers_rotate_exactly_once(tmp_path):
    """混合写者并发（走轮转逻辑 ×8 + 纯按路径追加 ×4，对齐 worker×N + cli +
    workbench 写者群）：轮转恰好一次、总行数守恒、每行恰落一个文件、无 rolling
    残留、无静默分叉。两波编排：轮转写者先竞速（真并发争抢跨日切），纯追加者
    随后混跑（对齐真实频率面——audit 行是高频主体）；纯追加者若抢在轮转前写会
    刷新 mtime 使本日无轮转，那是设计的正确语义而非缺陷，故不与其竞速起点。"""
    n_rot, n_plain, per = 8, 4, 3
    log = audit._log_path()
    _seed(log, "seed-line\n", mtime=_ago(2))
    day = _day(_ago(2))
    env = dict(os.environ)  # SANDBAR_PROJECTS_DIR（fixture 空注册表）随行：子进程走缺省配置
    env["SANDBAR_ADMIN_LOG"] = str(log)

    def _spawn(tag, code):
        env_k = dict(env)
        env_k["TAG"] = tag
        return subprocess.Popen([sys.executable, "-c", code], env=env_k,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    rot_procs = [_spawn("r%02d" % k, _ROT_CHILD % {"engine": str(ENGINE_DIR), "per": per})
                 for k in range(n_rot)]
    for k, p in enumerate(rot_procs):
        out, err = p.communicate(timeout=60)
        assert p.returncode == 0, "rot child %d failed: %s" % (k, err.decode()[:400])
    assert len(_archives(tmp_path)) == 1  # 轮转波：并发争抢下跨日切恰好一份
    plain_procs = [_spawn("p%02d" % k, _PLAIN_CHILD % {"per": per})
                   for k in range(n_plain)]
    for k, p in enumerate(plain_procs):
        out, err = p.communicate(timeout=60)
        assert p.returncode == 0, "plain child %d failed: %s" % (k, err.decode()[:400])
    # 恰好一次：归档仍恰一份、名字恰为关闭日、无去重后缀、无 rolling 残留
    archs = [p for p in _archives(tmp_path)
             if re.match(r"^admin\.log\.\d{8}(-[0-9a-f]{1,8})?$", p.name)]
    assert len(archs) == 1
    assert archs[0].name == "admin.log.%s" % day
    assert not list(tmp_path.glob("admin.log.%s.*" % audit.ROLLING_TAG))
    # 行数守恒 + 每行恰落一个文件（无丢失/无复制/无分叉双写）
    expected = ["seed-line"]
    for k in range(n_rot):
        for i in range(per):
            expected.append("rot-r%02d-%d" % (k, i))
    for k in range(n_plain):
        for i in range(per):
            expected.append("plain-p%02d-%d" % (k, i))
    got = []
    for p in [archs[0], log]:
        got.extend(p.read_text(encoding="utf-8").splitlines())

    def _rid(line):
        try:  # 审计 JSON 行取 sub；纯文本行（seed/plain）取原文
            return json.loads(line)["sub"]
        except Exception:
            return line

    assert sorted(map(_rid, got)) == sorted(expected)


def test_rotate_misgrabbed_new_file_restored(tmp_path):
    """inode 身份复核：stat→rename 窗口内文件已被换新（别人轮转后重建）时，
    rename 抓到的是新文件——必须原样还原、不算本进程轮转（不产生归档）。"""
    log = audit._log_path()
    _seed(log, "newcomer-row\n")  # mtime=今日（模拟别人的新文件）
    rotated = audit._rotate_active(log, 'day', expect_ino=123456789)  # 假 stat 到旧 inode
    assert rotated is False
    assert log.read_text(encoding="utf-8") == "newcomer-row\n"  # 原样还原
    assert _archives(tmp_path) == []  # 未误归档别人的新文件
    assert not list(tmp_path.glob("admin.log.%s.*" % audit.ROLLING_TAG))


# ---------- 写失败点名（验收⑤） ----------

def test_write_failure_stamps_receipt_and_warns(tmp_path, monkeypatch, capsys, caplog):
    bad = tmp_path / "occupied"
    bad.mkdir()  # 日志路径=已存在目录：open('a') 必败（跨平台稳，不依赖 chmod）
    monkeypatch.setenv("SANDBAR_ADMIN_LOG", str(bad))
    receipt = {"ok": True, "result": {}}
    cid = audit.audit_call("x", receipt)
    assert cid  # 回执主契约不受影响，call_id 照返
    assert "audit_write_failed" in receipt  # 回执点名（不静默吞）
    assert "audit_write_failed" not in (receipt.get("result") or {})
    assert "写失败" in capsys.readouterr().err  # stderr 通道
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings and "写失败" in warnings[0].getMessage()  # logging WARN 通道


def test_write_failure_non_dict_receipt_no_raise(tmp_path, monkeypatch):
    bad = tmp_path / "occupied"
    bad.mkdir()
    monkeypatch.setenv("SANDBAR_ADMIN_LOG", str(bad))
    audit.audit_call("x", None)  # 非 dict receipt：无处附着不炸
    audit.audit_call("y", "not-a-dict")


def test_emit_audits_before_print_marker_reaches_stdout(tmp_path):
    """client.py _emit 序（review C4 偏差面）：审计先于打印——写失败 marker 必须
    可达 stdout 回执（nusuyou/dengzhufpv 病灶回归锚）。真子进程跑未知子命令路径
    （不触 Temporal），日志路径=目录制造写失败。"""
    bad = tmp_path / "occupied"
    bad.mkdir()
    env = dict(os.environ)
    env["SANDBAR_ADMIN_LOG"] = str(bad)
    env["SANDBAR_TARGET_HOST"] = "127.0.0.1:9"  # 红线：不可达桩
    env.pop(audit.ENTRY_ENV, None)
    r = subprocess.run([sys.executable, str(ENGINE_DIR / "client.py"), "nosuch-sub"],
                       env=env, cwd=str(ENGINE_DIR), capture_output=True, timeout=60)
    assert r.returncode == 0
    out = json.loads(r.stdout.decode("utf-8").splitlines()[-1])
    assert "audit_write_failed" in out  # 打印在前则此处必空（病灶复现锚）
    assert "entry_hint" in out
    # 对照：可写路径 → 无 marker（成功面不添键，旧消费者零感知）
    env["SANDBAR_ADMIN_LOG"] = str(tmp_path / "ok.log")
    r2 = subprocess.run([sys.executable, str(ENGINE_DIR / "client.py"), "nosuch-sub"],
                        env=env, cwd=str(ENGINE_DIR), capture_output=True, timeout=60)
    out2 = json.loads(r2.stdout.decode("utf-8").splitlines()[-1])
    assert "audit_write_failed" not in out2
    rows = [json.loads(x) for x in (tmp_path / "ok.log").read_text(encoding="utf-8").splitlines()]
    assert rows and rows[-1]["sub"] == "nosuch-sub"  # 审计行照记


# ---------- env 隔离语义（验收⑥） ----------

def test_env_path_derives_all_faces(tmp_path, monkeypatch):
    """SANDBAR_ADMIN_LOG 语义不变：归档/清扫全从此路径派生（logname 面隔离）。"""
    mylog = tmp_path / "mylog.log"
    monkeypatch.setenv("SANDBAR_ADMIN_LOG", str(mylog))  # 换日志名：隔离面随之换
    _stub_registry(Path(os.environ["SANDBAR_PROJECTS_DIR"]), keep=2)
    audit._reset_config()
    decoy = tmp_path / ("admin.log.%s" % _day(_ago(40)))  # 同目录的默认名过期档
    decoy.write_text("decoy\n", encoding="utf-8")
    mine_expired = tmp_path / ("mylog.log.%s" % _day(_ago(40)))
    mine_expired.write_text("mine\n", encoding="utf-8")
    _seed(mylog, "old\n", mtime=_ago(2))
    audit.audit_call("fresh", {"ok": True})
    assert (tmp_path / ("mylog.log.%s" % _day(_ago(2)))).exists()  # 归档按 mylog 面
    assert mine_expired.exists() is False  # mylog 面过期档被清
    assert decoy.exists()  # 默认名面不属本日志，不碰
