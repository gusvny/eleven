"""t261001-13 单测：install_executor_preset.py（安装面机械化）。

全走 tmp 目录桩（零真实 ~/.dsh、零 3099/7233）；畸形输入用例按纪律必备：
真源 preset.yml 缺席 / 无 name 行 / name 不符 / 装后目录被换坏。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_TOOLS = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location("install_executor_preset", _TOOLS / "install_executor_preset.py")
mod = importlib.util.module_from_spec(_SPEC)
sys.modules.setdefault("install_executor_preset", mod)
_SPEC.loader.exec_module(mod)

GOOD_YML = "name: sandbar-executor\ndescription: x\norder: 20\n"


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    src = tmp_path / "server" / "profile" / "agent-presets" / mod.PRESET_NAME
    src.mkdir(parents=True)
    (src / "preset.yml").write_text(GOOD_YML, encoding="utf-8")
    (src / "agent.cordis.yml").write_text("roster: x\n", encoding="utf-8")
    return tmp_path


def home(tmp_path: Path) -> Path:
    h = tmp_path / "dshhome"
    h.mkdir()
    return h


def test_check_reports_missing(tmp_path, repo):
    code, msg = mod.check(home(tmp_path))
    assert code == mod.EXIT_MISSING and "未安装" in msg


def test_install_then_check_ok(tmp_path, repo):
    h = home(tmp_path)
    code, msg = mod.install(repo, h, force=False)
    assert code == mod.EXIT_OK and "安装完成" in msg
    dst = h / ".agent-presets" / mod.PRESET_NAME / "preset.yml"
    assert dst.is_file() and "name: sandbar-executor" in dst.read_text(encoding="utf-8")
    code, msg = mod.check(h)
    assert code == mod.EXIT_OK and "就绪" in msg


def test_install_idempotent_no_force(tmp_path, repo):
    h = home(tmp_path)
    assert mod.install(repo, h, force=False)[0] == mod.EXIT_OK
    code, msg = mod.install(repo, h, force=False)
    assert code == mod.EXIT_OK and "幂等跳过" in msg
    # 幂等跳过绝不覆盖：目标被改过也能原样保留。
    yml = h / ".agent-presets" / mod.PRESET_NAME / "preset.yml"
    yml.write_text("name: sandbar-executor\n# local edit\n", encoding="utf-8")
    assert mod.install(repo, h, force=False)[0] == mod.EXIT_OK
    assert "# local edit" in yml.read_text(encoding="utf-8")


def test_install_force_overwrites(tmp_path, repo):
    h = home(tmp_path)
    assert mod.install(repo, h, force=False)[0] == mod.EXIT_OK
    code, msg = mod.install(repo, h, force=True)
    assert code == mod.EXIT_OK and "安装完成" in msg


def test_rejects_source_missing_yml(tmp_path, repo):
    (repo / "server/profile/agent-presets" / mod.PRESET_NAME / "preset.yml").unlink()
    code, msg = mod.install(repo, home(tmp_path), force=False)
    assert code == mod.EXIT_FAIL and "preset.yml 缺席" in msg


def test_rejects_source_name_mismatch(tmp_path, repo):
    # 畸形输入：name 行与目录名不符（复制坏 preset = 把静默拒绝换家）。
    (repo / "server/profile/agent-presets" / mod.PRESET_NAME / "preset.yml").write_text(
        "name: other-preset\n", encoding="utf-8")
    code, msg = mod.install(repo, home(tmp_path), force=False)
    assert code == mod.EXIT_FAIL and "≠" in msg


def test_rejects_source_no_name_line(tmp_path, repo):
    (repo / "server/profile/agent-presets" / mod.PRESET_NAME / "preset.yml").write_text(
        "description: no name at all\n", encoding="utf-8")
    code, msg = mod.install(repo, home(tmp_path), force=False)
    assert code == mod.EXIT_FAIL and "无 name 行" in msg


def test_rejects_source_unreadable_yml(tmp_path, repo):
    p = repo / "server/profile/agent-presets" / mod.PRESET_NAME / "preset.yml"
    p.write_bytes(b"\xff\xfe\x00")  # 非法 UTF-8
    code, msg = mod.install(repo, home(tmp_path), force=False)
    assert code == mod.EXIT_FAIL and "不可读" in msg


def test_existing_broken_install_requires_force(tmp_path, repo):
    h = home(tmp_path)
    dst = h / ".agent-presets" / mod.PRESET_NAME
    dst.mkdir(parents=True)
    (dst / "preset.yml").write_text("name: wrong\n", encoding="utf-8")
    code, msg = mod.install(repo, h, force=False)
    assert code == mod.EXIT_FAIL and "校验不通过" in msg
    assert mod.install(repo, h, force=True)[0] == mod.EXIT_OK
    assert "name: sandbar-executor" in (dst / "preset.yml").read_text(encoding="utf-8")


def test_check_flags_broken_install(tmp_path, repo):
    h = home(tmp_path)
    assert mod.install(repo, h, force=False)[0] == mod.EXIT_OK
    (h / ".agent-presets" / mod.PRESET_NAME / "preset.yml").write_text("description: name line gone\n", encoding="utf-8")
    code, msg = mod.check(h)
    assert code == mod.EXIT_FAIL and "校验不通过" in msg


def test_cli_check_missing_exit_code(tmp_path, repo):
    # CLI 面：--check 缺装 → exit 3（可挂首启自检链）。
    rc = mod.main(["--repo", str(repo), "--dsh-home", str(home(tmp_path)), "--check"])
    assert rc == mod.EXIT_MISSING


def test_repo_root_derivation():
    assert mod.repo_root_of(_TOOLS / "install_executor_preset.py") == _TOOLS.parent.parent
