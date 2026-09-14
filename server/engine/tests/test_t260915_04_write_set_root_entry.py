"""t260915-04：建票期拒收「整仓根形态」写集条目（多仓重基空串陷阱 + 口径统一）。

覆盖面（对应已过审方案「测试清单」+ review 意见1/2/3）：
  - 层2 锚定层 shared.resolve_repos_for_paths：条目归一后 == 项目根（"."，单仓=整仓、
    混合形态=根仓）或 == 任一成员仓根相对路径（'fpv-toolchain' / 'fpv-toolchain/' /
    'fpv-toolchain//' / 'fpv-toolchain/.' 归一后同形）→ ValueError，文案含整仓根因 +
    逐子目录列举改法 + 仓顶层真实条目例句；
  - 零回归对照：仓内子目录/文件条目（含目录形 'server/'）受理且归属与既有语义一致；
    空仓集/逃逸/嵌套仓既有拒收不变（test_multirepo_anchor 另有钉死）；
  - 建票链可达性：单仓经 multirepo_fuse_a_error（client ticket-start 真实消费点，
    repo_worktrees 恒空必达 resolve）→ '.' 拒收；多仓经
    derive_lane_workspace→build_repo_worktrees→resolve → 成员仓根形态拒收；
  - 层1 形态层联动：validate_background_refs 形态拒、refresh_write_set 进 dropped；
  - 在途票纵深：保险丝B 对含根形态条目的写集 → 转红灯文案不 raise（merge 期
    fail-closed 可见，非静默）；
  - 畸形输入（工单点名形态，含 review 意见1 空串）：''、'  '、' . '、None、123、
    绝对路径、'..'、反斜杠、C:/ —— 建票口/归属口 fail-closed，既有拒收先于新判定。
夹具零 git 子进程：repos_under 与嵌套仓探测只 probe .git 存在性，.git 用目录桩即足
（test_multirepo_anchor 用真 git init 是同文件其它用例需要 git；本文件判定全纯函数）。
"""
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC))

import agent_activities as aa  # noqa: E402
import path_gates  # noqa: E402
import shared  # noqa: E402

MEMBERS = ("fpv-toolchain", "fpv-app", "fpv-web", "fpv-docs", "fpv-sim", "fpv-ops")


