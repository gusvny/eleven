#!/usr/bin/env python3
"""外置模板声明驱动的段路径闸·settle 执法面（t260925-23 / KI-124，灰盒 L3）。

用户可感知契约（工单原始需求 gap 3 四条 + review_plan 附条件③④）：
  A1 外置模板自声明 PATH_GATE_RULES 后，闸按**模板规则**执法——模板自有段 id
     （不在内建 STAGE_PATH_RULES 表内）不在永拒：面内改动照常落盘；面外改动
     拒绝落盘+path_gate_reason=unauthorized_path+点名+0 新 commit（不再「外置
     模板跑在无护栏状态」）。声明即真源：模板规则优先于内建表。
  A2 声明了空/假值规则（如 ""、{}）＝声明了坏值——**绝不静默跌回内建表**
     （review_plan 附条件③ falsy 遮蔽坑）：同名内建段的允许面不得被假值声明
     意外放行（fail-closed 或加载口拒收，二有一即可，不许「装没声明」）。
  A3 闸开＋段在两侧规则表皆未声明 → 拒绝落盘+path_gate_reason=unknown_stage，
     且文案点名：段 id、缺哪条规则（PATH_GATE_RULES["<id>"]）、怎么补——
     不许裸 unknown_stage 无出路（工单需求④）。

与既有条目 intent 分工：
  t260911-03 系（walkthrough/protected/normal/legacy）锁 dev-lane 内建表的
  settle 执法终态与老票兼容——本条锁**模板声明规则**驱动闸（声明面在
  sc_template_pathgate_load_contract 锁加载口，本条锁执行面接线与终态）；
  developer L1 judge 纯函数矩阵不同层（本条真 settle 单点直调，锁透传不断裂）。

跑法：PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; "$PY" -B
      integration/t260925-23/tests/sc_template_pathgate_faces.py（cwd=仓根）
纯本地：tmp 主仓+真注册泳道 worktree+直调 settle 单点，零 Temporal server 零端口。
三态：PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2（三态契约，无第四态）。
实现落地前 A1-A3 红属预期（TDD 验收门），arbitrate/merge 期必须绿。
"""
import inspect
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lib_tmp_reclaim import mkdtemp_reclaimed  # noqa: E402  （集成侧回收 helper：注册表+atexit）

REPO = Path(__file__).resolve().parents[3]
TICKET = "t260925-23"

_ok = _fail = 0


def ok(cond, label):
    global _ok, _fail
    print(("  ok " if cond else "  FAIL ") + label)
    _ok, _fail = _ok + (1 if cond else 0), _fail + (0 if cond else 1)


def section(t):
    print("\n== " + t)


def sh(*cmd, cwd=None):
    return subprocess.run([str(c) for c in cmd], capture_output=True, text=True,
                          cwd=str(cwd) if cwd else None)


def load_engine():
    if shutil.which("git") is None:
        print("ENV_FAIL: git 不可用（本场景全程真 git 仓）")
        sys.exit(2)
    try:
        import temporalio  # noqa: F401
    except Exception:
        print("ENV_FAIL: temporalio 不可导入——用 server/engine/.venv/bin/python 跑"
              "（环境红非产品红，exit 2 三态契约）")
        sys.exit(2)
    sys.path.insert(0, str(REPO / "server" / "engine"))
    import agent_activities
    return agent_activities


BASE = {
    "verify.yaml": "schema: v1\nlanes:\n  code:\n    write_allow:\n      - server/engine/\n      - integration/\n    checks: []\n",
    "server/engine/keep.py": "# engine anchor\n",
    "docs/design/contract-v1.md": "# contract v1\n",
    "integration/baselines/sc_battery.py": "# shared battery\n",
}


def head(repo):
    return sh("git", "-C", repo, "rev-parse", "HEAD").stdout.strip()


def mk_lane():
    """tmp 主仓（带本地 git 身份）+ 真注册泳道 worktree → (tmp, main, lane, 分叉sha)。"""
    tmp = mkdtemp_reclaimed("t26092523-faces-")
    main = tmp / "main"
    main.mkdir()
    for rel, content in BASE.items():
        p = main / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    sh("git", "init", "-q", "-b", "main", cwd=main)
    sh("git", "config", "user.email", "t@t", cwd=main)
    sh("git", "config", "user.name", "t", cwd=main)
    sh("git", "add", "-A", cwd=main)
    sh("git", "commit", "-qm", "init", cwd=main)
    fork = head(main)
    lane = tmp / "lane"
    r = sh("git", "-C", main, "worktree", "add", "-q", "-b", "lane/" + TICKET, lane)
    assert r.returncode == 0, "worktree add 失败: %s" % r.stderr
    return tmp, main, lane, fork


def inject(lane, rel, content="x = 1\n"):
    p = lane / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


# 模板自有的段 id——刻意不在内建 STAGE_PATH_RULES 键集内（外置模板八新段的同构形态）。
TPL_STAGE = "polish"


