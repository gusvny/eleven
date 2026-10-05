"""260929 单测（宿主令直修）：冲突消解交付失败 ⇒ **先把 merge 复位再转人工**。

实案（t260929-22，260929 深夜）：主同步把 main 并进泳道时，`integration/t260904-17/
sc_ticket_list_rowcard_ui.mjs` 两边都改（同一条宿主裁决、两套 T1 写法）⇒ 冲突消解 agent
把内容解好了，但它的**交付被判失败**（其中一条命令撞「developer 段禁跑集成」红线）⇒ 引擎
既没提交也没 `merge --abort`，把 `UU` 留在泳道里 ⇒ 之后**每一轮**主同步都在同一批文件上
重新冲突 ⇒ `main_sync_conflict_route` 的「同批文件反复冲突」守卫把票永久封死（连撞 3 轮），
最后只能由人进泳道 `git add`+`commit` 手动收尾。

修法（本单测锁三层）：
  ①活动层：`settle_conflict_resolution(abort=True)` 冪等复位——无合并在进行＝已复位＝ok（不
    谎报做过什么）；有合并则 `git merge --abort`（失败回落 `git reset --merge HEAD`，**不用
    --hard**：工作树改动宁可留着给人看）；复位后 MERGE_HEAD 仍在场＝如实报失败（需人工）。
  ②接线层：两条失败路径（agent 抛异常 / 交付非 ok）在 `blocked` **之前**门内调用复位，并
    复位同批计数器 ⇒ 下一轮从干净树重试（cap 仍封顶，不会变活锁）。
  ③零回归：老在途票 history 无门标记 → `patched()=False` → 旧路径（直接 blocked）逐字不变。

运行：server/engine/.venv/bin/python -B -m pytest \
      server/engine/tests/test_260929_main_sync_abort_recovery.py -q
"""
import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

POC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(POC))

import agent_activities as aa  # noqa: E402
import dev_lane  # noqa: E402
import shared  # noqa: E402


def _git(repo: Path, *args: str):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def _ok_git(repo: Path, *args: str) -> str:
    p = _git(repo, *args)
    assert p.returncode == 0, "git %s 失败：%s" % (" ".join(args), (p.stderr or "").strip()[-200:])
    return (p.stdout or "").strip()


@pytest.fixture()
def mid_merge(tmp_path: Path) -> Path:
    """真仓造「合并进行中 + 一个 UU 文件」现场（与实案同形）。"""
    r = tmp_path / "repo"
    r.mkdir()
    _ok_git(r, "init")
    _ok_git(r, "config", "user.email", "t@example.com")
    _ok_git(r, "config", "user.name", "t")
    f = r / "conflict.txt"
    f.write_text("base\n", encoding="utf-8")
    _ok_git(r, "add", "-A")
    _ok_git(r, "commit", "-m", "base")
    default = _ok_git(r, "rev-parse", "--abbrev-ref", "HEAD")   # 缺省分支名随 git 版本（main/master）
    _ok_git(r, "checkout", "-b", "lane")
    f.write_text("lane side\n", encoding="utf-8")
    _ok_git(r, "commit", "-am", "lane change")
    _ok_git(r, "checkout", default)
    f.write_text("main side\n", encoding="utf-8")
    _ok_git(r, "commit", "-am", "main change")
    _ok_git(r, "checkout", "lane")
    p = _git(r, "merge", default)           # 预期冲突
    assert p.returncode != 0, "夹具没造出冲突"
    assert (r / ".git" / "MERGE_HEAD").exists() or True
    return r


def _abort(repo: Path):
    return asyncio.run(aa.settle_conflict_resolution(
        shared.ConflictSettleArgs(ticket_id="t1", worktree=str(repo), base_ref="main",
                                  round_no=1, abort=True)))


# ---------------- ①活动层 ----------------

def test_abort_clears_the_mid_merge_state(mid_merge):
    r = mid_merge
    p = _git(r, "rev-parse", "--verify", "MERGE_HEAD")
    assert p.returncode == 0, "前置：应处于合并进行中"
    res = _abort(r)
    assert res.ok is True and res.error == ""
    assert _git(r, "rev-parse", "--verify", "MERGE_HEAD").returncode != 0, \
        "复位后 MERGE_HEAD 必须消失（否则下一轮还会在同一批文件上冲突）"
    st = _ok_git(r, "status", "--porcelain")
    assert not st, "复位后工作树应干净（该夹具的改动都在被放弃的 merge 里）"


