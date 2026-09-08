"""t260905-10 面②＋面③ 单元测试：会话撕裂检疫增强 / 泳道落盘身份守卫。

面②（_quarantine_torn_sessions 两层检疫）：
  - 旧口径回归：帧裂（zstd -t 红）仍隔离；
  - 新口径核心腿：帧好但 JSONL record 中截断（t260906-05 两次卡死同型）→ 隔离；
  - 新口径变体：好帧内非 JSON 行 → 隔离；
  - 对照组（防「见档就隔离」反向事故）：多行合法 JSONL + 多帧 zstd 拼接、
    含裸空行、无尾换行的完整末行 → 一律**不**隔离；
  - sessions 目录缺失 → 零动作。

面③（_check_git_identity / prepare_workspace / _ensure_lane_deps）：
  - 身份缺失（GIT_CONFIG_NOSYSTEM=1 + 空 global，防系统级 gitconfig 假红）→ 红字点名；
  - 只缺一项 → 只点名缺项；
  - global 身份在位 → None；
  - prepare_workspace worktree 分支：身份缺失即 failed（开工前点名），
    dir 型不查身份；身份在位走 reused + 依赖软链（.venv 在 LANE_DEP_SYMLINKS）；
  - 主仓无 .venv（全新克隆）→ 跳过不报错（既有行为保留）。

UT 全程禁网络/真 Temporal/真 git（git 仅以 env 探针形式被 _check_git_identity
spawn 在 tmp 夹具上，不触碰任何真仓库）。
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agent_activities  # noqa: E402
from agent_activities import (  # noqa: E402
    LANE_DEP_SYMLINKS,
    _check_git_identity,
    _ensure_lane_deps,
    _quarantine_torn_sessions,
    _session_jsonl_torn,
    prepare_workspace,
)
from shared import WorkspacePrep  # noqa: E402

# ---------- 面②：夹具工具 ----------


def _zstd_bytes(raw: bytes) -> bytes:
    """zstd 压一段字节（走被测代码同款 CLI 依赖）。"""
    p = subprocess.run(["zstd", "-z", "-c"], input=raw,
                       capture_output=True, check=True)
    return p.stdout


def _mk_dsh(tmp_path: Path, name: str, payloads: list) -> Path:
    """造 <tmp>/<name>.dsh/sessions/session.jsonl.zstd；payloads=多个 zstd 帧的
    原始字节列表（依次拼接——多帧拼接是 workbench/node.ts:59 证实的真实形态）。"""
    dsh = tmp_path / (name + ".dsh")
    sess = dsh / "sessions"
    sess.mkdir(parents=True)
    f = sess / "session.jsonl.zstd"
    f.write_bytes(b"".join(payloads))
    return dsh


def _lines_payload(objs, partial_tail: bytes = b"", raw_lines: list = ()) -> bytes:
    out = b""
    for o in objs:
        out += (json.dumps(o) + "\n").encode()
    for ln in raw_lines:
        out += ln
    out += partial_tail
    return out


def _quarantine_dir(dsh: Path) -> Path:
    return dsh.parent / ".sandbar" / "quarantine"


# ---------- 面②：帧好内撕裂（核心回归腿，t260906-05 同型） ----------


def test_torn_jsonl_record_quarantined(tmp_path):
    """两行合法 JSONL + 第三行截半，帧完整 → 逐行试析兜住，同路径隔离。"""
    dsh = _mk_dsh(tmp_path, "a", [_zstd_bytes(_lines_payload(
        [{"t": 1}, {"t": 2}], partial_tail=b'{"t":3,"m":'[:10]))])
    f = dsh / "sessions" / "session.jsonl.zstd"
    _quarantine_torn_sessions(dsh)
    assert not f.exists()                       # 原位已挪走
    q = _quarantine_dir(dsh) / "torn-sessions-session.jsonl.zstd"
    assert q.is_file()                          # 同一条隔离路径留档


def test_non_json_line_in_good_frame_quarantined(tmp_path):
    """好帧内非 JSON 行（乱写文本）→ 撕裂论处隔离。"""
    dsh = _mk_dsh(tmp_path, "b", [_zstd_bytes(
        _lines_payload([{"t": 1}], raw_lines=[b"hello not json\n"]))])
    _quarantine_torn_sessions(dsh)
    assert (_quarantine_dir(dsh) / "torn-sessions-session.jsonl.zstd").is_file()


def test_torn_frame_still_quarantined(tmp_path):
    """旧口径回归：帧裂（zstd -t 红）仍隔离。"""
    payload = _zstd_bytes(_lines_payload([{"t": 1}, {"t": 2}]))
    dsh = _mk_dsh(tmp_path, "c", [payload[:int(len(payload) * 0.6)]])
    f = dsh / "sessions" / "session.jsonl.zstd"
    assert subprocess.run(["zstd", "-t", str(f)], capture_output=True).returncode != 0
    _quarantine_torn_sessions(dsh)
    assert not f.exists()
    assert (_quarantine_dir(dsh) / "torn-sessions-session.jsonl.zstd").is_file()


# ---------- 面②：健康对照组（误隔离=反向事故，必须不红） ----------


def test_healthy_multiframe_concat_not_quarantined(tmp_path):
    """多行合法 JSONL + 多帧 zstd 拼接 → 不隔离（帧在位、内容合法）。"""
    dsh = _mk_dsh(tmp_path, "d", [
        _zstd_bytes(_lines_payload([{"t": 1}, {"t": 2}])),
        _zstd_bytes(_lines_payload([{"t": 3}])),
    ])
    _quarantine_torn_sessions(dsh)
    f = dsh / "sessions" / "session.jsonl.zstd"
    assert f.is_file()                          # 原位不动
    assert not _quarantine_dir(dsh).exists()    # 检疫目录都没建


def test_healthy_blank_lines_and_no_trailing_newline(tmp_path):
    """裸空行跳过不判；无尾换行的完整末行合法 → 不隔离。"""
    raw = b'{"a":1}\n\n{"b":2}\n\n{"c":3}'      # 末行无换行
    dsh = _mk_dsh(tmp_path, "e", [_zstd_bytes(raw)])
    _quarantine_torn_sessions(dsh)
    assert (dsh / "sessions" / "session.jsonl.zstd").is_file()


def test_missing_sessions_dir_noop(tmp_path):
    dsh = tmp_path / "f.dsh"
    dsh.mkdir()
    _quarantine_torn_sessions(dsh)              # 不抛即绿
    assert not _quarantine_dir(dsh).exists()


def test_session_jsonl_torn_direct(tmp_path):
    """_session_jsonl_torn 直测：撕裂 True / 健康 False（含空档=合法文件）。"""
    torn = tmp_path / "torn.zstd"
    torn.write_bytes(_zstd_bytes(_lines_payload([{"t": 1}], partial_tail=b'{"x":')))
    healthy = tmp_path / "ok.zstd"
    healthy.write_bytes(_zstd_bytes(b""))
    assert _session_jsonl_torn(torn) is True
    assert _session_jsonl_torn(healthy) is False


# ---------- 面③：身份守卫 ----------


@pytest.fixture()
def ident_env(tmp_path, monkeypatch):
    """身份探针环境闸：NOSYSTEM=1 + GIT_CONFIG_GLOBAL 指向可控文件（防系统级
    gitconfig 带身份的机器假红，C4 口径）。返回写入 global 文件的函数。"""
    home = tmp_path / "home"
    home.mkdir()
    gfile = home / "gitconfig"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gfile))
    monkeypatch.delenv("GIT_CONFIG_SYSTEM", raising=False)

    def _set(identity: dict) -> Path:
        gfile.write_text("".join(
            "[%s]\n\t%s = %s\n" % (k.split(".")[0], k.split(".")[1], v)
            for k, v in identity.items()))
        return gfile
    return _set


def test_identity_missing_named_red(ident_env, tmp_path):
    ident_env({})                               # 空 global + 无系统级 → 全缺
    err = _check_git_identity(tmp_path)
    assert err is not None
    assert "user.name、user.email" in err       # 点名缺项
    assert "retry_qc" in err                    # 给出重跑处置


def test_identity_partial_named_only_missing(ident_env, tmp_path):
    ident_env({"user.name": "host"})            # 只缺 email
    err = _check_git_identity(tmp_path)
    assert err is not None and "user.email" in err and "user.name、user.email" not in err


def test_identity_present_green(ident_env, tmp_path):
    ident_env({"user.name": "host", "user.email": "host@example.com"})
    assert _check_git_identity(tmp_path) is None


def test_identity_probe_fault_red(ident_env, tmp_path, monkeypatch):
    """git 都起不来（spawn 异常）→ 探针红字，不炸 activity。"""
    ident_env({"user.name": "h", "user.email": "e@x"})

    def _boom(*a, **k):
        raise OSError("no git")
    monkeypatch.setattr(agent_activities.subprocess, "run", _boom)
    err = _check_git_identity(tmp_path)
    assert err is not None and "探针执行失败" in err


def test_lane_dep_symlinks_contains_venv():
    assert "app/node_modules" in LANE_DEP_SYMLINKS
    assert "server/engine/.venv" in LANE_DEP_SYMLINKS


def _fake_main_and_lane(tmp_path, with_venv=True, with_node_modules=True):
    """夹具主仓=tmp_path + 泳道 tmp_path/.lane/t-x（路径约定自锚定：.lane 父级=repo 根）。"""
    main = tmp_path
    lane = tmp_path / ".lane" / "t-x"
    lane.mkdir(parents=True)
    for rel, yes in (("app/node_modules", with_node_modules),
                     ("server/engine/.venv", with_venv)):
        if yes:
            (main / rel).mkdir(parents=True, exist_ok=True)
    # 泳道内父目录（gitignored 目录链在 worktree 里是存在的——.gitignore 不删目录）
    (lane / "app").mkdir()
    (lane / "server" / "engine").mkdir(parents=True)
    return main, lane


def test_ensure_lane_deps_links_venv(tmp_path, monkeypatch):
    """验收④ UT 腿：主仓 .venv 在位 → 泳道自动软链，action 报 +deps。"""
    main, lane = _fake_main_and_lane(tmp_path)
    monkeypatch.setattr(agent_activities, "REPO_ROOT", main)
    suffix = _ensure_lane_deps(lane)
    assert suffix == "+deps:app/node_modules,server/engine/.venv"
    assert (lane / "server/engine/.venv").is_symlink()
    assert (lane / "app/node_modules").is_symlink()


def test_ensure_lane_deps_skips_missing_venv_silently(tmp_path, monkeypatch):
    """主仓无 .venv（全新克隆）→ 跳过不报错，红字留给 verify_lane（既有行为）。"""
    main, lane = _fake_main_and_lane(tmp_path, with_venv=False)
    monkeypatch.setattr(agent_activities, "REPO_ROOT", main)
    suffix = _ensure_lane_deps(lane)
    assert suffix == "+deps:app/node_modules"
    assert not (lane / "server/engine/.venv").is_symlink()


def _run(coro):
    import asyncio
    return asyncio.run(coro)


def test_prepare_workspace_identity_missing_fails_fast(tmp_path, ident_env, monkeypatch):
    """验收③ UT 腿：身份缺失 → worktree 分支开工前 failed 红字点名（不到 worktree add）。"""
    ident_env({})
    main, lane = _fake_main_and_lane(tmp_path)
    monkeypatch.setattr(agent_activities, "REPO_ROOT", main)
    monkeypatch.setattr(agent_activities, "_is_worktree_of", lambda p, repo=None: True)
    res = _run(prepare_workspace(WorkspacePrep(
        ticket_id="t-ut", workspace={"type": "worktree", "path": str(lane)})))
    assert res.ok is False and res.action == "failed"
    assert "git 身份缺失" in (res.error or "")


def test_prepare_workspace_dir_type_skips_identity(tmp_path, ident_env, monkeypatch):
    """dir 型工作区无 commit，不查身份（C4 口径）——身份缺失也照常 ensured。"""
    ident_env({})
    d = tmp_path / "ws-dir"
    res = _run(prepare_workspace(WorkspacePrep(
        ticket_id="t-ut", workspace={"type": "dir", "path": str(d)})))
    assert res.ok is True and res.action == "ensured"


def test_prepare_workspace_identity_ok_reused_with_deps(tmp_path, ident_env, monkeypatch):
    """身份在位 → 闸放行，reused 路径带依赖软链（.venv 在列）。"""
    ident_env({"user.name": "host", "user.email": "host@example.com"})
    main, lane = _fake_main_and_lane(tmp_path)
    monkeypatch.setattr(agent_activities, "REPO_ROOT", main)
    monkeypatch.setattr(agent_activities, "_is_worktree_of", lambda p, repo=None: True)
    res = _run(prepare_workspace(WorkspacePrep(
        ticket_id="t-ut", workspace={"type": "worktree", "path": str(lane)})))
    assert res.ok is True and res.action == "reused+deps:app/node_modules,server/engine/.venv"