def settle(aa, lane, mainrepo, fork, stage, rules, write_set, path_gate=True):
    kw = dict(repo=mainrepo, base_ref=str(fork), write_set=list(write_set),
              path_gate=path_gate, path_gate_rules=dict(rules or {}))
    if "face" in inspect.signature(aa._settle_worktree_lane).parameters:
        kw["face"] = "join"  # t260916-19 face 分层标签：本条只锁路径闸执法，标签取免检值
    return aa._settle_worktree_lane(lane, TICKET, stage, 0, **kw)


def main():
    aa = load_engine()
    sig = inspect.signature(aa._settle_worktree_lane).parameters
    if "path_gate_rules" not in sig:
        # 契约未兑现=本条全部子用例红（TDD 门）；path_gate 参数缺位同理。
        ok(False, "settle 无 path_gate_rules 参数——KI-124 模板闸接线未兑现"
                  "（实现落地前红属预期）")

    # ---- A1 模板规则驱动：面内落盘、面外拒绝（0 新 commit+点名） ----
    section("A1 模板段 %s 声明 kind=result_files：面外拒、（对照）面内落盘" % TPL_STAGE)
    tmp, mainrepo, lane, fork = mk_lane()
    before = head(lane)
    inject(lane, "server/engine/oof.py")
    try:
        note = settle(aa, lane, mainrepo, fork, TPL_STAGE,
                      {TPL_STAGE: {"kind": "result_files"}}, write_set=[])
    except Exception as e:  # noqa: BLE001
        note = None
        ok(False, "A1 面外子用例异常：%s" % e)
    if note is not None:
        # t260916-19 既有语义：?? 形态越权文件先自动处置（挪档）再复判，处置转干净
        # =拒绝落盘出口（回执无 path_gate_reason 键、0 commit）；处置不了才回
        # path_gate_reason=unauthorized_path 拒绝 note。两态都是「面外不落盘」，
        # 契约断言落在：0 新 commit + 点名段 id + 原因可辨（unauthorized 或已处置）。
        ok("path_gate_reason=unauthorized_path" in note
           or ("已自动处置" in note and "unauth-%s" % TPL_STAGE in note),
           "面外改动拒绝落盘（unauthorized_path 或越权自动处置，0 commit）")
        ok(TPL_STAGE in note, "回执点名段 id（非裸 unknown_stage）")
        ok(head(lane) == before, "0 新 commit（拒绝落盘）")
    # 面内对照：kind=result_files 语义=只准写结果文件（.sandbar 被 SETTLE_PATHSPEC
    # 排除、settle 不落盘）——「真放行」须用会 commit 的弱面验证：kind=join +
    # write_set 内代码文件 → 正常代落盘。
    tmp, mainrepo, lane, fork = mk_lane()
    before = head(lane)
    inject(lane, "server/engine/inface.py")
    try:
        note = settle(aa, lane, mainrepo, fork, TPL_STAGE,
                      {TPL_STAGE: {"kind": "join"}}, write_set=["server/engine/"])
    except Exception as e:  # noqa: BLE001
        note = None
        ok(False, "A1 面内子用例异常：%s" % e)
    ok(note is not None and "path_gate_reason" not in note and head(lane) != before,
       "面内改动照常落盘（模板规则真放行，非全拒假绿）")

    # ---- A2 假值声明绝不静默跌回内建表（falsy 遮蔽坑，review 附条件③） ----
    section("A2 声明空规则 \"\"（内建表同段有 result_files）→ 不许被内建面放行")
    tmp, mainrepo, lane, fork = mk_lane()
    before = head(lane)
    inject(lane, "server/engine/shadow.py")
    try:
        note = settle(aa, lane, mainrepo, fork, "review_plan", {"review_plan": ""},
                      write_set=[])
    except Exception as e:  # noqa: BLE001
        note = None
        ok(False, "A2 子用例异常：%s" % e)
    if note is not None:
        ok("path_gate_reason" in note and head(lane) == before,
           "坏值声明 fail-closed 拒绝（绝不静默享受内建 result_files 面）")

    # ---- A3 两侧皆未声明 → unknown_stage + 点名段 id 与补法 ----
    section("A3 未声明段 → 拒+unknown_stage+PATH_GATE_RULES 补法指引")
    tmp, mainrepo, lane, fork = mk_lane()
    before = head(lane)
    inject(lane, "server/engine/forgot.py")
    try:
        note = settle(aa, lane, mainrepo, fork, "never_declared_stage", {},
                      write_set=["server/engine/"])
    except Exception as e:  # noqa: BLE001
        note = None
        ok(False, "A3 子用例异常：%s" % e)
    if note is not None:
        ok("path_gate_reason=unknown_stage" in note, "未声明段拒绝+机读原因码")
        ok("never_declared_stage" in note, "文案点名段 id")
        ok("PATH_GATE_RULES" in note, "文案点名补法（在模板类声明 PATH_GATE_RULES）")
        ok("sanctioned way out" in note, "出路文案在场（fail-closed 但给合法出路/sanctioned way out）")
        ok(head(lane) == before, "0 新 commit")

    print("\nSC sc_template_pathgate_faces pass=%d fail=%d" % (_ok, _fail))
    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
