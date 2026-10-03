#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sweep_tmp_fixtures — 一次性、可复核的「测试夹具临时物料」清扫器（宿主令 260926／260927）。

背景：`$TMPDIR` 顶层实测 407,294 个目录，其中 401,578 个 >6 小时未动（98.6%）——大头是
各测试面 `mkdtemp` 出来的夹具（`integ-e2e-fixture-*` 1,086 个 / ~391GB、`t260907-06-ut-*`
1.7 万、`sandbar-agent-presets-*` 2 万……）。生产者侧已逐个修（见同日各票：注册表 +
退出钩子 + 拆台回收），本脚本是**存量止血**与「SIGKILL 类终态」的兜底网。

判据（两条同时满足才删，缺一不删）：
  ① 顶层条目名以**白名单前缀**开头（TMP_FIXTURE_PREFIXES；白名单之外一律不碰——
     宿主 temp 目录里可能有别的程序的东西）；
  ② 该条目 `mtime` 距今 ≥ `--max-age-h`（缺省 6 小时；年龄不足的一律不碰，可能在跑）。
另按**条目类型**分流（260927 全族清扫新增）：
  - 真目录 → `rmtree`；**常规文件** → `unlink`（锁档 `*-integ-run-*.lock`、影子
    `sandbar-admin-log-*.log`、凭据副本 `sandbar-credentials-*.yaml` 都是**文件**族，
    上一轮「只碰真目录」把它们整族漏掉了）；
  - 符号链接 / FIFO / socket 等一律跳过（`rmtree` 跟符号链接会删错东西）——逐条点名；
  - **在用即不动**（260927 新增的第三条文件族判据）：删文件前先试 `flock(LOCK_EX|LOCK_NB)`
    ——抢得到 = 没人持有 = 可删；抢不到 = 有活进程正握着这把锁 = **保留并点名**
    （绝不删活锁档；无 `fcntl` 的平台跳过该判据并留痕）；
  - **活载体即不动**（261001 新增，自递归风暴的机械网）：越龄白名单条目里若还有**活进程**
    的 cwd 落在其中，该条目**保留、逐条点名**；`--kill-carriers` 才先收进程再删。
    判据按 **cwd** 判而不是按命令行（风暴里那些进程的 args 是相对路径，按名字杀一律打偏）；
    探测面（`pgrep`/`lsof`）缺席时**具名留痕**，绝不当「没有载体」——「扫不到」与「没有」
    是两件事，混同会给出「机器干净」的假结论。
  - `EXCLUDED_PREFIXES` 里的族**永不参与**（别的程序的/别的项目的，如
    `com.google.Chrome.*`；以及 dsh 运行时自己的 spill 目录）——判据里**排除优先**，
    且在报告里逐族计数可见（不静默、也不误删）。

安全：默认 dry-run（只报数不删），`--apply` 才删；`--apply` 的年龄闸有 1 小时硬地板
（拒绝更激进的取值）。日志一行一动作，失败逐条点名。

用法（cwd=仓库根）：
  python3 integration/tools/sweep_tmp_fixtures.py                  # dry-run：各前缀命中数 + 占用估算
  python3 integration/tools/sweep_tmp_fixtures.py --json           # 机器可读
  nohup python3 integration/tools/sweep_tmp_fixtures.py --apply \
        > /tmp/sweep-tmp-fixtures.log 2>&1 &                       # 真删（宿主已明确要清）

摘要行（两种模式同形，dry-run 带 DRY-RUN 前缀）：
  swept N (dirs D / files F) | kept M live | failed X | locks kept L | freed≈Y
其中 `freed≈Y` 是**估算**（目录族：每前缀最多 `--sample` 个实测平均 × 命中数；文件族：
实删文件的实际字节累计）——估算值只进报告，**绝不参与「删不删」的判据**。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections import namedtuple

#: 白名单里的条目形态（`kind` = "dir" | "file"）
FixtureEntry = namedtuple("FixtureEntry", "name mtime kind")

