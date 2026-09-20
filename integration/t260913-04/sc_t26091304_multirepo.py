#!/usr/bin/env python3
"""t260913-04 场景④：多仓泳道（成员仓树）在容器形态下可写可落盘（灰盒 L3，真 docker）。

intent（用户可感知）：一票多仓时，agent 在容器里对**每棵成员仓树**的修改都能被
宿主看到、且由 worker 按树落盘成 commit（验收 E）；同时容器挂载面仍只是泳道根
（成员仓的**主树**绝不进容器，红线 2）；容器执行面内 git 读是有意降级——预期失败
形态必须可辨（D2：`fatal: not a git repository`，不许被读成「树坏了」，宿主 260913 沙箱事故同型误判教训）。

依据：工单验收 E ＋ 红线 2 ＋ 方案 gen1 D1/D2/D6（review gen0 R7：多仓清单真源
多仓清单真源路径（见引擎 `agent_activities.MULTI_MANIFEST_REL`）——清单**生成/解析**面归实现段 L1 与真票 e2e，本条锁
「容器面写入 + 按树落盘」的终态）。

high-level steps：两棵成员仓（各自真主仓+真注册 worktree，挂在泳道根下）→ 引擎 spawn
链直调（SANDBAR_AGENT_RUNTIME=docker，泳道=容器工作区）→ 容器内对根/树A/树B 各写一文件
→ 宿主断言：文件在、属主=worker uid → docker inspect 断言挂载面=仅泳道根 → 容器内
git status 断言预期失败形态 → 宿主逐树直调 settle 断言 commit 落到各成员泳道分支。

三态：PASS 0 / FAIL 1 / ENV_FAIL 2。实现段落地前容器面红属预期（TDD 验收棒）；
arbitrate/merge 期必须绿。engine 池（宽 1）。
"""
import asyncio
import inspect
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lib_container_case as F  # noqa: E402

C = F.Checker("t260913-04-scenario-4-multirepo")
TICKET = F.uniq("t260913-04-itest-multi")


def slice_env(tmp, stub):
    env = dict(os.environ)
    env["SANDBAR_TARGET_HOST"] = "127.0.0.1:1"
    env["SANDBAR_NAMESPACE"] = "sandbar-itest-multi"
    env["SANDBAR_AGENT_STUB"] = "0"
    env["SANDBAR_AGENT_RESUME"] = "0"
    env[F.RUNTIME_ENV] = "docker"
    env["SANDBAR_AGENT_CMD"] = str(stub)
    env["DSH_HOME"] = str(tmp / "dsh-home")
    Path(env["DSH_HOME"]).mkdir(parents=True, exist_ok=True)
    return env


def run_slice(aa, lane, mode_env):
    old = dict(os.environ)
    os.environ.clear()
    os.environ.update(mode_env)
    try:
        import importlib
        aa = importlib.reload(aa)   # DSH_CMD 等 import 期常量按本 slice env 重取
        A = getattr(aa, "AgentStageArgs", None)
        if A is None:
            import shared
            A = sys.modules["shared"].AgentStageArgs
        args = A(ticket_id=TICKET, stage_id="implement", role="developer",
                 prompt="（多仓桩）写结果文件后退出。",
                 workspace={"path": str(lane), "type": "dir"},
                 result_file=str(lane / ".sandbar" / "stage_implement_gen0.json"),
                 log_file=str(lane / ".sandbar" / "agent_stub.log"),
                 gen=0, max_polls=2, workflow_id="dev-lane")
        try:
            return asyncio.run(aa._run_agent_stage_impl(args)), None
        except Exception as e:  # noqa: BLE001
            return None, "%s: %s" % (type(e).__name__, str(e)[:200])
    finally:
        os.environ.clear()
        os.environ.update(old)


