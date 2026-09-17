#!/usr/bin/env python3
"""t260915-01 ②端到端腿：路径闸拒绝的结构化明细从真实判定点走到票面（灰盒 L2）。

用户可感知契约（R3 验收缝闭合）：worker 代落盘（settle）被路径闸拒绝时，**活动回执**
除人读 note 外还带结构化明细 gate_refusal——files 与 path_gates 判定清单全量相等
（不经 _fmt_files cap，不丢文件）、reason_code 与 note 内嵌码一致、evidence 与 note
逐字相同（=worker 日志原文）；workflow 侧消费（sanitize）后 blocked_detail 结构键齐。
负腿=非闸拒绝/正常落盘不挂明细。这是「测试在场≠接线生效」（KI-046/049）的反面：
本场景从**真实 settle 判定点**驱动，任何接线断裂（dict 建了没传/传了没挂）都会红。

跑法：PY=server/engine/.venv/bin/python; [ -x "$PY" ] || PY=python3; "$PY" -B
      integration/t260915-01/tests/sc_detail_red_refusal_end2end.py（cwd=仓根）
纯本地：tmp 主仓+真注册泳道 worktree+直调 settle 单点，零 Temporal server 零端口。
三态：PASS exit 0 / FAIL exit 1 / ENV_FAIL exit 2（三态契约，无第四态）。
"""
import inspect
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
TICKET = "t260915-01"

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
    import path_gates
    return agent_activities, path_gates


BASE = {
    "verify.yaml": "schema: v1\nlanes:\n  code:\n    write_allow:\n      - server/engine/\n      - integration/\n    checks: []\n",
    "server/engine/keep.py": "# engine anchor\n",
    "docs/design/contract-v1.md": "# contract v1\n",
    "integration/t260915-01/tests/.keep": "",
    # t260916-19 B 契约修订：??/M 态越权改自动处置不再拒绝，L1 探针改删除型（D 态）
    # 注入以保持「拒绝+结构化全量 files」可测——探针先落分叉点基线（tracked）。
    "server/engine/rogue_0.py": "x = 0\n",
    "server/engine/rogue_1.py": "x = 1\n",
    "server/engine/rogue_2.py": "x = 2\n",
    "server/engine/rogue_3.py": "x = 3\n",
    "server/engine/rogue_4.py": "x = 4\n",
}


def mk_lane():
    tmp = Path(tempfile.mkdtemp(prefix="detailred-e2e-"))
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