#: 已知测试夹具前缀白名单（真源之一；另一份在 server/engine/inspection_lane_watchdog.py
#: 的 TMP_FIXTURE_PREFIXES——两处一致性由机械漂移锁钉住
#: server/engine/tests/test_t260926_tmp_fixture_water.py::test_f1_prefix_whitelist_single_source）。
#: 本脚本**不 import 引擎包**：清扫器要在引擎装不上/被改坏的机器上也能跑（止血优先）。
#: 260927 全族整治：第二批（原先只登记在 `CANDIDATE_PREFIXES_BATCH2` 里、**未启用**——
#: 「登记了但没启用」这种半态本身就是陷阱：上一轮就是漏了 `t260907-12-act-/-ch-` 两个
#: 变体，存量又攒了 6,399 个）已**正式并入本表**，不再有「候选」态。逐条证据=260927
#: 只读普查（前缀 / 顶层条目数 / 最老年龄 / 生产者 file:line）：
TMP_FIXTURE_PREFIXES = (
    # ---- 第一批（260926 启用；`venv-compat-root` 260927 并入更宽的 `venv-compat-`）----
    "integ-e2e-fixture-",     # integration 场景夹具（ticket-lifecycle-scenes.mjs）
    "lint-pyc-",              # integration/lint_tests.py 的 pyc 暂存（atexit 回收已加）
    "fix10-", "fix14-", "fix17-",   # integration/t26* 各票 .mjs 夹具
    "pathgate-",              # t260911-03 pathgate 场景夹具
    "t260907-06-ut-",         # server/engine/tests/test_multirepo_anchor.py（已修）
    "t260907-12-ut",          # 同上 :276-362 的 -ut* 变体族（已修）
    "sandbar-agent-presets-",  # integration/stage_docker.py 起的台（agent preset 物化，已修）
    "t26092212-", "t260906-", "lease-ut-", "t260904-02-", "t260901-21-",
    "t02-lane", "t26090704-lane",
    "wb-",
    # ---- 第二批（260927 启用；逐条 = 命中数 / 最老 / 生产者 file:line）----
    "t260907-12-act-",        #  4,259  245h  server/engine/tests/test_multirepo_root_activity.py:51（已修；-ut 盖不住本变体）
    "t260907-12-ch",          #  2,140  245h  同上 :125/:136（-ch-/-ch1- 同族）
    "sandbar-admin-log-",     #  2,854  265h  integration/stage_docker.py:1332（**文件**；两条拆台路径已回收）
    "sandbar-credentials-",   #  2,519  112h  同上 :1333（**文件**；凭据副本留在 $TMPDIR 属卫生面欠账）
    "sandbar-integ-run-",     #  2,820  204h  integration/run_scenarios.py 的 `_run_lock_path`（**文件** 单飞锁档；260927 已修）
    "nusuyou-integ-run-",     #  1,836  106h  同款锁档的旧前缀——生产者在**姊妹项目**的同一份 runner（naming-compat）
                              #               （~/Documents/nusuyou/integration/run_scenarios.py:182），本仓修不到；
                              #               存量由本表清（0 条 <6h = 已无新产）
    "venv-compat-",           #  4,814  346h  integration/t260907-10/sc_engine_venv_compat.py:56-58（root+home 两族；260927 已修，原表只覆盖 -root）
    "t26092114-",             #  8,115  132h  integration/t260921-14/lib_t26092114.py:131/156
    "t26090704-lock",         #  3,251  245h  integration/t260907-04/sc_dispatcher_lock_fallback.py:35
    "t260904-18-mg",          #  3,257  245h  integration/t260904-18/lib_t260904_18.py:153
    "t260910-10-",            #  5,785  346h  integration/t260910-10/{sc_docs_project_anchor.mjs:111, sc_docs_ui_mock_v1.mjs:121-122}
    "t090506-",               #  3,230  346h  integration/t260905-06/sc_doc_{read_through,entry_present}.mjs
    "t260904-13-itest",       #  1,900  245h  integration/t260904-13/lib_ki044.py:47
    "sandbar-t26091202-",     #     35  321h  integration/t260912-02/lib_lifecycle_case.py:564（目录 + 文件混族）
    "detailred-e2e-",         #  1,568  292h  integration/t260915-01/tests/sc_detail_red_refusal_receipt.py:76
    "sandbar-reg-",           #  1,529  305h  server/plugins/workbench/tests/registry-loader.mjs:47（JS 侧，零回收动词）
    "t260915-10-",            #  2,204  285h  integration/t260915-10/sc_docs_follow_project.mjs:87-88
    "t26092404-",             #  2,123   64h  integration/t260924-04/sc_project_template_{journey,gate}.py
    # ---- 第三批（t261002-13 增补：t* 直方图 top 族的白名单缺口——逐条 = 命中数 / 生产者 file:line）----
    "t260924-04-",            # 10,037  server/engine/tests/test_t260924_04_project_templates.py:78（261002-13 已修；
                              #               巡检套件日跑，10k 存量主要来自它——261002 普查时误并入 t26092404- 桶）
    # ---- 第三批续（t261002-13：短前缀尾族——生产者已点名；workbench .mjs 在写集外，清扫器兜底）----
    "t01-",                   #  1,928  integration/t260902-02/t01_archive_paths.py:67（261002-13 已修）
    "t02-sb-",                #  1,157  integration/t260902-02/sc_t02_archive_ticket.py:50（261002-13 已修）
    "t03-",                   #  2,323  integration/t260902-02/sc_t03_merge_teardown.py:95（tag 变体 -old/-defer；261002-13 已修）
    "t04-sb-",                #  1,157  integration/t260902-02/sc_t04_prune_archive_legacy.py:87（261002-13 已修）
    "t08-guard-",             #  1,982  integration/t260905-08/sc_wb_contrast_guard.mjs（.mjs freshDir，写集外→清扫器兜底）
    "t09-",                   #  3,492  server/plugins/workbench/tests/*.mjs freshDir（t09-{bump,donut,fast,kpi,pri}；写集外→清扫器兜底）
    "t25-t03-",               #  1,130  integration/t260901-25/t03_reap_process_group.py:122（261002-13 已修）
    "t26092523-",             #  4,599  integration/t260925-23/tests/sc_template_pathgate_{load_contract.py:134-189,faces.py:48}（261002-13 已修：mkdtemp_reclaimed）
    "t260901-14-",            #  3,477  server/engine/tests/test_t260901_14_registry_loader.py:34-65（261002-13 已修：mkdtemp_reclaimed）
    "t260908-02-",            #  1,982  server/engine/tests/test_t260908_02_payload_roundtrip.py:55/:66（261002-13 已修；
                              #               原 "t260908-02-ut" 盖不住同文件 :67 的 -sg 变体——实测 653 条只因变体漏网）
    "t26091004-sc-",          #      3  4.6h  integration/t260910-04/sc_console_paused_list.mjs:200（**261001 载体风暴的巢**：
                              #               场景被 900s 执行器帽杀 → `finally` 的 rmSync 没跑 → 树 + 台内后代进程
                              #               一起活过收口；2.5h 后那片冻结代码（克隆自修前的 main）重跑闸，
                              #               自递归风暴。实测 3 条存量 / 最老 4.6h / ≈849MB）
    # 各期场景自建夹具族（前缀形态 = 本仓票号命名空间；有实命中的三条在前，其余为前瞻覆盖）
    "t260923-",               #    168    5h  integration/t260923-01 族场景夹具
    "t260925-",               #  1,053   55h  integration/t260925-* 族场景夹具
    "t260916-",               #  1,256  112h  integration/t260916-15/sc_sidebar_merged_sort_ui.mjs:52
    "t260922-", "t260921-", "t260917-", "t260918-", "t260919-", "t260920-",
)

