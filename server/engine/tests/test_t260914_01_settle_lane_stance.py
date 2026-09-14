"""t260914-01（结算面三修）单元测试：判脏口径 / 空提交收口 / 多仓清单真源。

被测：agent_activities._settle_worktree_lane（worker 代落盘）、_prepare_multirepo_lane、
_lane_scopes，以及 shared.multi_manifest_path 的解析规则。

覆盖（零 Temporal server / 零模型 / 零网络；git 夹具在 tmp 自足）：
  A. 单源锚：SETTLE_PATHSPEC 字面量与 shared 协调目录真源逐字对齐（首令牌必须是 "."
     ——守卫按「全量令牌」跳过它；`:!` 族必须且仅覆盖 .dsh+两名协调目录）、无重复；
     _SETTLE_RESET_PATHS 派生自 shared；MULTI_MANIFEST_REL 仍＝老名镜像相对路径。
  B. 纯老名泳道（只有老名协调目录）＋只产出协调目录产物的一段 → settle 返回「工作区
     已干净」note、零 commit、不 raise（dengzhufpv/t260911-07 形态的结构回归锚）。
  C. 空提交正反锁：判脏非空但撤下协调目录后暂存区为空 → 可辨 note 且不得出现
     RuntimeError（note 与干净态可区分、含判脏项数、不含 path_gate_reason= 键）；
     反向：add 真失败 / 暂存非空而 commit 真失败 / 暂存区探针自身报错 → 一律响亮。
  D. 清单真源：新建多仓泳道清单落解析位（新名），且不诞出老名目录；老名泳道粘滞
     原地可读、复写不换名。
  E. 既有 fail-closed 面：清单坏 JSON 仍 RuntimeError（不静默回落单仓锚）。

消费外部输入的畸形用例（岗位纪律）：status 输出的畸形条目、diff 探针 rc=2、坏 JSON
清单——全部桩/tmp 夹具内复现，不靠真外部源。
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

POC = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(POC))

import pytest  # noqa: E402
import agent_activities as aa  # noqa: E402
import shared  # noqa: E402

OLD = shared.DOT_DIR_OLD
NEW = shared.DOT_DIR_NEW
CLEAN_NOTE = "工作区已干净，无需代落盘"
TICKET = "t26091401ut"


# ---------- git 夹具（tmp 自足，不碰真仓） ----------

def _git(cwd, *args):
    p = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    assert p.returncode == 0, "git %s 失败: %s" % (" ".join(args), p.stderr)
    return p.stdout.strip()


def _init_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "ut@example.com")
    _git(path, "config", "user.name", "ut")
    (path / "README.md").write_text("base\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "base")
    return path


class _CP:
    """subprocess.CompletedProcess 的最小替身（桩注入用，只带被测代码读的字段）。"""

    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


@pytest.fixture
def single_lane(tmp_path):
    """单仓项目 + 一条注册好的泳道 worktree（未建任何协调目录）。"""
    root = _init_repo(tmp_path / "proj")
    lane = root / ".lane" / "wt"
    _git(root, "worktree", "add", "-q", "-b", "lane/ut-single", str(lane))
    return root, lane


@pytest.fixture
def mixed_lane(tmp_path):
    """多仓项目（根仓 + repo_a）+ 泳道容器（根树）与子仓树均已注册 worktree。"""
    root = _init_repo(tmp_path / "proj")
    a = _init_repo(root / "repo_a")
    lane = root / ".lane" / "wt"
    _git(root, "worktree", "add", "-q", "-b", "lane/ut-root", str(lane))
    _git(a, "worktree", "add", "-q", "-b", "lane/ut-repo_a", str(lane / "repo_a"))
    return root, a, lane


def _head_count(lane: Path) -> int:
    return int(_git(lane, "rev-list", "--count", "HEAD") or "0")


# ---------- A. 单源锚 ----------

def test_settle_pathspec_pinned_to_shared_dot_names():
    """字面量必须与 shared 的协调目录真源逐字对齐（ast 契约不可派生 → 单测钉死）。"""
    assert aa.SETTLE_PATHSPEC == [".", ":!.dsh",
                                  ":!" + shared.DOT_DIR_NEW,
                                  ":!" + shared.DOT_DIR_OLD]
    # 首令牌是「全量」令牌 "."（守卫按此跳过）；写成 ":." 会进排除集合让闸1 转红
    assert aa.SETTLE_PATHSPEC[0] == "."
    assert len(set(aa.SETTLE_PATHSPEC)) == len(aa.SETTLE_PATHSPEC)  # 无重复（260907 曾把新名写两遍）
    excludes = {t for t in aa.SETTLE_PATHSPEC if t.startswith(":!")}
    assert excludes == {":!.dsh", ":!" + shared.DOT_DIR_NEW, ":!" + shared.DOT_DIR_OLD}


def test_settle_reset_paths_derived_from_shared():
    """reset 清单从 shared 派生（settle 与冲突消解共用，不再各抄一份名字）。"""
    assert aa._SETTLE_RESET_PATHS == (".dsh", shared.DOT_DIR_OLD, shared.DOT_DIR_NEW)


def test_multi_manifest_rel_stays_legacy_mirror_path():
    """存量夹具/消费方按该常量直读，值必须保持老名镜像相对路径不变。"""
    assert aa.MULTI_MANIFEST_REL == OLD + "/" + shared.MULTI_MANIFEST_NAME
    assert Path(aa.MULTI_MANIFEST_REL).name == shared.MULTI_MANIFEST_NAME


# ---------- B. 纯老名泳道：协调目录产物段正常收口 ----------

def test_legacy_only_lane_coordination_artifact_settles_clean(single_lane):
    root, lane = single_lane
    art = lane / OLD / "stage_create_plan_gen0.json"
    art.parent.mkdir(parents=True)
    art.write_text('{"status":"ok","summary":"agent 产物完好"}\n', encoding="utf-8")
    before = _head_count(lane)

    note = aa._settle_worktree_lane(lane, TICKET, "create_plan", 0, repo=root)

    assert note == CLEAN_NOTE, note            # 老名目录不再被算脏改（260907 改名漏网面）
    assert _head_count(lane) == before         # 零 commit：没有空提交异常，也没有假落盘
    assert "path_gate_reason=" not in note


def test_new_name_lane_coordination_artifact_settles_clean(single_lane):
    """对照腿：新名泳道（本修前已正确排除）行为不变。"""
    root, lane = single_lane
    art = lane / NEW / "stage_create_plan_gen0.json"
    art.parent.mkdir(parents=True)
    art.write_text("{}\n", encoding="utf-8")
    assert aa._settle_worktree_lane(lane, TICKET, "create_plan", 0, repo=root) == CLEAN_NOTE


def test_real_change_still_lands_a_commit(single_lane):
    """正向对照：真改动照旧代落盘（修复不得把正常落盘也吞掉）。"""
    root, lane = single_lane
    (lane / "code.py").write_text("print(1)\n", encoding="utf-8")
    note = aa._settle_worktree_lane(lane, TICKET, "implement", 0, repo=root)
    assert "worker 代落盘 commit" in note, note
    assert "code.py" in _git(lane, "show", "--name-only", "--format=", "HEAD")


# ---------- C. 空提交正反锁 ----------

def _stub_git(monkeypatch, *, status_out, diff_rc=1, add_rc=0, calls=None):
    """只替换被测的少数 git 调用，其余透传真 git（夹具仍需真 worktree 身份）。"""
    real = aa._git

    def fake(args, cwd, timeout=60):
        if calls is not None:
            calls.append(list(args))
        if args[0] == "status" and "--porcelain" in args:
            return _CP(0, status_out, "")
        if args[0] == "diff" and "--cached" in args:
            return _CP(diff_rc, "", "" if diff_rc in (0, 1) else "fatal: 索引损坏")
        if args[0] == "add" and add_rc != 0:
            return _CP(add_rc, "", "fatal: unable to write new index file")
        return real(args, cwd, timeout)

    monkeypatch.setattr(aa, "_git", fake)


def test_empty_staged_after_add_reset_returns_distinguishable_note(single_lane, monkeypatch):
    """验收 C 正向：判脏非空 + 撤下协调目录后暂存区为空 → 可辨 note，不 raise。"""
    root, lane = single_lane
    calls = []
    _stub_git(monkeypatch, status_out="?? .dsh/agent.log\0?? .sandbar/x.json\0",
              diff_rc=0, calls=calls)

    note = aa._settle_worktree_lane(lane, TICKET, "create_plan", 0, repo=root)

    assert note != CLEAN_NOTE                          # ① 与「判脏为空」两态可区分
    assert "暂存区为空" in note and "2" in note         # ② 要素：判脏项数（2 项）
    assert "path_gate_reason=" not in note             # ③ 不得被判成闸拒绝
    assert not any(c and c[0] == "commit" for c in calls)  # 空提交压根不尝试 commit


def test_add_failure_still_loud(single_lane, monkeypatch):
    """验收 C 反向一：真 add 失败必须响亮（不得吞成 note）。"""
    root, lane = single_lane
    _stub_git(monkeypatch, status_out="?? code.py\0", add_rc=1)
    with pytest.raises(RuntimeError, match="git add 失败"):
        aa._settle_worktree_lane(lane, TICKET, "implement", 0, repo=root)


def test_commit_failure_with_nonempty_staging_still_loud(single_lane, monkeypatch):
    """验收 C 反向二：暂存非空而 commit 因其它原因失败 → 照旧抛（真失败与空提交可辨）。"""
    root, lane = single_lane
    _stub_git(monkeypatch, status_out="?? code.py\0", diff_rc=1)
    hook = root / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    with pytest.raises(RuntimeError, match="git commit 失败"):
        aa._settle_worktree_lane(lane, TICKET, "implement", 0, repo=root)


def test_staged_probe_git_trouble_still_loud(single_lane, monkeypatch):
    """畸形/环境类：暂存区探针 rc∉{0,1} → fail-closed 响亮（不猜、不吞）。"""
    root, lane = single_lane
    _stub_git(monkeypatch, status_out="?? code.py\0", diff_rc=2)
    with pytest.raises(RuntimeError, match="暂存区检查失败"):
        aa._settle_worktree_lane(lane, TICKET, "implement", 0, repo=root)


def test_clean_lane_note_unchanged(single_lane):
    """既有干净态文案不变（两态可区分的前提）。"""
    root, lane = single_lane
    assert aa._settle_worktree_lane(lane, TICKET, "implement", 0, repo=root) == CLEAN_NOTE


# ---------- D. 多仓清单走真源 ----------

def _prep():
    return shared.WorkspacePrep(ticket_id=TICKET)


def test_new_multirepo_lane_manifest_lands_at_new_name(mixed_lane):
    """验收 D：新泳道清单落解析位（新名），不诞出老名目录；读侧同源可读。"""
    root, a, lane = mixed_lane
    entries = [{"repo": "", "name": "root", "branch": "lane/ut-root"},
               {"repo": "repo_a", "name": "repo_a", "branch": "lane/ut-repo_a"}]

    res = aa._prepare_multirepo_lane(lane, entries, _prep())

    assert res.ok, res.error
    mf = lane / NEW / shared.MULTI_MANIFEST_NAME
    assert mf.is_file(), "清单未落解析位：%s" % sorted(p.name for p in lane.iterdir())
    assert not (lane / OLD).exists(), "新泳道不得诞出老名协调目录"
    got = json.loads(mf.read_text("utf-8"))
    assert [(e["repo"], e["name"], e["branch"]) for e in got] == \
        [("", "root", "lane/ut-root"), ("repo_a", "repo_a", "lane/ut-repo_a")]
    scopes = aa._lane_scopes(lane)
    assert [s["repo_rel"] for s in scopes] == ["", "repo_a"]


def test_legacy_lane_manifest_readable_and_rewritten_in_place(tmp_path):
    """兼容：老名粘滞泳道——清单读得到（回落/粘滞规则），复写原地不换名、不诞新名目录。"""
    root = _init_repo(tmp_path / "proj")
    a = _init_repo(root / "repo_a")
    lane = root / ".lane" / "wt"
    lane.mkdir(parents=True)
    mf = lane / OLD / shared.MULTI_MANIFEST_NAME
    mf.parent.mkdir(parents=True)
    mf.write_text(json.dumps([{"repo": "repo_a", "name": "repo_a",
                               "branch": "lane/ut-repo_a", "base_ref": ""}]),
                  encoding="utf-8")

    scopes = aa._lane_scopes(lane)                       # 读：老名位可读
    assert [s["repo_rel"] for s in scopes] == ["repo_a"]
    assert scopes[0]["repo"] == a and scopes[0]["branch"] == "lane/ut-repo_a"

    res = aa._prepare_multirepo_lane(
        lane, [{"repo": "repo_a", "name": "repo_a", "branch": "lane/ut-repo_a"}], _prep())
    assert res.ok, res.error
    assert mf.is_file(), "老泳道清单应原地复写（粘滞），不得迁位"
    assert not (lane / NEW).exists(), "老泳道不得因复写诞出新名目录"


def test_multi_manifest_path_pure_base_returns_resolved_position(tmp_path):
    """shared 单源：两名皆无的 base → 解析位（写侧 create 只建解析位目录）。"""
    base = tmp_path / "base"
    base.mkdir()
    p = shared.multi_manifest_path(base, create=True)
    assert p == base / NEW / shared.MULTI_MANIFEST_NAME
    assert p.parent.is_dir()
    legacy_only = tmp_path / "legacy"
    (legacy_only / OLD).mkdir(parents=True)
    (legacy_only / OLD / shared.MULTI_MANIFEST_NAME).write_text("[]", encoding="utf-8")
    assert shared.multi_manifest_path(legacy_only) == legacy_only / OLD / shared.MULTI_MANIFEST_NAME
    assert shared.multi_manifest_path(legacy_only, legacy_fallback=True) == \
        legacy_only / OLD / shared.MULTI_MANIFEST_NAME
    missing = tmp_path / "missing"
    missing.mkdir()
    assert not shared.multi_manifest_path(missing, legacy_fallback=True).is_file()


# ---------- E. 既有 fail-closed 面（不得放宽） ----------

def test_corrupt_manifest_still_raises(tmp_path):
    root = _init_repo(tmp_path / "proj")
    lane = root / ".lane" / "wt"
    lane.mkdir(parents=True)
    mf = lane / OLD / shared.MULTI_MANIFEST_NAME
    mf.parent.mkdir(parents=True)
    mf.write_text("{ not json", encoding="utf-8")
    with pytest.raises(RuntimeError, match="清单损坏"):
        aa._lane_scopes(lane)


def test_malformed_status_entry_dropped_without_raising(single_lane, monkeypatch):
    """畸形 status 流（缺 XY 前缀的条目）＝既有解析器丢弃、绝不猜（KI-009 口径不变）。"""
    root, lane = single_lane
    _stub_git(monkeypatch, status_out="garbage-entry\0?? .dsh/a.log\0", diff_rc=0)
    note = aa._settle_worktree_lane(lane, TICKET, "create_plan", 0, repo=root)
    assert "暂存区为空" in note and "1" in note
