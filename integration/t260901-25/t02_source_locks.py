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


def main():
    text = SRC.read_text("utf-8")

    print("== 前置 ==")
    ok("_dirty_within_write_set" in text and "_dirty_files_from_status_z" in text,
       "自愈纯函数已在真源定义")
    ok("def _reap_agent_proc" in text, "_reap_agent_proc 已在真源定义")

    print("== merge_check 自愈段（①写集内自愈） ==")
    # t260907-06 票B 逐树重构：自愈段语义锚迁入 _merge_check_one_scope——
    # 并集定位（锁语义不锁实现位置）。
    mc = (fn_body(text, "async def merge_check") + "\n"
          + fn_body(text, "async def _merge_check_one_scope"))
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
    ok("start_new_session=True" in text, "spawn 改 start_new_session=True（进程组隔离）")
    ok("os.killpg" in text, "按进程组 killpg 回收（孙进程树一并收）")
    for header, has_settle in (
            ("async def _run_agent_stage_impl", True),
            ("async def arbitrate", True),
            ("async def acceptance_walkthrough", False)):
        body = fn_body(text, header)
        if not body:
            ok(False, "%s：函数体不可定位" % header)
            continue
        reap = [m.start() for m in re.finditer(r"_reap_agent_proc\(", body)]
        settle = [m.start() for m in re.finditer(r"_settle_worktree_lane\(", body)]
        ok(len(reap) >= 2, "%s：reap 接入结果就绪路径 + finally 兜底" % header)
        if has_settle and settle:
            # 精确口径：Popen 之前的 settle 是幂等直读（缓存命中，无存活 agent，
            # 不需 reap）——豁免；Popen 之后每处 settle 前必须有 reap。
            popen = body.find("subprocess.Popen")
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