#: 第二批并入的前缀快照（**只作留证与回归锁**：它是 `TMP_FIXTURE_PREFIXES` 的子集，
#: 由 `server/engine/tests/test_t260927_tmp_fixture_family.py` 钉住「真已启用」；
#: 不是第二份可独立增删的清单——白名单真源只有上面那一个）。
BATCH2_MERGED_PREFIXES = (
    "t260907-12-act-", "t260907-12-ch", "sandbar-admin-log-", "sandbar-credentials-",
    "sandbar-integ-run-", "nusuyou-integ-run-", "venv-compat-", "t26092114-",  # naming-compat（姊妹项目同款前缀，非退役旧名）
    "t26090704-lock", "t260904-18-mg", "t260910-10-", "t090506-",
    "t260904-13-itest", "sandbar-t26091202-", "detailred-e2e-", "sandbar-reg-",
    "t260915-10-", "t26092404-", "t260923-", "t260925-", "t260922-", "t260921-",
    "t260916-", "t260917-", "t260918-", "t260919-", "t260920-",
)

#: **明确排除**的族：判据里排除优先（连白名单计数都不进），永不删——逐条给理由，
#: 因为「不碰」本身也得是可复核的判定，而不是「恰好没写进白名单」的偶然：
EXCLUDED_PREFIXES = (
    "com.google.Chrome.",     # Chrome 自己的 profile 临时目录（宿主浏览器的东西）
    "com.apple.",             # 系统服务（triald / tipsd / avconferenced…）
    "BlobRegistryFiles",      # 系统/其它进程
    "playwright",             # 浏览器 profile / artifacts（不是本仓夹具族）
    "TemporaryItems", "TemporaryDirectory.",
    "vscode-git-",            # 编辑器 socket
    "docker_cli_",            # docker CLI socket
    "dsh-subprocess-",        # **dsh 运行时自己的 spill 目录**：@deepseek-ai/dsh-subprocess-local
                              # 的 `lib/runner-launch-*.js:683`（`defaultSpillDir ??=
                              # mkdtempSync(join(tmpdir(), "dsh-subprocess-"))`）。260926 普查把它
                              # 归成「本仓 dsh 子进程探针族」——**归因是错的**（本仓 grep 零命中）；
                              # 删活会话的 spill 目录 = 弄坏在飞的 agent 子进程，一律不碰。
    "dsh-spill-",             # 同族（dsh 侧的 spill 目录）
    "tmp",                    # BSD `mktemp` 缺省模板（`tmpXXXXXXXX`）：归因不到本仓，不碰
)

DEFAULT_MAX_AGE_H = 6.0
DEFAULT_SAMPLE = 10
DEFAULT_SAMPLE_BUDGET_S = 8.0
#: --apply 的年龄硬地板（小时）：比这更激进的取值一律拒（正在跑的夹具必须活着）
APPLY_MIN_AGE_H = 1.0
#: 报告里逐条点名的上限（失败/跳过/在册锁档各自截断，但计数不截断）
NAMED_CAP = 40


def human(n: float) -> str:
    """字节 → 人读（B/K/M/G/T，一位小数）。"""
    v = float(n)
    for unit in ("B", "K", "M", "G", "T", "P"):
        if v < 1024 or unit == "P":
            return ("%dB" % int(v)) if unit == "B" else ("%.1f%s" % (v, unit))
        v /= 1024.0
    return "%.1fP" % v


def age_h(now: float, mtime: float) -> float:
    return max(0.0, (now - mtime) / 3600.0)