def main():
    F.require_docker(C)
    tag = F.agent_image_tag(C)
    aa = F.load_engine(C)

    tmp = Path(tempfile.mkdtemp(prefix="t26091304-multi-"))
    name = F.CONTAINER_FMT % TICKET
    try:
        # 成员仓 A/B：各自真主仓 + 真注册 worktree（泳道根下）
        lane = tmp / "lane"
        lane.mkdir(parents=True, exist_ok=True)
        members = {}
        for m in ("alpha", "beta"):
            mmain = F.mk_repo(tmp / ("main-" + m),
                              files={"%s/keep.py" % m: "# %s\n" % m})
            mtree = lane / m
            r = F.sh("git", "-C", mmain, "worktree", "add", "-q",
                     "-b", "lane/%s-%s" % (TICKET, m), mtree)
            if r.returncode != 0:
                C.check(False, "成员 worktree 搭建失败（夹具问题）：%s" % r.stderr[:120])
                C.finish()
                return
            members[m] = (mmain, mtree)
        stub = F.write_stub(lane, "instant", lane / ".sandbar" / "spy-multi.log")

        print("\n== 容器内对根+两棵成员树写入 ==")
        run_slice(aa, lane, slice_env(tmp, stub))
        r = F.sh("docker", "inspect", "--format", "{{.State.Running}}", name, timeout=30)
        MARKS = (("root", ""), ("alpha", "alpha"), ("beta", "beta"))   # (标记, 树相对位)
        if r.stdout.strip() != "true":
            C.check(False, "容器未在跑（容器面未接线，实现段落地前红属预期）",
                    "err=%s" % r.stderr[:120])
        else:
            for mark, rel in MARKS:
                tgt = str(lane / rel) if rel else str(lane)
                fname = "proof-%s.txt" % mark
                p = F.exec_in(name, "sh", "-c",
                              "echo %s > %s/%s" % (mark, tgt, fname), timeout=30)
                C.check(p.returncode == 0, "容器内写入 %s/%s" % (tgt, fname),
                        "err=%s" % p.stderr[:120])
        print("\n== 宿主面：文件可见 + 属主=worker uid ==")
        for mark, rel in MARKS:
            p = (lane / rel if rel else lane) / ("proof-%s.txt" % mark)
            body = p.read_text(encoding="utf-8").strip() if p.exists() else ""
            C.check(p.exists() and body == mark,
                    "宿主可见 %s（内容=%s）" % (p, mark), "exists=%s body=%r" % (p.exists(), body))
            if p.exists():
                C.check(p.stat().st_uid == os.getuid(),
                        "属主=worker uid（容器内新建可被宿主 git 收编，验收 D/E）",
                        "uid=%s" % p.stat().st_uid)

        print("\n== 挂载面：仅泳道根（成员主树不进容器，红线 2）==")
        insp = F.sh("docker", "inspect", name, timeout=30)
        if insp.returncode == 0:
            import json as _json
            mounts = _json.loads(insp.stdout)[0].get("Mounts", []) or []
            srcs = sorted({m.get("Source", "") for m in mounts if m.get("Source")})
            C.check(srcs == [str(lane)] or all(s == str(lane) for s in srcs),
                    "inspect Mounts 源=仅泳道根", "srcs=%s" % srcs)
            C.check(all(not s.startswith(str(tmp / "main-")) for s in srcs),
                    "成员仓主树零暴露")
        else:
            C.na("容器不在场，inspect 挂载面无可验对象（容器面未接线的伴生子用例）")

        print("\n== git 读降级：预期失败形态可辨（D2）==")
        for m in ("alpha", "beta"):
            p = F.exec_in(name, "git", "-C", str(lane / m), "status", timeout=30)
            if p.returncode == 0 and "not a git repository" not in (p.stderr or ""):
                C.check(False, "容器内 git 意外可用（超出 D2 声明面，需 review 重裁定）",
                        "out=%s" % (p.stdout + p.stderr)[:120])
            else:
                C.check("fatal: not a git repository" in (p.stderr or ""),
                        "容器内 git status 呈预期失败形态（%s 树）" % m,
                        "stderr=%s" % (p.stderr or "")[:120])

        print("\n== 按树落盘：settle 直调（验收 E 的 commit 面）==")
        import subprocess as _sp
        for m in ("alpha", "beta"):
            mmain, mtree = members[m]
            fname = "proof-%s.txt" % m
            _kw = dict(repo=mmain, write_set=[fname], path_gate=False)
            try:  # t260916-19 D：face 必填分层标签——新老树两侧可跑（c184e62 同款）
                if "face" in inspect.signature(aa._settle_worktree_lane).parameters:
                    _kw["face"] = "agent"
            except (TypeError, ValueError):
                pass
            note = aa._settle_worktree_lane(mtree, TICKET, "implement", 0, **_kw)
            branch = "lane/%s-%s" % (TICKET, m)
            sha = _sp.run(["git", "-C", str(mmain), "log", "-1", "--format=%H", branch],
                          capture_output=True, text=True).stdout.strip()
            files = _sp.run(["git", "-C", str(mmain), "show", "--name-only",
                             "--format=", sha],
                            capture_output=True, text=True).stdout if sha else ""
            C.check(fname in files,
                    "%s 树的容器内改动落成成员泳道分支 commit" % m,
                    "note=%s sha=%s files=%r" % (str(note)[:70], sha[:8], files.strip()[:80]))
    finally:
        F.sh("docker", "rm", "-f", name, timeout=60)
        left = F.containers_by_label(F.LABEL_TICKET, TICKET)
        C.check(not left, "清理零残留（验收 G）", "left=%s" % left)
        shutil.rmtree(tmp, ignore_errors=True)

    C.finish()


if __name__ == "__main__":
    main()
