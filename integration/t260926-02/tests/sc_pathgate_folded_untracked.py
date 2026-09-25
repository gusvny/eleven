#!/usr/bin/env python3
"""KI-125·越权闸不认 git 折叠的未跟踪目录（t260926-02，灰盒 L2，真实 settle 单点直调）。

用户可感知契约（nusuyou 260925 四缺口 gap1 实案）：票写集条目写成**新目录内具体
文件**（`workflows/content_studio.py`，目录整体未跟踪被 git 折叠成 `?? workflows/`）
时，合法交付**必须落地**，不得被 unauthorized_path 隔离进 .sandbar/quarantine/、
票不得两轮落不了地。修复方向=判定前把折叠目录展开为文件级条目（数据收集端展开，
闸语义零放宽），故验收含**反向对照**：写集外文件不得因同目录前缀被连带放行
（闸不得放宽），目录级条目对照组（commit f1ca1a9a 形态）不回归，嵌套仓折叠形态
保留（gitlink 闸前提不被展开破坏），merge_check 自愈准入对同一形态放行
（review_plan 附条件⑤：同族根修，折叠清单拒自愈=同症残留）。

依据：①工单原始需求（KI-125：合法交付被隔离两轮落不了地；目录级条目对照组可过）；
②已知问题清单 notes/debts/known-issues.md KI-125（修法方向+验收须含反向对照）；
③对外契约=路径闸承诺「写集白名单零放宽、合法交付不误伤」（t260911-03 系执法点）。
与 t260911-03 系不同面（彼锁拒绝/放行终态接线，注入件均非「git 折叠目录」形态）；
与 t26091619-unauth-disposal-matrix 不同面（彼分态矩阵用平铺文件，本条锁折叠目录
展开后的混合批次收口）；与 developer L1 纯函数矩阵不同层（本条锁真实 git 折叠形态
→ settle → commit 磁盘终态）。

跑法：PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; "$PY" -B
      integration/t260926-02/tests/sc_pathgate_folded_untracked.py（cwd=仓根）
纯本地：tmp 主仓+真注册泳道 worktree+直调 settle 单点，零 Temporal server 零端口。
三态：PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2（三态契约，无第四态）。
实现段落地前 A/D/E 子用例红属预期（TDD 验收门），arbitrate/merge 期必须绿。
"""
import inspect
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
TICKET = "t260926-02"

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
              "（KI-036 口径：缺环境点名，环境红非产品红）")
        sys.exit(2)
    sys.path.insert(0, str(REPO / "server" / "engine"))
    import agent_activities
    return agent_activities


BASE = {
    "verify.yaml": "schema: v1\nlanes:\n  code:\n    write_allow:\n      - server/engine/\n      - integration/\n    checks: []\n",
    "server/engine/keep.py": "# engine anchor\n",
    "docs/design/contract-v1.md": "# contract v1\n",
    "integration/t260926-02/tests/.keep": "",
}


def mk_lane():
    """tmp 主仓（带本地 git 身份）+ 真注册泳道 worktree → (tmp, main, lane, 分叉sha)。"""
    tmp = Path(tempfile.mkdtemp(prefix="pathgate-ki125-"))
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


def head(repo):
    return sh("git", "-C", repo, "rev-parse", "HEAD").stdout.strip()


def committed(repo):
    out = sh("git", "-C", repo, "show", "--name-only", "--format=", "HEAD").stdout
    return [ln for ln in out.splitlines() if ln.strip()]


def inject(lane, rel, content="x = 1\n"):
    p = lane / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def quarantine_names(lane):
    q = lane / ".sandbar" / "quarantine"
    if not q.is_dir():
        return []
    return sorted(x.name for x in q.iterdir())


def quarantined_files(lane):
    """隔离区全量文件（含批次目录深层——挪档保留相对路径，t260916-19 ② 矩阵）。"""
    q = lane / ".sandbar" / "quarantine"
    if not q.is_dir():
        return []
    return sorted(str(p.relative_to(q)) for p in q.rglob("*") if p.is_file())