def match_prefix(name: str, prefixes) -> str:
    """名称命中哪个前缀（按给定顺序取首个；无命中=空串）。扫描/分组/删除三处同一判据。"""
    for p in prefixes:
        if name.startswith(p):
            return p
    return ""


def scan(root: str, prefixes, max_age_h: float, now: float = None,
         excluded=EXCLUDED_PREFIXES):
    """扫 `root` 顶层一次（**唯一一次遍历**）：白名单命中的真目录/常规文件按年龄分桶。

    返回 dict：
      - `stale` / `live`：`[FixtureEntry]`（按名称排序，**删除顺序可复核**）；
      - `entries`（顶层条目总数）、`untouched`（白名单外）；
      - `excluded_by_prefix` / `excluded_count` / `excluded_named`（明确排除族：只可见、可删不着）；
      - `not_swept_named` / `not_swept`（符号链接、FIFO、stat 失败——逐条点名，绝不当 stale 删）。
    """
    now = time.time() if now is None else now
    stale, live, not_swept_named = [], [], []
    entries = untouched = 0
    locked = 0
    excluded_by_prefix = {p: 0 for p in excluded}
    excluded_named = []
    with os.scandir(root) as it:
        for ent in it:
            entries += 1
            name = ent.name
            ep = match_prefix(name, excluded)
            if ep:                       # 排除优先：明确排除的族永不参与（也不进白名单计数）
                excluded_by_prefix[ep] += 1
                if len(excluded_named) < 5:
                    excluded_named.append(name)
                continue
            if not match_prefix(name, prefixes):
                untouched += 1
                continue
            try:
                if ent.is_symlink():
                    # 符号链接：不碰（rmtree 跟链接会删到链接目标=别人的东西）
                    not_swept_named.append("%s (symlink — not followed)" % name)
                    continue
                if ent.is_dir(follow_symlinks=False):
                    kind = "dir"
                elif ent.is_file(follow_symlinks=False):
                    kind = "file"        # 文件族单独判定（锁档/影子/凭据副本）
                else:
                    not_swept_named.append("%s (not a real directory or regular file)" % name)
                    continue
                mtime = ent.stat(follow_symlinks=False).st_mtime
            except OSError as e:
                locked += 1
                not_swept_named.append("%s (stat failed: %s)" % (name, e))
                continue
            (stale if age_h(now, mtime) >= max_age_h else live).append(
                FixtureEntry(name, mtime, kind))
    stale.sort()
    live.sort()
    return {"entries": entries, "untouched": untouched, "stale": stale, "live": live,
            "not_swept_named": not_swept_named, "not_swept": locked,
            "excluded_by_prefix": excluded_by_prefix,
            "excluded_count": sum(excluded_by_prefix.values()),
            "excluded_named": excluded_named}


def by_prefix(items, prefixes):
    """[FixtureEntry] → {prefix: [items]}（按白名单顺序；同名多前缀取首个匹配，与 scan 同判据）。"""
    out = {p: [] for p in prefixes}
    for e in items:
        p = match_prefix(e.name, prefixes)
        if p:
            out[p].append(e)
    return out


def bounded_size(path: str, budget_s: float) -> tuple:
    """有界目录体积（不跟符号链接；预算用尽标 truncated）。返回 (bytes, truncated)。"""
    total = 0
    walked = 0
    deadline = time.monotonic() + budget_s
    stack = [path]
    truncated = False
    while stack:
        if time.monotonic() > deadline:
            truncated = True
            break
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for ent in it:
                    walked += 1
                    if walked > 200000:
                        truncated = True
                        stack = []
                        break
                    try:
                        if ent.is_symlink():
                            continue
                        if ent.is_dir(follow_symlinks=False):
                            stack.append(ent.path)
                        else:
                            total += ent.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total, truncated


def file_size(path: str) -> int:
    """常规文件字节（读不到算 0——估算面不猜，也绝不因此改判据）。"""
    try:
        return os.stat(path, follow_symlinks=False).st_size
    except OSError:
        return 0


def lock_held(path: str):
    """该文件是否正被某个进程 `flock` 持有？True/False；平台无 fcntl 或打不开=None（不判）。

    「在用即不动」的实现（文件族第三条判据）：先试着抢独占锁——抢得到 = 没人持有 =
    可以删；抢不到（EWOULDBLOCK）= 有活进程握着它（正是 `*-integ-run-*.lock` 的形态）
    = 保留并点名。`O_RDONLY` 打开即可 flock（不需要写权限），拿完立刻解锁。
    """
    try:
        import fcntl
    except ImportError:
        return None
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return None
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