def main():
    aa, pg = load_engine()

    # ---- L0 兼容腿：新参数缺省 None（既有直调场景逐字不变）----
    section("L0 兼容腿：refusal 形参缺省 None、gate_refusal dataclass 字段缺省 None")
    for fn in ("_settle_worktree_lane", "_settle_with_gate", "_apply_settle_note"):
        sig = inspect.signature(getattr(aa, fn)).parameters
        ok("refusal" in sig and sig["refusal"].default is None,
           "%s refusal 缺省 None（既有直调场景逐字不变）" % fn)
    ok(aa.StageResult().gate_refusal is None and aa.SettleLaneResult().gate_refusal is None,
       "StageResult/SettleLaneResult.gate_refusal 缺省 None（老回执重放安全）")

    # ---- L1 正例：零代码改动段注入产品代码 → 拒绝+结构化明细（验收②正例）----
    # 5 个越权探针（登记 intent：结构化面 files 全量相等、一个不丢——_fmt_files 的
    # cap=3 只许作用于人读 note 文本，结构化面不得截断）
    section("L1 acceptance_walkthrough 越权（5 探针） → 回执 gate_refusal 与判定/note 一致")
    tmp, mainrepo, lane, fork = mk_lane()
    rogues = ["server/engine/rogue_%d.py" % i for i in range(5)]
    # 删除型注入（D 态）：t260916-19 B 起 ??/M 态越权自动处置不再拒绝（本腿锁的是
    # 结构化拒绝回执保真，D 态在新旧契约下都产生拒绝终态）——探针已落分叉点基线。
    for rel in rogues:
        (lane / rel).unlink()
    refusal = {}
    before = head(lane)
    note = aa._settle_worktree_lane(lane, TICKET, "acceptance_walkthrough", 0,
                                    repo=mainrepo, path_gate=True, write_set=[],
                                    base_ref=fork, refusal=refusal,
                                    face="join")  # t260916-19 D：face 必填分层标签
    ok("path_gate_reason=unauthorized_path" in str(note), "note 带机读原因码")
    ok(bool(refusal), "结构化明细已收集（refusal dict 非空）")
    if refusal:
        # 判定单点重放：violations 清单须与闸判定全量相等（不丢文件口径）
        _, violations, reason = pg.judge_stage_paths(
            "acceptance_walkthrough", rogues + [".sandbar/stage_acceptance_walkthrough_gen0.json"],
            write_set=[], ticket_id=TICKET)
        ok(refusal.get("reason_code") == "unauthorized_path"
           and ("path_gate_reason=unauthorized_path" in note),
           "reason_code 与 note 内嵌码一致")
        ok(len(refusal.get("files") or []) == 5 and all(r in refusal["files"] for r in rogues),
           "5 探针一个不丢（结构化面全量=%s）" % refusal.get("files"))
        ok(refusal.get("files") == violations or set(refusal.get("files") or []) == set(violations),
           "files 与闸判定清单全量相等（判得 %s）" % violations)
        ok(refusal.get("evidence") == note, "evidence 与 note 逐字相同（=worker 日志原文）")
        ok(refusal.get("check_id") == "path_gate@acceptance_walkthrough", "check_id 点名段")
        ok(refusal.get("red") is True and bool(refusal.get("next_action")), "red 标记+next_action 在场")
    ok(head(lane) == before, "0 新 commit（拒绝落盘）")

    # ---- L2 负腿：写集内正常落盘 → refusal 空收集（不误挂）----
    section("L2 implement 写集内改动 → 落盘+零明细收集")
    tmp2, main2, lane2, fork2 = mk_lane()
    allowed = "server/engine/allowed.py"
    (lane2 / allowed).write_text("# in write set\n", encoding="utf-8")
    refusal2 = {}
    note2 = aa._settle_worktree_lane(lane2, TICKET, "implement", 0,
                                     repo=main2, path_gate=True,
                                     write_set=[allowed], base_ref=fork2, refusal=refusal2,
                                     face="join")
    ok(not refusal2, "正常落盘：refusal 空收集（负腿）")
    ok("path_gate_reason" not in str(note2), "回执零原因码")
    ok(head(lane2) != fork2, "commit 真落地")

    # ---- L3 受保护路径腿：改 base 已存在的真源 → protected_path+点名 ----
    # （干净泳道：受保护闸只在阶段闸放行后判——脏泳道会先撞 unauthorized_path）
    section("L3 改受保护真源 verify.yaml → protected_path 结构化")
    tmp3, main3, lane3, fork3 = mk_lane()
    (lane3 / "verify.yaml").write_text("schema: v2\n", encoding="utf-8")
    refusal3 = {}
    note3 = aa._settle_worktree_lane(lane3, TICKET, "implement", 1,
                                     repo=main3, path_gate=True,
                                     write_set=["verify.yaml"], base_ref=fork3, refusal=refusal3,
                                     face="join")
    ok("path_gate_reason=protected_path" in str(note3), "note 带受保护原因码")
    ok(refusal3.get("reason_code") == "protected_path", "结构化 reason_code=protected_path")
    ok(refusal3.get("item") == "受保护路径闸", "人话名=受保护路径闸")
    ok(refusal3.get("evidence") == note3, "evidence 与 note 逐字相同")

    # ---- L4 接线腿：真回执+真 refusal 喂 _apply_settle_note → 挂载 ----
    section("L4 _apply_settle_note 真 refusal 挂载（接线在场，非自造 dict）")
    res = aa.StageResult(status="ok", summary="s", evidence="e")
    out = aa._apply_settle_note(res, note, refusal=dict(refusal))
    ok(out.status == "failed" and out.summary == note, "闸拒绝改判 failed+summary=回执原文")
    ok(out.gate_refusal == refusal, "gate_refusal 逐字挂载（结构三件不走样）")
    res_neg = aa.StageResult(status="ok", summary="s")
    out_neg = aa._apply_settle_note(res_neg, note2, refusal=dict(refusal2))
    ok(out_neg.status == "ok" and out_neg.gate_refusal is None, "非闸拒绝不挂（负腿）")

    # ---- L5 消费腿：workflow 侧 _pin 经 sanitize 上 blocked_detail（结构键齐）----
    section("L5 dev_lane._pin_agent_refusal 消费真回执 → blocked_detail 键齐")
    import dev_lane
    from types import SimpleNamespace
    datetime = __import__("datetime")
    dev_lane.workflow = SimpleNamespace(
        patched=lambda pid: pid == dev_lane.DETAIL_FACE_PATCH_ID,
        now=lambda: datetime.datetime(2026, 9, 15, 12, 0, 0),
        logger=SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None))
    wf = object.__new__(dev_lane.DevLaneWorkflow)
    wf.meta = {}
    wf.timeline = []
    wf._gens = {}
    wf._retry_token = 1
    wf._rework = None
    wf.results = {}
    wf.ticket_id = TICKET
    wf._detail_face_on = True
    wf.engine_version = 2
    failed = aa.StageResult(status="failed", summary=note, evidence="…",
                            gate_refusal=dict(refusal))
    wf._pin_agent_refusal(failed)
    d = wf.meta.get("blocked_detail") or {}
    ok(d.get("reason_code") == "unauthorized_path", "blocked_detail.reason_code 在场")
    ok(isinstance(d.get("files"), list) and d.get("files"), "blocked_detail.files 非空列表")
    ok(all(k in d for k in ("check_id", "item", "red", "next_action", "evidence")),
       "结构键齐（check_id/item/red/next_action/evidence）")
    ok(d.get("evidence") == note, "blocked_detail.evidence=回执原文（不美化）")

    print("\nSC sc_detail_red_refusal_end2end pass=%d fail=%d" % (_ok, _fail))
    return 0 if _fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