def _touch(p: Path, text="x\n"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@pytest.fixture
def mixed7(tmp_path):
    """根仓+6 成员仓（dengzhufpv 260914 实测布局同形：repos_under 探到 7 仓，
    混合形态=根有 .git 且旁边有成员仓）。"""
    root = tmp_path / "proj"
    root.mkdir()
    (root / ".git").mkdir()
    _touch(root / "integration" / "sc_x.py")
    _touch(root / "docs" / "kb.md")
    for name in MEMBERS:
        (root / name / ".git").mkdir(parents=True)
    _touch(root / "fpv-toolchain" / "app" / "main.py")
    _touch(root / "fpv-toolchain" / "crates" / "core" / "lib.rs")
    _touch(root / "fpv-toolchain" / "Cargo.toml")
    return root


@pytest.fixture
def single(tmp_path):
    """单仓项目（根=.git，无成员仓）。"""
    root = tmp_path / "solo"
    root.mkdir()
    (root / ".git").mkdir()
    _touch(root / "server" / "engine" / "x.py")
    _touch(root / "README.md")
    return root


# ---------- 层2：成员仓根形态（两种写法 + 归一同形） ----------

def test_member_repo_root_rejected_all_forms(mixed7):
    root = mixed7
    for entry in ("fpv-toolchain", "fpv-toolchain/", "fpv-toolchain//", "fpv-toolchain/."):
        with pytest.raises(ValueError) as ei:
            shared.resolve_repos_for_paths(root, [entry])
        msg = str(ei.value)
        assert "整仓" in msg, (entry, msg)
        assert "逐个子目录" in msg and ".gitignore" in msg, (entry, msg)
        assert "fpv-toolchain" in msg, (entry, msg)
    # 列举式改法带例句=仓顶层真实条目（目录带尾斜杠），可直接粘进写集
    with pytest.raises(ValueError) as ei:
        shared.resolve_repos_for_paths(root, ["fpv-toolchain"])
    assert "例：fpv-toolchain/Cargo.toml" in str(ei.value)


# ---------- 层2：项目根形态（单仓与混合形态同拒，与闸同口径） ----------

def test_project_root_dot_rejected_mixed_and_single(mixed7, single):
    for root in (mixed7, single):
        for entry in (".", "./", ".//", " . "):
            with pytest.raises(ValueError) as ei:
                shared.resolve_repos_for_paths(root, [entry])
            msg = str(ei.value)
            # 断言命中的是新判定（'项目根'），不是既有的空白拒收（'非字符串或空白'）
            # ——锁定「先归一后判定」的次序。
            assert "项目根" in msg and "逐个子目录" in msg, (entry, msg)


# ---------- 零回归对照：仓内子目录/文件条目照常受理、归属不变 ----------

def test_member_subpaths_attribution_unchanged(mixed7):
    root = mixed7
    m = shared.resolve_repos_for_paths(
        root, ["integration/", "docs/kb.md",
               "fpv-toolchain/app/", "fpv-toolchain/crates/x.py"])
    assert m[str(root.resolve())] == ["integration/", "docs/kb.md"]
    assert m[str((root / "fpv-toolchain").resolve())] == \
        ["fpv-toolchain/app/", "fpv-toolchain/crates/x.py"]


def test_single_repo_dir_form_passthrough_unchanged(single):
    root = single
    m = shared.resolve_repos_for_paths(root, ["server/", "server/engine/x.py", "README.md"])
    assert list(m.keys()) == [str(root.resolve())]  # 全归根仓（单仓透传语义不变）
    assert m[str(root.resolve())] == ["server/", "server/engine/x.py", "README.md"]
    # 同一写集过保险丝A 恒放行（单仓零回归面）
    assert shared.multirepo_fuse_a_error(str(root), ["server/", "README.md"], []) == ""


def test_regression_unchanged_refusals(tmp_path):
    """既有拒收三态文案不变：空仓集/逃逸/嵌套仓（验收 4：resolve 既有行为不变）。"""
    bare = tmp_path / "bare"
    bare.mkdir()
    with pytest.raises(ValueError, match="未发现任何 git 仓"):
        shared.resolve_repos_for_paths(bare, ["x.py"])
    root = tmp_path / "r"
    root.mkdir()
    (root / ".git").mkdir()
    with pytest.raises(ValueError, match="不得逃逸项目根"):
        shared.resolve_repos_for_paths(root, ["../escape.md"])
    (root / "outer" / "nested" / ".git").mkdir(parents=True)
    with pytest.raises(ValueError, match="集合外嵌套仓"):
        shared.resolve_repos_for_paths(root, ["outer/nested/in.txt"])


# ---------- 建票链可达性：拒收在真实消费点生效，不是孤岛函数 ----------

def test_fuse_a_carries_dot_refusal_on_single_repo(single):
    """单仓建票（client ticket-start）repo_worktrees 恒空 → 保险丝A 必调 resolve →
    '.' 拒收经既有 fail-closed 转发上抛（验收 2：单仓与闸同口径）。"""
    with pytest.raises(ValueError, match="整仓"):
        shared.multirepo_fuse_a_error(str(single), ["."], [])
    with pytest.raises(ValueError, match="整仓"):
        shared.multirepo_fuse_a_error(str(single), ["./"], [])


def test_fuse_a_carries_member_root_refusal_on_multirepo(mixed7):
    """多仓明细缺失形态（repo_worktrees=[]）→ 保险丝A 走 resolve → 根形态条目上抛。"""
    with pytest.raises(ValueError, match="整仓"):
        shared.multirepo_fuse_a_error(str(mixed7), ["fpv-toolchain/"], [])


def test_derive_lane_workspace_rejects_member_root_entry(mixed7):
    """多仓正规链（derive→build_repo_worktrees→resolve）建票第一跳即拒。"""
    with pytest.raises(ValueError, match="整仓"):
        shared.derive_lane_workspace(
            "t-ut", shared.LANE_WORKTREE, project_root=str(mixed7),
            repo_write_set=["fpv-toolchain/", "fpv-toolchain/app/"])


# ---------- review 意见2：成员仓名恰为 integration 的交互点 ----------

def test_member_repo_named_integration(tmp_path):
    """成员仓叫 'integration' 时，tools/ticket.py 建票链的 'integration/' 自动并入
    探归属（ticket.py:399）会撞上整仓拒收 → 既有 except ValueError: pass 跳过并入、
    票照开（该行既有语义「自动化便利项缺席≠静默降级」）。锁定并入探归属在此形态下
    确实拒绝，防后续误写「并入恒成功」断言。"""
    root = tmp_path / "proj"
    root.mkdir()
    (root / ".git").mkdir()
    (root / "integration" / ".git").mkdir(parents=True)
    with pytest.raises(ValueError) as ei:
        shared.resolve_repos_for_paths(root, ["integration/"])
    assert "整仓" in str(ei.value)


# ---------- 层1 联动：背景文件闸形态拒 / refresh_write_set 进 dropped ----------

def test_background_refs_shape_rejects_dot_and_glob(tmp_path):
    ok, err = shared.validate_background_refs(["."], tmp_path)
    assert ok is False and "非法条目" in err
    ok, err = shared.validate_background_refs(["src/*"], tmp_path)
    assert ok is False and "非法条目" in err


def test_refresh_write_set_drops_dot_and_glob():
    merged, added, dropped = shared.refresh_write_set(
        ["server/a.py"], [".", "*", "server/b.py"])
    assert merged == ["server/a.py", "server/b.py"]
    assert added == ["server/b.py"]
    assert dropped == [".", "*"]


# ---------- 在途票纵深：保险丝B 转红灯文案不 raise ----------

def test_fuse_b_root_entry_turns_red_not_raise(mixed7):
    lane_root = mixed7 / ".lane" / "t-ut"  # 保险丝B 约定 project_root=lane_root.parent.parent
    red = aa.multirepo_materialization_error(
        lane_root, ["fpv-toolchain/"], [], is_worktree_of=lambda tree, repo: True)
    assert "fail-closed" in red and "整仓" in red


# ---------- 工单点名的畸形输入面（含 review 意见1 空串） ----------

def test_empty_string_entry_rejected_everywhere(mixed7):
    root = mixed7
    # 建票口（层1）
    ok, flags, err = shared.validate_write_set_args([""], False)
    assert ok is False and flags == {} and err
    # 归属口（层2）——既有「非字符串或空白」拒收，不因本票改动漂移
    with pytest.raises(ValueError, match="非字符串或空白"):
        shared.resolve_repos_for_paths(root, [""])
    # 运行期闸同立场（fail-closed 兜底，锁定防漂移）
    okws, pats = path_gates._entries([""])
    assert okws is False and pats == []


def test_malformed_entries_refused_before_new_check(mixed7):
    """畸形面既有拒收先于新判定：resolve 拒「非串/空白/绝对/'..'」四态；反斜杠/盘符
    属层1 形态层管辖（resolve 既有语义=混合形态回落归根仓，非本票收口面，锁定防漂移；
    建票口 validate_write_set_args 照旧全拒）。"""
    root = mixed7
    for bad in (["  "], [None], [123], ["/abs/x"], ["a/../b"]):
        with pytest.raises(ValueError):
            shared.resolve_repos_for_paths(root, bad)
        assert shared.validate_write_set_args(bad, False)[0] is False, bad
    for shape_only in (["a\\b"], ["C:/x"]):
        assert shared.validate_write_set_args(shape_only, False)[0] is False, shape_only
    assert shared.resolve_repos_for_paths(root, ["a\\b"])[str(root.resolve())] == ["a\\b"]
