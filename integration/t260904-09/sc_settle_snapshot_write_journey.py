#!/usr/bin/env python3
"""sc_settle_snapshot_write_journey.py —— t260904-09 引擎写路径 L3 旅程场景（灰盒）。

intent（用户可感知）：工单收口（squash merge 落定）那一刻，项目账本上就有一份
冻结快照（token 汇总 + squash 真身交付行数），此后面板数字不再随读侧实现/泳道
拆除而抖动；重复收口（Temporal 重试/重复 settle）不多记一笔；收口失败时观测
欠账不卡交付（merge 照常 ok）。

断言面（锚公开契约：快照文件路径约定 SANDBAR_SETTLE_SNAPSHOT_DIR、快照 schema、
MergeResult.ok，不锚函数内部）：
  W0 接线自检：_squash_merge 收 project_key 缝在位（未落地=显式红，TDD 信号）。
  W1 收口出仓：真仓真 merge 后 <settle>/<票>.json 在场，schema_version/ticket_id/
     squash_commit（=merge 回执 short hash）/tokens/delivery 键齐。
  W2 token 口径：只加总 assistant/message usage（chunk 同份 usage 加了翻倍——
     999 哨兵行在，总数仍=100+10/20+2/5+1）；模型归因到当时的 provider/model。
  W3 delivery=squash 真身：numstat 合计与 fixture 行数一致（不靠事后 grep）。
  W4 幂等（重试态）：同分支重入 merge（暂存区空、HEAD=本票 squash）→ 快照
     载荷逐字节稳定（settled_at 除外），账本上只有一份。
  W5 不可变：账面被篡改后重收口 → 保留旧件不回写（merge 仍 ok）。
  W6 软降级：会话目录缺失 / zstd 撕裂帧 → merge 照常 ok，delivery 照常出仓。
  W7 零变更收口：真·无内容可收（HEAD=他票 squash）→ zero_change=true、
     add/del/commits=0、**不把 HEAD 的 numstat 记到本票**（错账面关闭）。
  W8 路径防穿：票 id 含 ../ 注入 → 快照不落 settle 目录之外。

与既有资产 intent 区别：temporal-poc/tests L1（developer）守纯函数级幂等/降级
电池；本场景守「真 git squash merge → 快照文件契约」的跨组件写路径旅程。
预期状态：实现段落地前 W0 起全红属预期（TDD 信号）；merge 关卡必须全绿。
Run: python3 integration/t260904-09/sc_settle_snapshot_write_journey.py（cwd=仓库根）
"""
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path(subprocess.run(["git", "-C", str(HERE), "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True).stdout.strip())
ENGINE = REPO / "server" / "dsh" / "temporal-poc"

PASS, FAIL, SKIP = 0, 0, 0


def ok(cond, label, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok %s" % label)
    else:
        FAIL += 1
        print("  FAIL %s%s" % (label, (" — " + detail) if detail else ""))


def done():
    global PASS, FAIL, SKIP
    print("SUMMARY pass=%d skip=%d fail=%d" % (PASS, SKIP, FAIL))
    return 0 if FAIL == 0 else 1


def sh(args, cwd=None):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("%s failed: %s" % (args[0], (r.stderr or r.stdout)[-300:]))
    return r.stdout.strip()


# ---- temporalio 桩（t260901-16 先例：只为 import，defn 原样透传） ----
_mod = types.ModuleType("temporalio")
_act = types.ModuleType("temporalio.activity")
_act.defn = lambda fn=None, **kw: (lambda f: f)(fn) if fn else (lambda f: f)
_act.logger = logging.getLogger("stub")
_mod.activity = _act
sys.modules["temporalio"] = _mod
sys.modules["temporalio.activity"] = _act
sys.path.insert(0, str(ENGINE))


def git_init(repo: Path) -> None:
    repo.mkdir(parents=True)
    sh(["git", "init", "-q"], str(repo))
    for k, v in (("user.email", "sc-t260904-09@test.invalid"), ("user.name", "sc-t260904-09"),
                 ("commit.gpgsign", "false")):
        sh(["git", "config", k, v], str(repo))


def commit_file(repo: Path, rel: str, lines: int, message: str, prefix: str = "line") -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join("%s %d\n" % (prefix, i + 1) for i in range(lines)), encoding="utf8")
    sh(["git", "add", "-A"], str(repo))
    sh(["git", "commit", "-q", "-m", message], str(repo))


def write_session(wt: Path, ticket_id: str, *, torn: bool = False) -> None:
    """造 <wt>/.dsh/sessions/<slug>/<票>-review/session.jsonl.zstd（chunk 翻倍哨兵在）。"""
    d = wt / ".dsh" / "sessions" / "fixture-repo" / ("%s-review" % ticket_id)
    d.mkdir(parents=True, exist_ok=True)
    lines = [
        {"type": "request/context", "data": {"provider": "prov", "model": "m1"}},
        {"type": "assistant/message", "data": {"usage": {"inputTokens": 100, "outputTokens": 20, "cacheReadTokens": 5}}},
        {"type": "request/context", "data": {"provider": "prov", "model": "m2"}},
        {"type": "assistant/message", "data": {"usage": {"inputTokens": 10, "outputTokens": 2, "cacheReadTokens": 1}}},
        {"type": "assistant/chunk", "data": {"chunk": {"type": "usage"},
                                             "usage": {"inputTokens": 999, "outputTokens": 999, "cacheReadTokens": 999}}},
    ]
    raw = "\n".join(json.dumps(o) for o in lines).encode("utf8")
    tmp_raw = d / "session.jsonl"
    tmp_raw.write_bytes(raw)
    dst = d / "session.jsonl.zstd"
    r = subprocess.run(["zstd", "-q", "-f", "-o", str(dst), str(tmp_raw)], capture_output=True)
    tmp_raw.unlink()
    if torn:
        dst.write_bytes(dst.read_bytes()[: max(1, dst.stat().st_size // 3)])  # 撕裂帧


def main() -> int:
    if shutil.which("zstd") is None:
        print("SKIP settle-snapshot-write-journey：zstd CLI 不在 PATH（引擎同依赖，环境不备留因）")
        global SKIP
        SKIP = 1
        print("SUMMARY pass=%d skip=%d fail=%d" % (PASS, SKIP, FAIL))
        return 0

    import agent_activities as aa

    tmp = Path(tempfile.mkdtemp(prefix="sc-t260904-09-"))
    settle = tmp / "settle" / "demo" / "data" / "settle"  # env 替换项目根整体：快照落 <env>/<key>/data/settle
    os.environ["SANDBAR_SETTLE_SNAPSHOT_DIR"] = str(tmp / "settle")  # env=项目根整体；快照落 <env>/demo/data/settle
    try:
        repo = tmp / "main"
        git_init(repo)
        commit_file(repo, "base.txt", 1, "init")
        commit_file(repo, "fa.txt", 12, "main 侧 fa 初版", prefix="fa0")  # fa 在 base 已存在 → 泳道改写产生删除行
        sh(["git", "branch", "lane/sc-snap"], str(repo))
        wt = tmp / "wt-snap"
        sh(["git", "worktree", "add", "-q", str(wt), "lane/sc-snap"], str(repo))
        # 泳道两小步：fa 12 行改写 7 行（+7/−12，base 已有 fa）+ fb 新增 5 行 → squash 真身 add=12 del=12
        commit_file(wt, "fa.txt", 7, "lane 小步一（改写 fa）", prefix="fa2")
        commit_file(wt, "fb.txt", 5, "lane 小步二（含 fa 改写）", prefix="fb")
        write_session(wt, "t260904-09s1")

        T1 = "t260904-09s1"
        try:
            res = aa._squash_merge(repo=repo, wt=wt, branch="lane/sc-snap", ticket_id=T1,
                                   defer_teardown=True, project_key="demo")
        except TypeError as e:
            ok(False, "W0 merge 收 project_key 缝在位", "TypeError: %s（实现段未落地，预期红）" % str(e)[:120])
            return done()
        ok(res.ok, "W0 merge 接线在位且收口 ok", str(getattr(res, "error", ""))[:160])
        if not res.ok:
            return done()

        snap_path = settle / ("%s.json" % T1)
        ok(snap_path.is_file(), "W1 收口出仓：<settle>/<票>.json 在场", str(snap_path))
        snap = json.loads(snap_path.read_text(encoding="utf8")) if snap_path.is_file() else {}
        ok(all(k in snap for k in ("schema_version", "ticket_id", "squash_commit", "tokens", "delivery")),
           "W1 schema 键齐", str(sorted(snap.keys())))
        ok(snap.get("squash_commit") == res.merge_commit,
           "W1 squash_commit=merge 回执真身", "%s vs %s" % (snap.get("squash_commit"), res.merge_commit))

        tk = snap.get("tokens") or {}
        ok(tk.get("in") == 110 and tk.get("out") == 22 and tk.get("cacheRead") == 6,
           "W2 token 只加总 message（chunk 999 哨兵不计）", json.dumps(tk)[:160])
        ok("prov/m1" in (tk.get("by_model") or {}) and "prov/m2" in (tk.get("by_model") or {}),
           "W2 模型归因到当时 provider/model", str(tk.get("by_model"))[:120])

        dv = snap.get("delivery") or {}
        ok(dv.get("add") == 12 and dv.get("del") == 12 and dv.get("commits") == 1,
           "W3 delivery=squash 真身 numstat（+12/−12/1c）", json.dumps(dv)[:160])
        base_hash = sh(["git", "rev-parse", "--short", "%s^1" % res.merge_commit], str(repo))
        ok(dv.get("base") == base_hash, "W3 base= squash 父提交", "%s vs %s" % (dv.get("base"), base_hash))

        # W4 幂等（重试态）：同分支重入（暂存区空、HEAD=本票 squash，message 前缀匹配）
        before = json.loads(snap_path.read_text(encoding="utf8"))
        res2 = aa._squash_merge(repo=repo, wt=wt, branch="lane/sc-snap", ticket_id=T1,
                                defer_teardown=True, project_key="demo")
        after = json.loads(snap_path.read_text(encoding="utf8"))
        before.pop("settled_at", None), after.pop("settled_at", None)
        ok(res2.ok and before == after, "W4 重试态重收口：载荷稳定不双算",
           "ok=%s equal=%s" % (res2.ok, before == after))
        ok(sorted(p.name for p in settle.glob("*.json")) == ["%s.json" % T1], "W4 账本恰一份", str(list(settle.iterdir())))

        # W5 不可变：篡改账面后重收口 → 保留旧件
        before["delivery"]["add"] = 999
        snap_path.write_text(json.dumps(before), encoding="utf8")
        res3 = aa._squash_merge(repo=repo, wt=wt, branch="lane/sc-snap", ticket_id=T1,
                                defer_teardown=True, project_key="demo")
        kept = json.loads(snap_path.read_text(encoding="utf8"))
        ok(res3.ok and kept.get("delivery", {}).get("add") == 999, "W5 载荷不一致：保留旧件不回写且 merge ok",
           "ok=%s add=%s" % (res3.ok, kept.get("delivery", {}).get("add")))

        # W6 软降级（会话目录缺失 + zstd 撕裂帧两态）：merge 照常 ok、delivery 照常出仓
        sh(["git", "branch", "lane/sc-snap2"], str(repo))
        wt2 = tmp / "wt-snap2"
        sh(["git", "worktree", "add", "-q", str(wt2), "lane/sc-snap2"], str(repo))
        T2 = "t260904-09s2"   # 无会话目录
        commit_file(wt2, "fc.txt", 3, "lane 二号小步", prefix="fc")
        res4 = aa._squash_merge(repo=repo, wt=wt2, branch="lane/sc-snap2", ticket_id=T2,
                                defer_teardown=True, project_key="demo")
        snap2 = json.loads((settle / ("%s.json" % T2)).read_text(encoding="utf8")) if res4.ok else {}
        ok(res4.ok and (snap2.get("delivery") or {}).get("add") == 3,
           "W6 无会话目录：merge ok 且 delivery 出仓", "ok=%s delivery=%s" % (res4.ok, json.dumps(snap2.get("delivery"))[:120]))
        ok((snap2.get("tokens") or {}).get("in", 0) == 0, "W6 无会话：token 不虚计", str(snap2.get("tokens"))[:120])

        sh(["git", "branch", "lane/sc-snap3"], str(repo))
        wt3 = tmp / "wt-snap3"
        sh(["git", "worktree", "add", "-q", str(wt3), "lane/sc-snap3"], str(repo))
        T4 = "t260904-09s4"   # 撕裂 zstd 帧
        commit_file(wt3, "fd.txt", 4, "lane 三号小步", prefix="fd")
        write_session(wt3, T4, torn=True)
        res5 = aa._squash_merge(repo=repo, wt=wt3, branch="lane/sc-snap3", ticket_id=T4,
                                defer_teardown=True, project_key="demo")
        snap4 = json.loads((settle / ("%s.json" % T4)).read_text(encoding="utf8")) if res5.ok else {}
        ok(res5.ok and (snap4.get("delivery") or {}).get("add") == 4,
           "W6 zstd 撕裂帧：merge ok 且 delivery 出仓（软降级不阻塞）",
           "ok=%s delivery=%s" % (res5.ok, json.dumps(snap4.get("delivery"))[:120]))

        # W7 零变更收口：真·无内容可收（HEAD=他票 T4 的 squash），不吸他票账
        sh(["git", "branch", "lane/sc-empty"], str(repo))
        T3 = "t260904-09s3"
        res6 = aa._squash_merge(repo=repo, wt=tmp / "wt-nowt", branch="lane/sc-empty", ticket_id=T3,
                                defer_teardown=True, project_key="demo")
        snap3 = json.loads((settle / ("%s.json" % T3)).read_text(encoding="utf8")) if res6.ok else {}
        dv3 = snap3.get("delivery") or {}
        ok(res6.ok and dv3.get("zero_change") is True and dv3.get("add") == 0 and dv3.get("del") == 0
           and dv3.get("commits") == 0,
           "W7 零变更收口：zero_change=true 且不吸他票 HEAD 账", json.dumps(dv3)[:160])

        # W8 路径防穿：票 id 注入 ../ 不落 settle 目录之外
        sh(["git", "branch", "lane/sc-esc"], str(repo))
        try:
            aa._squash_merge(repo=repo, wt=tmp / "wt-nowt", branch="lane/sc-esc",
                             ticket_id="../escape_t260904-09", defer_teardown=True, project_key="demo")
        except Exception as e:  # 快照缝可以选择显式拒绝——只要不落盘逃逸
            ok(True, "W8 注入票 id 显式拒绝（不静默）", str(e)[:120])
        escaped = [p for p in tmp.rglob("*.json") if "escape" in p.name or "escape" in str(p.parent)]
        ok(not escaped, "W8 注入票 id 不落 settle 目录之外", str(escaped[:3]))
        return done()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        os.environ.pop("SANDBAR_SETTLE_SNAPSHOT_DIR", None)


if __name__ == "__main__":
    sys.exit(main())