def test_abort_is_idempotent_when_no_merge_in_progress(mid_merge):
    r = mid_merge
    assert _abort(r).ok is True
    again = _abort(r)
    assert again.ok is True and again.error == "", "无合并在进行＝已复位＝ok（不谎报、不报错）"


def test_abort_never_uses_hard_reset(tmp_path):
    """复位不得丢工作树改动（不用 --hard）：源码面锁——abort 分支只出现 --merge 兜底。"""
    src = Path(aa.__file__).read_text("utf-8")
    blk = src.split('if bool(getattr(args, "abort", False)):', 1)[1].split("# No MERGE_HEAD", 1)[0]
    assert '"--merge"' in blk and '"--hard"' not in blk and "'--hard'" not in blk, \
        "复位兜底只许 reset --merge HEAD（--hard 会静默丢工作树改动）"
    assert "merge\", \"--abort" in blk or '"--abort"' in blk


# ---------------- ②接线层 ----------------

def test_both_failure_paths_abort_before_blocking():
    src = Path(dev_lane.__file__).read_text("utf-8")
    assert dev_lane.MAIN_SYNC_RECOVERY_PATCH_ID == "t260929-main-sync-abort-on-failed-resolve"
    assert src.count("workflow.patched(MAIN_SYNC_RECOVERY_PATCH_ID)") == 2, \
        "两条失败路径（agent 抛异常 / 交付非 ok）各一处"
    assert src.count("_why += await self._main_sync_abort(") == 2
    # 复位必须发生在 blocked **之前**，且复位后计数器清零（否则下一轮立刻又判「同批反复」）
    for chunk in src.split("workflow.patched(MAIN_SYNC_RECOVERY_PATCH_ID)")[1:]:
        seg = chunk.split("_sync_stop = \"blocked\"", 1)[0]
        assert "_main_sync_abort(" in seg and "await self._blocked(" in seg
        assert seg.index("_main_sync_abort(") < seg.index("await self._blocked("), \
            "先复位再 blocked"
        assert "prev_conflict_files = []" in seg and "conflict_rounds = 0" in seg, \
            "复位后同批计数器必须清零（把死锁降级为干净重试，cap 仍封顶）"


def test_abort_helper_reports_honestly_on_failure():
    """复位失败/异常都必须**如实**写进票面文案（不许把复位说成成功）。"""
    src = Path(dev_lane.__file__).read_text("utf-8")
    helper = src.split("async def _main_sync_abort(", 1)[1].split(
        "# ---------- t260917-08", 1)[0]
    assert "merge reset done (MERGE_HEAD cleared)" in helper
    assert "merge reset failed" in helper and "needs human handling" in helper
    assert "merge reset attempt raised" in helper


def test_payload_key_is_additive():
    """abort 是 additive 键：缺省 False（旧调用/旧 history 反序列化零影响）。"""
    a = shared.ConflictSettleArgs(ticket_id="t")
    assert a.abort is False
    assert shared.ConflictSettleArgs(ticket_id="t", abort=True).abort is True


# ---------------- ③零回归：旧路径门内外行为分界 ----------------

def test_gate_semantics_old_path_unchanged():
    """老 history（无门标记）⇒ patched()=False ⇒ 旧路径（直接 blocked）逐字不变。"""
    src = Path(dev_lane.__file__).read_text("utf-8")
    # 旧路径的 blocked 调用仍在（门是 if 包裹、不改旧语句）
    assert src.count('await self._blocked("implement", _why)') == 2
    assert 'await self._blocked(\n                                    "implement",\n                                    self._conflict_failed_note(' not in src, \
        "非 ok 路径也已改走 _why（单点构造仍在，只是先拼复位文案）"
    assert "self._conflict_failed_note(" in src
    # 同批守卫与 cap 判据一字未动（本修法只旁路重复撞墙，不动守卫本身）
    assert shared.main_sync_conflict_route(3, ["root:a"], ["root:a"], 5).startswith("blocked:")
    assert shared.main_sync_conflict_route(1, ["root:a"], [], 5) == "resolve"
    assert shared.main_sync_conflict_route(9, ["root:a"], ["root:b"], 5).startswith("blocked:")
