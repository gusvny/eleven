#!/usr/bin/env python3
"""t02_source_locks.py —— KI-009 修复结构源码锁（t260901-25）。

用户故事：自愈与 drain 是两条「出问题就是静默越权 / 静默孤儿」的机制，
它们的关键结构必须钉在真源上，防止后续重构悄悄退化回 KI-009 的
人工 commit 死路（红灯照旧、迟写照旧）。

锁点（方案 v2 测试节 2，全部对真源 agent_activities.py 断言）：
  - 自愈 settle 调用位于 item 1「泳道有 commit」之前（自愈前置）；
  - MERGE_HEAD 护栏/自检在 merge_check 内（消解期收口权不旁落）；
  - 自愈 settle 调用包 try 转红不抛（保 merge_check「红灯不抛」语义）；
  - detail 带 [auto-settle] 标记（账面可见不静默）；
  - merge_check 脏清单解析用 --porcelain -z（quotePath/rename 无歧义）；
  - _reap_agent_proc 已定义，且在三处结果就绪路径 settle 之前 + finally 兜底；
  - spawn 带 start_new_session=True、按进程组 killpg（孙进程树一并收）。

直跑：python3 integration/t260901-25/t02_source_locks.py
末行 SUMMARY pass=<n> fail=<k>；fail>0 exit 1。
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
SRC = REPO / "server" / "engine" / "agent_activities.py"

PASS = 0
FAIL = 0


def ok(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ok  %s" % label)
    else:
        FAIL += 1
        print("  FAIL %s" % label)


def fn_body(text, header):
    """取从 header 起到下一个顶层 def/async def（或文末）的函数体源码。"""
    i = text.find(header)
    if i < 0:
        return ""
    m = re.search(r"\n(?:async )?def \w", text[i + len(header):])
    return text[i: i + len(header) + (m.start() + 1 if m else len(text))]


def _code_view(body):
    """把注释内容抹成空格（**保偏移**）后的源码视图——本锁的计数与位置断言都跑在它上面。

    目的=**守卫判据不许被注释里的字样满足**（守的是代码，不是文档）。261001 integration 复核
    时实测：当前真源里三个段体各有 **3 处真 reap 调用**（结果就绪 / 进程已退出分支 / finally
    兜底），而注释里的字样**并没有**额外凑数（原文匹配 3 = 抹注释后 3），所以这次是**防御性
    加固**：今天不改变任何判定，但往后有人在注释里写 `proc.reap(...)` 也不会变成「守卫已接线」。
    只抹 `#` 之后的部分，**不改字节数、不改行序**，因此偏移与原文一一对应。

    同批复核到的一条**真实弱点**（本函数不解决，登记在案）：判据是 `len(reap) >= 2`，而旧结构
    每体有 3 处调用 ⇒ **删掉其中一处仍绿**（实测：删一处 exit=0）。可删窗口是阈值与调用点数的
    关系，不是注释造成的；阈值不许收紧到 3——新结构（改走共享 helper）下每个段体只有 1 处
    调用、helper 体 2 处，锚在 helper 上恰是 2，收紧即假红。"""
    out = []
    for ln in body.splitlines(keepends=True):
        i = ln.find("#")
        out.append((ln[:i] + "\n") if i >= 0 else ln)
    return "".join(out)


def resolve_body(text, header):
    """t260916-29：长活动外包了 worker_termination_guard 薄壳（worker 停机取消归因），
    spawn/reap 本体移到 _<name>_body——本锁跟随薄壳找本体（壳无 spawn/reap 面），
    锁语义不变。"""
    body = fn_body(text, header)
    if body and "worker_termination_guard" in body:
        name = header.split("def ", 1)[1]
        inner = fn_body(text, "async def _%s_body" % name)
        if inner:
            return inner
    return body


def main():
    text = SRC.read_text("utf-8")
    # t260913-04（agent 执行面容器化）：三处 spawn/reap 的实现形态迁入传输层
    # agent_runtime.py（agent_runtime.spawn_agent / AgentProc.reap），KI-009 语义不变。
    # 本锁按「兼容双形态」扩锚：旧=真源内直 Popen+_reap_agent_proc；新=经传输层。
    # 锁语义不锁形态；共享守卫锚点更新随 t260913-04 交付，merge 侧复核。
    RUNTIME_SRC = REPO / "server" / "engine" / "agent_runtime.py"
    text_runtime = RUNTIME_SRC.read_text("utf-8") if RUNTIME_SRC.exists() else ""

    print("== 前置 ==")
    ok("_dirty_within_write_set" in text and "_dirty_files_from_status_z" in text,
       "自愈纯函数已在真源定义")
    ok("def _reap_agent_proc" in text, "_reap_agent_proc 已在真源定义")

    print("== merge_check 自愈段（①写集内自愈） ==")
    # t260907-06 票B 逐树重构：自愈段语义锚迁入 _merge_check_one_scope——
    # 并集定位（锁语义不锁实现位置）。
    # t260921-09 三态化：item 1 的 git log 判定再迁入 _lane_commits_check_item——
    # 并集定位随之并入该函数；拼接顺序保持「自愈段在前、item 1 git log 在后」，
    # 时序断言（自愈 settle 先于 item 1）语义不变。
    mc = (fn_body(text, "async def merge_check") + "\n"
          + fn_body(text, "async def _merge_check_one_scope") + "\n"
          + fn_body(text, "def _lane_commits_check_item"))
    ok(bool(mc), "merge_check 函数体可定位")
    if mc:
        auto_idx = mc.find("[auto-settle]")
        item1_idx = mc.find('"log", "--oneline"')
        ok(auto_idx >= 0, "merge_check detail 带 [auto-settle] 标记（账面可见）")
        ok(item1_idx >= 0, "item 1 git log 检查点可定位")
        settle_calls = [m.start() for m in re.finditer(r"_settle_worktree_lane\(", mc)]
        if auto_idx >= 0 and item1_idx >= 0 and settle_calls:
            ok(min(settle_calls) < item1_idx,
               "自愈 settle 调用先于 item 1（自愈前置，时序洞不复活）")
            seg = mc[:item1_idx]
            ok("try" in seg and "except" in seg,
               "自愈 settle 调用包 try/except（红灯不抛语义不变）")
        ok("MERGE_HEAD" in mc, "merge_check 内有 MERGE_HEAD 消解期护栏/自检")
        ok("--porcelain" in mc and re.search(r"['\"]-z['\"]", mc),
           "脏清单解析用 --porcelain -z")

    print("== drain 压竞态窗（②terminate 后组粒度回收） ==")
    # t260913-04：组隔离实现可留真源（host 直跑）也可迁传输层（agent_runtime）。
    ok("start_new_session=True" in text or "start_new_session=True" in text_runtime,
       "spawn 改 start_new_session=True（进程组隔离）")
    ok("os.killpg" in text or "os.killpg" in text_runtime,
       "按进程组 killpg 回收（孙进程树一并收）")
    ok("agent_runtime.spawn_agent(" in text or "subprocess.Popen" in text,
       "三处 agent spawn 经统一入口（传输层或真源直跑）")
    for header, has_settle in (
            ("async def _run_agent_stage_impl", True),
            ("async def arbitrate", True),
            ("async def acceptance_walkthrough", False)):
        body = resolve_body(text, header)
        if not body:
            ok(False, "%s：函数体不可定位" % header)
            continue
        # t261001-03（轮询循环三副本抽成共享 helper）：rc 分支前置 reap 与 finally
        # 兜底 reap 搬进共享 helper `_wait_for_agent_result`——站体改走 helper（恰一份
        # 实现），reap 锚就核到 helper 体上。锁**意图不变**：结果就绪路径 reap +
        # finally 兜底 reap 两处在位。
        # 为什么写成**双形态容忍**而不是硬要求 helper：这次改动横跨写集边界——重构在
        # `server/engine/`（票的写集内），而本脚本在 `integration/`（写集外，越权守卫会
        # 把它回滚，留档 .sandbar/quarantine/unauth-implement-gen1）。两半必须**原子**落地
        # （只上锁=main 立刻红；只上重构=锁红），所以锁必须两态都绿：旧结构核站体、
        # 新结构核 helper；接线形态 0/1 之外（多份实现 / 有 helper 无接线）一律红。
        # 锚是语义面（两处 reap 在位 + 单份实现），不是书写形态（KI-166 同纪律）。
        routed = body.count("await _wait_for_agent_result(")
        helper = fn_body(text, "async def _wait_for_agent_result")
        ok(routed <= 1 and (routed == 0 or bool(helper)),
           "%s：轮询循环接线形态唯一（0=旧三副本结构／1=共享 helper；多份实现或 helper 缺席=红）"
           % header)
        # 计数与位置都在**抹掉注释**的视图上做（见 `_code_view`）：注释里的字样不许满足守卫判据。
        body_code = _code_view(body)
        anchor = _code_view(helper) if (routed == 1 and helper) else body_code
        # reap 形态双锚：旧=真源直调 _reap_agent_proc(；新=AgentProc.reap(
        reap = [m.start() for m in re.finditer(r"_reap_agent_proc\(|proc\.reap\(", anchor)]
        settle = [m.start() for m in re.finditer(r"_settle_worktree_lane\(", body_code)]
        ok(len(reap) >= 2, "%s：reap 接入结果就绪路径 + finally 兜底" % header)
        if has_settle and settle:
            # 精确口径：spawn 之前的 settle 是幂等直读（缓存命中，无存活 agent，
            # 不需 reap）——豁免；spawn 之后每处 settle 前必须有 reap。
            spawn_at = [x for x in (body_code.find("subprocess.Popen"),
                                    body_code.find("agent_runtime.spawn_agent(")) if x >= 0]
            popen = min(spawn_at) if spawn_at else -1
            prev = popen
            bad = []
            for s in settle:
                if s <= popen:
                    continue  # Popen 前的 settle=幂等直读缓存路径，豁免
                if not any(prev < r < s for r in reap):
                    bad.append(s)
                prev = s
            ok(not bad,
               "%s：Popen 后每处 settle 之前都有 reap（缓存路径豁免）" % header)

    print("SUMMARY pass=%d fail=%d" % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