def _all_pids():
    """全机 pid 列表（`pgrep -f .`）。取不到 → (None, 原因串)：**具名留痕，绝不静默当 0**。

    「扫不到」与「没有载体」是两件事：前者会让人以为机器干净（261001 风暴里正是这个幻觉
    让人以为收口了）。所以工具缺席一律把原因写进报告。
    """
    try:
        r = subprocess.run(["pgrep", "-f", "."], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        return None, "pgrep unavailable: %s: %s" % (type(e).__name__, e)
    if r.returncode not in (0, 1):
        return None, "pgrep exit=%d" % r.returncode
    pids = tuple(int(x) for x in r.stdout.split() if x.strip().isdigit())
    return pids, None


def _pid_cwd(pid: int):
    """该进程的 cwd（`lsof -a -p PID -d cwd -Fn`）；取不到=None（进程已死/无权限）。"""
    try:
        r = subprocess.run(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    for line in r.stdout.splitlines():
        if line.startswith("n"):
            return line[1:]
    return None


def live_carriers(root: str, entries):
    """越龄夹具条目里还活着的进程（**载体**）→ ({条目名: [pid…]}, 扫描面错误或 None)。

    为什么按 **cwd** 判、不按命令行：261001 自递归风暴里那些进程的 args 是**相对路径**
    （`integration/run_scenarios.py --only …`，cwd 落在夹具泳道目录里），所以「按名字杀」
    三轮都打偏——实测杀完还剩 156 个，且越杀越多（杀掉 worker 反而触发它自己的
    supervisor 重拉）。**判据 = cwd 落在 `root/<白名单条目>/` 之下**，这才与「这条夹具里
    是谁在跑」同义。

    扫描面只取**越龄条目**（调用方传进来的是 `scan()` 的 stale 集合）：鲜条目里的活进程是
    正常现场（场景/running 套件），报它只会把报告刷成噪音，判据就没人看了。

    返回的第二种情况（错误串非 None）= 探测面不可用：**报告里必须具名**，
    且此刻**不算「没有载体」**（宁可保守：条目按「可能有载体」处置）。
    """
    pids, err = _all_pids()
    if err or not pids:
        return {}, (err or "pgrep returned no pids (unexpected on a live machine)")
    # 两侧都按 realpath 归一后再比（t261002-13 仲裁实锤的失真点）：`--root` 是调用方
    # 给的字面路径（macOS 上 `tempfile.gettempdir()` 给 `/var/folders/...`），而 pid cwd
    # 报的是**已解析**路径（`/private/var/folders/...`）——字面对字面永远比不中，
    # 「活载体保留」这条安全轨就在 symlinked temp 根下整条失效（而且静默失效）。
    # 归一用 `realpath`：两侧同一种解析，`/var/...` 与 `/private/var/...` 折到同一条真路径；
    # 不存在的条目 realpath 也能给出规范化形态（cwd 不可能落在不存在的目录里，无误伤）。
    dirs = {}
    root_real = os.path.realpath(root)
    for e in entries:
        if e.kind == "dir":
            dirs[os.path.realpath(os.path.join(root_real, e.name)).rstrip("/") + os.sep] = e.name
    if not dirs:
        return {}, None
    hits = {}
    for pid in pids:
        cwd = _pid_cwd(pid)
        if not cwd:
            continue
        cwd_real = os.path.realpath(cwd)
        for prefix_path, name in dirs.items():
            if cwd_real == prefix_path[:-1] or cwd_real.startswith(prefix_path):
                hits.setdefault(name, []).append(pid)
                break
    return hits, None


def kill_carriers(pids, grace_s: float = 5.0):
    """TERM → 等 grace_s → KILL。返回 {"termed","killed","failed"}（逐条点名，不静默）。

    **只由 `--kill-carriers` 显式开启**：杀进程不属于「清扫临时物料」的缺省语义——
    白名单目录很容易正好是某个真在跑的套件的夹具，误杀就是把别人的跑打红。
    调用点必须已确认「条目越龄」（与删除判据同一条线）。
    """
    import signal as _signal
    res = {"termed": 0, "killed": 0, "failed": []}
    alive = []
    for pid in list(pids):
        try:
            os.kill(pid, _signal.SIGTERM)
            res["termed"] += 1
            alive.append(pid)
        except ProcessLookupError:
            continue
        except OSError as e:
            res["failed"].append("%d: TERM %s: %s" % (pid, type(e).__name__, e))
    deadline = time.monotonic() + grace_s
    while alive and time.monotonic() < deadline:
        time.sleep(0.2)
        alive = [p for p in alive if _pid_alive(p)]
    for pid in alive:
        try:
            os.kill(pid, _signal.SIGKILL)
            res["killed"] += 1
        except ProcessLookupError:
            pass
        except OSError as e:
            res["failed"].append("%d: KILL %s: %s" % (pid, type(e).__name__, e))
    return res


def _pid_alive(pid: int) -> bool:
    """liveness（`os.kill(pid, 0)`）：权限不允许时也算活着（保守——不假装杀掉了）。"""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return True


def estimate(root: str, per_prefix: dict, sample: int, budget_s: float):
    """每前缀采样估占用（目录族：最多 sample 个实测平均 × 命中数；文件族：实际字节求和）。

    返回 (per_prefix_rows, est_total_bytes, notes)。采样与估算是**观测**，删除判据只有
    「前缀 + 年龄（+ 文件在用即不动）」——估算值绝不参与「删不删」的决定。
    """
    rows = []
    est_total = 0.0
    notes = []
    now = time.time()
    for prefix, items in per_prefix.items():
        dirs = [e for e in items if e.kind == "dir"]
        files = [e for e in items if e.kind == "file"]
        if not items:
            rows.append({"prefix": prefix, "count": 0, "dirs": 0, "files": 0,
                         "oldest_h": 0.0, "est_bytes": 0, "sampled": 0,
                         "dir_avg_bytes": 0.0, "truncated": False})
            continue
        picks = dirs[:sample] if sample > 0 else []
        sizes = []
        truncated = False
        for e in picks:
            b, t = bounded_size(os.path.join(root, e.name), budget_s)
            sizes.append(b)
            truncated = truncated or t
        dir_avg = (sum(sizes) / float(len(sizes))) if sizes else 0.0
        if dirs and not sizes:
            notes.append("%s: no dir sample taken (dir estimate omitted)" % prefix)
        if truncated:
            notes.append("%s: dir size estimate truncated by the %ss budget (underestimate)"
                         % (prefix, budget_s))
        file_bytes = sum(file_size(os.path.join(root, e.name)) for e in files)
        est = dir_avg * len(dirs) + file_bytes
        est_total += est
        oldest = max(age_h(now, e.mtime) for e in items)
        rows.append({"prefix": prefix, "count": len(items), "dirs": len(dirs),
                     "files": len(files), "oldest_h": oldest, "est_bytes": est,
                     "sampled": len(sizes), "dir_avg_bytes": dir_avg,
                     "truncated": truncated})
    return rows, est_total, notes


def make_tree_writable(path: str) -> None:
    """把一棵树里的目录/文件补上写位（**只在常规删除失败时**走这条路）。

    为什么需要：fixture 里「只读形态」是常见被测面（260927 实况：`t260925-15-inst-*`
    的 `content/releases/v000001/` 是 `dr-xr-xr-x`——删它里面的文件需要父目录可写，
    `rmtree` 于是报 `PermissionError: entries.json`，21 个目录成了**永久残留**）。补权限
    只改 mode 位，不动内容、不碰树外任何东西；失败照旧逐条点名（不静默、不假装成功）。
    """
    for root, dirs, files in os.walk(path):
        for n in dirs + files:
            try:
                os.chmod(os.path.join(root, n), 0o700)
            except OSError:
                pass
        try:
            os.chmod(root, 0o700)
        except OSError:
            pass


def _delete(root: str, entry) -> int:
    """真删一个条目（目录 rmtree / 文件 unlink）→ 返回该条目字节数（失败上抛给调用点）。"""
    path = os.path.join(root, entry.name)
    if entry.kind == "file":
        n = file_size(path)
        os.unlink(path)
        return n
    try:
        shutil.rmtree(path)
    except PermissionError:
        make_tree_writable(path)      # 只读 fixture 形态：补写位后重试一次
        shutil.rmtree(path)
    return 0


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Sweep leaked test-fixture entries under $TMPDIR "
                                            "(dry-run by default; --apply deletes)")
    ap.add_argument("--apply", action="store_true",
                    help="actually delete (default = dry-run, report only)")
    ap.add_argument("--root", default=None, help="temp root (default: tempfile.gettempdir())")
    ap.add_argument("--max-age-h", type=float, default=DEFAULT_MAX_AGE_H,
                    help="delete only entries idle >= this many hours (default 6)")
    ap.add_argument("--prefix", action="append", default=None,
                    help="override the whitelist prefix (repeatable; default = built-in whitelist)")
    ap.add_argument("--sample", type=int, default=DEFAULT_SAMPLE,
                    help="dirs sampled per prefix for the size estimate (default 10)")
    ap.add_argument("--sample-budget-s", type=float, default=DEFAULT_SAMPLE_BUDGET_S,
                    help="per-dir size-walk budget in seconds (default 8)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--kill-carriers", action="store_true",
                    help="kill orphan processes whose cwd still lives inside an aged-out "
                         "whitelisted fixture entry, then sweep it (default = report only)")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.root or tempfile.gettempdir())
    # 空串前缀 = 形同没有前缀闸（`match_prefix` 对空串恒真）——一律剔除，宁严不松：
    # 剔除后若白名单为空，下面 `--apply` 的空白名单闸会拒收。
    prefixes = tuple(p for p in args.prefix if p) if args.prefix else TMP_FIXTURE_PREFIXES
    out = {"mode": "apply" if args.apply else "dry-run", "root": root,
           "max_age_h": args.max_age_h, "prefixes": list(prefixes)}
    log = (lambda m: print(m, file=sys.stderr, flush=True)) if args.json \
        else (lambda m: print(m, flush=True))

    def bail(msg, code=2):
        out["error"] = msg
        if args.json:
            print(json.dumps(out, ensure_ascii=False))
        else:
            print("REFUSED: " + msg)
        return code

    if not os.path.isdir(root):
        return bail("root is not a directory: %s" % root)
    if args.max_age_h <= 0:
        return bail("--max-age-h must be > 0 (a sweep without an age gate could kill a running suite)")
    if args.apply and args.max_age_h < APPLY_MIN_AGE_H:
        return bail("--apply with --max-age-h %s < hard floor %sh refused"
                    % (args.max_age_h, APPLY_MIN_AGE_H))
    if args.apply and not prefixes:
        return bail("whitelist is empty — refusing to sweep with no prefix gate")

    if not args.apply:
        log("DRY-RUN (nothing is deleted; pass --apply to delete)")
    log("root=%s max-age=%sh prefixes=%d" % (root, args.max_age_h, len(prefixes)))

    t0 = time.monotonic()
    sc = scan(root, prefixes, args.max_age_h)
    rows, est_total, notes = estimate(root, by_prefix(sc["stale"], prefixes), args.sample,
                                      args.sample_budget_s)
    live_rows = by_prefix(sc["live"], prefixes)
    n_dirs = sum(1 for e in sc["stale"] if e.kind == "dir")
    n_files = len(sc["stale"]) - n_dirs
    # 载体（第三条判据，261001 自递归风暴新增）：**越龄**夹具里还活着的进程。它们是
    # 「宿主点名的实报」的承载者——树是死的、进程是活的，按名字杀打不中，只有按 cwd 才认得出。
    carriers, carrier_err = live_carriers(root, sc["stale"])
    carriers_n = sum(len(v) for v in carriers.values())
    log("scanned %d top-level entries in %.1fs: %d whitelisted stale (>=%sh: %d dirs / %d files), "
        "%d whitelisted live, %d untouched (outside whitelist), %d not swept"
        % (sc["entries"], time.monotonic() - t0, len(sc["stale"]), args.max_age_h,
           n_dirs, n_files, len(sc["live"]), sc["untouched"], len(sc["not_swept_named"])))
    if carrier_err:
        log("CARRIER SCAN UNAVAILABLE: %s —— 这批条目按「可能有载体」处置（不当作没有）" % carrier_err)
    elif carriers:
        log("LIVE CARRIERS: %d process(es) inside %d aged-out fixture entr(ies) —— 条目按在册"
            "保留（不删）；这形态=生产者收口漏了后代进程（被 SIGKILL 掉的场景不跑 finally）"
            % (carriers_n, len(carriers)))
        for name in sorted(carriers)[:NAMED_CAP]:
            log("  carrier %s: %d pid(s) %s" % (name, len(carriers[name]),
                                                ",".join(str(p) for p in carriers[name][:8])))
        if len(carriers) > NAMED_CAP:
            log("  ... (%d more carrier entries suppressed; see the count)" % (len(carriers) - NAMED_CAP))
    for r in rows:
        live_n = len(live_rows.get(r["prefix"], []))
        log("  %-24s stale=%-7d (d=%-6d f=%-5d) live=%-5d oldest=%-8s est≈%s%s"
            % (r["prefix"], r["count"], r["dirs"], r["files"], live_n,
               ("%.1fh" % r["oldest_h"]) if r["count"] else "-",
               human(r["est_bytes"]) if r["count"] else "-",
               (" (from %d sampled)" % r["sampled"]) if r["dirs"] else ""))
    for n in notes:
        log("  note: %s" % n)
    if sc["excluded_count"]:
        log("excluded by policy (never swept): %d entries — %s"
            % (sc["excluded_count"],
               ", ".join("%s=%d" % (p, c) for p, c in sorted(sc["excluded_by_prefix"].items())
                         if c)))

    freed = 0.0
    failed, failed_named = 0, []
    done = 0
    done_dirs = done_files = 0
    locked_kept, locked_named = 0, []
    carriers_kept, carriers_killed, carriers_named, unverified_kept = 0, 0, [], 0
    if args.apply:
        # 目录族的实际释放量按「逐前缀实测平均 × 实删条数」重算（不直接抄全量估算）；
        # 文件族按实删字节累计（精确，无需采样）。
        dir_avg_by_prefix = {}
        for r in rows:
            if r["dirs"] and r["sampled"]:
                dir_avg_by_prefix[r["prefix"]] = r["dir_avg_bytes"]
        log("APPLY: deleting %d entries (>=%sh, whitelist only, live locks kept, "
            "carrier entries kept unless --kill-carriers) ..." % (len(sc["stale"]), args.max_age_h))
        for entry in sc["stale"]:
            p = match_prefix(entry.name, prefixes)
            if carrier_err and entry.kind == "dir":
                # 探测面不可用 = **不知道**有没有载体。不知道就不删目录（树里有活进程时删树
                # 只留更脏的半态）；文件族与目录的判据不同（活锁判据独立可查），照旧处置。
                unverified_kept += 1
                if len(carriers_named) < NAMED_CAP:
                    carriers_named.append("%s (carrier scan unavailable: %s)" % (entry.name, carrier_err))
                log("  KEPT %s (carrier scan unavailable — refusing to assume 'no carriers')"
                    % entry.name)
                continue
            if carriers.get(entry.name):
                pids = carriers[entry.name]
                if not args.kill_carriers:
                    # 有活载体的条目**不删**：删树不杀进程 = 留下更脏的半态（进程继续在
                    # 已被 unlink 的目录里跑，报告却显示「已清」）。这与文件族的活锁同一条纪律。
                    carriers_kept += 1
                    if len(carriers_named) < NAMED_CAP:
                        carriers_named.append("%s (%d live pid(s) %s; --kill-carriers to reap)"
                                              % (entry.name, len(pids),
                                                 ",".join(str(x) for x in pids[:8])))
                    log("  KEPT %s (%d live carrier pid(s); pass --kill-carriers to reap)"
                        % (entry.name, len(pids)))
                    continue
                kr = kill_carriers(pids)
                carriers_killed += kr["termed"]
                if kr["failed"]:
                    for m in kr["failed"][:NAMED_CAP]:
                        if len(failed_named) < NAMED_CAP:
                            failed_named.append("%s carrier reap failed: %s" % (entry.name, m))
                log("  REAPED %s carriers: termed=%d killed=%d failed=%d"
                    % (entry.name, kr["termed"], kr["killed"], len(kr["failed"])))
            if entry.kind == "file":
                held = lock_held(os.path.join(root, entry.name))
                if held is True:      # 在用的锁档绝不删（第三条文件族判据）
                    locked_kept += 1
                    if len(locked_named) < NAMED_CAP:
                        locked_named.append("%s (lock held by a live process)" % entry.name)
                    log("  KEPT %s (flock held by a live process)" % entry.name)
                    continue
            try:
                if entry.kind == "dir":
                    _delete(root, entry)
                    freed += dir_avg_by_prefix.get(p, 0.0)
                    done_dirs += 1
                else:
                    freed += _delete(root, entry)
                    done_files += 1
                done += 1
            except Exception as e:            # noqa: BLE001 —— 单条失败不中断全局清扫
                failed += 1
                if len(failed_named) < NAMED_CAP:
                    failed_named.append("%s: %s: %s" % (entry.name, type(e).__name__, e))
                elif len(failed_named) == NAMED_CAP:
                    failed_named.append("... (further failures suppressed; see the count)")
                log("  FAILED %s: %s: %s" % (entry.name, type(e).__name__, e))
            if done and done % 500 == 0:
                log("  progress: %d/%d deleted, %d failed, %.1fs elapsed, freed≈%s"
                    % (done, len(sc["stale"]), failed, time.monotonic() - t0, human(freed)))
    else:
        # dry-run：三个计数都是**候选**数（谁会被删；`kept live` 与 `locks kept` 另计）。
        # 有活载体的条目缺省**不删**（要 `--kill-carriers` 才动），所以候选里先摘掉它们——
        # 否则 dry-run 报「要删 N 条」而 apply 只删 N-M 条，报告与行为分叉。
        carriers_kept = len(carriers)
        if carrier_err:
            # 探测面不可用：目录族一律不算候选（不知道 ≠ 没有），文件族照旧
            unverified_kept = n_dirs
            carriers_kept = 0
            done = len(sc["stale"]) - n_dirs
            done_dirs, done_files = 0, n_files
        elif carriers_kept and not args.kill_carriers:
            done = len(sc["stale"]) - sum(1 for e in sc["stale"] if carriers.get(e.name))
            done_dirs, done_files = n_dirs, n_files
        else:
            done = len(sc["stale"])
            done_dirs, done_files = n_dirs, n_files
        freed = est_total

    summary = ("%sswept %d (dirs %d / files %d) | kept %d live | carriers %d in %d entr(ies) "
               "(reaped %d, kept %d, unverified %d) | failed %d | locks kept %d | freed≈%s"
               % ("" if args.apply else "DRY-RUN: ", done, done_dirs, done_files,
                  len(sc["live"]), carriers_n, len(carriers), carriers_killed, carriers_kept,
                  unverified_kept, failed, locked_kept, human(freed)))
    log(summary)
    log("done in %.1fs" % (time.monotonic() - t0))
    out.update({"entries": sc["entries"], "untouched": sc["untouched"],
                "swept": done, "swept_dirs": done_dirs, "swept_files": done_files,
                "candidate_dirs": n_dirs, "candidate_files": n_files,
                "kept_live": len(sc["live"]), "failed": failed,
                "failed_named": failed_named,
                "locks_kept": locked_kept, "locks_kept_named": locked_named,
                "carriers": {k: sorted(v) for k, v in carriers.items()},
                "carriers_count": carriers_n, "carriers_entries": len(carriers),
                "carriers_scan_error": carrier_err, "carriers_reaped": carriers_killed,
                "carriers_kept": carriers_kept, "carriers_unverified_kept": unverified_kept,
                "carriers_named": carriers_named,
                "kill_carriers": bool(args.kill_carriers),
                "freed_est_bytes": freed, "swept_is_estimate": not args.apply,
                "per_prefix": rows,
                "live_per_prefix": {p: len(v) for p, v in live_rows.items()},
                "excluded_by_prefix": {p: c for p, c in sc["excluded_by_prefix"].items() if c},
                "excluded_named": sc["excluded_named"],
                "not_swept_named": sc["not_swept_named"][:NAMED_CAP], "notes": notes,
                "summary": summary})
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
