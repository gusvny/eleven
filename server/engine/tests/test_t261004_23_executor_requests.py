# -*- coding: utf-8 -*-
"""t261004-23 —— 引擎侧执行器请求投递口（executor_requests.py）单测。

覆盖：身份三关（真源=executor_grants/caller_gate，全注入零真环境）、§8 写侧契约
的每个具名拒收、行形与 TS RequestRow 镜像、来源标记、raised_by 真实性、账本根
词表与 TS 源的漂移锁（review 意见 #2：读 TS 源做正则断言，不是第二份常量抄本）、
CLI 畸形输入（非 JSON/非对象）。
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import executor_requests as er  # noqa: E402
import shared  # noqa: E402

REPO = Path(__file__).resolve().parents[3]

VALID_BODY = {
    "kind": "decision",
    "question": "Which option should the executor take for ticket T-1?",
    "detail": "evidence: both paths pass CI",
    "options": ["Adopt plan A (rec.)", "Adopt plan B"],
    "expires_at": None,
}


def _env(tmp: Path, **kw) -> dict:
    env = {
        "SANDBAR_PANEL_DIR": str(tmp),
        "DSH_SESSION_ID": "sess-exec-1",
        "DSH_HEADLESS_SESSION": "",
        shared.CALLER_PROJECT_ENV: "proj-alpha",
        shared.CALLER_IDENTITY_SRC_ENV: "env",
        shared.CALLER_SURFACE_ENV: "",
    }
    env.update(kw)
    return env


def _decl_loader(sessions):
    def load(key):
        return {"ok": True, "executor_sessions": list(sessions)}
    return load


def _file(tmp, key="proj-alpha"):
    return tmp / key / "requests.jsonl"


# ---------- 落账：行形 / 来源标记 / raised_by ----------

def test_file_appends_engine_row(tmp_path):
    env = _env(tmp_path)
    out = er.append_request(dict(VALID_BODY), 1000, env=env, load_decl=_decl_loader(["sess-exec-1"]))
    assert out["ok"] is True
    row = out["row"]
    # 行形=TS RequestRow 镜像 + surface 标记；raised_by=解析出的执行器会话。
    assert row["type"] == "request" and row["project"] == "proj-alpha"
    assert row["id"] == "req-1000-0001"
    assert row["raised_by"] == "sess-exec-1"
    assert row["surface"] == er.SURFACE_ENGINE
    assert row["options"] == VALID_BODY["options"]
    assert row["expires_at"] is None
    assert row["default_action"] == ""
    # 一行一条、O_APPEND JSONL。
    lines = _file(tmp_path).read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0]) == row


def test_row_without_options_has_no_options_key(tmp_path):
    body = {"kind": "question", "question": "May I open a follow-up ticket?", "default_action": "no action"}
    out = er.append_request(body, 2000, seq=7, env=_env(tmp_path), load_decl=_decl_loader(["sess-exec-1"]))
    assert out["ok"] is True
    row = out["row"]
    assert "options" not in row and row["default_action"] == "no action"
    assert row["id"] == "req-2000-0007"


def test_raised_by_mismatch_refused(tmp_path):
    body = dict(VALID_BODY, raised_by="someone-else")
    out = er.append_request(body, 1000, env=_env(tmp_path), load_decl=_decl_loader(["sess-exec-1"]))
    assert out["ok"] is False and out["field"] == "raised_by"
    assert not _file(tmp_path).exists()


def test_raised_by_matching_session_accepted(tmp_path):
    body = dict(VALID_BODY, raised_by="sess-exec-1")
    out = er.append_request(body, 1000, env=_env(tmp_path), load_decl=_decl_loader(["sess-exec-1"]))
    assert out["ok"] is True and out["row"]["raised_by"] == "sess-exec-1"


def test_ledger_written_under_panel_dir_word_list(tmp_path):
    er.append_request(dict(VALID_BODY), 1000, env=_env(tmp_path), load_decl=_decl_loader(["sess-exec-1"]))
    assert _file(tmp_path).is_file()
    # SANDBAR_PANEL_DIR 优先于实例根：非缺省实例（DSH_HOME 指向他处）也不落在其下。
    env2 = _env(tmp_path, DSH_HOME=str(tmp_path / "dsh-home"))
    env2.pop("SANDBAR_PANEL_DIR")
    er.append_request(dict(VALID_BODY), 1001, env=env2, load_decl=_decl_loader(["sess-exec-1"]))
    assert (tmp_path / "dsh-home" / "sandbar" / "projects" / "proj-alpha" / "requests.jsonl").is_file()


# ---------- 身份三关（无匿名投递） ----------

def test_caller_undeclared_refused(tmp_path):
    env = _env(tmp_path)
    env.pop(shared.CALLER_PROJECT_ENV)
    env[shared.CALLER_IDENTITY_SRC_ENV] = ""
    out = er.append_request(dict(VALID_BODY), 1000, env=env, load_decl=_decl_loader(["sess-exec-1"]))
    assert out["ok"] is False and out["field"] == "caller"
    assert out["reason"].startswith("caller-undeclared")


def test_session_absent_refused(tmp_path):
    env = _env(tmp_path, DSH_SESSION_ID="")
    out = er.append_request(dict(VALID_BODY), 1000, env=env, load_decl=_decl_loader(["sess-exec-1"]))
    assert out["ok"] is False and out["field"] == "caller"
    assert out["reason"].startswith("session-absent")


def test_lane_agent_exempt_channel_refused(tmp_path):
    env = _env(tmp_path, **{shared.CALLER_SURFACE_ENV: shared.CALLER_SURFACE_LANE_AGENT})
    out = er.append_request(dict(VALID_BODY), 1000, env=env, load_decl=_decl_loader([]))
    assert out["ok"] is False and out["field"] == "caller"
    assert out["reason"].startswith("lane-agent-exempt")


def test_session_not_named_refused(tmp_path):
    env = _env(tmp_path, DSH_SESSION_ID="sess-stranger")
    out = er.append_request(dict(VALID_BODY), 1000, env=env, load_decl=_decl_loader(["sess-exec-1"]))
    assert out["ok"] is False and out["field"] == "caller"
    assert out["reason"].startswith("session-not-named")


def test_cwd_channel_executor_accepted(tmp_path):
    # cwd 推导通道（watchdog 代建会话）：注册表条目指向的目录即执行器通道。
    env = _env(tmp_path)
    env.pop(shared.CALLER_PROJECT_ENV)
    env[shared.CALLER_IDENTITY_SRC_ENV] = ""
    proj_dir = tmp_path / "workdir"
    proj_dir.mkdir()
    projects = [{"key": "proj-alpha", "dirs": [str(proj_dir)]}]
    out = er.append_request(dict(VALID_BODY), 1000, env=env, cwd=str(proj_dir),
                            projects=projects, exclude_trees=(),
                            load_decl=_decl_loader([]))
    assert out["ok"] is True
    assert out["row"]["project"] == "proj-alpha" and out["row"]["raised_by"] == "sess-exec-1"


def test_cwd_inside_engine_tree_not_derived(tmp_path):
    # 引擎仓树排除：仓内 cwd（dsh 工具链 spawn）绝不凭空造身份（review C1）。
    env = _env(tmp_path)
    env.pop(shared.CALLER_PROJECT_ENV)
    env[shared.CALLER_IDENTITY_SRC_ENV] = ""
    engine_dir = Path(__file__).resolve().parents[1]
    projects = [{"key": "proj-alpha", "dirs": [str(engine_dir)]}]
    out = er.append_request(dict(VALID_BODY), 1000, env=env, cwd=str(engine_dir),
                            projects=projects, exclude_trees=(str(engine_dir),),
                            load_decl=_decl_loader(["sess-exec-1"]))
    assert out["ok"] is False and out["field"] == "caller"
    assert out["reason"].startswith("caller-undeclared")


# ---------- §8 写侧契约：每个拒收都点名失败字段 ----------

def test_empty_question_refused(tmp_path):
    out = er.append_request(dict(VALID_BODY, question="   "), 1000,
                            env=_env(tmp_path), load_decl=_decl_loader(["sess-exec-1"]))
    assert out["ok"] is False and out["field"] == "question"


def test_long_question_refused(tmp_path):
    body = dict(VALID_BODY, question="x" * 61)
    out = er.append_request(body, 1000, env=_env(tmp_path), load_decl=_decl_loader(["sess-exec-1"]))
    assert out["ok"] is False and out["field"] == "question"
    assert "61" in out["error"] and "60" in out["error"]


def test_empty_kind_refused(tmp_path):
    out = er.append_request(dict(VALID_BODY, kind=""), 1000,
                            env=_env(tmp_path), load_decl=_decl_loader(["sess-exec-1"]))
    assert out["ok"] is False and out["field"] == "kind"


def test_options_not_array_refused(tmp_path):
    out = er.append_request(dict(VALID_BODY, options="yes"), 1000,
                            env=_env(tmp_path), load_decl=_decl_loader(["sess-exec-1"]))
    assert out["ok"] is False and out["field"] == "options"


def test_options_one_label_refused(tmp_path):
    out = er.append_request(dict(VALID_BODY, options=["only"]), 1000,
                            env=_env(tmp_path), load_decl=_decl_loader(["sess-exec-1"]))
    assert out["ok"] is False and out["field"] == "options"
    assert "2" in out["error"]


def test_options_five_labels_refused(tmp_path):
    # 刻意收窄（review 意见 #1）：面板地板 ≤8，本口按 §8 收到 2–4；文案带实际计数。
    labels = ["a", "b", "c", "d", "e"]
    out = er.append_request(dict(VALID_BODY, options=labels), 1000,
                            env=_env(tmp_path), load_decl=_decl_loader(["sess-exec-1"]))
    assert out["ok"] is False and out["field"] == "options"
    assert "5" in out["error"]


def test_option_label_too_long_refused(tmp_path):
    out = er.append_request(dict(VALID_BODY, options=["ok", "x" * 21]), 1000,
                            env=_env(tmp_path), load_decl=_decl_loader(["sess-exec-1"]))
    assert out["ok"] is False and out["field"] == "options"
    assert "21" in out["error"]


def test_option_blank_label_refused(tmp_path):
    out = er.append_request(dict(VALID_BODY, options=["ok", "  "]), 1000,
                            env=_env(tmp_path), load_decl=_decl_loader(["sess-exec-1"]))
    assert out["ok"] is False and out["field"] == "options"


def test_missing_default_action_without_options_refused(tmp_path):
    body = {"kind": "question", "question": "May I proceed without a grant?"}
    out = er.append_request(body, 1000, env=_env(tmp_path), load_decl=_decl_loader(["sess-exec-1"]))
    assert out["ok"] is False and out["field"] == "default_action"


def test_bad_shape_body_refused_per_field(tmp_path):
    env = _env(tmp_path)
    ld = _decl_loader(["sess-exec-1"])
    for field, patch in [("detail", 42), ("default_action", []), ("expires_at", True),
                         ("expires_at", "soon"), ("expires_at", -1)]:
        out = er.append_request(dict(VALID_BODY, **{field: patch}), 1000, env=env, load_decl=ld)
        assert out["ok"] is False and out["field"] == field, (field, patch, out)


def test_malformed_caller_identity_refused_as_caller(tmp_path):
    # caller_gate 对形状非法的显式/env 身份 fail-closed raise——落 field=caller。
    env = _env(tmp_path, **{shared.CALLER_PROJECT_ENV: "../evil"})
    out = er.append_request(dict(VALID_BODY), 1000, env=env, load_decl=_decl_loader(["sess-exec-1"]))
    assert out["ok"] is False and out["field"] == "caller"
    assert out["reason"].startswith("caller-identity-malformed")


# ---------- 账本根词表漂移锁（读 TS 源断言，非第二份常量抄本） ----------

def test_ledger_root_word_list_matches_ts_sources():
    requests_ts = (REPO / "server/plugins/executor-panel/src/host/requests.ts").read_text()
    config_ts = (REPO / "server/plugins/watchdog/src/host/config.ts").read_text()
    # TS 侧根序：SANDBAR_PANEL_DIR || instanceProjectsRoot(env)。
    assert re.search(r"env\.SANDBAR_PANEL_DIR\s*\|\|\s*instanceProjectsRoot\(env\)", requests_ts), \
        "TS requestsLedgerFile root order changed — re-mirror it in executor_requests.ledger_root"
    # 实例根：缺省实例 HOME/.sandbar，非缺省 <DSH_HOME>/sandbar。
    assert "join(dshHome(env), 'sandbar')" in config_ts and "join(env.HOME || '', '.sandbar')" in config_ts, \
        "TS instanceSandbarRoot fallback changed — re-mirror it in executor_requests.instance_projects_root"
    # python 镜像消费同一词表（键名在源里逐字出现）。
    src = Path(er.__file__).read_text()
    for name in ("SANDBAR_PANEL_DIR", "DSH_HOME", "HOME", ".sandbar", "sandbar", "projects"):
        assert name in src, "python mirror lost the %r token of the ledger root word list" % name
    # 行为级双例：缺省实例与非缺省实例各走对根。
    assert er.instance_projects_root({"HOME": "/h", "DSH_HOME": "/h/.dsh"}) == "/h/.sandbar/projects"
    assert er.instance_projects_root({"HOME": "/h", "DSH_HOME": "/tmp/dsh-x"}) == "/tmp/dsh-x/sandbar/projects"


# ---------- CLI 畸形输入（外部输入纪律：固定桩复现，不靠真外部源） ----------

def _run_cli(arg, tmp_path):
    # CLI 走真声明装载（grants_root=SANDBAR_PROJECTS_DIR），测试把声明也钉进 tmp。
    (tmp_path / "proj-alpha").mkdir(exist_ok=True)
    (tmp_path / "proj-alpha" / "executor-grants.json").write_text(json.dumps(
        {"version": 1, "grants": {}, "executor_sessions": ["sess-exec-1"]}))
    env = dict(os.environ)
    env.update(_env(tmp_path))
    env["SANDBAR_PROJECTS_DIR"] = str(tmp_path)
    return subprocess.run(
        [sys.executable, str(REPO / "server/engine/executor_requests.py"), arg],
        capture_output=True, text=True, env=env, cwd=str(REPO), timeout=60)


# ---------- 坏字符纪律（KI-185/186，t261002-14 emit-surrogate-guard 打回项） ----------

def test_hostile_lone_surrogates_sanitized_not_crashing(tmp_path):
    # 入界消毒：lone surrogate 变可见转义——落账不崩、账本行恒为合法 utf-8。
    body = {"kind": "decision", "question": "bad\udcbc\udc89 plan?", "default_action": "hold",
            "detail": "evi\udcbc dence", "options": ["a\udcbc", "b"]}
    out = er.append_request(body, 1000, env=_env(tmp_path), load_decl=_decl_loader(["sess-exec-1"]))
    assert out["ok"] is True
    row = out["row"]
    assert "\\udcbc" in row["question"] and "\\udcbc" in row["detail"]
    raw = _file(tmp_path).read_text()  # 读不了就是账本行被写坏（fail loud）
    assert "\\udcbc" in raw


def test_emit_fallback_keeps_receipt_parseable(tmp_path):
    # 出口兜底：含坏字符的回执仍是一行合法 JSON，坏字符以可见转义在场。
    import io as _io
    from contextlib import redirect_stdout
    buf = _io.StringIO()
    with redirect_stdout(buf):
        er._emit({"ok": False, "field": "question", "error": "bad\udcbc\udc89"})
    out_text = buf.getvalue()
    out = json.loads(out_text)  # 回执仍是合法 JSON
    assert out["field"] == "question"
    # 坏字符以可见转义在场（断言原始出界文本；json.loads 会把 \udcbc 还原成码点）。
    assert "\\udcbc" in out_text


def test_cli_hostile_argv_receipt_intact(tmp_path):
    # CLI 端到端：argv 带 lone surrogate，进程受控退出、回执完整、stderr 无 Traceback。
    (tmp_path / "proj-alpha").mkdir(exist_ok=True)
    (tmp_path / "proj-alpha" / "executor-grants.json").write_text(json.dumps(
        {"version": 1, "grants": {}, "executor_sessions": ["sess-exec-1"]}))
    env = dict(os.environ)
    env.update(_env(tmp_path))
    env["SANDBAR_PROJECTS_DIR"] = str(tmp_path)
    raw = json.dumps({"kind": "d", "question": "bad\udcbc\udc89?", "default_action": "hold",
                      "caller_project": "proj-alpha"})
    p = subprocess.run([sys.executable, str(REPO / "server/engine/executor_requests.py"), raw],
                       capture_output=True, text=True, errors="backslashreplace",
                       env=env, cwd=str(REPO), timeout=60)
    assert p.returncode == 0 and "Traceback" not in p.stderr
    out = json.loads(p.stdout)
    assert out["ok"] is True
    assert "\\udcbc" in p.stdout  # 可见转义在原始出界文本上断言（round-trip 会还原码点）


def test_cli_non_json_argv_refused_as_body(tmp_path):
    p = _run_cli("not json at all", tmp_path)
    assert p.returncode == 2
    out = json.loads(p.stdout)
    assert out["field"] == "body" and "not valid JSON" in out["error"]


def test_cli_non_object_argv_refused_as_body(tmp_path):
    p = _run_cli("[1,2,3]", tmp_path)
    assert p.returncode == 2
    out = json.loads(p.stdout)
    assert out["field"] == "body" and "JSON object" in out["error"]


def test_cli_help_refused_as_body(tmp_path):
    p = _run_cli("--help", tmp_path)
    assert p.returncode == 2 and json.loads(p.stdout)["field"] == "body"


def test_cli_valid_filing_writes_ledger(tmp_path):
    body = dict(VALID_BODY, op="file", caller_project="proj-alpha")
    p = _run_cli(json.dumps(body), tmp_path)
    assert p.returncode == 0, p.stdout + p.stderr
    out = json.loads(p.stdout)
    assert out["ok"] is True and out["row"]["surface"] == "engine"
    row = json.loads(_file(tmp_path).read_text().splitlines()[0])
    assert row["raised_by"] == "sess-exec-1"


def test_cli_refusal_exit_two_and_no_write(tmp_path):
    body = dict(VALID_BODY, caller_project="proj-alpha", question="")
    p = _run_cli(json.dumps(body), tmp_path)
    assert p.returncode == 2
    out = json.loads(p.stdout)
    assert out["field"] == "question"
    assert not _file(tmp_path).exists()