def main():
    aa = load_engine()
    sig = inspect.signature(aa._settle_worktree_lane)
    has_gate = "path_gate" in sig.parameters
    has_face = "face" in sig.parameters

    def settle(lane, mainrepo, stage, gen=0, write_set=None, base=""):
        if not has_gate:
            return None, "settle 未接闸参数（path_gate 不在签名）——闸未接线，契约未兑现"
        try:
            kwargs = dict(repo=mainrepo, path_gate=True,
                          write_set=list(write_set or []),
                          base_ref=str(base))
            if has_face:
                kwargs["face"] = "join"
            return aa._settle_worktree_lane(lane, TICKET, stage, gen, **kwargs), None
        except Exception as e:  # noqa: BLE001
            return None, "settle 调用异常：%s" % e

    # ---- A（KI-125 事故形态）：新目录 × 文件级写集条目 → 合法交付落地 ----
    section("A 新目录整体未跟踪 × 文件级写集条目 → 落地（事故修复面）")
    tmp, mainrepo, lane, fork = mk_lane()
    inject(lane, "workflows/content_studio.py")
    before = head(lane)
    note, err = settle(lane, mainrepo, "implement",
                       write_set=["workflows/content_studio.py"], base=fork)
    if note is None:
        ok(False, "A 驱动失败：%s" % (err or ""))
    else:
        ok("unauthorized_path" not in note, "回执零 unauthorized_path（折叠形态不再误判越权）")
        ok(head(lane) != before, "commit 落地（合法交付不隔离、票不停摆）")
        c = committed(lane)
        ok("workflows/content_studio.py" in c, "新目录内文件真入库")
        ok(not any(n.startswith("fake") for n in quarantine_names(lane)),
           "交付件未进 .sandbar/quarantine/")

    # ---- B（反向对照，验收硬性要求）：同目录塞写集外文件 → 闸不放宽 ----
    section("B 同目录混入写集外文件 → 不连带放行（闸零放宽反向对照）")
    tmp, mainrepo, lane, fork = mk_lane()
    inject(lane, "workflows/content_studio.py")
    inject(lane, "workflows/evil.sh", "#!/bin/sh\nrm -rf /\n")
    before = head(lane)
    note, err = settle(lane, mainrepo, "implement",
                       write_set=["workflows/content_studio.py"], base=fork)
    if note is None:
        ok(False, "B 驱动失败：%s" % (err or ""))
    else:
        c = committed(lane) if head(lane) != before else []
        ok("workflows/evil.sh" not in c, "写集外文件绝不入库（不因目录折叠/展开被连带放行）")
        ok("workflows/content_studio.py" in c, "同批合法文件仍落地（处置不误伤）")
        ok(any("evil.sh" in n for n in quarantined_files(lane)),
           "越权件留档可追溯（.sandbar/quarantine/ 批次目录内在案）")
    # 纯写集外新目录：什么都不该落地
    section("B2 纯写集外新目录 → 零落地")
    tmp, mainrepo, lane, fork = mk_lane()
    inject(lane, "elsewhere/rogue.py")
    before = head(lane)
    note, err = settle(lane, mainrepo, "implement",
                       write_set=["workflows/content_studio.py"], base=fork)
    if note is None:
        ok(False, "B2 驱动失败：%s" % (err or ""))
    else:
        ok(head(lane) == before, "写集外目录零 commit")
        ok(not committed(lane) or "elsewhere/rogue.py" not in committed(lane),
           "rogue.py 不在历史内")
        ok(any("rogue.py" in n for n in quarantined_files(lane)), "越权件留档在案")

    # ---- C（对照组，f1ca1a9a 形态）：目录级写集条目 → 照常落地不回归 ----
    section("C 目录级写集条目 → 落地（事故对照组不回归）")
    tmp, mainrepo, lane, fork = mk_lane()
    inject(lane, "packaging/setup_helper.py")
    before = head(lane)
    note, err = settle(lane, mainrepo, "implement",
                       write_set=["packaging/"], base=fork)
    if note is None:
        ok(False, "C 驱动失败：%s" % (err or ""))
    else:
        ok("unauthorized_path" not in note and head(lane) != before,
           "目录级条目放行且落地（f1ca1a9a 对照形态）")

    # ---- D（嵌套仓折叠保留）：泳道内 git init 子仓 → gitlink 闸仍拦 ----
    section("D 泳道内新建嵌套仓 → gitlink 闸拦截（展开不得破坏闸前提）")
    tmp, mainrepo, lane, fork = mk_lane()
    sub = lane / "submod"
    sub.mkdir()
    sh("git", "init", "-q", cwd=sub)
    sh("git", "-C", sub, "config", "user.email", "t@t")
    sh("git", "-C", sub, "config", "user.name", "t")
    (sub / "inner.txt").write_text("i\n", encoding="utf-8")
    sh("git", "-C", sub, "add", "-A")
    sh("git", "-C", sub, "commit", "-qm", "inner")
    before = head(lane)
    note, err = settle(lane, mainrepo, "implement",
                       write_set=["submod/"], base=fork)
    if note is None:
        ok(False, "D 驱动失败：%s" % (err or ""))
    else:
        ok(head(lane) == before, "嵌套仓形态零 commit（拒绝落盘）")
        ok("gitlink" in note or "gitlink" in note.lower() or "嵌套" in note,
           "拒绝点名嵌套仓/gitlink（不是 unauthorized_path 冒名）")

    # ---- E（自愈准入同族面）：折叠形态展开后，写集自愈准入判定放行 ----
    section("E merge_check 自愈准入：新目录×文件级写集 → 准入判定为真")
    tmp, mainrepo, lane, fork = mk_lane()
    inject(lane, "workflows/content_studio.py")
    p = sh("git", "-C", lane, "status", "--porcelain", "-z",
           "--untracked-files=all", "--", ".")
    ok(p.returncode == 0, "status -uall 可执行")
    dirty = aa._dirty_files_from_status_z(p.stdout)
    ok("workflows/content_studio.py" in dirty,
       "判脏清单为文件级条目（折叠目录已展开，非 `workflows/` 单条）")
    ok(aa._dirty_within_write_set(dirty, ["workflows/content_studio.py"]),
       "自愈准入判定放行（同症不残留：merge_check 阶段不再 fail-closed 拒自愈）")

    print("\nSUMMARY pass=%d fail=%d env_fail=0 na=0" % (_ok, _fail))
    if _fail:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    finally:
        pass
